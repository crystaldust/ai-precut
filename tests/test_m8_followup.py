"""M8 补充修复：结构不对的中间文件给人话（require_key）、切片缓存损坏、merge 不改入参、转写跳句提示持久化。"""
import argparse
import json
import sys

import pytest

import aicut
from gui import payloads
from pipeline import (classify, format_transcript, junk_detect, media_io, notices, questions, schema,
                      select, summarize, understand_audio, understand_text, understand_visual)


# ---------------------------------------------------------------- schema.require_key / read_field
def test_require_key_ok(tmp_path):
    assert schema.require_key({"segments": [1]}, "segments", tmp_path / "a.json") == [1]
    assert schema.require_key({"segments": {}}, "segments", tmp_path / "a.json", dict) == {}


@pytest.mark.parametrize("data", [{}, {"segments": None}, {"segments": {}}, {"segments": "x"}, []])
def test_require_key_bad_raises_corrupt_json_with_file_name(tmp_path, data):
    with pytest.raises(schema.CorruptJSON, match="segments_audio.json") as exc:
        schema.require_key(data, "segments", tmp_path / "segments_audio.json")
    assert "segments" in str(exc.value)


def test_read_field(tmp_path):
    p = tmp_path / "segments.json"
    p.write_text('{"segments": [{"id": "S001"}]}', encoding="utf-8")
    assert schema.read_field(p, "segments") == [{"id": "S001"}]
    p.write_text('{"count": 0}', encoding="utf-8")
    with pytest.raises(schema.CorruptJSON, match="segments.json"):
        schema.read_field(p, "segments")


# ---------------------------------------------------------------- 各读取点：缺 segments → CorruptJSON（不是 KeyError）
def _w(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


TEXT_OK = {"segments": [{"id": "S001", "start": 0, "end": 5, "text": "x", "level": 3}], "topics": []}


def _sites(tmp):
    bad = _w(tmp / "bad.json", {"count": 0})
    ok_text = _w(tmp / "text.json", TEXT_OK)
    ok_summary = _w(tmp / "summary.json", {"summary": "s"})
    return {
        "run_quality": lambda: understand_visual.run_quality(tmp / "p.mp4", bad, tmp / "o.json"),
        "audio": lambda: understand_audio.run(tmp / "a.wav", bad, tmp / "o.json"),
        "text": lambda: understand_text.run(bad, tmp / "o.json"),
        "classify_text": lambda: classify.run(bad, None, tmp / "o.json"),
        "classify_audio": lambda: classify.run(ok_text, bad, tmp / "o.json"),
        "classify_visual": lambda: classify.run(ok_text, None, tmp / "o.json",
                                                visual_path=_w(tmp / "v.json", {"segments": []})),
        "questions": lambda: questions.run(ok_summary, bad, tmp / "o.json"),
        "summarize": lambda: summarize.run(ok_text, bad, tmp / "o.json"),
        "select": lambda: select.run(bad, tmp / "none.json", tmp),
    }


@pytest.mark.parametrize("site", ["run_quality", "audio", "text", "classify_text", "classify_audio",
                                  "classify_visual", "questions", "summarize", "select"])
def test_missing_segments_is_corrupt_json(tmp_path, site, monkeypatch):
    monkeypatch.setattr(understand_visual, "sample_frames", lambda *a, **k: pytest.fail("不应抽帧"))
    with pytest.raises(schema.CorruptJSON):
        _sites(tmp_path)[site]()
    assert not (tmp_path / "o.json").exists()


def test_browse_scored_without_segments_is_corrupt(tmp_path):
    pdir = tmp_path / "p1"
    _w((pdir / "work").mkdir(parents=True) or pdir / "project.json", {"name": "p1", "material": "/a"})
    _w(pdir / "work/segments_scored.json", {"topics": []})
    with pytest.raises(schema.CorruptJSON, match="segments_scored.json"):
        payloads.browse(pdir, "p1")


def test_cli_score_missing_segments_dies_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", "/a.mov"))
    (pdir / "work").mkdir()
    _w(pdir / "work/segments_text.json", TEXT_OK)
    _w(pdir / "work/segments_audio.json", {"meta": {}})
    assert aicut.run_cli(["score", "p"]) == 1
    cap = capsys.readouterr()
    assert "segments_audio.json" in cap.out and "Traceback" not in cap.out + cap.err


# ---------------------------------------------------------------- 1. 切片缓存损坏 → 当空缓存重切
def test_corrupt_clip_manifest_recut_with_warning(tmp_path, monkeypatch, capsys):
    pdir = tmp_path / "p"
    clips = pdir / "work/clips"
    clips.mkdir(parents=True)
    (clips / "manifest.json").write_text("{坏", encoding="utf-8")
    cut = []

    def fake_ffmpeg(args, **kw):
        cut.append(args)
        from pathlib import Path
        Path(args[-1]).write_bytes(b"clip")
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg)
    aicut.ensure_clips(pdir, {"material": "/tmp/a.mp4"}, [{"id": "sh01", "in": 0.0, "out": 2.0}])
    out = capsys.readouterr().out
    assert "[!]" in out and "manifest.json" in out
    assert len(cut) == 1
    assert json.loads((clips / "manifest.json").read_text(encoding="utf-8"))["sh01"]


# ---------------------------------------------------------------- 4. merge 不改入参
def test_merge_does_not_mutate_input():
    raw = [(5.0, 6.0, "silence"), (0.0, 1.0, "black"), (1.1, 2.0, "black")]
    before = list(raw)
    out = junk_detect.merge(raw)
    assert raw == before
    assert (0.0, 2.0, "black") in out


# ---------------------------------------------------------------- 7. KI-24 跳句提示进警告栏
def test_dropped_subs_persisted_and_shown_in_project_warnings(tmp_path, monkeypatch):
    raw = _w(tmp_path / "raw.json", {"result": {"duration": 30, "subtitles": [
        {"start_time": 1, "end_time": 3, "text": "好"}, {"end_time": 2, "text": "缺起点"}]}})
    work = tmp_path / "work"
    monkeypatch.setattr(sys, "argv", ["format_transcript", str(raw), "-o", str(work)])
    format_transcript.main()
    data = json.loads((work / "segments.json").read_text(encoding="utf-8"))
    assert any("1 句缺少有效时间码" in w for w in data["warnings"])
    assert any("1 句缺少有效时间码" in w for w in notices.project_warnings(work))


def test_clean_transcript_has_no_warning(tmp_path, monkeypatch):
    raw = _w(tmp_path / "raw.json", {"result": {"duration": 30, "subtitles": [
        {"start_time": 1, "end_time": 3, "text": "好"}]}})
    work = tmp_path / "work"
    monkeypatch.setattr(sys, "argv", ["format_transcript", str(raw), "-o", str(work)])
    format_transcript.main()
    assert json.loads((work / "segments.json").read_text(encoding="utf-8"))["warnings"] == []
    assert notices.project_warnings(work) == []
