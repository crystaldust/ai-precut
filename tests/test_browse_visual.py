# -*- coding: utf-8 -*-
"""画面理解第 5 阶段：③ 的画面片段（V001…）——列表、计数、标记接口、剪辑列表、④ 待定队列、⑤ 合计。"""
import json

import pytest
from conftest import call, make_project

from gui import payloads
from pipeline import exclusions, review

pytestmark = pytest.mark.usefixtures("consented")

SEGS = [
    {"id": "S1", "start": 0, "end": 6, "level": 3, "text": "甲", "topic": "讲合同", "speaker": "老王",
     "visual": {"desc": "两人签合同", "issues": ["画面晃动"]}},
    {"id": "S2", "start": 30, "end": 36, "level": 2, "text": "乙", "topic": "讲合同", "speaker": "小李"},
]
VSEGS = [
    {"id": "V001", "kind": "visual", "start": 6, "end": 30, "text": "", "level": 3, "level_reason": "画面：扫码付款",
     "label": "扫码付款 9600 元", "visual": {"desc": "一人扫码", "issues": [], "text_on_screen": "9600"}},
    {"id": "V002", "kind": "visual", "start": 40, "end": 50, "text": "", "level": 2, "level_reason": "画面片段",
     "label": "", "visual": {"desc": "走廊", "issues": []}},
]
SCORED = {"target": 60, "topics": [{"name": "讲合同", "budget": 20}], "segments": SEGS}


def _project(gs, scored=None):
    return make_project(gs.root, **{"work/segments_scored.json": json.dumps(
        scored or {**SCORED, "visual_segments": VSEGS}, ensure_ascii=False)})


def _get(gs, path):
    status, raw, _ = call(gs, "GET", path)
    assert status == 200, raw
    return json.loads(raw)


def _post(gs, path, **body):
    status, raw, _ = call(gs, "POST", path, {"project": "p1", **body})
    return status, json.loads(raw)


def test_browse_interleaves_visual_segments_by_time(gui_server):
    _project(gui_server)
    data = _get(gui_server, "/api/browse?project=p1")
    assert [s["id"] for s in data["segments"]] == ["S1", "V001", "S2", "V002"]
    v = data["segments"][1]
    assert v["kind"] == "visual" and v["topic"] == "画面片段" and v["text"] == "" and v["level"] == 3
    assert data["segments"][0]["visual"]["desc"] == "两人签合同"   # 对白句的画面字段原样带给前端


def test_browse_counts_topics_and_speakers_exclude_visual_segments(gui_server):
    _project(gui_server)
    data = _get(gui_server, "/api/browse?project=p1")
    assert data["counts"] == {"waste": 0, "pending": 1, "usable": 1, "visual": 2}
    topics = {t["name"]: t for t in data["topics"]}
    assert set(topics) == {"讲合同"} and topics["讲合同"]["usable_dur"] == 6
    assert {s["name"] for s in data["speakers"]} == {"老王", "小李"}


def test_browse_without_visual_segments_is_unchanged(gui_server):
    _project(gui_server, SCORED)
    data = _get(gui_server, "/api/browse?project=p1")
    assert [s["id"] for s in data["segments"]] == ["S1", "S2"]
    assert data["counts"] == {"waste": 0, "pending": 1, "usable": 1}


def test_visual_segment_can_be_marked_and_joins_clip_list(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, "/api/browse/must", id="V001", must=True)
    assert status == 200 and data["segment"]["id"] == "V001" and data["segment"]["must_keep"] is True
    item = data["clip_list"]["items"][0]
    assert item == {"id": "V001", "start": 6, "end": 30, "dur": 24, "topic": "画面片段", "text": "",
                    "kind": "visual", "title": "扫码付款 9600 元"}
    assert review.load(pdir / "work")["V001"]["anchor"] == {"text": review.VISUAL_ANCHOR, "start": 6.0, "end": 30.0}
    status, data = _post(gui_server, "/api/browse/level", id="V002", level=1)
    assert status == 200 and data["segment"]["level"] == 1


def test_visual_segment_can_be_marked_unusable_and_is_excluded(gui_server):
    pdir = _project(gui_server)
    status, _ = _post(gui_server, "/api/browse/unusable", id="V002", unusable=True)
    assert status == 200
    assert exclusions.spans(pdir / "work") == [(40.0, 50.0, "V002")]


def test_unknown_visual_id_is_still_rejected(gui_server):
    _project(gui_server)
    status, data = _post(gui_server, "/api/browse/unusable", id="V009", unusable=True)
    assert status == 400 and "V009" in data["error"]


def test_batch_marks_visual_segments(gui_server):
    _project(gui_server)
    status, data = _post(gui_server, "/api/browse/batch", items=[{"id": "V001", "must_keep": True},
                                                                  {"id": "S2", "level": 3}])
    assert status == 200, data
    assert [s["id"] for s in data["segments"]] == ["V001", "S2"]


def test_confirm_pending_queue_and_topics_skip_visual_segments(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    scored = {**SCORED, "visual_segments": VSEGS}
    segs = payloads.applied_segments(work, scored)
    assert [s["id"] for s in segs] == ["S1", "S2"]
    assert [p["id"] for p in payloads._pending_items(segs)] == ["S2"]
    both = payloads.applied_segments(work, scored, visual=True)
    assert [s["id"] for s in both] == ["S1", "V001", "S2", "V002"]


def test_result_lists_visual_segment_only_when_listed_but_missing(gui_server):
    pdir = _project(gui_server)
    (pdir / "shots.json").write_text(json.dumps({"shots": [{"id": "a", "in": 0, "out": 6, "sub": "甲"}]}),
                                     encoding="utf-8")
    data = _get(gui_server, "/api/result?project=p1")
    assert all(u["id"] not in ("V001", "V002") for u in data["unused"])   # 可用但没放进剪辑列表：不列
    _post(gui_server, "/api/browse/must", id="V001", must=True)
    data = _get(gui_server, "/api/result?project=p1")
    row = next(u for u in data["unused"] if u["id"] == "V001")
    assert row["text"] == "扫码付款 9600 元" and row["shot"]["sub"] == ""
    assert data["topbar"]["clip"] == {"count": 1, "covered": 0, "missing": ["V001"]}


def test_unusable_on_non_dict_scored_is_409_not_500(gui_server):
    make_project(gui_server.root, **{"work/segments_scored.json": "[1, 2]"})
    status, _ = _post(gui_server, "/api/browse/unusable", id="V001", unusable=True)
    assert status in (400, 409)
