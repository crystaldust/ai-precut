# -*- coding: utf-8 -*-
"""pipeline.plat：平台常量、pid_alive、process_image。
Windows 分支（OpenProcess / GetExitCodeProcess / QueryFullProcessImageNameW）用伪造 kernel32 在任何平台上测。"""
import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ctypes import wintypes

from pipeline import plat
from platform_marks import WIN_ONLY, posix_only


class FakeKernel32:
    """按 pid 表模拟进程：{pid: (exit_code, image)}；pid 不在表里 → OpenProcess 失败。"""

    def __init__(self, procs, denied=()):
        self.procs, self.denied = procs, set(denied)
        self.opened, self.closed, self.access = [], [], []
        self.last_error = 0

    def OpenProcess(self, access, inherit, pid):  # noqa: N802
        self.access.append(access)
        if pid in self.denied:
            self.last_error = plat.ERROR_ACCESS_DENIED
            return None
        if pid not in self.procs:
            self.last_error = 87  # ERROR_INVALID_PARAMETER：没有这个 pid
            return None
        self.opened.append(pid)
        return 1000 + pid

    def GetExitCodeProcess(self, handle, code_ref):  # noqa: N802
        # 真实声明是 POINTER(wintypes.DWORD)：传 c_uint32 的 byref 在 Windows 上会 ArgumentError
        assert isinstance(code_ref._obj, wintypes.DWORD)
        code_ref._obj.value = self.procs[handle - 1000][0]
        return 1

    def QueryFullProcessImageNameW(self, handle, flags, buf, size_ref):  # noqa: N802
        assert isinstance(size_ref._obj, wintypes.DWORD)
        assert isinstance(buf, ctypes.Array)
        image = self.procs[handle - 1000][1]
        if image is None:
            self.last_error = 5
            return 0
        buf.value = image
        size_ref._obj.value = len(image)
        return 1

    def CloseHandle(self, handle):  # noqa: N802
        self.closed.append(handle)
        return 1


def win(procs, denied=()):
    k32 = FakeKernel32(procs, denied)
    return plat.Win32Process(k32, lambda: k32.last_error), k32


# ---------------------------------------------------------------- 常量
def test_win32_constants():
    assert plat.PROCESS_QUERY_LIMITED_INFORMATION == 0x1000
    assert plat.STILL_ACTIVE == 259
    assert plat.CREATE_NO_WINDOW == 0x08000000


@posix_only("NO_WINDOW 在 POSIX 上必须是空字典，subprocess 才不会收到 creationflags")
def test_no_window_empty_on_posix():
    assert plat.NO_WINDOW == {} and plat.IS_WIN is False


@WIN_ONLY
def test_no_window_sets_creationflags_on_windows():
    assert plat.NO_WINDOW == {"creationflags": subprocess.CREATE_NO_WINDOW}


# ---------------------------------------------------------------- Windows 分支（伪 kernel32）
def test_win_pid_alive_true_while_still_active():
    w, k32 = win({42: (plat.STILL_ACTIVE, "C:\\x\\a.exe")})
    assert w.pid_alive(42) is True
    assert k32.access == [plat.PROCESS_QUERY_LIMITED_INFORMATION]
    assert k32.closed == [1042]  # 句柄必须关


def test_win_pid_alive_false_when_exited():
    w, k32 = win({42: (0, "C:\\x\\a.exe")})
    assert w.pid_alive(42) is False
    assert k32.closed == [1042]


def test_win_pid_alive_false_when_no_such_pid():
    w, _ = win({})
    assert w.pid_alive(4242) is False


def test_win_pid_alive_true_when_access_denied():
    w, _ = win({}, denied=[7])  # 与 POSIX 的 PermissionError 一致：存在但无权限 = 活着
    assert w.pid_alive(7) is True


@pytest.mark.parametrize("pid", [0, -1])
def test_win_pid_alive_false_for_non_positive(pid):
    w, k32 = win({})
    assert w.pid_alive(pid) is False and k32.access == []


def test_win_pid_alive_false_for_overflow_pid():
    w, _ = win({})
    assert w.pid_alive(2 ** 70) is False


def test_win_process_image_returns_path_and_closes_handle():
    w, k32 = win({5: (plat.STILL_ACTIVE, "C:\\Program Files\\剪辑台\\剪辑台.exe")})
    assert w.process_image(5) == "C:\\Program Files\\剪辑台\\剪辑台.exe"
    assert k32.closed == [1005]


def test_win_process_image_none_when_unavailable():
    w, k32 = win({5: (0, None)})
    assert w.process_image(5) is None and k32.closed == [1005]
    assert win({})[0].process_image(99) is None


def test_pid_alive_routes_to_win32_when_is_win(monkeypatch):
    w, _ = win({42: (plat.STILL_ACTIVE, "x")})
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setattr(plat, "_win32", lambda: w)

    def boom(*a):
        raise AssertionError("Windows 上绝不能调 os.kill(pid, 0)（它会终止进程）")

    monkeypatch.setattr(plat.os, "kill", boom)
    assert plat.pid_alive(42) is True
    assert plat.pid_alive(43) is False


def test_process_image_routes_to_win32_when_is_win(monkeypatch):
    w, _ = win({5: (plat.STILL_ACTIVE, "C:\\a\\python.exe")})
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setattr(plat, "_win32", lambda: w)
    assert plat.process_image(5) == "C:\\a\\python.exe"


# ---------------------------------------------------------------- 真实进程
def test_pid_alive_true_for_self():
    assert plat.pid_alive(os.getpid()) is True


def test_pid_alive_false_for_exited_process():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert plat.pid_alive(p.pid) is False


def test_process_image_of_self_mentions_python():
    image = plat.process_image(os.getpid())
    assert image and "python" in image.lower()


def test_process_image_none_for_exited_process():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert plat.process_image(p.pid) is None


# ---------------------------------------------------------------- POSIX 分支
@posix_only("os.kill(pid, 0) 探活语义")
@pytest.mark.parametrize("exc,expected", [(ProcessLookupError, False), (PermissionError, True),
                                          (OSError, False), (OverflowError, False)])
def test_posix_pid_alive_error_mapping(monkeypatch, exc, expected):
    def fake_kill(pid, sig):
        assert sig == 0
        raise exc()

    monkeypatch.setattr(plat.os, "kill", fake_kill)
    assert plat.pid_alive(12345) is expected


@posix_only("ps 命令")
def test_posix_process_image_uses_same_ps_command(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return type("R", (), {"stdout": "/usr/bin/python aicut.py\n"})()

    monkeypatch.setattr(plat.subprocess, "run", fake_run)
    assert plat.process_image(77) == "/usr/bin/python aicut.py"
    assert seen["argv"] == ["ps", "-o", "command=", "-p", "77"]
    assert seen["kw"]["timeout"] == 5 and seen["kw"]["capture_output"] is True
    assert seen["kw"]["encoding"] == "utf-8" and seen["kw"]["errors"] == "replace"


@posix_only("ps 命令")
def test_posix_process_image_none_when_ps_fails(monkeypatch):
    def boom(*a, **k):
        raise OSError("no ps")

    monkeypatch.setattr(plat.subprocess, "run", boom)
    assert plat.process_image(77) is None


# ---------------------------------------------------------------- 平台默认目录（M16 Task 4）
@pytest.fixture
def as_windows(monkeypatch):
    """在任何平台上走 Windows 分支的纯路径逻辑（Win32 调用不在这些函数里）。"""
    monkeypatch.setattr(plat, "IS_WIN", True)


def test_mac_dirs_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert plat.jianying_draft_root(home=tmp_path) == tmp_path / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
    assert plat.jianying_setting(home=tmp_path) == tmp_path / "Movies/JianyingPro/User Data/Config/globalSetting"
    assert plat.config_dir(home=tmp_path) == tmp_path / ".config" / "ai-cut"
    assert plat.log_dir(home=tmp_path) == tmp_path / "Library" / "Logs" / "剪辑台"
    assert plat.jianying_draft_root_rel() == Path("Movies/JianyingPro/User Data/Projects/com.lveditor.draft")


def test_windows_jianying_dirs_use_localappdata(as_windows, tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    assert plat.jianying_draft_root(env=env) == tmp_path / "Local/JianyingPro/User Data/Projects/com.lveditor.draft"
    assert plat.jianying_setting(env=env) == tmp_path / "Local/JianyingPro/User Data/Config/globalSetting"


def test_windows_dirs_fall_back_to_home_when_env_missing(as_windows, tmp_path):
    assert plat.jianying_draft_root(env={}, home=tmp_path) == (
        tmp_path / "AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft")
    assert plat.config_dir(env={}, home=tmp_path) == tmp_path / "AppData/Roaming/ai-cut"
    assert plat.log_dir(env={}, home=tmp_path) == tmp_path / "AppData/Local/剪辑台/logs"


def test_windows_explicit_home_ignores_localappdata(as_windows, tmp_path):
    """显式传 home（测试 / 调用方指定整套 home）时不看环境变量，整套目录跟着 home 走。"""
    env = {"LOCALAPPDATA": str(tmp_path / "elsewhere")}
    assert plat.jianying_setting(env=env, home=tmp_path) == (
        tmp_path / "AppData/Local/JianyingPro/User Data/Config/globalSetting")


def test_windows_config_and_log_dirs(as_windows, tmp_path):
    env = {"APPDATA": str(tmp_path / "Roam"), "LOCALAPPDATA": str(tmp_path / "Local")}
    assert plat.config_dir(env=env) == tmp_path / "Roam" / "ai-cut"
    assert plat.log_dir(env=env) == tmp_path / "Local" / "剪辑台" / "logs"
    assert plat.jianying_draft_root_rel() == Path("AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft")


def test_windows_empty_env_values_count_as_missing(as_windows, tmp_path):
    assert plat.config_dir(env={"APPDATA": ""}, home=tmp_path) == tmp_path / "AppData/Roaming/ai-cut"
