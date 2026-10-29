"""④ 决策问题「自定义」前端（node vm）：每题一个自定义 + 题后「其他想法」、单选替换 / 多选并存、草稿与闸门带上、上次换算结果。"""
import json

import pytest

from fe_criteria import ALL_DECIDED, CONFIRM, in_criteria
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def custom_input(target, value):
    """模拟在自定义输入框里打字：target = 题下标（'0'）或 'extra'。"""
    data = "{extra: '1'}" if target == "extra" else f"{{q: '{target}'}}"
    return f"act('critCustomInput', {data}, {{value: {json.dumps(value, ensure_ascii=False)}}});"


# ---------------------------------------------------------------- 渲染
def test_each_question_gets_a_custom_option_and_an_extra_box_follows():
    html = in_criteria("return el('#cQuestions').innerHTML;")
    assert html.count('data-act="critCustomPick"') == 2
    assert 'data-act="critCustomPick" data-q="0"' in html and 'data-act="critCustomPick" data-q="1"' in html
    assert "其他想法（自定义）" in html
    assert 'data-input="critCustomInput" data-extra="1"' in html and 'maxlength="200"' in html
    assert html.count('data-input="critCustomInput"') == 1   # 题内的输入框只在选了「自定义」后出现


def test_saved_custom_text_is_shown_escaped_with_its_box_open():
    data = {**CONFIRM, "custom": {"q1": "背影<b>收尾</b>", "_extra": "别<i>出现</i>价格"}}
    html = in_criteria("return el('#cQuestions').innerHTML;", {"GET /api/confirm": data})
    assert 'data-input="critCustomInput" data-q="0"' in html
    assert "背影&lt;b&gt;收尾&lt;/b&gt;" in html and "别&lt;i&gt;出现&lt;/i&gt;价格" in html
    assert "<b>收尾" not in html


# ---------------------------------------------------------------- 单选：自定义替换选项
def test_single_custom_replaces_the_option_and_picking_an_option_clears_it():
    out = in_criteria(f"""act('critPick', {{q: '0', o: '0'}}); act('critCustomPick', {{q: '0'}});
      const a = JSON.stringify(C().answers);
      {custom_input('0', '以拥抱收尾')}
      const b = JSON.stringify(answerBody(C()));
      act('critPick', {{q: '0', o: '1'}});
      return [a, b, JSON.stringify(answerBody(C()))];""")
    assert json.loads(out[0]) == {}
    assert json.loads(out[1]) == {"answers": {}, "custom": {"q1": "以拥抱收尾"}}
    assert json.loads(out[2]) == {"answers": {"q1": "全部"}}


def test_single_custom_option_renders_as_selected_radio():
    html = in_criteria("act('critCustomPick', {q: '0'}); return el('#cQuestions').innerHTML;")
    start = html.index('data-act="critCustomPick" data-q="0"')
    label = html[html.rindex("<label", 0, start):html.index("</label>", start)]
    assert 'class="opt sel"' in label and 'type="radio" checked' in label


# ---------------------------------------------------------------- 多选：自定义与选项并存
def test_multi_custom_coexists_and_unchecking_drops_its_text():
    out = in_criteria(f"""act('critPick', {{q: '1', o: '0'}}); act('critCustomPick', {{q: '1'}});
      {custom_input('1', '再保留吃饭')}
      const a = JSON.stringify(answerBody(C()));
      act('critCustomPick', {{q: '1'}});
      return [a, JSON.stringify(answerBody(C())), el('#cQuestions').innerHTML.includes('data-input="critCustomInput" data-q="1"')];""")
    assert json.loads(out[0]) == {"answers": {"q2": ["合同"]}, "custom": {"q2": "再保留吃饭"}}
    assert json.loads(out[1]) == {"answers": {"q2": ["合同"]}}
    assert out[2] is False


# ---------------------------------------------------------------- 其他想法、目录、草稿
def test_extra_idea_is_saved_in_the_debounced_draft():
    out = in_criteria(f"""{custom_input('extra', '  不要出现价格 ')} await runTimers(); return draftPosts();""")
    assert out == [{"project": "新项目", "answers": {}, "custom": {"_extra": "不要出现价格"}}]


def test_custom_input_does_not_rerender_the_questions():
    out = in_criteria(f"""act('critCustomPick', {{q: '0'}}); const before = el('#cQuestions').innerHTML;
      {custom_input('0', '以拥抱收尾')} return before === el('#cQuestions').innerHTML;""")
    assert out is True   # 重画会让输入框丢焦点


def test_toc_counts_custom_only_once_it_has_text():
    out = in_criteria(f"""act('critCustomPick', {{q: '0'}});
      const a = tocItems(C())[2].text; {custom_input('0', '   ')} const b = tocItems(C())[2].text;
      {custom_input('0', '以拥抱收尾')} return [a, b, tocItems(C())[2].text];""")
    assert out == ["已答 0/2", "已答 0/2", "已答 1/2"]


def test_extra_idea_is_not_a_question_in_the_toc():
    out = in_criteria(f"""{custom_input('extra', '不要价格')} return tocItems(C())[2].text;""")
    assert out == "已答 0/2"


def test_custom_text_is_capped_at_max_chars():
    out = in_criteria(f"""{custom_input('extra', '长' * 250)} return answerBody(C()).custom._extra.length;""")
    assert out == 200


def test_bad_indices_are_ignored():
    out = in_criteria("""act('critCustomPick', {q: '9'}); act('critCustomInput', {q: '9'}, {value: 'x'});
      await runTimers(); return [draftPosts().length, JSON.stringify(answerBody(C()))];""")
    assert out == [0, '{"answers":{}}']


# ---------------------------------------------------------------- 上次换算结果
UNDERSTOOD = {**CONFIRM, "custom": {"q1": "背影收尾", "_extra": "加点音乐"},
              "custom_understood": {"q1": {"rules": "结尾落在<b>离开</b>", "note": ""},
                                    "_extra": {"rules": "", "note": "和<i>选段</i>无关"}}}


def test_last_understanding_is_shown_escaped():
    html = in_criteria("return el('#cQuestions').innerHTML;", {"GET /api/confirm": UNDERSTOOD})
    assert "AI 理解为：结尾落在&lt;b&gt;离开&lt;/b&gt;" in html
    assert "上次没能换算成选段规则：和&lt;i&gt;选段&lt;/i&gt;无关" in html


def test_understanding_hides_once_the_text_changes():
    out = in_criteria(f"""const node = () => el('#cuQ0');
      {custom_input('0', '背影收尾，慢一点')} const a = node().hidden;
      {custom_input('0', '背影收尾')} return [a, node().hidden];""", {"GET /api/confirm": UNDERSTOOD})
    assert out == [True, False]   # 改了文字：上次的换算不再对应它；改回来又对上


# ---------------------------------------------------------------- 闸门带上自定义
def test_gate_confirm_sends_custom():
    setup = """window.__respond = (m, p, b) => m === 'POST' && p === '/api/confirm/answers'
        ? [200, {ok: true, job_id: null, wizard: null}] : respond(m, p, b);"""
    out = in_criteria(f"""{setup} {custom_input('extra', '不要价格')}
      await act('gate'); await runTimers();
      return draftPosts().filter(b => b.confirmed === true);""", {"GET /api/confirm": ALL_DECIDED})
    assert len(out) == 1 and out[0]["custom"] == {"_extra": "不要价格"} and out[0]["answers"] == ALL_DECIDED["answers"]


# ---------------------------------------------------------------- 审查修复（可访问性 / 稳健）
def test_custom_controls_are_keyboard_reachable_and_named_per_question():
    html = in_criteria("act('critCustomPick', {q: '1'}); return el('#cQuestions').innerHTML;")
    start = html.index('data-act="critCustomPick" data-q="1"')
    label = html[start:html.index("</label>", start)]
    assert "tabindex" not in label
    assert 'aria-label="第 2 题 · 自定义"' in html and 'aria-label="其他想法（自定义）"' in html


def test_custom_for_unknown_question_is_not_switched_on():
    data = {**CONFIRM, "custom": {"q9": "旧题目的", "q1": "背影"}}
    out = in_criteria("return C().customOn;", {"GET /api/confirm": data})
    assert out == ["q1"]


def test_understood_hint_without_note_does_not_say_undefined():
    data = {**CONFIRM, "custom": {"q1": "背影"}, "custom_understood": {"q1": {"rules": ""}}}
    html = in_criteria("return el('#cQuestions').innerHTML;", {"GET /api/confirm": data})
    assert "undefined" not in html
