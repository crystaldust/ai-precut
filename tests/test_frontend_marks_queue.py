"""M13c 审查修复（node vm）：标记请求队列失败后的对账、撤销栈只指向服务端确认过的状态、撤销 X 还原镜头、
面板合并在途的乐观改动、响应拼装失败的处理、标记后各处同步、播放器精确停止。"""
import pytest

from fe_browse import in_browse
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


# ---------------------------------------------------------------- HIGH-1：失败对账
def test_first_fails_while_second_queued_second_is_never_sent_and_ui_matches_server():
    out = in_browse("""sim({fail: () => true});
      const first = toggleList(B().segs[0]); const second = toggleList(B().segs[0]);   // 第二次按键时乐观状态是「已在列表」
      const r = [await first, await second];
      return [r, posts().length, B().segs[0].must_keep, el('#r0').classList.contains('in-list'), B().undo.length,
              el('#t0').textContent];""")
    assert out == [[False, False], 1, False, False, 0, "＋ 剪辑列表"]


def test_double_press_both_would_fail_shows_one_toast_and_one_request():
    out = in_browse("""sim({fail: () => true}); let toasts = 0; const orig = window.toast; window.toast = (...a) => { toasts++; return orig(...a); };
      await Promise.all([toggleList(B().segs[0]), toggleList(B().segs[0])]); await tick();
      return [posts().length, toasts, B().segs[0].must_keep];""")
    assert out == [1, 1, False]


def test_second_fails_after_first_succeeded_reconciles_to_first_result():
    out = in_browse("""sim({fail: (path, body) => body.must === false});
      await Promise.all([toggleList(B().segs[0]), toggleList(B().segs[0])]);
      return [B().segs[0].must_keep, el('#r0').classList.contains('in-list'), B().undo.length, B().undo[0].before.must_keep];""")
    assert out == [True, True, 1, False]


def test_failure_of_one_segment_does_not_touch_another_segments_queue():
    out = in_browse("""sim({fail: (path, body) => body.id === 'S1'});
      await Promise.all([toggleList(B().segs[0]), toggleList(B().segs[1])]);
      return [B().segs[0].must_keep, B().segs[1].must_keep, B().undo.length];""")
    assert out == [False, True, 1]


def test_new_press_after_a_failure_is_sent_normally():
    out = in_browse("""let n = 0; sim({fail: () => ++n === 1});
      await toggleList(B().segs[0]); const ok = await toggleList(B().segs[0]);
      return [ok, B().segs[0].must_keep, posts().length];""")
    assert out == [True, True, 2]


def test_undo_waits_for_pending_request_then_undoes_it():
    out = in_browse("""sim(); const held = hold(p => p.startsWith('/api/browse/must'));
      act('jumpSeg', {i: '0'}); const s = press('KeyS'); await tick();
      const z = press('KeyZ'); await tick(); const before = held.length;
      held[0](); await s; await z; await tick(); await tick(); held[1] && held[1](); await tick(); await tick();
      return [before, posts().map(p => p[1].must), B().segs[0].must_keep];""")
    assert out[1] == [True, False] and out[2] is False


def test_undo_entries_of_failed_requests_are_dropped():
    out = in_browse("""sim({fail: () => true}); act('jumpSeg', {i: '0'}); await press('KeyS'); await press('KeyZ');
      return [posts().length, el('#toast').textContent];""")
    assert out == [1, "没有可撤销的操作"]


# ---------------------------------------------------------------- MEDIUM-4：撤销失败
def test_undo_failure_retries_once_then_drops_entry_with_toast():
    out = in_browse("""sim(); act('jumpSeg', {i: '0'}); await press('KeyS');
      window.__respond = () => [500, {error: '炸了'}];
      await press('KeyZ'); return [posts().length, B().undo.length, el('#toast').textContent, B().segs[0].must_keep];""")
    assert out[0] == 3 and out[1] == 0 and "撤销" in out[2] and out[3] is True


def test_undo_skips_entries_whose_segment_is_gone():
    out = in_browse("""sim(); await toggleList(B().segs[0]); await toggleList(B().segs[1]);
      B().segs = B().segs.filter(s => s.id !== 'S2'); await press('KeyZ');
      return [posts().map(p => p[1].id), B().undo.length];""")
    assert out == [["S1", "S2", "S1"], 0]


# ---------------------------------------------------------------- MEDIUM-3：撤销 X 还原镜头
SHOTS = [{"id": "b", "in": 11, "out": 14, "sub": "", "note": ""}, {"id": "c", "in": 12, "out": 13, "sub": "", "note": ""}]


def test_undo_of_x_sends_removed_shots_back_and_reports_restored():
    out = in_browse(f"""sim({{removed: {SHOTS!r}}}); act('jumpSeg', {{i: '1'}}); await press('KeyX');
      const x = el('#toast').textContent; const sim_ = window.__respond;
      window.__respond = (m, p, b) => b && b.restore_shots ? [200, {{...sim_(m, p, b)[1], restored: 2, not_restored: 0}}] : sim_(m, p, b);
      await press('KeyZ'); const z = posts()[1][1];
      return [x, z.unusable, z.restore_shots, el('#toast').textContent];""")
    assert out[0] == "已从分镜表移除 2 镜" and out[1] is False and out[2] == SHOTS
    assert "已恢复 2 镜" in out[3]


def test_undo_of_x_reports_shots_that_could_not_be_restored():
    out = in_browse(f"""sim({{removed: {SHOTS!r}}}); act('jumpSeg', {{i: '1'}}); await press('KeyX');
      const s0 = window.__respond;
      window.__respond = (m, p, b) => m === 'POST' ? [200, {{...s0(m, p, b)[1], restored: 1, not_restored: 1}}] : s0(m, p, b);
      await press('KeyZ'); return el('#toast').textContent;""")
    assert "已恢复 1 镜" in out and "1 镜没能恢复" in out


def test_x_that_removed_nothing_sends_no_restore_payload():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); await press('KeyX'); await press('KeyZ'); return posts()[1][1];""")
    assert "restore_shots" not in out


def test_x_with_removed_shots_refetches_browse_so_used_tags_update():
    out = in_browse(f"""sim({{removed: {SHOTS!r}}}); const before = calls.filter(c => c.path.startsWith('/api/browse?')).length;
      act('jumpSeg', {{i: '1'}}); await press('KeyX'); await tick();
      return calls.filter(c => c.path.startsWith('/api/browse?')).length - before;""")
    assert out == 1


# ---------------------------------------------------------------- HIGH-2 前端：响应拼装失败
def test_warning_response_is_treated_as_saved_and_refetched():
    warn = {"ok": True, "cleared": None, "segment": None, "clip_list": None, "wizard": None, "warning": "已保存，但没能读回最新状态"}
    out = in_browse("""const saved = JSON.parse(JSON.stringify(B().data)); saved.segments[0].must_keep = true;   // 服务端确实已保存
      window.__respond = (m, p) => m === 'POST' ? [200, %s] : p.startsWith('/api/browse?') ? [200, saved] : respond(m, p);
      act('jumpSeg', {i: '0'}); await press('KeyS'); await tick(); await tick();
      return [B().segs[0].must_keep, el('#toast').textContent, B().undo.length,
              calls.filter(c => c.path.startsWith('/api/browse?')).length, calls.filter(c => c.path.startsWith('/api/state')).length];""" % __import__("json").dumps(warn, ensure_ascii=False))
    assert out[0] is True and "已保存" in out[1] and out[2] == 1 and out[3] == 2 and out[4] == 2


# ---------------------------------------------------------------- MEDIUM-6：面板合并在途改动
def test_panel_keeps_pending_change_of_b_when_a_response_arrives():
    out = in_browse("""sim(); const held = hold(p => p.startsWith('/api/browse/must'));
      const a = toggleList(B().segs[0]); const b = toggleList(B().segs[1]); await tick();
      held[0](); await a; await tick();        // A 的响应回来：服务端的 clip_list 里没有 B
      const html = el('#bPanel').innerHTML; held[1] && held[1](); await b; await tick();
      return [html.includes('3 段'), el('#bPanel').innerHTML.includes('3 段')];""")
    assert out == [True, True]


def test_local_clip_orders_server_items_first_then_new_ones():
    out = in_browse("""B().segs[0].must_keep = true; return localClip().items.map(i => i.id);""")
    assert out == ["S4", "S1"]


# ---------------------------------------------------------------- MEDIUM-7：队列在模块里，不挂在 seg 上
def test_queues_live_at_module_level_and_are_dropped_on_project_switch():
    out = in_browse("""sim(); await toggleList(B().segs[0]);
      const onSeg = Object.keys(B().segs[0]).filter(k => k.startsWith('_') && k !== '_i');
      const had = markQueues.size; await selectProject('新项目'); return [onSeg, had, markQueues.size];""")
    assert out == [[], 1, 0]


def test_ordering_survives_reentering_step_three():
    out = in_browse("""sim(); const held = hold(p => p.startsWith('/api/browse/must'));
      const a = toggleList(B().segs[0]); await tick();
      await go('browse'); for (let i = 0; i < 6; i++) await tick();   // 重新进入 ③：旧请求还没回来
      toggleList(B().segs[0]); await tick(); const sentBeforeRelease = held.length;
      held[0](); await a; await tick(); await tick();
      return [sentBeforeRelease, posts().map(p => p[1].must)];""")
    assert out[0] == 1 and out[1][0] is True


# ---------------------------------------------------------------- MEDIUM-5：标记后各处同步
def test_mark_repaints_density_cell_group_counts_and_used_filter_count():
    out = in_browse("""sim(); act('setView', {v: 'topic'}); act('jumpSeg', {i: '1'}); await press('KeyA');
      return [el('#d1').className, el('#g0').textContent, el('#bFilters').innerHTML.includes('未用 4')];""")
    assert "lv3" in out[0] and "可用 2 · 待定 0" in out[1] and out[2] is True


def test_density_cell_marks_unusable():
    out = in_browse("""sim(); act('jumpSeg', {i: '1'}); await press('KeyX'); return el('#d1').className;""")
    assert "unusable" in out


def test_note_when_current_row_no_longer_matches_filter():
    out = in_browse("""sim(); act('setFilter', {v: 'pending'}); act('jumpSeg', {i: '1'});
      const before = el('#bNote').textContent; await press('KeyA'); const after = el('#bNote').textContent;
      act('setFilter', {v: 'all'}); return [before, after, el('#bNote').textContent];""")
    assert out[0] == "" and "待定" in out[1] and out[2] == ""


# ---------------------------------------------------------------- MEDIUM-8：播放器
PLAYER = """const pv = el('#bPv'); const ev = n => (pv.listeners[n] || []).forEach(f => f());
  let paused = 0; pv.pause = () => { paused++; pv.paused = true; ev('pause'); };
  const tickAt = t => { pv.currentTime = t; intervals.filter(i => !i.cleared).forEach(i => i.fn()); };
  const live = () => intervals.filter(i => !i.cleared).length;"""


def test_player_stops_when_playback_crosses_stop_point_using_a_short_interval():
    out = in_browse(PLAYER + """act('jumpSeg', {i: '1'}); pv.paused = false; ev('play'); const running = live();
      tickAt(9.8); tickAt(16.2); const before = paused; tickAt(16.35); return [running, before, paused, live(), B().stopAt];""")
    assert out == [1, 0, 1, 0, None]


def test_manual_seek_beyond_stop_point_does_not_pause():
    out = in_browse(PLAYER + """act('jumpSeg', {i: '1'}); pv.paused = false; ev('play'); tickAt(10);
      pv.currentTime = 40; ev('seeking'); tickAt(40); tickAt(41); return [paused, live()];""")
    assert out == [0, 1]


def test_interval_is_cleared_on_pause_and_on_project_reset():
    out = in_browse(PLAYER + """act('jumpSeg', {i: '0'}); ev('play'); const a = live(); pv.paused = true; ev('pause'); const b = live();
      ev('play'); resetBrowse(); return [a, b, live()];""")
    assert out == [1, 0, 0]


def test_key_point_jump_does_not_change_the_segment_cue_used_by_space():
    out = in_browse(PLAYER + """act('jumpSeg', {i: '1'}); const cue = B().cueEnd; act('jumpAt', {t: '12'}); return [B().cueEnd === cue, B().stopAt];""")
    assert out[0] is True and out[1] == pytest.approx(16)


def test_reset_pauses_and_unloads_the_player():
    out = in_browse(PLAYER + """pv.paused = false; let loaded = 0, removed = []; pv.load = () => loaded++;
      pv.removeAttribute = k => removed.push(k); resetBrowse(); return [paused, removed, loaded];""")
    assert out == [1, ["src"], 1]


def test_switching_to_project_without_analysis_unloads_the_player():
    out = in_browse(PLAYER + """pv.paused = false; let removed = 0; pv.removeAttribute = () => removed++;
      await selectProject('新项目'); return [paused, removed];""",
                    {"GET /api/browse": [404, {"error": "还没有分析结果"}]})
    assert out[0] >= 1 and out[1] >= 1
