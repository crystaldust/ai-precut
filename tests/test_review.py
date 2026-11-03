import json

import pytest

from pipeline import review


def test_set_level_and_load(tmp_path):
    review.set_level(tmp_path, "S001", 3)
    data = review.load(tmp_path)
    assert data["S001"]["level"] == 3
    assert "at" in data["S001"]


def test_invalid_level_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        review.set_level(tmp_path, "S001", 9)


def test_set_must_and_clear(tmp_path):
    review.set_must(tmp_path, "S002", True)
    assert review.load(tmp_path)["S002"]["must_keep"] is True
    review.clear(tmp_path, "S002")
    assert "S002" not in review.load(tmp_path)


def test_apply_merges_overrides():
    segs = [{"id": "S001", "start": 0, "end": 5, "level": 2, "level_reason": "待定"},
            {"id": "S002", "start": 5, "end": 9, "level": 3, "level_reason": "含关键信息"}]
    merged = review.apply(segs, {"S001": {"level": 1, "must_keep": True}})
    assert merged[0]["level"] == 1
    assert merged[0]["base_level"] == 2
    assert merged[0]["override"] is True
    assert merged[0]["must_keep"] is True
    assert merged[1]["override"] is False
    assert merged[1]["level_reason"] == "含关键信息"


def test_apply_without_overrides_keeps_original():
    segs = [{"id": "S001", "start": 0, "end": 5, "level": 2, "level_reason": "x"}]
    merged = review.apply(segs, {})
    assert merged[0]["level"] == 2 and merged[0]["must_keep"] is False


# ---- GL-18：损坏不当空、读改写串行 ----

def test_load_missing_returns_empty(tmp_path):
    assert review.load(tmp_path) == {}


def test_load_corrupt_raises(tmp_path):
    import pytest
    (tmp_path / "overrides.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt, match="overrides.json"):
        review.load(tmp_path)


def test_load_non_dict_raises(tmp_path):
    import pytest
    (tmp_path / "overrides.json").write_text("[1,2]", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.load(tmp_path)


def test_set_level_on_corrupt_keeps_file(tmp_path):
    import pytest
    f = tmp_path / "overrides.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.set_level(tmp_path, "S001", 3)
    assert f.read_text(encoding="utf-8") == "{bad"


def test_set_must_on_corrupt_keeps_file(tmp_path):
    import pytest
    f = tmp_path / "overrides.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.set_must(tmp_path, "S001", True)
    assert f.read_text(encoding="utf-8") == "{bad"


def test_clear_one_on_corrupt_keeps_file(tmp_path):
    import pytest
    f = tmp_path / "overrides.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.clear(tmp_path, "S001")
    assert f.read_text(encoding="utf-8") == "{bad"


def test_concurrent_set_level_no_lost_update(tmp_path):
    import threading
    errors = []

    def worker(i):
        try:
            review.set_level(tmp_path, f"S{i:03d}", 3)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(review.load(tmp_path)) == 50


def test_overrides_corrupt_is_value_error():
    assert issubclass(review.OverridesCorrupt, ValueError)


# ================================================================ M6 · KI-12 裁决锚点
def _scored(tmp_path, *segs):
    (tmp_path / "segments_scored.json").write_text(json.dumps({"segments": [
        {"id": i, "start": s, "end": s + 5, "text": t, "level": 2} for i, s, t in segs]},
        ensure_ascii=False), encoding="utf-8")


def _segs(*segs):
    return [{"id": i, "start": s, "end": s + 5, "text": t, "level": 2} for i, s, t in segs]


def _anchor(text, start):
    return {"text": review.text_key(text), "start": start}


def test_set_level_records_anchor_when_scored_exists(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "九千八"))
    data = review.set_level(tmp_path, "S001", 3)
    assert data["S001"]["anchor"] == {"text": review.text_key("九千八"), "start": 12.0}


def test_set_must_records_anchor(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "九千八"))
    assert review.set_must(tmp_path, "S001", True)["S001"]["anchor"]["start"] == 12.0


def test_anchor_missing_scored_file_ok(tmp_path):
    assert "anchor" not in review.set_level(tmp_path, "S001", 3)["S001"]
    (tmp_path / "segments_scored.json").write_text("{坏", encoding="utf-8")
    assert "anchor" not in review.set_must(tmp_path, "S002", True)["S002"]


def test_text_key_ignores_whitespace():
    assert review.text_key("九千 八\n") == review.text_key("九千八")


def test_apply_anchor_match_applies():
    ov = {"S001": {"level": 1, "anchor": _anchor("甲", 0)}}
    assert review.apply(_segs(("S001", 0, "甲")), ov)[0]["level"] == 1


def test_apply_relocates_by_text_after_resegmentation():
    ov = {"S001": {"level": 1, "must_keep": True, "anchor": _anchor("甲", 0)}}
    merged = review.apply(_segs(("S001", 0, "乙"), ("S003", 1, "甲")), ov)
    assert merged[0]["level"] == 2 and merged[0]["must_keep"] is False
    assert merged[1]["level"] == 1 and merged[1]["must_keep"] is True


def test_apply_relocate_prefers_nearest_start():
    ov = {"S001": {"level": 1, "anchor": _anchor("甲", 50)}}
    merged = review.apply(_segs(("S001", 0, "乙"), ("S002", 10, "甲"), ("S003", 48, "甲")), ov)
    assert [m["level"] for m in merged] == [2, 2, 1]


def test_apply_stale_override_skipped_and_reported():
    ov = {"S001": {"level": 1, "must_keep": True, "anchor": _anchor("甲", 0)}}
    segs = _segs(("S001", 0, "乙"), ("S002", 10, "丙"))
    merged = review.apply(segs, ov)
    assert all(m["level"] == 2 and not m["must_keep"] for m in merged)
    assert review.stale_ids(segs, ov) == ["S001"]


def test_legacy_override_without_anchor_applies_by_id():
    ov = {"S001": {"level": 1}}
    assert review.apply(_segs(("S001", 0, "乙")), ov)[0]["level"] == 1
    assert review.stale_ids(_segs(("S001", 0, "乙")), ov) == []


def test_non_dict_override_ignored():
    assert review.apply(_segs(("S001", 0, "乙")), {"S001": 5})[0]["override"] is False


def test_rewrite_after_resegmentation_does_not_carry_stale_fields(tmp_path):
    """旧裁决挂在 S001（原文甲），重新分段后 S001 变成乙、甲变成 S003；再标 S001 不能把旧档位带到乙上。"""
    (tmp_path / "overrides.json").write_text(json.dumps(
        {"S001": {"level": 1, "anchor": _anchor("甲", 0)}}), encoding="utf-8")
    _scored(tmp_path, ("S001", 0, "乙"), ("S003", 1, "甲"))
    data = review.set_must(tmp_path, "S001", True)
    segs = _segs(("S001", 0, "乙"), ("S003", 1, "甲"))
    merged = review.apply(segs, data)
    assert merged[0]["level"] == 2 and merged[0]["must_keep"] is True
    assert merged[1]["level"] == 1  # 旧裁决跟着原文走到 S003
    assert review.stale_ids(segs, data) == []


def test_rewrite_relocated_segment_updates_same_decision(tmp_path):
    """浏览页显示在 S003 的（从 S001 重定位来的）裁决，再改 S003 → 不能留下一条失效的 S001。"""
    (tmp_path / "overrides.json").write_text(json.dumps(
        {"S001": {"level": 1, "anchor": _anchor("甲", 0)}}), encoding="utf-8")
    _scored(tmp_path, ("S001", 0, "乙"), ("S003", 1, "甲"))
    data = review.set_level(tmp_path, "S003", 3)
    segs = _segs(("S001", 0, "乙"), ("S003", 1, "甲"))
    assert review.stale_ids(segs, data) == []
    assert [m["level"] for m in review.apply(segs, data)] == [2, 3]


# ================================================================ M6 审查修复：重定位全局最近 + 距离上限
def test_relocation_assigned_globally_by_distance():
    ov = {"S003": {"must_keep": True, "anchor": _anchor("对。", 10.0)},
          "S010": {"must_keep": True, "anchor": _anchor("对。", 50.0)}}
    segs = [{"id": "S004", "text": "好的", "start": 10.2, "end": 11, "level": 1},
            {"id": "S011", "text": "对。", "start": 50.1, "end": 51, "level": 1}]
    mapping, stale = review.resolve(segs, ov)
    assert mapping == {"S011": ov["S010"]} and stale == ["S003"]


def test_relocation_global_not_greedy_within_cap():
    ov = {"S001": {"level": 1, "anchor": _anchor("甲", 20.0)},
          "S002": {"level": 3, "anchor": _anchor("甲", 26.0)}}
    segs = _segs(("S007", 25, "甲"), ("S008", 5, "甲"))
    mapping, stale = review.resolve(segs, ov)
    assert mapping["S007"] is ov["S002"] and mapping["S008"] is ov["S001"] and stale == []


def test_relocation_beyond_cap_is_stale():
    ov = {"S003": {"must_keep": True, "anchor": _anchor("对。", 10.0)}}
    segs = [{"id": "S090", "text": "对。", "start": 3000, "end": 3001, "level": 1}]
    assert review.resolve(segs, ov) == ({}, ["S003"])
    assert review.RELOCATE_MAX_SECONDS <= 60


def test_same_id_same_text_far_start_prefers_near_duplicate():
    ov = {"S010": {"must_keep": True, "anchor": _anchor("对。", 50.0)}}
    segs = [{"id": "S010", "text": "对。", "start": 7.0, "end": 8, "level": 1},
            {"id": "S011", "text": "对。", "start": 50.0, "end": 51, "level": 1}]
    assert review.resolve(segs, ov)[0] == {"S011": ov["S010"]}


def test_clear_removes_relocated_override_by_current_id(tmp_path):  # KI-85
    (tmp_path / "overrides.json").write_text(json.dumps(
        {"S001": {"level": 1, "anchor": _anchor("甲", 0)}}), encoding="utf-8")
    _scored(tmp_path, ("S001", 0, "乙"), ("S003", 1, "甲"))
    assert review.clear(tmp_path, "S003") == {}
    assert review.load(tmp_path) == {}


def test_rewrite_does_not_inherit_far_same_text_stale_item(tmp_path):
    (tmp_path / "overrides.json").write_text(json.dumps(
        {"S001": {"level": 1, "anchor": _anchor("对。", 500.0)}}), encoding="utf-8")
    _scored(tmp_path, ("S001", 0, "对。"))
    data = review.set_must(tmp_path, "S001", True)
    assert "level" not in data["S001"] and data["S001"]["must_keep"] is True


# ================================================================ 画面片段（第 5 阶段）：没有对白，按起点锚定
def _vis(i, start, end=None, level=2):
    return {"id": i, "kind": "visual", "start": start, "end": end or start + 10, "text": "", "level": level}


def test_visual_segment_anchor_is_by_time_not_empty_text(tmp_path):
    (tmp_path / "segments_scored.json").write_text(json.dumps({
        "segments": [{"id": "S001", "start": 0, "end": 5, "text": "甲", "level": 2}],
        "visual_segments": [_vis("V001", 40.0)]}, ensure_ascii=False), encoding="utf-8")
    data = review.set_must(tmp_path, "V001", True)
    assert data["V001"]["anchor"] == {"text": review.VISUAL_ANCHOR, "start": 40.0, "end": 50.0}


def test_visual_override_follows_renumbered_segment():
    ov = {"V003": {"level": 3, "must_keep": True, "anchor": {"text": review.VISUAL_ANCHOR, "start": 40.0}}}
    merged = review.apply([_vis("V003", 10.0), _vis("V004", 41.5)], ov)
    assert [(m["id"], m["level"], m["must_keep"]) for m in merged] == [("V003", 2, False), ("V004", 3, True)]


def test_visual_override_does_not_jump_beyond_visual_cap():
    ov = {"V001": {"level": 1, "anchor": {"text": review.VISUAL_ANCHOR, "start": 40.0}}}
    segs = [_vis("V001", 40.0 + review.VISUAL_RELOCATE_MAX_SECONDS + 1)]
    assert review.apply(segs, ov)[0]["level"] == 2
    assert review.stale_ids(segs, ov) == ["V001"]


def test_visual_and_speech_anchors_never_cross():
    ov = {"S001": {"level": 1, "anchor": _anchor("", 40.0)},
          "V001": {"level": 3, "anchor": {"text": review.VISUAL_ANCHOR, "start": 40.0}}}
    merged = review.apply([{"id": "S009", "start": 40.0, "end": 41, "text": "", "level": 2}, _vis("V002", 40.0)], ov)
    assert [m["level"] for m in merged] == [1, 3]


def test_rekey_on_write_moves_visual_override(tmp_path):
    (tmp_path / "segments_scored.json").write_text(json.dumps({
        "segments": [], "visual_segments": [_vis("V002", 41.0)]}), encoding="utf-8")
    (tmp_path / "overrides.json").write_text(json.dumps({
        "V001": {"level": 3, "anchor": {"text": review.VISUAL_ANCHOR, "start": 40.0}}}), encoding="utf-8")
    data = review.set_must(tmp_path, "V002", True)
    assert set(data) == {"V002"} and data["V002"]["level"] == 3 and data["V002"]["must_keep"] is True


def test_visual_override_needs_both_ends_close_not_just_start():
    """同起点附近、但长短完全不同的画面片段是另一段画面：裁决不能跟过去（审查 LOW）。"""
    ov = {"V001": {"must_keep": True, "anchor": {"text": review.VISUAL_ANCHOR, "start": 10.0, "end": 20.0}}}
    merged = review.apply([_vis("V001", 12.5, 40.0), _vis("V002", 11.0, 21.0)], ov)
    assert [(m["id"], m["must_keep"]) for m in merged] == [("V001", False), ("V002", True)]


def test_is_visual_override():
    assert review.is_visual_override({"anchor": {"text": review.VISUAL_ANCHOR, "start": 1}})
    assert not review.is_visual_override({"anchor": _anchor("甲", 1)})
    assert not review.is_visual_override("坏的") and not review.is_visual_override({"anchor": 3})


# ================================================================ 编辑片段起止（bounds）
def _anchored(tmp_path, *segs):
    _scored(tmp_path, *segs)


def test_apply_without_bounds_edit_exposes_base_and_not_edited():
    out = review.apply(_segs(("S001", 10.0, "甲")), {})[0]
    assert (out["start"], out["end"]) == (10.0, 15.0)
    assert (out["base_start"], out["base_end"]) == (10.0, 15.0) and out["bounds_edited"] is False


def test_apply_edited_bounds_replace_start_end_and_keep_base():
    ov = {"S001": {"start": 9.5, "end": 18.25, "anchor": _anchor("甲", 10.0)}}
    out = review.apply(_segs(("S001", 10.0, "甲")), ov)[0]
    assert (out["start"], out["end"]) == (9.5, 18.25)
    assert (out["base_start"], out["base_end"]) == (10.0, 15.0) and out["bounds_edited"] is True


def test_apply_ignores_half_or_inverted_bounds():
    segs = _segs(("S001", 10.0, "甲"))
    for bad in ({"start": 9.0}, {"end": 20.0}, {"start": 20.0, "end": 9.0}, {"start": "a", "end": 2}):
        out = review.apply(segs, {"S001": bad})[0]
        assert (out["start"], out["end"], out["bounds_edited"]) == (10.0, 15.0, False)


def test_apply_does_not_mutate_inputs():
    segs, ov = _segs(("S001", 10.0, "甲")), {"S001": {"start": 9.0, "end": 16.0}}
    review.apply(segs, ov)
    assert segs[0]["start"] == 10.0 and "base_start" not in segs[0] and ov == {"S001": {"start": 9.0, "end": 16.0}}


def test_set_bounds_rounds_keeps_anchor_on_original_bounds(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "九千八"))
    data, cleared = review.set_bounds(tmp_path, "S001", 11.234, 19.999)
    assert (data["S001"]["start"], data["S001"]["end"]) == (11.23, 20.0) and cleared is None
    assert data["S001"]["anchor"] == {"text": review.text_key("九千八"), "start": 12.0}
    assert "must_keep" not in data["S001"]
    assert review.load(tmp_path) == data


def test_set_bounds_with_must_is_one_atomic_write_and_clears_unusable(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "甲"))
    review.set_unusable(tmp_path, "S001", True)
    data, cleared = review.set_bounds(tmp_path, "S001", 11.0, 18.0, must=True)
    item = data["S001"]
    assert item["must_keep"] is True and item["unusable"] is False and item["must_at"] and cleared == "unusable"
    assert (item["start"], item["end"]) == (11.0, 18.0)


def test_set_bounds_without_must_leaves_clip_list_state(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "甲"))
    review.set_must(tmp_path, "S001", True)
    before = review.load(tmp_path)["S001"]["must_at"]
    data, _ = review.set_bounds(tmp_path, "S001", 11.0, 18.0)
    assert data["S001"]["must_keep"] is True and data["S001"]["must_at"] == before


def test_bounds_only_entry_survives_unset_level_and_clear_bounds_deletes_it(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "甲"))
    review.set_level(tmp_path, "S001", 3)
    review.set_bounds(tmp_path, "S001", 11.0, 18.0)
    data = review.unset_level(tmp_path, "S001")
    assert (data["S001"]["start"], data["S001"]["end"]) == (11.0, 18.0) and "level" not in data["S001"]
    assert review.clear_bounds(tmp_path, "S001") == {}
    assert review.load(tmp_path) == {}


def test_clear_bounds_keeps_other_fields(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "甲"))
    review.set_bounds(tmp_path, "S001", 11.0, 18.0, must=True)
    data = review.clear_bounds(tmp_path, "S001")
    assert data["S001"]["must_keep"] is True and "start" not in data["S001"] and "end" not in data["S001"]


def test_clear_bounds_without_entry_is_noop_and_corrupt_kept(tmp_path):
    assert review.clear_bounds(tmp_path, "S001") == {}
    (tmp_path / "overrides.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.clear_bounds(tmp_path, "S001")
    with pytest.raises(review.OverridesCorrupt):
        review.set_bounds(tmp_path, "S001", 1.0, 3.0)
    assert (tmp_path / "overrides.json").read_text(encoding="utf-8") == "{bad"


def test_edited_bounds_relocate_with_override_after_reanalysis(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "九千八"))
    review.set_bounds(tmp_path, "S001", 11.0, 20.0)
    ov = review.load(tmp_path)
    shifted = _segs(("S007", 13.5, "九千八"))   # 重新分段：id 变了、起点挪了一点
    out = review.apply(shifted, ov)[0]
    assert (out["start"], out["end"], out["bounds_edited"]) == (11.0, 20.0, True)
    assert (out["base_start"], out["base_end"]) == (13.5, 18.5)


def test_stale_bounds_override_is_dropped_and_reported():
    ov = {"S001": {"start": 11.0, "end": 20.0, "anchor": _anchor("九千八", 12.0)}}
    segs = _segs(("S001", 100.0, "九千八"))
    out = review.apply(segs, ov)[0]
    assert out["bounds_edited"] is False and (out["start"], out["end"]) == (100.0, 105.0)
    assert review.stale_ids(segs, ov) == ["S001"]


def test_visual_bounds_edit_relocates_by_original_anchor(tmp_path):
    (tmp_path / "segments_scored.json").write_text(json.dumps({
        "segments": [{"id": "S001", "start": 0, "end": 5, "text": "甲", "level": 2}],
        "visual_segments": [_vis("V001", 40.0)]}, ensure_ascii=False), encoding="utf-8")
    data, _ = review.set_bounds(tmp_path, "V001", 38.0, 55.0)
    assert data["V001"]["anchor"] == {"text": review.VISUAL_ANCHOR, "start": 40.0, "end": 50.0}
    out = review.apply([_vis("V002", 40.5, 50.5)], data)[0]
    assert (out["start"], out["end"], out["bounds_edited"]) == (38.0, 55.0, True)


# ---------------------------------------------------------------- 审查补充
def test_huge_int_in_hand_edited_overrides_is_no_edit_not_a_crash():
    ov = {"S001": {"start": 1, "end": int("1" + "0" * 400)}}
    out = review.apply(_segs(("S001", 10.0, "甲")), ov)[0]
    assert out["bounds_edited"] is False and (out["start"], out["end"]) == (10.0, 15.0)
    assert review.edited_bounds({"start": 1, "end": float("inf")}) is None
    assert review.finite_number(True) is None and review.finite_number("1") is None and review.finite_number(2) == 2.0


def test_apply_is_idempotent_on_already_applied_segments():
    ov = {"S001": {"start": 9.0, "end": 16.0, "anchor": _anchor("甲", 10.0)}}
    once = review.apply(_segs(("S001", 10.0, "甲")), ov)
    twice = review.apply(once, ov)
    assert twice == once and (twice[0]["base_start"], twice[0]["base_end"]) == (10.0, 15.0)
    cleared = review.apply(once, {})
    assert (cleared[0]["start"], cleared[0]["end"], cleared[0]["bounds_edited"]) == (10.0, 15.0, False)


def test_other_marks_keep_edited_bounds(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "甲"))
    review.set_bounds(tmp_path, "S001", 11.0, 18.0)
    for step in (lambda: review.set_level(tmp_path, "S001", 3), lambda: review.unset_level(tmp_path, "S001"),
                 lambda: review.set_must(tmp_path, "S001", True), lambda: review.set_must(tmp_path, "S001", False),
                 lambda: review.set_unusable(tmp_path, "S001", True), lambda: review.set_unusable(tmp_path, "S001", False)):
        step()
        item = review.load(tmp_path)["S001"]
        assert (item["start"], item["end"]) == (11.0, 18.0)


def test_set_bounds_on_stale_id_does_not_inherit_old_sentence_fields(tmp_path):
    _scored(tmp_path, ("S001", 100.0, "新句"))
    (tmp_path / "overrides.json").write_text(json.dumps({"S001": {
        "level": 1, "must_keep": True, "anchor": _anchor("旧句", 12.0)}}), encoding="utf-8")
    data, _ = review.set_bounds(tmp_path, "S001", 99.0, 108.0)
    assert set(data["S001"]) == {"start", "end", "at", "anchor"}
    assert data["S001"]["anchor"] == _anchor("新句", 100.0)


def test_clear_bounds_by_current_id_after_relocation(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "九千八"))
    review.set_bounds(tmp_path, "S001", 11.0, 20.0)
    _scored(tmp_path, ("S007", 13.0, "九千八"))   # 重新分段后当前 id 变了
    assert review.clear_bounds(tmp_path, "S007") == {}


def test_unset_level_and_clear_bounds_share_the_drop_rule(tmp_path):
    _scored(tmp_path, ("S001", 12.0, "甲"))
    review.set_level(tmp_path, "S001", 2)
    assert review.unset_level(tmp_path, "S001") == {}
    before = (tmp_path / "overrides.json").read_text(encoding="utf-8")
    review.clear_bounds(tmp_path, "S001")   # 没有起止可撤：不写文件
    assert (tmp_path / "overrides.json").read_text(encoding="utf-8") == before
