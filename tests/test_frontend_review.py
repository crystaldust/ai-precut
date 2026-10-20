"""M13b 代码审查后的回归（node vm）：跨项目任务、未保存分镜表、未处理的异步错误、播放器与定时器、页内填 Key 等。"""
import json
from pathlib import Path

import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_fixtures import (DONE_WIZARD, FILL_NEW, NEW_ROUTES, NEW_STATE, NEW_WIZARD, READY_ROUTES, READY_STATE,
                         config, in_project, progress)
from fe_harness import NODE, run_app, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")
STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"


def js(v):
    return json.dumps(v, ensure_ascii=False)


# ---------------------------------------------------------------- HIGH-1：别的项目的任务完成
def test_job_done_for_other_project_does_not_navigate_or_open_dialog_here():
    out = in_project("""await go('analyze');
      state.data = {...state.data, selection: {over_target: true, must_keep_total: 300, suggested_target: 300}};
      onJobDone({project: '别的项目', log: [], status: 'done'}, 'prepare');
      await runTimers(); await runTimers();
      return [state.view, el('#mask').classList.contains('on'), el('#toast').textContent];""")
    view, modal, toast_text = out
    assert view == "analyze" and modal is False
    assert "别的项目" in toast_text and "分析完成" in toast_text


def test_job_done_for_current_project_still_navigates():
    out = in_project("""await go('analyze'); state.view = 'analyze';
      onJobDone({project: '新项目', log: [], status: 'done'}, 'prepare');
      await runTimers(); await runTimers(); return state.view;""",
                     {"GET /api/state": {**NEW_STATE, "wizard": DONE_WIZARD}})
    assert out == "browse"


# ---------------------------------------------------------------- HIGH-2：不覆盖未保存的分镜表改动
def ready_script(body):
    server_js = """
      let server = [{id:'sh01', in:1, out:4, sub:'旧', note:''}];
      __respond = (m, p, b) => {
        if (m === 'POST' && p.startsWith('/api/shots')) { server = b.shots; return [200, {ok: true}]; }
        if (m === 'GET' && p.startsWith('/api/state')) { if (typeof onState === 'function') onState();
          return [200, {...READY, shots: server}]; }
        return respond(m, p);
      };"""
    return ("(async () => { const READY = " + js(READY_STATE) + ";" + server_js
            + "await selectProject('新项目'); await go('result');" + body + "})()")


def test_refresh_inside_debounce_window_saves_first_then_keeps_edit():
    out = run_app(ready_script("""
      state.shots[0].sub = '改了'; scheduleSave();
      await refreshOrWarn();
      const order = calls.filter(c => c.path.startsWith('/api/shots') || c.path.startsWith('/api/state'))
                         .map(c => c.method + c.path.split('?')[0]);
      return [order.slice(-2), state.shots[0].sub];"""), routes=READY_ROUTES)
    assert out == [["POST/api/shots", "GET/api/state"], "改了"]


def test_edit_made_while_state_is_in_flight_is_not_clobbered():
    out = run_app(ready_script("""
      window.onState = () => { state.shots[0].sub = '中途改'; scheduleSave(); };
      await refreshOrWarn();
      return state.shots[0].sub;"""), routes=READY_ROUTES)
    assert out == "中途改"


# ---------------------------------------------------------------- HIGH-3：异步动作不能悄悄失败
def test_dispatcher_toasts_rejected_async_actions():
    out = run_app("""(async () => {
      ACTIONS.boom = async () => { throw new Error('炸了 <b>'); };
      click(node({'data-act': 'boom'})); await tick(); await tick();
      return el('#toast').textContent; })()""")
    assert out == "炸了 <b>"


def test_dispatcher_does_not_toast_for_sync_or_resolved_actions():
    out = run_app("""(async () => {
      let n = 0; ACTIONS.ok = async () => { n++; return 1; }; ACTIONS.plain = () => { n++; };
      click(node({'data-act': 'ok'})); click(node({'data-act': 'plain'})); await tick();
      return [n, el('#toast').textContent]; })()""")
    assert out == [2, ""]


def test_click_on_child_reaches_closest_action_through_delegation():
    out = run_app("""(async () => {
      state.project = 'p'; state.data = {project: {name: 'p'}, wizard: %s, shots: []}; state.view = 'analyze';
      const btn = node({'data-act': 'go', 'data-step': 'browse'}); const label = node({}, btn);
      click(label); await tick(); return state.view; })()""" % js(DONE_WIZARD))
    assert out == "browse"


def test_open_new_failure_toasts_instead_of_rejecting():
    out = run_app("(async () => { await openNew(); return [el('#toast').textContent, el('#mask').classList.contains('on')]; })()",
                  routes={"GET /api/presets": [500, {"error": "预设读不出来"}]})
    assert out == ["预设读不出来", False]


def test_pick_file_failure_toasts():
    out = run_app("(async () => { await pickFile(); return el('#toast').textContent; })()",
                  routes={"POST /api/pick": [500, {"error": "选择器打不开"}]})
    assert out == "选择器打不开"


def test_create_still_selects_new_project_when_project_list_fails_to_load():
    out = run_app("(async () => {" + FILL_NEW + """
      await createAndAnalyze();
      return [state.project, calls.some(c => c.path === '/api/job')]; })()""",
                  routes={**NEW_ROUTES, "GET /api/projects": [500, {"error": "项目列表读不出来"}]})
    assert out == ["新项目", True]


def test_create_double_submit_posts_new_once():
    out = run_app("(async () => {" + FILL_NEW + """
      const a = createAndAnalyze(); const b = createAndAnalyze(); await Promise.all([a, b]);
      return calls.filter(c => c.path === '/api/new').length; })()""", routes=NEW_ROUTES)
    assert out == 1


# ---------------------------------------------------------------- MEDIUM (a)(b)：播放器条与试听定时器
def test_player_bar_is_not_rebuilt_on_every_render():
    out = run_app("""(async () => { await selectProject('新项目'); await go('result');
      el('#shotbar').innerHTML = 'SENTINEL'; renderView(); renderView();
      return el('#shotbar').innerHTML; })()""", routes=READY_ROUTES)
    assert out == "SENTINEL"


def test_play_selection_clears_previous_timer_and_project_switch_stops_it():
    out = run_app("""(async () => { await selectProject('新项目'); await go('result');
      state.sel = 0; el('#pv2').currentTime = 0;
      playSel(); playSel();
      const two = intervals.map(i => i.cleared);
      await selectProject('新项目');
      return [two, intervals.map(i => i.cleared)]; })()""", routes=READY_ROUTES)
    assert out == [[True, False], [True, True]]


# ---------------------------------------------------------------- MEDIUM (c)：项目设置遇到切项目
def test_project_settings_open_ignored_if_project_switched_meanwhile():
    out = in_project("""__respond = (m, p) => { if (p.startsWith('/api/presets')) state.project = '别的项目'; return respond(m, p); };
      await openProjectSettings(); return el('#mask').classList.contains('on');""")
    assert out is False


def test_project_settings_save_after_switch_closes_modal_and_leaves_state_alone():
    out = in_project("""await openProjectSettings();
      __respond = (m, p) => { if (p.startsWith('/api/project/settings')) state.project = '别的项目'; return respond(m, p); };
      const before = state.data.project.title; await saveProjectSettings();
      return [el('#mask').classList.contains('on'), state.data.project.title === before];""",
                     {"POST /api/project/settings": {"ok": True, "project": {"name": "新项目", "title": "改了"},
                                                      "wizard": DONE_WIZARD}})
    assert out == [False, True]


def test_project_settings_save_moves_view_off_a_step_that_became_locked():
    locked = wizard(analyze="stale", browse=("locked", "先完成「② 分析」", None))
    locked["next"] = "analyze"
    out = in_project("""await go('analyze'); state.view = 'browse';
      await openProjectSettings(); await saveProjectSettings(); return state.view;""",
                     {"POST /api/project/settings": {"ok": True, "project": NEW_STATE["project"], "wizard": locked}})
    assert out == "analyze"


# ---------------------------------------------------------------- MEDIUM (d)(e)(f)
def test_analysis_block_dropped_if_project_changes_while_loading_config():
    out = run_app("""(async () => { state.project = 'p'; state.data = {project: {name: 'p'}, wizard: %s, shots: []};
      __respond = (m, p) => { if (p === '/api/config') state.project = '别的'; return respond(m, p); };
      await showAnalysisBlock({message: 'x', data: {need: 'keys', missing: ['deepseek']}});
      return state.block; })()""" % js(NEW_WIZARD),
                  routes={"GET /api/config": config(True, True, False)})
    assert out is None


def test_analysis_poll_error_is_visible_even_with_previous_data():
    html = run_app("""(() => { state.project = 'p'; analysisUi.project = 'p'; analysisUi.data = %s;
      analysisUi.error = '连接被拒绝 <b>'; return viewAnalyze(); })()""" % js(progress(done=3, running=3)))
    assert "进度暂时读不到" in html and "连接被拒绝 &lt;b&gt;" in html and "读取素材" in html


def test_prefs_load_failure_is_visible():
    out = run_app("(async () => { await loadPrefs(); return el('#toast').textContent; })()",
                  routes={"GET /api/prefs": [500, {"error": "配置目录不可读"}]})
    assert "配置目录不可读" in out


def test_project_settings_list_reload_failure_is_visible():
    out = in_project("""await openProjectSettings(); await saveProjectSettings(); await tick(); await tick();
      return el('#toast').textContent;""",
                     {"POST /api/project/settings": {"ok": True, "project": NEW_STATE["project"], "wizard": NEW_WIZARD},
                      "GET /api/projects": [500, {"error": "项目列表读不出来"}]})
    assert out == "项目列表读不出来"


# ---------------------------------------------------------------- MEDIUM (g)：页内填 Key 不吞另一个输入框
def test_saving_one_key_keeps_what_was_typed_in_the_other_input():
    out = run_app("""(async () => { checkFirstRun(); await tick();
      el('#key_mediakit').value = 'AKLTnew12345678'; el('#key_deepseek').value = 'sk-halftyped';
      await act('saveKey', {provider: 'mediakit'}); await tick();
      return [el('#key_mediakit').value, el('#key_deepseek').value]; })()""",
                  routes={"GET /api/config": config(True, False, False), "POST /api/config/key": config(True, True, False)})
    assert out == ["", "sk-halftyped"]


def test_analysis_block_keeps_other_input_too():
    out = in_project("""await startAnalysis(); el('#key_deepseek').value = 'sk-halftyped';
      el('#key_mediakit').value = 'AKLTnew12345678';
      await act('saveKey', {provider: 'mediakit'}); await tick();
      return el('#key_deepseek').value;""",
                     {"POST /api/job": [409, {"error": "缺 Key", "need": "keys", "missing": ["mediakit", "deepseek"]}],
                      "GET /api/config": config(True, False, False), "POST /api/config/key": config(True, True, False)})
    assert out == "sk-halftyped"


# ---------------------------------------------------------------- 切换竞态、LOW
def test_double_click_a_then_b_ends_on_b_with_b_view():
    a = {**NEW_STATE, "project": {**NEW_STATE["project"], "name": "A", "title": "A"}}
    b = {**NEW_STATE, "wizard": DONE_WIZARD, "project": {**NEW_STATE["project"], "name": "B", "title": "B"}}
    out = run_app("""(async () => {
      __respond = (m, p) => p.includes('project=A') ? [200, %s] : (p.includes('project=B') ? [200, %s] : respond(m, p));
      const x = selectProject('A'); const y = selectProject('B'); await Promise.all([x, y]); await tick();
      return [state.project, state.view, el('#title').textContent]; })()""" % (js(a), js(b)),
                  routes={"GET /api/analysis": {"steps": []}})
    assert out == ["B", "criteria", "B"]


def test_open_subpage_only_accepts_known_pages():
    out = run_app("(async () => { state.project = 'p'; await openSubpage('../evil'); await openSubpage('calibrate');"
                  " return calls.length; })()")
    assert out == 0


def test_unused_copy_constants_removed():
    text = "\n".join(p.read_text(encoding="utf-8") for p in STATIC.glob("*.js"))
    for name in ("COPY_ABOUT_BUTTON", "COPY_DIAG_BUTTON", "COPY_KEYS_MISSING_HINT", "COPY_ANALYZE_TITLE", "COPY_MORE"):
        assert name not in text


def test_titles_are_named_constants_not_string_surgery():
    form = (STATIC / "project-form.js").read_text(encoding="utf-8")
    assert ".replace('（可跳过）'" not in form and "COPY_SETTINGS_PREFS_TITLE" in form
    analyze = (STATIC / "step-analyze.js").read_text(encoding="utf-8")
    assert "COPY_ANALYZE_RUNNING_ELAPSED" in analyze
