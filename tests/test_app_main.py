"""app/main：桌面入口先分发子任务、再起窗口；窗口关掉（含异常）一定停任务、关服务（KI-38）。"""
import runpy
import sys
import types

import pytest

from pipeline import proc

MAIN = proc.app_root() / "app" / "main.py"


class FakeWindow:
    def create_file_dialog(self, kind, **kw):
        return ("/v/a.mov",)


def fake_webview(start_exc=None):
    wv = types.ModuleType("webview")
    wv.OPEN_DIALOG, wv.calls = 10, []

    def create_window(title, url, **kw):
        wv.calls.append(("create", title, url))
        return FakeWindow()

    def start(**kw):
        wv.calls.append(("start", kw))
        if start_exc:
            raise start_exc

    wv.create_window, wv.start = create_window, start
    return wv


@pytest.fixture
def entry(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))  # main.py 开发模式会 sys.path.insert
    monkeypatch.setattr(sys, "argv", ["app"])


@pytest.mark.parametrize("start_exc", [None, RuntimeError("cocoa")])
def test_main_wires_window_and_always_cleans_up(entry, monkeypatch, start_exc):
    from gui import jobs, server
    wv = fake_webview(start_exc)
    monkeypatch.setitem(sys.modules, "webview", wv)
    seen = []
    srv = types.SimpleNamespace(shutdown=lambda: seen.append("srv.shutdown"))
    monkeypatch.setattr(server, "serve_in_background", lambda: (srv, "http://127.0.0.1:9/"))
    monkeypatch.setattr(server, "set_picker", lambda fn: seen.append(("picker", fn())))
    monkeypatch.setattr(server, "report_stale_job", lambda: seen.append("stale"))
    monkeypatch.setattr(jobs, "shutdown_all", lambda *a, **k: seen.append("jobs.shutdown"))
    monkeypatch.setattr(proc, "ensure_bundled_path", lambda: seen.append("path"))
    from app import cursor_mac
    monkeypatch.setattr(cursor_mac, "keep_cursor_visible", lambda: seen.append(("cursor", len(wv.calls))) or True)
    from app import motw_win
    monkeypatch.setattr(motw_win, "strip_download_marks", lambda *a, **k: seen.append(("motw", len(wv.calls))) or 0)
    ns = runpy.run_path(str(MAIN), run_name="app_main_under_test")
    if start_exc:
        with pytest.raises(RuntimeError):
            ns["main"]()
    else:
        ns["main"]()
    kind, title, url = wv.calls[0]
    assert (kind, title) == ("create", "AI 粗剪")
    assert url.startswith("http://127.0.0.1:9/?nonce=")  # KI-88：主窗口用一次性入口换 cookie
    from gui import session
    assert session.redeem(url.split("nonce=", 1)[1]) is True
    assert [c for c in wv.calls if c[0] == "create"] == [wv.calls[0]]  # M13：只有主窗口，没有子窗口了
    assert not hasattr(server, "set_window_opener")
    assert ("start", {"private_mode": False}) in wv.calls
    assert [c for c in seen if c[0:1] == ("cursor",)] == [("cursor", 0)]  # 只装一次，且在创建窗口之前
    assert [c for c in seen if c[0:1] == ("motw",)] == [("motw", 0)]  # 去下载标记在创建窗口、启动 webview 之前
    assert "path" in seen and ("picker", ["/v/a.mov"]) in seen and "stale" in seen
    assert seen[-2:] == ["jobs.shutdown", "srv.shutdown"]  # 关窗口 = 停任务，不留孤儿进程


def _run_with_start_error(monkeypatch, exc, platform):
    from app import motw_win
    from gui import jobs, server
    wv = fake_webview(exc)
    monkeypatch.setitem(sys.modules, "webview", wv)
    seen = []
    monkeypatch.setattr(server, "serve_in_background",
                        lambda: (types.SimpleNamespace(shutdown=lambda: seen.append("srv.shutdown")), "http://x/"))
    monkeypatch.setattr(server, "set_picker", lambda fn: None)
    monkeypatch.setattr(server, "report_stale_job", lambda: None)
    monkeypatch.setattr(jobs, "shutdown_all", lambda *a, **k: seen.append("jobs.shutdown"))
    monkeypatch.setattr(proc, "ensure_bundled_path", lambda: None)
    monkeypatch.setattr(motw_win, "strip_download_marks", lambda *a, **k: 0)
    monkeypatch.setattr(motw_win, "explain_load_failure", lambda e, **k: seen.append(("explain", str(e))))
    ns = runpy.run_path(str(MAIN), run_name="app_main_under_test")
    monkeypatch.setattr(sys, "platform", platform)  # 在 main() 调用时才生效，只影响 main 里的平台判断
    return ns, seen


def test_clr_load_error_on_win32_explains_exits_1_and_cleans_up(entry, monkeypatch):
    err = RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize from C:\\x\\Python.Runtime.dll")
    ns, seen = _run_with_start_error(monkeypatch, err, "win32")
    with pytest.raises(SystemExit) as exc:
        ns["main"]()
    assert exc.value.code == 1
    assert seen[0][0] == "explain" and seen[-2:] == ["jobs.shutdown", "srv.shutdown"]


def test_clr_load_error_off_win32_propagates(entry, monkeypatch):
    err = RuntimeError("Python.Runtime missing")
    ns, seen = _run_with_start_error(monkeypatch, err, "darwin")
    with pytest.raises(RuntimeError):
        ns["main"]()
    assert not any(isinstance(c, tuple) for c in seen)


def test_picker_returns_empty_list_when_dialog_cancelled(entry, monkeypatch):
    from gui import jobs, server
    wv = fake_webview()
    wv.create_window = lambda *a, **k: types.SimpleNamespace(create_file_dialog=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "webview", wv)
    picked = []
    monkeypatch.setattr(server, "serve_in_background",
                        lambda: (types.SimpleNamespace(shutdown=lambda: None), "http://x/"))
    monkeypatch.setattr(server, "set_picker", lambda fn: picked.append(fn()))
    monkeypatch.setattr(server, "report_stale_job", lambda: None)
    monkeypatch.setattr(jobs, "shutdown_all", lambda *a, **k: None)
    monkeypatch.setattr(proc, "ensure_bundled_path", lambda: None)
    runpy.run_path(str(MAIN), run_name="app_main_under_test")["main"]()
    assert picked == [[]]  # 取消选择 → 空列表，不是 None


def test_task_flag_exits_before_importing_webview(entry, monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)  # 一旦 import webview 就 ImportError
    monkeypatch.setattr(sys, "argv", ["app", "--aicut-cli", "list"])
    monkeypatch.setattr(proc, "dispatch", lambda argv: 7)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(MAIN), run_name="app_main_under_test")
    assert exc.value.code == 7
