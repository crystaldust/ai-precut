# -*- coding: utf-8 -*-
"""编辑片段起止：POST /api/browse/bounds（设置 / 恢复 / 同次放进剪辑列表 / 校验）与 ③ 浏览、剪辑列表的反映。"""
import json

import pytest
from conftest import call, make_project

from gui import project_routes
from pipeline import review

pytestmark = pytest.mark.usefixtures("consented")

SEGS = [
    {"id": "S1", "start": 0, "end": 6, "level": 3, "text": "甲", "topic": "t"},
    {"id": "S2", "start": 10, "end": 16, "level": 3, "text": "乙", "topic": "t"},
]
VSEGS = [{"id": "V001", "kind": "visual", "start": 20, "end": 30, "text": "", "level": 3, "label": "走廊",
          "visual": {"desc": "走廊", "issues": []}}]
SCORED = {"topics": [], "segments": SEGS, "visual_segments": VSEGS}
MATERIAL = {"items": [{"duration": 100.0}]}


def _project(gs, *, shots=None, material=MATERIAL):
    files = {"work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False)}
    if material is not None:
        files["work/materials.json"] = json.dumps(material)
    return make_project(gs.root, shots=shots, **files)


def _post(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/browse/bounds", {"project": "p1", **body})
    return status, json.loads(raw)


def _browse(gs):
    status, raw, _ = call(gs, "GET", "/api/browse?project=p1")
    assert status == 200
    return json.loads(raw)


def test_set_bounds_returns_applied_segment_and_persists(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, id="S2", start=9.5, end=18.254)
    assert status == 200 and data["ok"] is True and data["cleared"] is None
    seg = data["segment"]
    assert (seg["start"], seg["end"], seg["dur"]) == (9.5, 18.25, 8.75)
    assert (seg["base_start"], seg["base_end"], seg["bounds_edited"]) == (10, 16, True)
    assert data["manual_table"] is False and data["wizard"] is not None and data["clip_list"]["items"] == []
    stored = review.load(pdir / "work")["S2"]
    assert (stored["start"], stored["end"]) == (9.5, 18.25) and "must_keep" not in stored


def test_without_must_leaves_clip_list_untouched(gui_server):
    pdir = _project(gui_server)
    review.set_must(pdir / "work", "S1", True)
    _, data = _post(gui_server, id="S1", start=1, end=5)
    assert [i["id"] for i in data["clip_list"]["items"]] == ["S1"]
    assert (data["clip_list"]["items"][0]["start"], data["clip_list"]["items"][0]["dur"]) == (1, 4)
    _, data = _post(gui_server, id="S1", start=1, end=5, must=False)
    assert [i["id"] for i in data["clip_list"]["items"]] == ["S1"]


def test_must_true_adds_to_clip_list_in_one_write_and_clears_unusable(gui_server):
    pdir = _project(gui_server)
    review.set_unusable(pdir / "work", "S2", True)
    _, data = _post(gui_server, id="S2", start=9, end=17, must=True)
    assert data["cleared"] == "unusable"
    assert [(i["id"], i["start"], i["end"], i["dur"]) for i in data["clip_list"]["items"]] == [("S2", 9, 17, 8)]
    item = review.load(pdir / "work")["S2"]
    assert item["must_keep"] is True and item["unusable"] is False and item["must_at"] and item["start"] == 9


def test_both_null_clears_and_restores_original(gui_server):
    pdir = _project(gui_server)
    _post(gui_server, id="S2", start=9, end=17)
    status, data = _post(gui_server, id="S2", start=None, end=None)
    assert status == 200 and data["segment"]["bounds_edited"] is False
    assert (data["segment"]["start"], data["segment"]["end"]) == (10, 16)
    assert review.load(pdir / "work") == {}


def test_visual_segment_can_be_edited(gui_server):
    _project(gui_server)
    status, data = _post(gui_server, id="V001", start=18, end=33, must=True)
    assert status == 200 and (data["segment"]["start"], data["segment"]["base_start"]) == (18, 20)
    item = data["clip_list"]["items"][0]
    assert item["kind"] == "visual" and (item["start"], item["end"], item["dur"]) == (18, 33, 15)


def test_overlap_with_neighbour_is_allowed(gui_server):
    _project(gui_server)
    status, _ = _post(gui_server, id="S1", start=0, end=12)   # 盖到 S2（10~16）
    assert status == 200


def test_manual_table_flag(gui_server):
    _project(gui_server, shots=[{"id": "a", "in": 0, "out": 5}])
    _, data = _post(gui_server, id="S1", start=1, end=5)
    assert data["manual_table"] is True


def test_browse_and_clip_list_reflect_edit(gui_server):
    _project(gui_server)
    _post(gui_server, id="S1", start=1, end=5, must=True)
    data = _browse(gui_server)
    seg = next(s for s in data["segments"] if s["id"] == "S1")
    assert (seg["start"], seg["end"], seg["dur"]) == (1, 5, 4)
    assert (seg["base_start"], seg["base_end"], seg["bounds_edited"]) == (0, 6, True)
    other = next(s for s in data["segments"] if s["id"] == "S2")
    assert (other["base_start"], other["base_end"], other["bounds_edited"]) == (10, 16, False)
    assert [(i["start"], i["end"], i["dur"]) for i in data["clip_list"]["items"]] == [(1, 5, 4)]
    assert data["clip_list"]["total"] == 4


@pytest.mark.parametrize("body", [
    {"start": 1},                                  # 只给一个
    {"end": 5},
    {"start": 1, "end": None},
    {"start": None, "end": 5},
    {"start": "1", "end": 5},
    {"start": True, "end": 5},
    {"start": 1, "end": [5]},
    {"start": -0.1, "end": 5},                     # 负起点
    {"start": 5, "end": 5.2},                      # 短于 0.5 秒
    {"start": 5, "end": 3},
    {"start": 1, "end": 100.5},                    # 超出素材
    {"start": 1, "end": 5, "must": "yes"},
])
def test_bad_bounds_are_400_with_chinese_message_and_write_nothing(gui_server, body):
    pdir = _project(gui_server)
    status, data = _post(gui_server, id="S1", **body)
    assert status == 400 and data["error"]
    assert not (pdir / "work" / "overrides.json").exists()


def test_non_finite_numbers_are_400(gui_server):
    pdir = _project(gui_server)
    for raw in (b'{"project":"p1","id":"S1","start":NaN,"end":5}', b'{"project":"p1","id":"S1","start":1,"end":Infinity}'):
        status, body, _ = call(gui_server, "POST", "/api/browse/bounds", raw=raw)
        assert status == 400, body
    assert not (pdir / "work" / "overrides.json").exists()


def test_minimum_length_boundary_ok_and_unknown_material_duration_skips_end_check(gui_server):
    _project(gui_server, material=None)
    assert _post(gui_server, id="S1", start=1, end=1 + project_routes.BOUNDS_MIN_S)[0] == 200
    assert _post(gui_server, id="S1", start=1, end=80000)[0] == 200


def test_end_equal_to_material_duration_ok(gui_server):
    _project(gui_server)
    assert _post(gui_server, id="S1", start=1, end=100.0)[0] == 200


def test_missing_and_unknown_id_and_non_text_id(gui_server):
    _project(gui_server)
    assert _post(gui_server, start=1, end=5)[0] == 400
    assert _post(gui_server, id="S9", start=1, end=5)[0] == 400
    assert _post(gui_server, id=3, start=1, end=5)[0] == 400
    status, data = _post(gui_server, id="S9", start=1, end=5)
    assert "S9" in data["error"]


def test_corrupt_overrides_is_409_and_untouched(gui_server):
    pdir = _project(gui_server)
    (pdir / "work" / "overrides.json").write_text("{bad", encoding="utf-8")
    assert _post(gui_server, id="S1", start=1, end=5)[0] == 409
    assert _post(gui_server, id="S1", start=None, end=None)[0] == 409
    assert (pdir / "work" / "overrides.json").read_text(encoding="utf-8") == "{bad"


def test_corrupt_scored_is_409(gui_server):
    pdir = _project(gui_server)
    (pdir / "work" / "segments_scored.json").write_text("{bad", encoding="utf-8")
    assert _post(gui_server, id="S1", start=1, end=5)[0] == 409


def test_saved_even_if_response_assembly_fails(gui_server, monkeypatch):
    pdir = _project(gui_server)
    monkeypatch.setattr(project_routes.payloads, "clip_list", lambda *a: 1 / 0)
    status, data = _post(gui_server, id="S1", start=1, end=5)
    assert status == 200 and data["warning"] and data["segment"] is None and data["manual_table"] is False
    assert review.load(pdir / "work")["S1"]["start"] == 1


# ---------------------------------------------------------------- 审查补充
def test_must_true_with_null_bounds_is_400(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, id="S1", start=None, end=None, must=True)
    assert status == 400 and data["error"] == project_routes.CLEAR_WITH_MUST_MSG
    assert not (pdir / "work" / "overrides.json").exists()


def test_must_type_checked_on_null_branch_too(gui_server):
    _project(gui_server)
    status, data = _post(gui_server, id="S1", start=None, end=None, must="yes")
    assert status == 400 and data["error"] == project_routes.BAD_MUST_MSG


def test_must_false_with_null_bounds_is_a_plain_clear(gui_server):
    _project(gui_server)
    assert _post(gui_server, id="S1", start=None, end=None, must=False)[0] == 200


def test_huge_json_int_is_400_not_500(gui_server):
    pdir = _project(gui_server)
    raw = ('{"project":"p1","id":"S1","start":1,"end":1' + "0" * 400 + '}').encode()
    status, body, _ = call(gui_server, "POST", "/api/browse/bounds", raw=raw)
    assert status == 400 and json.loads(body)["error"]
    assert not (pdir / "work" / "overrides.json").exists()


def test_hard_cap_when_material_duration_unknown(gui_server):
    _project(gui_server, material=None)
    assert _post(gui_server, id="S1", start=1, end=project_routes.BOUNDS_MAX_END_S)[0] == 200
    status, data = _post(gui_server, id="S1", start=1, end=project_routes.BOUNDS_MAX_END_S + 1)
    assert status == 400 and data["error"]


def test_rounding_happens_before_validation_and_epsilon_on_min_length(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, id="S1", start=0.2, end=0.7)   # 0.7 - 0.2 = 0.49999999999999994
    assert status == 200
    assert (data["segment"]["start"], data["segment"]["end"]) == (0.2, 0.7)
    status, _ = _post(gui_server, id="S1", start=0.004, end=0.504)   # 取整后 0.0 ~ 0.5
    assert status == 200
    assert (review.load(pdir / "work")["S1"]["start"], review.load(pdir / "work")["S1"]["end"]) == (0.0, 0.5)
    assert _post(gui_server, id="S1", start=1.0, end=1.494)[0] == 400   # 取整后 0.49 → 太短


def test_end_rounding_to_material_duration_is_accepted(gui_server):
    _project(gui_server)
    assert _post(gui_server, id="S1", start=1, end=100.004)[0] == 200


@pytest.mark.parametrize("duration", ["abc", "100", None, [], -5, {"x": 1}])
def test_corrupt_material_duration_is_treated_as_unknown(gui_server, duration):
    _project(gui_server, material={"items": [{"duration": duration}]})
    assert _post(gui_server, id="S1", start=1, end=5000)[0] == 200


def test_browse_survives_corrupt_material_duration(gui_server):
    _project(gui_server, material={"items": [{"duration": "abc"}]})
    assert _browse(gui_server)["material_duration"] == 0.0
