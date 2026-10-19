"""审查修复 H2：清理缓存删掉 work/clips 后，旧版本导出 Windows 包要能按这一版的分镜表重切缺失的切片。"""
import argparse
import json
from pathlib import Path

import pytest

import aicut
from pipeline import clips, media_io, schema


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    src = tmp_path / "src.mov"
    src.write_bytes(b"material")
    schema.save(pdir / "project.json", schema.default_project("p", str(src)))
    return pdir


SHOTS = [{"id": "S01", "in": 0.0, "out": 2.0, "sub": "", "note": ""},
         {"id": "S02", "in": 5.0, "out": 7.0, "sub": "", "note": ""}]


def fake_ffmpeg(calls):
    def run(args, **kw):
        calls.append(args)
        Path(args[-1]).write_bytes(b"clip")
    return run


def _version(pdir, with_snapshot=True):
    vdir = pdir / "output/v1"
    vdir.mkdir(parents=True)
    cdir = pdir / "work/clips"
    tl = {"project": {"name": "p"}, "video": [
        {"id": s["id"], "source": str(cdir / f"{s['id']}.mp4"), "in": 0.0, "out": 2.0, "timeline_in": 0.0}
        for s in SHOTS], "audio": [], "text": []}
    schema.write_json(vdir / "timeline.json", tl)
    if with_snapshot:
        clips.save_snapshot(vdir, SHOTS)
    return vdir


def _export(pdir, seen):
    def build(t, n, out):
        seen.append([Path(v["source"]).exists() for v in json.loads(Path(t).read_text())["video"]])
        return {"zip": str(out), "size": 1, "warnings": []}
    return build


def test_build_writes_version_shot_snapshot(project, monkeypatch):
    (project / "shots.json").write_text(json.dumps({"shots": SHOTS}))
    monkeypatch.setattr(aicut, "load_preset", lambda n: {})
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: project / "work/clips")
    monkeypatch.setattr(aicut, "actual_durations", lambda *a: {"S01": 2.0, "S02": 2.0})
    monkeypatch.setattr(aicut, "ensure_preview", lambda *a: "p.mp4")
    aicut.cmd_build(argparse.Namespace(name="p", version="v1", no_draft=True))
    assert clips.load_snapshot(project / "output/v1") == SHOTS


def test_export_recuts_only_missing_clips_after_clean(project, monkeypatch, tmp_path, capsys):
    vdir = _version(project)
    cdir = project / "work/clips"
    with media_io.atomic_output(cdir / "S01.mp4") as tmp:  # S01 还在（可能已被新一版重切过）：不动
        tmp.write_bytes(b"kept")
    calls, seen = [], []
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
    monkeypatch.setattr(aicut.export_draft, "build_windows_package", _export(project, seen))
    aicut.cmd_export(argparse.Namespace(name="p", timeline=str(vdir / "timeline.json"),
                                        package_name=None, out=str(tmp_path)))
    assert len(calls) == 1 and "5.000" in calls[0]
    assert (cdir / "S01.mp4").read_bytes() == b"kept" and seen == [[True, True]]
    assert "重新切" in capsys.readouterr().out


def test_export_without_snapshot_dies_with_clear_reason(project, monkeypatch, tmp_path, capsys):
    vdir = _version(project, with_snapshot=False)
    monkeypatch.setattr(aicut.export_draft, "build_windows_package",
                        lambda *a: pytest.fail("切片缺失时不应开始打包"))
    with pytest.raises(SystemExit):
        aicut.cmd_export(argparse.Namespace(name="p", timeline=str(vdir / "timeline.json"),
                                            package_name=None, out=str(tmp_path)))
    out = capsys.readouterr().out
    assert "重新生成成片" in out and "v1" in out


def test_clean_dialog_says_old_versions_recut_on_demand():
    js = (Path(__file__).resolve().parent.parent / "gui/static/index.js").read_text(encoding="utf-8")
    from pipeline import cache
    assert "旧版本" in cache.CLIPS_LABEL or "旧版本" in js
    assert "重新切" in js


# ---------------------------------------------------------------- 审查修复 M5：磁盘预检只算要重切的镜头
def test_pending_cut_seconds_skips_cached_clips(project):
    src = project.parent / "src.mov"
    cdir = project / "work/clips"
    with media_io.atomic_output(cdir / "S01.mp4") as tmp:
        tmp.write_bytes(b"c")
    from pipeline import build_documentary
    schema.write_json(cdir / "manifest.json", {"S01": build_documentary.clip_key(SHOTS[0], src)})
    assert clips.pending_cut_seconds(project, src, SHOTS) == 2.0  # 只有 S02 要切


def test_build_preflight_counts_only_pending(project, monkeypatch):
    (project / "shots.json").write_text(json.dumps({"shots": SHOTS}))
    monkeypatch.setattr(aicut, "load_preset", lambda n: {})
    monkeypatch.setattr(aicut.clips, "pending_cut_seconds", lambda *a: 0.0)
    seen = []
    monkeypatch.setattr(aicut.diskspace, "shortfall", lambda path, need, **k: seen.append(need))
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: project / "work/clips")
    monkeypatch.setattr(aicut, "actual_durations", lambda *a: {"S01": 2.0, "S02": 2.0})
    monkeypatch.setattr(aicut, "ensure_preview", lambda *a: "p.mp4")
    aicut.cmd_build(argparse.Namespace(name="p", version=None, no_draft=True))
    from pipeline import diskspace
    assert seen == [diskspace.need_for_build(0.0, 4.0)]


def test_prepare_skips_disk_check_when_media_done(project, monkeypatch, consented):
    from pipeline import diskspace
    monkeypatch.setattr(aicut.readiness, "missing_keys", lambda w: [])
    monkeypatch.setattr(aicut.media_io, "complete_or_adopt", lambda p, **k: True)
    seen = []
    monkeypatch.setattr(aicut.diskspace, "shortfall", lambda path, need, **k: seen.append(need))
    for step in aicut.readiness.PREPARE_STEPS:
        monkeypatch.setattr(aicut, f"cmd_{step}", lambda a: None)
    aicut.cmd_prepare(argparse.Namespace(name="p"))
    assert seen == [0]
