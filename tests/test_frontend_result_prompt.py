"""⑤ 查看 AI 提示词（node vm）：顶栏按钮、点了才拉接口、弹窗内容（提示词 / 回复 / 换算 / 最终规则）、转义、出错提示。"""
import pytest

from fe_harness import NODE
from fe_result import PROJECT_Q, in_result, text_of

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

PROMPT_PATH = f"/api/result/prompt?project={PROJECT_Q}"
CALLED = {"called": True, "recorded": True, "system": "你是纪录片剪辑顾问<script>",
          "user": "剪辑师写了 <img src=x onerror=alert(1)>", "reply": '{\n  "items": []\n}',
          "at": "2026-10-29T10:00:00",
          "items": [{"text": "背影<b>收尾</b>", "rules": "结尾落在离开 / 背影", "note": ""},
                    {"text": "加点音乐", "rules": "", "note": "和选段<i>无关</i>"}],
          "rules": ["必须覆盖话题「讲合同」", "节奏<u>正常</u>"]}
NOT_CALLED = {"called": False, "recorded": False, "system": None, "user": None, "reply": None, "at": None,
              "items": [], "rules": ["节奏正常"]}
OLD = {**CALLED, "recorded": False, "system": None, "user": None, "reply": None, "at": None}
OPEN = """await act('openAiPrompt'); await tick(); await tick();
  return [el('#modalTitle').textContent, el('#modalBody').innerHTML, el('#mask').classList.contains('on'),
          calls.filter(c => c.path.startsWith('/api/result/prompt')).map(c => c.path), el('#toast').textContent];"""


def _open(payload):
    return in_result(OPEN, {"GET /api/result/prompt": payload})


def test_top_bar_has_the_button_and_nothing_is_fetched_until_clicked():
    top, paths = in_result("""return [el('#rTop').innerHTML,
      calls.filter(c => c.path.startsWith('/api/result/prompt')).length];""")
    assert 'data-act="openAiPrompt"' in top and "查看 AI 提示词" in text_of(top) and paths == 0


def test_called_shows_prompts_reply_items_and_rules_all_escaped():
    title, body, on, paths, _ = _open(CALLED)
    assert on is True and title == "发给 AI 的提示词" and paths == [PROMPT_PATH]
    text = text_of(body)
    for part in ("系统提示词", "用户提示词", "AI 的回复", "2026-10-29 10:00", "结尾落在离开 / 背影",
                 "未生效", "最终选段规则", "必须覆盖话题「讲合同」"):
        assert part in text
    for raw in ("<script>", "<img", "<b>收尾", "<i>无关", "<u>正常"):
        assert raw not in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body and "<pre" in body


def test_not_called_says_no_ai_was_used_and_still_lists_rules():
    _, body, on, _, _ = _open(NOT_CALLED)
    text = text_of(body)
    assert on is True and "本次选段没有调用 AI" in text and "节奏正常" in text
    assert "系统提示词" not in text and "<pre" not in body


def test_old_conversion_without_record_says_so_and_shows_items():
    _, body, _, _, _ = _open(OLD)
    text = text_of(body)
    assert "当时没有记录原始提示词" in text and "结尾落在离开 / 背影" in text and "<pre" not in body


def test_error_is_a_toast_not_a_modal():
    _, _, on, _, toast = _open([404, {"error": "还没有选段：请先在「④ 定标准」确认并生成选段"}])
    assert on is False and "还没有选段" in toast


def test_late_reply_after_leaving_result_does_not_open_the_modal():
    on = in_result("""const p = act('openAiPrompt'); state.view = 'criteria'; await p; await tick();
      return el('#mask').classList.contains('on');""", {"GET /api/result/prompt": CALLED})
    assert on is False


def test_dollar_patterns_and_placeholders_in_text_are_shown_verbatim():
    payload = {**CALLED, "items": [{"text": "价格 $& $$ 封顶 {rules}", "rules": "节奏 $1 紧凑", "note": ""}]}
    _, body, _, _, _ = _open(payload)
    assert "「价格 $&amp; $$ 封顶 {rules}」→ 节奏 $1 紧凑" in text_of(body)


def test_late_reply_after_switching_project_does_not_open_the_modal():
    on = in_result("""const p = act('openAiPrompt'); state.project = '别的项目'; await p; await tick();
      return el('#mask').classList.contains('on');""", {"GET /api/result/prompt": CALLED})
    assert on is False


def test_prompt_blocks_are_keyboard_scrollable():
    _, body, _, _, _ = _open(CALLED)
    assert body.count('tabindex="0"') == 3
