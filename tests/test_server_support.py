"""GL-19 / GL-04：诊断包导出与「关于 / 第三方许可」路由（同一套 Host/token 校验）与前端入口。"""
import json
import zipfile

import pytest

from conftest import call, make_project


@pytest.fixture
def gs(gui_server, tmp_path, monkeypatch):
    from gui import support
    out = tmp_path / "downloads"
    revealed = []
    monkeypatch.setattr(support.diagnostics, "default_out_dir", lambda: out)
    monkeypatch.setattr(support.diagnostics, "ffmpeg_info", lambda: None)
    monkeypatch.setattr(support, "reveal", lambda path: revealed.append(path))
    gui_server.out, gui_server.revealed = out, revealed
    return gui_server


def post(gs, body, **kw):
    status, raw, _ = call(gs, "POST", "/api/diagnostics", body, **kw)
    return status, json.loads(raw)


def test_diagnostics_requires_token(gs):
    status, _ = post(gs, {}, token=False)
    assert status == 403 and not gs.out.exists()


def test_diagnostics_rejects_cross_site(gs):
    status, _ = post(gs, {}, headers={"Origin": "http://evil.example"})
    assert status == 403


def test_diagnostics_with_project_writes_zip_and_reveals(gs):
    make_project(gs.root, **{"work/timings.json": '{"ingest": {"ok": true}}',
                             "work/transcript.md": "隐私原话"})
    status, body = post(gs, {"project": "p1"})
    assert status == 200 and body["ok"] is True
    zips = list(gs.out.glob("*.zip"))
    assert len(zips) == 1 and body["name"] == zips[0].name
    assert gs.revealed == [zips[0]]
    with zipfile.ZipFile(zips[0]) as z:
        names = z.namelist()
    assert "project/work/timings.json" in names and "meta.json" in names
    assert "path" not in body  # 不把完整路径（含用户名）回给前端


def test_diagnostics_without_project(gs):
    status, body = post(gs, {})
    assert status == 200 and len(list(gs.out.glob("*.zip"))) == 1


@pytest.mark.parametrize("name, code", [("../etc", 400), ("不存在", 404), (123, 400)])
def test_diagnostics_bad_project(gs, name, code):
    status, _ = post(gs, {"project": name})
    assert status == code and not gs.out.exists()


def test_diagnostics_write_failure_is_reported(gs, monkeypatch):
    from gui import support
    monkeypatch.setattr(support.diagnostics, "build_bundle",
                        lambda *a: (_ for _ in ()).throw(OSError("磁盘满")))
    status, body = post(gs, {})
    assert status == 500 and "导出失败" in body["error"] and gs.revealed == []


def test_about_returns_notices_and_version(gs):
    status, raw, _ = call(gs, "GET", "/api/about")
    body = json.loads(raw)
    assert status == 200
    assert "FFmpeg" in body["notices"] and "LGPL" in body["notices"]
    assert body["version"] == "0.1.0"


def test_about_requires_token(gs):
    status, _, _ = call(gs, "GET", "/api/about", token=False)
    assert status == 403


def test_about_missing_notices_degrades(gs, monkeypatch, tmp_path):
    from gui import support
    monkeypatch.setattr(support, "notices_path", lambda: tmp_path / "nope.txt")
    status, raw, _ = call(gs, "GET", "/api/about")
    assert status == 200 and json.loads(raw)["notices"] == support.NOTICES_MISSING


# ---------------------------------------------------------------- 前端入口
from test_frontend_jobs import NODE, STATIC, run_js  # noqa: E402


def test_sidebar_has_diagnostics_and_about_entries():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<script src="/static/support.js"></script>' in html
    more = (STATIC / "wizard.js").read_text(encoding="utf-8")  # M13：入口收进「更多」菜单
    assert "act: 'exportDiag'" in more and "act: 'openAbout'" in more


@pytest.mark.skipif(NODE is None, reason="需要 node")
def test_failed_job_actions_offer_diagnostics():
    html = run_js("jobActionsHtml('ended')", files=["jobs.js", "support.js"])
    assert 'data-act="exportDiag"' in html and "导出诊断包" in html
    assert 'data-act="exportDiag"' not in run_js("jobActionsHtml('running')", files=["jobs.js", "support.js"])


@pytest.mark.skipif(NODE is None, reason="需要 node")
def test_export_diag_posts_current_project_and_toasts():
    out = run_js("exportDiag().then(() => calls)", files=["jobs.js", "support.js"],
                 extra="window.__api = () => Promise.resolve({ok: true, name: '剪辑台诊断-1.zip', folder: 'Downloads'});")
    posted = [json.loads(c[2]) for c in out if c[0] == "api" and c[1] == "/api/diagnostics"]
    assert posted == [{"project": "p1"}]
    toasts = [c[1] for c in out if c[0] == "toast"]
    assert any("剪辑台诊断-1.zip" in t and "下载" in t for t in toasts)


@pytest.mark.skipif(NODE is None, reason="需要 node")
def test_export_diag_failure_toasts_error():
    out = run_js("exportDiag().then(() => calls)", files=["support.js"],
                 extra="window.__api = () => Promise.reject(new Error('导出失败：磁盘满'));")
    assert ["toast", "导出失败：磁盘满"] in [c[:2] for c in out]


@pytest.mark.skipif(NODE is None, reason="需要 node")
def test_about_escapes_notices():
    out = run_js("openAbout().then(() => el('modalBody').innerHTML)", files=["support.js"],
                 extra="window.__api = () => Promise.resolve({notices: '<b>x</b>', version: '0.1.0'});")
    assert "&lt;b&gt;x&lt;/b&gt;" in out and "<b>x</b>" not in out and "0.1.0" in out


def test_reveal_failure_still_reports_success(gs, monkeypatch):
    from gui import support

    def broken(path):
        raise OSError("no open")
    monkeypatch.setattr(support, "reveal", broken)
    status, body = post(gs, {})
    assert status == 200 and body["ok"] is True and body.get("revealed") is False
