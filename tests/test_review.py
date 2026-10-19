import json

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
    segs = [{"id": "S001", "level": 2, "level_reason": "待定"},
            {"id": "S002", "level": 3, "level_reason": "含关键信息"}]
    merged = review.apply(segs, {"S001": {"level": 1, "must_keep": True}})
    assert merged[0]["level"] == 1
    assert merged[0]["base_level"] == 2
    assert merged[0]["override"] is True
    assert merged[0]["must_keep"] is True
    assert merged[1]["override"] is False
    assert merged[1]["level_reason"] == "含关键信息"


def test_apply_without_overrides_keeps_original():
    segs = [{"id": "S001", "level": 2, "level_reason": "x"}]
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
