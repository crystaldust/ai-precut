# -*- coding: utf-8 -*-
"""④ 自定义想法 → 选段规则（AI 换算）：按题限种类、严格校验、未生效说明、按摘要缓存、失败不降级。"""
import json

import pytest

from pipeline import custom_rules, questions, usage
from pipeline.llm import LLMError

TOPICS = [{"name": "讲合同"}, {"name": "聊吃饭"}]
QS = {"questions": [
    {"id": "q1", "text": "结尾落在哪？", "type": "single", "options": [
        {"label": "签字", "rule": {"kind": "ending", "value": "sign"}},
        {"label": "留白", "rule": {"kind": "ending", "value": "silence"}}]},
    {"id": "q2", "text": "必须覆盖哪些话题？", "type": "multi", "options": [
        {"label": "合同", "rule": {"kind": "must_topics", "value": ["讲合同"]}}]}]}
EXTRA = questions.CUSTOM_EXTRA


class Fake:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def chat_json(self, system, user, **kw):
        self.calls.append((system, user))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _items(result):
    return {i["key"]: i for i in result["items"]}


# ---------------------------------------------------------------- 按题限定可换算的种类
def test_allowed_kinds_follow_question_options_and_extra_allows_all():
    assert custom_rules.allowed_kinds("q1", QS) == {"ending"}
    assert custom_rules.allowed_kinds("q2", QS) == {"must_topics"}
    assert custom_rules.allowed_kinds(EXTRA, QS) == set(questions.KINDS)
    assert custom_rules.allowed_kinds("q9", QS) == set(questions.KINDS)


def test_prompt_carries_question_context_allowed_kinds_and_topics():
    fake = Fake({"items": []})
    custom_rules.interpret({"q1": "以拥抱收尾"}, QS, TOPICS, client=fake)
    _, user = fake.calls[0]
    assert "结尾落在哪？" in user and "以拥抱收尾" in user and "讲合同" in user
    item = json.loads(user.split(custom_rules.ITEMS_MARK, 1)[1].strip())[0]
    assert item == {"key": "q1", "question": "结尾落在哪？", "allowed": ["ending"], "text": "以拥抱收尾"}


# ---------------------------------------------------------------- 严格校验
def test_interpret_keeps_valid_rules_and_drops_out_of_kind_ones():
    fake = Fake({"items": [
        {"key": "q1", "rules": [{"kind": "ending", "value": "emotion"},
                                {"kind": "must_topics", "value": ["讲合同"]}]},   # q1 只能是 ending
        {"key": EXTRA, "rules": [{"kind": "exclude", "value": ["聊吃饭", "不存在"]},
                                 {"kind": "pacing", "value": "tight"},
                                 {"kind": "focus", "value": "妈妈"},             # 自由文本主角：不合格
                                 {"kind": "must_lines", "value": ["九千八包含所有耗材"]}]}]})
    res = custom_rules.interpret({"q1": "最有力的话收尾", EXTRA: "不要吃饭那段，节奏快，留下「九千八包含所有耗材」"}, QS, TOPICS, client=fake)
    items = _items(res)
    assert items["q1"]["rules"] == [{"kind": "ending", "value": "emotion"}]
    assert items[EXTRA]["rules"] == [{"kind": "exclude", "value": ["聊吃饭"]},
                                     {"kind": "pacing", "value": "tight"},
                                     {"kind": "must_lines", "value": ["九千八包含所有耗材"]}]
    assert items["q1"]["text"] == "最有力的话收尾"


@pytest.mark.parametrize("rule,expected", [
    ({"kind": "ending", "value": "签字收尾"}, {"kind": "ending", "value": "sign"}),
    ({"kind": "ending", "value": "随便"}, None),
    ({"kind": "pacing", "value": "slow"}, None),
    ({"kind": "focus", "value": "ensemble"}, {"kind": "focus", "value": "ensemble"}),
    ({"kind": "exclude", "value": "讲合同"}, {"kind": "exclude", "value": ["讲合同"]}),
    ({"kind": "exclude", "value": ["没有"]}, None),
    ({"kind": "hack", "value": 1}, None),
    ("ending", None),
])
def test_strict_rule(rule, expected):
    assert custom_rules.strict_rule(rule, {"讲合同", "聊吃饭"}) == expected


def test_rules_per_item_are_capped():
    many = [{"kind": "must_lines", "value": [f"第{i}句原话"]} for i in range(10)]
    text = "保留" + "".join(f"「第{i}句原话」" for i in range(10))
    res = custom_rules.interpret({EXTRA: text}, QS, TOPICS, client=Fake({"items": [{"key": EXTRA, "rules": many}]}))
    assert len(_items(res)[EXTRA]["rules"]) == custom_rules.MAX_RULES_PER_ITEM


def test_unmapped_item_gets_a_note():
    fake = Fake({"items": [{"key": "q1", "rules": [], "note": "「温暖一点」没法落到结尾的选择上"}]})
    res = custom_rules.interpret({"q1": "温暖一点", EXTRA: "加点音乐"}, QS, TOPICS, client=fake)
    items = _items(res)
    assert items["q1"]["rules"] == [] and "温暖一点" in items["q1"]["note"]
    assert items[EXTRA]["rules"] == [] and items[EXTRA]["note"] == custom_rules.NOT_MAPPED  # 模型漏掉的条目


def test_items_follow_custom_order_and_ignore_unknown_keys():
    fake = Fake({"items": [{"key": "q7", "rules": [{"kind": "pacing", "value": "tight"}]},
                           {"key": EXTRA, "rules": [{"kind": "pacing", "value": "tight"}]}]})
    res = custom_rules.interpret({"q1": "a", EXTRA: "b"}, QS, TOPICS, client=fake)
    assert [i["key"] for i in res["items"]] == ["q1", EXTRA]


# ---------------------------------------------------------------- 失败不降级
def test_llm_failure_raises_interpret_failed():
    with pytest.raises(custom_rules.InterpretFailed) as err:
        custom_rules.interpret({"q1": "x"}, QS, TOPICS, client=Fake(RuntimeError("timeout")))
    assert "timeout" in str(err.value) and isinstance(err.value, LLMError)


def test_malformed_reply_raises_interpret_failed():
    with pytest.raises(custom_rules.InterpretFailed):
        custom_rules.interpret({"q1": "x"}, QS, TOPICS, client=Fake({"items": "不是列表"}))


def test_budget_exceeded_propagates_unchanged():
    with pytest.raises(usage.BudgetExceeded):
        custom_rules.interpret({"q1": "x"}, QS, TOPICS, client=Fake(usage.BudgetExceeded(10, 5)))


# ---------------------------------------------------------------- 缓存
def test_ensure_caches_by_text_questions_and_topics(tmp_path):
    reply = {"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]}]}
    made = []

    def factory():
        made.append(Fake(reply))
        return made[-1]

    first, cached = custom_rules.ensure(tmp_path, {"q1": "背影收尾"}, QS, TOPICS, client_factory=factory)
    assert cached is False and (tmp_path / custom_rules.CUSTOM_RULES_FILE).exists()
    again, cached = custom_rules.ensure(tmp_path, {"q1": "背影收尾"}, QS, TOPICS, client_factory=factory)
    assert cached is True and again == first and len(made) == 1   # 没改：不建 client、不计费
    custom_rules.ensure(tmp_path, {"q1": "拥抱收尾"}, QS, TOPICS, client_factory=factory)
    custom_rules.ensure(tmp_path, {"q1": "拥抱收尾"}, QS, [{"name": "讲合同"}], client_factory=factory)
    assert len(made) == 3


def test_ensure_without_custom_needs_no_client(tmp_path):
    def factory():
        raise AssertionError("不该建 client")

    res, cached = custom_rules.ensure(tmp_path, {}, QS, TOPICS, client_factory=factory)
    assert res["items"] == [] and cached is True


def test_ensure_failure_keeps_previous_cache(tmp_path):
    good = Fake({"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]}]})
    custom_rules.ensure(tmp_path, {"q1": "背影收尾"}, QS, TOPICS, client_factory=lambda: good)
    before = (tmp_path / custom_rules.CUSTOM_RULES_FILE).read_text(encoding="utf-8")
    with pytest.raises(custom_rules.InterpretFailed):
        custom_rules.ensure(tmp_path, {"q1": "改了"}, QS, TOPICS, client_factory=lambda: Fake(RuntimeError("x")))
    assert (tmp_path / custom_rules.CUSTOM_RULES_FILE).read_text(encoding="utf-8") == before


def test_load_current_only_returns_matching_cache(tmp_path):
    fake = Fake({"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]}]})
    custom_rules.ensure(tmp_path, {"q1": "背影收尾"}, QS, TOPICS, client_factory=lambda: fake)
    assert custom_rules.load_current(tmp_path, {"q1": "背影收尾"}, QS, TOPICS)["items"][0]["key"] == "q1"
    assert custom_rules.load_current(tmp_path, {"q1": "别的"}, QS, TOPICS) is None
    (tmp_path / custom_rules.CUSTOM_RULES_FILE).write_text("{坏", encoding="utf-8")
    assert custom_rules.load_current(tmp_path, {"q1": "背影收尾"}, QS, TOPICS) is None


# ---------------------------------------------------------------- 人话
def test_describe_rules_in_plain_words():
    text = custom_rules.describe([{"kind": "ending", "value": "leave"},
                                  {"kind": "must_topics", "value": ["讲合同"]},
                                  {"kind": "exclude", "value": ["聊吃饭"]},
                                  {"kind": "pacing", "value": "tight"},
                                  {"kind": "focus", "value": "ensemble"},
                                  {"kind": "must_lines", "value": ["九千八包含所有耗材"]}])
    for word in ("离开", "讲合同", "聊吃饭", "紧凑", "群像", "九千八包含所有耗材"):
        assert word in text


def test_cache_file_is_plain_json(tmp_path):
    fake = Fake({"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]}]})
    custom_rules.ensure(tmp_path, {"q1": "背影收尾"}, QS, TOPICS, client_factory=lambda: fake)
    data = json.loads((tmp_path / custom_rules.CUSTOM_RULES_FILE).read_text(encoding="utf-8"))
    assert set(data) >= {"key", "items"}


# ---------------------------------------------------------------- 审查修复
def test_unhashable_values_in_reply_are_dropped_not_crashing():
    fake = Fake({"items": [{"key": ["x"], "rules": []},
                           {"key": EXTRA, "rules": [{"kind": "exclude", "value": [["聊吃饭"]]},
                                                    {"kind": "must_topics", "value": [{"a": 1}]},
                                                    {"kind": {"k": 1}, "value": 1}]}]})
    res = custom_rules.interpret({EXTRA: "别出现吃饭"}, QS, TOPICS, client=fake)
    assert _items(res)[EXTRA]["rules"] == [] and _items(res)[EXTRA]["note"] == custom_rules.NOT_MAPPED


def test_items_follow_question_order_then_extra_whatever_the_typing_order():
    fake = Fake({"items": []})
    res = custom_rules.interpret({EXTRA: "c", "q2": "b", "q1": "a"}, QS, TOPICS, client=fake)
    assert [i["key"] for i in res["items"]] == ["q1", "q2", EXTRA]


def test_only_first_rule_of_a_single_valued_kind_is_kept_per_item():
    fake = Fake({"items": [{"key": EXTRA, "rules": [{"kind": "ending", "value": "leave"},
                                                    {"kind": "ending", "value": "sign"},
                                                    {"kind": "pacing", "value": "tight"}]}]})
    res = custom_rules.interpret({EXTRA: "背影收尾，节奏快"}, QS, TOPICS, client=fake)
    assert _items(res)[EXTRA]["rules"] == [{"kind": "ending", "value": "leave"}, {"kind": "pacing", "value": "tight"}]


def test_must_lines_must_be_quoted_in_the_editors_own_text():
    fake = Fake({"items": [{"key": EXTRA, "rules": [
        {"kind": "must_lines", "value": ["九千八包含所有耗材", "编造的一句很长的话"]}]}]})
    res = custom_rules.interpret({EXTRA: "保留「九千八包含所有耗材」这句"}, QS, TOPICS, client=fake)
    assert _items(res)[EXTRA]["rules"] == [{"kind": "must_lines", "value": ["九千八包含所有耗材"]}]


def test_cached_items_are_revalidated_on_load(tmp_path):
    custom = {"q1": "背影收尾"}
    key = custom_rules.cache_key(custom, QS, TOPICS)
    (tmp_path / custom_rules.CUSTOM_RULES_FILE).write_text(json.dumps({"key": key, "items": [
        {"key": "q1", "text": "背影收尾", "rules": [{"kind": "focus", "value": "随便什么"},
                                                   {"kind": "ending", "value": "leave"}], "note": ""}]},
        ensure_ascii=False), encoding="utf-8")
    loaded = custom_rules.load_current(tmp_path, custom, QS, TOPICS)
    assert loaded["items"][0]["rules"] == [{"kind": "ending", "value": "leave"}]   # q1 只能是 ending


def test_cache_key_carries_a_version(monkeypatch):
    before = custom_rules.cache_key({"q1": "x"}, QS, TOPICS)
    monkeypatch.setattr(custom_rules, "CUSTOM_RULES_VERSION", custom_rules.CUSTOM_RULES_VERSION + 1)
    assert custom_rules.cache_key({"q1": "x"}, QS, TOPICS) != before


def test_cache_write_failure_still_returns_the_paid_result(tmp_path, monkeypatch):
    from pipeline import schema

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(schema, "write_json", boom)
    fake = Fake({"items": [{"key": "q1", "rules": [{"kind": "ending", "value": "leave"}]}]})
    res, cached = custom_rules.ensure(tmp_path, {"q1": "背影收尾"}, QS, TOPICS, client_factory=lambda: fake)
    assert cached is False and res["items"][0]["rules"] == [{"kind": "ending", "value": "leave"}]
