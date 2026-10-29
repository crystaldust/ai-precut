# -*- coding: utf-8 -*-
"""④ 决策问题「自定义」：剪辑师自己填的想法（每题一个 + 所有题后一个），落盘、规整、进指纹。"""
import json

import pytest

from conftest import call, make_project
from pipeline import fingerprints, questions

QS = {"questions": [
    {"id": "q1", "type": "single", "options": [{"label": "签字", "rule": {"kind": "ending", "value": "sign"}}]},
    {"id": "q2", "type": "multi", "options": [{"label": "合同", "rule": {"kind": "must_topics", "value": ["讲合同"]}}]}]}


# ---------------------------------------------------------------- normalize_custom
@pytest.mark.parametrize("raw,expected", [
    (None, {}), ([], {}), ("x", {}), ({}, {}),
    ({"q1": "  以拥抱收尾 "}, {"q1": "以拥抱收尾"}),
    ({"q1": "", "q2": "   "}, {}),
    ({"q1": 3, "q2": ["a"]}, {}),
    ({"q9": "不存在的题"}, {}),
    ({questions.CUSTOM_EXTRA: " 不要出现价格 "}, {questions.CUSTOM_EXTRA: "不要出现价格"}),
    ({"q1": "第一行\n第二行\t\x00尾"}, {"q1": "第一行 第二行 尾"}),
])
def test_normalize_custom(raw, expected):
    assert questions.normalize_custom(QS, raw) == expected


def test_normalize_custom_caps_length():
    out = questions.normalize_custom(QS, {"q1": "长" * (questions.MAX_CUSTOM_CHARS + 50)})
    assert out == {"q1": "长" * questions.MAX_CUSTOM_CHARS}


def test_normalize_custom_without_questions_keeps_only_extra():
    assert questions.normalize_custom(None, {"q1": "a", questions.CUSTOM_EXTRA: "b"}) == {questions.CUSTOM_EXTRA: "b"}


def test_single_question_custom_replaces_option_answer():
    answers = questions.normalize_answers(QS, {"q1": "签字", "q2": ["合同"]})
    custom = questions.normalize_custom(QS, {"q1": "以拥抱收尾", "q2": "再保留吃饭"})
    assert questions.drop_replaced_answers(QS, answers, custom) == {"q2": ["合同"]}  # 多选题两者并存


def test_drop_replaced_answers_returns_new_dict():
    answers = {"q1": "签字"}
    questions.drop_replaced_answers(QS, answers, {"q1": "x"})
    assert answers == {"q1": "签字"}


# ---------------------------------------------------------------- 指纹
def test_answers_digest_tracks_custom(tmp_path):
    path = tmp_path / "brief_answers.json"
    path.write_text(json.dumps({"answers": {"q2": ["合同"]}}), encoding="utf-8")
    plain = fingerprints.answers_digest(tmp_path)
    path.write_text(json.dumps({"answers": {"q2": ["合同"]}, "custom": {}}), encoding="utf-8")
    assert fingerprints.answers_digest(tmp_path) == plain  # 没填自定义：老项目的指纹不变（不误报「需要更新」）
    path.write_text(json.dumps({"answers": {"q2": ["合同"]}, "custom": {"q1": "以拥抱收尾"}}), encoding="utf-8")
    with_custom = fingerprints.answers_digest(tmp_path)
    assert with_custom != plain
    path.write_text(json.dumps({"answers": {"q2": ["合同"]}, "custom": {"q1": "以背影收尾"}}), encoding="utf-8")
    assert fingerprints.answers_digest(tmp_path) != with_custom


# ---------------------------------------------------------------- 保存（/api/confirm/answers）
def _save(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/confirm/answers", {"project": "p1", **body})
    return status, json.loads(raw)


def _stored(pdir):
    return json.loads((pdir / "work/brief_answers.json").read_text(encoding="utf-8"))


def test_save_stores_normalized_custom_and_drops_replaced_single_answer(gui_server):
    pdir = make_project(gui_server.root, **{"work/questions.json": json.dumps(QS, ensure_ascii=False)})
    status, _ = _save(gui_server, answers={"q1": "签字", "q2": ["合同"]},
                      custom={"q1": " 以拥抱收尾 ", "q9": "x", questions.CUSTOM_EXTRA: "不要出现价格"})
    assert status == 200
    saved = _stored(pdir)
    assert saved["answers"] == {"q2": ["合同"]}
    assert saved["custom"] == {"q1": "以拥抱收尾", questions.CUSTOM_EXTRA: "不要出现价格"}
    assert saved["rules"]["ending"] is None  # 被自定义替换的选项不再进规则


def test_save_without_custom_writes_empty_custom(gui_server):
    pdir = make_project(gui_server.root, **{"work/questions.json": json.dumps(QS, ensure_ascii=False)})
    _save(gui_server, answers={"q1": "签字"})
    assert _stored(pdir)["custom"] == {}


def test_save_rejects_non_object_custom(gui_server):
    make_project(gui_server.root, **{"work/questions.json": json.dumps(QS, ensure_ascii=False)})
    status, data = _save(gui_server, answers={}, custom=["x"])
    assert status == 400 and "custom" in data["error"]


# ---------------------------------------------------------------- ④ 页面数据（GET /api/confirm）
SCORED = {"target": 60, "topics": [{"name": "讲合同"}], "segments": []}


class _Fake:
    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, *a, **k):
        return self.payload


def _page(gs):
    status, raw, _ = call(gs, "GET", "/api/confirm?project=p1")
    return status, json.loads(raw)


def _page_project(gs, custom):
    return make_project(gs.root, **{
        "work/questions.json": json.dumps(QS, ensure_ascii=False),
        "work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False),
        "work/brief_answers.json": json.dumps({"answers": {"q2": ["合同"]}, "custom": custom}, ensure_ascii=False)})


def test_confirm_payload_returns_custom_and_matching_understanding(gui_server):
    from pipeline import custom_rules
    custom = {"q1": "以背影收尾", questions.CUSTOM_EXTRA: "加点音乐"}
    pdir = _page_project(gui_server, custom)
    reply = {"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]},
                       {"key": questions.CUSTOM_EXTRA, "rules": [], "note": "和选段无关"}]}
    custom_rules.ensure(pdir / "work", custom, QS, SCORED["topics"], client_factory=lambda: _Fake(reply))
    status, data = _page(gui_server)
    assert status == 200 and data["custom"] == custom
    assert data["custom_understood"]["q1"] == {"rules": "结尾落在离开 / 背影", "note": ""}
    assert data["custom_understood"][questions.CUSTOM_EXTRA] == {"rules": "", "note": "和选段无关"}


def test_confirm_payload_hides_understanding_after_text_changed(gui_server):
    from pipeline import custom_rules
    pdir = _page_project(gui_server, {"q1": "改过的文字"})
    reply = {"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]}]}
    custom_rules.ensure(pdir / "work", {"q1": "原来的文字"}, QS, SCORED["topics"], client_factory=lambda: _Fake(reply))
    _, data = _page(gui_server)
    assert data["custom"] == {"q1": "改过的文字"} and data["custom_understood"] == {}


def test_confirm_payload_without_custom(gui_server):
    _page_project(gui_server, {})
    _, data = _page(gui_server)
    assert data["custom"] == {} and data["custom_understood"] == {}


def test_normalize_custom_strips_invisible_format_characters():
    assert questions.normalize_custom(QS, {"q1": "背​影‮收尾 了"}) == {"q1": "背影收尾 了"}


# ---------------------------------------------------------------- 重新出题后：绑在旧题上的自定义作废
@pytest.mark.parametrize("saved,current,kept,dropped", [
    (None, "new", {"q1": "a", questions.CUSTOM_EXTRA: "b"}, {}),          # 老数据没记题目摘要：不判过期
    ("new", "new", {"q1": "a", questions.CUSTOM_EXTRA: "b"}, {}),
    ("old", "new", {questions.CUSTOM_EXTRA: "b"}, {"q1": "a"}),
])
def test_split_stale_custom(saved, current, kept, dropped):
    assert questions.split_stale_custom({"q1": "a", questions.CUSTOM_EXTRA: "b"}, saved, current) == (kept, dropped)


def test_confirm_payload_drops_question_bound_custom_after_regenerate(gui_server):
    pdir = _page_project(gui_server, {"q1": "以背影收尾", questions.CUSTOM_EXTRA: "不要价格"})
    path = pdir / "work/brief_answers.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**stored, "questions_digest": "旧题目的摘要"}, ensure_ascii=False), encoding="utf-8")
    _, data = _page(gui_server)
    assert data["custom"] == {questions.CUSTOM_EXTRA: "不要价格"}
