"""app/motw_win：去掉下载标记（Zone.Identifier）并把 .NET 加载失败讲清楚。"""
import logging
import sys

import pytest

from app import motw_win

MSG = "Failed to resolve Python.Runtime.Loader.Initialize from C:\\x\\Python.Runtime.dll"


@pytest.fixture
def frozen_win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def _layout(tmp_path):
    exe_dir, bundle = tmp_path / "app", tmp_path / "app" / "_internal"
    files = ["ai-cut.exe", "readme.txt", "other/x.dll", "_internal/a.dll", "_internal/b.EXE",
             "_internal/c.pyd", "_internal/d.DLL", "_internal/e.txt", "_internal/sub/deep/f.dll"]
    for rel in files:
        p = exe_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return exe_dir, bundle


def test_noop_when_not_win32(tmp_path, monkeypatch):
    exe_dir, bundle = _layout(tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    calls = []
    assert motw_win.strip_download_marks(exe_dir, bundle, remove=calls.append) == 0
    assert calls == []


def test_noop_when_not_frozen(tmp_path, monkeypatch):
    exe_dir, bundle = _layout(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    calls = []
    assert motw_win.strip_download_marks(exe_dir, bundle, remove=calls.append) == 0
    assert calls == []


def _rel(calls, exe_dir):
    return sorted(c.removeprefix(str(exe_dir)).replace("\\", "/").lstrip("/") for c in calls)


def test_scope_is_exe_dir_top_level_plus_bundle_recursive(tmp_path, frozen_win):
    exe_dir, bundle = _layout(tmp_path)
    calls = []
    n = motw_win.strip_download_marks(exe_dir, bundle, remove=calls.append)
    assert _rel(calls, exe_dir) == sorted(f"{x}:Zone.Identifier" for x in (
        "ai-cut.exe", "_internal/a.dll", "_internal/b.EXE", "_internal/c.pyd", "_internal/d.DLL",
        "_internal/sub/deep/f.dll"))  # 旁边无关的 other/x.dll 不能动
    assert n == 6


def test_missing_stream_is_skipped_and_not_counted(tmp_path, frozen_win):
    exe_dir, bundle = _layout(tmp_path)

    def remove(p):
        if "a.dll" in p or "b.EXE" in p:
            raise FileNotFoundError(p)

    assert motw_win.strip_download_marks(exe_dir, bundle, remove=remove) == 4


def test_oserror_logs_first_detail_then_one_summary(tmp_path, frozen_win, caplog):
    exe_dir, bundle = _layout(tmp_path)

    def remove(p):
        if "_internal" in p and p.endswith(("a.dll:Zone.Identifier", "b.EXE:Zone.Identifier", "c.pyd:Zone.Identifier")):
            raise PermissionError("denied")

    with caplog.at_level(logging.INFO, logger="aicut"):
        n = motw_win.strip_download_marks(exe_dir, bundle, remove=remove)
    assert n == 3
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 2 and "另有 2 个文件清除失败" in warns[1]


def test_no_info_log_when_nothing_cleared(tmp_path, frozen_win, caplog):
    exe_dir, bundle = _layout(tmp_path)
    with caplog.at_level(logging.INFO, logger="aicut"):
        motw_win.strip_download_marks(exe_dir, bundle, remove=lambda p: (_ for _ in ()).throw(FileNotFoundError(p)))
    assert not caplog.records


def test_reparse_dirs_pruned_and_files_skipped(tmp_path, frozen_win, monkeypatch):
    exe_dir, bundle = _layout(tmp_path)
    monkeypatch.setattr(motw_win, "_is_reparse_point",
                        lambda p: p.endswith(("sub", "a.dll")) or p.endswith("ai-cut.exe"))
    calls = []
    n = motw_win.strip_download_marks(exe_dir, bundle, remove=calls.append)
    assert _rel(calls, exe_dir) == sorted(f"_internal/{x}:Zone.Identifier" for x in ("b.EXE", "c.pyd", "d.DLL"))
    assert n == 3


def test_is_reparse_point_false_for_plain_file_and_true_on_error(tmp_path):
    f = tmp_path / "a.dll"
    f.write_bytes(b"x")
    assert motw_win._is_reparse_point(str(f)) is False
    assert motw_win._is_reparse_point(str(tmp_path / "missing")) is True


def test_defaults_use_executable_dir_and_meipass(tmp_path, frozen_win, monkeypatch):
    exe_dir, bundle = _layout(tmp_path)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "ai-cut.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    calls = []
    assert motw_win.strip_download_marks(remove=calls.append) == 6
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert motw_win.strip_download_marks(remove=calls.append) == 6


@pytest.mark.parametrize("exc,expected", [
    (RuntimeError(MSG), True),
    (Exception("You must have pythonnet installed to use this"), True),
    (ImportError("clr_loader failed"), False),
    (Exception("pythonnet mentioned elsewhere"), False),
    (RuntimeError("cocoa"), False),
    (ValueError(""), False),
])
def test_is_clr_load_error(exc, expected):
    assert motw_win.is_clr_load_error(exc) is expected


def test_explain_shows_chinese_box_on_win32(monkeypatch, caplog):
    monkeypatch.setattr(sys, "platform", "win32")
    shown = []
    with caplog.at_level(logging.ERROR, logger="aicut"):
        motw_win.explain_load_failure(RuntimeError(MSG), message_box=lambda t, x: shown.append((t, x)))
    assert len(shown) == 1 and "解除锁定" in shown[0][1] and "4.7.2" in shown[0][1] and "杀毒软件" in shown[0][1]
    assert any(r.exc_info for r in caplog.records)


def test_explain_noop_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    shown = []
    motw_win.explain_load_failure(RuntimeError(MSG), message_box=lambda t, x: shown.append(x))
    assert shown == []


def test_explain_survives_failing_message_box(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def boom(t, x):
        raise OSError("no gui")

    motw_win.explain_load_failure(RuntimeError(MSG), message_box=boom)


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS 备用数据流只在 Windows 上有")
def test_real_ads_is_removed(tmp_path, monkeypatch):
    dll = tmp_path / "a.dll"
    dll.write_bytes(b"MZ")
    stream = str(dll) + ":Zone.Identifier"
    with open(stream, "w") as f:
        f.write("[ZoneTransfer]\nZoneId=3\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert motw_win.strip_download_marks(tmp_path, tmp_path / "_internal") == 1
    with pytest.raises(OSError):
        open(stream).close()
    assert dll.read_bytes() == b"MZ"
