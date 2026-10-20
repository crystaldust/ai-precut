"""审查修复：写接口不建幽灵目录、请求字段类型校验、不断连、请求体上限、CSP。"""
import json
import socket

import pytest

from conftest import call, make_project

GOOD_SHOT = {"id": "sh01", "in": 0, "out": 1, "sub": "", "note": ""}


@pytest.fixture
def fake_aicut(gui_server, monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(gui_server.module, "run_aicut", run)
    return calls


# ---------------------------------------------------------------- HIGH 1：幽灵目录
@pytest.mark.parametrize("path,body", [
    ("/api/shots?project=nope", {"shots": [GOOD_SHOT]}),
    ("/api/confirm/answers", {"project": "nope", "answers": {}}),
    ("/api/browse/level", {"project": "nope", "id": "S001", "level": 3}),
    ("/api/browse/must", {"project": "nope", "id": "S001", "must": True}),
    ("/api/open", {"project": "nope"}),
    ("/api/calibrate", {"project": "nope", "calibration": {}}),
])
def test_write_endpoints_404_and_no_ghost_dir(gui_server, monkeypatch, path, body):
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda *a, **k: ran.append(a))
    status, resp, _ = call(gui_server, "POST", path, body)
    assert status == 404
    assert "error" in json.loads(resp)
    assert not (gui_server.root / "nope").exists()
    assert ran == []


# ---------------------------------------------------------------- HIGH 2：字段类型
@pytest.mark.parametrize("shot", [
    {"in": "abc", "out": 1}, {"in": None, "out": 1}, {"in": 1, "out": 1},
    {"in": -1, "out": 1}, {"in": 0, "out": 1, "sub": 3}, {"in": 0, "out": 1, "note": ["x"]},
])
def test_shots_bad_values_400_and_no_write(gui_server, shot):
    pdir = make_project(gui_server.root, shots=[GOOD_SHOT])
    before = (pdir / "shots.json").read_bytes()
    status, resp, _ = call(gui_server, "POST", "/api/shots?project=p1",
                           {"shots": [{"id": "sh01", **shot}]})
    assert status == 400
    assert "镜头" in json.loads(resp)["error"]
    assert (pdir / "shots.json").read_bytes() == before


@pytest.mark.parametrize("literal", [b"NaN", b"Infinity", b"-Infinity"])
def test_shots_non_finite_400(gui_server, literal):
    pdir = make_project(gui_server.root, shots=[GOOD_SHOT])
    before = (pdir / "shots.json").read_bytes()
    raw = b'{"shots":[{"id":"sh01","in":0,"out":' + literal + b"}]}"
    status, _, _ = call(gui_server, "POST", "/api/shots?project=p1", raw=raw)
    assert status == 400
    assert (pdir / "shots.json").read_bytes() == before


@pytest.mark.parametrize("title", [123, ["x"], "a/b", "a\\b", "a\x01b", "x" * 101])
def test_new_bad_title_400(gui_server, preset_dir, fake_aicut, title):
    status, resp, _ = call(gui_server, "POST", "/api/new",
                           {"name": "ok", "material": "/x.mp4", "preset": "测试预设",
                            "title": title})
    assert status == 400
    assert "片名" in json.loads(resp)["error"]
    assert fake_aicut == []


@pytest.mark.parametrize("name", [" ok", "ok ", 5])
def test_new_name_with_edge_whitespace_or_non_str_400(gui_server, preset_dir, fake_aicut, name):
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": name, "material": "/x.mp4", "preset": "测试预设"})
    assert status == 400
    assert fake_aicut == []


def test_get_unexpected_error_returns_500_json(gui_server, monkeypatch, capsys):
    def boom(_name):
        raise RuntimeError("boom")

    make_project(gui_server.root)
    monkeypatch.setattr(gui_server.module, "project_state", boom)
    status, resp, _ = call(gui_server, "GET", "/api/state?project=p1")
    assert status == 500
    assert "error" in json.loads(resp)


def test_post_unexpected_error_returns_500_json(gui_server, preset_dir, monkeypatch):
    def boom(_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(gui_server.module, "run_aicut", boom)
    status, resp, _ = call(gui_server, "POST", "/api/new",
                           {"name": "ok", "material": "/x.mp4", "preset": "测试预设"})
    assert status == 500
    assert "error" in json.loads(resp)


def _too_new(gs):
    pdir = make_project(gs.root)
    (pdir / "project.json").write_text(json.dumps(
        {"name": "p1", "material": "/tmp/a.mp4", "schema_version": 99}), encoding="utf-8")
    return pdir


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/state?project=p1", None),
    ("GET", "/api/calibrate?project=p1", None),
    ("POST", "/api/calibrate", {"project": "p1", "calibration": {}}),
])
def test_schema_too_new_409(gui_server, method, path, body):
    pdir = _too_new(gui_server)
    before = (pdir / "project.json").read_bytes()
    status, resp, _ = call(gui_server, method, path, body)
    assert status == 409
    assert "升级" in json.loads(resp)["error"]
    assert (pdir / "project.json").read_bytes() == before


@pytest.mark.parametrize("name", ["..", "-h", "a%2Fb"])
def test_state_invalid_name_400(gui_server, name):
    status, _, _ = call(gui_server, "GET", f"/api/state?project={name}")
    assert status == 400


def test_state_missing_project_404(gui_server):
    status, _, _ = call(gui_server, "GET", "/api/state?project=nope")
    assert status == 404


# ---------------------------------------------------------------- MEDIUM 4：请求体上限
def _raw_post(gs, headers: dict, body: bytes = b"") -> int:
    from gui import session
    lines = [f"POST /api/browse/must HTTP/1.1", f"Host: 127.0.0.1:{gs.port}",
             f"Cookie: {session.cookie_name(gs.port)}={session.SECRET}", "Content-Type: application/json",
             "Connection: close"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    data = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    with socket.create_connection(("127.0.0.1", gs.port), timeout=10) as sock:
        sock.sendall(data)
        resp = sock.recv(4096).decode("utf-8", "replace")
    return int(resp.split(" ", 2)[1])


def test_post_without_content_length_411(gui_server):
    make_project(gui_server.root)
    assert _raw_post(gui_server, {}) == 411


@pytest.mark.parametrize("value", ["-5", "abc", "1e3"])
def test_post_bad_content_length_400(gui_server, value):
    make_project(gui_server.root)
    assert _raw_post(gui_server, {"Content-Length": value}) == 400


def test_post_body_too_large_413(gui_server):
    make_project(gui_server.root)
    too_big = gui_server.module.MAX_BODY_BYTES + 1
    assert _raw_post(gui_server, {"Content-Length": str(too_big)}, b"{}") == 413


def test_handler_has_socket_timeout(gui_server):
    timeout = gui_server.module.Handler.timeout
    assert timeout is not None and 0 < timeout <= 120


# ---------------------------------------------------------------- MEDIUM 5：CSP
@pytest.mark.parametrize("path", ["/", "/static/browse.html", "/static/confirm.html"])
def test_html_has_csp(gui_server, path):
    _, _, headers = call(gui_server, "GET", path, token=False)
    csp = headers["content-security-policy"]
    for part in ("default-src 'self'", "object-src 'none'", "base-uri 'none'",
                 "frame-ancestors 'none'", "connect-src 'self'"):
        assert part in csp
