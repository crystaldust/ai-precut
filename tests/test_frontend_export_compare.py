"""M14c · ⑥ 的对比两版与回到这一版（node vm，KI-94）。"""
import pytest

from fe_export import in_export, js, text_of, ver
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

STAGE = "el('#stage').innerHTML"
THREE = [ver("v3", current=True), ver("v2"), ver("v1", preview=False)]
COMPARE = {
    "a": {"name": "v2", "preview": True, "shots": 16, "duration": 150, "has_snapshot": True},
    "b": {"name": "v3", "preview": True, "shots": 18, "duration": 178, "has_snapshot": True},
    "diff": {"added": [{"index": 4, "shot": {"in": 10, "out": 20, "sub": "新<b>镜"}}, {"index": 5, "shot": {"in": 30, "out": 40, "sub": "又一镜"}}],
             "removed": [{"index": 2, "shot": {"in": 65, "out": 70, "sub": "旧"}}],
             "sub_changed": [{"index": 0, "before": "之前<i>", "after": "之后"}, {"index": 1, "before": "a", "after": "b"},
                             {"index": 3, "before": "c", "after": "d"}],
             "retimed": [{"index": 6, "before": [0, 5], "after": [0, 6]}], "reordered": False},
    "count": 7, "lines": [], "more": 0, "note": None,
}
NO_SNAP = {**COMPARE, "diff": None, "count": None, "note": "有一版没有留存分镜表，只能并排播放预览片，没法逐镜比较",
           "b": {**COMPARE["b"], "has_snapshot": False}}
COMPARE_ROUTE = {"GET /api/versions/compare": COMPARE}
CMP_CALLS = "calls.filter(c => c.path.startsWith('/api/versions/compare')).map(c => c.path)"


def test_compare_button_needs_two_versions():
    one = in_export(f"return {STAGE};", state={"versions": [ver("v1")]})
    two = in_export(f"return {STAGE};", state={"versions": THREE})
    assert 'data-act="toggleCompare"' not in one and 'data-act="toggleCompare"' in two and "对比两版" in two


def test_toggle_shows_checkboxes_and_picking_two_loads_the_compare_with_earlier_first():
    out = in_export(f"""const before = {STAGE};
      await act('toggleCompare'); const boxes = {STAGE};
      await act('pickCompare', {{i: '0'}}); const afterOne = {CMP_CALLS};   // v3
      await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);                    // v2
      return [before, boxes, afterOne, {CMP_CALLS}];""", COMPARE_ROUTE, state={"versions": THREE})
    before, boxes, after_one, calls = out
    assert 'data-change="pickCompare"' not in before and boxes.count('data-change="pickCompare"') == 3
    assert "选两个版本" in boxes and "关闭对比" in boxes
    assert after_one == [] and calls == ["/api/versions/compare?project=%E6%96%B0%E9%A1%B9%E7%9B%AE&a=v2&b=v3"]


def test_third_pick_replaces_the_earliest_selected():
    out = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);   // v3, v2
      await act('pickCompare', {{i: '2'}});                                                          // v1 顶掉 v3
      return {CMP_CALLS}.map(p => p.split('&').slice(1).join('&'));""", COMPARE_ROUTE, state={"versions": THREE})
    assert out == ["a=v2&b=v3", "a=v1&b=v2"]


def test_unpicking_back_to_one_clears_the_panel():
    out = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      const open = {STAGE}.includes('class="ver cmp"') && {STAGE}.includes('<video id="xvA"');
      await act('pickCompare', {{i: '1'}});
      return [open, {STAGE}.includes('<video id="xvA"')];""", COMPARE_ROUTE, state={"versions": THREE})
    assert out == [True, False]


def test_panel_has_two_videos_summary_and_escaped_diff_list():
    html = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      return {STAGE};""", COMPARE_ROUTE, state={"versions": THREE})
    assert '<video id="xvA" src="/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/preview/v2"' in html
    assert '<video id="xvB" src="/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/preview/v3"' in html
    assert "新增 2 · 删除 1 · 改字幕 3 · 改入出点 1" in html
    assert "第 1 镜字幕：「之前&lt;i&gt;」→「之后」" in html and "新增第 5 镜「新&lt;b&gt;镜」" in html
    assert "删除了 01:05 那一镜" in html and "<i>" not in html and "新<b>镜" not in html
    assert "同时播放" in html


def test_missing_snapshot_shows_the_server_note_and_missing_preview_says_so():
    html = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      return {STAGE};""", {"GET /api/versions/compare": {**NO_SNAP, "b": {**NO_SNAP["b"], "preview": False}}},
                     state={"versions": THREE})
    assert "有一版没有留存分镜表，只能并排播放预览片，没法逐镜比较" in html
    assert "这一版没有预览片" in html and "新增" not in html.split("同时播放")[1]


def test_play_both_rewinds_and_plays_both_videos():
    out = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      const log = [];
      for(const id of ['#xvA', '#xvB']){{ const v = el(id); v.readyState = 4; v.currentTime = 99; v.play = () => {{ log.push(id + ':' + v.currentTime); return Promise.resolve(); }}; }}
      await act('playBoth');
      return log;""", COMPARE_ROUTE, state={"versions": THREE})
    assert out == ["#xvA:0", "#xvB:0"]


def test_close_compare_pauses_both_videos_and_removes_the_panel():
    out = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      const paused = [];
      for(const id of ['#xvA', '#xvB']) el(id).pause = () => paused.push(id);
      await act('closeCompare');
      return [paused, {STAGE}.includes('<video id="xvA"'), {STAGE}.includes('pickCompare')];""",
                    COMPARE_ROUTE, state={"versions": THREE})
    assert out == [["#xvA", "#xvB"], False, False]


def test_leaving_export_pauses_the_compare_videos():
    out = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      const paused = [];
      for(const id of ['#xvA', '#xvB']) el(id).pause = () => paused.push(id);
      await go('browse');
      return [paused, exportUi.compare, exportUi.picks];""", COMPARE_ROUTE, state={"versions": THREE})
    assert out == [["#xvA", "#xvB"], False, []]


def test_out_of_order_compare_responses_are_dropped():
    out = in_export(f"""await act('toggleCompare');
      const waiters = [];
      __respond = (m, p) => p.startsWith('/api/versions/compare') ? [200, {js(COMPARE)}] : respond(m, p);
      const slow = loadCompare('v1', 'v2');       // 先发的
      exportUi.seq += 1;                          // 之后又选了别的
      await slow;
      return {STAGE}.includes('<video id="xvA"');""", state={"versions": THREE})
    assert out is False


def test_compare_failure_is_told_and_leaves_the_page_usable():
    out = in_export(f"""await act('toggleCompare');
      await act('pickCompare', {{i: '0'}}); await act('pickCompare', {{i: '1'}}); await until(() => exportUi.data || exportUi.error);
      return [{STAGE}.includes('没能比较这两版：找不到版本 v2'), {STAGE}.includes('<video id="xvA"')];""",
                    {"GET /api/versions/compare": [404, {"error": "找不到版本 v2"}]}, state={"versions": THREE})
    assert out == [True, False]  # 面板里说明原因（带「重试」，见下面的用例）


# ---------------------------------------------------------------- 回到这一版
RESTORE_OK = {"POST /api/versions/restore": {"ok": True, "count": 16, "dropped": [], "backup": "x", "wizard": None}}


def test_restore_button_is_disabled_with_the_reason_without_a_snapshot():
    html = in_export(f"return {STAGE};", state={"versions": [ver("v2"), ver("v1", has_snapshot=False, legacy=True, exports=None)]})
    assert html.count('data-act="askRestore"') == 1
    assert 'disabled title="这一版是改版前生成的，没有留存分镜表，不能回到这一版"' in html


def test_restore_asks_first_then_posts_toasts_and_goes_to_result():
    out = in_export("""await act('askRestore', {i: '1'});
      const ask = [el('#modalTitle').textContent, el('#modalBody').innerHTML, calls.filter(c => c.path === '/api/versions/restore').length];
      await act('restoreVersionGo', {v: 'v2'}); await until(() => !exportUi.restoring.size);
      return [ask, calls.filter(c => c.path === '/api/versions/restore').map(c => c.body), el('#toast').textContent,
              state.view, el('#mask').classList.contains('on')];""", RESTORE_OK, state={"versions": THREE})
    ask, posts, toast, view, modal = out
    assert ask[0] == "回到 v2" and "用 v2 的分镜表替换当前分镜表？当前的分镜表会自动备份，不会删除任何版本。" in ask[1] and ask[2] == 0
    assert posts == [{"project": "新项目", "version": "v2"}]
    assert toast == "已回到 v2 的分镜表（16 镜）" and view == "result" and modal is False


def test_restore_mentions_dropped_shots():
    out = in_export("""await act('restoreVersionGo', {v: 'v2'}); await until(() => !exportUi.restoring.size); return el('#toast').textContent;""",
                    {"POST /api/versions/restore": {"ok": True, "count": 14, "dropped": ["a", "b"], "wizard": None}},
                    state={"versions": THREE})
    assert out == "已回到 v2 的分镜表（14 镜）；已去掉 2 个含不可用片段的镜头"


def test_restore_flushes_the_pending_save_before_posting():
    out = in_export("""state.shots[0].sub = '还没存'; scheduleSave();
      await act('restoreVersionGo', {v: 'v2'}); await until(() => !exportUi.restoring.size);
      return calls.filter(c => c.method === 'POST').map(c => c.path.split('?')[0]);""",
                    {**RESTORE_OK, "POST /api/shots": {"ok": True}}, state={"versions": THREE})
    assert out.index("/api/shots") < out.index("/api/versions/restore")


def test_restore_conflict_shows_the_reason_and_stays_on_export():
    out = in_export("""await act('restoreVersionGo', {v: 'v2'}); await until(() => !exportUi.restoring.size);
      return [el('#toast').textContent, state.view];""",
                    {"POST /api/versions/restore": [409, {"error": "这个项目正在重新选段，完成后再试"}]}, state={"versions": THREE})
    assert out == ["这个项目正在重新选段，完成后再试", "export"]


def test_cancel_in_the_restore_dialog_posts_nothing():
    out = in_export("""await act('askRestore', {i: '1'}); await act('closeModal');
      return [calls.filter(c => c.path === '/api/versions/restore').length, el('#mask').classList.contains('on')];""",
                    RESTORE_OK, state={"versions": THREE})
    assert out == [0, False]


# ---------------------------------------------------------------- 评审修复
OPEN_PANEL = """await act('toggleCompare');
      await act('pickCompare', {i: '0'}); await act('pickCompare', {i: '1'}); await until(() => exportUi.data || exportUi.error);"""


def test_restore_response_after_switching_project_only_toasts_with_the_project_name():
    out = in_export("""
      const wizardBefore = state.data.wizard;
      let release; postJson = () => new Promise(r => { release = r; });
      const p = restoreVersion('v2');
      await until(() => release);
      const lockedA = exportUi.restoring.has('新项目');
      await selectProject('B');
      const stateCalls = calls.filter(c => c.path.startsWith('/api/state')).length;
      release({ok: true, count: 16, dropped: [], wizard: {steps: [], next: 'result'}});
      await p;
      return [lockedA, exportUi.restoring.has('新项目'), exportUi.restoring.has('B'), state.project, state.view,
              calls.filter(c => c.path.startsWith('/api/state')).length - stateCalls, el('#toast').textContent,
              state.data.wizard === wizardBefore || state.data.wizard.steps.length > 0];""", state={"versions": THREE})
    locked_a, a_after, b_locked, project, view, extra_state_calls, toast, wizard_intact = out
    assert locked_a is True and a_after is False and b_locked is False
    assert project == "B" and view != "result" and extra_state_calls == 0
    assert "新项目" in toast and "已回到 v2 的分镜表（16 镜）" in toast and wizard_intact


def test_restore_lock_of_one_project_is_not_released_by_another_projects_finish():
    out = in_export("""
      let releaseA; postJson = () => new Promise(r => { releaseA = r; });
      const pa = restoreVersion('v2'); await until(() => releaseA);
      await selectProject('B');
      let releaseB; postJson = () => new Promise(r => { releaseB = r; });
      const pb = restoreVersion('v2'); await until(() => releaseB);
      releaseA({ok: true, count: 1, dropped: [], wizard: null}); await pa;
      const bStillLocked = exportUi.restoring.has('B');
      releaseB({ok: true, count: 1, dropped: [], wizard: null}); await pb;
      return [bStillLocked, exportUi.restoring.size];""", state={"versions": THREE})
    assert out == [True, 0]


def test_compare_failure_shows_an_error_state_with_retry_not_loading_forever():
    out = in_export("""await act('toggleCompare');
      __respond = (m, p) => p.startsWith('/api/versions/compare') ? [500, {error: '服务出错了'}] : respond(m, p);
      await act('pickCompare', {i: '0'}); await act('pickCompare', {i: '1'});
      const failed = el('#stage').innerHTML;
      __respond = (m, p) => p.startsWith('/api/versions/compare') ? [200, %s] : respond(m, p);
      await act('retryCompare');
      return [failed, el('#stage').innerHTML];""" % js(COMPARE), state={"versions": THREE})
    failed, retried = out
    assert "服务出错了" in failed and "重试" in failed and "正在比较" not in failed and 'data-act="retryCompare"' in failed
    assert '<video id="xvA"' in retried and "正在比较" not in retried


def test_play_both_waits_for_metadata_then_starts_both_at_zero():
    out = in_export(OPEN_PANEL + """
      const log = [], handlers = {};
      for(const id of ['#xvA', '#xvB']){
        const v = el(id); v.readyState = 0; v.currentTime = 99;
        v.addEventListener = (t, fn) => { (handlers[id + t] = handlers[id + t] || []).push(fn); };
        v.play = () => { log.push('play ' + id + ' ' + v.currentTime); return Promise.resolve(); };
      }
      const p = playBoth(); await tick();
      const early = [...log, el('#xvA').currentTime];
      for(const id of ['#xvA', '#xvB']){ el(id).readyState = 1; handlers[id + 'loadedmetadata'].forEach(f => f()); }
      await p;
      return [early, log];""", COMPARE_ROUTE, state={"versions": THREE})
    assert out == [[99], ["play #xvA 0", "play #xvB 0"]]


def test_play_and_pause_are_mirrored_between_the_two_videos_but_not_seek():
    out = in_export(OPEN_PANEL + """
      const a = el('#xvA'), b = el('#xvB'), log = [];
      a.paused = false; b.paused = true;
      b.play = () => { log.push('b.play'); return Promise.resolve(); };
      a.pause = () => log.push('a.pause');
      b.pause = () => log.push('b.pause');
      a.listeners.play.forEach(f => f());            // A 开始播放 → B 跟着播
      b.paused = false; a.paused = false;
      b.listeners.pause.forEach(f => f());           // B 暂停 → A 跟着停
      a.listeners.seeked && a.listeners.seeked.forEach(f => f());
      return [log, Object.keys(a.listeners).sort()];""", COMPARE_ROUTE, state={"versions": THREE})
    assert out[0] == ["b.play", "a.pause"] and "seeked" not in out[1] and "seeking" not in out[1]


def test_mirroring_listeners_are_removed_when_leaving_export():
    out = in_export(OPEN_PANEL + """
      const before = (el('#xvA').listeners.play || []).length;
      await go('browse');
      return [before, (el('#xvA').listeners.play || []).length, (el('#xvA').listeners.pause || []).length];""",
                    COMPARE_ROUTE, state={"versions": THREE})
    assert out == [1, 0, 0]


def test_close_compare_unloads_the_videos():
    out = in_export(OPEN_PANEL + """
      el('#xvA').attrs.src = '/media/x'; el('#xvB').attrs.src = '/media/y';
      const l0 = [el('#xvA').loaded || 0, el('#xvB').loaded || 0];
      await act('closeCompare');
      return [el('#xvA').attrs.src === undefined, el('#xvB').attrs.src === undefined, el('#xvA').loaded - l0[0], el('#xvB').loaded - l0[1]];""",
                    COMPARE_ROUTE, state={"versions": THREE})
    assert out == [True, True, 1, 1]


def test_switching_project_pauses_and_unloads_the_compare_videos():
    out = in_export(OPEN_PANEL + """
      const paused = [];
      for(const id of ['#xvA', '#xvB']){ el(id).attrs.src = '/m'; el(id).pause = () => paused.push(id); }
      await selectProject('B');
      return [paused, el('#xvA').attrs.src === undefined, exportUi.compare, exportUi.picks, exportUi.data];""",
                    COMPARE_ROUTE, state={"versions": THREE})
    assert out == [["#xvA", "#xvB"], True, False, [], None]


def test_refresh_that_moves_the_view_away_from_export_clears_the_compare():
    from fe_harness import wizard
    locked = {**wizard(analyze="done", browse="done", criteria="done", result="available",
                       export=("locked", "先在「⑤ 看结果」生成当前分镜表的预览片", None)), "next": "result"}
    out = in_export(OPEN_PANEL + """
      const paused = [];
      for(const id of ['#xvA', '#xvB']) el(id).pause = () => paused.push(id);
      __respond = (m, p) => p.startsWith('/api/state') ? [200, %s] : respond(m, p);
      await refreshOrWarn();
      return [state.view, paused, exportUi.compare, exportUi.data];""" % js({"project": {"name": "新项目", "title": "新项目"},
                                                                         "wizard": locked, "shots": [], "warnings": [], "versions": THREE,
                                                                         "segments": [], "job": None, "busy": None}),
                    COMPARE_ROUTE, state={"versions": THREE})
    assert out == ["result", ["#xvA", "#xvB"], False, None]


def test_long_subtitles_in_the_diff_list_are_truncated():
    long_text = "很长的字幕" * 20
    data = {**COMPARE, "diff": {**COMPARE["diff"], "added": [], "removed": [], "retimed": [],
                                "sub_changed": [{"index": 0, "before": long_text, "after": long_text + "改"}]}}
    html = in_export(OPEN_PANEL + "return el('#stage').innerHTML;", {"GET /api/versions/compare": data},
                     state={"versions": THREE})
    assert long_text not in html and "…" in html


def test_after_restore_step_five_sees_the_preview_as_outdated():
    from fe_result import PREVIEW_FRESH, RESULT
    outdated = {"status": "outdated", "reasons": ["table"], "at": "2026-10-20T14:02:00", "duration": 178, "shots": 2, "url": PREVIEW_FRESH["url"]}
    out = in_export("""await act('restoreVersionGo', {v: 'v2'});
      await until(() => state.view === 'result' && state.result && state.result.data);
      return [state.view, previewStatus(), state.data.preview.status];""",
                    {**RESTORE_OK, "GET /api/result": {**RESULT, "preview": outdated}},
                    state={"versions": THREE, "preview": {"status": "outdated", "at": "2026-10-20T14:02:00"}})
    assert out == ["result", "outdated", "outdated"]
