# -*- coding: utf-8 -*-
"""任务进程树（M16）：让「取消 / 退出时连同子孙进程（ffmpeg）一起停」在两个平台上用同一套接口。

POSIX：子进程自成进程组（`start_new_session`），树 = 进程组（pgid = pid）；
  terminate = killpg SIGTERM，kill = killpg SIGKILL，alive = killpg(pgid, 0)。
Windows：子进程起在新进程组里，随后放进一个 Job Object（KILL_ON_JOB_CLOSE）；
  terminate / kill 都是 TerminateJobObject（Windows 没有可靠的温和停止，半成品由 .aicut-partial 机制兜底），
  alive = Job 里的活动进程数 > 0，close 关句柄——剪辑台崩溃时系统会替我们关句柄，整棵树随之结束。
注意：Job 赋值发生在进程启动之后。venv 的 python.exe 是个转发器，会再拉起真正的解释器，
  若子进程一启动就跑，子孙可能赶在赋值前逃出 Job；所以 Windows 上以 CREATE_SUSPENDED 启动，
  先放进 Job 再用 ntdll.NtResumeProcess 恢复，成员关系在第一条指令执行前就建好了。
  Job 赋值失败时不拒绝任务：记警告、树标记为 fallback，取消 / 强杀改用 `taskkill /T /F /PID`。
Win32 调用都经过 `Win32Jobs`（kernel32 注入），逻辑可在任何平台用伪对象测试；
`os.killpg` / `signal.SIGKILL` 只在函数体内引用，模块导入在 Windows 上不会炸。
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import signal
import subprocess
import threading
from collections.abc import Callable

from pipeline import applog, plat

LOG = applog.get("proctree")
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_SUSPENDED = 0x00000004
TASKKILL_TIMEOUT_S = 10
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
TERMINATE_EXIT_CODE = 1


class IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),  # ULONG_PTR
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JobBasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JobBasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class Tree:
    """一棵任务进程树：POSIX 只有 pid（= pgid）；Windows 另有 Job 句柄，或 fallback（taskkill）。

    lock 是叶子锁：只保护 job 句柄的「读取 + 使用 + 清空」，持有期间不再拿别的锁，
    所以取消线程、强杀定时器、任务线程收尾可以并发调用而不会对已关闭的句柄操作 / 重复 CloseHandle。
    """

    __slots__ = ("pid", "job", "fallback", "lock")

    def __init__(self, pid: int, job: int | None = None, fallback: bool = False) -> None:
        self.pid, self.job, self.fallback = pid, job, fallback
        self.lock = threading.Lock()


class Win32Jobs:
    """用 Job Object 实现树的建立 / 终止 / 探活；依赖全部注入，便于在非 Windows 上测试。"""

    def __init__(self, kernel32, get_last_error: Callable[[], int], ntdll) -> None:
        self._k32 = kernel32
        self._get_last_error = get_last_error
        self._ntdll = ntdll

    def _error(self, what: str) -> OSError:
        code = self._get_last_error()
        if plat.IS_WIN:
            return OSError(None, what, None, code)
        exc = OSError(f"{what} (winerror {code})")
        exc.winerror = code  # type: ignore[attr-defined]
        return exc

    def attach(self, process_handle: int) -> int:
        """新建 Job（句柄关闭时杀光成员）并把进程放进去；返回 Job 句柄。"""
        job = self._k32.CreateJobObjectW(None, None)
        if not job:
            raise self._error("CreateJobObjectW 失败")
        try:
            info = JobExtendedLimitInformation()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self._k32.SetInformationJobObject(
                    job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info),
                    ctypes.sizeof(info)):
                raise self._error("SetInformationJobObject 失败")
            if not self._k32.AssignProcessToJobObject(job, process_handle):
                raise self._error("AssignProcessToJobObject 失败")
        except OSError:
            self._k32.CloseHandle(job)
            raise
        return job

    def resume(self, process_handle: int) -> None:
        """恢复 CREATE_SUSPENDED 启动的进程（NTSTATUS < 0 即失败）。"""
        status = self._ntdll.NtResumeProcess(process_handle)
        if status < 0:
            raise OSError(f"NtResumeProcess 失败 (NTSTATUS {status & 0xFFFFFFFF:#x})")

    def terminate(self, job: int) -> None:
        self._k32.TerminateJobObject(job, TERMINATE_EXIT_CODE)  # 树已结束时失败无妨

    def alive(self, job: int) -> bool:
        info = JobBasicAccountingInformation()
        if not self._k32.QueryInformationJobObject(
                job, JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS, ctypes.byref(info),
                ctypes.sizeof(info), None):
            return False
        return info.ActiveProcesses > 0

    def close(self, job: int) -> None:
        self._k32.CloseHandle(job)


_WIN_JOBS: dict = {}


def _win_jobs() -> Win32Jobs:
    """真实 kernel32 封装（仅 Windows 调用；惰性创建并缓存）。"""
    if "obj" not in _WIN_JOBS:
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.CreateJobObjectW.restype = h
        k32.SetInformationJobObject.argtypes = [h, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [h, h]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [h, wintypes.UINT]
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.QueryInformationJobObject.argtypes = [h, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.POINTER(wintypes.DWORD)]
        k32.QueryInformationJobObject.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [h]
        k32.CloseHandle.restype = wintypes.BOOL
        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = [h]
        ntdll.NtResumeProcess.restype = ctypes.c_long  # NTSTATUS
        _WIN_JOBS["obj"] = Win32Jobs(k32, ctypes.get_last_error, ntdll)
    return _WIN_JOBS["obj"]


# ------------------------------------------------------------------ 对外接口
def spawn_kwargs() -> dict:
    """`subprocess.Popen(..., **spawn_kwargs())`：让子进程成为可整树管理的根。

    Windows 上进程以挂起状态创建，必须紧接着调用 attach()（它负责恢复）；不经 attach 直接用会得到一个永远不动的进程。
    """
    if plat.IS_WIN:
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED | plat.CREATE_NO_WINDOW}
    return {"start_new_session": True}  # 自成进程组：killpg 才能连带杀掉 ffmpeg


def attach(popen) -> Tree:
    """Popen 刚返回后立刻调用（Windows：放进 Job 并恢复挂起的进程）。

    只有「恢复失败」才抛异常（此时进程已被杀掉，调用方应报告启动失败）；Job 赋值失败时退化为 fallback 树。
    `popen._handle` 是 CPython 在 Windows 上 Popen 的进程句柄（私有属性，3.11–3.12 稳定；升级 Python 时复核）。
    """
    if not plat.IS_WIN:
        return Tree(popen.pid)
    api = _win_jobs()
    handle = int(popen._handle)
    job = None
    try:
        job = api.attach(handle)
    except Exception as exc:  # noqa: BLE001 - 不因为 Job 不可用就拒绝任务
        LOG.warning("Job Object 分配失败，改用 taskkill /T 兜底：%s", exc)
    try:
        api.resume(handle)
    except Exception:
        if job is not None:
            with contextlib.suppress(Exception):
                api.terminate(job)
            with contextlib.suppress(Exception):
                api.close(job)
        with contextlib.suppress(Exception):
            popen.kill()
        raise
    return Tree(popen.pid, job, fallback=job is None)


def _taskkill(pid: int) -> None:
    """fallback：结束 pid 及其子孙（根进程已退出时只能尽力而为）。"""
    if pid <= 0:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=TASKKILL_TIMEOUT_S, **plat.NO_WINDOW)


def _killpg(pid: int, sig: int) -> None:
    if pid <= 0:  # killpg(0) 会杀到剪辑台自己所在的进程组
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _stop(tree: Tree, sig_name: str) -> None:
    with tree.lock:
        if tree.job is not None:
            _win_jobs().terminate(tree.job)
            return
    if tree.fallback:
        _taskkill(tree.pid)
    elif not plat.IS_WIN:
        _killpg(tree.pid, getattr(signal, sig_name))


def terminate(tree: Tree) -> None:
    """请整棵树停止：POSIX = SIGTERM；Windows = 立即终止 Job（fallback：taskkill /T /F）。"""
    _stop(tree, "SIGTERM")


def kill(tree: Tree) -> None:
    """强制结束整棵树：POSIX = SIGKILL；Windows 同 terminate。"""
    _stop(tree, "SIGKILL")


def alive(tree: Tree) -> bool:
    """树里还有没有活着的进程（主进程退了，ffmpeg 可能还在）。"""
    with tree.lock:
        if tree.job is not None:
            return _win_jobs().alive(tree.job)
    if tree.fallback:
        return plat.pid_alive(tree.pid)
    if plat.IS_WIN or tree.pid <= 0:
        return False
    try:
        os.killpg(tree.pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def close(tree: Tree) -> None:
    """释放资源（Windows 关 Job 句柄，剩余成员随之被杀）；可重复调用，只会关一次。"""
    with tree.lock:
        job, tree.job = tree.job, None
        if job is not None:
            _win_jobs().close(job)
