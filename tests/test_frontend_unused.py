"""M14 T11：⑤ 未采用清单（node vm）：原因标签、试听、加回（乐观更新 + 回滚）、防连点。"""
import pytest

from fe_harness import NODE
from fe_result import RESULT, in_result, js, text_of

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_list_shows_title_count_causes_and_escapes_server_text():
    html = in_result("return el('#rUnused').innerHTML;")
    assert "未采用清单（3）" in text_of(html)
    assert "因时长：这个话题的时长已经用完" in html and "你从分镜表里删掉了" in html
    assert "讲退费&lt;b&gt;" in html and "原文&lt;i&gt;九" in html and "<i>九" not in html
    assert "05:00.0" in html  # 时间码


def test_clip_list_items_come_first_and_are_marked():
    html = in_result("return el('#rUnused').innerHTML;")
    assert html.index("U9") < html.index("U1") < html.index("U2")
    first = html[:html.index("U1")]
    assert 'class="un must"' in first and "出片前必须加回" in first
    assert "必留" not in html


def test_empty_list_says_so():
    html = in_result("return el('#rUnused').innerHTML;", result={"unused": []})
    assert "没有未采用的可用片段" in html and "未采用清单（0）" in text_of(html)


def test_audition_plays_from_a_bit_before_to_a_bit_after_in_material_mode():
    out = in_result("""let paused = 0; act('audition', {id: 'U1'}); el('#rPv').pause = () => { paused++; };
      const t0 = el('#rPv').currentTime; const mode = R().mode;
      el('#rPv').currentTime = 36.2; fire('#rPv', 'timeupdate'); const early = paused;
      el('#rPv').currentTime = 36.31; fire('#rPv', 'timeupdate');
      return [mode, t0, early, paused];""")
    assert out[0] == "material" and out[1] == pytest.approx(29.7) and out[2] == 0 and out[3] == 1


def test_audition_of_a_vanished_item_does_nothing():
    out = in_result("act('audition', {id: 'nope'}); return [R().mode, el('#toast').textContent];")
    assert out[0] == "preview"


def test_add_back_inserts_by_time_saves_removes_the_row_at_once_and_reloads():
    out = in_result("""const held = hold(p => p.startsWith('/api/shots'));
      const run = act('addBack', {id: 'U1'}); await tick();
      const mid = [state.shots.map(s => s.id), el('#rUnused').innerHTML.includes('data-id="U1"')];
      const before = rcalls().length;
      held.forEach(r => r()); await run; await tick();
      return [mid, shotPosts()[0].shots.map(s => [s.id, s.in, s.out, s.sub, s.note]),
              el('#toast').textContent, rcalls().length - before];""")
    assert out[0] == [["sh01", "sh03", "sh02"], False]
    assert out[1] == [["sh01", 0, 100, "<b>字幕</b>", ""], ["sh03", 30, 36, "字幕一", "讲合同"], ["sh02", 100, 178, "二", ""]]
    assert out[2] == "已加回第 2 镜（算一次手动修改）" and out[3] == 1


def test_add_back_after_all_shots_appends_at_the_end():
    out = in_result("await act('addBack', {id: 'U9'}); return state.shots.map(s => s.id);")
    assert out == ["sh01", "sh02", "sh03"]


def test_add_back_failure_rolls_back_restores_the_row_and_explains():
    out = in_result("""await act('addBack', {id: 'U1'}); await tick();
      return [state.shots.map(s => s.id), el('#rUnused').innerHTML.includes('data-id="U1"'), el('#toast').textContent];""",
                    routes={"POST /api/shots": [500, {"error": "磁盘满"}]})
    assert out[0] == ["sh01", "sh02"] and out[1] is True and "磁盘满" in out[2]


def test_double_click_on_add_back_inserts_once():
    out = in_result("""const a = act('addBack', {id: 'U1'}); const b = act('addBack', {id: 'U1'}); await a; await b;
      return [state.shots.length, shotPosts().length];""")
    assert out == [3, 1]


def test_add_back_uses_the_local_table_order_not_a_resorted_one():
    out = in_result("""state.shots = [state.shots[1], state.shots[0]];  // 剪辑师手动换过顺序
      await act('addBack', {id: 'U1'}); return state.shots.map(s => s.id);""")
    assert out == ["sh03", "sh02", "sh01"]  # 第一个 in 比 30 大的镜头（本地表里的 sh02）之前


def test_adding_back_marks_the_table_as_edited_in_the_top_bar_after_reload():
    manual = {"edited": True, "count": 1, "changes": ["新增第 2 镜「字幕一」"], "more": 0}
    out = in_result(f"""let n = 0;
      window.__respond = (m, p, b) => (m === 'GET' && p.startsWith('/api/result') && ++n > 0)
        ? [200, {js({**RESULT, "manual": manual})}] : respond(m, p, b);
      await act('addBack', {{id: 'U1'}}); await tick();
      return el('#rTop').innerHTML.includes('openRestoreAi');""")
    assert out is True
