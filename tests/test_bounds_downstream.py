# -*- coding: utf-8 -*-
"""手改起止对下游的影响：不可用排除用手改后的区间；出片前的必留核对按手改后的区间。"""
import json

from pipeline import exclusions, review, select


def _scored(workdir):
    (workdir / "segments_scored.json").write_text(json.dumps({"segments": [
        {"id": "S1", "start": 10, "end": 16, "text": "甲", "level": 3, "topic": "t"},
        {"id": "S2", "start": 30, "end": 36, "text": "乙", "level": 3, "topic": "t"}]}, ensure_ascii=False),
        encoding="utf-8")


def test_unusable_span_uses_edited_bounds(tmp_path):
    _scored(tmp_path)
    review.set_bounds(tmp_path, "S1", 8.0, 20.0)
    review.set_unusable(tmp_path, "S1", True)
    assert exclusions.spans(tmp_path) == [(8.0, 20.0, "S1")]   # 隐私优先：排除的是剪辑师划定的整段


def test_unedited_unusable_span_unchanged(tmp_path):
    _scored(tmp_path)
    review.set_unusable(tmp_path, "S2", True)
    assert exclusions.spans(tmp_path) == [(30.0, 36.0, "S2")]


def test_extended_must_segment_is_reported_by_manual_table_that_only_covers_original_range(tmp_path):
    # 意图：手动分镜表不会自动跟着新起止走；延长了的必留段没被盖住，出片前就要报缺（回 ④ 重新选段）
    _scored(tmp_path)
    review.set_bounds(tmp_path, "S1", 10.0, 24.0, must=True)
    manual = [{"id": "a", "in": 10.0, "out": 16.0}]
    assert [m["id"] for m in select.missing_must_keep(tmp_path, manual)] == ["S1"]
    assert select.missing_must_keep(tmp_path, [{"id": "a", "in": 10.0, "out": 24.0}]) == []


def test_trimmed_must_segment_covered_by_original_wide_shot(tmp_path):
    _scored(tmp_path)
    review.set_bounds(tmp_path, "S1", 11.0, 14.0, must=True)
    assert select.missing_must_keep(tmp_path, [{"id": "a", "in": 10.0, "out": 16.0}]) == []
