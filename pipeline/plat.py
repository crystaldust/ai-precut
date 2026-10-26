# -*- coding: utf-8 -*-
"""平台差异的集中地（M16）：IS_WIN、无黑窗参数、进程存活探测、进程镜像名。

POSIX：`os.kill(pid, 0)` 探活（PermissionError = 别的用户的进程 = 活着），`ps -o command=` 取命令行。
Windows：`os.kill(pid, 0)` 会直接终止进程，绝不能用；改为 kernel32 的
`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetExitCodeProcess == STILL_ACTIVE`，
镜像名用 `QueryFullProcessImageNameW`。Win32 调用都经过 `Win32Process`（kernel32 由构造参数注入），
所以它的逻辑可以在任何平台上用伪对象测试；ctypes.windll 只在 Windows 上惰性取用。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath

IS_WIN = sys.platform == "win32"

CREATE_NO_WINDOW = 0x08000000  # 与 subprocess.CREATE_NO_WINDOW 同值（POSIX 的 subprocess 没有这个常量）
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5
IMAGE_BUFFER_CHARS = 32768  # QueryFullProcessImageNameW 的最长路径（含长路径前缀）
PS_TIMEOUT_S = 5

# 在 GUI 进程里起子进程时展开进 subprocess 调用：Windows 上不弹黑色控制台窗口，POSIX 上是空字典
NO_WINDOW: dict = {"creationflags": CREATE_NO_WINDOW} if IS_WIN else {}


# ---------------------------------------------------------------- 平台默认目录
# 路径逻辑（可在任何平台上测）：Windows 看 %LOCALAPPDATA% / %APPDATA%，缺失（或为空）时退回 home/AppData/…；
# 显式传 home（测试 / 调用方指定整套 home）时不看环境变量。AI_CUT_* 覆盖项由各调用方先处理。
JY_DRAFT_TAIL = Path("JianyingPro/User Data/Projects/com.lveditor.draft")
JY_SETTING_TAIL = Path("JianyingPro/User Data/Config/globalSetting")
MAC_JY_BASE = Path("Movies")           # 相对 home
WIN_LOCAL_REL = Path("AppData/Local")  # %LOCALAPPDATA% 缺失时相对 home
WIN_ROAMING_REL = Path("AppData/Roaming")
CONFIG_DIRNAME = "ai-cut"
LOG_DIRNAME = "剪辑台"
WIN_LOG_SUBDIR = "logs"


def _win_base(var: str, rel: Path, env, home) -> Path:
    """Windows 的 %VAR%；显式 home 或变量缺失 / 为空 → home/rel。"""
    if home is None:
        value = (os.environ if env is None else env).get(var)
        if value:
            return Path(value)
    return (Path.home() if home is None else Path(home)) / rel


def _mac_home(home) -> Path:
    return Path.home() if home is None else Path(home)


def local_appdata(env=None, home=None) -> Path:
    """%LOCALAPPDATA%（缺失 / 为空 / 显式 home → home/AppData/Local）。"""
    return _win_base("LOCALAPPDATA", WIN_LOCAL_REL, env, home)


WIN_DIR_FALLBACK = Path("C:/Windows")


def windows_dir(env=None) -> Path:
    """%SystemRoot%（缺失 / 为空 → C:/Windows）。系统工具一律用绝对路径调，不依赖 PATH。"""
    value = (os.environ if env is None else env).get("SystemRoot")
    return Path(value) if value else WIN_DIR_FALLBACK


PUBLIC_DIR_FALLBACK = Path("C:/Users/Public")


def public_dir(env=None) -> Path:
    """%PUBLIC%（缺失 / 为空 → C:/Users/Public）：Windows 上所有用户可写、路径恒为 ASCII 的位置。"""
    value = (os.environ if env is None else env).get("PUBLIC")
    return Path(value) if value else PUBLIC_DIR_FALLBACK


def explorer_exe(env=None) -> Path:
    return windows_dir(env) / "explorer.exe"


def tasklist_exe(env=None) -> Path:
    return windows_dir(env) / "System32" / "tasklist.exe"


def jianying_draft_root_rel() -> Path:
    """剪映默认草稿根相对 home 的部分（to_jianying.DEFAULT_DRAFT_ROOT）。"""
    return (WIN_LOCAL_REL if IS_WIN else MAC_JY_BASE) / JY_DRAFT_TAIL


def jianying_setting_rel() -> Path:
    return (WIN_LOCAL_REL if IS_WIN else MAC_JY_BASE) / JY_SETTING_TAIL


def _jy_base(env, home) -> Path:
    if IS_WIN:
        return _win_base("LOCALAPPDATA", WIN_LOCAL_REL, env, home)
    return _mac_home(home) / MAC_JY_BASE


def jianying_draft_root(env=None, home=None) -> Path:
    """剪映默认草稿根（Mac ~/Movies/…；Windows %LOCALAPPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft）。"""
    return _jy_base(env, home) / JY_DRAFT_TAIL


def jianying_setting(env=None, home=None) -> Path:
    """剪映 globalSetting（Qt INI，里面可能有自定义草稿位置）。"""
    return _jy_base(env, home) / JY_SETTING_TAIL


def config_dir(env=None, home=None) -> Path:
    """凭证 / 告知记录所在目录的默认位置：Mac ~/.config/ai-cut，Windows %APPDATA%/ai-cut。"""
    if IS_WIN:
        return _win_base("APPDATA", WIN_ROAMING_REL, env, home) / CONFIG_DIRNAME
    return _mac_home(home) / ".config" / CONFIG_DIRNAME


def log_dir(env=None, home=None) -> Path:
    """日志目录的默认位置：Mac ~/Library/Logs/剪辑台，Windows %LOCALAPPDATA%/剪辑台/logs。"""
    if IS_WIN:
        return _win_base("LOCALAPPDATA", WIN_LOCAL_REL, env, home) / LOG_DIRNAME / WIN_LOG_SUBDIR
    return _mac_home(home) / "Library" / "Logs" / LOG_DIRNAME


def is_absolute_path(value: str) -> bool:
    """value 在本平台上是不是绝对路径（Windows：盘符 / UNC，`C:/x` 与 `C:\\x` 都算；POSIX：以 / 开头）。"""
    return (PureWindowsPath if IS_WIN else PurePosixPath)(value).is_absolute()


def _dword(value: int = 0):
    """DWORD 实例：byref 传给声明为 POINTER(wintypes.DWORD) 的参数时类型必须一致（c_uint32 与 DWORD 是两个类型）。"""
    from ctypes import wintypes
    return wintypes.DWORD(value)


class Win32Process:
    """用 OpenProcess 等实现存活 / 镜像探测；依赖全部注入，便于在非 Windows 上测试。"""

    def __init__(self, kernel32, get_last_error: Callable[[], int]) -> None:
        self._k32 = kernel32
        self._get_last_error = get_last_error

    def _open(self, pid: int):
        """句柄；打不开返回 None（原因见 _get_last_error）。"""
        return self._k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid) or None

    def pid_alive(self, pid: int) -> bool:
        if pid <= 0 or pid > 0xFFFFFFFF:
            return False
        handle = self._open(pid)
        if handle is None:  # 无权限 = 进程存在（与 POSIX 的 PermissionError 一致）
            return self._get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = _dword()
            if not self._k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            self._k32.CloseHandle(handle)

    def process_image(self, pid: int) -> str | None:
        if pid <= 0 or pid > 0xFFFFFFFF:
            return None
        handle = self._open(pid)
        if handle is None:
            return None
        try:
            buf = ctypes.create_unicode_buffer(IMAGE_BUFFER_CHARS)
            size = _dword(IMAGE_BUFFER_CHARS)
            if not self._k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return buf.value or None
        finally:
            self._k32.CloseHandle(handle)


_WIN32: dict = {}


def _win32() -> Win32Process:
    """真实 kernel32 封装（仅 Windows 调用；惰性创建并缓存）。"""
    if "obj" not in _WIN32:
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL
        _WIN32["obj"] = Win32Process(k32, ctypes.get_last_error)
    return _WIN32["obj"]


def pid_alive(pid: int) -> bool:
    """pid 对应的进程还在不在（僵尸进程在 POSIX 上仍算在，调用方自己处理）。"""
    if IS_WIN:
        return _win32().pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # 别的用户的进程：活着
        return True
    except (OSError, OverflowError):
        return False
    return True


def process_image(pid: int) -> str | None:
    """进程的命令行（POSIX，`ps -o command=`）或可执行文件完整路径（Windows）；取不到返回 None。"""
    if IS_WIN:
        return _win32().process_image(pid)
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=PS_TIMEOUT_S, **NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip() or None
