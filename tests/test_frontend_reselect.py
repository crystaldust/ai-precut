"""M14 T12：KI-95 询问（三个入口）与「恢复为 AI 选段」（node vm）。"""
import pytest

from fe_criteria import CONFIRM, CRIT_STATE, in_criteria
from fe_harness import NODE, wizard
from fe_result import MANUAL_ON, PROJECT_Q, RESULT, in_result, js, text_of

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

EDITED = {"state": {"manual": MANUAL_ON}, "result": {"manual": MANUAL_ON}}
STALE_RESULT = wizard(analyze="done", browse="done", criteria="done",
                      result=("stale", "素材标记改过了 · 重新选段", "reselect"), export="available")
DONE_W = wizard(analyze="done", browse="done", criteria="done", result="available", export="available")


def reselect_in_result(script, **kw):
    return in_result(script, **{**EDITED, **kw})


# ---------------------------------------------------------------- 没改过：不询问
def test_banner_reselect_without_manual_edits_replaces_without_a_prompt():
    out = in_result("""await act('reselect'); await tick();
      return [jobs(), el('#mask').classList.contains('on')];""")
    assert out == [[{"project": "新项目", "task": "select", "manual": "replace"}], False]


def test_pending_edits_are_saved_and_state_reread_before_deciding():
    out = in_result("""state.shots[0].sub = '改了'; scheduleSave();
      const states = calls.filter(c => c.path.startsWith('/api/state')).length;
      await act('reselect'); await tick();
      const order = calls.filter(c => c.method === 'POST' || c.path.startsWith('/api/state')).map(c => c.path.split('?')[0]);
      return [order.slice(-3), calls.filter(c => c.path.startsWith('/api/state')).length - states];""")
    assert out[0] == ["/api/shots", "/api/state", "/api/job"] and out[1] == 1


def test_unsaved_table_blocks_the_reselect_with_an_explanation():
    out = in_result("""state.shots[0].sub = '改了'; scheduleSave();
      await act('reselect'); await tick();
      return [jobs().length, el('#mask').classList.contains('on'), el('#toast').textContent];""",
                    routes={"POST /api/shots": [500, {"error": "写不进去"}]})
    assert out[0] == 0 and out[1] is False and "分镜表还没保存成功，先不重新选段" in out[2]


# ---------------------------------------------------------------- 改过：三选一
def test_prompt_lists_the_manual_changes_escaped_with_the_remaining_count():
    out = reselect_in_result("""act('reselect'); await tick(); await tick();
      return [el('#modalTitle').textContent, el('#modalBody').innerHTML, state.modalKind];""")
    title, body, kind = out
    assert title == "你手动改过分镜表（3 处）" and kind == "reselect"
    assert "按新的设置重新选段会覆盖这些修改。" in body
    assert "第 4 镜改了字幕&lt;b&gt;" in body and "第 4 镜改了字幕<b>" not in body and "新增第 7 镜" in body
    assert "等另外 2 处" in body
    for act in ("reselectReplace", "reselectKeep", "reselectCancel"):
        assert f'data-act="{act}"' in body
    assert "覆盖，用新的 AI 选段" in body and "保留我的修改" in body and "取消" in body
    assert "只更新未采用清单和建议" in body
    assert "必留" not in body


def test_no_remaining_line_when_nothing_more_to_list():
    body = reselect_in_result("act('reselect'); await tick(); await tick(); return el('#modalBody').innerHTML;",
                              state={"manual": {**MANUAL_ON, "more": 0}},
                              result={"manual": {**MANUAL_ON, "more": 0}})
    assert "等另外" not in body


@pytest.mark.parametrize("button, manual", [("reselectReplace", "replace"), ("reselectKeep", "keep")])
def test_choice_starts_select_with_that_manual_mode_and_closes_the_prompt(button, manual):
    out = reselect_in_result(f"""act('reselect'); await tick(); await tick();
      await act('{button}'); await tick(); return [jobs(), el('#mask').classList.contains('on')];""")
    assert out == [[{"project": "新项目", "task": "select", "manual": manual}], False]


def test_cancel_sends_nothing():
    out = reselect_in_result("""act('reselect'); await tick(); await tick();
      await act('reselectCancel'); await tick(); return [jobs().length, el('#mask').classList.contains('on')];""")
    assert out == [0, False]


def test_escape_or_clicking_the_mask_counts_as_cancel_and_resolves_the_promise():
    out = reselect_in_result("""const p = confirmReselect({}); await tick(); await tick(); closeModal();
      return [await p, jobs().length];""")
    assert out == [None, 0]


def test_only_one_prompt_at_a_time():
    out = reselect_in_result("""const a = confirmReselect({}); const b = confirmReselect({}); await tick(); await tick();
      await act('reselectReplace'); const ra = await a; const rb = await b; await tick();
      return [ra, rb, jobs().length];""")
    assert out[0] == "replace" and out[1] is None and out[2] == 1


# ---------------------------------------------------------------- 入口：⑤ 改时长 / 建议时长
def test_target_change_with_manual_edits_asks_then_sends_target_and_choice():
    out = reselect_in_result("""act('editTarget'); el('#tgtMin').value = '4'; el('#tgtSec').value = '0';
      act('applyTarget'); await tick(); await tick(); const asked = el('#modalTitle').textContent;
      await act('reselectKeep'); await tick(); return [asked, jobs()];""")
    assert out[0] == "你手动改过分镜表（3 处）"
    assert out[1] == [{"project": "新项目", "task": "select", "target": 240, "manual": "keep"}]


def test_suggested_target_with_manual_edits_also_asks():
    over = {**RESULT["topbar"], "over_target": True, "must_total": 220, "suggested_target": 220}
    out = reselect_in_result("""act('applySuggested'); await tick(); await tick(); const asked = el('#modalTitle').textContent;
      await act('reselectReplace'); await tick(); return [asked, jobs()];""", result={"manual": MANUAL_ON, "topbar": over})
    assert out[0] == "你手动改过分镜表（3 处）"
    assert out[1] == [{"project": "新项目", "task": "select", "target": 220, "manual": "replace"}]


def test_cancelling_the_target_prompt_keeps_the_inline_editor_open():
    out = reselect_in_result("""act('editTarget'); el('#tgtMin').value = '4'; el('#tgtSec').value = '0';
      act('applyTarget'); await tick(); await tick(); await act('reselectCancel'); await tick();
      return [jobs().length, el('#rTop').innerHTML.includes('id="tgtMin"')];""")
    assert out == [0, True]


# ---------------------------------------------------------------- 入口：④ 重新确认
CRIT_EDITED = {"GET /api/state": {**CRIT_STATE, "manual": MANUAL_ON}}
CONFIRM_ALL = {**CONFIRM, "pending": []}
SETUP_GATE = """window.__respond = (m, p, b) => m === 'POST' && p === '/api/confirm/answers'
  ? (b.confirmed === true ? [200, {ok: true, job_id: 'sel1', wizard: null}] : [200, {ok: true, job_id: null, wizard: null}])
  : respond(m, p, b);
const gatePosts = () => draftPosts().filter(b => b.confirmed === true);"""


def gate(script, routes=None):
    return in_criteria(SETUP_GATE + script, {"GET /api/confirm": CONFIRM_ALL, **(routes or {})})


def test_gate_without_manual_edits_confirms_with_replace_and_no_prompt():
    out = gate("await act('gate'); return [gatePosts(), el('#mask').classList.contains('on')];")
    assert out[0] == [{"project": "新项目", "answers": {}, "confirmed": True, "manual": "replace"}] and out[1] is False


@pytest.mark.parametrize("button, manual", [("reselectReplace", "replace"), ("reselectKeep", "keep")])
def test_gate_with_manual_edits_asks_then_confirms_with_the_choice(button, manual):
    out = gate(f"""const run = act('gate'); await tick(); await tick(); const asked = el('#modalTitle').textContent;
      const before = gatePosts().length; await act('{button}'); await run; await tick();
      return [asked, before, gatePosts().map(b => b.manual)];""", CRIT_EDITED)
    assert out == ["你手动改过分镜表（3 处）", 0, [manual]]


def test_gate_cancel_does_not_confirm_keeps_draft_and_allows_trying_again():
    out = gate("""act('critPick', {q: '0', o: '0'}); act('critPick', {q: '1', o: '1'});
      const run = act('gate'); await tick(); await tick(); await act('reselectCancel'); await run; await tick();
      const first = [gatePosts().length, draftPosts().length, el('#cStatus').innerHTML, C().gating];
      const again = act('gate'); await tick(); await tick(); const reopened = el('#mask').classList.contains('on');
      await act('reselectReplace'); await again; return [first, reopened, gatePosts().length];""", CRIT_EDITED)
    assert out[0][0] == 0 and out[0][1] >= 1 and "已取消：答案已保存为草稿" in out[0][2] and out[0][3] is False
    assert out[1] is True and out[2] == 1


def test_gate_asks_about_pending_segments_first_and_manual_edits_second():
    out = in_criteria(SETUP_GATE + """await act('gate'); const first = el('#modalTitle').textContent;
      const run = act('gateGo'); await tick(); await tick(); const second = el('#modalTitle').textContent;
      await act('reselectReplace'); await run; return [first, second, gatePosts().map(b => b.manual)];""",
                      CRIT_EDITED)
    assert out == ["还有 3 段待定，按 AI 建议处理？", "你手动改过分镜表（3 处）", ["replace"]]


def test_gate_nav_has_no_manual_table_note_any_more():
    out = in_criteria("""state.data = {...state.data, shots_from_selection: false}; state.shots = [{id: 'sh01'}];
      renderNav(); return el('#nav').innerHTML;""")
    assert "手动改过分镜表" not in out and "确认，生成分镜表" in out


# ---------------------------------------------------------------- 恢复为 AI 选段
def test_restore_button_only_appears_after_manual_edits():
    off = in_result("return el('#rTop').innerHTML;")
    on = reselect_in_result("return el('#rTop').innerHTML;")
    assert "openRestoreAi" not in off
    assert 'data-act="openRestoreAi"' in on and "恢复为 AI 选段" in text_of(on) and "data-starts-job" in on


def test_restore_asks_for_confirmation_with_the_change_count():
    out = reselect_in_result("""act('openRestoreAi'); return [el('#modalTitle').textContent, el('#modalBody').innerHTML, calls.filter(c => c.path.includes('restore')).length];""")
    assert out[0] == "恢复为 AI 选段？当前手动修改（3 处）会被替换，已自动备份"
    assert 'data-act="restoreAiGo"' in out[1] and out[2] == 0


def test_confirmed_restore_posts_then_rereads_state_and_result_and_repaints_the_table():
    plain_state = {"manual": {"edited": False, "count": 0, "changes": [], "more": 0}}
    out = reselect_in_result(f"""const base = window.__respond; let restored = false;
      window.__respond = (m, p, b) => {{
        if (m === 'POST' && p === '/api/result/restore-ai') {{ restored = true; return [200, {{ok: true, backup: 'x.json', wizard: null}}]; }}
        if (m === 'GET' && p.startsWith('/api/state') && restored) return [200, {{...window.__st, manual: window.__off, shots: [{{id:'sel01', in: 1, out: 9, sub: 'AI 的字幕', note: ''}}]}}];
        return respond(m, p, b); }};
      window.__st = JSON.parse(JSON.stringify(state.data)); window.__off = {js(plain_state['manual'])};
      el('#rTable').innerHTML = 'OLD';
      act('openRestoreAi'); await act('restoreAiGo'); await tick(); await tick();
      return [calls.filter(c => c.path === '/api/result/restore-ai').map(c => c.body),
              state.shots.map(s => s.id), el('#rTable').innerHTML.includes('AI 的字幕'), el('#mask').classList.contains('on')];""")
    assert out[0] == [{"project": "新项目"}] and out[1] == ["sel01"] and out[2] is True and out[3] is False


def test_pending_edits_are_flushed_before_restoring():
    out = reselect_in_result("""state.shots[0].sub = '改了'; scheduleSave();
      act('openRestoreAi'); await act('restoreAiGo'); await tick();
      return calls.filter(c => c.method === 'POST').map(c => c.path.split('?')[0]).slice(-2);""",
                             routes={"POST /api/result/restore-ai": {"ok": True, "backup": None, "wizard": None}})
    assert out == ["/api/shots", "/api/result/restore-ai"]


def test_restore_refusal_is_shown_verbatim_and_nothing_else_happens():
    out = reselect_in_result("""act('openRestoreAi'); await act('restoreAiGo'); await tick();
      return [el('#toast').textContent, el('#mask').classList.contains('on')];""",
                             routes={"POST /api/result/restore-ai": [409, {"error": "正在重新选段，完成后再试<b>"}]})
    assert out[0] == "正在重新选段，完成后再试<b>"


def test_q6_note_after_reanalysis_when_the_table_is_still_the_manual_one():
    stale = wizard(analyze="done", browse="done", criteria="done",
                   result=("stale", "分析结果更新了 · 重新选段", "reselect"), export="available")
    stale["steps"][4]["reasons"] = ["scored"]
    stale = {**stale, "next": "result"}
    out = in_result("return el('#rTop').innerHTML;", state={"wizard": stale, "manual": MANUAL_ON},
                    result={"manual": MANUAL_ON, "source": "manual", "wizard": stale})
    assert "分析结果更新了：分镜表仍是你手动改的那一版；需要时点「恢复为 AI 选段」" in text_of(out)
    plain = in_result("return el('#rTop').innerHTML;", state={"wizard": stale},
                      result={"source": "selection", "wizard": stale})
    assert "分析结果更新了：分镜表仍是" not in text_of(plain)
