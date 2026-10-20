# -*- coding: utf-8 -*-
"""M13 T5：选段 / 分析写输入戳；PREPARE_STEPS 顺序（D10）。"""
import json

import pytest

from pipeline import fingerprints, readiness, select

from tests.test_select import RV, TOPICS, seg


def _setup(tmp_path, answers=None):
    scored = {"target": 60, "topics": TOPICS, "segments": [seg(1, 0, 6, "讲合同", key=True)]}
    sp = tmp_path / "segments_scored.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "brief_answers.json"
    ap.write_text(json.dumps({"answers": answers or {}, "rules_version": RV}), encoding="utf-8")
    return sp, ap


def test_select_run_stamps_inputs_in_result_and_file(tmp_path):
    sp, ap = _setup(tmp_path, {"q1": "a"})
    cal = {"tone": "info", "must_lines": "不白学吗"}
    res = select.run(sp, ap, tmp_path, calibration=cal, target=90)
    expected = fingerprints.selection_inputs(tmp_path, {"target_duration": 90, "calibration": cal})
    assert res["inputs"] == expected
    saved = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert saved["inputs"] == expected


def test_select_run_stamp_uses_passed_target_not_project_json(tmp_path):
    sp, ap = _setup(tmp_path)
    res = select.run(sp, ap, tmp_path, target=120)
    assert res["inputs"]["target"] == "120"


def test_select_run_stamp_taken_before_selection_runs(tmp_path, monkeypatch):
    """选段过程中有人改 overrides：戳是选段开始前的输入，改动要在选完后显示为「过期」。"""
    sp, ap = _setup(tmp_path)
    real = select.select

    def racing(*a, **k):
        (tmp_path / "overrides.json").write_text(json.dumps({"S001": {"level": 1}}), encoding="utf-8")
        return real(*a, **k)

    monkeypatch.setattr(select, "select", racing)
    res = select.run(sp, ap, tmp_path, target=60)
    now = fingerprints.selection_inputs(tmp_path, {"target_duration": 60})
    assert fingerprints.changed(res["inputs"], now) == ["overrides"]


def test_prepare_steps_follow_spec_order():
    assert readiness.PREPARE_STEPS == (
        "ingest", "junk", "transcribe", "analyze", "scenes", "quality", "text", "score",
        "summary", "questions", "select", "brief")


def test_write_analysis_stamp_roundtrip(tmp_path):
    cfg = {"calibration": {"tone": "info"}, "preset": "纪实3min"}
    readiness.write_analysis_stamp(tmp_path, fingerprints.analysis_inputs(cfg))
    stamp = json.loads((tmp_path / readiness.ANALYSIS_STAMP).read_text(encoding="utf-8"))
    assert stamp == fingerprints.analysis_inputs(cfg)
    assert readiness.ANALYSIS_STAMP == "analysis_inputs.json"


def test_write_analysis_stamp_takes_prepared_inputs(tmp_path):
    readiness.write_analysis_stamp(tmp_path, {"directive": "d", "preset": "p"})
    assert json.loads((tmp_path / readiness.ANALYSIS_STAMP).read_text(encoding="utf-8")) == {
        "directive": "d", "preset": "p"}


def test_text_and_summary_caches_are_keyed_by_preference_directive():
    """MEDIUM-8：改剪辑偏好后重新分析，AI 理解 / 摘要不会命中旧缓存（score / select 本来每次重算）。"""
    from pipeline import summarize, understand_text, style
    segs = [{"id": "S1", "text": "a", "start": 0, "end": 1, "speaker": None}]
    a = understand_text._fingerprint(segs, style.directive({"tone": "info"}), "m")
    b = understand_text._fingerprint(segs, style.directive({"tone": "emotion"}), "m")
    assert a != b
    assert summarize._input_hash("t", "p", style.directive({"tone": "info"}), "m") != \
        summarize._input_hash("t", "p", style.directive({"tone": "emotion"}), "m")
