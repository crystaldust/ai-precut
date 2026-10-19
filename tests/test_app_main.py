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

    def start():
        wv.calls.append(("start",))
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
    monkeypatch.setattr(server, "set_window_opener",
                        lambda fn: seen.append(("opener", fn("浏览素材", "http://127.0.0.1:9/b"))))
    monkeypatch.setattr(server, "report_stale_job", lambda: seen.append("stale"))
    monkeypatch.setattr(jobs, "shutdown_all", lambda *a, **k: seen.append("jobs.shutdown"))
    monkeypatch.setattr(proc, "ensure_bundled_path", lambda: seen.append("path"))
    ns = runpy.run_path(str(MAIN), run_name="app_main_under_test")
    if start_exc:
        with pytest.raises(RuntimeError):
            ns["main"]()
    else:
        ns["main"]()
    assert wv.calls[0] == ("create", "AI 粗剪", "http://127.0.0.1:9/")
    assert ("create", "浏览素材", "http://127.0.0.1:9/b") in wv.calls  # KI-36：子页面开新窗口
    assert ("start",) in wv.calls
    assert "path" in seen and ("picker", ["/v/a.mov"]) in seen and "stale" in seen
    assert seen[-2:] == ["jobs.shutdown", "srv.shutdown"]  # 关窗口 = 停任务，不留孤儿进程


def test_picker_returns_empty_list_when_dialog_cancelled(entry, monkeypatch):
    from gui import jobs, server
    wv = fake_webview()
    wv.create_window = lambda *a, **k: types.SimpleNamespace(create_file_dialog=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "webview", wv)
    picked = []
    monkeypatch.setattr(server, "serve_in_background",
                        lambda: (types.SimpleNamespace(shutdown=lambda: None), "http://x/"))
    monkeypatch.setattr(server, "set_picker", lambda fn: picked.append(fn()))
    monkeypatch.setattr(server, "set_window_opener", lambda fn: None)
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
