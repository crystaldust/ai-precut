# -*- coding: utf-8 -*-
"""跨平台文件锁（M16）：给 project_lock / shots_store / schema 提供同一套 flock 语义。

POSIX 直接复用 `fcntl.flock` 与 `LOCK_SH/EX/NB/UN`；Windows 没有 fcntl，用 kernel32 的
`LockFileEx` / `UnlockFileEx` 在文件第 0 字节起、长度 1 的区间上加锁，常量取值与 Linux / mac 的 fcntl 相同
（SH=1、EX=2、NB=4、UN=8），调用方不用分平台。

错误约定与 fcntl 一致：非阻塞拿不到锁 → `BlockingIOError`；其它失败 → `OSError`（Windows 上带 winerror）。
Windows 上同一进程两个 fd 对同一区间加锁同样互斥（与 flock 按打开文件描述计锁一致）；
但关闭句柄后锁的释放是异步的，所以调用方关 fd 前应先显式 `LOCK_UN`。

Win32 调用都经过 `Win32Locker`（kernel32 等依赖由构造参数注入），因此它的逻辑可在任何平台上用伪对象测试。
注意：不支持同一个 fd 上的锁升级 / 降级（SH→EX）。flock 是原子换锁，而 LockFileEx 按句柄叠加锁、
不会替换，所以先 `LOCK_UN` 再重新加锁。
fcntl 只在 POSIX 导入，ctypes.windll / msvcrt 只在 Windows 取用，互不污染。
"""
from __future__ import annotations

import ctypes
import errno
import sys
from collections.abc import Callable

# Windows 分支用的常量，与 Linux / mac 的 fcntl 数值一致（POSIX 下也保留，供测试引用）
WIN_LOCK_SH = 1
WIN_LOCK_EX = 2
WIN_LOCK_NB = 4
WIN_LOCK_UN = 8

LOCKFILE_FAIL_IMMEDIATELY = 0x1
LOCKFILE_EXCLUSIVE_LOCK = 0x2
ERROR_LOCK_VIOLATION = 33
ERROR_IO_PENDING = 997
LOCK_REGION_LEN = 1  # 固定锁第 0 字节起的 1 个字节


class Overlapped(ctypes.Structure):
    """Win32 OVERLAPPED（Offset=0 即锁区间起点）。"""
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


class Win32Locker:
    """用 LockFileEx / UnlockFileEx 实现 flock；依赖全部注入，便于在非 Windows 上测试。"""

    def __init__(self, kernel32, get_osfhandle: Callable[[int], int],
                 get_last_error: Callable[[], int]) -> None:
        self._k32 = kernel32
        self._get_osfhandle = get_osfhandle
        self._get_last_error = get_last_error

    def flock(self, fd: int, mode: int) -> None:
        handle = self._get_osfhandle(fd)
        overlapped = Overlapped()
        if mode & WIN_LOCK_UN:
            if not self._k32.UnlockFileEx(handle, 0, LOCK_REGION_LEN, 0, ctypes.byref(overlapped)):
                raise self._error()
            return
        if not mode & (WIN_LOCK_SH | WIN_LOCK_EX):
            raise OSError(errno.EINVAL, "flock: 需要 LOCK_SH / LOCK_EX / LOCK_UN 之一")
        flags = 0
        if mode & WIN_LOCK_EX:
            flags |= LOCKFILE_EXCLUSIVE_LOCK
        if mode & WIN_LOCK_NB:
            flags |= LOCKFILE_FAIL_IMMEDIATELY
        if not self._k32.LockFileEx(handle, flags, 0, LOCK_REGION_LEN, 0, ctypes.byref(overlapped)):
            raise self._error()

    def _error(self) -> OSError:
        code = self._get_last_error()
        # os.open 得到的 CRT 句柄不是 overlapped，理论上不会返回 997；若出现，非阻塞语义下同样按「拿不到锁」处理
        if code in (ERROR_LOCK_VIOLATION, ERROR_IO_PENDING):
            return BlockingIOError(errno.EAGAIN, "文件已被其它句柄锁定")
        if sys.platform == "win32":
            return OSError(None, "文件锁调用失败", None, code)
        exc = OSError(errno.EIO, "文件锁调用失败 (winerror %d)" % code)
        exc.winerror = code  # type: ignore[attr-defined]
        return exc


def _windows_flock() -> Callable[[int, int], None]:
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ov_ptr = ctypes.POINTER(Overlapped)
    k32.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, wintypes.DWORD, ov_ptr]
    k32.LockFileEx.restype = wintypes.BOOL
    k32.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, ov_ptr]
    k32.UnlockFileEx.restype = wintypes.BOOL
    return Win32Locker(k32, msvcrt.get_osfhandle, ctypes.get_last_error).flock


if sys.platform == "win32":
    LOCK_SH = WIN_LOCK_SH
    LOCK_EX = WIN_LOCK_EX
    LOCK_NB = WIN_LOCK_NB
    LOCK_UN = WIN_LOCK_UN
    flock = _windows_flock()
else:
    import fcntl
    LOCK_SH = fcntl.LOCK_SH
    LOCK_EX = fcntl.LOCK_EX
    LOCK_NB = fcntl.LOCK_NB
    LOCK_UN = fcntl.LOCK_UN
    flock = fcntl.flock
