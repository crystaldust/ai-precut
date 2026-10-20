# -*- coding: utf-8 -*-
"""M13c · Task 15/16 后端：③ 看素材的数据（KI-99、speakers、clip_list）与标记接口的响应补全。"""
import json

import pytest
from conftest import call, make_project

from gui import payloads
from pipeline import review

pytestmark = pytest.mark.usefixtures("consented")

SEGS = [
    {"id": "S1", "start": 0, "end": 6, "level": 3, "text": "甲", "topic": "讲合同", "speaker": "老王",
     "visual_flags": ["soft"]},
    {"id": "S2", "start": 10, "end": 16, "level": 2, "text": "乙", "topic": "讲合同", "speaker": "小李"},
    {"id": "S3", "start": 20, "end": 30, "level": 3, "text": "丙", "topic": "聊吃饭", "speaker": "老王"},
]
SCORED = {"target": 60, "topics": [{"name": "讲合同", "budget": 20}, {"name": "聊吃饭", "budget": 10}],
          "segments": SEGS}


def _project(gs, *, shots=None, selected=None, target=None):
    files = {"work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False)}
    if selected is not None:
        files["work/shots-selected.json"] = json.dumps({"shots": selected})
    pdir = make_project(gs.root, shots=shots, **files)
    if target is not None:
        cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
        (pdir / "project.json").write_text(json.dumps({**cfg, "target_duration": target}), encoding="utf-8")
    return pdir


def _browse(gs):
    status, raw, _ = call(gs, "GET", "/api/browse?project=p1")
    assert status == 200
    return json.loads(raw)


def _by_id(data):
    return {s["id"]: s for s in data["segments"]}


# ---------------------------------------------------------------- KI-99
def test_ki99_selected_shots_mark_segments_used_when_no_manual_table(gui_server):
    _project(gui_server, selected=[{"id": "a", "in": 10, "out": 16}])
    segs = _by_id(_browse(gui_server))
    assert segs["S2"]["inCut"] is True and segs["S1"]["inCut"] is False


def test_ki99_manual_table_wins_over_selection(gui_server):
    _project(gui_server, shots=[{"id": "m", "in": 0, "out": 6}], selected=[{"id": "a", "in": 10, "out": 16}])
    segs = _by_id(_browse(gui_server))
    assert segs["S1"]["inCut"] is True and segs["S2"]["inCut"] is False


def test_nothing_is_used_when_neither_table_exists(gui_server):
    _project(gui_server)
    assert not any(s["inCut"] for s in _browse(gui_server)["segments"])


# ---------------------------------------------------------------- 字段
def test_segments_carry_marks_flags_and_topic_names(gui_server):
    pdir = _project(gui_server)
    review.set_must(pdir / "work", "S1", True)
    review.set_unusable(pdir / "work", "S3", True)
    segs = _by_id(_browse(gui_server))
    assert segs["S1"]["must_keep"] is True and segs["S1"]["unusable"] is False
    assert segs["S3"]["unusable"] is True and segs["S3"]["must_keep"] is False
    assert segs["S1"]["visual_flags"] == ["soft"]
    assert segs["S1"]["topic"] == "讲合同" and segs["S1"]["topic_raw"] == "讲合同"


def test_browse_includes_clip_list_with_project_target(gui_server):
    pdir = _project(gui_server, target=100)
    review.set_must(pdir / "work", "S1", True)
    review.set_must(pdir / "work", "S3", True)
    clip = _browse(gui_server)["clip_list"]
    assert [i["id"] for i in clip["items"]] == ["S1", "S3"]
    assert clip["total"] == 16 and clip["target"] == 100 and clip["over_target"] is False


def test_clip_list_uses_default_target_without_one(gui_server):
    _project(gui_server)
    assert _browse(gui_server)["clip_list"]["target"] == payloads.DEFAULT_TARGET_S


def test_clip_list_over_target_suggests_rounded_target(gui_server):
    pdir = _project(gui_server, target=10)
    review.set_must(pdir / "work", "S3", True)
    review.set_must(pdir / "work", "S1", True)
    clip = _browse(gui_server)["clip_list"]
    assert clip["over_target"] is True and clip["over_by"] == 6
    assert clip["suggested_target"] >= clip["total"]


def test_unusable_must_segment_is_not_counted(gui_server):
    pdir = _project(gui_server, target=100)
    review.set_must(pdir / "work", "S1", True)
    review.set_unusable(pdir / "work", "S1", True)
    assert _browse(gui_server)["clip_list"]["items"] == []


# ---------------------------------------------------------------- speakers
def test_speakers_sorted_by_seconds_descending():
    out = payloads.speakers(SEGS)
    assert out == [{"name": "老王", "seconds": 16.0}, {"name": "小李", "seconds": 6.0}]


def test_speakers_skips_missing_names_and_bad_spans():
    out = payloads.speakers([{"start": 0, "end": 5}, {"speaker": "", "start": 0, "end": 5},
                             {"speaker": "甲", "start": 5, "end": 4}, {"speaker": "乙", "start": 0, "end": 2}])
    assert out == [{"name": "乙", "seconds": 2.0}]


def test_browse_includes_speakers(gui_server):
    _project(gui_server)
    assert _browse(gui_server)["speakers"][0] == {"name": "老王", "seconds": 16.0}


# ---------------------------------------------------------------- 标记接口响应补全
def _post(gs, path, **body):
    status, raw, _ = call(gs, "POST", path, {"project": "p1", **body})
    return status, json.loads(raw)


def test_must_response_has_segment_clip_list_and_wizard(gui_server):
    _project(gui_server, target=100)
    status, data = _post(gui_server, "/api/browse/must", id="S1", must=True)
    assert status == 200 and data["ok"] is True and data["cleared"] is None
    assert data["segment"]["id"] == "S1" and data["segment"]["must_keep"] is True
    assert [i["id"] for i in data["clip_list"]["items"]] == ["S1"]
    assert [s["key"] for s in data["wizard"]["steps"]][:3] == ["new", "analyze", "browse"]


def test_level_response_has_segment_clip_list_and_wizard(gui_server):
    _project(gui_server)
    status, data = _post(gui_server, "/api/browse/level", id="S2", level=3)
    assert status == 200 and data["segment"]["level"] == 3 and data["segment"]["override"] is True
    assert "clip_list" in data and "wizard" in data


def test_level_null_clears_manual_level(gui_server):
    pdir = _project(gui_server)
    _post(gui_server, "/api/browse/level", id="S2", level=3)
    status, data = _post(gui_server, "/api/browse/level", id="S2", level=None)
    assert status == 200 and data["segment"]["level"] == 2 and data["segment"]["override"] is False
    assert "level" not in review.load(pdir / "work").get("S2", {})


def test_level_null_keeps_must_keep(gui_server):
    pdir = _project(gui_server)
    review.set_must(pdir / "work", "S2", True)
    _post(gui_server, "/api/browse/level", id="S2", level=3)
    _, data = _post(gui_server, "/api/browse/level", id="S2", level=None)
    assert data["segment"]["must_keep"] is True


def test_bad_level_still_400(gui_server):
    _project(gui_server)
    assert _post(gui_server, "/api/browse/level", id="S2", level=9)[0] == 400
    assert _post(gui_server, "/api/browse/level", id="S2", level="x")[0] == 400


def test_unusable_response_has_wizard(gui_server):
    _project(gui_server)
    status, data = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    assert status == 200 and "wizard" in data


def test_marks_without_analysis_still_work_without_segment(gui_server):
    make_project(gui_server.root)
    status, data = _post(gui_server, "/api/browse/must", id="S1", must=True)
    assert status == 200 and data["ok"] is True and data["segment"] is None and data["clip_list"] is None


def test_marks_change_result_step_to_stale_after_selection(gui_server, monkeypatch):
    """⑤ 的「需要更新」：选段时记下输入指纹，之后标剪辑列表 → 响应里的 wizard 把 ⑤ 标 stale。"""
    from gui import analysis
    from pipeline import fingerprints
    monkeypatch.setattr(analysis, "is_complete", lambda artifacts: True)
    pdir = _project(gui_server)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    (pdir / "work/selection.json").write_text(json.dumps(
        {"inputs": fingerprints.selection_inputs(pdir / "work", cfg)}), encoding="utf-8")
    (pdir / "work/brief_answers.json").write_text(json.dumps(
        {"answers": {}, "confirmed": True}), encoding="utf-8")
    _, data = _post(gui_server, "/api/browse/must", id="S1", must=True)
    result = next(s for s in data["wizard"]["steps"] if s["key"] == "result")
    assert result["status"] == "stale" and "素材标记改过了" in result["banner"]
