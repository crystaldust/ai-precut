"""简单模式（mode=simple）前端：新建 / 项目设置的出片模式、步骤条跳过 ④、导航、⑤ 顶栏、空表提示、进入 ⑤ 自动重新选段。"""
import pytest

from fe_fixtures import FILL_NEW, NEW_ROUTES, NEW_STATE
from fe_harness import NODE, run_app, wizard
from fe_result import (MANUAL_ON, RESULT, RROUTES, RSTATE, SHOTS, UNUSED, in_result, js, result_wizard, text_of)

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

NOTE = "简单模式不需要定标准"
SIMPLE_PROJECT = {**NEW_STATE["project"], "mode": "simple"}


def simple_wizard(result="available", export="available", nxt="result", result_banner=None):
    w = wizard(analyze="done", browse="done", criteria="available", result=result, export=export)
    for s in w["steps"]:
        if s["key"] == "criteria":
            s.update(status="skipped", hint=NOTE, banner=None)  # 后端把说明放在 hint（键集合与其他步骤一致）
        if s["key"] == "result" and result_banner:
            s.update(banner=result_banner, action="reselect", reasons=["mode"])
    return {**w, "next": nxt}


STALE_WIZARD = simple_wizard(result=("stale", "剪辑列表改过了 · 重新选段", "reselect"), nxt="result")
STALE_WIZARD["steps"][4]["action"] = "reselect"


def simple_state(**kw):
    return {"project": SIMPLE_PROJECT, "wizard": simple_wizard(), **kw}


def simple_result(**kw):
    topbar = {"total": 178, "shots": 2, "clip": {"count": 2, "covered": 2, "missing": []},
              "target": None, "over_target": False, "must_total": 0, "suggested_target": None}
    return {"mode": "simple", "unused": [], "topbar": topbar, "wizard": simple_wizard(), **kw}


def in_simple(script, *, state=None, result=None, routes=None):
    return in_result(script, routes, state=simple_state(**(state or {})), result=simple_result(**(result or {})))


# ---------------------------------------------------------------- 1. 新建 / 项目设置
def test_new_project_form_offers_mode_radios_default_simple_recommended():
    out = run_app("(async () => { await openNew(); return el('#modalBody').innerHTML; })()", routes=NEW_ROUTES)
    assert 'name="npMode"' in out and 'value="simple" checked' in out and 'value="full" checked' not in out
    assert "简单（只用剪辑列表 · 推荐）" in out and "完整（AI 按标准选段）" in out
    assert out.index('value="simple"') < out.index('value="full"')  # 推荐的放前面


def test_create_posts_mode_chosen():
    out = run_app("(async () => {" + FILL_NEW + """
      el('input[name="npMode"]:checked').value = 'full';
      await createProject(); return calls.find(c => c.path === '/api/new').body.mode; })()""", routes=NEW_ROUTES)
    assert out == "full"


def test_create_defaults_to_simple_when_untouched():
    out = run_app("(async () => {" + FILL_NEW + "await createProject(); return calls.find(c => c.path === '/api/new').body.mode; })()",
                  routes=NEW_ROUTES)
    assert out == "simple"


PREFS_SIMPLE = "剪辑偏好（可选，影响 ③ 的 AI 分档）"


def test_new_form_in_simple_mode_collapses_prefs_and_hides_must_lines():
    html = run_app("(async () => { await openNew(); return el('#modalBody').innerHTML; })()", routes=NEW_ROUTES)
    assert '<details class="prefs" id="npPrefs">' in html  # 默认收起（没有 open）
    assert f'<summary id="npPrefsTitle">{PREFS_SIMPLE}</summary>' in html
    assert 'id="npMustField" hidden' in html and 'id="npMust"' in html  # 原话框还在，只是简单模式下藏起来
    assert 'data-change="syncModePrefs" data-prefix="np"' in html


def test_new_form_switching_to_full_shows_must_lines_and_original_title():
    out = run_app("""(async () => { await openNew();
      el('input[name="npMode"]:checked').value = 'full'; ACTIONS.syncModePrefs({dataset: {prefix: 'np'}});
      const full = [el('#npMustField').hidden, el('#npPrefsTitle').textContent];
      el('input[name="npMode"]:checked').value = 'simple'; ACTIONS.syncModePrefs({dataset: {prefix: 'np'}});
      return [full, [el('#npMustField').hidden, el('#npPrefsTitle').textContent]]; })()""", routes=NEW_ROUTES)
    assert out == [[False, "剪辑偏好（可跳过）"], [True, PREFS_SIMPLE]]


def test_settings_prefs_follow_mode_choice():
    out = run_app("""(async () => { await selectProject('新项目'); await openProjectSettings();
      const html = el('#modalBody').innerHTML;
      el('input[name="psMode"]:checked').value = 'simple'; ACTIONS.syncModePrefs({dataset: {prefix: 'ps'}});
      return [html, el('#psMustField').hidden, el('#psPrefsTitle').textContent]; })()""", routes=NEW_ROUTES)
    html, hidden, title = out
    assert 'id="psMustField">' in html and '<h3 id="psPrefsTitle">剪辑偏好</h3>' in html  # 完整项目：和以前一样
    assert hidden is True and title == "剪辑偏好（影响 ③ 的 AI 分档）"


def test_settings_dialog_shows_current_mode_and_posts_change_applying_wizard():
    body, steps = run_app("""(async () => {
      await selectProject('新项目'); await openProjectSettings();
      const html = el('#modalBody').innerHTML;
      el('#psMin').value = '2'; el('#psSec').value = '55';
      el('input[name="psMode"]:checked').value = 'simple';
      await saveProjectSettings();
      return [calls.find(c => c.path === '/api/project/settings').body, [html, el('#steps').innerHTML]]; })()""",
                         routes={**NEW_ROUTES, "POST /api/project/settings": {
                             "ok": True, "project": SIMPLE_PROJECT, "wizard": simple_wizard()}},
                         setup="__respond = (m, p, b) => m === 'GET' && p.startsWith('/api/state') && calls.some(c => c.path === '/api/project/settings')"
                               " ? [200, " + js(simple_state(**{k: v for k, v in NEW_STATE.items() if k not in ('project', 'wizard')})) + "] : respond(m, p);")
    html, bar = steps
    assert 'name="psMode"' in html and 'value="full" checked' in html
    assert body["mode"] == "simple" and "st-skipped" in bar


def test_settings_omit_mode_when_unchanged():
    body = run_app("""(async () => {
      await selectProject('新项目'); await openProjectSettings(); el('#psMin').value = '2'; el('#psSec').value = '55';
      await saveProjectSettings(); return calls.find(c => c.path === '/api/project/settings').body; })()""",
                   routes={**NEW_ROUTES, "POST /api/project/settings": {
                       "ok": True, "project": NEW_STATE["project"], "wizard": NEW_STATE["wizard"]}})
    assert "mode" not in body


def test_settings_mode_radios_disabled_while_a_job_runs():
    html = run_app("(async () => { await selectProject('新项目'); await openProjectSettings(); return el('#modalBody').innerHTML; })()",
                   routes={**NEW_ROUTES, "GET /api/state": {**NEW_STATE, "busy": {"id": "j1", "task": "select", "label": "重新选段"}}})
    assert html.count('name="psMode"') == 2 and html.count(" disabled") >= 2 and "正在" in text_of(html)


# ---------------------------------------------------------------- 2. 步骤条与导航
def test_step_bar_greys_out_criteria_with_note_and_go_toasts_it():
    bar, toast, view = in_simple("""const bar = el('#steps').innerHTML; await go('criteria');
      return [bar, el('#toast').textContent, state.view];""")
    assert "st-skipped" in bar and f'title="{NOTE}"' in bar
    assert toast == NOTE and view == "result"


def test_browse_next_skips_criteria_and_reads_go_to_result():
    html = in_simple("await go('browse'); return el('#nav').innerHTML;")
    assert 'data-step="result"' in html and "下一步：去看结果 →" in text_of(html) and 'data-step="criteria"' not in html


def test_result_prev_goes_back_to_browse_in_simple_mode():
    html = in_simple("return el('#nav').innerHTML;")
    assert 'data-step="browse"' in html and 'data-step="criteria"' not in html


def test_full_mode_browse_next_still_goes_to_criteria():
    html = in_result("await go('browse'); return el('#nav').innerHTML;")
    assert 'data-step="criteria"' in html and "去定标准" in text_of(html)


def test_skipped_view_resolves_to_wizard_next():
    view = in_simple("state.view = 'criteria'; return resolveView(state.data.wizard, 'criteria');")
    assert view == "result"


# ---------------------------------------------------------------- 3. ⑤ 顶栏
def test_simple_top_bar_shows_total_and_shots_without_target_prompt_or_over_warning():
    top = in_simple("return el('#rTop').innerHTML;", result={"topbar": {
        **simple_result()["topbar"], "over_target": True, "must_total": 220, "suggested_target": 220}})
    txt = text_of(top)
    assert "剪辑列表合计 2:58" in txt and "镜头 2" in txt
    for gone in ("editTarget", "applySuggested", "openAiPrompt", "目标"):
        assert gone not in top


def test_simple_top_bar_restore_wording_keeps_same_action():
    top = in_simple("return el('#rTop').innerHTML;", state={"manual": MANUAL_ON}, result={"manual": MANUAL_ON})
    assert "恢复为剪辑列表" in text_of(top) and "恢复为 AI 选段" not in top and 'data-act="openRestoreAi"' in top


def test_full_mode_top_bar_unchanged():
    top = in_result("return el('#rTop').innerHTML;")
    assert "editTarget" in top and "openAiPrompt" in top


def test_simple_hides_unused_panel_full_shows_it():
    simple = in_simple("return el('#rUnused').innerHTML;", result={"unused": UNUSED})
    full = in_result("return el('#rUnused').innerHTML;")
    assert simple == "" and "未采用清单" in full


# ---------------------------------------------------------------- 3b. 空表
def test_empty_clip_list_shows_notice_with_button_to_browse_and_disables_preview():
    table, note = in_simple("return [el('#rTable').innerHTML, el('#rPvNote').innerHTML];", state={"shots": []},
                            result={"topbar": {**simple_result()["topbar"], "total": 0, "shots": 0}})
    assert "剪辑列表是空的：先在「③ 看素材」把要用的片段放进剪辑列表" in text_of(table)
    assert 'data-act="go" data-step="browse"' in table and "addBlank" not in table
    assert 'data-act="makePreview"' in note and " disabled" in note and "data-starts-job" not in note


def test_nonempty_simple_table_keeps_preview_button_enabled():
    note = in_simple("return el('#rPvNote').innerHTML;")
    assert "makePreview" in note and " disabled" not in note


# ---------------------------------------------------------------- 4. 进入 ⑤ 自动重新选段
STALE_STATE = {"wizard": STALE_WIZARD}
STALE_RESULT = {"wizard": STALE_WIZARD}


def test_entering_stale_simple_result_auto_reselects_without_prompt():
    jobs = in_simple("return [jobs(), el('#mask').classList.contains('on')];", state=STALE_STATE, result=STALE_RESULT)
    assert jobs == [[{"project": "新项目", "task": "select", "manual": "replace"}], False]


def test_auto_reselect_asks_keep_replace_when_manually_edited_and_starts_nothing_yet():
    out = in_simple("return [jobs().length, el('#mask').classList.contains('on'), el('#modalTitle').textContent];",
                    state={**STALE_STATE, "manual": MANUAL_ON}, result={**STALE_RESULT, "manual": MANUAL_ON})
    assert out[0] == 0 and out[1] is True and "你手动改过分镜表" in out[2]


def test_auto_reselect_does_not_loop_on_reloads():
    n = in_simple("await loadResult(); await loadResult(); await onResultJobDone('select'); await tick(); return jobs().length;",
                  state=STALE_STATE, result=STALE_RESULT)
    assert n == 1


def test_auto_reselect_skipped_when_a_job_is_already_running():
    n = in_simple("return jobs().length;", state={**STALE_STATE, "busy": {"id": "j9", "task": "select", "label": "重新选段"}},
                  result=STALE_RESULT)
    assert n == 0


def test_fresh_simple_result_does_not_auto_reselect():
    assert in_simple("return jobs().length;") == 0


def test_full_mode_stale_result_never_auto_reselects():
    stale = result_wizard(result=("stale", "目标变了 · 重新选段", "reselect"))
    assert in_result("return jobs().length;", state={"wizard": stale}, result={"wizard": stale}) == 0


# ---------------------------------------------------------------- 评审修复
FRESH_SIMPLE = simple_state()
def switch_setup(stale_state):
    """staleNow 为真时 /api/state 与 /api/result 都回「⑤ 过期」的版本。"""
    return ("var staleNow = false; const STALE_JSON = " + js({**RSTATE, **stale_state}) + ", FRESH_JSON = "
            + js({**RSTATE, **FRESH_SIMPLE}) + ", STALE_RES = " + js({**RESULT, **simple_result(), "wizard": STALE_WIZARD}) + "; "
            "__respond = (m, p) => m !== 'GET' ? respond(m, p) : p.startsWith('/api/state') "
            "? [200, staleNow ? STALE_JSON : FRESH_JSON] : p.startsWith('/api/result?') && staleNow ? [200, STALE_RES] : respond(m, p);")


def in_switch(script, stale_extra=None):
    stale = {**simple_state(), "wizard": STALE_WIZARD, **(stale_extra or {})}
    return in_result(script, None, state=FRESH_SIMPLE, result=simple_result(), setup=switch_setup(stale))


def test_auto_reselect_aborts_when_project_switches_during_the_awaits():
    n = in_switch("""staleNow = true; applyWizard(%s); const before = jobs().length;
      const p = autoReselectOnEnter(resultGen, state.project); state.project = '其他'; await p; await tick();
      return jobs().length - before;""" % js(STALE_WIZARD))
    assert n == 0


def test_auto_reselect_aborts_when_leaving_step_five_before_the_result_loads():
    n = in_switch("""staleNow = true; const before = jobs().length;
      const p = enterResult(); state.view = 'browse'; await p; await tick(); return jobs().length - before;""")
    assert n == 0


def test_auto_reselect_aborts_when_step_turns_fresh_during_the_awaits():
    n = in_switch("""staleNow = false; applyWizard(%s); const before = jobs().length;
      await autoReselectOnEnter(resultGen, state.project); await tick(); return jobs().length - before;""" % js(STALE_WIZARD))
    assert n == 0


def test_auto_reselect_starts_when_nothing_changed():
    n = in_switch("""staleNow = true; applyWizard(%s); const before = jobs().length;
      await autoReselectOnEnter(resultGen, state.project); await tick(); return jobs().length - before;""" % js(STALE_WIZARD))
    assert n == 1


def test_reclicking_step_five_after_cancelling_the_dialog_does_not_reopen_it():
    out = in_simple("""await act('reselectCancel'); await tick(); closeModal();
      await go('result'); await tick(); await tick(); await tick();
      return [jobs().length, el('#mask').classList.contains('on')];""",
                    state={**STALE_STATE, "manual": MANUAL_ON}, result={**STALE_RESULT, "manual": MANUAL_ON})
    assert out == [0, False]


def test_entering_step_five_from_another_step_still_auto_reselects():
    n = in_switch("""await go('browse'); staleNow = true; const before = jobs().length;
      await go('result'); await tick(); await tick(); await tick(); return jobs().length - before;""")
    assert n == 1


def test_finished_auto_job_leaves_step_fresh_and_never_starts_a_second():
    out = in_switch("""staleNow = true; applyWizard(%s); const before = jobs().length;
      await autoReselectOnEnter(resultGen, state.project); await tick();
      staleNow = false; await onResultJobDone('select'); await tick(); await tick();
      return [jobs().length - before, stepOf('result').status];""" % js(STALE_WIZARD))
    assert out[0] == 1 and out[1] != "stale"


def test_disabled_preview_button_is_enabled_again_once_clips_arrive():
    out = in_simple("""const empty = el('#rPvNote').innerHTML;
      state.shots = %s.map(s => ({...s})); paintResult(true);
      return [empty, el('#rPvNote').innerHTML];""" % js(SHOTS), state={"shots": []})
    assert " disabled" in out[0] and " disabled" not in out[1] and "data-starts-job" in out[1]


SETTINGS_SWITCH = ("__respond = (m, p) => { if(m === 'GET' && calls.some(c => c.path === '/api/project/settings')){ "
                   "if(p.startsWith('/api/state')) return [200, %s]; if(p.startsWith('/api/result')) return [200, %s]; } "
                   "return respond(m, p); };")


def to_simple_script(extra=""):
    return ("""await openProjectSettings(); el('#psMin').value = '2'; el('#psSec').value = '55';
      el('input[name="psMode"]:checked').value = 'simple'; """ + extra + """
      await saveProjectSettings(); await tick(); await tick(); await tick();""")


def test_switching_to_simple_while_on_step_five_auto_starts_the_reselect():
    stale_state = {**RSTATE, **simple_state(), "wizard": STALE_WIZARD}
    stale_result = {**RESULT, **simple_result(), "wizard": STALE_WIZARD}
    out = in_result(to_simple_script() + "return [jobs(), state.view];",
                    {"POST /api/project/settings": {"ok": True, "project": SIMPLE_PROJECT, "wizard": STALE_WIZARD}},
                    setup=SETTINGS_SWITCH % (js(stale_state), js(stale_result)))
    assert out == [[{"project": "新项目", "task": "select", "manual": "replace"}], "result"]


def test_switching_to_simple_while_on_step_four_flushes_the_draft_and_lands_on_the_next_step():
    fresh_state = {**RSTATE, **simple_state()}
    out = in_result("""let flushed = 0; const orig = flushCriteriaDraft; flushCriteriaDraft = (...a) => { flushed += 1; return orig(...a); };
      state.view = 'criteria';""" + to_simple_script() + "return [flushed, state.view];",
                    {"POST /api/project/settings": {"ok": True, "project": SIMPLE_PROJECT, "wizard": simple_wizard()}},
                    setup=SETTINGS_SWITCH % (js(fresh_state), js({**RESULT, **simple_result()})))
    assert out == [1, "result"]


def test_settings_save_that_moves_the_view_off_step_five_runs_the_leave_path():
    locked = result_wizard(result=("locked", "先在「③ 看素材」…", None))
    locked["next"] = "browse"
    out = in_result("""let left = 0; const orig = leaveResult; leaveResult = () => { left += 1; return orig(); };
      await openProjectSettings(); el('#psMin').value = '2'; el('#psSec').value = '55';
      await saveProjectSettings(); return [left, state.view];""",
                    {"POST /api/project/settings": {"ok": True, "project": RSTATE["project"], "wizard": locked}})
    assert out == [1, "browse"]


def test_mode_switch_shows_one_combined_toast_with_the_stale_note():
    stale_state = {**RSTATE, **simple_state(), "wizard": STALE_WIZARD}
    toast = in_result(to_simple_script("el('#psMin').value = '4';") + "return el('#toast').textContent;",
                      {"POST /api/project/settings": {"ok": True, "project": SIMPLE_PROJECT, "wizard": STALE_WIZARD}},
                      setup=SETTINGS_SWITCH % (js(stale_state), js({**RESULT, **simple_result(), "wizard": STALE_WIZARD})))
    assert "重新选段" in toast and "已切换出片模式" in toast
