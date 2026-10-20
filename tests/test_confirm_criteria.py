# -*- coding: utf-8 -*-
"""M13 Task 18：④ 定标准的数据（/api/confirm 增加 pending / topics 计数 / speakers / legacy / blocks / segments）。"""
import json

import pytest

from conftest import call, make_project

SEGMENTS = [
    {"id": "S001", "start": 0, "end": 6, "topic": "讲合同", "level": 3, "text": "甲", "speaker": "老王",
     "level_reason": "信息密度高"},
    {"id": "S003", "start": 30, "end": 36, "topic": "聊吃饭", "level": 2, "text": "丙", "speaker": "小李",
     "level_reason": "不确定"},
    {"id": "S002", "start": 10, "end": 16, "topic": "讲合同", "level": 2, "text": "乙<b>", "speaker": "老王",
     "level_reason": "可能有用"},
    {"id": "S004", "start": 40, "end": 44, "topic": "聊吃饭", "level": 2, "text": "丁", "level_reason": "不确定"},
    {"id": "S005", "start": 50, "end": 55, "topic": "聊吃饭", "level": 1, "text": "戊", "level_reason": "闲聊"},
]
SCORED = {"target": 60, "topics": [{"name": "讲合同", "budget": 20}, {"name": "聊吃饭", "budget": 10}],
          "segments": SEGMENTS}
QUESTIONS = {"questions": [
    {"id": "q1", "text": "结尾？", "type": "single", "options": [
        {"label": "签字", "rule": {"kind": "ending", "value": "sign"}, "effect": "结尾落在签字"}]},
    {"id": "q2", "text": "保留？", "type": "multi", "options": [
        {"label": "合同", "rule": {"kind": "must_topics", "value": ["讲合同"]}}]}]}


def _project(gs, answers=None, **extra):
    files = {"work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False),
             "work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False), **extra}
    if answers is not None:
        files["work/brief_answers.json"] = json.dumps(answers, ensure_ascii=False)
    return make_project(gs.root, **files)


def _confirm(gs, name="p1"):
    status, raw, _ = call(gs, "GET", f"/api/confirm?project={name}")
    return status, json.loads(raw)


def test_pending_lists_level_two_segments_in_time_order_as_ids(gui_server):
    _project(gui_server)
    status, data = _confirm(gui_server)
    assert status == 200
    assert [p["id"] for p in data["pending"]] == ["S002", "S003", "S004"]
    assert data["pending"][0] == {"id": "S002", "start": 10, "end": 16}  # 文字只在 segments 里出现一份


def test_pending_follows_overrides_and_skips_unusable(gui_server):
    pdir = _project(gui_server, **{"work/overrides.json": json.dumps({
        "S002": {"level": 3, "at": "t"}, "S003": {"unusable": True, "at": "t"}})})
    _, data = _confirm(gui_server)
    assert [p["id"] for p in data["pending"]] == ["S004"]
    assert pdir.exists()


def test_pending_uses_topic_display_names(gui_server):
    _project(gui_server)
    call(gui_server, "POST", "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "谈合同"})
    _, data = _confirm(gui_server)
    assert next(x for x in data["segments"] if x["id"] == "S002")["topic"] == "谈合同"
    assert {"topic": "谈合同", "topic_raw": "讲合同", "count": 2} in data["topics"]
    assert {"topic": "聊吃饭", "topic_raw": "聊吃饭", "count": 3} in data["topics"]


def test_segments_are_compact_and_carry_current_level(gui_server):
    _project(gui_server, **{"work/overrides.json": json.dumps({"S001": {"level": 1, "at": "t"}})})
    _, data = _confirm(gui_server)
    by_id = {s["id"]: s for s in data["segments"]}
    assert len(by_id) == 5 and [s["id"] for s in data["segments"]] == sorted(by_id, key=lambda i: by_id[i]["start"])
    assert by_id["S001"]["level"] == 1 and by_id["S001"]["override"] is True
    assert set(by_id["S002"]) >= {"id", "start", "end", "dur", "level", "level_reason", "override",
                                  "unusable", "topic", "topic_raw", "text"}


def test_speakers_sorted_by_duration(gui_server):
    _project(gui_server)
    _, data = _confirm(gui_server)
    assert data["speakers"] == [{"name": "老王", "seconds": 12.0}, {"name": "小李", "seconds": 6.0}]


def test_missing_questions_is_still_404(gui_server):
    make_project(gui_server.root, **{"work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False)})
    assert _confirm(gui_server)[0] == 404


def test_unreadable_answers_keep_page_open_and_clear_blocks(gui_server):
    _project(gui_server, **{"work/brief_answers.json": "{坏"})
    status, data = _confirm(gui_server)
    assert status == 200 and data["answers_unreadable"] is True and data["answers"] == {}


def test_scored_missing_still_serves_questions_without_pending(gui_server):
    make_project(gui_server.root, **{"work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})
    status, data = _confirm(gui_server)
    assert status == 200 and data["pending"] == [] and data["segments"] == [] and data["speakers"] == []


def test_corrupt_overrides_is_409(gui_server):
    _project(gui_server, **{"work/overrides.json": "{坏"})
    assert _confirm(gui_server)[0] == 409


def test_answers_save_response_carries_wizard(gui_server):
    _project(gui_server)
    status, raw, _ = call(gui_server, "POST", "/api/confirm/answers",
                          {"project": "p1", "answers": {"q1": "签字"}})
    data = json.loads(raw)
    assert status == 200 and [s["key"] for s in data["wizard"]["steps"]][:2] == ["new", "analyze"]


def test_no_blocks_or_legacy_in_payload(gui_server):
    _project(gui_server)
    _, data = _confirm(gui_server)
    assert "blocks" not in data and "legacy" not in data


MALFORMED = [
    {"segments": "不是列表"},
    {"segments": [5]},
    {"segments": [{"id": "S1", "start": 0, "end": 5, "text": "x"}]},                       # 缺 level
    {"segments": [{"id": "S1", "start": "0", "end": 5, "level": 2, "text": "x"}]},        # start 不是数字
    {"segments": [{"id": "S1", "start": 0, "end": 5, "level": 9, "text": "x"}]},          # level 不在 1-3
    {"segments": [{"start": 0, "end": 5, "level": 2, "text": "x"}]},                      # 缺 id
    {"segments": [{"id": "S1", "start": True, "end": 5, "level": 2, "text": "x"}]},       # 布尔不算数字
]


@pytest.mark.parametrize("scored", MALFORMED)
def test_malformed_segments_are_409_with_a_clear_message(gui_server, scored):
    make_project(gui_server.root, **{"work/segments_scored.json": json.dumps(scored, ensure_ascii=False),
                                     "work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})
    status, data = _confirm(gui_server)
    assert status == 409 and "分析结果不完整" in data["error"]


def test_corrupt_scored_file_is_409_not_an_empty_page(gui_server):
    make_project(gui_server.root, **{"work/segments_scored.json": "{坏",
                                     "work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})
    assert _confirm(gui_server)[0] == 409


def test_overlong_segment_text_is_truncated_server_side(gui_server):
    from gui import payloads
    big = {**SCORED, "segments": [{**SEGMENTS[0], "text": "字" * (payloads.SEGMENT_TEXT_MAX_CHARS + 500),
                                   "level_reason": "因" * 5000}]}
    make_project(gui_server.root, **{"work/segments_scored.json": json.dumps(big, ensure_ascii=False),
                                     "work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})
    seg = _confirm(gui_server)[1]["segments"][0]
    assert len(seg["text"]) == payloads.SEGMENT_TEXT_MAX_CHARS and len(seg["level_reason"]) <= payloads.SEGMENT_TEXT_MAX_CHARS
