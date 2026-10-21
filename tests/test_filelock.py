# -*- coding: utf-8 -*-
"""pipeline.filelock：跨平台 flock 语义（共享 / 独占 / 非阻塞 / 解锁 / 跨进程），
外加 Windows 分支（LockFileEx / UnlockFileEx）的逻辑——用伪造的 kernel32 在任何平台上都能测。"""
import ctypes
import errno
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pipeline import filelock

ROOT = str(Path(__file__).resolve().parent.parent)


@pytest.fixture
def two_fds(tmp_path):
    path = tmp_path / "x.lock"
    a = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    b = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    yield a, b
    for fd in (a, b):
        try:
            filelock.flock(fd, filelock.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def test_constants_match_linux_and_mac_values():
    assert (filelock.LOCK_SH, filelock.LOCK_EX, filelock.LOCK_NB, filelock.LOCK_UN) == (1, 2, 4, 8)


def test_shared_locks_coexist_on_two_fds(two_fds):
    a, b = two_fds
    filelock.flock(a, filelock.LOCK_SH | filelock.LOCK_NB)
    filelock.flock(b, filelock.LOCK_SH | filelock.LOCK_NB)


def test_exclusive_nb_fails_while_shared_held(two_fds):
    a, b = two_fds
    filelock.flock(a, filelock.LOCK_SH)
    with pytest.raises(BlockingIOError):
        filelock.flock(b, filelock.LOCK_EX | filelock.LOCK_NB)


def test_exclusive_nb_fails_while_exclusive_held(two_fds):
    a, b = two_fds
    filelock.flock(a, filelock.LOCK_EX)
    with pytest.raises(BlockingIOError):
        filelock.flock(b, filelock.LOCK_EX | filelock.LOCK_NB)


def test_shared_nb_fails_while_exclusive_held(two_fds):
    a, b = two_fds
    filelock.flock(a, filelock.LOCK_EX)
    with pytest.raises(BlockingIOError):
        filelock.flock(b, filelock.LOCK_SH | filelock.LOCK_NB)


def test_unlock_then_lock_again_works(two_fds):
    a, b = two_fds
    filelock.flock(a, filelock.LOCK_EX)
    filelock.flock(a, filelock.LOCK_UN)
    filelock.flock(b, filelock.LOCK_EX | filelock.LOCK_NB)
    filelock.flock(b, filelock.LOCK_UN)
    filelock.flock(a, filelock.LOCK_EX | filelock.LOCK_NB)


def _readline_timeout(stream, timeout):
    out = []
    t = threading.Thread(target=lambda: out.append(stream.readline()), daemon=True)
    t.start()
    t.join(timeout)
    assert out, "子进程没有在限时内输出"
    return out[0].strip()


def _lock_eventually(fd, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        try:
            filelock.flock(fd, filelock.LOCK_EX | filelock.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def test_cross_process_exclusive_lock(tmp_path):
    path = tmp_path / "x.lock"
    code = ("import os, sys; sys.path.insert(0, %r)\n"
            "from pipeline import filelock\n"
            "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
            "filelock.flock(fd, filelock.LOCK_EX)\n"
            "print('locked', flush=True)\n"
            "sys.stdin.readline()\n" % ROOT)
    child = subprocess.Popen([sys.executable, "-c", code, str(path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        assert _readline_timeout(child.stdout, 10) == "locked"
        with pytest.raises(BlockingIOError):
            filelock.flock(fd, filelock.LOCK_EX | filelock.LOCK_NB)
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(10)
        _lock_eventually(fd)  # Windows 关句柄后释放是异步的
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(fd)


# ---------------------------------------------------------------- Windows 分支（伪 kernel32）
class FakeKernel32:
    def __init__(self, lock_result=1, unlock_result=1):
        self.calls = []
        self.lock_result = lock_result
        self.unlock_result = unlock_result

    def LockFileEx(self, handle, flags, reserved, lo, hi, overlapped):
        self.calls.append(("lock", handle, flags, reserved, lo, hi, overlapped))
        return self.lock_result

    def UnlockFileEx(self, handle, reserved, lo, hi, overlapped):
        self.calls.append(("unlock", handle, reserved, lo, hi, overlapped))
        return self.unlock_result


def _locker(k32, last_error=0):
    return filelock.Win32Locker(k32, get_osfhandle=lambda fd: 1000 + fd, get_last_error=lambda: last_error)


@pytest.mark.parametrize("mode, flags", [
    (filelock.WIN_LOCK_SH, 0),
    (filelock.WIN_LOCK_SH | filelock.WIN_LOCK_NB, 1),
    (filelock.WIN_LOCK_EX, 2),
    (filelock.WIN_LOCK_EX | filelock.WIN_LOCK_NB, 3),
])
def test_win_flags_computed_from_mode(mode, flags):
    k32 = FakeKernel32()
    _locker(k32).flock(7, mode)
    kind, handle, got, reserved, lo, hi, ov = k32.calls[0]
    assert (kind, handle, got, reserved, lo, hi) == ("lock", 1007, flags, 0, 1, 0)
    assert isinstance(ov._obj, filelock.Overlapped)  # byref(OVERLAPPED)


def test_win_lock_violation_is_blocking_io_error():
    k32 = FakeKernel32(lock_result=0)
    with pytest.raises(BlockingIOError):
        _locker(k32, last_error=33).flock(3, filelock.WIN_LOCK_EX | filelock.WIN_LOCK_NB)


def test_win_other_error_is_oserror_with_winerror_but_not_blocking():
    k32 = FakeKernel32(lock_result=0)
    with pytest.raises(OSError) as info:
        _locker(k32, last_error=5).flock(3, filelock.WIN_LOCK_EX)
    assert not isinstance(info.value, BlockingIOError)
    assert info.value.winerror == 5


def test_win_unlock_calls_unlock_file_ex():
    k32 = FakeKernel32()
    _locker(k32).flock(4, filelock.WIN_LOCK_UN)
    kind, handle, reserved, lo, hi, ov = k32.calls[0]
    assert (kind, handle, reserved, lo, hi) == ("unlock", 1004, 0, 1, 0)


def test_win_unlock_failure_raises_oserror():
    k32 = FakeKernel32(unlock_result=0)
    with pytest.raises(OSError):
        _locker(k32, last_error=158).flock(4, filelock.WIN_LOCK_UN)


def test_win_mode_without_lock_kind_is_einval():
    with pytest.raises(OSError) as info:
        _locker(FakeKernel32()).flock(4, filelock.WIN_LOCK_NB)
    assert info.value.errno == errno.EINVAL


def test_overlapped_struct_layout():
    assert [f[0] for f in filelock.Overlapped._fields_] == [
        "Internal", "InternalHigh", "Offset", "OffsetHigh", "hEvent"]
    assert ctypes.sizeof(filelock.Overlapped) == (32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20)


@pytest.mark.skipif(sys.platform != "win32", reason="真实 Windows 分支冒烟")
def test_real_windows_branch_smoke(two_fds):
    a, b = two_fds
    filelock.flock(a, filelock.LOCK_SH)
    filelock.flock(b, filelock.LOCK_SH)
    filelock.flock(b, filelock.LOCK_UN)
    with pytest.raises(BlockingIOError):
        filelock.flock(b, filelock.LOCK_EX | filelock.LOCK_NB)
    filelock.flock(a, filelock.LOCK_UN)
    filelock.flock(b, filelock.LOCK_EX)
