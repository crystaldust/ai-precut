"""KI-36：pywebview 里 window.open 无效 → POST /api/window 由桌面壳在 App 内开新窗口。"""
import json

import pytest

from conftest import call, make_project


@pytest.fixture
def opener(gui_server, monkeypatch):
    from gui import desktop
    seen = []
    monkeypatch.setattr(desktop, "OPENER", None)
    return desktop, seen


def _open(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/window", {"project": "p1", "page": "browse", **body})
    return status, json.loads(raw)


def test_without_opener_tells_page_to_fall_back(gui_server, opener):
    make_project(gui_server.root)
    assert _open(gui_server) == (200, {"opened": False})


@pytest.mark.parametrize("page", ["browse", "calibrate", "confirm"])
def test_opener_gets_local_url_and_title(gui_server, opener, page):
    desktop, seen = opener
    make_project(gui_server.root, name="九月 一号")
    gui_server.module.set_window_opener(lambda title, url: seen.append((title, url)))
    status, data = _open(gui_server, project="九月 一号", page=page)
    assert status == 200 and data == {"opened": True}
    title, url = seen[0]
    assert url == (f"http://127.0.0.1:{gui_server.port}/static/{page}.html"
                   "?project=%E4%B9%9D%E6%9C%88%20%E4%B8%80%E5%8F%B7")
    assert "九月 一号" in title


def test_opener_failure_falls_back(gui_server, opener):
    make_project(gui_server.root)

    def boom(title, url):
        raise RuntimeError("webview gone")

    gui_server.module.set_window_opener(boom)
    assert _open(gui_server) == (200, {"opened": False})


@pytest.mark.parametrize("page", ["index", "../browse", "prototype", None, 3])
def test_unknown_page_is_400(gui_server, opener, page):
    make_project(gui_server.root)
    assert _open(gui_server, page=page)[0] == 400


def test_missing_or_bad_project(gui_server, opener):
    assert _open(gui_server, project="nope")[0] == 404
    assert _open(gui_server, project="-h")[0] == 400


def test_requires_token(gui_server, opener):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/window", {"project": "p1", "page": "browse"},
                        token=False)
    assert status == 403


def test_app_main_injects_window_opener():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(encoding="utf-8")
    assert "server.set_window_opener(" in src and "webview.create_window(" in src
