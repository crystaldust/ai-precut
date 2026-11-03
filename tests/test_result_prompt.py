"""⑤ 查看 AI 提示词：GET /api/result/prompt 返回生成当前选段时实际发给 AI 的提示词、原始回复和最终规则。"""
import json

import pytest

from conftest import call, make_project
from gui import result_payload
from pipeline import questions

EXTRA = questions.CUSTOM_EXTRA
RULES = {"must_topics": ["讲合同"], "exclude_topics": [], "ending": "leave", "focus": None,
         "pacing": "normal", "must_lines": []}
ITEMS = [{"key": EXTRA, "text": "背影收尾", "rules": [{"kind": "ending", "value": "leave"}], "note": ""},
         {"key": "q1", "text": "加点音乐", "rules": [], "note": "和选段无关"}]
RECORD = {"system": "你是纪录片剪辑顾问", "user": "剪辑师在决策问题里写了自己的想法 <b>x</b>",
          "reply": {"items": [{"key": EXTRA, "rules": [{"kind": "ending", "value": "leave"}]}]},
          "at": "2026-10-29T10:00:00"}


def _selection(**extra):
    return json.dumps({"shots": [], "rules": RULES, **extra}, ensure_ascii=False)


# ---------------------------------------------------------------- 数据
def test_with_custom_returns_recorded_prompt_reply_items_and_rules(tmp_path):
    pdir = make_project(tmp_path, **{"work/selection.json": _selection(custom_rules=ITEMS, custom_prompt=RECORD)})
    out = result_payload.ai_prompt(pdir)
    assert out["called"] is True and out["recorded"] is True
    assert (out["system"], out["user"], out["at"]) == (RECORD["system"], RECORD["user"], RECORD["at"])
    assert json.loads(out["reply"]) == RECORD["reply"]
    assert out["items"] == [{"text": "背影收尾", "rules": "结尾落在离开 / 背影", "note": ""},
                            {"text": "加点音乐", "rules": "", "note": "和选段无关"}]
    assert out["rules"] == ["必须覆盖话题「讲合同」", "结尾落在离开 / 背影", "节奏正常"]


def test_without_custom_says_no_ai_call_but_lists_rules(tmp_path):
    pdir = make_project(tmp_path, **{"work/selection.json": _selection(custom_rules=[], custom_prompt=None)})
    out = result_payload.ai_prompt(pdir)
    assert out["called"] is False and out["recorded"] is False and out["system"] is None
    assert out["items"] == [] and "结尾落在离开 / 背影" in out["rules"]


def test_old_selection_without_record_is_called_but_not_recorded(tmp_path):
    pdir = make_project(tmp_path, **{"work/selection.json": _selection(custom_rules=ITEMS)})
    out = result_payload.ai_prompt(pdir)
    assert out["called"] is True and out["recorded"] is False and out["user"] is None and out["reply"] is None
    assert len(out["items"]) == 2


def test_selection_from_before_custom_answers_is_not_called(tmp_path):
    pdir = make_project(tmp_path, **{"work/selection.json": _selection()})
    out = result_payload.ai_prompt(pdir)
    assert out["called"] is False and out["items"] == []


@pytest.mark.parametrize("bad", [{"custom_rules": "坏", "custom_prompt": "坏", "rules": "坏"},
                                 {"custom_rules": [1, None], "custom_prompt": {"system": 1}}])
def test_malformed_fields_degrade_to_nothing(tmp_path, bad):
    pdir = make_project(tmp_path, **{"work/selection.json": json.dumps(bad)})
    out = result_payload.ai_prompt(pdir)
    assert out["recorded"] is False and out["items"] == [] and isinstance(out["rules"], list)


def test_no_selection_raises_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="还没有选段"):
        result_payload.ai_prompt(make_project(tmp_path))


# ---------------------------------------------------------------- 接口
@pytest.mark.usefixtures("consented")
def test_api_returns_prompt(gui_server):
    make_project(gui_server.root, **{"work/selection.json": _selection(custom_rules=ITEMS, custom_prompt=RECORD)})
    status, body, _ = call(gui_server, "GET", "/api/result/prompt?project=p1")
    assert status == 200 and json.loads(body)["user"] == RECORD["user"]


@pytest.mark.usefixtures("consented")
def test_api_404_without_selection_and_409_when_corrupt(gui_server):
    make_project(gui_server.root)
    status, body, _ = call(gui_server, "GET", "/api/result/prompt?project=p1")
    assert status == 404 and "还没有选段" in json.loads(body)["error"]
    (gui_server.root / "p1" / "work" / "selection.json").write_text("{坏", encoding="utf-8")
    status, _, _ = call(gui_server, "GET", "/api/result/prompt?project=p1")
    assert status == 409


@pytest.mark.usefixtures("consented")
def test_api_unknown_project_is_404(gui_server):
    status, _, _ = call(gui_server, "GET", "/api/result/prompt?project=nope")
    assert status == 404


def test_record_without_reply_shows_no_reply(tmp_path):
    record = {k: v for k, v in RECORD.items() if k != "reply"}
    pdir = make_project(tmp_path, **{"work/selection.json": _selection(custom_rules=ITEMS, custom_prompt=record)})
    out = result_payload.ai_prompt(pdir)
    assert out["recorded"] is True and out["reply"] is None


def test_non_object_selection_is_corrupt(tmp_path):
    from pipeline import schema
    pdir = make_project(tmp_path, **{"work/selection.json": "[]"})
    with pytest.raises(schema.CorruptJSON):
        result_payload.ai_prompt(pdir)
