"""M4 · GL-17 / GL-20：后台任务（互斥、取消、先校验后登记、子进程化）与新建项目。"""
import json
import subprocess
import sys
import time

import pytest

from conftest import call, make_project

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
    status, first = post_job(gui_server, task="build")
    assert status == 200
    status, second = post_job(gui_server, task="select")
    assert status == 409 and second["job_id"] == first["job_id"]
    assert "已有任务在运行" in second["error"] and "p1" in second["error"]
    status, other = call(gui_server, "POST", "/api/job", {"project": "p2", "task": "build"})[:2]
    assert status == 409  # 全局一次一个（MAX_ACTIVE_JOBS = 1）
    assert len(jobs.JOBS) == 1


# ---------------------------------------------------------------- 取消
def test_cancel_kills_process_group(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, GRANDCHILD)
    _, data = post_job(gui_server, task="build")
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
    status, _ = post_job(gui_server, task="build")
    assert status == 200  # 互斥已释放


def test_cancel_unknown_job_404(gui_server):
    status, _, _ = call(gui_server, "POST", "/api/job/deadbeef/cancel", {})
    assert status == 404


def test_cancel_finished_job_returns_false(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    _, data = post_job(gui_server, task="build")
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "done")
    status, raw, _ = call(gui_server, "POST", f"/api/job/{data['job_id']}/cancel", {})
    assert status == 200 and json.loads(raw)["ok"] is False


# ---------------------------------------------------------------- 状态与日志
def test_failed_job_status_and_exit_code(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "import sys; print('x'); sys.exit(2)"])
    _, data = post_job(gui_server, task="build")
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] != "running")
    job = get_job(gui_server, data["job_id"])[1]
    assert job["status"] == "failed" and job["exit"] == 2
    assert job["log"][-1] == "[退出码] 2"
    assert job["project"] == "p1" and job["task"] == "build"
    assert set(job) == {"status", "log", "exit", "task", "project"}  # 绝不序列化 Popen


def test_start_failure_is_reported_not_ghost(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, ["/nonexistent/aicut-binary"])
    _, data = post_job(gui_server, task="build")
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "failed")
    assert any("无法启动任务" in l for l in get_job(gui_server, data["job_id"])[1]["log"])


def test_state_reports_active_job(gui_server, jobs, monkeypatch):
    make_project(gui_server.root)
    make_project(gui_server.root, "p2")
    fake_command(monkeypatch, jobs, LONG)
    _, data = post_job(gui_server, task="build")
    state = json.loads(call(gui_server, "GET", "/api/state?project=p1")[1])
    assert state["job"] == {"id": data["job_id"], "task": "build"}
    other = json.loads(call(gui_server, "GET", "/api/state?project=p2")[1])
    assert other["job"] is None


# ---------------------------------------------------------------- 子进程化
def test_job_command_dev_and_frozen(jobs, monkeypatch):
    monkeypatch.setattr(jobs.proc, "FROZEN", False)
    assert jobs.job_command("prepare", "p1", [])[1].endswith("aicut.py")
    monkeypatch.setattr(jobs.proc, "FROZEN", True)
    assert jobs.job_command("prepare", "p1", ["--x"])[1:] == ["--aicut-cli", "prepare", "p1", "--x"]


def test_child_popen_flags(gui_server, jobs, monkeypatch):
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
    assert seen["start_new_session"] is True
    assert seen["env"]["PYTHONUNBUFFERED"] == "1"


def test_frozen_child_env_keeps_bundled_path_first(jobs, monkeypatch):
    monkeypatch.setattr(jobs.proc, "FROZEN", True)
    monkeypatch.setenv("PATH", "/app/bin:/usr/bin")
    assert jobs.child_env()["PATH"] == "/app/bin:/usr/bin"
    monkeypatch.setattr(jobs.proc, "FROZEN", False)
    assert jobs.child_env()["PATH"].startswith("/opt/homebrew/bin:")


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


def test_cancel_force_kills_group_even_if_main_child_already_exited(gui_server, jobs, monkeypatch):
    # aicut 收到 SIGTERM 退出了，但它拉起的 ffmpeg 不理 SIGTERM 且还占着输出管道：
    # 宽限期后必须 SIGKILL 整组，任务才能结束、互斥才能释放
    monkeypatch.setattr(jobs, "CANCEL_GRACE_S", 0.5)
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, STUBBORN)
    _, data = post_job(gui_server, task="build")
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
    _, data = post_job(gui_server, task="build")
    assert wait_for(lambda: jobs.JOBS[data["job_id"]]["popen"] is not None)
    for _ in range(3):
        call(gui_server, "POST", f"/api/job/{data['job_id']}/cancel", {})
    assert len(started) == 1


# ---------------------------------------------------------------- 审查修复 2：不留孤儿任务（HIGH-1）
def test_shutdown_all_kills_running_jobs_and_grandchildren(gui_server, jobs, monkeypatch):
    monkeypatch.setattr(jobs, "CANCEL_GRACE_S", 0.5)
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, STUBBORN)
    _, data = post_job(gui_server, task="build")
    job_id = data["job_id"]
    assert wait_for(lambda: any(l.startswith("child") for l in get_job(gui_server, job_id)[1]["log"]))
    grandchild = int(next(l for l in get_job(gui_server, job_id)[1]["log"]
                          if l.startswith("child")).split()[1])
    started = time.time()
    jobs.shutdown_all()
    assert time.time() - started < 5
    assert wait_for(lambda: not pid_alive(grandchild), timeout=3), "退出时孙进程也必须被杀"


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
    _, data = post_job(gui_server, task="build")
    assert wait_for(lambda: jobs.marker_path().exists())
    marker = json.loads(jobs.marker_path().read_text(encoding="utf-8"))
    assert marker["project"] == "p1" and marker["task"] == "build" and marker["pid"] > 0
    jobs.cancel_job(data["job_id"])
    assert wait_for(lambda: not jobs.marker_path().exists())


def _orphan(tmp_path):
    """一个「上次剪辑台留下的」还活着的任务进程（命令行里带 aicut 字样）。"""
    script = tmp_path / "aicut_orphan.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    return subprocess.Popen([sys.executable, str(script)], start_new_session=True)


def test_stale_job_from_previous_server_blocks_new_job(gui_server, jobs, monkeypatch, tmp_path):
    orphan = _orphan(tmp_path)
    try:
        jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
        jobs.marker_path().write_text(json.dumps(
            {"pid": orphan.pid, "project": "old", "task": "prepare", "server_pid": 1}),
            encoding="utf-8")
        make_project(gui_server.root)
        fake_command(monkeypatch, jobs, LONG)
        status, data = post_job(gui_server, task="build")
        assert status == 409 and str(orphan.pid) in data["error"] and "old" in data["error"]
        assert jobs.JOBS == {}
        assert jobs.stale_job()["pid"] == orphan.pid
    finally:
        orphan.kill()
        orphan.wait()


def test_dead_stale_marker_is_ignored_and_cleaned(gui_server, jobs, monkeypatch):
    jobs.marker_path().parent.mkdir(parents=True, exist_ok=True)
    jobs.marker_path().write_text(json.dumps({"pid": 999999, "project": "old", "task": "build"}),
                                  encoding="utf-8")
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('ok')"])
    status, _ = post_job(gui_server, task="build")
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
    post_job(gui_server, task="build")
    status, data = post_job(gui_server, task="select")
    assert status == 409 and data["task"] == "build" and data["project"] == "p1"


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


def test_reader_exception_reaps_child_and_fails_job(gui_server, jobs, monkeypatch):
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
