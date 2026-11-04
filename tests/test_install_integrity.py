"""安装完整性自检：missing_static、安装不完整页、启动日志。"""
import ast
import json
import logging
import sys

import pytest

from conftest import call
from gui import static_files
from gui.static_files import STATIC_FILES, missing_static


@pytest.fixture
def static_copy(tmp_path, gui_server, monkeypatch):
    dst = tmp_path / "static_copy"
    dst.mkdir()
    for name in STATIC_FILES:
        (dst / name).write_text("x", encoding="utf-8")
    (dst / "index.html").write_text("<html>REAL-INDEX</html>", encoding="utf-8")
    monkeypatch.setattr(gui_server.module, "STATIC", dst)
    return dst


# ---------------------------------------------------------------- missing_static
def test_missing_static_all_present(static_copy):
    assert missing_static(static_copy) == []


def test_missing_static_one_missing(static_copy):
    (static_copy / "simple-mode.js").unlink()
    assert missing_static(static_copy) == ["simple-mode.js"]


def test_missing_static_several_sorted(static_copy):
    for n in ("wizard.js", "app.css", "base.js"):
        (static_copy / n).unlink()
    assert missing_static(static_copy) == ["app.css", "base.js", "wizard.js"]


def test_missing_static_directory_counts_as_missing(static_copy):
    (static_copy / "main.js").unlink()
    (static_copy / "main.js").mkdir()
    assert missing_static(static_copy) == ["main.js"]


def test_static_files_module_is_stdlib_only():
    tree = ast.parse(open(static_files.__file__, encoding="utf-8").read())
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            mods.append(node.module.split(".")[0])
    assert mods and all(m in sys.stdlib_module_names for m in mods)


# ---------------------------------------------------------------- 页面
def test_authed_page_shows_install_incomplete(gui_server, static_copy):
    (static_copy / "simple-mode.js").unlink()
    status, body, headers = call(gui_server, "GET", "/")
    text = body.decode()
    assert status == 200
    assert "安装不完整" in text and "simple-mode.js" in text and "共缺少 1 个文件" in text
    assert "REAL-INDEX" not in text and "<script" not in text
    assert "Content-Security-Policy".lower() in headers
    assert headers["content-security-policy"] == gui_server.module.PAGE_CSP


def test_missing_name_is_escaped(gui_server, static_copy, monkeypatch):
    monkeypatch.setattr(gui_server.module, "missing_static", lambda root: ["<b>x</b>.js"])
    _, body, _ = call(gui_server, "GET", "/")
    text = body.decode()
    assert "&lt;b&gt;x&lt;/b&gt;.js" in text and "<b>x</b>" not in text


def test_long_list_is_truncated(gui_server, static_copy, monkeypatch):
    names = [f"f{i:02d}.js" for i in range(13)]
    monkeypatch.setattr(gui_server.module, "missing_static", lambda root: names)
    _, body, _ = call(gui_server, "GET", "/")
    text = body.decode()
    assert "f09.js" in text and "f10.js" not in text
    assert "共缺少 13 个文件" in text and "…另外还有 3 个" in text and "等 13 个" not in text


def test_complete_install_serves_index(gui_server, static_copy):
    status, body, _ = call(gui_server, "GET", "/")
    assert status == 200 and b"REAL-INDEX" in body


def test_unauthed_gets_gate_without_names(gui_server, static_copy):
    (static_copy / "simple-mode.js").unlink()
    status, body, headers = call(gui_server, "GET", "/", token=False)
    assert status == 403
    assert b"simple-mode.js" not in body and "安装不完整".encode() not in body
    assert "content-security-policy" in headers


def test_missing_asset_still_404_json(gui_server, static_copy):
    (static_copy / "simple-mode.js").unlink()
    status, body, _ = call(gui_server, "GET", "/simple-mode.js")
    assert status == 404
    assert json.loads(body) == {"error": "not found"}


def test_remedy_text_windows(gui_server, static_copy, win_platform):
    (static_copy / "simple-mode.js").unlink()
    _, body, _ = call(gui_server, "GET", "/")
    t = body.decode()
    assert "全部提取" in t and "隔离区" in t and "截图发给开发" in t
    assert "两层" not in t and "拖" in t and "里面还有" in t
    assert "AI粗剪.app" not in t


def test_remedy_text_mac(gui_server, static_copy, mac_platform):
    (static_copy / "simple-mode.js").unlink()
    _, body, _ = call(gui_server, "GET", "/")
    t = body.decode()
    assert "AI粗剪.app" in t and "截图发给开发" in t
    assert "全部提取" not in t


# ---------------------------------------------------------------- 启动日志
def _start(server, monkeypatch):
    class FakeSrv:
        def serve_forever(self):
            pass
    monkeypatch.setattr(server, "ThreadingHTTPServer", lambda *a, **k: FakeSrv())
    srv, _ = server.serve_in_background(0)
    return srv


def test_startup_logs_missing_files(gui_server, static_copy, monkeypatch, caplog):
    (static_copy / "simple-mode.js").unlink()
    with caplog.at_level(logging.ERROR):
        _start(gui_server.module, monkeypatch)
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(msgs) == 1 and "simple-mode.js" in msgs[0]
    assert str(static_copy) not in msgs[0]


def test_startup_silent_when_complete(gui_server, static_copy, monkeypatch, caplog):
    with caplog.at_level(logging.ERROR):
        _start(gui_server.module, monkeypatch)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
