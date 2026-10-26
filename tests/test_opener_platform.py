# -*- coding: utf-8 -*-
"""gui/opener 的语义函数（M16 Task 4）：Mac 命令逐字不变，Windows 走 startfile / explorer /select,。"""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gui import opener, support
from pipeline import plat


def _recorder(monkeypatch, code=0):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return SimpleNamespace(returncode=code, stderr=b"")
    monkeypatch.setattr(subprocess, "run", run)
    return calls


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", True)
    started = []
    monkeypatch.setattr(opener, "_startfile", lambda p: started.append(p), raising=False)
    return started


def test_mac_commands_are_byte_identical(mac, monkeypatch, tmp_path):
    calls = _recorder(monkeypatch)
    opener.open_path(tmp_path)
    opener.reveal(tmp_path / "a.zip")
    opener.open_app(Path("/Applications/X.app"))
    assert [c[0] for c in calls] == [["open", str(tmp_path)], ["open", "-R", str(tmp_path / "a.zip")],
                                     ["open", "-a", "/Applications/X.app"]]
    assert all(c[1]["timeout"] == opener.OPEN_TIMEOUT_S for c in calls)


@pytest.fixture
def jy_exe(win, monkeypatch, tmp_path):
    """Windows 上剪映 exe 的候选路径之一真实存在。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    exe = tmp_path / "Local/JianyingPro/Apps/JianyingPro.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return exe


def test_windows_open_path_and_app_use_startfile(win, jy_exe, monkeypatch, tmp_path):
    calls = _recorder(monkeypatch)
    opener.open_path(tmp_path)
    opener.open_app(jy_exe)
    assert win == [str(tmp_path), str(jy_exe)] and calls == []


def test_windows_open_path_only_accepts_existing_directories(win, tmp_path):
    f = tmp_path / "evil.bat"
    f.write_text("x", encoding="utf-8")
    for bad in (f, tmp_path / "nope", "http://example.com"):
        with pytest.raises(opener.OpenFailed):
            opener.open_path(bad)
    assert win == []  # startfile 一次都没调


def test_windows_open_app_only_accepts_known_existing_jianying_exe(win, jy_exe, tmp_path):
    other = tmp_path / "evil.exe"
    other.write_bytes(b"MZ")
    missing = tmp_path / "Local/JianyingPro/JianyingPro.exe"   # 是候选路径但文件不存在
    for bad in (other, missing, tmp_path):
        with pytest.raises(opener.OpenFailed):
            opener.open_app(bad)
    assert win == []


def test_windows_reveal_command_line_quotes_select_argument(win, monkeypatch, tmp_path):
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Win"))
    f = tmp_path / "a b" / "x.zip"
    f.parent.mkdir()
    f.write_bytes(b"z")
    calls = _recorder(monkeypatch, code=1)  # explorer 返回码不可靠：非 0 也不算失败
    opener.reveal(f)
    cmdline, kw = calls[0]
    assert cmdline == f'"{tmp_path / "Win" / "explorer.exe"}" /select,"{f}"'
    assert kw["timeout"] == opener.OPEN_TIMEOUT_S


def test_windows_reveal_missing_file_opens_parent_directory(win, monkeypatch, tmp_path):
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Win"))
    calls = _recorder(monkeypatch)
    opener.reveal(tmp_path / "gone.zip")
    assert calls[0][0] == f'"{tmp_path / "Win" / "explorer.exe"}" "{tmp_path}"'


def test_windows_reveal_nothing_to_show_is_openfailed(win, monkeypatch, tmp_path):
    _recorder(monkeypatch)
    with pytest.raises(opener.OpenFailed):
        opener.reveal(tmp_path / "no_dir" / "gone.zip")


def test_explorer_falls_back_to_c_windows(win, monkeypatch):
    monkeypatch.delenv("SystemRoot", raising=False)
    assert plat.explorer_exe() == Path("C:/Windows/explorer.exe")
    assert plat.tasklist_exe() == Path("C:/Windows/System32/tasklist.exe")


@pytest.mark.parametrize("call", ["open_path", "open_app"])
def test_windows_startfile_error_becomes_openfailed(win, jy_exe, monkeypatch, tmp_path, call):
    def boom(p):
        raise OSError("no association")
    monkeypatch.setattr(opener, "_startfile", boom)
    target = tmp_path if call == "open_path" else jy_exe
    with pytest.raises(opener.OpenFailed) as exc:
        getattr(opener, call)(target)
    assert "访达" not in str(exc.value)


def test_windows_explorer_missing_becomes_openfailed(win, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("explorer")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(opener.OpenFailed):
        opener.reveal(tmp_path)


def test_failure_messages_per_platform(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert opener.open_failed_msg() == opener.OPEN_FAILED_MSG == "没能打开：系统「打开」命令执行失败，请手动在访达或启动台里找"
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert "访达" not in opener.open_failed_msg() and "文件资源管理器" in opener.open_failed_msg()


def test_str_stderr_does_not_crash_logging(mac, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="LSOpen failed"))
    with pytest.raises(opener.OpenFailed):
        opener.run_open(["x"])


# ---------------------------------------------------------------- support.reveal / REVEAL_FAILED_MSG
def test_support_reveal_mac_uses_open_dash_R(mac, monkeypatch, tmp_path):
    calls = _recorder(monkeypatch)
    assert support.reveal(tmp_path / "x.zip") is True
    assert calls[0][0] == ["open", "-R", str(tmp_path / "x.zip")]


def test_support_reveal_false_when_opener_fails(mac, monkeypatch, tmp_path):
    _recorder(monkeypatch, code=1)
    assert support.reveal(tmp_path / "x.zip") is False


def test_reveal_failed_message_per_platform(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert support.reveal_failed_msg() == support.REVEAL_FAILED_MSG == "诊断包已生成，但没能在访达中打开，请到「下载」文件夹里找"
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert support.reveal_failed_msg() == "诊断包已生成，但没能在文件资源管理器中打开，请到「下载」文件夹里找"
