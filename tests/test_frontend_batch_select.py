"""KI-103：③ 看素材的批量选择（node vm）：勾选框、Shift 连选、全选三态、操作栏、批量标记、整批撤销与各种竞态。"""
import json
from pathlib import Path

import pytest

from fe_browse import BROWSE, SEGS, in_browse, seg
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")
STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"

PRE = """
const pick = (i, shift = false, detail = 1) => ACTIONS.pickIdx(node({'data-act': 'pickIdx', 'data-i': String(i)}), {shiftKey: shift, detail});
const sel = () => [...B().sel].sort((a, b) => a - b);
const bposts = () => calls.filter(c => c.path === '/api/browse/batch' && c.method === 'POST');
const sleep = async n => { for (let k = 0; k < n; k++) await tick(); };
"""


def go(script, routes=None):
    return in_browse(PRE + script, routes)


def routes_with(segs):
    return {"GET /api/browse": {**BROWSE, "segments": segs}}


# 话题交错：时间序 A B A B A，按话题视图的显示顺序是 0 2 4 1 3
INTERLEAVED = [seg(i + 1, i * 10, i * 10 + 5, 3, "甲" if i % 2 == 0 else "乙", f"t{i}") for i in range(5)]


# ---------------------------------------------------------------- Task 3：勾选框
def test_rows_have_an_unchecked_checkbox_with_label_and_no_banned_word():
    out = go("return [el('#bList').innerHTML, sel()];")
    html = out[0]
    assert html.count('class="pick"') == 5 and 'data-act="pickIdx" data-i="0"' in html
    assert 'id="pk0"' in html and "aria-label" in html and " checked" not in html and out[1] == []
    assert "必留" not in html


def test_clicking_checkbox_toggles_selection_without_moving_current_or_playing():
    out = go("""act('jumpSeg', {i: '3'}); const pv = el('#bPv'); let played = 0; pv.play = () => { played++; return Promise.resolve(); };
      pick(1); const a = sel(); const cur = B().cur; pick(1); return [a, cur, B().cur, sel(), played];""")
    assert out == [[1], 3, 3, [], 0]


def test_checkbox_click_via_delegation_does_not_trigger_row_jump():
    out = go("""act('jumpSeg', {i: '3'}); const row = node({'data-act': 'jumpSeg', 'data-i': '1'});
      const box = node({'data-act': 'pickIdx', 'data-i': '1'}, row); click(box); await tick();
      return [B().cur, sel()];""")
    assert out == [3, [1]]


def test_picking_paints_row_checkbox_and_blurs_the_checkbox():
    out = go("""const box = node({'data-act': 'pickIdx', 'data-i': '2'}); ACTIONS.pickIdx(box, {shiftKey: false, detail: 1});
      const r = [el('#r2').classList.contains('picked'), el('#pk2').checked, box.blurred];
      pick(2); return [r, el('#r2').classList.contains('picked'), el('#pk2').checked];""")
    assert out == [[True, True, 1], False, False]


def test_hotkeys_still_act_on_current_segment_only_while_rows_are_selected():
    out = go("""sim(); pick(0); pick(1); act('jumpSeg', {i: '2'}); await press('KeyS'); await sleep(2);
      return [posts().map(p => [p[0], p[1].id]), sel()];""")
    assert out == [[["/api/browse/must", "S3"]], [0, 1]]


# ---------------------------------------------------------------- Shift 连选
def test_shift_click_selects_range_in_displayed_order():
    out = go("""pick(0); pick(3, true); return sel();""")
    assert out == [0, 1, 2, 3]


def test_shift_click_on_selected_row_deselects_range_back_to_anchor():
    out = go("""pick(0); pick(4, true); const all = sel(); pick(3); pick(1, true); return [all, sel()];""")
    assert out == [[0, 1, 2, 3, 4], [0, 4]]


def test_shift_click_range_works_upwards_and_updates_row_state():
    out = go("""pick(3); pick(1, true); return [sel(), el('#pk2').checked, el('#r2').classList.contains('picked')];""")
    assert out == [[1, 2, 3], True, True]


def test_shift_click_without_anchor_acts_like_plain_click():
    assert go("pick(2, true); return sel();") == [2]


def test_shift_range_follows_topic_view_order_across_groups():
    out = go("""act('setView', {v: 'topic'}); const shown = [...B().shown]; pick(2); pick(1, true); return [shown, sel()];""",
             routes_with(INTERLEAVED))
    assert out == [[0, 2, 4, 1, 3], [1, 2, 4]]   # 显示序 2 4 1 之间，不是时间序 1 2 3


def test_shift_click_with_anchor_hidden_by_filter_acts_like_plain_click():
    out = go("""pick(0); act('setFilter', {v: 'pending'}); pick(1, true); return sel();""")
    assert out == [1]


# ---------------------------------------------------------------- 全选（当前筛选）
def test_select_all_picks_only_segments_shown_by_current_filter():
    out = go("""act('setFilter', {v: 'usable'}); act('pickAll', {}); return [sel(), el('#bFilters').innerHTML];""")
    assert out[0] == [0, 3] and "全选 2" in out[1]


def test_select_all_checkbox_is_first_in_filters_and_unchecked_by_default():
    html = go("return el('#bFilters').innerHTML;")
    assert html.index("bPickAll") < html.index("view-toggle")
    assert 'data-act="pickAll"' in html and "全选 5" in html and "checked" not in html


def test_select_all_is_tri_state():
    out = go("""const st = () => [el('#bPickAll').checked, el('#bPickAll').indeterminate];
      const none = st(); pick(1); const part = st(); act('pickAll', {}); const full = sel().length;
      const all = st(); act('pickAll', {}); return [none, part, full, all, sel(), st()];""")
    assert out == [[False, False], [False, True], 5, [True, False], [], [False, False]]


def test_select_all_from_partial_selects_everything_shown():
    assert go("pick(2); act('pickAll', {}); return sel();") == [0, 1, 2, 3, 4]


def test_select_all_with_nothing_shown_is_a_noop_and_disabled():
    out = go("""act('setFilter', {v: 'waste'}); act('pickAll', {}); return [sel(), el('#bFilters').innerHTML.includes('全选 0'),
      el('#bBatch').hidden];""", routes_with([SEGS[0]]))
    assert out == [[], True, True]


def test_select_all_in_topic_view_covers_all_groups():
    out = go("act('setView', {v: 'topic'}); act('pickAll', {}); return sel();", routes_with(INTERLEAVED))
    assert out == [0, 1, 2, 3, 4]


def test_picking_keeps_filter_counts_and_select_all_label_in_sync():
    out = go("""pick(0); return el('#bFilters').innerHTML;""")
    assert "全选 5" in out and "全部 5" in out


# ---------------------------------------------------------------- 清空时机
def test_selection_clears_on_filter_view_change():
    out = go("""pick(0); pick(1); act('setFilter', {v: 'all'}); const a = sel();
      pick(0); act('setView', {v: 'topic'}); return [a, sel(), B().selAnchor];""")
    assert out == [[], [], None]


def test_selection_clears_on_reenter_and_project_switch():
    out = go("""pick(0); await go('browse'); await sleep(4); const a = sel(); pick(1);
      await selectProject('新项目'); await go('browse'); await sleep(4); return [a, sel(), el('#bBatch').hidden];""")
    assert out == [[], [], True]


def test_selection_is_pruned_to_rows_still_shown_after_relist():
    out = go("""pick(0); pick(1); B().filter = 'pending'; renderList(); return [sel(), el('#bBatch').innerHTML.includes('已选 1 段')];""")
    assert out == [[1], True]


def test_checked_rows_are_rendered_checked_after_relist():
    out = go("""pick(2); renderList(); const h = el('#bList').innerHTML;
      return [/id="pk2"[^>]* checked/.test(h), /id="pk1"[^>]* checked/.test(h), /id="r2" [^>]*>/.exec(h)[0].includes('picked')];""")
    assert out[0] is True and out[1] is False


# ---------------------------------------------------------------- 操作栏
def test_batch_bar_hidden_without_selection_and_shows_count_and_six_buttons():
    out = go("""const h0 = el('#bBatch').hidden; pick(0); pick(1); const bar = el('#bBatch');
      return [h0, bar.hidden, bar.innerHTML];""")
    assert out[0] is True and out[1] is False
    html = out[2]
    assert "已选 2 段" in html
    for k in ("add", "remove", "usable", "waste", "unusable"):
        assert f'data-act="batchDo" data-k="{k}"' in html
    for label in ("放入剪辑列表", "移出剪辑列表", "标为可用", "标为废片", "标为不可用", "取消选择"):
        assert label in html
    assert 'data-act="batchClear"' in html and "必留" not in html


def test_bar_sits_after_list_in_skeleton():
    html = go("return el('#stage').innerHTML;")
    assert html.index('id="bList"') < html.index('id="bBatch"')


def test_cancel_clears_selection_and_hides_bar():
    out = go("""pick(0); pick(3); act('batchClear', {}); return [sel(), el('#bBatch').hidden, el('#pk0').checked, B().selAnchor];""")
    assert out == [[], True, False, None]


def test_unknown_batch_kind_is_ignored():
    out = go("""pick(0); const r = await ACTIONS.batchDo(node({'data-k': 'nuke'})); return [r, bposts().length, sel()];""")
    assert out == [False, 0, [0]]


# ---------------------------------------------------------------- Task 4：批量操作
def test_add_sends_one_request_with_exact_body_and_applies_server_state():
    out = go("""sim(); pick(0); pick(1); await applyBatch('add'); await sleep(2);
      return [bposts().map(c => c.body), B().segs[0].must_keep, B().segs[1].must_keep, B().clip.items.map(i => i.id),
              sel(), B().undo.length, el('#bBatch').hidden, el('#t0').textContent, el('#r0').classList.contains('in-list')];""")
    assert out[0] == [{"project": "新项目", "items": [{"id": "S1", "must_keep": True}, {"id": "S2", "must_keep": True}]}]
    assert out[1:] == [True, True, ["S1", "S2", "S4"], [], 1, True, "✓ 剪辑列表", True]


def test_add_on_unusable_segment_clears_unusable_and_says_so():
    out = go("""sim(); pick(0); pick(4); await applyBatch('add'); await sleep(2);
      return [bposts()[0].body.items, B().segs[4].unusable, B().segs[4].must_keep, el('#toast').textContent];""")
    assert out[0] == [{"id": "S1", "must_keep": True}, {"id": "S5", "must_keep": True, "unusable": False}]
    assert out[1] is False and out[2] is True
    assert "放入剪辑列表 2 段" in out[3] and "1 段已取消不可用" in out[3]


def test_remove_skips_segments_already_out_of_list():
    out = go("""sim(); pick(0); pick(3); await applyBatch('remove'); await sleep(2);
      return [bposts()[0].body.items, B().segs[3].must_keep, el('#toast').textContent];""")
    assert out[0] == [{"id": "S4", "must_keep": False}] and out[1] is False
    assert "移出剪辑列表 1 段" in out[2] and "1 段本来就是这样" in out[2]


def test_level_batches_send_numeric_level_and_mark_override_locally():
    out = go("""sim(); pick(1); pick(2); await applyBatch('usable'); await sleep(2);
      const first = bposts()[0].body.items; const s = B().segs[1];
      pick(0); await applyBatch('waste'); await sleep(2);
      return [first, s.level, s.override, B().segs[0].level, B().segs[0].level_reason, bposts()[1].body.items];""")
    assert out[0] == [{"id": "S2", "level": 3}, {"id": "S3", "level": 3}]
    assert out[1:5] == [3, True, 1, "人工改为1"] and out[5] == [{"id": "S1", "level": 1}]


def test_level_batch_skips_segments_already_manually_at_that_level():
    out = go("""sim(); await applyBatch('usable'); pick(0); await applyBatch('usable'); await sleep(2);
      B().segs[0].override = true; B().segs[0].level = 3; pick(0); const n = bposts().length; const r = await applyBatch('usable');
      return [n, bposts().length, r, el('#toast').textContent];""")
    assert out[0] == out[1] and out[2] is False and "不需要改" in out[3]


def test_unusable_batch_sends_unusable_only_and_clears_list_flag_and_reports_shots():
    shots = [{"id": "b", "in": 1, "out": 2, "sub": "", "note": ""}, {"id": "c", "in": 3, "out": 4, "sub": "", "note": ""}]
    out = go(f"""sim({{removed: {json.dumps(shots)}}}); pick(0); pick(3); await applyBatch('unusable'); await sleep(2);
      return [bposts()[0].body.items, B().segs[3].must_keep, B().segs[3].unusable, el('#toast').textContent,
              B().undo[0].removed.length, el('#d0').className];""")
    assert out[0] == [{"id": "S1", "unusable": True}, {"id": "S4", "unusable": True}]
    assert out[1] is False and out[2] is True
    assert "已从分镜表移除 2 镜" in out[3] and "已移出剪辑列表" in out[3] and out[4] == 2 and "unusable" in out[5]


def test_nothing_to_change_sends_no_request_and_keeps_selection():
    out = go("""sim(); pick(0); const r = await applyBatch('remove'); return [r, bposts().length, sel(), el('#toast').textContent, B().undo.length];""")
    assert out[0] is False and out[1] == 0 and out[2] == [0] and "不需要改" in out[3] and out[4] == 0


def test_apply_without_selection_does_nothing():
    assert go("sim(); const r = await applyBatch('add'); return [r, calls.filter(c => c.method === 'POST').length];") == [False, 0]


def test_optimistic_update_shows_before_server_answers_and_disables_buttons():
    out = go("""sim(); const held = hold(p => p === '/api/browse/batch'); pick(0); pick(1);
      const run = applyBatch('add'); await sleep(3);
      const mid = [B().segs[0].must_keep, el('#r1').classList.contains('in-list'), el('#bBatch').innerHTML.includes('disabled'),
                   el('#bPanel').innerHTML.includes('3 段'), held.length, sel()];
      held[0](); await run; await sleep(2); return [mid, el('#bBatch').innerHTML.includes('disabled')];""")
    assert out[0] == [True, True, True, True, 1, [0, 1]] and out[1] is False


def test_second_batch_while_one_is_in_flight_is_rejected():
    out = go("""sim(); const held = hold(p => p === '/api/browse/batch'); pick(0);
      const first = applyBatch('add'); await sleep(3); const second = await applyBatch('remove');
      held[0](); await first; await sleep(2); return [second, bposts().length];""")
    assert out == [False, 1]


def test_failure_rolls_back_whole_batch_keeps_selection_and_reports_reason():
    out = go("""sim({fail: path => path === '/api/browse/batch'}); pick(1); pick(4); pick(3);
      const r = await applyBatch('unusable'); await sleep(2);
      return [r, B().segs.map(s => [s.must_keep, s.unusable]), sel(), B().undo.length, el('#toast').textContent,
              el('#bBatch').innerHTML.includes('disabled'), el('#r3').classList.contains('unusable'), B().batchBusy];""")
    assert out[0] is False
    assert out[1] == [[False, False], [False, False], [False, False], [True, False], [False, True]]
    assert out[2] == [1, 3, 4] and out[3] == 0 and "没保存上" in out[4] and "炸了" in out[4]
    assert out[5] is False and out[6] is False and out[7] is False


def test_failure_drops_single_segment_requests_queued_behind_the_batch():
    out = go("""sim({fail: path => path === '/api/browse/batch'}); const held = hold(p => p === '/api/browse/batch'); pick(0);
      const run = applyBatch('add'); await sleep(3); const single = toggleList(B().segs[0]);
      held[0](); await run; await single; await sleep(2);
      return [B().segs[0].must_keep, posts().map(p => p[0]), B().undo.length];""")
    assert out == [False, ["/api/browse/batch"], 0]


def test_success_uses_server_clip_list_wizard_and_merges_server_segments():
    out = go("""sim(); const orig = window.__respond;
      window.__respond = (m, p, b) => { const r = orig(m, p, b); if (p === '/api/browse/batch') r[1].clip_list = {...r[1].clip_list, total: 77, target: 90}; return r; };
      pick(0); await applyBatch('usable'); await sleep(2);
      return [B().clip.total, el('#bPanel').innerHTML.includes('合计'), state.data.wizard.steps.find(s => s.key === 'result').status,
              B().confirmed.get('S1').override];""")
    assert out[0] == 77 and out[1] is True and out[2] == "stale" and out[3] is True


def test_cleared_note_for_unusable_batch_names_list_removals():
    out = go("""sim(); pick(3); await applyBatch('unusable'); await sleep(2); return el('#toast').textContent;""")
    assert "1 段已移出剪辑列表" in out


def test_warning_response_resyncs_like_single_save_and_still_clears_selection():
    warn = {"ok": True, "warning": "已保存，但没能读回最新状态", "segments": None, "clip_list": None, "wizard": None,
            "cleared": {}, "removed_shots": [], "restored": 0, "not_restored": 0}
    out = go("""const saved = JSON.parse(JSON.stringify(B().data)); saved.segments[0].must_keep = true;
      window.__respond = (m, p) => m === 'POST' ? [200, %s] : p.startsWith('/api/browse?') ? [200, saved] : respond(m, p);
      pick(0); await applyBatch('add'); await sleep(4);
      return [B().segs[0].must_keep, el('#toast').textContent, sel(), calls.filter(c => c.path.startsWith('/api/browse?')).length];""" % json.dumps(warn, ensure_ascii=False))
    assert out[0] is True and "已保存" in out[1] and out[2] == [] and out[3] == 2


# ---------------------------------------------------------------- 与单段队列的串行
def test_batch_waits_for_in_flight_single_requests_first():
    out = go("""sim(); const held = hold(p => p.startsWith('/api/browse/must')); const single = toggleList(B().segs[0]); await sleep(2);
      pick(1); const run = applyBatch('add'); await sleep(3); const before = bposts().length;
      held[0](); await single; await run; await sleep(2);
      return [before, posts().map(p => p[0])];""")
    assert out == [0, ["/api/browse/must", "/api/browse/batch"]]


def test_single_mark_pressed_during_batch_is_sent_after_it():
    out = go("""sim(); const held = hold(p => p === '/api/browse/batch'); pick(0); pick(1);
      const run = applyBatch('add'); await sleep(3); act('jumpSeg', {i: '0'}); const s = press('KeyS'); await sleep(3);
      const sentDuring = posts().map(p => p[0]); held[0](); await run; await s; await sleep(3);
      return [sentDuring, posts().map(p => [p[0], p[1].must]), B().segs[0].must_keep, B().undo.length];""")
    assert out[0] == []
    assert out[1] == [["/api/browse/batch", None], ["/api/browse/must", False]]
    assert out[2] is False and out[3] == 2


def test_stale_response_after_project_switch_does_not_touch_the_new_page():
    out = go("""sim(); const held = hold(p => p === '/api/browse/batch'); pick(0);
      const run = applyBatch('add'); await sleep(3); const old = B();
      await selectProject('新项目'); await go('browse'); await sleep(4); const fresh = B();
      held[0](); await run; await sleep(3);
      return [fresh !== old, B() === fresh, B().segs[0].must_keep, B().undo.length, sel(), old.undo.length, B().batchBusy, old.undo[0].done, old.sel.size];""")
    assert out[0] is True and out[1] is True and out[2] is False and out[3] == 0 and out[4] == [] and out[6] is False
    assert out[5] == 1 and out[7] is False and out[8] == 1   # 旧页面对象原样留着，回包没碰它


def test_batch_repaints_panel_filters_and_groups_once_per_phase():
    out = go("""sim(); pick(0); pick(1); pick(2); let panel = 0, filters = 0, groups = 0;
      const p = renderClipPanel, f = renderFilters, g = paintGroups;
      renderClipPanel = (...a) => { panel++; return p(...a); }; renderFilters = (...a) => { filters++; return f(...a); }; paintGroups = () => { groups++; return g(); };
      await applyBatch('usable'); await sleep(2); return [panel, filters, groups];""")
    assert out == [2, 2, 2]   # 乐观一次、回包一次


# ---------------------------------------------------------------- 整批撤销
def test_undo_restores_whole_batch_with_one_request():
    out = go("""sim(); pick(0); pick(1); pick(4); await applyBatch('add'); await sleep(2);
      await press('KeyZ'); await sleep(2);
      return [bposts().length, bposts()[1].body, B().segs.map(s => [s.must_keep, s.unusable]), B().undo.length, el('#toast').textContent,
              B().clip.items.map(i => i.id)];""")
    assert out[0] == 2
    assert out[1] == {"project": "新项目", "items": [
        {"id": "S1", "must_keep": False, "unusable": False, "level": None},
        {"id": "S2", "must_keep": False, "unusable": False, "level": None},
        {"id": "S5", "must_keep": False, "unusable": True, "level": None}]}
    assert out[2] == [[False, False], [False, False], [False, False], [True, False], [False, True]]
    assert out[3] == 0 and "已撤销" in out[4] and out[5] == ["S4"]


def test_undo_of_level_batch_sends_manual_level_or_null_per_segment():
    segs = [seg(1, 0, 6, 3, "讲合同", "甲"), seg(2, 10, 16, 1, "讲合同", "乙", reason="人工改为废片", override=True)]
    out = go("""sim(); pick(0); pick(1); await applyBatch('usable'); await sleep(2); await press('KeyZ'); await sleep(2);
      return [bposts()[1].body.items, B().segs[0].override, B().segs[0].level, B().segs[1].level, B().segs[1].override];""",
             routes_with(segs))
    assert out[0] == [{"id": "S1", "must_keep": False, "unusable": False, "level": None},
                      {"id": "S2", "must_keep": False, "unusable": False, "level": 1}]
    assert out[1] is False and out[2] == 3 and out[3] == 1 and out[4] is True


def test_undo_of_unusable_batch_sends_removed_shots_back_in_the_same_request():
    shots = [{"id": "b", "in": 1, "out": 2, "sub": "", "note": ""}]
    out = go(f"""sim({{removed: {json.dumps(shots)}}}); pick(0); pick(3); await applyBatch('unusable'); await sleep(2);
      await press('KeyZ'); await sleep(2);
      return [bposts().length, bposts()[1].body.restore_shots, bposts()[1].body.items, el('#toast').textContent,
              B().segs[3].must_keep, B().segs[0].unusable];""")
    assert out[0] == 2 and out[1] == shots
    assert out[2] == [{"id": "S1", "must_keep": False, "unusable": False, "level": None},
                      {"id": "S4", "must_keep": True, "unusable": False, "level": None}]
    assert "已恢复 1 镜" in out[3] and out[4] is True and out[5] is False


def test_undo_sends_no_restore_shots_when_nothing_was_removed():
    out = go("""sim(); pick(0); await applyBatch('unusable'); await sleep(2); await press('KeyZ'); await sleep(2);
      return 'restore_shots' in bposts()[1].body;""")
    assert out is False


def test_undo_order_is_batch_then_earlier_single_mark():
    out = go("""sim(); act('jumpSeg', {i: '1'}); await press('KeyS'); pick(0); await applyBatch('add'); await sleep(2);
      await press('KeyZ'); const a = [B().segs[0].must_keep, B().segs[1].must_keep];
      await press('KeyZ'); await press('KeyZ');
      return [a, B().segs[1].must_keep, el('#toast').textContent];""")
    assert out == [[False, True], False, "没有可撤销的操作"]


def test_undo_failure_retries_once_then_drops_entry():
    out = go("""sim(); pick(0); pick(1); await applyBatch('add'); await sleep(2);
      window.__respond = () => [500, {error: '炸了'}];
      await press('KeyZ'); await sleep(2);
      return [bposts().length, B().undo.length, el('#toast').textContent, B().segs[0].must_keep, B().segs[1].must_keep];""")
    assert out[0] == 3 and out[1] == 0 and "撤销" in out[2] and out[3] is True and out[4] is True


def test_undo_waits_for_the_batch_still_in_flight():
    out = go("""sim(); const held = hold(p => p === '/api/browse/batch'); pick(0);
      const run = applyBatch('add'); await sleep(3); const z = press('KeyZ'); await sleep(3); const during = held.length;
      held[0](); await run; await sleep(3); held[1] && held[1](); await z; await sleep(3);
      return [during, bposts().map(c => c.body.items[0].must_keep), B().segs[0].must_keep];""")
    assert out == [1, [True, False], False]


def test_undo_of_failed_batch_has_nothing_to_undo():
    out = go("""sim({fail: () => true}); pick(0); await applyBatch('add'); await sleep(2); await press('KeyZ');
      return [bposts().length, el('#toast').textContent];""")
    assert out == [1, "没有可撤销的操作"]


def test_undo_skips_segments_that_already_match():
    out = go("""sim(); pick(0); pick(1); await applyBatch('add'); await sleep(2);
      await toggleList(B().segs[0]); await sleep(2);   // 单段又移出了 S1
      B().undo.pop();                                   // 只留批量这一条
      await press('KeyZ'); await sleep(2); return bposts()[1].body.items.map(i => i.id);""")
    assert out == ["S2"]


def test_undo_stack_is_capped_with_batch_entries():
    out = go("""sim(); for (let k = 0; k < 55; k++) { B().sel.add(0); await applyBatch(k % 2 ? 'remove' : 'add'); await sleep(1); }
      return B().undo.length;""")
    assert out == 50


# ---------------------------------------------------------------- 守卫
def test_batch_select_file_exists_within_size_limit_and_uses_no_inline_handlers():
    src = (STATIC / "batch-select.js").read_text(encoding="utf-8")
    assert 0 < len(src.splitlines()) <= 400
    for name in ("cliplist.js", "step-browse.js", "batch-select.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 400 and "必留" not in text and "onclick" not in text
    assert "const COPY_BATCH" in src


# ---------------------------------------------------------------- 审查修复
def test_row_checkbox_has_its_own_aria_label_not_select_all():
    html = go("return el('#bList').innerHTML;")
    assert 'id="pk0"' in html and 'aria-label="选择 00:00.0"' in html
    assert 'aria-label="全选' not in html


def test_blur_only_after_mouse_click_not_keyboard_space():
    out = go("""const mk = () => node({'data-act': 'pickIdx', 'data-i': '1'});
      const kb = mk(); ACTIONS.pickIdx(kb, {shiftKey: false, detail: 0});
      const ms = mk(); ACTIONS.pickIdx(ms, {shiftKey: false, detail: 1});
      const all = node({'data-act': 'pickAll'}); ACTIONS.pickAll(all, {detail: 0});
      return [kb.blurred || 0, ms.blurred || 0, all.blurred || 0];""")
    assert out == [0, 1, 0]


def test_success_clears_only_rows_of_this_batch_not_ones_ticked_in_flight():
    out = go("""sim(); const held = hold(p => p === '/api/browse/batch'); pick(0); pick(1);
      const run = applyBatch('add'); await sleep(3); pick(2);
      held[0](); await run; await sleep(2); return [sel(), el('#bBatch').innerHTML.includes('已选 1 段'), el('#pk2').checked, el('#pk0').checked];""")
    assert out == [[2], True, True, False]


def test_empty_selection_after_waiting_for_pending_marks_returns_silently():
    out = go("""sim(); const held = hold(p => p.startsWith('/api/browse/must')); const single = toggleList(B().segs[3]); await sleep(2);
      pick(0); let toasts = 0; const orig = window.toast; window.toast = (...a) => { toasts++; return orig(...a); };
      const run = applyBatch('remove'); await sleep(3); act('setFilter', {v: 'pending'});
      held[0](); const r = await run; await single; await sleep(2);
      return [r, bposts().length, toasts, B().batchBusy];""")
    assert out == [False, 0, 0, False]


def test_failed_batch_rolls_back_to_confirmed_state_not_pre_batch_snapshot():
    out = go("""sim({fail: p => p === '/api/browse/batch'}); await toggleList(B().segs[0]); await sleep(2);
      pick(0); await applyBatch('remove'); await sleep(3);
      return [B().segs[0].must_keep, el('#r0').classList.contains('in-list')];""")
    assert out == [True, True]


def test_failed_batch_resyncs_in_case_the_server_wrote_anyway():
    out = go("""sim(); const ok = window.__respond; const saved = JSON.parse(JSON.stringify(B().data)); saved.segments[0].must_keep = true;
      window.__respond = (m, p, b) => p === '/api/browse/batch' ? [500, {error: '炸了'}] : p.startsWith('/api/browse?') ? [200, saved] : ok(m, p, b);
      pick(0); await applyBatch('add'); await sleep(4);
      return [B().segs[0].must_keep, calls.filter(c => c.path.startsWith('/api/browse?')).length];""")
    assert out == [True, 2]


def test_batch_skipped_when_a_queue_epoch_changed_before_its_turn():
    out = go("""sim({fail: p => p.startsWith('/api/browse/must')}); const held = hold(p => p.startsWith('/api/browse/must'));
      const single = toggleList(B().segs[0]); await sleep(2);
      const seg = B().segs[0];
      const batch = sendBatch(B(), [{seg, change: {unusable: true}, item: {unusable: true}}], {}, null); await sleep(2);
      held[0](); await single; const r = await batch; await sleep(3);
      return [r, bposts().length, seg.unusable, seg.must_keep];""")
    assert out == [None, 0, False, False]


def test_double_undo_runs_one_undo_batch_at_a_time():
    out = go("""sim(); pick(0); await applyBatch('add'); await sleep(2); pick(1); await applyBatch('add'); await sleep(2);
      const held = hold(p => p === '/api/browse/batch');
      const z1 = press('KeyZ'); const z2 = press('KeyZ'); await sleep(4); const inflight = held.length;
      held[0](); await sleep(4); held[1] && held[1](); await z1; await z2; await sleep(3);
      return [inflight, bposts().map(c => c.body.items.map(i => i.id)), B().segs.map(s => s.must_keep)];""")
    assert out[0] == 1
    assert out[1][2:] == [["S2"], ["S1"]] and out[2][:2] == [False, False]


def test_double_undo_when_first_fails_does_not_send_second_before_first_settles():
    out = go("""sim(); pick(0); await applyBatch('add'); await sleep(2); pick(1); await applyBatch('add'); await sleep(2);
      const ok = window.__respond; let n = 0;
      window.__respond = (m, p, b) => p === '/api/browse/batch' && ++n <= 2 ? [500, {error: '炸了'}] : ok(m, p, b);
      await press('KeyZ'); await press('KeyZ'); await sleep(3);
      return [bposts().map(c => c.body.items.map(i => i.id)), B().undo.length, B().segs.map(s => s.must_keep)];""")
    assert out[0][2:5] == [["S2"], ["S2"], ["S1"]]   # 第一次撤销试两次都失败、丢弃，之后才轮到更早的那一条
    assert out[1] == 0 and out[2][:2] == [False, True]   # B 的撤销被放弃，S2 仍在列表里


def test_undo_batch_after_a_single_mark_in_flight_on_a_batch_segment():
    out = go("""sim(); pick(0); pick(1); await applyBatch('add'); await sleep(2);
      const held = hold(p => p.startsWith('/api/browse/must')); act('jumpSeg', {i: '0'});
      const s = press('KeyS'); await sleep(2); const z1 = press('KeyZ'); const z2 = press('KeyZ'); await sleep(3);
      const during = posts().length; held[0](); await s; await sleep(4); held[1] && held[1](); await z1; await z2; await sleep(4);
      return [during, posts().map(p => p[0]), B().segs.map(x => x.must_keep).slice(0, 2)];""")
    assert out[0] == 1 and out[1] == ["/api/browse/batch", "/api/browse/must", "/api/browse/must", "/api/browse/batch"]
    assert out[2] == [False, False]


def test_undo_batch_after_a_single_mark_on_it_failed():
    out = go("""sim(); pick(0); pick(1); await applyBatch('add'); await sleep(2);
      const ok = window.__respond; window.__respond = (m, p, b) => p.startsWith('/api/browse/must') ? [500, {error: '炸了'}] : ok(m, p, b);
      act('jumpSeg', {i: '0'}); await press('KeyS'); await sleep(2); window.__respond = ok;
      await press('KeyZ'); await sleep(3);
      return [bposts()[1].body.items, B().segs.map(x => x.must_keep).slice(0, 2), B().undo.length];""")
    assert [i["id"] for i in out[0]] == ["S1", "S2"] and out[1] == [False, False] and out[2] == 0


def test_warning_with_normal_payload_is_shown_merged_and_keeps_removed_shots_for_undo():
    shots = [{"id": "b", "in": 1, "out": 2, "sub": "", "note": ""}]
    out = go(f"""sim({{removed: {json.dumps(shots)}}}); const ok = window.__respond;
      window.__respond = (m, p, b) => {{ const r = ok(m, p, b); if (p === '/api/browse/batch' && !b.restore_shots) r[1].warning = '已保存，但分镜表没能同步'; return r; }};
      pick(0); await applyBatch('unusable'); await sleep(4);
      const toast1 = el('#toast').textContent, segs = [B().segs[0].unusable, B().clip.items.length], sel1 = sel(), removed = B().undo[0].removed;
      await press('KeyZ'); await sleep(3);
      return [toast1, segs, sel1, removed, bposts()[1].body.restore_shots, B().segs[0].unusable];""")
    assert "分镜表没能同步" in out[0] and out[1] == [True, 1] and out[2] == []
    assert out[3] == shots and out[4] == shots and out[5] is False


def test_undo_after_warning_response_without_segments_still_restores_whole_batch():
    warn = {"ok": True, "warning": "已保存，但没能读回最新状态", "segments": None, "clip_list": None, "wizard": None,
            "cleared": {}, "removed_shots": [], "restored": 0, "not_restored": 0}
    out = go("""sim(); const ok = window.__respond; let first = true;
      window.__respond = (m, p, b) => { if (p === '/api/browse/batch' && first) { first = false; ok(m, p, b); return [200, %s]; } return ok(m, p, b); };
      pick(0); pick(1); await applyBatch('add'); await sleep(4); await press('KeyZ'); await sleep(3);
      return [bposts().length, bposts()[1].body.items.map(i => i.id), B().segs.map(s => s.must_keep).slice(0, 2)];""" % json.dumps(warn, ensure_ascii=False))
    assert out == [2, ["S1", "S2"], [False, False]]


def test_hostile_text_and_topic_never_become_elements_in_row_or_bar():
    evil = "<img src=x onerror=alert(1)>"
    segs = [seg(1, 0, 6, 3, evil, evil), seg(2, 10, 16, 2, evil, "乙")]
    out = go("""pick(0); pick(1); return [el('#bList').innerHTML, el('#bBatch').innerHTML, el('#bFilters').innerHTML];""",
             routes_with(segs))
    assert all("<img" not in h for h in out) and "&lt;img" in out[0]
