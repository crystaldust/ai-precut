# -*- coding: utf-8 -*-
"""pipeline.proctree：任务进程树。POSIX 用进程组；Windows 用 Job Object。
Windows 逻辑（Win32Jobs）用伪造 kernel32 在任何平台上测，真树用例标 WIN_ONLY / POSIX_ONLY。"""
import ctypes
import os
import signal
import subprocess
import sys
import time

import pytest

from pipeline import plat, proctree
from platform_marks import WIN_ONLY, posix_only

GRANDCHILD = ("import subprocess,sys,time;"
              "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
              "print(c.pid, flush=True); time.sleep(60)")


def wait_for(pred, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def pid_gone(pid):
    if plat.IS_WIN:
        return not plat.pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return not r.stdout.strip() or r.stdout.strip().startswith("Z")  # 僵尸也算已退出


# ---------------------------------------------------------------- 结构体布局（64 位）
@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="布局断言按 64 位")
def test_struct_layouts_match_win32_abi_64bit():
    assert ctypes.sizeof(proctree.IoCounters) == 48
    assert ctypes.sizeof(proctree.JobBasicLimitInformation) == 64
    assert ctypes.sizeof(proctree.JobExtendedLimitInformation) == 144
    assert ctypes.sizeof(proctree.JobBasicAccountingInformation) == 48
    ext = proctree.JobExtendedLimitInformation
    assert ext.BasicLimitInformation.offset == 0 and ext.IoInfo.offset == 64
    assert ext.ProcessMemoryLimit.offset == 112 and ext.PeakJobMemoryUsed.offset == 136
    basic = proctree.JobBasicLimitInformation
    assert basic.LimitFlags.offset == 16 and basic.MinimumWorkingSetSize.offset == 24
    assert basic.ActiveProcessLimit.offset == 40 and basic.PriorityClass.offset == 56
    assert proctree.JobBasicAccountingInformation.ActiveProcesses.offset == 40


def test_win32_constants():
    assert proctree.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x2000
    assert proctree.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS == 9
    assert proctree.JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS == 1
    assert proctree.CREATE_NEW_PROCESS_GROUP == 0x200


# ---------------------------------------------------------------- 伪 kernel32
class FakeKernel32:
    def __init__(self, fail=None, active=1):
        self.calls, self.fail, self.active = [], set(fail or ()), active
        self.last_error = 0
        self.limit_flags = None

    def _ok(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            self.last_error = 5
            return 0
        return 1

    def CreateJobObjectW(self, attrs, name):  # noqa: N802
        self.calls.append(("CreateJobObjectW", attrs, name))
        if "CreateJobObjectW" in self.fail:
            self.last_error = 5
            return None
        return 777

    def SetInformationJobObject(self, job, cls, info_ref, size):  # noqa: N802
        self.limit_flags = info_ref._obj.BasicLimitInformation.LimitFlags
        return self._ok("SetInformationJobObject", job, cls, size)

    def AssignProcessToJobObject(self, job, process):  # noqa: N802
        return self._ok("AssignProcessToJobObject", job, process)

    def TerminateJobObject(self, job, code):  # noqa: N802
        return self._ok("TerminateJobObject", job, code)

    def QueryInformationJobObject(self, job, cls, info_ref, size, ret_len):  # noqa: N802
        info_ref._obj.ActiveProcesses = self.active
        return self._ok("QueryInformationJobObject", job, cls, size)

    def CloseHandle(self, handle):  # noqa: N802
        return self._ok("CloseHandle", handle)

    def names(self):
        return [c[0] for c in self.calls]


class FakeNtdll:
    def __init__(self, k32, status=0):
        self.k32, self.status = k32, status

    def NtResumeProcess(self, handle):  # noqa: N802
        self.k32.calls.append(("NtResumeProcess", handle))
        return self.status


class FakePopen:
    pid = 4321
    _handle = 555

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


def jobs_api(resume_status=0, **kw):
    k32 = FakeKernel32(**kw)
    return proctree.Win32Jobs(k32, lambda: k32.last_error, FakeNtdll(k32, resume_status)), k32


def test_win_attach_creates_job_with_kill_on_close_and_assigns_process():
    api, k32 = jobs_api()
    job = api.attach(555)
    assert job == 777
    assert k32.names() == ["CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject"]
    assert k32.limit_flags == proctree.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert ("SetInformationJobObject", 777, 9, ctypes.sizeof(proctree.JobExtendedLimitInformation)) in k32.calls
    assert ("AssignProcessToJobObject", 777, 555) in k32.calls


@pytest.mark.parametrize("failing", ["CreateJobObjectW", "SetInformationJobObject",
                                     "AssignProcessToJobObject"])
def test_win_attach_failure_raises_oserror_and_closes_job(failing):
    api, k32 = jobs_api(fail=[failing])
    with pytest.raises(OSError):
        api.attach(555)
    if failing != "CreateJobObjectW":
        assert ("CloseHandle", 777) in k32.calls  # 不漏句柄


def test_win_resume_success_and_ntstatus_failure():
    api, k32 = jobs_api()
    api.resume(555)
    assert ("NtResumeProcess", 555) in k32.calls
    bad, _ = jobs_api(resume_status=-1073741790)  # STATUS_ACCESS_DENIED
    with pytest.raises(OSError):
        bad.resume(555)


def test_win_terminate_uses_exit_code_1():
    api, k32 = jobs_api()
    api.terminate(777)
    assert ("TerminateJobObject", 777, 1) in k32.calls


def test_win_terminate_failure_is_ignored_for_dead_job():
    api, _ = jobs_api(fail=["TerminateJobObject"])
    api.terminate(777)  # 任务早已结束：不抛


@pytest.mark.parametrize("active,expected", [(2, True), (1, True), (0, False)])
def test_win_alive_reads_active_processes(active, expected):
    api, k32 = jobs_api(active=active)
    assert api.alive(777) is expected
    assert ("QueryInformationJobObject", 777, 1,
            ctypes.sizeof(proctree.JobBasicAccountingInformation)) in k32.calls


def test_win_alive_false_when_query_fails():
    api, _ = jobs_api(fail=["QueryInformationJobObject"])
    assert api.alive(777) is False


# ---------------------------------------------------------------- 模块级 API（Windows 路径用伪 api）
@pytest.fixture
def fake_win(monkeypatch):
    api, k32 = jobs_api()
    monkeypatch.setattr(proctree.plat, "IS_WIN", True)
    monkeypatch.setattr(proctree, "_win_jobs", lambda: api)
    return k32


def test_spawn_kwargs_windows_starts_suspended(fake_win):
    assert proctree.CREATE_SUSPENDED == 0x4
    assert proctree.spawn_kwargs() == {
        "creationflags": (proctree.CREATE_NEW_PROCESS_GROUP | proctree.CREATE_SUSPENDED
                          | plat.CREATE_NO_WINDOW)}


def test_attach_windows_assigns_job_then_resumes(fake_win):
    tree = proctree.attach(FakePopen())
    assert tree.job == 777 and tree.pid == 4321 and tree.fallback is False
    assert ("AssignProcessToJobObject", 777, 555) in fake_win.calls
    assert fake_win.names() == ["CreateJobObjectW", "SetInformationJobObject",
                                "AssignProcessToJobObject", "NtResumeProcess"]  # 先入 Job，后恢复


def test_attach_windows_job_failure_falls_back_but_still_resumes(monkeypatch):
    api, k32 = jobs_api(fail=["AssignProcessToJobObject"])
    monkeypatch.setattr(proctree.plat, "IS_WIN", True)
    monkeypatch.setattr(proctree, "_win_jobs", lambda: api)
    tree = proctree.attach(FakePopen())
    assert tree.job is None and tree.fallback is True
    assert k32.names()[-1] == "NtResumeProcess"  # 不拒绝任务：进程必须被恢复


def test_attach_windows_resume_failure_kills_child_and_job(monkeypatch):
    api, k32 = jobs_api(resume_status=-1)
    monkeypatch.setattr(proctree.plat, "IS_WIN", True)
    monkeypatch.setattr(proctree, "_win_jobs", lambda: api)
    popen = FakePopen()
    with pytest.raises(OSError):
        proctree.attach(popen)
    assert popen.killed is True
    assert ("TerminateJobObject", 777, 1) in k32.calls and ("CloseHandle", 777) in k32.calls


def test_fallback_tree_uses_taskkill_and_pid_alive(monkeypatch):
    monkeypatch.setattr(proctree.plat, "IS_WIN", True)
    monkeypatch.setattr(proctree, "_win_jobs", lambda: pytest.fail("fallback 不碰 Job"))
    runs, alive = [], {"v": True}
    monkeypatch.setattr(proctree.subprocess, "run", lambda argv, **kw: runs.append((argv, kw)))
    monkeypatch.setattr(proctree.plat, "pid_alive", lambda pid: alive["v"])
    monkeypatch.setattr(proctree.plat, "NO_WINDOW", {"creationflags": plat.CREATE_NO_WINDOW})
    tree = proctree.Tree(pid=4321, fallback=True)
    proctree.terminate(tree)
    proctree.kill(tree)
    assert [r[0] for r in runs] == [["taskkill", "/T", "/F", "/PID", "4321"]] * 2
    kw = runs[0][1]
    assert kw["encoding"] == "utf-8" and kw["errors"] == "replace" and kw["timeout"] > 0
    assert kw["creationflags"] == plat.CREATE_NO_WINDOW  # 不弹黑窗
    assert proctree.alive(tree) is True
    alive["v"] = False
    assert proctree.alive(tree) is False


def test_fallback_taskkill_errors_are_swallowed(monkeypatch):
    monkeypatch.setattr(proctree.plat, "IS_WIN", True)

    def boom(*a, **k):
        raise OSError("no taskkill")

    monkeypatch.setattr(proctree.subprocess, "run", boom)
    proctree.terminate(proctree.Tree(pid=4321, fallback=True))


def test_concurrent_terminate_and_close_never_touch_closed_handle(fake_win, monkeypatch):
    import threading
    tree = proctree.attach(FakePopen())
    closed_at = []
    real = fake_win.TerminateJobObject

    def terminate(job, code):
        assert not closed_at, "关闭后还在用句柄"
        time.sleep(0.01)
        return real(job, code)

    monkeypatch.setattr(fake_win, "TerminateJobObject", terminate)
    real_close = fake_win.CloseHandle
    monkeypatch.setattr(fake_win, "CloseHandle", lambda h: (closed_at.append(h), real_close(h))[1])
    threads = [threading.Thread(target=proctree.terminate, args=(tree,)) for _ in range(5)]
    threads += [threading.Thread(target=proctree.close, args=(tree,)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert closed_at == [777]  # 只关一次


def test_terminate_and_kill_windows_both_terminate_job(fake_win):
    tree = proctree.attach(FakePopen())
    proctree.terminate(tree)
    proctree.kill(tree)
    assert fake_win.calls.count(("TerminateJobObject", 777, 1)) == 2


def test_alive_windows(fake_win):
    tree = proctree.attach(FakePopen())
    assert proctree.alive(tree) is True
    fake_win.active = 0
    assert proctree.alive(tree) is False


def test_close_windows_closes_handle_once_and_stops_everything(fake_win):
    tree = proctree.attach(FakePopen())
    proctree.close(tree)
    proctree.close(tree)  # 幂等
    assert fake_win.calls.count(("CloseHandle", 777)) == 1
    n = len(fake_win.calls)
    proctree.terminate(tree)
    assert proctree.alive(tree) is False
    assert len(fake_win.calls) == n  # 关闭后不再碰已关的句柄


def test_windows_never_uses_posix_signals(fake_win, monkeypatch):
    def boom(*a):
        raise AssertionError("Windows 路径不许用进程组信号")

    monkeypatch.setattr(os, "killpg", boom, raising=False)
    tree = proctree.attach(FakePopen())
    proctree.terminate(tree)
    proctree.kill(tree)
    proctree.alive(tree)


# ---------------------------------------------------------------- POSIX 路径（可在 mac 上直接测）
@posix_only("进程组 + killpg")
def test_posix_spawn_kwargs_is_new_session():
    assert proctree.spawn_kwargs() == {"start_new_session": True}


@posix_only("进程组 + killpg")
def test_posix_attach_records_pgid_equal_pid_without_syscalls(monkeypatch):
    monkeypatch.setattr(proctree, "_win_jobs", lambda: pytest.fail("POSIX 不该碰 Win32"))
    tree = proctree.attach(FakePopen())
    assert tree.pid == 4321 and tree.job is None


@posix_only("进程组 + killpg")
def test_posix_terminate_sigterm_kill_sigkill_alive_probe(monkeypatch):
    seen = []
    monkeypatch.setattr(proctree.os, "killpg", lambda pgid, sig: seen.append((pgid, sig)))
    tree = proctree.Tree(pid=99)
    proctree.terminate(tree)
    proctree.kill(tree)
    assert proctree.alive(tree) is True
    assert seen == [(99, signal.SIGTERM), (99, signal.SIGKILL), (99, 0)]


@posix_only("进程组 + killpg")
@pytest.mark.parametrize("pid", [0, -5])
def test_posix_non_positive_pid_never_signals(monkeypatch, pid):
    # killpg(0) 会杀到剪辑台自己所在的进程组
    monkeypatch.setattr(proctree.os, "killpg", lambda *a: pytest.fail("不能发信号"))
    tree = proctree.Tree(pid=pid)
    proctree.terminate(tree)
    proctree.kill(tree)
    assert proctree.alive(tree) is False


@posix_only("进程组 + killpg")
@pytest.mark.parametrize("exc", [ProcessLookupError, PermissionError])
def test_posix_signal_errors_are_ignored_and_mean_not_alive(monkeypatch, exc):
    def raiser(pgid, sig):
        raise exc()

    monkeypatch.setattr(proctree.os, "killpg", raiser)
    tree = proctree.Tree(pid=99)
    proctree.terminate(tree)
    proctree.kill(tree)
    assert proctree.alive(tree) is False


@posix_only("进程组 + killpg")
def test_posix_close_is_noop():
    proctree.close(proctree.Tree(pid=99))


@posix_only("进程组 + killpg：真实进程组")
def test_posix_terminate_kills_child_and_grandchild():
    child = subprocess.Popen([sys.executable, "-c", GRANDCHILD], stdout=subprocess.PIPE,
                             text=True, **proctree.spawn_kwargs())
    tree = proctree.attach(child)
    grandchild = int(child.stdout.readline())
    assert proctree.alive(tree) is True
    proctree.terminate(tree)
    child.wait(timeout=10)
    assert wait_for(lambda: pid_gone(grandchild))
    assert wait_for(lambda: proctree.alive(tree) is False)
    proctree.close(tree)


# ---------------------------------------------------------------- Windows 真实 Job Object
@WIN_ONLY
def test_win_terminate_kills_child_and_grandchild():
    child = subprocess.Popen([sys.executable, "-c", GRANDCHILD], stdout=subprocess.PIPE,
                             text=True, **proctree.spawn_kwargs())
    tree = proctree.attach(child)
    grandchild = int(child.stdout.readline())
    try:
        assert proctree.alive(tree) is True
        proctree.terminate(tree)
        child.wait(timeout=10)
        assert wait_for(lambda: pid_gone(grandchild))
        assert wait_for(lambda: proctree.alive(tree) is False)
    finally:
        proctree.close(tree)


@WIN_ONLY
def test_win_venv_python_trampoline_descendants_die_with_job():
    # venv 的 python.exe 是转发器：子进程会再拉起真正的解释器。挂起启动 + 先入 Job 后恢复，子孙不会逃逸
    child = subprocess.Popen([sys.executable, "-c", GRANDCHILD], stdout=subprocess.PIPE,
                             text=True, **proctree.spawn_kwargs())
    tree = proctree.attach(child)
    grandchild = int(child.stdout.readline())
    try:
        assert tree.fallback is False
        proctree.terminate(tree)
        child.wait(timeout=10)
        assert wait_for(lambda: pid_gone(grandchild))
    finally:
        proctree.close(tree)


@WIN_ONLY
def test_win_close_handle_ends_whole_tree():
    child = subprocess.Popen([sys.executable, "-c", GRANDCHILD], stdout=subprocess.PIPE,
                             text=True, **proctree.spawn_kwargs())
    tree = proctree.attach(child)
    grandchild = int(child.stdout.readline())
    proctree.close(tree)  # KILL_ON_JOB_CLOSE
    child.wait(timeout=10)
    assert wait_for(lambda: pid_gone(grandchild))
