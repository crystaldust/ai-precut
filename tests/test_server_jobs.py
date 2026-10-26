"""M4 · GL-17 / GL-20：后台任务（互斥、取消、先校验后登记、子进程化）与新建项目。"""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import call, make_project
from pipeline import plat, proctree
from platform_marks import posix_only, win_only

LONG = [sys.executable, "-c", "import time; print('go', flush=True); time.sleep(30)"]
# 子进程再拉一个孙进程（模拟 aicut 拉起 ffmpeg），取消时两个都必须被杀
GRANDCHILD = [sys.executable, "-c",
              "import subprocess,sys,time;"
              "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
              "print('child', c.pid, flush=True); time.sleep(60)"]


@pytest.fixture
def jobs(gui_server):
    from gui import jobs as module
    return module


def fake_command(monkeypatch, jobs, argv):
    seen = []

    def job_command(task, name, extra):
        seen.append((task, name, list(extra)))
        return argv

    monkeypatch.setattr(jobs, "job_command", job_command)
    return seen


def wait_for(pred, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def get_job(gs, job_id):
    status, body, _ = call(gs, "GET", f"/api/job/{job_id}")
    return status, json.loads(body)


def post_job(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/job", {"project": "p1", **body})
    return status, json.loads(raw)


def pid_alive(pid):
    import os
    if plat.IS_WIN:  # Windows 上绝不能 os.kill(pid, 0)
        return plat.pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # 僵尸进程也算已退出
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(r.stdout.strip()) and not r.stdout.strip().startswith("Z")


# ---------------------------------------------------------------- 先校验后登记
def test_unknown_task_rejected_without_ghost_job(gui_server, jobs):
    make_project(gui_server.root)
    status, data = post_job(gui_server, task="rm")
    assert status == 400 and "未知任务" in data["error"]
    assert jobs.JOBS == {}


def test_server_shares_job_registry(gui_server, jobs):
    srv = gui_server.module
    assert srv.JOBS is jobs.JOBS and srv.JOBS_LOCK is jobs.JOBS_LOCK


# ---------------------------------------------------------------- 互斥
def test_second_job_conflicts_409(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    make_project(gui_server.root, "p2")
    fake_command(monkeypatch, jobs, LONG)
    status, first = post_job(gui_server, task="preview")
    assert status == 200
    status, second = post_job(gui_server, task="select")
    assert status == 409 and second["job_id"] == first["job_id"]
    assert "已有任务在运行" in second["error"] and "p1" in second["error"]
    status, other = call(gui_server, "POST", "/api/job", {"project": "p2", "task": "preview"})[:2]
    assert status == 409  # 全局一次一个（MAX_ACTIVE_JOBS = 1）
    assert len(jobs.JOBS) == 1


# ---------------------------------------------------------------- 取消
@posix_only("进程组 + SIGTERM 取消")
def test_cancel_kills_process_group(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, GRANDCHILD)
    _, data = post_job(gui_server, task="preview")
    job_id = data["job_id"]
    assert wait_for(lambda: any(l.startswith("child") for l in get_job(gui_server, job_id)[1]["log"]))
    grandchild = int(next(l for l in get_job(gui_server, job_id)[1]["log"]
                          if l.startswith("child")).split()[1])
    status, raw, _ = call(gui_server, "POST", f"/api/job/{job_id}/cancel", {})
    assert status == 200 and json.loads(raw)["ok"] is True
    assert wait_for(lambda: get_job(gui_server, job_id)[1]["status"] == "cancelled")
    job = get_job(gui_server, job_id)[1]
    assert any(l.startswith("[取消]") for l in job["log"])
    assert wait_for(lambda: not pid_alive(grandchild)), "孙进程（ffmpeg）也必须被杀"
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    status, _ = post_job(gui_server, task="preview")
    assert status == 200  # 互斥已释放


@win_only("Job Object 取消：子进程与孙进程都被 TerminateJobObject 结束")
def test_cancel_kills_child_and_grandchild_via_job_object(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, GRANDCHILD)
    _, data = post_job(gui_server, task="preview")
    job_id = data["job_id"]
    assert wait_for(lambda: any(l.startswith("child") for l in get_job(gui_server, job_id)[1]["log"]))
    grandchild = int(next(l for l in get_job(gui_server, job_id)[1]["log"]
                          if l.startswith("child")).split()[1])
    status, raw, _ = call(gui_server, "POST", f"/api/job/{job_id}/cancel", {})
    assert status == 200 and json.loads(raw)["ok"] is True
    assert wait_for(lambda: get_job(gui_server, job_id)[1]["status"] == "cancelled")
    assert wait_for(lambda: not pid_alive(grandchild)), "孙进程（ffmpeg）也必须被杀"
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    assert post_job(gui_server, task="preview")[0] == 200  # 互斥已释放


def test_cancel_unknown_job_404(gui_server):
    status, _, _ = call(gui_server, "POST", "/api/job/deadbeef/cancel", {})
    assert status == 404


def test_cancel_finished_job_returns_false(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    _, data = post_job(gui_server, task="preview")
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "done")
    status, raw, _ = call(gui_server, "POST", f"/api/job/{data['job_id']}/cancel", {})
    assert status == 200 and json.loads(raw)["ok"] is False


# ---------------------------------------------------------------- 状态与日志
def test_failed_job_status_and_exit_code(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "import sys; print('x'); sys.exit(2)"])
    _, data = post_job(gui_server, task="preview")
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] != "running")
    job = get_job(gui_server, data["job_id"])[1]
    assert job["status"] == "failed" and job["exit"] == 2
    assert job["log"][-1] == "[退出码] 2"
    assert job["project"] == "p1" and job["task"] == "preview"
    assert set(job) == {"status", "log", "exit", "task", "project", "elapsed_s"}  # 绝不序列化 Popen


def test_start_failure_is_reported_not_ghost(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, ["/nonexistent/aicut-binary"])
    _, data = post_job(gui_server, task="preview")
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "failed")
    assert any("无法启动任务" in l for l in get_job(gui_server, data["job_id"])[1]["log"])


def test_state_reports_active_job(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    make_project(gui_server.root, "p2")
    fake_command(monkeypatch, jobs, LONG)
    _, data = post_job(gui_server, task="preview")
    state = json.loads(call(gui_server, "GET", "/api/state?project=p1")[1])
    assert state["job"] == {"id": data["job_id"], "task": "preview"}
    other = json.loads(call(gui_server, "GET", "/api/state?project=p2")[1])
    assert other["job"] is None


# ---------------------------------------------------------------- 子进程化
def test_job_command_dev_and_frozen(jobs, monkeypatch):
    monkeypatch.setattr(jobs.proc, "FROZEN", False)
    assert jobs.job_command("prepare", "p1", [])[1].endswith("aicut.py")
    monkeypatch.setattr(jobs.proc, "FROZEN", True)
    assert jobs.job_command("prepare", "p1", ["--x"])[1:] == ["--aicut-cli", "prepare", "p1", "--x"]


def test_child_popen_flags(gui_server, jobs, plain_attach, monkeypatch):
    seen = {}

    class FakePopen:
        pid = 0

        def __init__(self, argv, **kw):
            seen.update(kw)
            self.stdout = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(jobs.subprocess, "Popen", FakePopen)
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] == "done")
    assert seen["stdin"] is subprocess.DEVNULL
    for key, value in proctree.spawn_kwargs().items():  # 进程树的启动参数由 proctree 决定，不再写死
        assert seen[key] == value
    assert seen["env"]["PYTHONUNBUFFERED"] == "1"
    assert len(plain_attach) == 1


def test_child_popen_uses_proctree_spawn_kwargs_and_attaches(gui_server, jobs, monkeypatch):
    seen, events = {}, []

    class FakePopen:
        pid = 0
        returncode = None

        def __init__(self, argv, **kw):
            seen.update(kw)
            self.stdout = iter([])

        def wait(self):
            return 0

    tree = object()
    monkeypatch.setattr(jobs.proctree, "spawn_kwargs", lambda: {"sentinel_flag": 7})
    monkeypatch.setattr(jobs.proctree, "attach", lambda popen: events.append(("attach", popen)) or tree)
    monkeypatch.setattr(jobs.proctree, "close", lambda t: events.append(("close", t)))
    monkeypatch.setattr(jobs.subprocess, "Popen", FakePopen)
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] == "done")
    assert seen["sentinel_flag"] == 7
    assert [e[0] for e in events] == ["attach", "close"]  # 起好立刻挂树；任务结束释放
    assert events[1][1] is tree


def test_attach_failure_kills_child_and_fails_job(gui_server, jobs, monkeypatch):
    killed = []

    class FakePopen:
        pid = 0
        returncode = None

        def __init__(self, argv, **kw):
            self.stdout = iter([])

        def kill(self):
            killed.append(1)

        def wait(self, timeout=None):
            return -9

    def boom(popen):
        raise ValueError("ctypes ArgumentError 之类：不止 OSError")

    monkeypatch.setattr(jobs.proctree, "attach", boom)
    monkeypatch.setattr(jobs.subprocess, "Popen", FakePopen)
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] == "failed")
    assert killed == [1]
    assert any("无法启动任务" in l for l in jobs.JOBS[job_id]["log"])


class BlockingPopen:
    """stdout 一直阻塞到 release；用来测取消 / 关停时调用了 proctree 的哪些函数。"""
    pid = 0
    returncode = None

    def __init__(self, argv=None, **kw):
        import threading
        self.release = threading.Event()
        self.stdout = self

    def __iter__(self):
        self.release.wait(10)
        return iter([])

    def wait(self, timeout=None):
        self.returncode = -15
        return -15

    def poll(self):
        return None

    def close(self):
        pass


def test_cancel_terminates_tree_then_kills_after_grace(gui_server, jobs, monkeypatch):
    monkeypatch.setattr(jobs, "CANCEL_GRACE_S", 0.2)
    calls, popens = [], []

    def make(*a, **kw):
        popens.append(BlockingPopen())
        return popens[-1]

    tree = object()
    monkeypatch.setattr(jobs.subprocess, "Popen", make)
    monkeypatch.setattr(jobs.proctree, "attach", lambda popen: tree)
    monkeypatch.setattr(jobs.proctree, "terminate", lambda t: calls.append(("terminate", t)))
    monkeypatch.setattr(jobs.proctree, "kill", lambda t: calls.append(("kill", t)))
    monkeypatch.setattr(jobs.proctree, "close", lambda t: calls.append(("close", t)))
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["popen"] is not None)
    assert wait_for(lambda: jobs.JOBS[job_id].get("tree") is tree)
    jobs.cancel_job(job_id)
    assert wait_for(lambda: ("kill", tree) in calls)  # 宽限期后仍未结束 → 强杀
    assert calls[0] == ("terminate", tree)
    popens[0].release.set()
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] == "cancelled")
    assert calls[-1] == ("close", tree)


def test_frozen_child_env_keeps_bundled_path_first(jobs, monkeypatch):
    monkeypatch.setattr(jobs.proc, "FROZEN", True)
    monkeypatch.setenv("PATH", os.pathsep.join(["/app/bin", "/usr/bin"]))  # 分隔符：POSIX ':'、Windows ';'
    assert jobs.child_env()["PATH"] == os.pathsep.join(["/app/bin", "/usr/bin"])
    monkeypatch.setattr(jobs.proc, "FROZEN", False)
    monkeypatch.setattr(jobs.sys, "platform", "darwin")
    assert jobs.child_env()["PATH"].startswith("/opt/homebrew/bin" + os.pathsep)


def test_homebrew_path_prefix_kept_on_linux_but_not_windows(jobs, monkeypatch):
    monkeypatch.setattr(jobs.proc, "FROZEN", False)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(jobs.sys, "platform", "linux")
    assert jobs.child_env()["PATH"].startswith("/opt/homebrew/bin" + os.pathsep)  # 与改动前一致
    monkeypatch.setattr(jobs.sys, "platform", "win32")
    assert "/opt/homebrew/bin" not in jobs.child_env()["PATH"]


# ---------------------------------------------------------------- GL-20：新建项目
def test_api_new_passes_no_input_and_devnull(gui_server, preset_dir, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    srv = gui_server.module
    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": "n1", "material": "/tmp/a.mp4", "preset": "测试预设",
                         "target": 120})
    assert status == 200
    assert "--no-input" in seen["argv"]
    assert seen["kw"]["stdin"] is subprocess.DEVNULL and seen["kw"]["timeout"] > 0


def test_run_aicut_frozen_relaunches_app_not_inprocess(jobs, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return type("R", (), {"returncode": 0, "stdout": "o", "stderr": "e"})()

    monkeypatch.setattr(jobs.proc, "FROZEN", True)
    monkeypatch.setattr(jobs.subprocess, "run", fake_run)
    assert jobs.run_aicut(["list"]) == (0, "oe")
    assert seen["argv"] == [sys.executable, "--aicut-cli", "list"]


def test_run_aicut_timeout_reports_error(jobs, monkeypatch):
    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)
    code, out = jobs.run_aicut(["new", "x"])
    assert code != 0 and "超时" in out


# ---------------------------------------------------------------- 审查修复
STUBBORN = [sys.executable, "-c",
            "import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import signal,time;"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); print(\"ready\", flush=True); time.sleep(60)']);"
            "time.sleep(0.5); print('child', c.pid, flush=True); time.sleep(60)"]


@posix_only("SIGTERM 被忽略的孙进程要靠 SIGKILL 进程组兜底；Windows 的 Job 终止没有宽限期这一层")
def test_cancel_force_kills_group_even_if_main_child_already_exited(gui_server, jobs, monkeypatch):
    # aicut 收到 SIGTERM 退出了，但它拉起的 ffmpeg 不理 SIGTERM 且还占着输出管道：
    # 宽限期后必须 SIGKILL 整组，任务才能结束、互斥才能释放
    monkeypatch.setattr(jobs, "CANCEL_GRACE_S", 0.5)
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, STUBBORN)
    _, data = post_job(gui_server, task="preview")
    job_id = data["job_id"]
    assert wait_for(lambda: any(l.startswith("child") for l in get_job(gui_server, job_id)[1]["log"]))
    call(gui_server, "POST", f"/api/job/{job_id}/cancel", {})
    assert wait_for(lambda: get_job(gui_server, job_id)[1]["status"] == "cancelled", timeout=8)


@pytest.mark.parametrize("task", [["build"], {"a": 1}, 3, None])
def test_non_string_task_is_400_not_500(gui_server, task):
    make_project(gui_server.root)
    status, data = post_job(gui_server, task=task)
    assert status == 400


def test_repeated_cancel_starts_one_kill_timer(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    started = []
    real = jobs._terminate
    monkeypatch.setattr(jobs, "_terminate", lambda *a: (started.append(a), real(*a)))
    _, data = post_job(gui_server, task="preview")
    assert wait_for(lambda: jobs.JOBS[data["job_id"]]["popen"] is not None)
    for _ in range(3):
        call(gui_server, "POST", f"/api/job/{data['job_id']}/cancel", {})
    assert len(started) == 1


# ---------------------------------------------------------------- 审查修复 2：不留孤儿任务（HIGH-1）
@posix_only("SIGTERM → 宽限期 → SIGKILL 整组")
def test_shutdown_all_kills_running_jobs_and_grandchildren(gui_server, jobs, monkeypatch):
    monkeypatch.setattr(jobs, "CANCEL_GRACE_S", 0.5)
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, STUBBORN)
    _, data = post_job(gui_server, task="preview")
    job_id = data["job_id"]
    assert wait_for(lambda: any(l.startswith("child") for l in get_job(gui_server, job_id)[1]["log"]))
    grandchild = int(next(l for l in get_job(gui_server, job_id)[1]["log"]
                          if l.startswith("child")).split()[1])
    started = time.time()
    jobs.shutdown_all()
    assert time.time() - started < 5
    assert wait_for(lambda: not pid_alive(grandchild), timeout=3), "退出时孙进程也必须被杀"


@win_only("shutdown_all 经 Job Object 一次结束子进程与孙进程")
def test_shutdown_all_kills_job_tree_on_windows(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, GRANDCHILD)
    _, data = post_job(gui_server, task="preview")
    job_id = data["job_id"]
    assert wait_for(lambda: any(l.startswith("child") for l in get_job(gui_server, job_id)[1]["log"]))
    grandchild = int(next(l for l in get_job(gui_server, job_id)[1]["log"]
                          if l.startswith("child")).split()[1])
    started = time.time()
    jobs.shutdown_all()
    assert time.time() - started < 5
    assert wait_for(lambda: not pid_alive(grandchild), timeout=3), "退出时孙进程也必须被杀"


def test_shutdown_all_terminates_waits_kills_and_closes_trees(gui_server, jobs, monkeypatch):
    calls = []
    state = {"alive": True}

    class Child:
        pid = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    tree = object()
    monkeypatch.setattr(jobs.proctree, "terminate", lambda t: calls.append("terminate"))
    monkeypatch.setattr(jobs.proctree, "alive", lambda t: state["alive"])
    monkeypatch.setattr(jobs.proctree, "kill", lambda t: (calls.append("kill"), state.update(alive=False)))
    monkeypatch.setattr(jobs.proctree, "close", lambda t: calls.append("close"))
    jobs.JOBS["j1"] = {"status": "running", "log": [], "exit": None, "started": 0, "task": "build",
                       "project": "p1", "popen": Child(), "tree": tree, "cancel": False,
                       "thread": None, "out_lines": 0}
    jobs.shutdown_all(grace=0.1)
    assert calls == ["terminate", "kill", "close"]  # 宽限期内没退出 → 强杀 → 释放
    assert jobs.JOBS["j1"]["cancel"] is True


def test_shutdown_all_without_jobs_is_noop(jobs):
    jobs.shutdown_all()


def test_shutdown_registered_at_exit_and_in_entrypoints(jobs):
    import atexit  # noqa: F401
    from pathlib import Path
    root = Path(jobs.__file__).resolve().parent.parent
    assert "atexit.register(shutdown_all)" in Path(jobs.__file__).read_text(encoding="utf-8")
    assert "jobs.shutdown_all()" in (root / "app/main.py").read_text(encoding="utf-8")
    assert "jobs.shutdown_all()" in (root / "gui/server.py").read_text(encoding="utf-8")


def test_child_env_carries_parent_pid_for_watchdog(jobs):
    import os
    assert jobs.child_env()[jobs.proc.PARENT_PID_ENV] == str(os.getpid())


def test_marker_written_while_running_and_removed_after(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    _, data = post_job(gui_server, task="preview")
    assert wait_for(lambda: jobs.marker_path().exists())
    marker = json.loads(jobs.marker_path().read_text(encoding="utf-8"))
    assert marker["project"] == "p1" and marker["task"] == "preview" and marker["pid"] > 0
    jobs.cancel_job(data["job_id"])
    assert wait_for(lambda: not jobs.marker_path().exists())


def _orphan(tmp_path):
    """一个「上次剪辑台留下的」还活着的任务进程（命令行里带 aicut 字样）。"""
    script = tmp_path / "aicut_orphan.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    return subprocess.Popen([sys.executable, str(script)], **proctree.spawn_kwargs())


def test_stale_job_from_previous_server_blocks_new_job(gui_server, jobs, monkeypatch, tmp_path):
    orphan = _orphan(tmp_path)
    try:
        jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
        jobs.marker_path().write_text(json.dumps(
            {"pid": orphan.pid, "project": "old", "task": "prepare", "server_pid": 1}),
            encoding="utf-8")
        make_project(gui_server.root)
        fake_command(monkeypatch, jobs, LONG)
        status, data = post_job(gui_server, task="preview")
        assert status == 409 and str(orphan.pid) in data["error"] and "old" in data["error"]
        assert jobs.JOBS == {}
        assert jobs.stale_job()["pid"] == orphan.pid
    finally:
        orphan.kill()
        orphan.wait()


@win_only("Windows 上遗留 marker 靠 OpenProcess + 镜像名识别（python.exe / 本 App 的 exe）")
def test_stale_job_detected_via_win32_probes(gui_server, jobs, tmp_path):
    orphan = _orphan(tmp_path)
    try:
        jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
        jobs.marker_path().write_text(json.dumps(
            {"pid": orphan.pid, "project": "old", "task": "prepare", "server_pid": 1}),
            encoding="utf-8")
        stale = jobs.stale_job()
        assert stale is not None and stale["pid"] == orphan.pid
    finally:
        orphan.kill()
        orphan.wait()
    assert jobs.stale_job() is None  # 进程没了：记录失效并清掉
    assert not jobs.marker_path().exists()


def test_stale_job_uses_plat_pid_alive_not_os_kill(jobs, monkeypatch):
    def boom(*a):
        raise AssertionError("Windows 上 os.kill(pid, 0) 会终止进程，探活必须走 plat.pid_alive")

    seen = []
    monkeypatch.setattr(jobs.os, "kill", boom)
    monkeypatch.setattr(jobs.plat, "pid_alive", lambda pid: seen.append(pid) or False)
    jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
    jobs.marker_path().write_text(json.dumps({"pid": 4242, "project": "x", "task": "build"}),
                                  encoding="utf-8")
    assert jobs.stale_job() is None
    assert seen == [4242] and not jobs.marker_path().exists()


@pytest.mark.parametrize("image,expected", [
    ("C:\\Program Files\\剪辑台\\剪辑台.exe", True),   # 本 App 的 exe（下面把 sys.executable 指过来）
    ("C:\\Python312\\python.exe", True),
    ("C:\\Python312\\PYTHONW.EXE", True),
    ("C:\\Windows\\System32\\notepad.exe", False),
    (None, False),
])
def test_looks_like_job_on_windows_matches_app_or_python_image(jobs, monkeypatch, image, expected):
    monkeypatch.setattr(jobs.plat, "IS_WIN", True)
    monkeypatch.setattr(jobs.sys, "executable", "C:\\Program Files\\剪辑台\\剪辑台.exe")
    monkeypatch.setattr(jobs.plat, "process_image", lambda pid: image)
    assert jobs._looks_like_job(1) is expected


@pytest.mark.parametrize("image,expected", [
    ("/usr/bin/python3 /app/aicut.py run p1", True),
    ("/Applications/AI粗剪.app/Contents/MacOS/AI粗剪 --aicut-cli prepare x", True),
    ("/usr/bin/vim notes.txt", False),
    (None, False),
])
def test_looks_like_job_on_posix_matches_command_hints(jobs, monkeypatch, image, expected):
    monkeypatch.setattr(jobs.plat, "IS_WIN", False)
    monkeypatch.setattr(jobs.plat, "process_image", lambda pid: image)
    assert jobs._looks_like_job(1) is expected


def test_dead_stale_marker_is_ignored_and_cleaned(gui_server, jobs, monkeypatch):
    jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
    jobs.marker_path().write_text(json.dumps({"pid": 999999, "project": "old", "task": "build"}),
                                  encoding="utf-8")
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    status, _ = post_job(gui_server, task="preview")
    assert status == 200


def test_unrelated_live_pid_in_marker_is_ignored(gui_server, jobs, monkeypatch):
    import os
    jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
    # pid 被复用成了无关进程（这里是 pytest 自己，命令行里没有 aicut 字样）也不能永久卡住
    monkeypatch.setattr(jobs, "_looks_like_job", lambda pid: False)
    jobs.marker_path().write_text(json.dumps({"pid": os.getpid(), "project": "x", "task": "build"}),
                                  encoding="utf-8")
    assert jobs.stale_job() is None


# ---------------------------------------------------------------- 审查修复 2：LOW-8 / LOW-12 / MEDIUM-4
def test_conflict_body_names_running_task_and_project(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    post_job(gui_server, task="preview")
    status, data = post_job(gui_server, task="select")
    assert status == 409 and data["task"] == "preview" and data["project"] == "p1"


def test_thread_start_failure_unregisters_job(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)

    class BrokenThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(jobs.threading, "Thread", BrokenThread)
    with pytest.raises(RuntimeError):
        jobs.start_job("p1", "build")
    assert jobs.JOBS == {} and jobs.active_job() is None  # 互斥已释放


def test_reader_exception_reaps_child_and_fails_job(gui_server, jobs, plain_attach, monkeypatch):
    closed = {}

    class Out:
        def __iter__(self):
            raise OSError("pipe broke")

        def close(self):
            closed["stdout"] = True

    class FakePopen:
        pid = 0
        returncode = None

        def __init__(self, argv, **kw):
            self.stdout = Out()

        def wait(self, timeout=None):
            closed["waited"] = True
            self.returncode = -9
            return -9

        def poll(self):
            return self.returncode

    monkeypatch.setattr(jobs.subprocess, "Popen", FakePopen)
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] == "failed")
    assert closed == {"stdout": True, "waited": True}
    assert len(plain_attach) == 1
    assert any("任务异常中断" in l for l in jobs.JOBS[job_id]["log"])


def test_cancel_before_popen_still_stops_job(gui_server, jobs, monkeypatch):
    import threading as th
    release = th.Event()
    real_popen = subprocess.Popen

    def slow_popen(*a, **kw):
        release.wait(5)  # 模拟取消请求先于 Popen 返回到达
        return real_popen(*a, **kw)

    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    monkeypatch.setattr(jobs.subprocess, "Popen", slow_popen)
    job_id = jobs.start_job("p1", "build")
    assert jobs.cancel_job(job_id) is True and jobs.JOBS[job_id]["popen"] is None
    release.set()
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] == "cancelled", timeout=8)


def test_stop_jobs_helper_joins_threads(gui_server, jobs, monkeypatch):
    from conftest import _stop_jobs
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    job_id = jobs.start_job("p1", "build")
    thread = jobs.JOBS[job_id]["thread"]
    _stop_jobs(jobs)
    assert not thread.is_alive() and jobs.JOBS == {}


def test_error_right_after_popen_fails_job_instead_of_hanging(gui_server, jobs, monkeypatch):
    monkeypatch.setattr(jobs, "_write_marker", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] != "running")
    assert jobs.JOBS[job_id]["status"] == "failed"


# ---------------------------------------------------------------- KI-70：任务日志里的 Key 打码
def test_job_log_lines_are_redacted(gui_server, jobs, monkeypatch):
    from pipeline import secrets
    key = "sk-joblogsecret12345678"
    secrets.set("deepseek", key)  # 凭证文件里的 Key：start_job 会登记（不碰钥匙串）
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", f"print('leak {key}', flush=True)"])
    status, data = post_job(gui_server, task="select")
    assert status == 200
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] != "running")
    log = "\n".join(get_job(gui_server, data["job_id"])[1]["log"])
    assert key not in log and "leak" in log


# ---------------------------------------------------------------- KI-68：任务表与日志有上限
def _finish(gs, data):
    assert wait_for(lambda: get_job(gs, data["job_id"])[1]["status"] != "running")


def test_finished_jobs_are_pruned_beyond_limit(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    monkeypatch.setattr(jobs, "MAX_FINISHED_JOBS", 2)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    ids = []
    for _ in range(4):
        status, data = post_job(gui_server, task="select")
        assert status == 200
        _finish(gui_server, data)
        ids.append(data["job_id"])
    fake_command(monkeypatch, jobs, LONG)
    status, running = post_job(gui_server, task="select")
    assert status == 200
    with jobs.JOBS_LOCK:
        kept = set(jobs.JOBS)
    assert kept == {ids[-2], ids[-1], running["job_id"]}  # 运行中的不算、也不删


def test_job_log_is_capped_with_note(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    monkeypatch.setattr(jobs, "JOB_LOG_MAX_LINES", 10)
    fake_command(monkeypatch, jobs, [sys.executable, "-c",
                                     "[print(f'line {i}', flush=True) for i in range(30)]"])
    status, data = post_job(gui_server, task="select")
    _finish(gui_server, data)
    log = get_job(gui_server, data["job_id"])[1]["log"]
    assert len(log) <= 11 and "省略" in log[0] and log[-1].startswith("[退出码]")
    assert "line 29" in log


# ---------------------------------------------------------------- KI-71：遗留任务主动提示
def test_projects_endpoint_reports_stale_job(gui_server, jobs, tmp_path):
    orphan = _orphan(tmp_path)
    try:
        jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
        jobs.marker_path().write_text(json.dumps(
            {"pid": orphan.pid, "project": "old", "task": "prepare", "server_pid": 1}),
            encoding="utf-8")
        status, body, _ = call(gui_server, "GET", "/api/projects")
        stale = json.loads(body)["stale_job"]
        assert status == 200 and stale["pid"] == orphan.pid and stale["project"] == "old"
        assert stale["task"] == "分析" and str(orphan.pid) in stale["message"]
    finally:
        orphan.kill()
        orphan.wait()
    status, body, _ = call(gui_server, "GET", "/api/projects")
    assert json.loads(body)["stale_job"] is None


def test_job_failure_notes_are_redacted(gui_server, jobs, monkeypatch):  # 审查修复 L17
    from pipeline import applog
    key = "sk-notesecret12345678"
    applog.register_secret(key)
    make_project(gui_server.root)
    monkeypatch.setattr(jobs, "job_command", lambda *a: [f"/nonexistent/{key}"])
    status, data = post_job(gui_server, task="select")
    assert status == 200
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] != "running")
    log = "\n".join(get_job(gui_server, data["job_id"])[1]["log"])
    assert key not in log and "无法启动任务" in log


# ---------------------------------------------------------------- M13 T7：elapsed / busy / 新名词
def _fake_clock(monkeypatch, jobs, now):
    """只替换 gui.jobs 看到的 time（不动全局 time 模块，免得 wait_for 的超时判断也被冻住）。"""
    import types
    stub = types.SimpleNamespace(time=now, monotonic=time.monotonic, sleep=time.sleep)
    monkeypatch.setattr(jobs, "time", stub)


def _finish_quick(gs, jobs, monkeypatch, argv, task="select"):
    make_project(gs.root)
    fake_command(monkeypatch, jobs, argv)
    job_id = jobs.start_job("p1", task)
    assert wait_for(lambda: get_job(gs, job_id)[1]["status"] != "running")
    return job_id


def test_task_labels_use_wizard_terms(jobs):
    assert jobs.TASK_LABELS == {"prepare": "分析", "build": "导出", "select": "重新选段",
                                "export": "生成 Windows 剪映包", "questions": "重新出题",
                                "preview": "生成预览片"}


def test_conflict_message_uses_new_label(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    jobs.start_job("p1", "prepare")  # 绕过 prepare 的告知 / Key 前置检查，这里只看冲突文案
    status, data = post_job(gui_server, task="select")
    assert status == 409 and "p1 · 分析" in data["error"]


def test_job_view_elapsed_grows_while_running_and_freezes_after(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    clock = {"now": 1000.0}
    _fake_clock(monkeypatch, jobs, lambda: clock["now"])
    status, data = post_job(gui_server, task="select")
    assert get_job(gui_server, data["job_id"])[1]["elapsed_s"] == 0
    clock["now"] = 1042.4
    assert get_job(gui_server, data["job_id"])[1]["elapsed_s"] == 42
    jobs.cancel_job(data["job_id"])
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "cancelled")
    frozen = get_job(gui_server, data["job_id"])[1]["elapsed_s"]
    clock["now"] = 9999.0
    assert get_job(gui_server, data["job_id"])[1]["elapsed_s"] == frozen


def test_busy_view_none_without_jobs_and_describes_running(gui_server, jobs, monkeypatch):
    assert jobs.busy_view() is None
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    _, data = post_job(gui_server, task="preview")
    assert jobs.busy_view() == {"id": data["job_id"], "task": "preview", "project": "p1",
                                "label": "生成预览片"}


def test_busy_view_none_after_finish(gui_server, jobs, monkeypatch):
    _finish_quick(gui_server, jobs, monkeypatch, [sys.executable, "-c", "print('ok')"])
    assert jobs.busy_view() is None


def test_project_job_detail_none_for_unknown_project(gui_server, jobs):
    assert jobs.project_job_detail("p1") is None


def test_project_job_detail_running_and_filter_by_task(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, LONG)
    job_id = jobs.start_job("p1", "prepare")
    detail = jobs.project_job_detail("p1")
    assert detail["id"] == job_id and detail["task"] == "prepare"
    assert detail["status"] == "running" and isinstance(detail["started"], float)
    assert detail["last_error"] is None
    assert jobs.project_job_detail("p1", task="build") is None
    assert jobs.project_job_detail("other") is None


def test_project_job_detail_keeps_last_error_line_after_failure(gui_server, jobs, monkeypatch):
    script = "print('[x] 第一个错误'); print('普通行'); print('[x] AI 理解失败：网络不通'); print('[退出码]')"
    jid = _finish_quick(gui_server, jobs, monkeypatch,
                        [sys.executable, "-c", script + "; import sys; sys.exit(1)"], task="prepare")
    detail = jobs.project_job_detail("p1", task="prepare")
    assert detail["id"] == jid and detail["status"] == "failed"
    assert detail["last_error"] == "AI 理解失败：网络不通"


def test_project_job_detail_picks_latest_job(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    ids = []
    for started in (100.0, 200.0):
        _fake_clock(monkeypatch, jobs, lambda s=started: s)
        fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('x')"])
        _, data = post_job(gui_server, task="select")
        ids.append(data["job_id"])
        assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "done")
    assert jobs.project_job_detail("p1")["id"] == ids[1]


# ---------------------------------------------------------------- M16：信号注册不碰 Windows 上不存在的 SIGHUP
def test_server_main_registers_signals_via_getattr():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "gui" / "server.py").read_text(encoding="utf-8")
    assert "signal.SIGHUP" not in src and "signal.SIGTERM" not in src
    assert 'getattr(signal, name, None)' in src
