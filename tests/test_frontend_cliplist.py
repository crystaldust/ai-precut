"""M13c Task 16：剪辑列表与标记（node vm）：S / A / D / X、乐观更新与回滚、P9 互斥提示、P8 撤销栈、剪辑列表面板。"""
import pytest

from fe_browse import BROWSE, CLIP, STALE_WIZARD, in_browse, mark_ok
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

S1_LISTED = {"id": "S1", "must_keep": True, "unusable": False, "level": 3, "override": False}
CLIP_S1 = {**CLIP, "items": [{"id": "S1", "start": 0, "end": 6, "dur": 6, "topic": "讲合同", "text": "甲<b>"}],
           "total": 6}
OK_MUST = {"POST /api/browse/must": mark_ok(S1_LISTED, CLIP_S1)}


# ---------------------------------------------------------------- 键盘流：↓ → Space → S
def test_keyboard_flow_down_space_s_adds_to_clip_list():
    out = in_browse("""let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); }; el('#bPv').paused = true;
      await press('ArrowDown'); await press('Space'); const s = press('KeyS');
      const instant = [el('#r0').classList.contains('in-list'), el('#t0').textContent];
      await s; await tick();
      return [played, instant, posts(), el('#bPanel').innerHTML];""", OK_MUST)
    played, instant, posts, panel = out
    assert played == 1 and instant == [True, "✓ 剪辑列表"]
    assert posts == [["/api/browse/must", {"project": "新项目", "id": "S1", "must": True}]]
    assert "1 段" in panel and "00:06" not in panel and "0:06" in panel


def test_s_with_no_current_segment_does_nothing():
    out = in_browse("await press('KeyS'); return posts();", OK_MUST)
    assert out == []


def test_s_removes_when_already_in_list():
    out = in_browse("""act('jumpSeg', {i: '3'}); await press('KeyS'); return [posts(), el('#r3').classList.contains('in-list')];""",
                    {"POST /api/browse/must": mark_ok({"id": "S4", "must_keep": False, "unusable": False, "level": 3},
                                                      {**CLIP, "items": [], "total": 0})})
    assert out[0] == [["/api/browse/must", {"project": "新项目", "id": "S4", "must": False}]]
    assert out[1] is False


def test_key_auto_repeat_is_ignored_for_marks():
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyS', {repeat: true}); await press('KeyA', {repeat: true});
      return posts();""", OK_MUST)
    assert out == []


def test_typing_in_input_does_not_trigger_shortcuts():
    out = in_browse("""act('jumpSeg', {i: '0'});
      for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) await press('KeyS', {target: {tagName: tag}});
      await press('KeyS', {target: {tagName: 'DIV', isContentEditable: true}});
      return posts();""", OK_MUST)
    assert out == []


# ---------------------------------------------------------------- 乐观更新、成功、失败回滚
def test_success_uses_server_clip_list_and_updates_step_bar_without_refetch():
    out = in_browse("""act('jumpSeg', {i: '0'}); const before = calls.filter(c => c.path.startsWith('/api/state')).length;
      await toggleList(B().segs[0]);
      return [el('#steps').innerHTML, el('#banner').innerHTML, calls.filter(c => c.path.startsWith('/api/state')).length - before,
              state.data.wizard.steps[4].status];""", OK_MUST)
    steps, banner, refetch, status = out
    assert "看结果 ⚠" in steps and 'title="素材标记改过了 · 重新选段"' in steps  # ⑤ 的横幅进入 ⑤ 时才显示
    assert banner == "" and refetch == 0 and status == "stale"


def test_failure_rolls_back_and_toasts_server_reason():
    out = in_browse("""act('jumpSeg', {i: '0'}); await toggleList(B().segs[0]);
      return [B().segs[0].must_keep, el('#r0').classList.contains('in-list'), el('#toast').textContent, B().undo.length];""",
                    {"POST /api/browse/must": [409, {"error": "人工裁决文件损坏"}]})
    assert out[:2] == [False, False] and "人工裁决文件损坏" in out[2] and out[3] == 0


def test_network_failure_rolls_back():
    out = in_browse("""window.__fail = '断网'; await toggleList(B().segs[0]);
      return [B().segs[0].must_keep, el('#toast').textContent];""")
    assert out[0] is False and "断网" in out[1]


def test_p9_must_on_unusable_cancels_unusable_and_says_so():
    out = in_browse("""await toggleList(B().segs[4]);
      return [B().segs[4].unusable, B().segs[4].must_keep, el('#toast').textContent, el('#r4').classList.contains('unusable')];""",
                    {"POST /api/browse/must": mark_ok({"id": "S5", "must_keep": True, "unusable": False, "level": 3},
                                                      CLIP_S1, cleared="unusable")})
    assert out == [False, True, "已取消不可用并放入剪辑列表", False]


def test_p9_unusable_on_listed_removes_from_list_and_says_so():
    out = in_browse("""await markUnusable(B().segs[3]);
      return [B().segs[3].unusable, B().segs[3].must_keep, el('#toast').textContent, el('#r3').classList.contains('in-list')];""",
                    {"POST /api/browse/unusable": mark_ok({"id": "S4", "must_keep": False, "unusable": True, "level": 3},
                                                          {**CLIP, "items": [], "total": 0}, cleared="must_keep",
                                                          removed_shots=[])})
    assert out == [True, False, "已移出剪辑列表并标为不可用", False]


def test_optimistic_unusable_on_listed_segment_is_mutually_exclusive_immediately():
    out = in_browse("""const p = markUnusable(B().segs[3]);
      const instant = [B().segs[3].unusable, B().segs[3].must_keep]; await p; return instant;""",
                    {"POST /api/browse/unusable": mark_ok({"id": "S4", "must_keep": False, "unusable": True},
                                                          {**CLIP, "items": [], "total": 0}, cleared="must_keep",
                                                          removed_shots=[])})
    assert out == [True, False]


def test_unusable_reports_removed_shots():
    out = in_browse("""await markUnusable(B().segs[1]); return el('#toast').textContent;""",
                    {"POST /api/browse/unusable": mark_ok({"id": "S2", "unusable": True, "must_keep": False},
                                                          removed_shots=[{"id": "a"}, {"id": "b"}])})
    assert out == "已从分镜表移除 2 镜"


def test_unusable_with_both_effects_reports_both():
    out = in_browse("""await markUnusable(B().segs[3]); return el('#toast').textContent;""",
                    {"POST /api/browse/unusable": mark_ok({"id": "S4", "unusable": True, "must_keep": False},
                                                          cleared="must_keep", removed_shots=[{"id": "a"}])})
    assert "已移出剪辑列表并标为不可用" in out and "已从分镜表移除 1 镜" in out


def test_x_key_marks_unusable_and_second_x_unmarks():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); await press('KeyX'); const first = posts().slice();
      await press('KeyX'); return [first, posts()[1]];""")
    assert out[0] == [["/api/browse/unusable", {"project": "新项目", "id": "S2", "unusable": True}]]
    assert out[1] == ["/api/browse/unusable", {"project": "新项目", "id": "S2", "unusable": False}]


# ---------------------------------------------------------------- A / D
def test_a_and_d_set_level_and_repaint_tag_immediately():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); const p = press('KeyA');
      const instant = [B().segs[1].level, el('#lv1').textContent]; await p;
      await press('KeyD'); return [instant, posts(), B().segs[1].level, el('#lv1').textContent];""")
    assert out[0] == [3, "可用"]
    assert out[1] == [["/api/browse/level", {"project": "新项目", "id": "S2", "level": 3}],
                      ["/api/browse/level", {"project": "新项目", "id": "S2", "level": 1}]]
    assert out[2] == 1 and out[3] == "废片"


def test_level_failure_rolls_back_tag():
    out = in_browse("""act('jumpSeg', {i: '1'}); await press('KeyA'); return [B().segs[1].level, el('#lv1').textContent, B().undo.length];""",
                    {"POST /api/browse/level": [500, {"error": "炸了"}]})
    assert out == [2, "待定", 0]


def test_a_on_already_manually_usable_is_a_no_op():
    out = in_browse("""B().segs[0].override = true; act('jumpSeg', {i: '0'}); await press('KeyA'); return posts();""")
    assert out == []


# ---------------------------------------------------------------- 撤销（P8）
def test_z_after_s_sends_inverse_request():
    out = in_browse("""sim(); act('jumpSeg', {i: '0'}); await press('KeyS'); await press('KeyZ');
      return [posts().map(p => p[1].must), B().segs[0].must_keep, B().undo.length];""")
    assert out[0] == [True, False] and out[2] == 0


def test_cmd_z_is_alias_for_undo():
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyS'); await press('KeyZ', {metaKey: true});
      return posts().length;""", OK_MUST)
    assert out == 2


def test_z_after_a_with_no_manual_level_sends_null():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); await press('KeyA'); await press('KeyZ');
      return [posts().map(p => p[1].level), B().segs[1].level, B().segs[1].override];""")
    assert out == [[3, None], 2, False]


def test_z_after_a_with_existing_manual_level_restores_previous_level():
    out = in_browse("""B().segs[1].override = true; B().segs[1].level = 1; sim(); act('jumpSeg', {i: '1'});
      await press('KeyA'); await press('KeyZ'); return posts().map(p => p[1].level);""")
    assert out == [3, 1]


def test_z_after_x_unmarks_unusable():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); await press('KeyX'); await press('KeyZ');
      return [posts().map(p => p[1].unusable), B().segs[1].unusable];""")
    assert out == [[True, False], False]


def test_z_after_s_that_cleared_unusable_restores_unusable():
    out = in_browse("""sim(); await toggleList(B().segs[4]); await press('KeyZ');
      return [posts().map(p => p[0]), posts()[1][1], B().segs[4].unusable, B().segs[4].must_keep];""")
    assert out[0] == ["/api/browse/must", "/api/browse/unusable"]
    assert out[1] == {"project": "新项目", "id": "S5", "unusable": True}
    assert out[2] is True and out[3] is False


def test_z_with_empty_stack_says_nothing_to_undo_and_sends_nothing():
    out = in_browse("await press('KeyZ'); return [posts(), el('#toast').textContent];")
    assert out == [[], "没有可撤销的操作"]


def test_undo_is_not_itself_undoable():
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyS'); await press('KeyZ'); await press('KeyZ');
      return [posts().length, el('#toast').textContent];""", OK_MUST)
    assert out == [2, "没有可撤销的操作"]


def test_undo_stack_keeps_at_most_fifty_steps():
    out = in_browse("""sim(); for (let i = 0; i < 55; i++) await toggleList(B().segs[0]);
      return [B().undo.length, UNDO_MAX];""")
    assert out == [50, 50]


def test_undo_stack_cleared_on_project_switch():
    out = in_browse("""await toggleList(B().segs[0]); const had = B().undo.length;
      await selectProject('新项目'); await go('browse'); await tick(); await tick();
      return [had, B().undo.length];""", OK_MUST)
    assert out == [1, 0]


def test_undo_failure_keeps_ui_in_server_state():
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyS');
      window.__respond = () => [500, {error: '炸了'}];
      await press('KeyZ'); return [B().segs[0].must_keep, el('#r0').classList.contains('in-list')];""", OK_MUST)
    assert out == [True, True]


# ---------------------------------------------------------------- 请求顺序与过期响应
def test_same_segment_requests_are_sent_one_after_another():
    out = in_browse("""const orig = window.fetch; let release = null;
      window.fetch = (p, o) => String(p).startsWith('/api/browse/must') && !release
        ? new Promise(r => { release = () => r(orig(p, o)); }) : orig(p, o);
      const a = toggleList(B().segs[0]); await tick();
      const b = toggleList(B().segs[0]); await tick();
      const mid = posts().length; release(); await a; await b; await tick();
      return [mid, posts().map(p => p[1].must)];""", OK_MUST)
    assert out == [0, [True, False]]


def test_response_after_project_switch_is_ignored():
    out = in_browse("""const orig = window.fetch; let release = null;
      window.fetch = (p, o) => String(p).startsWith('/api/browse/must')
        ? new Promise(r => { release = () => r(orig(p, o)); }) : orig(p, o);
      const p = toggleList(B().segs[0]); await tick();
      const old = B(); await selectProject('新项目'); await go('browse'); await tick(); await tick();
      const fresh = B(); release(); await p; await tick();
      return [old === fresh, fresh.undo.length, fresh.segs[0].must_keep, state.data.wizard.steps[4].status,
              el('#steps').innerHTML.includes('⚠')];""", OK_MUST)
    assert out == [False, 0, False, "locked", False]  # 旧项目的响应不能改新项目的步骤条


# ---------------------------------------------------------------- 面板
def test_panel_shows_count_total_target_progress_and_items():
    html = in_browse("return el('#bPanel').innerHTML;")
    assert "剪辑列表" in html and "1 段" in html
    assert "0:05" in html and "1:00" in html and "width:8.3" in html  # 5 / 60
    assert 'data-act="jumpClip"' in html and 'data-act="removeClip"' in html and "✕" in html
    assert "已超出" not in html


def test_panel_over_target_warning_with_suggested_target():
    over = {**CLIP, "total": 100, "target": 60, "over_target": True, "over_by": 40, "suggested_target": 220}
    over = {**over, "total": 220 - 40, "over_by": 40, "suggested_target": 220}
    html = in_browse("return el('#bPanel').innerHTML;",
                     {"GET /api/browse": {**BROWSE, "clip_list": {**over, "total": 100, "target": 60,
                                                                  "over_by": 40, "suggested_target": 220}}})
    assert "已超出目标 0:40，进片时全部保留，建议把目标改为 3:40" in html


def test_panel_empty_state_hint():
    html = in_browse("return el('#bPanel').innerHTML;",
                     {"GET /api/browse": {**BROWSE, "clip_list": {**CLIP, "items": [], "total": 0}}})
    assert "0 段" in html and "按 S" in html


def test_panel_escapes_text_and_ignores_unknown_items():
    clip = {**CLIP, "items": [{"id": "S4", "start": 40, "end": 45, "dur": 5, "topic": "聊吃饭", "text": "<img src=x>"},
                              {"id": "GONE", "start": 1, "end": 2, "dur": 1, "text": "x"}]}
    html = in_browse("return el('#bPanel').innerHTML;", {"GET /api/browse": {**BROWSE, "clip_list": clip}})
    assert "<img" not in html and "&lt;img" in html


def test_panel_item_click_jumps_and_x_removes():
    out = in_browse("""let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      act('jumpClip', {i: '3'}); const cur = B().cur; await act('removeClip', {i: '3'});
      return [cur, played, posts()];""",
                    {"POST /api/browse/must": mark_ok({"id": "S4", "must_keep": False}, {**CLIP, "items": [], "total": 0})})
    assert out[0] == 3 and out[1] == 1
    assert out[2] == [["/api/browse/must", {"project": "新项目", "id": "S4", "must": False}]]


def test_panel_count_updates_optimistically_before_response():
    out = in_browse("""const p = toggleList(B().segs[0]); const mid = el('#bPanel').innerHTML; await p; return mid;""", OK_MUST)
    assert "2 段" in out


def test_toggle_buttons_in_rows_call_the_same_logic():
    out = in_browse("""await act('toggleListIdx', {i: '0'}); await act('markUnusableIdx', {i: '1'}); return posts().map(p => p[0]);""",
                    {**OK_MUST, "POST /api/browse/unusable": mark_ok({"id": "S2", "unusable": True}, removed_shots=[])})
    assert out == ["/api/browse/must", "/api/browse/unusable"]


def test_marks_do_not_redraw_list_and_keep_filter_rows_in_place():
    out = in_browse("""sim(); act('setFilter', {v: 'pending'}); el('#bList').innerHTML += '<!--m-->'; act('jumpSeg', {i: '1'});
      await press('KeyA'); return [el('#bList').innerHTML.includes('<!--m-->'), ids()];""")
    assert out == [True, ["S2"]]


def test_filter_chip_counts_follow_marks():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); await press('KeyA'); return el('#bFilters').innerHTML;""")
    assert "待定 0" in out and "可用 3" in out
