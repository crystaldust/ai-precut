"""KI-104：③ 剪辑列表面板里改成片时长（node vm）：就地分 + 秒、确定 / 取消、超目标一键采用建议值、并发与竞态。"""
import pytest

from fe_browse import BROWSE, CLIP, STALE_WIZARD, in_browse, js
from fe_harness import NODE, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

CLIP_175 = {**CLIP, "target": 175}
BROWSE_175 = {**BROWSE, "clip_list": CLIP_175}
CLIP_OVER = {**CLIP, "total": 220, "target": 175, "over_target": True, "over_by": 45, "suggested_target": 220}
BROWSE_OVER = {**BROWSE, "clip_list": CLIP_OVER}
SAVED = {"ok": True, "project": {**BROWSE["project"], "target_duration": 180}, "wizard": STALE_WIZARD}
ROUTES = {"GET /api/browse": BROWSE_175, "POST /api/project/settings": SAVED}
SETTINGS = "/api/project/settings"
RANGE_TOAST = "时长要在 10 秒到 60 分钟之间（秒填 0–59 的整数）"


def settings_posts():
    return "calls.filter(c => c.path === '/api/project/settings').map(c => c.body)"


def test_panel_has_change_button_that_is_busy_guarded():
    html = in_browse("return el('#bPanel').innerHTML;", ROUTES)
    assert 'data-act="editClipTarget" data-starts-job' in html and ">改<" in html
    assert "目标 2:55" in html and "clipTgtMin" not in html


def test_edit_shows_minutes_and_seconds_prefilled_with_current_target():
    html = in_browse("act('editClipTarget'); return el('#bPanel').innerHTML;", ROUTES)
    assert 'id="clipTgtMin"' in html and 'value="2"' in html and 'id="clipTgtSec"' in html and 'value="55"' in html
    assert 'data-act="applyClipTarget" data-starts-job' in html and 'data-act="cancelClipTarget"' in html
    assert 'data-act="editClipTarget"' not in html and "合计" in html


def test_cancel_returns_to_plain_display_without_request():
    out = in_browse("act('editClipTarget'); act('cancelClipTarget'); return [el('#bPanel').innerHTML, " + settings_posts() + "];", ROUTES)
    assert 'data-act="editClipTarget"' in out[0] and "clipTgtMin" not in out[0] and out[1] == []


def test_confirm_posts_target_then_syncs_steps_and_rereads_browse():
    out = in_browse(f"""act('editClipTarget'); el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '';
      const before = calls.filter(c => c.path.startsWith('/api/browse')).length;
      await act('applyClipTarget'); await tick(); await tick();
      return [{settings_posts()}, B().targetEditing, el('#steps').innerHTML.includes('st-stale'), el('#steps').innerHTML,
              state.data.project.target_duration, calls.filter(c => c.path.startsWith('/api/browse')).length - before,
              el('#bPanel').innerHTML.includes('clipTgtMin'), el('#toast').textContent];""", ROUTES)
    assert out[0] == [{"project": "新项目", "target": 180}]
    assert out[1] is False and out[2] is True and 'title="素材标记改过了 · 重新选段"' in out[3]
    assert out[4] == 180 and out[5] == 1 and out[6] is False
    assert out[7] == "已保存。⑤ 看结果需要重新选段才会按新时长出分镜表"


def test_confirm_without_stale_result_uses_plain_toast():
    plain = {**SAVED, "wizard": wizard()}
    out = in_browse("act('editClipTarget'); el('#clipTgtMin').value = '3'; await act('applyClipTarget'); return el('#toast').textContent;",
                    {**ROUTES, "POST " + SETTINGS: plain})
    assert out == "成片时长已保存"


@pytest.mark.parametrize("minutes,seconds", [("", "5"), ("0", "9"), ("1", "60"), ("61", "0"), ("0", "0"), ("x", "1")])
def test_invalid_duration_toasts_and_sends_nothing(minutes, seconds):
    out = in_browse(f"""act('editClipTarget'); el('#clipTgtMin').value = {minutes!r}; el('#clipTgtSec').value = {seconds!r};
      await act('applyClipTarget'); return [{settings_posts()}, el('#toast').textContent, B().targetEditing];""", ROUTES)
    assert out == [[], RANGE_TOAST, True]


def test_server_failure_keeps_edit_state_and_shows_reason():
    out = in_browse(f"""act('editClipTarget'); el('#clipTgtMin').value = '3';
      await act('applyClipTarget'); await tick();
      return [el('#toast').textContent, B().targetEditing, el('#bPanel').innerHTML.includes('clipTgtMin'),
              state.data.project.target_duration, el('#steps').innerHTML.includes('st-stale')];""",
                    {**ROUTES, "POST " + SETTINGS: [409, {"error": "正在处理这个项目，完成后再改时长"}]})
    assert out == ["正在处理这个项目，完成后再改时长", True, True, None, False]


def test_second_confirm_while_saving_sends_only_one_request():
    out = in_browse(f"""const held = hold(p => p === '{SETTINGS}');
      act('editClipTarget'); el('#clipTgtMin').value = '3';
      const a = act('applyClipTarget'), b2 = act('applyClipTarget'); await tick();
      held.forEach(f => f()); await a; await b2; await tick();
      return [held.length, {settings_posts()}.length];""", ROUTES)
    assert out == [1, 1]


def test_reply_after_switching_project_does_not_touch_the_page():
    out = in_browse(f"""const held = hold(p => p === '{SETTINGS}');
      act('editClipTarget'); el('#clipTgtMin').value = '3';
      const run = act('applyClipTarget'); await tick();
      const wiz = state.data.wizard, toasts = el('#toast').textContent;
      resetBrowse();
      held.forEach(f => f()); await run; await tick(); await tick();
      return [state.data.wizard === wiz, el('#toast').textContent === toasts, state.data.project.target_duration];""", ROUTES)
    assert out == [True, True, None]


def test_over_target_warning_offers_apply_suggested_and_posts_it():
    html = in_browse("return el('#bPanel').innerHTML;", {**ROUTES, "GET /api/browse": BROWSE_OVER})
    assert 'data-act="applyClipSuggested" data-starts-job' in html and "改为 3:40" in html and "已超出目标 0:45" in html
    out = in_browse(f"await act('applyClipSuggested'); await tick(); return {settings_posts()};",
                    {**ROUTES, "GET /api/browse": BROWSE_OVER})
    assert out == [{"project": "新项目", "target": 220}]


def test_no_suggested_button_when_within_target():
    html = in_browse("return el('#bPanel').innerHTML;", ROUTES)
    assert "applyClipSuggested" not in html
    out = in_browse(f"await act('applyClipSuggested'); return {settings_posts()};", ROUTES)
    assert out == []


def test_repaint_during_edit_writes_typed_values_back():
    out = in_browse("""act('editClipTarget');
      const writes = [];
      for (const id of ['#clipTgtMin', '#clipTgtSec']) {
        let cur = '';
        Object.defineProperty(el(id), 'value', {get(){ return cur; }, set(v){ writes.push([id, v]); cur = v; }, configurable: true});
      }
      el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '5'; writes.length = 0;
      act('jumpSeg', {i: '0'}); await press('KeyS');
      return [writes, B().targetEditing, el('#bPanel').innerHTML.includes('clipTgtMin')];""",
                   {**ROUTES, "POST /api/browse/must": {"ok": True, "cleared": None, "segment": {"id": "S1", "must_keep": True, "unusable": False, "level": 3, "override": False},
                                                         "clip_list": CLIP_175, "wizard": STALE_WIZARD}})
    writes, editing, has_inputs = out
    assert ["#clipTgtMin", "3"] in writes and ["#clipTgtSec", "5"] in writes and editing is True and has_inputs is True


def test_busy_guard_disables_panel_buttons_after_repaint():
    out = in_browse("""const btn = node({'data-starts-job': ''}); lists['[data-starts-job]'] = [btn];
      state.data = {...state.data, busy: {id: 'j1', label: '选段'}};
      renderClipPanel(); return btn.disabled;""", ROUTES)
    assert out is True


def test_entering_browse_again_resets_edit_state():
    out = in_browse("act('editClipTarget'); await enterBrowse(); await tick(); return [B().targetEditing, el('#bPanel').innerHTML.includes('clipTgtMin')];", ROUTES)
    assert out == [False, False]


def test_every_dynamic_text_in_panel_goes_through_esc():
    """把 esc 换成会打标记的版本：去掉标记过的文字和标签后，不能剩下任何文字（含 COPY_* 和数字）。"""
    out = in_browse("""const orig = esc; esc = s => '\u00ab' + orig(s) + '\u00bb';
      const clip = {items: [], total: 125, target: 175, over_target: true, over_by: 45, suggested_target: 220};
      const strip = h => h.replace(/\u00ab[^\u00bb]*\u00bb/g, '').replace(/<[^>]*>/g, '').replace(/[分秒\\s]/g, '');   // durationFields 里写死的「分」「秒」不是动态文本
      const view = editing => { B().targetEditing = editing; return strip(clipSumHtml(clip, B())) + '|' + strip(clipOverHtml(clip)); };
      const marked = clipOverHtml(clip).includes('\u00ab');
      return [view(false), view(true), marked, strip(panelHtml(clip, B()))];""", ROUTES)
    assert out[0] == "|" and out[1] == "|" and out[2] is True and out[3] == ""


def test_esc_marker_really_detects_unescaped_text():
    out = in_browse("""const orig = esc; esc = s => '\u00ab' + orig(s) + '\u00bb';
      const strip = h => h.replace(/\u00ab[^\u00bb]*\u00bb/g, '').replace(/<[^>]*>/g, '').trim();
      return strip('<div>raw ' + esc('ok') + '</div>');""", ROUTES)
    assert out == "raw"


# ---------------------------------------------------------------- 评审修复
def hold_settings():
    return f"const held = hold(p => p === '{SETTINGS}');"


def test_saving_flag_is_per_browse_so_other_project_is_not_blocked():
    out = in_browse(hold_settings() + """
      act('editClipTarget'); el('#clipTgtMin').value = '3';
      const first = act('applyClipTarget'); await tick();
      resetBrowse(); await enterBrowse(); await tick();
      act('editClipTarget'); el('#clipTgtMin').value = '4';
      const second = act('applyClipTarget'); await tick();
      const n = held.length;
      held.forEach(f => f()); await first; await second;
      return n;""", ROUTES)
    assert out == 2


FAIL_RESYNC = "window.__respond = (m, p, b) => p.startsWith('/api/browse?') ? [500, {error: '读不出来'}] : respond(m, p);"


def test_clip_target_updates_locally_even_when_resync_fails_and_edit_prefills_it():
    out = in_browse(FAIL_RESYNC + """
      act('editClipTarget'); el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick(); await tick();
      const html = el('#bPanel').innerHTML;
      act('editClipTarget');
      return [B().clip.target, html.includes('目标 3:00'), el('#bPanel').innerHTML];""", {**ROUTES, "GET /api/browse": BROWSE_OVER})
    assert out[0] == 180 and out[1] is True
    assert 'id="clipTgtMin"' in out[2] and 'value="3"' in out[2]


def test_local_target_recomputes_over_flags_and_hides_stale_suggestion():
    routes = {**ROUTES, "GET /api/browse": BROWSE_OVER}
    out = in_browse(FAIL_RESYNC + """
      await act('applyClipTarget'); // 空输入：不发
      act('editClipTarget'); el('#clipTgtMin').value = '4'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick();
      const roomy = {...B().clip}, html = el('#bPanel').innerHTML;
      act('editClipTarget'); el('#clipTgtMin').value = '2'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick();
      return [roomy, html, B().clip];""", routes)
    assert in_browse(FAIL_RESYNC + "await act('applyClipTarget'); act('editClipTarget'); el('#clipTgtMin').value = '4'; el('#clipTgtSec').value = '0'; await act('applyClipTarget'); await tick(); return await act('applyClipSuggested');",
                     routes) is False  # 不超出时「改为…」不生效
    roomy, html, tight = out
    assert roomy["target"] == 240 and roomy["over_target"] is False and roomy["over_by"] == 0
    assert "applyClipSuggested" not in html and "已超出" not in html
    assert tight["target"] == 120 and tight["over_target"] is True and tight["over_by"] == 100 and tight["suggested_target"] == 220


MUST_OK = {"POST /api/browse/must": {"ok": True, "cleared": None, "wizard": STALE_WIZARD, "clip_list": CLIP_175,
                                     "segment": {"id": "S1", "must_keep": True, "unusable": False, "level": 3, "override": False}}}


def test_save_while_mark_in_flight_keeps_new_target_in_panel():
    out = in_browse("const held = hold(p => p === '/api/browse/must');" + FAIL_RESYNC + """
      act('jumpSeg', {i: '0'}); await press('KeyS');
      act('editClipTarget'); el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick();
      const during = el('#bPanel').innerHTML;
      held.forEach(f => f()); await tick(); await tick(); await tick();
      return [during.includes('目标 3:00'), B().clip.target, el('#bPanel').innerHTML.includes('目标 3:00')];""",
                   {**ROUTES, **MUST_OK})
    assert out == [True, 180, True]


def test_late_mark_response_with_old_target_does_not_revert_new_target():
    out = in_browse("const held = hold(p => p === '/api/browse/must');" + FAIL_RESYNC + """
      act('jumpSeg', {i: '0'}); await press('KeyS');
      act('editClipTarget'); el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick();
      held.forEach(f => f()); await tick(); await tick(); await tick();
      return [B().clip.target, el('#bPanel').innerHTML.includes('目标 3:00')];""", {**ROUTES, **MUST_OK})
    assert out == [180, True]


def test_successful_resync_always_wins_even_if_value_differs_from_what_was_saved():
    """保存 120，重读回来 200（别处改过）：以服务端为准，面板显示 200，并清掉本地覆盖。"""
    other = {**BROWSE, "clip_list": {**CLIP, "target": 200}}
    out = in_browse("""act('editClipTarget'); el('#clipTgtMin').value = '2'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick(); await tick();
      return [B().clip.target, B().targetOverride || null, el('#bPanel').innerHTML.includes('目标 3:20')];""",
                    {**ROUTES, "GET /api/browse": other})
    assert out == [200, None, True]


def test_resync_returning_the_same_value_also_clears_override():
    fresh = {**BROWSE, "clip_list": {**CLIP, "target": 180}}
    out = in_browse("""act('editClipTarget'); el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick(); await tick();
      return [B().clip.target, B().targetOverride || null];""", {**ROUTES, "GET /api/browse": fresh})
    assert out == [180, None]


def test_failed_resync_keeps_override_so_local_value_stays():
    out = in_browse(FAIL_RESYNC + """
      act('editClipTarget'); el('#clipTgtMin').value = '3'; el('#clipTgtSec').value = '0';
      await act('applyClipTarget'); await tick(); await tick();
      return [B().clip.target, B().targetOverride];""", ROUTES)
    assert out == [180, 180]


def test_repaint_restores_focus_and_selection_of_target_inputs():
    out = in_browse("""act('editClipTarget');
      const inp = el('#clipTgtMin'); let focused = 0; inp.focus = () => { focused++; };
      inp.id = 'clipTgtMin'; inp.selectionStart = 1; inp.selectionEnd = 2;
      document.activeElement = inp;
      renderClipPanel();
      inp.selectionStart = 0; inp.selectionEnd = 0;   // 真 DOM 重画后光标丢了
      document.activeElement = null;
      return [focused];""", ROUTES)
    assert out == [1]
    out = in_browse("""act('editClipTarget');
      const inp = el('#clipTgtSec'); let focused = 0; const marks = [];
      inp.id = 'clipTgtSec'; inp.selectionStart = 1; inp.selectionEnd = 2;
      Object.defineProperty(inp, 'focus', {value(){ focused++; }});
      document.activeElement = inp;
      let start = 1;
      Object.defineProperty(inp, 'selectionStart', {get(){ return start; }, set(v){ marks.push(v); start = v; }, configurable: true});
      renderClipPanel();
      return [focused, marks];""", ROUTES)
    assert out == [1, [1]]


def test_repaint_does_not_steal_focus_from_elsewhere():
    out = in_browse("""act('editClipTarget'); const other = el('#somewhere'); other.id = 'somewhere';
      let focused = 0; el('#clipTgtMin').focus = () => { focused++; };
      document.activeElement = other; renderClipPanel(); return focused;""", ROUTES)
    assert out == 0


def test_suggested_button_hidden_while_marks_are_in_flight():
    tight = {**CLIP, "target": 3, "over_target": True, "over_by": 2, "suggested_target": 5}   # 再放一段本地也还是超
    routes = {**ROUTES, "GET /api/browse": {**BROWSE, "clip_list": tight}, **MUST_OK}
    out = in_browse("const held = hold(p => p === '/api/browse/must');" + """
      const before = el('#bPanel').innerHTML.includes('applyClipSuggested');
      act('jumpSeg', {i: '0'}); await press('KeyS');
      const during = el('#bPanel').innerHTML;
      held.forEach(f => f()); await tick(); await tick(); await tick();
      return [before, during.includes('applyClipSuggested'), during.includes('已超出')];""", routes)
    assert out[0] is True and out[1] is False and out[2] is True   # 仍显示超出说明，只是没有按钮


def test_stale_wizard_uses_stale_toast_on_browse_too():
    out = in_browse("act('editClipTarget'); el('#clipTgtMin').value = '3'; await act('applyClipTarget'); return el('#toast').textContent;", ROUTES)
    assert out == "已保存。⑤ 看结果需要重新选段才会按新时长出分镜表"
