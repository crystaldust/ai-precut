# -*- coding: utf-8 -*-
"""剪辑台 · 后台任务（GL-17）与短命令（GL-20）。

所有任务一律是子进程（打包版是 App 带 `--aicut-cli` 重启自己，见 pipeline/proc.py）：
  * 全局互斥：同时最多 MAX_ACTIVE_JOBS 个，再起直接 JobConflict（→ 409），不排队；
  * 可取消：子进程自成进程组，取消时 SIGTERM 整组（连同它拉起的 ffmpeg），宽限期后 SIGKILL；
  * 先校验后登记：未知任务不会留下幽灵 running；
  * 子进程 stdin 一律断开，任何 input() 都不能卡住界面；
  * 不留孤儿：剪辑台退出时 shutdown_all 停掉全部任务；剪辑台被强杀时，任务进程里的
    看门狗（proc.start_parent_watchdog）发现父进程没了就带着 ffmpeg 一起退出；
    运行中的任务记在配置目录的 job.marker 里，重启后若发现上次的任务还活着就拒绝再起新任务。
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from pipeline import proc, schema, secrets

JOB_COMMANDS = {"prepare": ["prepare"], "build": ["build"], "select": ["select"],
                "export": ["export"]}
TASK_LABELS = {"prepare": "处理素材", "build": "生成成片", "select": "重新选段",
               "export": "导出 Windows 剪映包"}
MAX_ACTIVE_JOBS = 1          # 重任务全局串行：ffmpeg / ASR 吃满资源，也避免重复计费
CANCEL_GRACE_S = 5.0         # SIGTERM 后等这么久仍未退出就 SIGKILL
SHORT_CMD_TIMEOUT_S = 60     # 短命令（新建项目等）的超时
ZIP_TITLE_MAX_CHARS = 60     # 片名在 zip 文件名里最多保留的字数（中文 3 字节/字，远低于 255 字节）
PUBLIC_FIELDS = ("status", "log", "exit", "task", "project")
MARKER_FILE = "job.marker"   # 配置目录下：当前运行中的任务（跨剪辑台实例 / 重启可见）
JOB_PROCESS_HINTS = ("aicut", "--aicut-cli")  # 判断 marker 里的 pid 还是不是我们的任务进程
HOMEBREW_BIN = "/opt/homebrew/bin"

UNKNOWN_TASK_MSG = "未知任务"
JOB_CONFLICT_MSG = "已有任务在运行：{project} · {task}。等它结束，或先取消它"
STALE_JOB_MSG = ("上次剪辑台退出时留下的任务还在后台运行：{project} · {task}（进程 {pid}）。"
                 "等它结束再试；急用的话在「活动监视器」里结束这个进程")
JOB_START_FAILED = "[错误] 无法启动任务：{exc}"
JOB_RUN_FAILED = "[错误] 任务异常中断：{exc}"
JOB_CANCEL_NOTE = "[取消] 正在停止任务…"
JOB_EXIT_NOTE = "[退出码] {code}"
SHORT_CMD_TIMEOUT_MSG = "[错误] 命令超时（{s} 秒没有完成），请重试"
SHORT_CMD_START_FAILED = "[错误] 无法执行命令：{exc}"
NO_TIMELINE_MSG = "这一版还没有时间线，先生成成片"

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

# 路径字符、控制字符，以及能把文件名显示成别的样子的零宽 / 双向控制字符
_UNSAFE_FILENAME = re.compile(
    r'[\\/:*?"<>|\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]')


class JobConflict(Exception):
    """已有任务在运行；job_id 指向正在跑的那个，界面可以「查看进行中的任务」。"""

    def __init__(self, job_id: str | None, project: str, task: str,
                 template: str = JOB_CONFLICT_MSG, **extra: object) -> None:
        super().__init__(template.format(project=project, task=TASK_LABELS.get(task, task),
                                         **extra))
        self.job_id, self.project, self.task = job_id, project, task


class StaleJob(JobConflict):
    """上次剪辑台留下的任务进程还活着（不在本进程的任务表里，界面没法查看 / 取消它）。"""

    def __init__(self, pid: int, project: str, task: str) -> None:
        super().__init__(None, project, task, STALE_JOB_MSG, pid=pid)


# ------------------------------------------------------------------ 子进程
def child_env() -> dict:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env[proc.PARENT_PID_ENV] = str(os.getpid())  # 任务进程的看门狗靠它发现剪辑台没了
    if not proc.FROZEN:  # 打包版必须优先用内置 ffmpeg，不能把 brew 的插到前面
        env["PATH"] = HOMEBREW_BIN + os.pathsep + env.get("PATH", "")
    return env


def job_command(task: str, name: str, extra: list[str]) -> list[str]:
    """测试替换点：真实环境下就是一条 aicut 子命令。"""
    return proc.cli_cmd([*JOB_COMMANDS[task], name, *extra])


def run_aicut(args: list[str]) -> tuple[int, str]:
    """执行一条短 aicut 命令（如 new）：一律子进程、stdin 断开、有超时（GL-17 / GL-20）。"""
    try:
        r = subprocess.run(proc.cli_cmd(args), cwd=str(proc.app_root()),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=SHORT_CMD_TIMEOUT_S, env=child_env())
    except subprocess.TimeoutExpired:
        return 1, SHORT_CMD_TIMEOUT_MSG.format(s=SHORT_CMD_TIMEOUT_S)
    except OSError as exc:
        return 1, SHORT_CMD_START_FAILED.format(exc=exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ------------------------------------------------------------------ 任务表
def _running_locked() -> list[str]:
    return [jid for jid, j in JOBS.items() if j["status"] == "running"]


def active_job(project: str | None = None) -> str | None:
    """正在跑的任务 id；给了 project 就只看这个项目的。"""
    with JOBS_LOCK:
        for jid in _running_locked():
            if project is None or JOBS[jid]["project"] == project:
                return jid
    return None


def project_job(project: str) -> dict | None:
    """这个项目正在跑的任务 {id, task}；没有则 None。"""
    job_id = active_job(project)
    if job_id is None:
        return None
    with JOBS_LOCK:
        return {"id": job_id, "task": JOBS[job_id]["task"]}


def job_view(job_id: str) -> dict | None:
    """给界面的任务快照：显式挑字段，绝不能把 Popen 序列化出去。"""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        view = {k: job[k] for k in PUBLIC_FIELDS}
        view["log"] = list(job["log"])
        return view


def start_job(name: str, task: str, extra: list[str] | None = None) -> str:
    if not isinstance(task, str) or task not in JOB_COMMANDS:  # 先校验再登记，不留幽灵 running
        raise ValueError(UNKNOWN_TASK_MSG)
    cmd = job_command(task, name, list(extra or []))
    with JOBS_LOCK:
        running = _running_locked()
        if len(running) >= MAX_ACTIVE_JOBS:
            busy = JOBS[running[0]]
            raise JobConflict(running[0], busy["project"], busy["task"])
        if not running and (stale := stale_job()) is not None:
            raise StaleJob(stale["pid"], stale.get("project", "?"), stale.get("task", "?"))
        job_id = uuid.uuid4().hex[:8]
        thread = threading.Thread(target=_run_job, args=(job_id, cmd), daemon=True,
                                  name=f"aicut-job-{job_id}")
        JOBS[job_id] = {"status": "running", "log": [], "exit": None, "started": time.time(),
                        "task": task, "project": name, "popen": None, "cancel": False,
                        "thread": thread}
    try:
        thread.start()
    except BaseException:
        with JOBS_LOCK:  # 线程没起来：撤销登记，释放互斥
            JOBS.pop(job_id, None)
        raise
    return job_id


def _run_job(job_id: str, cmd: list[str]) -> None:
    try:
        child = subprocess.Popen(
            cmd, cwd=str(proc.app_root()), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=child_env(),
            start_new_session=True)  # 自成进程组：取消时 killpg 才能连带杀掉 ffmpeg
    except OSError as exc:
        _finish_job(job_id, -1, JOB_START_FAILED.format(exc=exc))
        return
    try:
        with JOBS_LOCK:
            job = JOBS[job_id]
            job["popen"] = child
            cancel_now = job["cancel"]
            _write_marker(child.pid, job["project"], job["task"])
        if cancel_now:  # 取消请求先于 Popen 返回到达
            _terminate(job_id, child)
        for line in child.stdout:
            with JOBS_LOCK:
                JOBS[job_id]["log"].append(line.rstrip())
        code = child.wait()
    except Exception as exc:  # noqa: BLE001 - 任务线程不能静默死掉，留下永远 running
        with contextlib.suppress(Exception):
            _terminate(job_id, child)
        with contextlib.suppress(Exception):
            child.stdout.close()
        with contextlib.suppress(Exception):
            child.wait(timeout=CANCEL_GRACE_S * 2)  # 回收进程，不留僵尸
        _finish_job(job_id, -1, JOB_RUN_FAILED.format(exc=exc))
        return
    _finish_job(job_id, code)


def _finish_job(job_id: str, code: int, note: str | None = None) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        if note:
            job["log"].append(note)
        if job["cancel"] and code != 0:
            job["status"] = "cancelled"
        else:
            job["status"] = "done" if code == 0 else "failed"
        job["exit"] = code
        job["popen"] = None
        job["log"].append(JOB_EXIT_NOTE.format(code=code))
        _clear_marker()


def _killpg(pid: int, sig: int) -> None:
    if pid <= 0:  # killpg(0) 会杀到剪辑台自己所在的进程组
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _terminate(job_id: str, child: subprocess.Popen) -> None:
    """杀整个进程组（含它拉起的 ffmpeg），宽限期后任务仍未结束就 SIGKILL 整组。"""
    if child.returncode is None:  # 已被 wait() 回收的 pid 可能被复用，不能再发信号
        _killpg(child.pid, signal.SIGTERM)

    def _force() -> None:
        # 以「任务还没结束」为准，而不是主进程是否活着：aicut 退了但 ffmpeg 不理 SIGTERM、
        # 还占着输出管道时，任务会一直 running、占住全局互斥。进程组只要还有成员，pgid 就不会被复用
        with JOBS_LOCK:
            running = JOBS.get(job_id, {}).get("status") == "running"
        if running:
            _killpg(child.pid, signal.SIGKILL)

    timer = threading.Timer(CANCEL_GRACE_S, _force)
    timer.daemon = True
    timer.start()


def cancel_job(job_id: str) -> bool:
    """True=已发出取消；False=任务已结束。未知 id 抛 KeyError。重复点只发一次信号。"""
    with JOBS_LOCK:
        job = JOBS[job_id]
        if job["status"] != "running":
            return False
        if job["cancel"]:
            return True
        job["cancel"] = True
        job["log"].append(JOB_CANCEL_NOTE)
        child = job["popen"]
    if child is not None:  # 还没启动的话，_run_job 拿到 Popen 后会看到 cancel 标志
        _terminate(job_id, child)
    return True


def shutdown_all(grace: float | None = None) -> None:
    """剪辑台退出时调用：停掉全部运行中的任务（SIGTERM → 宽限期 → SIGKILL 整组），不留孤儿。"""
    grace = CANCEL_GRACE_S if grace is None else grace
    with JOBS_LOCK:
        targets = []
        for job in JOBS.values():
            if job["status"] == "running":
                job["cancel"] = True
                if job["popen"] is not None:
                    targets.append(job["popen"])
    for child in targets:
        if child.poll() is None:
            _killpg(child.pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_group_alive(c) for c in targets):
        time.sleep(0.05)
    for child in targets:
        if _group_alive(child):
            _killpg(child.pid, signal.SIGKILL)
    for child in targets:
        with contextlib.suppress(Exception):
            child.wait(timeout=1)


def _group_alive(child: subprocess.Popen) -> bool:
    """进程组里还有没有活着的进程（主进程退了，ffmpeg 可能还在）。"""
    if child.pid <= 0:
        return False
    try:
        os.killpg(child.pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


atexit.register(shutdown_all)


# ------------------------------------------------------------------ 跨实例 / 重启的任务记录
def marker_path() -> Path:
    return secrets.config_dir() / MARKER_FILE


def _write_marker(pid: int, project: str, task: str) -> None:
    with contextlib.suppress(OSError):  # 记不下来不影响任务本身
        schema.write_json(marker_path(), {"pid": pid, "project": project, "task": task,
                                          "server_pid": os.getpid(), "at": time.time()})


def _clear_marker() -> None:
    with contextlib.suppress(OSError):
        marker_path().unlink(missing_ok=True)


def _looks_like_job(pid: int) -> bool:
    """pid 可能早被系统复用：只有命令行里带 aicut 字样的才算我们的任务进程。"""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(hint in out for hint in JOB_PROCESS_HINTS)


def stale_job() -> dict | None:
    """上次（或另一个剪辑台实例）留下的、仍在运行的任务；没有就 None，失效记录顺手清掉。"""
    try:
        data = json.loads(marker_path().read_text(encoding="utf-8"))
        pid = int(data["pid"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        _clear_marker()
        return None
    own = {j["popen"].pid for j in JOBS.values() if j.get("popen") is not None}
    if pid in own:
        return None
    try:
        os.kill(pid, 0)
        alive = pid > 0 and _looks_like_job(pid)
    except (ProcessLookupError, PermissionError, OverflowError):
        alive = False
    if not alive:
        _clear_marker()
        return None
    return {**data, "pid": pid}


# ------------------------------------------------------------------ Windows 导出（GL-14）
def windows_zip(pdir: Path, version: str, title: str | None) -> Path:
    """<项目>/output/vN/<片名>_vN_Windows.zip；片名里的路径字符一律换成 _。"""
    raw = title if isinstance(title, str) and title.strip() else pdir.name
    name = _UNSAFE_FILENAME.sub("_", raw).lstrip(".-")[:ZIP_TITLE_MAX_CHARS] or pdir.name
    stem = f"{name}_{version}_Windows"
    return pdir / "output" / version / f"{stem}.zip"


def export_args(pdir: Path, version: object, title: str | None) -> list[str]:
    """`aicut export` 的参数；版本号先过白名单，-o 必须显式给（打包版 cwd 不可写）。"""
    version = schema.check_version(version)
    timeline = pdir / "output" / version / "timeline.json"
    if not timeline.is_file():
        raise FileNotFoundError(NO_TIMELINE_MSG)
    out = windows_zip(pdir, version, title)
    # --x=value：以 - 开头的片名也不会被 argparse 当成选项
    return [f"--timeline={timeline}", f"--out={out.parent}", f"--package-name={out.stem}"]


def windows_export_state(pdir: Path, version: str, title: str | None) -> dict:
    """版本卡片用：这一版是否已导出 Windows 包、多大。"""
    zip_path = windows_zip(pdir, version, title)
    if not zip_path.is_file():
        return {"windows_zip": None, "windows_mb": 0}
    return {"windows_zip": zip_path.name, "windows_mb": round(zip_path.stat().st_size / 1e6)}


def job_extra(pdir: Path, task: str, body: dict, title: str | None) -> list[str]:
    """把界面请求翻译成 aicut 子命令的额外参数；全部先过白名单。"""
    extra: list[str] = []
    if task == "build":
        if body.get("version"):
            extra += ["--version", schema.check_version(body["version"])]
        if body.get("no_draft"):
            extra.append("--no-draft")
    elif task == "select" and body.get("target") is not None:
        extra += ["--target", str(schema.check_target_duration(body["target"]))]
    elif task == "export":
        extra = export_args(pdir, body.get("version"), title)
    return extra
