# -*- coding: utf-8 -*-
"""剪辑台 · 后台任务（GL-17）与短命令（GL-20）。

所有任务一律是子进程（打包版是 App 带 `--aicut-cli` 重启自己，见 pipeline/proc.py）：
  * 全局互斥：同时最多 MAX_ACTIVE_JOBS 个，再起直接 JobConflict（→ 409），不排队；
  * 可取消：每个任务一棵进程树（pipeline/proctree.py：POSIX 进程组 / Windows Job Object），
    取消时停掉整棵树（连同它拉起的 ffmpeg）；POSIX 先 SIGTERM、宽限期后 SIGKILL；
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
import ntpath
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from pipeline import applog, outputs, plat, proc, proctree, schema, secrets, shots_store

JOB_COMMANDS = {"prepare": ["prepare"], "build": ["build"], "select": ["select"],
                "export": ["export"], "questions": ["questions", "--force"],  # KI-86：确认页重新出题
                "preview": ["preview"]}  # M14：只生成预览片，不产生版本
# M13：任务名词统一到向导的步骤名（PRD §12）；JOB_CONFLICT_MSG / 遗留任务提示 / 任务胶囊都用它
TASK_LABELS = {"prepare": "分析", "build": "导出", "select": "重新选段",
               "export": "生成 Windows 剪映包", "questions": "重新出题", "preview": "生成预览片"}
MAX_ACTIVE_JOBS = 1          # 重任务全局串行：ffmpeg / ASR 吃满资源，也避免重复计费
CANCEL_GRACE_S = 5.0         # 请求停止后等这么久仍未退出就强杀整棵树
SHORT_CMD_TIMEOUT_S = 60     # 短命令（新建项目等）的超时
ZIP_TITLE_MAX_CHARS = outputs.ZIP_TITLE_MAX_CHARS  # 别名：测试按 jobs.<名> 引用
_UNSAFE_FILENAME = outputs.UNSAFE_FILENAME
PUBLIC_FIELDS = ("status", "log", "exit", "task", "project")
MARKER_FILE = "job.marker"   # 配置目录下：当前运行中的任务（跨剪辑台实例 / 重启可见）
JOB_PROCESS_HINTS = ("aicut", "--aicut-cli")  # 判断 marker 里的 pid 还是不是我们的任务进程（POSIX：命令行）
WIN_JOB_IMAGES = ("python.exe", "pythonw.exe")  # Windows：镜像名是本 App 的 exe 或 python.exe 即视为像
HOMEBREW_BIN = "/opt/homebrew/bin"
MAX_FINISHED_JOBS = 20       # KI-68 / D13：任务表只留最近这么多个已结束任务（运行中的永不删）
JOB_LOG_MAX_LINES = 5000     # 单个任务在界面里保留的日志行数（保留末尾）
JOB_LOG_TRIM_FRACTION = 10   # 超限时一次丢掉 1/10，避免每行都整表搬移
JOB_LOG_TRIMMED = "…（前面省略 {n} 行，完整输出见日志文件）"

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
NO_TIMELINE_MSG = "这一版还没有时间线，先在「⑥ 导出」导出一次"

LOG = applog.get("job")  # app.log 只记任务要点（起止、退出码、行数、错误行），不记普通输出（GL-19）
LOGGED_PREFIXES = ("[错误]", "[x]", "[!]", "Traceback")  # 只有这些行进 app.log；正文可能含文稿 / 片名
LOGGED_LINE_MAX = 300
ERROR_PREFIX = "[x]"  # aicut.die() 输出的失败行
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


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
    if not proc.FROZEN and sys.platform != "win32":  # 打包版必须优先用内置 ffmpeg，不能把 brew 的插到前面
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
                           timeout=SHORT_CMD_TIMEOUT_S, env=child_env(), **plat.NO_WINDOW)
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


def project_running_locked(project: str) -> bool:
    """这个项目有没有任务在跑。调用方必须已持有 JOBS_LOCK（Lock 不可重入，不能再调 active_job）。"""
    return any(JOBS[jid]["project"] == project for jid in _running_locked())


def project_job(project: str) -> dict | None:
    """这个项目正在跑的任务 {id, task}；没有则 None。"""
    job_id = active_job(project)
    if job_id is None:
        return None
    with JOBS_LOCK:
        return {"id": job_id, "task": JOBS[job_id]["task"]}


def busy_view() -> dict | None:
    """全局正在跑的任务（任务胶囊 / 启动类按钮置灰用）：{id, task, project, label}；没有则 None。"""
    job_id = active_job()
    if job_id is None:
        return None
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None or job["status"] != "running":  # 取到 id 之后刚好结束
            return None
        return {"id": job_id, "task": job["task"], "project": job["project"],
                "label": TASK_LABELS.get(job["task"], job["task"])}


def _last_error_line(log: list[str]) -> str | None:
    """日志里最后一条 `[x]` 行（去掉前缀）；② 页失败时当原因显示。"""
    for line in reversed(log):
        text = line.strip()
        if text.startswith(ERROR_PREFIX):
            return text[len(ERROR_PREFIX):].strip() or None
    return None


def project_job_detail(project: str, task: str | None = None) -> dict | None:
    """这个项目最近一个任务（运行中或已结束，可按任务名过滤）：{id, task, started, status, last_error}。"""
    with JOBS_LOCK:
        mine = [(jid, j) for jid, j in JOBS.items()
                if j["project"] == project and (task is None or j["task"] == task)]
        if not mine:
            return None
        jid, job = max(mine, key=lambda item: item[1]["started"])
        return {"id": jid, "task": job["task"], "started": job["started"],
                "status": job["status"], "last_error": _last_error_line(job["log"])}


def job_view(job_id: str) -> dict | None:
    """给界面的任务快照：显式挑字段，绝不能把 Popen 序列化出去。"""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        view = {k: job[k] for k in PUBLIC_FIELDS}
        view["elapsed_s"] = max(0, round((job.get("ended") or time.time()) - job["started"]))
        trimmed = job.get("trimmed", 0)
        view["log"] = ([JOB_LOG_TRIMMED.format(n=trimmed)] if trimmed else []) + list(job["log"])
        return view


def _append_locked(job: dict, line: str) -> None:
    """追加一行界面日志（调用方持有 JOBS_LOCK）；超过上限丢掉最早的一批，计数给界面显示省略说明。"""
    log = job["log"]
    log.append(line)
    if len(log) <= JOB_LOG_MAX_LINES - (1 if job.get("trimmed") else 0):  # 省略说明也占一行
        return
    batch = max(1, JOB_LOG_MAX_LINES // JOB_LOG_TRIM_FRACTION)
    drop = len(log) - (JOB_LOG_MAX_LINES - batch)
    del log[:drop]
    job["trimmed"] = job.get("trimmed", 0) + drop


def _prune_locked() -> None:
    """只留最近 MAX_FINISHED_JOBS 个已结束任务（KI-68）；运行中的永不删。"""
    finished = sorted((j for j in JOBS.items() if j[1]["status"] != "running"),
                      key=lambda item: item[1]["started"])
    for job_id, _ in finished[:max(0, len(finished) - MAX_FINISHED_JOBS)]:
        del JOBS[job_id]


def _log_line(job_id: str, line: str) -> None:
    text = line.strip()
    if text.startswith(LOGGED_PREFIXES):
        LOG.info("[%s] %s", job_id, applog.strip_paths(text)[:LOGGED_LINE_MAX])


def start_job(name: str, task: str, extra: list[str] | None = None) -> str:
    applog.register_known_secrets()  # 子进程输出里若出现 Key 也要打码；不弹钥匙串
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
        _prune_locked()
        job_id = uuid.uuid4().hex[:8]
        thread = threading.Thread(target=_run_job, args=(job_id, cmd), daemon=True,
                                  name=f"aicut-job-{job_id}")
        JOBS[job_id] = {"status": "running", "log": [], "exit": None, "started": time.time(),
                        "task": task, "project": name, "popen": None, "tree": None,
                        "cancel": False, "thread": thread, "out_lines": 0}
    try:
        thread.start()
    except BaseException:
        with JOBS_LOCK:  # 线程没起来：撤销登记，释放互斥
            JOBS.pop(job_id, None)
        raise
    LOG.info("任务开始 %s %s %s", job_id, task, name)
    return job_id


def _run_job(job_id: str, cmd: list[str]) -> None:
    try:
        child = subprocess.Popen(
            cmd, cwd=str(proc.app_root()), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, env=child_env(),
            **proctree.spawn_kwargs())  # 子进程成为进程树的根：取消时才能连带杀掉 ffmpeg
    except OSError as exc:
        _finish_job(job_id, -1, JOB_START_FAILED.format(exc=exc))
        return
    try:
        tree = proctree.attach(child)  # Windows 上 Job 赋值有毫秒级窗口，见 proctree 说明
    except Exception as exc:  # noqa: BLE001 - 任何失败（含 ctypes ArgumentError）都不能让任务线程静默死掉
        # proctree.attach 只在「恢复挂起进程」失败时抛：此时进程不能跑，杀掉并报告启动失败
        for step in (lambda: child.kill(), lambda: child.stdout.close(),
                     lambda: child.wait(timeout=CANCEL_GRACE_S)):
            with contextlib.suppress(Exception):
                step()
        _finish_job(job_id, -1, JOB_START_FAILED.format(exc=exc))
        return
    try:
        with JOBS_LOCK:
            job = JOBS[job_id]
            job["popen"] = child
            job["tree"] = tree
            cancel_now = job["cancel"]
            _write_marker(child.pid, job["project"], job["task"])
        if cancel_now:  # 取消请求先于 Popen 返回到达
            _terminate(job_id, child, tree)
        for line in child.stdout:
            with JOBS_LOCK:
                _append_locked(JOBS[job_id], applog.redact(line.rstrip()))  # KI-70：界面日志也打码
                JOBS[job_id]["out_lines"] += 1
            _log_line(job_id, line)
        code = child.wait()
    except Exception as exc:  # noqa: BLE001 - 任务线程不能静默死掉，留下永远 running
        with contextlib.suppress(Exception):
            _terminate(job_id, child, tree)
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
        tree = job.pop("tree", None)
        if tree is not None:  # 释放树（Windows：关 Job 句柄，剩余成员随之结束）
            with contextlib.suppress(Exception):
                proctree.close(tree)
        if note:  # 异常文本可能带路径 / Key：与任务输出一样打码（L17）
            note = applog.redact(note)
            _append_locked(job, note)
        if job["cancel"] and code != 0:
            job["status"] = "cancelled"
        else:
            job["status"] = "done" if code == 0 else "failed"
        job["exit"] = code
        job["ended"] = time.time()
        job["popen"] = None
        _append_locked(job, JOB_EXIT_NOTE.format(code=code))
        _clear_marker()
    (LOG.info if code == 0 else LOG.warning)(
        "任务结束 %s %s 退出码 %s，输出共 %d 行 %s", job_id, job["status"], code,
        job.get("out_lines", 0), applog.strip_paths(note or "")[:LOGGED_LINE_MAX])


def _terminate(job_id: str, child: subprocess.Popen, tree: proctree.Tree) -> None:
    """停整棵树（含它拉起的 ffmpeg）；宽限期后任务仍未结束就强杀整棵树。"""
    if child.returncode is None:  # 已被 wait() 回收的 pid 可能被复用，不能再发信号
        proctree.terminate(tree)

    def _force() -> None:
        # 以「任务还没结束」为准，而不是主进程是否活着：aicut 退了但 ffmpeg 不理 SIGTERM、
        # 还占着输出管道时，任务会一直 running、占住全局互斥。进程组只要还有成员，pgid 就不会被复用
        with JOBS_LOCK:
            running = JOBS.get(job_id, {}).get("status") == "running"
        if running:
            proctree.kill(tree)

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
        _append_locked(job, JOB_CANCEL_NOTE)
        child, tree = job["popen"], job.get("tree")
    if child is not None and tree is not None:  # 还没启动的话，_run_job 拿到 Popen 后会看到 cancel 标志
        _terminate(job_id, child, tree)
    return True


def shutdown_all(grace: float | None = None) -> None:
    """剪辑台退出时调用：停掉全部运行中的任务（请求停止 → 宽限期 → 强杀整棵树），不留孤儿。"""
    grace = CANCEL_GRACE_S if grace is None else grace
    with JOBS_LOCK:
        targets = []
        for job in JOBS.values():
            if job["status"] == "running":
                job["cancel"] = True
                if job["popen"] is not None and job.get("tree") is not None:
                    targets.append((job["popen"], job["tree"]))
    for child, tree in targets:
        if child.poll() is None:
            proctree.terminate(tree)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(proctree.alive(t) for _, t in targets):
        time.sleep(0.05)
    for _, tree in targets:
        if proctree.alive(tree):
            proctree.kill(tree)
    for child, _ in targets:
        with contextlib.suppress(Exception):
            child.wait(timeout=1)
    for _, tree in targets:
        with contextlib.suppress(Exception):
            proctree.close(tree)


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
    """pid 可能早被系统复用：POSIX 看命令行里有没有 aicut 字样；Windows 看镜像名是本 App 的 exe 或 python.exe。"""
    image = plat.process_image(pid)
    if not image:
        return False
    if plat.IS_WIN:
        name = ntpath.basename(image).lower()
        return name in {ntpath.basename(sys.executable).lower(), *WIN_JOB_IMAGES}
    return any(hint in image for hint in JOB_PROCESS_HINTS)


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
    alive = pid > 0 and plat.pid_alive(pid) and _looks_like_job(pid)  # 探活不能用 os.kill(pid, 0)：Windows 上会终止进程
    if not alive:
        _clear_marker()
        return None
    return {**data, "pid": pid}


def stale_job_view() -> dict | None:
    """给界面的遗留任务提示（KI-71 / D14：顶部提示条）：{project, task, pid, message}；没有就 None。"""
    stale = stale_job()
    if stale is None:
        return None
    project = str(stale.get("project", "?"))
    task = TASK_LABELS.get(stale.get("task"), str(stale.get("task", "?")))
    return {"project": project, "task": task, "pid": stale["pid"],
            "message": STALE_JOB_MSG.format(project=project, task=task, pid=stale["pid"])}


# ------------------------------------------------------------------ Windows 导出（GL-14）
def windows_zip(pdir: Path, version: str, title: str | None) -> Path:
    """<项目>/output/vN/<片名>_vN_Windows.zip（实现在 outputs，M14 E22）。"""
    return outputs.windows_zip(pdir, version, title)


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
    if task == "build":  # 项目文件损坏抛 CorruptJSON，由路由变成 409
        extra = outputs.build_args(pdir, body, schema.read_json(Path(pdir) / "project.json"))
    elif task == "select":
        if body.get("target") is not None:
            extra += ["--target", str(schema.check_target_duration(body["target"]))]
        if body.get("manual") is not None:
            extra.append(f"--manual={shots_store.check_manual(body['manual'])}")
    elif task == "export":
        extra = export_args(pdir, body.get("version"), title)
    return extra
