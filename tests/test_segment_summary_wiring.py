# -*- coding: utf-8 -*-
"""片段总结接进流水线：CLI 子命令、PREPARE_STEPS、② 进度行、③ browse 载荷、status 产物。"""
import argparse
import json

import pytest
from conftest import call, make_project

import aicut
from gui import analysis, payloads
from pipeline import cli_args, readiness, review, schema, usage
from pipeline import segment_summary as ss

pytestmark = pytest.mark.usefixtures("consented")

SEGS = [{"id": "S1", "start": 0, "end": 6, "level": 3, "text": "甲", "topic": "t"},
        {"id": "S2", "start": 10, "end": 16, "level": 3, "text": "乙", "topic": "t"}]
VSEGS = [{"id": "V001", "kind": "visual", "start": 20, "end": 30, "text": "", "level": 3, "label": "走廊",
          "visual": {"desc": "走廊", "issues": []}}]


class FakeDeepSeek:
    def __init__(self, model=None, **kw):
        self.model, self.last_usage = model, {}

    def chat_json(self, system, user, **kw):
        import re
        self.last_usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
        return {"segments": [{"id": i, "summary": f"总结{i}"} for i in re.findall(r"^(S\w+) ", user, re.M)]}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "DeepSeekClient", FakeDeepSeek)
    monkeypatch.setenv(usage.BUDGET_ENV, "0")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", str(tmp_path / "m.mov")))
    (pdir / "work").mkdir(exist_ok=True)
    return pdir


def args(**kw):
    return argparse.Namespace(name="p", **kw)


def test_prepare_steps_put_segment_summary_after_text():
    steps = readiness.PREPARE_STEPS
    assert steps[steps.index("text") + 1] == "segment_summary" and steps.count("segment_summary") == 1


def test_cmd_segment_summary_missing_input_is_quiet(project, capsys):
    aicut.cmd_segment_summary(args())
    assert capsys.readouterr().out == "" and not (project / "work" / ss.OUT_FILE).exists()


def test_cmd_segment_summary_writes_file_and_usage_stage(project):
    (project / "work" / "segments_text.json").write_text(json.dumps({"segments": SEGS}), encoding="utf-8")
    aicut.cmd_segment_summary(args())
    got = json.loads((project / "work" / ss.OUT_FILE).read_text(encoding="utf-8"))["items"]
    assert got["S1"]["summary"] == "总结S1"
    assert usage.load(project / "work")["by_stage"]["segment_summary"]["calls"] == 1


def test_cmd_segment_summary_without_consent_warns_and_sends_nothing(project, monkeypatch, capsys):
    from pipeline import consent
    monkeypatch.setattr(consent, "accepted", lambda: False)
    (project / "work" / "segments_text.json").write_text(json.dumps({"segments": SEGS}), encoding="utf-8")
    sent = []
    monkeypatch.setattr(aicut, "DeepSeekClient", lambda *a, **k: sent.append(1))
    aicut.cmd_segment_summary(args())  # 不能 sys.exit
    out = capsys.readouterr().out
    assert sent == [] and consent.CLI_REQUIRED_MSG in out and "不影响" in out
    assert not (project / "work" / ss.OUT_FILE).exists()


def test_cmd_segment_summary_without_key_warns_friendly(project, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    (project / "work" / "segments_text.json").write_text(json.dumps({"segments": SEGS}), encoding="utf-8")
    aicut.cmd_segment_summary(args())
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().out


def test_cmd_segment_summary_full_cache_hit_needs_no_consent(project, monkeypatch, capsys):
    from pipeline import consent
    (project / "work" / "segments_text.json").write_text(json.dumps({"segments": SEGS}), encoding="utf-8")
    aicut.cmd_segment_summary(args())
    capsys.readouterr()
    monkeypatch.setattr(consent, "accepted", lambda: False)
    aicut.cmd_segment_summary(args())
    out = capsys.readouterr().out
    assert "已是最新" in out and consent.CLI_REQUIRED_MSG not in out


def test_cmd_segment_summary_failure_only_warns(project, monkeypatch, capsys):
    (project / "work" / "segments_text.json").write_text(json.dumps({"segments": SEGS}), encoding="utf-8")

    class Boom(FakeDeepSeek):
        def chat_json(self, *a, **k):
            from pipeline.llm import LLMError
            raise LLMError("额度不足", status=402)
    monkeypatch.setattr(aicut, "DeepSeekClient", Boom)
    aicut.cmd_segment_summary(args())  # 不能抛 / 不能 sys.exit
    assert "额度不足" in capsys.readouterr().out


def test_prepare_succeeds_when_summary_round_fails(project, monkeypatch, capsys):
    monkeypatch.setattr(aicut.readiness, "missing_keys", lambda w, c=None: [])
    monkeypatch.setattr(aicut.media_io, "complete_or_adopt", lambda p, **k: True)
    monkeypatch.setattr(aicut.encode, "preflight", lambda: None)
    monkeypatch.setattr(aicut.diskspace, "shortfall", lambda *a, **k: None)
    monkeypatch.setattr(ss, "run", lambda *a, **k: {"done": 0, "failed": 2, "error": "挂了", "cached": 0})
    (project / "work" / "segments_text.json").write_text(json.dumps({"segments": SEGS}), encoding="utf-8")
    for step in aicut.readiness.PREPARE_STEPS:
        if step != "segment_summary":
            monkeypatch.setattr(aicut, f"cmd_{step}", lambda a: None)
    aicut.cmd_prepare(args())
    out = capsys.readouterr().out
    assert "挂了" in out and "前期处理完成" in out
    assert (project / "work" / "analysis_inputs.json").exists()


def test_segment_summary_step_parses_from_cli(project, monkeypatch):
    seen = []
    monkeypatch.setattr(aicut, "cmd_segment_summary", lambda a: seen.append(a.name))
    aicut.main(["segment_summary", "p"])
    assert seen == ["p"]


# ---- ② 进度行 ----
JOB_START = 1_700_000_000.0


def _iso(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _facts(timings, running=True):
    arts = {k: False for k in analysis.ARTIFACT_KEYS}
    arts["text_json"] = True
    job = {"task": "prepare", "status": "running", "started": JOB_START} if running else None
    return {"artifacts": arts, "timings": timings, "job": job}


def _timings(upto, last_ok=True):
    out = {}
    for step in readiness.PREPARE_STEPS[:readiness.PREPARE_STEPS.index(upto) + 1]:
        out[step] = {"started": _iso(JOB_START + 1), "seconds": 1.0, "ok": True}
    out[upto]["ok"] = last_ok
    return out


def test_text_row_covers_segment_summary_and_count_stays_11():
    res = analysis.progress(_facts(_timings("text")))
    assert res["total"] == 11 and len(res["steps"]) == 11
    row = next(s for s in res["steps"] if s["key"] == "text")
    assert row["status"] == "running"  # 逐句标注已完成，总结还没跑


def test_text_row_running_while_summary_runs_and_done_after():
    timings = _timings("text")
    res = analysis.progress(_facts(timings))
    assert res["running"] == "text"
    done = {**timings, "segment_summary": {"started": _iso(JOB_START + 2), "seconds": 1.0, "ok": True}}
    row = next(s for s in analysis.progress(_facts(done))["steps"] if s["key"] == "text")
    assert row["status"] == "done"


def test_summary_failure_never_marks_text_row_failed():
    timings = {**_timings("text"),
               "segment_summary": {"started": _iso(JOB_START + 2), "seconds": 1.0, "ok": False}}
    res = analysis.progress(_facts(timings, running=False))
    row = next(s for s in res["steps"] if s["key"] == "text")
    assert row["status"] == "done" and res["failed"] is None


# ---- ③ browse ----
def _browse_project(gui_server, summaries=None, raw=None):
    files = {"work/segments_scored.json": json.dumps(
        {"topics": [], "segments": SEGS, "visual_segments": VSEGS}, ensure_ascii=False),
        "work/materials.json": json.dumps({"items": [{"duration": 100.0}]})}
    if summaries is not None:
        files["work/segment_summaries.json"] = json.dumps({"items": summaries}, ensure_ascii=False)
    if raw is not None:
        files["work/segment_summaries.json"] = raw
    return make_project(gui_server.root, **files)


def _browse(gui_server):
    status, body, _ = call(gui_server, "GET", "/api/browse?project=p1")
    assert status == 200
    return {s["id"]: s for s in json.loads(body)["segments"]}


def test_browse_attaches_summary_to_speech_only(gui_server):
    _browse_project(gui_server, {"S1": {"summary": "讲合同", "key": "k"}, "V001": {"summary": "不该出现", "key": "k"}})
    segs = _browse(gui_server)
    assert segs["S1"]["summary"] == "讲合同" and "summary" not in segs["S2"] and "summary" not in segs["V001"]


def test_browse_reclamps_and_ignores_bad_values(gui_server):
    _browse_project(gui_server, {"S1": {"summary": "字" * 40, "key": "k"}, "S2": {"summary": "  ", "key": "k"}})
    segs = _browse(gui_server)
    assert segs["S1"]["summary"] == "字" * 20 and "summary" not in segs["S2"]


@pytest.mark.parametrize("raw", ["{broken", "[]", '{"items": 3}', '{"items": {"S1": "x"}}'])
def test_browse_survives_corrupt_summary_file(gui_server, raw):
    _browse_project(gui_server, raw=raw)
    assert all("summary" not in s for s in _browse(gui_server).values())


def test_browse_without_summary_file_has_no_field(gui_server):
    _browse_project(gui_server)
    assert all("summary" not in s for s in _browse(gui_server).values())


def test_summary_survives_bounds_edit_and_text_unchanged(gui_server):
    _browse_project(gui_server, {"S1": {"summary": "讲合同", "key": "k"}})
    status, _, _ = call(gui_server, "POST", "/api/browse/bounds",
                        {"project": "p1", "id": "S1", "start": 1.0, "end": 5.0})
    assert status == 200
    s1 = _browse(gui_server)["S1"]
    assert s1["summary"] == "讲合同" and s1["text"] == "甲" and s1["id"] == "S1" and s1["start"] == 1.0


def test_review_apply_leaves_id_and_text_alone(tmp_path):
    out = review.apply([dict(SEGS[0])], {"S1": {"start": 1.0, "end": 5.0}})
    assert (out[0]["id"], out[0]["text"]) == ("S1", "甲")


def test_status_lists_segment_summary_artifact():
    assert ("片段总结", "work/segment_summaries.json") in readiness.STATUS_ARTIFACTS


def test_optional_stage_never_blocks_timings_done_step(monkeypatch):
    monkeypatch.setattr(analysis, "TIMINGS_DONE_STEPS", frozenset({"visual", "text"}))
    f = {"artifacts": {k: False for k in analysis.ARTIFACT_KEYS},
         "timings": {"text": {"started": _iso(JOB_START), "seconds": 1.0, "ok": True},
                     "segment_summary": {"started": _iso(JOB_START), "seconds": 1.0, "ok": False}}}
    assert analysis._step_status("text", ("text", "segment_summary"), "text_json", f, None) == "done"
    f["timings"].pop("segment_summary")  # 没跑也一样
    assert analysis._step_status("text", ("text", "segment_summary"), "text_json", f, None) == "done"


def test_material_timeout_moved_to_media_io(tmp_path):
    from pipeline import media_io
    (tmp_path / "work").mkdir()
    assert media_io.material_timeout(tmp_path) == media_io.FFMPEG_TIMEOUT_S  # 没有台账：兜底值
    (tmp_path / "work" / "materials.json").write_text(json.dumps({"items": [{"duration": 600}]}), encoding="utf-8")
    assert media_io.material_timeout(tmp_path) == media_io.timeout_for(600)
