"""M14b 评审修复（node vm）：重新选段询问只信刚读的状态、⑥ 闸门、保存失败不被覆盖、过期回包、加回 / 询问的收尾。"""
import pytest

from fe_criteria import CONFIRM, in_criteria
from fe_harness import NODE
from fe_result import MANUAL_OFF, MANUAL_ON, PREVIEW_FRESH, RESULT, in_result, in_result_split, js

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

HINT = "先在「⑤ 看结果」生成当前分镜表的预览片"
OVER = {**RESULT["topbar"], "over_target": True, "must_total": 220, "suggested_target": 220}
NO_CONFIRM_PENDING = {"GET /api/confirm": {**CONFIRM, "pending": []}}


# ---------------------------------------------------------------- HIGH-1：询问只信刚读的 /api/state
@pytest.mark.parametrize("entry", [
    "act('reselect')",
    "act('editTarget'), el('#tgtMin').value = '4', el('#tgtSec').value = '0', act('applyTarget')",
    "act('applySuggested')"])
def test_prompt_appears_when_fresh_state_says_edited_even_if_result_payload_is_stale(entry):
    out = in_result_split(f"""{entry}; await tick(); await tick(); await tick();
      return [el('#modalTitle').textContent, jobs().length];""", state_manual=MANUAL_ON, result_manual=MANUAL_OFF,
                          result={"topbar": OVER})
    assert out == ["你手动改过分镜表（3 处）", 0]


def test_no_prompt_when_fresh_state_says_not_edited_even_if_result_payload_still_says_edited():
    out = in_result_split("""await act('reselect'); await tick();
      return [jobs(), el('#mask').classList.contains('on')];""", state_manual=MANUAL_OFF, result_manual=MANUAL_ON)
    assert out == [[{"project": "新项目", "task": "select", "manual": "replace"}], False]


def test_edit_in_step_five_then_immediate_reselect_prompts_with_the_state_read_after_the_save():
    out = in_result("""window.__edited = false;
      window.__respond = (m, p, b) => {
        if (m === 'POST' && p.startsWith('/api/shots')) window.__edited = true;
        if (m === 'GET' && p.startsWith('/api/state') && window.__edited) return [200, {...state.data, manual: %s}];
        return respond(m, p, b); };
      state.shots[0].sub = '刚改的'; scheduleSave();
      act('reselect'); await tick(); await tick(); await tick();
      return el('#modalTitle').textContent;""" % js(MANUAL_ON))
    assert out == "你手动改过分镜表（3 处）"


def test_gate_in_step_four_prompts_from_the_state_it_just_reread():
    out = in_criteria("""window.__respond = (m, p, b) => {
        if (m === 'POST' && p === '/api/confirm/answers') return [200, {ok: true, job_id: null, wizard: null}];
        if (m === 'GET' && p.startsWith('/api/state')) return [200, {...state.data, manual: %s}];
        return respond(m, p, b); };
      const run = act('gate'); await tick(); await tick(); await tick();
      return el('#modalTitle').textContent;""" % js(MANUAL_ON), NO_CONFIRM_PENDING)
    assert out == "你手动改过分镜表（3 处）"


# ---------------------------------------------------------------- HIGH-2：⑥ 闸门
GO_EXPORT = "await act('go', {step: 'export'}); await tick(); return [state.view, el('#toast').textContent];"


@pytest.mark.parametrize("preview", [{}, {"preview": {**PREVIEW_FRESH, "status": "outdated", "reasons": ["table"]}}])
def test_step_bar_cannot_skip_the_preview_when_there_are_no_versions(preview):
    assert in_result(GO_EXPORT, result=preview) == ["result", HINT]


def test_click_and_keyboard_activation_on_the_step_bar_button_take_the_same_blocked_path():
    out = in_result("""const b = node({'data-act': 'go', 'data-step': 'export'});
      click(b); await tick();   // 键盘 Enter / 空格激活 <button> 也是 click 事件
      return [state.view, el('#toast').textContent];""")
    assert out == ["result", HINT]


def test_local_edit_after_a_fresh_preview_closes_the_export_door_at_once():
    out = in_result("await act('del', {i: '1'}); await tick(); await act('go', {step: 'export'}); return state.view;",
                    result={"preview": PREVIEW_FRESH})
    assert out == "result"


def test_fresh_preview_or_history_opens_export():
    assert in_result(GO_EXPORT, result={"preview": PREVIEW_FRESH})[0] == "export"
    versions = [{"name": "v1", "shots": 1, "duration": 3, "mtime": "x", "draft": "a", "preview": False}]
    assert in_result(GO_EXPORT, state={"versions": versions})[0] == "export"


def test_export_is_blocked_from_other_steps_too_when_there_are_no_versions_and_no_fresh_preview():
    out = in_result("await go('browse'); await go('export'); return [state.view, el('#toast').textContent];")
    assert out == ["browse", HINT]


# ---------------------------------------------------------------- MEDIUM-1：保存失败的改动永远不被覆盖
def test_failed_save_keeps_local_edits_through_a_refresh():
    out = in_result("""state.shots[0].sub = '没存上'; await saveShots(true);
      await refreshOrWarn(); return [state.shots[0].sub, unsavedFor];""",
                    routes={"POST /api/shots": [500, {"error": "写不进去"}]})
    assert out == ["没存上", "新项目"]


def test_successful_save_clears_the_unsaved_flag_and_the_bar():
    out = in_result("""state.shots[0].sub = 'a'; window.__ok = false;
      const base = window.__respond;
      window.__respond = (m, p, b) => (m === 'POST' && p.startsWith('/api/shots')) ? (window.__ok ? [200, {ok: true}] : [500, {error: 'x'}]) : respond(m, p, b);
      await saveShots(true); const failed = unsavedFor; window.__ok = true; await saveShots(true);
      return [failed, unsavedFor, el('#savebar').hidden];""")
    assert out == ["新项目", None, True]


def test_retries_exhausted_show_a_persistent_warning_with_a_manual_retry():
    out = in_result("""await act('del', {i: '1'}); await tick();
      for (let i = 0; i < 8; i++) { await runTimers(); await tick(); }
      const bar = [el('#savebar').hidden, el('#savebar').innerHTML];
      window.__respond = (m, p, b) => (m === 'POST' && p.startsWith('/api/shots')) ? [200, {ok: true}] : respond(m, p, b);
      await act('retrySave'); await tick();
      return [bar, el('#savebar').hidden, unsavedFor, shotPosts().length];""",
                    routes={"POST /api/shots": [409, {"error": "正在重新选段，完成后再改分镜表"}]})
    bar, hidden_after, flag, posts = out
    assert bar[0] is False and "重试保存" in bar[1] and 'data-act="retrySave"' in bar[1]
    assert hidden_after is True and flag is None and posts >= 7


def test_failed_edit_is_also_protected_by_adopt_shots():
    out = in_result("""state.shots[0].sub = '没存上'; unsavedFor = state.project;
      adoptShots([{id: 'x', in: 0, out: 1, sub: '服务端'}]); return state.shots[0].sub;""")
    assert out == "没存上"


# ---------------------------------------------------------------- MEDIUM-2：touched 只在期间没有新编辑时清
def test_load_result_does_not_clear_touched_when_an_edit_happened_while_it_was_in_flight():
    out = in_result("""const held = hold(p => p.startsWith('/api/result'));
      const run = loadResult(); await tick();
      act('editSub', {i: '0'}, {value: '请求发出之后改的'});
      held.forEach(r => r()); await run; await tick();
      return R().touched;""")
    assert out is True


def test_load_result_clears_touched_when_nothing_changed_meanwhile():
    out = in_result("""act('editSub', {i: '0'}, {value: 'x'}); const t = R().touched; await loadResult(); return [t, R().touched];""")
    assert out == [True, False]


# ---------------------------------------------------------------- MEDIUM-3：询问被别的弹窗顶掉 / 任何方式关闭都算取消
def test_prompt_replaced_by_another_modal_resolves_as_cancel_and_frees_the_slot():
    out = in_result("""const p = confirmReselect({}); await tick(); await tick(); await tick();
      showModal('别的窗口', '<p>x</p>');
      const r = await p; return [r, reselectUi.busy, jobs().length];""", state={"manual": MANUAL_ON})
    assert out == [None, False, 0]


def test_busy_flag_is_released_even_when_submit_throws():
    out = in_result("""let err = null;
      try { await confirmReselect({}, {submit: async () => { throw new Error('炸'); }}); } catch (e) { err = e.message; }
      return [err, reselectUi.busy];""")
    assert out == ["炸", False]


# ---------------------------------------------------------------- MEDIUM-4：目标时长的编辑框
def test_target_editor_stays_open_with_typed_value_when_the_job_cannot_start():
    out = in_result("""act('editTarget'); el('#tgtMin').value = '4'; el('#tgtSec').value = '30';
      await act('applyTarget'); await tick(); await tick();
      return [el('#rTop').innerHTML.includes('id="tgtMin"'), el('#tgtMin').value, el('#tgtSec').value, R().editing];""",
                    routes={"POST /api/job": [409, {"error": "已有任务在运行：别的 · 分析", "job_id": "j1", "task": "prepare"}]})
    assert out == [True, "4", "30", True]


def test_target_editor_closes_once_the_job_has_started():
    out = in_result("""act('editTarget'); el('#tgtMin').value = '4'; el('#tgtSec').value = '30';
      await act('applyTarget'); await tick(); return [R().editing, el('#rTop').innerHTML.includes('id="tgtMin"')];""")
    assert out == [False, False]


# ---------------------------------------------------------------- MEDIUM-5：旧的 /api/state 回包不能盖掉更新的本地表
def test_old_state_response_cannot_overwrite_edits_saved_while_it_was_in_flight():
    out = in_result("""const held = hold(p => p.startsWith('/api/state'));
      const run = refresh(); await tick(); await tick();
      act('editSub', {i: '0'}, {value: '请求期间改并存好'}); await flushPendingSave();
      held.forEach(r => r()); await run; await tick();
      return state.shots[0].sub;""")
    assert out == "请求期间改并存好"


# ---------------------------------------------------------------- MEDIUM-6：加回的行在重拉回来之前一直隐藏
def test_added_back_row_stays_hidden_until_the_reload_returns():
    out = in_result("""let armed = false; const orig = window.fetch, held = [];
      window.fetch = (p, o) => (armed && String(p).startsWith('/api/result')) ? new Promise(r => held.push(() => r(orig(p, o)))) : orig(p, o);
      armed = true;
      const run = act('addBack', {id: 'U1'}); await tick(); await tick(); await tick();
      const mid = [el('#rUnused').innerHTML.includes('data-id="U1"'), R().adding.has('U1')];
      held.forEach(r => r()); await run;
      return [mid, R().adding.has('U1')];""")
    assert out == [[False, True], False]


def test_failed_add_back_rolls_back_and_reloads_so_the_gate_state_is_right():
    out = in_result("""const before = rcalls().length;
      await act('addBack', {id: 'U1'}); await tick();
      return [state.shots.length, rcalls().length - before, R().touched, el('#nav').innerHTML.includes('aria-disabled')];""",
                    routes={"POST /api/shots": [500, {"error": "磁盘满"}]}, result={"preview": PREVIEW_FRESH})
    assert out == [2, 1, False, False]


# ---------------------------------------------------------------- LOW
def test_mark_confirms_only_after_a_successful_save_and_repaints_the_row_at_once():
    ok = in_result("""act('pick', {i: '0'}); el('#rPv').currentTime = 12.5; act('mark', {which: 'in'});
      const now = el('#rTable').innerHTML.includes('00:12.5'); await tick(); await tick();
      return [now, el('#toast').textContent];""")
    assert ok == [True, "已设为入点"]
    bad = in_result("""act('pick', {i: '0'}); el('#rPv').currentTime = 12.5; act('mark', {which: 'in'}); await tick(); await tick();
      return el('#toast').textContent;""", routes={"POST /api/shots": [500, {"error": "磁盘满"}]})
    assert "已设为入点" not in bad and "磁盘满" in bad


def test_add_blank_confirms_only_after_a_successful_save():
    bad = in_result("act('addBlank'); await tick(); await tick(); return el('#toast').textContent;",
                    routes={"POST /api/shots": [500, {"error": "磁盘满"}]})
    assert "已加一个" not in bad


def test_clicking_inside_the_subtitle_box_does_not_pick_the_row():
    out = in_result("""const row = node({'data-act': 'pick', 'data-i': '1'});
      const box = node({'data-input': 'editSub', 'data-i': '1'}, row);
      click(box); const inside = [state.sel, R().mode];
      click(row); return [inside, state.sel, R().mode];""")
    assert out == [[None, "preview"], 1, "material"]


def test_gate_says_why_when_the_table_was_not_saved_instead_of_cancelled():
    out = in_criteria("""window.__respond = (m, p, b) => (m === 'POST' && p.startsWith('/api/shots')) ? [500, {error: '写不进去'}] : respond(m, p, b);
      state.shots = [{id: 'sh01', in: 0, out: 5, sub: 'x', note: ''}]; scheduleSave();
      await act('gate'); await tick(); await tick();
      return el('#cStatus').innerHTML;""", NO_CONFIRM_PENDING)
    assert "分镜表还没保存成功" in out and "已取消" not in out


def test_gate_cancel_keeps_the_cancelled_wording():
    out = in_criteria("""act('critPick', {q: '0', o: '0'});
      window.__respond = (m, p, b) => (m === 'GET' && p.startsWith('/api/state')) ? [200, {...state.data, manual: %s}] : respond(m, p, b);
      const run = act('gate'); await tick(); await tick(); await tick(); await act('reselectCancel'); await run; await tick();
      return el('#cStatus').innerHTML;""" % js(MANUAL_ON), NO_CONFIRM_PENDING)
    assert "已取消：答案已保存为草稿" in out


def test_restore_is_single_flight_and_the_table_is_read_only_between_flush_and_post():
    out = in_result("""const held = hold(p => p === '/api/result/restore-ai');
      act('openRestoreAi'); const a = act('restoreAiGo'); await tick(); await tick(); await tick();
      const lockedHtml = el('#rTable').innerHTML.includes('readonly');
      await act('del', {i: '0'}); const len = state.shots.length;
      act('openRestoreAi'); const b = act('restoreAiGo'); await tick();
      held.forEach(r => r()); await a; await b; await tick();
      return [lockedHtml, len, calls.filter(c => c.path === '/api/result/restore-ai').length, el('#rTable').innerHTML.includes('readonly')];""",
                    state={"manual": MANUAL_ON}, result={"manual": MANUAL_ON},
                    routes={"POST /api/result/restore-ai": {"ok": True, "backup": None, "wizard": None}})
    assert out == [True, 2, 1, False]
