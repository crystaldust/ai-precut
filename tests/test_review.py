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
