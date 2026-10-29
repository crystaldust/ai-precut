# -*- coding: utf-8 -*-
"""④ 自定义想法接入选段：换算出的规则合并在选项规则之后（单值以自定义为准）、未生效写警告、CLI 换算与失败。"""
import json
from argparse import Namespace

import pytest

import aicut
from pipeline import custom_rules, questions, select, select_rules
from pipeline.llm import LLMError

RV = select_rules.RULES_VERSION
EXTRA = questions.CUSTOM_EXTRA
TOPICS = [{"name": "讲合同", "budget": 20, "must": True, "duration": 60, "usable_dur": 40},
          {"name": "聊吃饭", "budget": 10, "must": False, "duration": 60, "usable_dur": 30}]
QS = {"questions": [
    {"id": "q1", "text": "结尾落在哪？", "type": "single", "options": [
        {"label": "签字", "rule": {"kind": "ending", "value": "sign"}}]}]}


def seg(i, start, dur, topic, *, level=3, text=""):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur, "topic": topic, "level": level,
            "key_info": False, "must_keep": False, "info_type": "", "text": text or f"第{i}句", "signals": {}}


def item(key, text, rules, note=""):
    return {"key": key, "text": text, "rules": rules, "note": note}


# ---------------------------------------------------------------- 规则合并
def test_with_custom_overrides_single_values_and_appends_lists():
    base = {**select_rules.rules_from_answers({}, None), "ending": "sign", "must_topics": ["讲合同"]}
    merged = select_rules.with_custom(base, [
        item("q1", "背影收尾", [{"kind": "ending", "value": "leave"}]),
        item(EXTRA, "别出现吃饭，节奏快", [{"kind": "exclude", "value": ["聊吃饭"]},
                                         {"kind": "pacing", "value": "tight"},
                                         {"kind": "must_topics", "value": ["聊吃饭"]}])])
    assert merged["ending"] == "leave" and merged["pacing"] == "tight"
    assert merged["exclude_topics"] == ["聊吃饭"] and merged["must_topics"] == ["讲合同", "聊吃饭"]
    assert base["ending"] == "sign" and base["exclude_topics"] == []  # 不改输入


def test_custom_warnings_only_for_unmapped_items():
    warns = select_rules.custom_warnings([item("q1", "温暖一点", [], "和选段无关"),
                                          item(EXTRA, "背影", [{"kind": "ending", "value": "leave"}])])
    assert warns == [select_rules.CUSTOM_NOT_MAPPED.format(text="温暖一点", note="和选段无关")]


# ---------------------------------------------------------------- select.run
def _files(tmp_path, answers):
    sp = tmp_path / "scored.json"
    sp.write_text(json.dumps({"target": 60, "topics": TOPICS,
                              "segments": [seg(1, 0, 6, "讲合同"), seg(2, 10, 6, "聊吃饭")]},
                             ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "answers.json"
    ap.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    return sp, ap


def test_run_applies_custom_rules_and_records_them(tmp_path):
    sp, ap = _files(tmp_path, {"answers": {}, "rules": {}, "rules_version": RV})
    custom = {"items": [item(EXTRA, "不要吃饭那段", [{"kind": "exclude", "value": ["聊吃饭"]}]),
                        item("q1", "加点音乐", [], "和选段无关")]}
    res = select.run(sp, ap, tmp_path, custom=custom)
    assert all(s["topic"] != "聊吃饭" for s in res["shots"])
    assert res["rules"]["exclude_topics"] == ["聊吃饭"]
    assert res["custom_rules"] == custom["items"]
    assert any("加点音乐" in w and "未生效" in w for w in res["warnings"])


def test_run_without_custom_is_unchanged(tmp_path):
    sp, ap = _files(tmp_path, {"answers": {}})
    res = select.run(sp, ap, tmp_path)
    assert res["custom_rules"] == [] and not any("自定义" in w for w in res["warnings"])


# ---------------------------------------------------------------- CLI：cmd_select
class Fake:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def chat_json(self, *a, **k):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _project(root, custom):
    pdir = root / "p"
    (pdir / "work").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": "p", "material": "/tmp/a.mp4", "schema_version": 2, "target_duration": 60}), encoding="utf-8")
    files = {"segments_scored.json": {"target": 60, "topics": TOPICS,
                                      "segments": [seg(1, 0, 6, "讲合同"), seg(2, 10, 6, "聊吃饭")]},
             "questions.json": QS,
             "brief_answers.json": {"answers": {}, "custom": custom, "rules": {}, "rules_version": RV}}
    for rel, obj in files.items():
        (pdir / "work" / rel).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return pdir


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    return tmp_path


def test_cmd_select_interprets_custom_and_reports_it(project, monkeypatch, consented, capsys):
    pdir = _project(project, {EXTRA: "不要吃饭那段"})
    fake = Fake({"items": [{"key": EXTRA, "rules": [{"kind": "exclude", "value": ["聊吃饭"]}]}]})
    stages = []
    monkeypatch.setattr(aicut, "metered", lambda work, stage, *a, **k: stages.append(stage) or fake)
    aicut.cmd_select(Namespace(name="p", target=None))
    sel = json.loads((pdir / "work/selection.json").read_text(encoding="utf-8"))
    assert sel["rules"]["exclude_topics"] == ["聊吃饭"]
    assert stages == [custom_rules.STAGE] and fake.calls == 1
    assert "不出现话题「聊吃饭」" in capsys.readouterr().out
    aicut.cmd_select(Namespace(name="p", target=None))   # 第二次：命中缓存，不再调用
    assert fake.calls == 1


def test_cmd_select_failure_dies_and_keeps_answers(project, monkeypatch, consented, capsys):
    pdir = _project(project, {"q1": "背影收尾"})
    before = (pdir / "work/brief_answers.json").read_text(encoding="utf-8")
    monkeypatch.setattr(aicut, "metered", lambda *a, **k: Fake(LLMError("HTTP 500: boom")))
    with pytest.raises(SystemExit) as ei:
        aicut.cmd_select(Namespace(name="p", target=None))
    assert ei.value.code == 1
    out = capsys.readouterr().out
    assert "boom" in out and "答案已保存" in out
    assert not (pdir / "work/selection.json").exists()
    assert (pdir / "work/brief_answers.json").read_text(encoding="utf-8") == before


def test_cmd_select_with_custom_needs_consent(project, monkeypatch):
    _project(project, {"q1": "背影收尾"})
    monkeypatch.setattr(aicut, "metered", lambda *a, **k: pytest.fail("没确认外发不该建 client"))
    with pytest.raises(SystemExit):
        aicut.cmd_select(Namespace(name="p", target=None))


def test_cmd_select_without_custom_stays_local(project, monkeypatch):
    pdir = _project(project, {})
    monkeypatch.setattr(aicut, "metered", lambda *a, **k: pytest.fail("没填自定义不该调用模型"))
    aicut.cmd_select(Namespace(name="p", target=None))  # 也不需要外发确认
    assert (pdir / "work/selection.json").exists()


def test_cmd_select_ignores_custom_for_vanished_questions(project, monkeypatch):
    pdir = _project(project, {"q9": "题目已经重新生成过了"})
    monkeypatch.setattr(aicut, "metered", lambda *a, **k: pytest.fail("对不上题目的自定义不换算"))
    aicut.cmd_select(Namespace(name="p", target=None))
    assert (pdir / "work/selection.json").exists()


def test_question_bound_custom_is_not_used_after_questions_were_regenerated(project, monkeypatch, consented):
    pdir = _project(project, {"q1": "背影收尾", EXTRA: "不要吃饭那段"})
    answers = json.loads((pdir / "work/brief_answers.json").read_text(encoding="utf-8"))
    answers["questions_digest"] = "旧题目的摘要"
    (pdir / "work/brief_answers.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    seen = []
    fake = Fake({"items": [{"key": EXTRA, "rules": [{"kind": "exclude", "value": ["聊吃饭"]}]}]})
    fake.chat_json = lambda system, user, **k: seen.append(user) or fake.payload
    monkeypatch.setattr(aicut, "metered", lambda *a, **k: fake)
    aicut.cmd_select(Namespace(name="p", target=None))
    sel = json.loads((pdir / "work/selection.json").read_text(encoding="utf-8"))
    assert "背影收尾" not in seen[0]                                  # 旧题目上的自定义不外发、不换算
    assert sel["rules"]["exclude_topics"] == ["聊吃饭"]                # 「其他想法」不绑题目，照常生效
    assert any("背影收尾" in w and "未生效" in w for w in sel["warnings"])


# ---------------------------------------------------------------- ⑤ 查看 AI 提示词：选段记下这次用的提示词
def test_run_records_the_prompt_used_for_this_selection(tmp_path):
    sp, ap = _files(tmp_path, {"answers": {}, "rules": {}, "rules_version": RV})
    custom = {"items": [item(EXTRA, "不要吃饭那段", [{"kind": "exclude", "value": ["聊吃饭"]}])],
              "prompt": {"system": "系统", "user": "用户"}, "reply": {"items": []}, "at": "2026-10-29T10:00:00"}
    res = select.run(sp, ap, tmp_path, custom=custom)
    saved = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    expected = {"system": "系统", "user": "用户", "reply": {"items": []}, "at": "2026-10-29T10:00:00"}
    assert res["custom_prompt"] == expected and saved["custom_prompt"] == expected


def test_run_without_custom_records_no_prompt(tmp_path):
    sp, ap = _files(tmp_path, {"answers": {}})
    assert select.run(sp, ap, tmp_path)["custom_prompt"] is None


def test_selection_rules_in_plain_words():
    lines = custom_rules.describe_selection_rules({
        "must_topics": ["讲合同"], "exclude_topics": ["聊吃饭"], "ending": "leave", "focus": "ensemble",
        "pacing": "tight", "must_lines": ["九千八包含所有耗材"], "ignored_answers": ["旧答案"]})
    text = "\n".join(lines)
    for word in ("讲合同", "聊吃饭", "离开", "群像", "紧凑", "九千八包含所有耗材"):
        assert word in text
    assert "旧答案" not in text and len(lines) == 6


def test_selection_rules_skip_empty_values():
    lines = custom_rules.describe_selection_rules({"must_topics": [], "exclude_topics": [], "ending": None,
                                                    "focus": None, "pacing": "normal", "must_lines": []})
    assert lines == ["节奏正常"]
    assert custom_rules.describe_selection_rules(None) == []
