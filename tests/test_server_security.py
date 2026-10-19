"""GL-05（Host/token/Origin/Content-Type 守卫）与 GL-06（路由参数白名单）。"""
import json

import pytest

from conftest import call, make_project

SHOTS = [{"id": "sh01", "in": 0, "out": 1, "sub": "", "note": ""}]


def test_server_smoke(gui_server):
    status, body, _ = call(gui_server, "GET", "/api/projects")
    assert status == 200
    assert "projects" in json.loads(body)


# ---------------------------------------------------------------- GL-05 / KI-88
def test_session_secret_is_random_per_process(gui_server):
    from gui import session
    assert len(session.SECRET) >= 64


def test_api_get_without_token_forbidden(gui_server):
    status, body, _ = call(gui_server, "GET", "/api/projects", token=False)
    assert status == 403
    assert json.loads(body)["error"] == gui_server.module.TOKEN_EXPIRED_MSG


def test_api_get_wrong_token_forbidden(gui_server):
    from gui import session
    status, _, _ = call(gui_server, "GET", "/api/projects", token=False,
                        headers={"Cookie": f"{session.cookie_name(gui_server.port)}=x"})
    assert status == 403


def test_api_get_with_token_ok(gui_server):
    status, _, _ = call(gui_server, "GET", "/api/projects")
    assert status == 200


def test_api_post_without_token_forbidden_and_no_write(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, _, _ = call(gui_server, "POST", "/api/shots?project=p1",
                        {"shots": []}, token=False)
    assert status == 403
    assert (pdir / "shots.json").read_bytes() == before


def test_foreign_host_rejected_for_page_and_api(gui_server):
    evil = {"Host": f"evil.example:{gui_server.port}"}
    assert call(gui_server, "GET", "/", headers=evil)[0] == 403
    assert call(gui_server, "GET", "/api/projects", headers=evil)[0] == 403


def test_localhost_host_allowed(gui_server):
    status, _, _ = call(gui_server, "GET", "/",
                        headers={"Host": f"localhost:{gui_server.port}"})
    assert status == 200


def test_host_with_wrong_port_rejected(gui_server):
    status, _, _ = call(gui_server, "GET", "/", headers={"Host": "127.0.0.1:1"})
    assert status == 403


def test_cross_origin_post_rejected(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/browse/must",
                        {"project": "p1", "id": "S001", "must": True},
                        headers={"Origin": "http://evil.example"})
    assert status == 403


def test_null_origin_post_rejected(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/browse/must",
                        {"project": "p1", "id": "S001", "must": True},
                        headers={"Origin": "null"})
    assert status == 403


def test_same_origin_post_allowed(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/browse/must",
                        {"project": "p1", "id": "S001", "must": True},
                        headers={"Origin": f"http://127.0.0.1:{gui_server.port}"})
    assert status == 200


def test_post_requires_json_content_type(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/browse/must",
                        {"project": "p1", "id": "S001", "must": True},
                        headers={"Content-Type": "text/plain"})
    assert status == 415


def test_pick_post_with_empty_json_ok(gui_server, monkeypatch):
    monkeypatch.setattr(gui_server.module, "PICKER", lambda: ["/x.mp4"])
    status, body, _ = call(gui_server, "POST", "/api/pick", raw=b"{}")
    assert status == 200
    assert json.loads(body) == {"path": "/x.mp4"}


@pytest.mark.parametrize("path", ["/", "/static/index.html", "/static/browse.html",
                                  "/static/confirm.html", "/static/calibrate.html"])
def test_pages_need_cookie_and_hold_no_secret(gui_server, path):
    from gui import session
    assert call(gui_server, "GET", path, token=False)[0] == 403  # KI-88：「请从剪辑台 App 打开」
    status, body, _ = call(gui_server, "GET", path)
    assert status == 200
    assert session.SECRET.encode() not in body
    assert b"__AICUT_TOKEN__" not in body


def test_static_js_served_without_token(gui_server):
    status, body, headers = call(gui_server, "GET", "/static/common.js", token=False)
    assert status == 200
    assert "javascript" in headers["content-type"]
    assert b"X-AICUT-Token" not in body


@pytest.mark.parametrize("path", ["/", "/api/projects", "/api/nope"])
def test_security_headers(gui_server, path):
    _, _, headers = call(gui_server, "GET", path)
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["cross-origin-resource-policy"] == "same-origin"


def test_media_needs_host_and_cookie(gui_server):
    make_project(gui_server.root, **{"work/proxy.mp4": b"\x00" * 100})
    assert call(gui_server, "GET", "/media/p1/proxy", token=False)[0] == 403  # KI-88
    status, _, headers = call(gui_server, "GET", "/media/p1/proxy")
    assert status == 200
    assert headers["cross-origin-resource-policy"] == "same-origin"
    status, _, headers = call(gui_server, "GET", "/media/p1/proxy",
                              headers={"Range": "bytes=0-9"})
    assert status == 206
    assert headers["x-content-type-options"] == "nosniff"
    evil = {"Host": f"evil.example:{gui_server.port}"}
    assert call(gui_server, "GET", "/media/p1/proxy", headers=evil)[0] == 403


# ---------------------------------------------------------------- GL-06
@pytest.fixture
def recorder(gui_server, monkeypatch):
    calls = {"start_job": [], "run_aicut": []}

    def fake_start_job(*args):
        calls["start_job"].append(args)
        return "job1"

    def fake_run_aicut(args):
        calls["run_aicut"].append(args)
        return 0, ""

    monkeypatch.setattr(gui_server.module, "start_job", fake_start_job)
    monkeypatch.setattr(gui_server.module, "run_aicut", fake_run_aicut)
    return calls


def test_job_rejects_traversal_version(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job",
                        {"project": "p1", "task": "build", "version": "../../evil"})
    assert status == 400
    assert recorder["start_job"] == []


@pytest.mark.parametrize("name", ["-h", "../x", "", "nope"])
def test_job_rejects_bad_project(gui_server, recorder, name):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job", {"project": name, "task": "prepare"})
    assert status == 400
    assert recorder["start_job"] == []


def test_job_accepts_valid(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job",
                        {"project": "p1", "task": "build", "version": "v2"})
    assert status == 200
    assert recorder["start_job"] == [("p1", "build", ["--version", "v2"])]


def test_shots_rejects_traversal_id(gui_server):
    pdir = make_project(gui_server.root, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, _, _ = call(gui_server, "POST", "/api/shots?project=p1",
                        {"shots": [{"id": "../../x", "in": 0, "out": 1}]})
    assert status == 400
    assert (pdir / "shots.json").read_bytes() == before


def test_new_rejects_option_like_name(gui_server, recorder):
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": "--help", "material": "/x.mp4"})
    assert status == 400
    assert recorder["run_aicut"] == []


def test_new_rejects_unknown_preset(gui_server, recorder):
    status, body, _ = call(gui_server, "POST", "/api/new",
                           {"name": "ok", "material": "/x.mp4", "preset": "../../etc/x"})
    assert status == 400
    assert "预设" in json.loads(body)["error"]
    assert recorder["run_aicut"] == []


def test_new_uses_equals_form(gui_server, recorder, preset_dir):
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": "ok", "material": "-x.mp4", "preset": "测试预设",
                         "title": "-片名"})
    assert status == 200
    assert recorder["run_aicut"] == [
        ["new", "ok", "--no-input", "--material=-x.mp4", "--preset=测试预设", "--title=-片名"]]


def test_new_title_defaults_to_name(gui_server, recorder, preset_dir):
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": "ok", "material": "/x.mp4", "preset": "测试预设"})
    assert status == 200
    assert recorder["run_aicut"][0][-1] == "--title=ok"


def test_media_preview_rejects_bad_version(gui_server):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "GET", "/media/p1/preview/..")
    assert status == 400


@pytest.mark.parametrize("path", ["/api/confirm?project=-h", "/api/confirm?project=..",
                                  "/api/browse?project=-h", "/api/state?project=..",
                                  "/api/state?project=-h", "/api/calibrate?project=-h"])
def test_bad_project_query_is_rejected_not_crash(gui_server, path):
    status, body, _ = call(gui_server, "GET", path)
    assert status == 400
    assert "error" in json.loads(body)


# ---------------------------------------------------------------- KI-52：静态文件白名单
@pytest.fixture
def fake_static(gui_server, tmp_path, monkeypatch):
    d = tmp_path / "static_copy"
    d.mkdir()
    for name in ("index.html", "common.js", "prototype.html", "secret.txt"):
        (d / name).write_text(f"<!-- {name} __AICUT_TOKEN__ -->", encoding="utf-8")
    monkeypatch.setattr(gui_server.module, "STATIC", d)
    return d


@pytest.mark.parametrize("path", ["/static/prototype.html", "/static/secret.txt",
                                  "/static/../static_copy/index.html", "/static/sub/index.html"])
def test_unlisted_static_file_404(gui_server, fake_static, path):
    assert call(gui_server, "GET", path, token=False)[0] == 404


def test_listed_static_file_still_served(gui_server, fake_static):
    assert call(gui_server, "GET", "/static/index.html")[0] == 200
    assert call(gui_server, "GET", "/static/common.js", token=False)[0] == 200


def test_every_script_referenced_by_pages_is_whitelisted(gui_server):
    import re
    from gui import static_files
    pages = [n for n in static_files.STATIC_FILES if n.endswith(".html")]
    srcs = set()
    for page in pages:
        html = (gui_server.module.STATIC / page).read_text(encoding="utf-8")
        srcs |= set(re.findall(r'<script[^>]*\ssrc="/static/([^"]+)"', html))
    assert srcs and srcs <= static_files.STATIC_FILES
    for name in sorted(srcs | set(pages)):
        assert call(gui_server, "GET", f"/static/{name}")[0] == 200, name


# ---------------------------------------------------------------- KI-53：CSP 不再允许内联脚本
def test_csp_has_no_unsafe_inline_script(gui_server):
    _, _, headers = call(gui_server, "GET", "/", token=False)
    csp = headers["content-security-policy"]
    script = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
    assert "'unsafe-inline'" not in script and "'self'" in script
    assert "object-src 'none'" in csp
