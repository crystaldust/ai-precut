"""M12 收尾：KI-80（相对 staging）、KI-88（nonce → cookie）、KI-89（切片按内容命名）。"""
import json
from pathlib import Path

from pipeline import proc
from pipeline import to_jianying as tj
from tests.test_to_jianying import clip, full_timeline  # noqa: F401  复用夹具


# ---------------------------------------------------------------- KI-80
def test_ki80_relative_staging_dry_run_passes(tmp_path, monkeypatch, clip):  # noqa: F811
    tl = tmp_path / "timeline.json"
    tl.write_text(json.dumps(full_timeline(clip)), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out = proc.run_inprocess("pipeline.to_jianying",
                                   [str(tl), "--name", "T", "--staging", "stg", "--dry-run"])
    assert code == 0, out
    content = json.loads((tmp_path / "stg/T/draft_content.json").read_text(encoding="utf-8"))
    assert all(Path(m["path"]).is_absolute() for m in content["materials"]["videos"])


def test_ki80_bundle_media_writes_absolute_final_paths(tmp_path, monkeypatch, clip):  # noqa: F811
    d = tj.build_staging(full_timeline(clip), tmp_path / "stg", "T")
    monkeypatch.chdir(tmp_path)
    tj.bundle_media(d, Path("rel_root/T"))
    content = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
    paths = [m["path"] for m in content["materials"]["videos"]]
    assert paths and all(Path(p).is_absolute() for p in paths)
    assert all(p.startswith(str(tmp_path / "rel_root/T/Resources")) for p in paths)


# ---------------------------------------------------------------- KI-88：gui/session
def test_session_nonce_is_single_use():
    from gui import session
    n = session.issue_nonce()
    assert len(n) >= 32
    assert session.redeem(n) is True
    assert session.redeem(n) is False


def test_session_nonce_expires():
    from gui import session
    n = session.issue_nonce(now=lambda: 1000.0)
    assert session.redeem(n, now=lambda: 1000.0 + session.NONCE_TTL_S + 1) is False


def test_session_unknown_or_bad_nonce_rejected():
    from gui import session
    assert session.redeem("") is False
    assert session.redeem("nope") is False
    assert session.redeem(None) is False


def test_session_pending_nonces_are_capped():
    from gui import session
    first = session.issue_nonce()
    for _ in range(session.MAX_PENDING):
        session.issue_nonce()
    assert session.redeem(first) is False  # 最旧的被挤掉


def test_session_cookie_header_attributes():
    from gui import session
    h = session.cookie_header(8765)
    assert h.startswith(f"aicut_session_8765={session.SECRET};")
    for attr in ("Path=/", "HttpOnly", "SameSite=Strict"):
        assert attr in h
    assert "Max-Age" not in h and "Expires" not in h


def test_session_cookie_validation():
    from gui import session
    good = f"aicut_session_8765={session.SECRET}"
    assert session.has_valid_cookie(good, 8765)
    assert session.has_valid_cookie(f"x=1; {good}; y", 8765)
    assert session.has_valid_cookie(f"a; =; b==; {good}", 8765)
    assert not session.has_valid_cookie(None, 8765)
    assert not session.has_valid_cookie("", 8765)
    assert not session.has_valid_cookie(good, 8766)  # 另一个实例（端口）的 cookie
    assert not session.has_valid_cookie("aicut_session_8765=wrong", 8765)
    assert not session.has_valid_cookie("a; =; b==", 8765)


def test_session_entry_url_appends_nonce():
    from gui import session
    u = session.entry_url("http://127.0.0.1:9/")
    assert u.startswith("http://127.0.0.1:9/?nonce=")
    assert session.redeem(u.split("nonce=", 1)[1]) is True
    u2 = session.entry_url("http://127.0.0.1:9/static/confirm.html?project=a")
    assert u2.startswith("http://127.0.0.1:9/static/confirm.html?project=a&nonce=")


# ---------------------------------------------------------------- KI-88：服务端接线
def _get(gs, path, **kw):
    from conftest import call
    return call(gs, "GET", path, **kw)


def _nonce_of(url):
    return url.split("nonce=", 1)[1]


def test_page_without_cookie_shows_gate_without_secrets(gui_server):
    from gui import session
    status, body, headers = _get(gui_server, "/", token=False)
    assert status == 403
    text = body.decode("utf-8")
    assert "请从剪辑台 App 打开" in text
    assert session.SECRET not in text and "__AICUT_TOKEN__" not in text
    assert "script-src 'self'" in headers["content-security-policy"]
    assert "set-cookie" not in headers


def test_nonce_exchanged_once_for_cookie(gui_server):
    from gui import session
    nonce = _nonce_of(session.entry_url("http://x/"))
    status, _, headers = _get(gui_server, f"/?nonce={nonce}", token=False)
    assert status == 302 and headers["location"] == "/"
    cookie = headers["set-cookie"]
    assert cookie == session.cookie_header(gui_server.port)
    assert headers["cache-control"] == "no-store"
    assert _get(gui_server, f"/?nonce={nonce}", token=False)[0] == 403  # 一次性


def test_nonce_redirect_keeps_other_query(gui_server):
    from gui import session
    nonce = _nonce_of(session.entry_url("http://x/"))
    status, _, headers = _get(gui_server, f"/static/confirm.html?project=p1&nonce={nonce}",
                              token=False)
    assert status == 302
    assert headers["location"] == "/static/confirm.html?project=p1"


def test_page_with_cookie_has_no_secret(gui_server):
    from gui import session
    status, body, _ = _get(gui_server, "/")
    assert status == 200
    assert session.SECRET.encode() not in body and b"aicut-token" not in body


def test_used_nonce_with_valid_cookie_just_redirects(gui_server):
    status, _, headers = _get(gui_server, "/?nonce=already-used")
    assert status == 302 and headers["location"] == "/" and "set-cookie" not in headers


def test_wrong_host_does_not_consume_nonce(gui_server):
    from gui import session
    nonce = _nonce_of(session.entry_url("http://x/"))
    evil = {"Host": f"evil.example:{gui_server.port}"}
    assert _get(gui_server, f"/?nonce={nonce}", token=False, headers=evil)[0] == 403
    assert session.redeem(nonce) is True


def test_api_and_media_require_cookie(gui_server):
    from conftest import make_project
    make_project(gui_server.root, **{"work/proxy.mp4": b"\x00" * 100})
    for path in ("/api/projects", "/media/p1/proxy"):
        assert _get(gui_server, path, token=False)[0] == 403, path
        assert _get(gui_server, path)[0] == 200, path


def test_old_token_header_no_longer_accepted(gui_server):
    status, _, _ = _get(gui_server, "/api/projects", token=False,
                        headers={"X-AICUT-Token": "anything"})
    assert status == 403


def test_other_port_cookie_rejected(gui_server):
    from gui import session
    other = f"{session.cookie_name(gui_server.port + 1)}={session.SECRET}"
    assert _get(gui_server, "/api/projects", token=False, headers={"Cookie": other})[0] == 403


# ---------------------------------------------------------------- KI-89：切片按内容命名
import argparse  # noqa: E402

import pytest  # noqa: E402

import aicut  # noqa: E402
from pipeline import build_documentary, clips, media_io, schema  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    src = tmp_path / "src.mov"
    src.write_bytes(b"material")
    schema.save(pdir / "project.json", schema.default_project("p", str(src)))
    return pdir


def _shot(sid="S01", a=0.0, b=1.0):
    return {"id": sid, "in": a, "out": b, "sub": "", "note": ""}


def cutter(calls):
    """假 ffmpeg：切片内容 = 入点/时长参数，入出点不同则内容不同。"""
    def run(args, **kw):
        calls.append(args)
        Path(args[-1]).write_bytes(f"clip {args[1]} {args[3]}".encode())
    return run


def _build(pdir, shots, version, monkeypatch):
    (pdir / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
    monkeypatch.setattr(aicut, "load_preset", lambda n: {})
    monkeypatch.setattr(aicut, "ensure_preview", lambda *a: "p.mp4")
    monkeypatch.setattr(media_io, "duration_or_zero", lambda p, **k: 0.0)
    aicut.cmd_build(argparse.Namespace(name="p", version=version, no_draft=True))
    tl = json.loads((pdir / "output" / version / "timeline.json").read_text(encoding="utf-8"))
    return {v["id"]: Path(v["source"]) for v in tl["video"]}


def test_ki89_new_version_does_not_change_old_version_clip(project, monkeypatch):
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter(calls))
    v1 = _build(project, [_shot(b=1.0)], "v1", monkeypatch)
    before = v1["S01"].read_bytes()
    v2 = _build(project, [_shot(b=2.0)], "v2", monkeypatch)
    assert v1["S01"] != v2["S01"]
    assert v1["S01"].read_bytes() == before  # 旧版本引用的切片原封不动
    src = Path(aicut.cfg(project)["material"])
    assert v1["S01"].name == f"S01-{build_documentary.clip_key(_shot(b=1.0), src)}.mp4"
    assert v1["S01"].parent == project / "work/clips"


def test_ki89_same_shot_reuses_keyed_clip(project, monkeypatch):
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter(calls))
    _build(project, [_shot()], "v1", monkeypatch)
    _build(project, [_shot()], "v2", monkeypatch)
    assert len(calls) == 1


def _legacy(pdir, shot, body=b"legacy", key=None):
    cdir = pdir / "work/clips"
    with media_io.atomic_output(cdir / f"{shot['id']}.mp4") as tmp:
        tmp.write_bytes(body)
    src = Path(aicut.cfg(pdir)["material"])
    schema.write_json(cdir / "manifest.json",
                      {shot["id"]: key or build_documentary.clip_key(shot, src)})
    return cdir


def test_ki89_legacy_cache_is_adopted_without_recut(project, monkeypatch):
    cdir = _legacy(project, _shot())
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter(calls))
    paths = aicut.ensure_clips(project, aicut.cfg(project), [_shot()])
    assert calls == []
    assert paths["S01"].read_bytes() == b"legacy" and media_io.is_complete(paths["S01"])
    assert (cdir / "S01.mp4").read_bytes() == b"legacy"  # 旧版本时间线仍指向它
    assert schema.read_json(cdir / "manifest.json") == {
        "S01": build_documentary.clip_key(_shot(), Path(aicut.cfg(project)["material"]))}


def test_ki89_legacy_cache_with_other_key_is_recut(project, monkeypatch):
    _legacy(project, _shot(), key="0" * 12)
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter(calls))
    paths = aicut.ensure_clips(project, aicut.cfg(project), [_shot()])
    assert len(calls) == 1 and paths["S01"].read_bytes() != b"legacy"


def test_ki89_pending_cut_seconds_counts_keyed_and_legacy(project):
    src = Path(aicut.cfg(project)["material"])
    _legacy(project, _shot("S01", 0.0, 2.0))
    with media_io.atomic_output(project / "work/clips" / clips.clip_name(_shot("S02", 5.0, 8.0), src)) as t:
        t.write_bytes(b"k")
    shots = [_shot("S01", 0.0, 2.0), _shot("S02", 5.0, 8.0), _shot("S03", 10.0, 14.0)]
    assert clips.pending_cut_seconds(project, src, shots) == 4.0  # 只有 S03 要切


def test_ki89_export_recuts_keyed_clip_to_timeline_path(project, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter(calls))
    v1 = _build(project, [_shot(b=1.0), _shot("S02", 5.0, 6.0)], "v1", monkeypatch)
    v1["S02"].unlink()  # 「清理缓存」之类
    calls.clear()
    seen = []
    monkeypatch.setattr(aicut.export_draft, "build_windows_package",
                        lambda t, n, out: seen.append(v1["S02"].exists()) or
                        {"zip": str(out), "size": 1, "warnings": []})
    aicut.cmd_export(argparse.Namespace(name="p", timeline=str(project / "output/v1/timeline.json"),
                                        package_name=None, out=str(tmp_path)))
    assert len(calls) == 1 and Path(calls[0][-1]).suffix == ".mp4" and seen == [True]


def test_ki89_rebuild_same_version_prunes_unreferenced_clip(project, monkeypatch):
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter([]))
    old = _build(project, [_shot(b=1.0)], "v1", monkeypatch)["S01"]
    _age(old)  # 一小时内写的不清（复审 MEDIUM）
    new = _build(project, [_shot(b=2.0)], "v1", monkeypatch)["S01"]
    assert new.exists() and not old.exists()
    assert not media_io.done_marker(old).exists()


def _tl(pdir, version, names):
    cdir = pdir / "work/clips"
    schema.write_json(pdir / "output" / version / "timeline.json", {"video": [
        {"id": n, "source": str(cdir / n)} for n in names]})


def test_ki89_prune_keeps_every_referenced_clip(project):
    cdir = project / "work/clips"
    for n in ("S01-aaaaaaaaaaaa.mp4", "S01.mp4", "S02-bbbbbbbbbbbb.mp4"):
        with media_io.atomic_output(cdir / n) as t:
            t.write_bytes(b"x")
        _age(cdir / n)
    schema.write_json(cdir / "manifest.json", {})
    _tl(project, "v1", ["S01.mp4"])
    _tl(project, "v2", ["S01-aaaaaaaaaaaa.mp4"])
    assert clips.prune_unreferenced(project) == 1
    assert sorted(p.name for p in cdir.glob("*.mp4")) == ["S01-aaaaaaaaaaaa.mp4", "S01.mp4"]
    assert (cdir / "manifest.json").exists()


def test_ki89_prune_skips_when_any_timeline_unreadable(project):
    cdir = project / "work/clips"
    with media_io.atomic_output(cdir / "S09-cccccccccccc.mp4") as t:
        t.write_bytes(b"x")
    _age(cdir / "S09-cccccccccccc.mp4")
    _tl(project, "v1", [])
    (project / "output/v2").mkdir(parents=True)
    (project / "output/v2/timeline.json").write_text("{坏", encoding="utf-8")
    assert clips.prune_unreferenced(project) == 0
    assert (cdir / "S09-cccccccccccc.mp4").exists()


def test_ki89_prune_without_clips_dir_is_noop(project):
    assert clips.prune_unreferenced(project) == 0


def test_ki89_legacy_adoption_falls_back_to_copy(project, monkeypatch):
    _legacy(project, _shot())

    def no_link(a, b):
        raise OSError("cross-device")
    monkeypatch.setattr(clips.os, "link", no_link)
    monkeypatch.setattr(media_io, "run_ffmpeg", lambda *a, **k: pytest.fail("不该重切"))
    paths = aicut.ensure_clips(project, aicut.cfg(project), [_shot()])
    assert paths["S01"].read_bytes() == b"legacy"


def test_ki89_legacy_adoption_failure_recuts(project, monkeypatch):
    _legacy(project, _shot())

    def broken(a, b):
        raise OSError("disk")
    monkeypatch.setattr(clips.os, "link", broken)
    monkeypatch.setattr(clips.shutil, "copy2", broken)
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter(calls))
    aicut.ensure_clips(project, aicut.cfg(project), [_shot()])
    assert len(calls) == 1


def test_ki89_legacy_recut_keeps_manifest_key_consistent(project, monkeypatch, tmp_path):
    """旧命名补切后 manifest 的键跟着补切内容走，之后的出片才能放心复用它。"""
    cdir = project / "work/clips"
    vdir = project / "output/v1"
    shot = _shot(b=3.0)
    schema.write_json(vdir / "timeline.json", {"video": [{"id": "S01", "source": str(cdir / "S01.mp4")}]})
    clips.save_snapshot(vdir, [shot])
    cdir.mkdir(parents=True)
    schema.write_json(cdir / "manifest.json", {"S01": "0" * 12})
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter([]))
    src = Path(aicut.cfg(project)["material"])
    assert clips.restore_missing(project, vdir / "timeline.json", src, say=lambda m: None) == 1
    assert schema.read_json(cdir / "manifest.json") == {"S01": build_documentary.clip_key(shot, src)}


def test_ki89_restore_never_writes_non_clip_paths(project, monkeypatch):
    cdir = project / "work/clips"
    vdir = project / "output/v1"
    schema.write_json(vdir / "timeline.json", {"video": [
        {"id": "S01", "source": str(cdir / "manifest.json")}]})
    clips.save_snapshot(vdir, [_shot()])
    cdir.mkdir(parents=True)
    schema.write_json(cdir / "manifest.json", {"S01": "k"})
    monkeypatch.setattr(media_io, "run_ffmpeg", lambda *a, **k: pytest.fail("不该切"))
    src = Path(aicut.cfg(project)["material"])
    assert clips.restore_missing(project, vdir / "timeline.json", src) == 0
    assert schema.read_json(cdir / "manifest.json") == {"S01": "k"}


# ---------------------------------------------------------------- 安全复审跟进
def _age(path, seconds=7200):
    import os
    import time
    t = time.time() - seconds
    os.utime(path, (t, t))


def test_review_build_section_is_exclusive_per_project(project):
    from pipeline import project_lock
    with project_lock.build_section(project):
        with pytest.raises(project_lock.Busy):
            with project_lock.build_section(project, blocking=False):
                pass
    with project_lock.build_section(project, blocking=False):  # 释放后可再拿
        pass


def test_review_cmd_build_cuts_writes_and_prunes_inside_build_lock(project, monkeypatch):
    from pipeline import project_lock
    import contextlib
    events = []

    @contextlib.contextmanager
    def section(pdir, **kw):
        events.append("lock")
        yield
        events.append("unlock")
    monkeypatch.setattr(project_lock, "build_section", section)
    real_ensure, real_prune = aicut.ensure_clips, clips.prune_unreferenced
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: events.append("cut") or real_ensure(*a))
    monkeypatch.setattr(clips, "prune_unreferenced", lambda p: events.append("prune") or real_prune(p))
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter([]))
    _build(project, [_shot()], "v1", monkeypatch)
    assert events == ["lock", "cut", "prune", "unlock"]


def test_review_prune_keeps_recently_written_unreferenced_clip(project):
    cdir = project / "work/clips"
    with media_io.atomic_output(cdir / "S05-dddddddddddd.mp4") as t:
        t.write_bytes(b"x")
    _tl(project, "v1", [])
    assert clips.prune_unreferenced(project) == 0  # 可能是另一个出片任务刚切、还没写进时间线
    _age(cdir / "S05-dddddddddddd.mp4")
    assert clips.prune_unreferenced(project) == 1


def test_review_open_browser_failure_prints_link(monkeypatch, capsys):
    from gui import server
    monkeypatch.setattr(server.webbrowser, "open", lambda url: False)
    server.open_browser("http://127.0.0.1:9/")
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9/?nonce=" in out
    monkeypatch.setattr(server.webbrowser, "open", lambda url: True)
    server.open_browser("http://127.0.0.1:9/")
    assert "nonce=" not in capsys.readouterr().out


def test_review_restore_refuses_keyed_clip_when_material_changed(project, monkeypatch, tmp_path):
    monkeypatch.setattr(media_io, "run_ffmpeg", cutter([]))
    v1 = _build(project, [_shot()], "v1", monkeypatch)
    v1["S01"].unlink()
    other = tmp_path / "other.mov"
    other.write_bytes(b"new material")
    monkeypatch.setattr(media_io, "run_ffmpeg", lambda *a, **k: pytest.fail("不该切"))
    with pytest.raises(clips.ClipsUnavailable, match="v1"):
        clips.restore_missing(project, project / "output/v1/timeline.json", other, say=lambda m: None)
