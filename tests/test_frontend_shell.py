"""M13b 向导外壳的前端行为（node vm）：步骤条、横幅、底部导航、更多菜单、项目栏、打开项目、首次打开闸门。"""
import json

import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_steps_locked_done_stale_current_markup():
    w = wizard(analyze=("stale", "剪辑偏好或预设改过了 · 重新分析", "reanalyze"),
               browse="done", criteria="available",
               result=("locked", "先完成「④ 定标准」", None), export=("locked", "先完成「④ 定标准」", None))
    html = run_app(f"renderSteps({js(w)}, 'browse')")
    assert html.count('data-act="go"') == 6
    buttons = html.split("</button>")
    result = buttons[4]  # ⑤ 看结果
    assert 'data-step="result"' in result and 'aria-disabled="true"' in result
    assert 'title="先完成「④ 定标准」"' in result and "✓" not in result
    done = html.split("</button>")[0]  # ① 新建
    assert "✓" in done and "st-done" in done
    stale = html.split("</button>")[1]  # ② 分析
    assert "⚠" in stale and "stale" in stale and "剪辑偏好或预设改过了" in stale
    browse = html.split("</button>")[2]
    assert "current" in browse
    assert "current" not in html.split("</button>")[3]


def test_steps_escape_label_and_hint():
    w = wizard(result=("locked", '"><img src=x>', None))
    w["steps"][4]["label"] = "<b>x</b>"
    html = run_app(f"renderSteps({js(w)}, 'browse')")
    assert "<img" not in html and "<b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


def test_clicking_locked_step_toasts_hint_and_keeps_view():
    out = run_app(f"""(async () => {{
      state.project = 'p1'; state.data = {{project: {{name:'p1'}}, wizard: {W}, shots: []}}; state.view = 'browse';
      await go('result');
      return [state.view, el('#toast').textContent];
    }})()""")
    assert out == ["browse", "先完成「④ 定标准」"]


def test_go_to_available_step_switches_view_and_renders_stage():
    out = run_app(f"""(async () => {{
      state.project = 'p1'; state.data = {{project: {{name:'p1'}}, wizard: {W}, shots: []}}; state.view = 'browse';
      await go('criteria');
      return [state.view, el('#stage').innerHTML.length > 0, el('#steps').innerHTML.includes('current')];
    }})()""")
    assert out == ["criteria", True, True]


def test_new_step_opens_project_settings_instead_of_switching():
    out = run_app(f"""(async () => {{
      state.project = 'p1'; state.data = {{project: {{name:'p1', preset:'a'}}, wizard: {W}, shots: []}}; state.view = 'browse';
      let opened = 0; openProjectSettings = () => {{ opened++; }};
      await go('new');
      return [state.view, opened];
    }})()""")
    assert out == ["browse", 1]


def test_banner_stale_result_has_reselect_button_and_escapes():
    step = {"key": "result", "status": "stale", "banner": "<i>素材标记改过了</i> · 重新选段",
            "action": "reselect"}
    html = run_app(f"bannerHtml({js(step)})")
    assert 'data-act="reselect"' in html and "data-starts-job" in html
    assert "<i>" not in html and "&lt;i&gt;素材标记改过了&lt;/i&gt;" in html
    assert "重新选段</button>" in html


def test_banner_reanalyze_button_and_note():
    step = {"key": "analyze", "status": "stale", "action": "reanalyze",
            "banner": "剪辑偏好或预设改过了 · 重新分析（只重跑 AI 理解及之后的环节，会重新调用 AI）"}
    html = run_app(f"bannerHtml({js(step)})")
    assert 'data-act="reanalyze"' in html and "重新分析</button>" in html
    assert "只重跑 AI 理解及之后的环节" in html


def test_banner_without_action_is_plain_note():
    step = {"key": "criteria", "status": "done", "banner": "这个项目在改版前已出过片", "action": None}
    html = run_app(f"bannerHtml({js(step)})")
    assert "改版前已出过片" in html and "<button" not in html


def test_banner_empty_when_nothing_to_say():
    assert run_app("bannerHtml({key:'browse', status:'done', banner:null, action:null})") == ""


def test_banner_shows_only_for_viewed_step_and_manual_shots_line():
    w = wizard(result=("stale", "素材标记改过了 · 重新选段", "reselect"), criteria="done")
    out = run_app(f"""(() => {{
      state.project = 'p1'; state.data = {{project: {{name:'p1'}}, wizard: {js(w)}, shots: [{{id:'sh01'}}],
        shots_from_selection: false}};
      state.shots = [{{id:'sh01'}}];
      state.view = 'browse'; renderBanner(); const other = el('#banner').innerHTML;
      state.view = 'result'; renderBanner();
      return [other, el('#banner').innerHTML];
    }})()""")
    assert out[0] == ""
    assert "素材标记改过了" in out[1] and "你手动改过分镜表" in out[1]


def test_nav_browse_to_criteria_enabled():
    nav = run_app(f"navModel({W}, 'browse')")
    assert nav["next"] == {"key": "criteria", "label": "去定标准", "enabled": True}
    assert nav["prev"]["key"] == "analyze" and nav["prev"]["enabled"] is True


def test_nav_analyze_next_disabled_until_analysis_done():
    w = wizard(analyze="available", browse=("locked", "先完成「② 分析」", None),
               criteria=("locked", "先完成「② 分析」", None))
    nav = run_app(f"navModel({js(w)}, 'analyze')")
    assert nav["prev"] is None
    assert nav["next"]["enabled"] is False


def test_nav_last_step_has_no_next():
    w = wizard(criteria="done", result="available", export="available")
    nav = run_app(f"navModel({js(w)}, 'export')")
    assert nav["next"] is None and nav["prev"]["key"] == "result"


def test_render_nav_markup_uses_go_action():
    html = run_app(f"renderNav({W}, 'browse')")
    assert 'data-act="go" data-step="analyze"' in html and "← 上一步" in html
    assert 'data-act="go" data-step="criteria"' in html and "下一步：去定标准 →" in html


def test_more_menu_without_project_has_four_items():
    labels = run_app("moreItems(false).map(i => i.label)")
    assert labels == ["设置 · API Key", "快捷键", "导出诊断包", "关于 / 第三方许可"]


def test_more_menu_with_project_has_seven_items_in_spec_order():
    labels = run_app("moreItems(true).map(i => i.label)")
    assert labels == ["项目设置", "打开项目文件夹", "清理缓存", "设置 · API Key", "快捷键",
                      "导出诊断包", "关于 / 第三方许可"]


def test_more_menu_toggle_and_item_closes_menu_then_runs():
    out = run_app("""(async () => {
      state.project = 'p1';
      let ran = 0; ACTIONS.openFolder = () => { ran++; };
      toggleMore(); const open = el('#moreMenu').classList.contains('on'); const html = el('#moreMenu').innerHTML;
      moreItem('folder');
      return [open, el('#moreMenu').classList.contains('on'), ran, html.includes('data-act="moreItem"')];
    })()""")
    assert out == [True, False, 1, True]


def test_shortcuts_entry_opens_the_key_editor():
    out = run_app("openShortcuts(); [el('#modalTitle').textContent, el('#modalBody').innerHTML.includes('recordKey')]")
    assert out[0] == "快捷键" and out[1] is True


def test_render_projects_shows_name_and_current_step_escaped():
    html = run_app(f"state.project = 'p2'; renderProjects({js(PROJECTS)})")
    assert "&lt;i&gt;片&lt;/i&gt;" in html and "<i>" not in html
    assert "④ 定标准" in html
    assert 'data-act="selectProject" data-name="a&lt;b"' in html
    assert 'class="proj on" data-act="selectProject" data-name="p2"' in html  # 当前项目高亮


def test_rail_modes():
    out = run_app("[railMode(false, false, false), railMode(true, false, false), railMode(true, false, true),"
                  " railMode(true, true, false)]")
    assert out == ["wide", "narrow", "float", "wide"]


def test_set_rail_applies_classes():
    out = run_app("""(() => {
      state.project = 'p1'; state.pinned = false; state.railOpen = false; setRail();
      const narrow = [el('#app').classList.contains('in-project'), el('#rail').classList.contains('open')];
      state.railOpen = true; setRail();
      const open = el('#rail').classList.contains('open');
      state.pinned = true; setRail();
      return [narrow, open, el('#app').classList.contains('pinned')];
    })()""")
    assert out == [[True, False], True, True]


def test_hover_opens_and_leave_closes_unless_pinned():
    out = run_app("""(() => {
      state.project = 'p1'; initRail();
      fire('#rail', 'mouseenter'); const a = state.railOpen;
      fire('#rail', 'mouseleave'); const b = state.railOpen;
      state.pinned = true; fire('#rail', 'mouseenter'); fire('#rail', 'mouseleave');
      return [a, b, state.pinned];
    })()""")
    assert out == [True, False, True]


def test_toggle_pin_saves_to_prefs_not_local_storage():
    out = run_app("""(async () => {
      state.project = 'p1'; await togglePin();
      return [state.pinned, calls.filter(c => c.path === '/api/prefs').map(c => c.body)];
    })()""", routes={"POST /api/prefs": {"sidebar_pinned": True, "shortcuts": {}}})
    assert out == [True, [{"sidebar_pinned": True}]]


def test_toggle_pin_rolls_back_when_save_fails():
    out = run_app("""(async () => {
      state.project = 'p1'; await togglePin();
      return [state.pinned, el('#toast').textContent];
    })()""", routes={"POST /api/prefs": [500, {"error": "界面设置保存失败"}]})
    assert out == [False, "界面设置保存失败"]


def test_load_prefs_restores_pin():
    out = run_app("(async () => { await loadPrefs(); return state.pinned; })()",
                  routes={"GET /api/prefs": {"sidebar_pinned": True}})
    assert out is True


def test_select_project_lands_on_next_step():
    state_payload = {"project": {"name": "p1", "title": "片名", "preset": "x", "platform": "douyin"},
                     "wizard": json.loads(W), "shots": [], "warnings": [], "versions": [], "segments": [],
                     "job": None, "busy": None}
    out = run_app("(async () => { await selectProject('p1'); return [state.project, state.view,"
                  " el('#title').textContent]; })()",
                  routes={"GET /api/state": state_payload, "GET /api/analysis": {"steps": []}})
    assert out == ["p1", "criteria", "片名"]


def test_select_project_failure_clears_steps_and_shows_error_card():
    out = run_app("""(async () => {
      state.project = 'old'; el('#steps').innerHTML = 'x';
      await selectProject('<b>bad</b>');
      return [state.project, el('#steps').innerHTML, el('#stage').innerHTML, el('#nav').innerHTML,
              el('#app').classList.contains('in-project')];
    })()""", routes={"GET /api/state": [409, {"error": "project.json 损坏 <script>"}]})
    assert out[0] is None and out[1] == "" and out[3] == ""
    assert "project.json 损坏 &lt;script&gt;" in out[2] and "<script>" not in out[2]
    assert out[4] is False


def test_leaving_result_flushes_pending_shot_save():
    out = run_app(f"""(async () => {{
      const w = {js(wizard(criteria="done", result="available", export="available"))};
      state.project = 'p1'; state.data = {{project: {{name:'p1'}}, wizard: w, shots: [{{id:'sh01', in:0, out:3, sub:''}}]}};
      state.shots = [{{id:'sh01', in:0, out:3, sub:''}}]; state.view = 'result';
      scheduleSave();
      await go('browse');
      return calls.filter(c => c.path.startsWith('/api/shots')).length;
    }})()""", routes={"POST /api/shots": {"ok": True}})
    assert out == 1


def test_refresh_keeps_view_unless_it_became_locked():
    state_payload = {"project": {"name": "p1", "title": "p1"}, "wizard": json.loads(W), "shots": [],
                     "warnings": [], "versions": [], "segments": [], "job": None, "busy": None}
    out = run_app("""(async () => {
      await selectProject('p1'); await go('browse');
      await refresh('p1'); const kept = state.view;
      state.view = 'result'; await refresh('p1');
      return [kept, state.view];
    })()""", routes={"GET /api/state": state_payload, "GET /api/analysis": {"steps": []}})
    assert out == ["browse", "criteria"]


def test_first_run_without_consent_shows_disclosure_in_stage_without_skip():
    out = run_app("""(async () => {
      checkFirstRun(); await tick();
      const html = el('#stage').innerHTML;
      return [html, el('#app').classList.contains('first-run'), el('#mask').classList.contains('on')];
    })()""", routes={"GET /api/config": config(False, False, False)})
    html, gate, modal = out
    for text in ("16kHz", "火山引擎", "DeepSeek", "不会离开这台电脑", "我知道了，继续"):
        assert text in html
    assert "暂不使用" not in html and gate is True and modal is False


def test_first_run_continue_records_consent_then_shows_two_key_rows():
    out = run_app("""(async () => {
      checkFirstRun(); await tick();
      await act('firstRunConsent'); await tick();
      const html = el('#stage').innerHTML;
      return [calls.filter(c => c.method === 'POST').map(c => c.path), html];
    })()""", routes={"GET /api/config": config(False, False, False),
                     "POST /api/config/consent": config(True, False, False)})
    posts, html = out
    assert posts == ["/api/config/consent"]
    assert 'id="key_mediakit"' in html and 'id="key_deepseek"' in html and 'type="password"' in html
    assert "进入剪辑台" in html and "disabled" in html.split("进入剪辑台")[0].split("<button")[-1]


def test_first_run_enter_disabled_until_both_keys_configured():
    one = run_app("""(async () => {
      checkFirstRun(); await tick();
      return el('#stage').innerHTML;
    })()""", routes={"GET /api/config": config(True, True, False)})
    enter = one.split("进入剪辑台")[0].split("<button")[-1]
    assert "disabled" in enter
    both = run_app("""(async () => {
      checkFirstRun(); await tick();
      await act('firstRunConsent'); await tick();
      return el('#stage').innerHTML;
    })()""", routes={"GET /api/config": config(False, True, True),
                     "POST /api/config/consent": config(True, True, True)})
    assert "disabled" not in both.split("进入剪辑台")[0].split("<button")[-1]


def test_first_run_already_complete_passes_silently_including_env_keys():
    out = run_app("""(async () => {
      const ok = await checkFirstRun();
      return [ok, el('#app').classList.contains('first-run'), el('#stage').innerHTML];
    })()""", routes={"GET /api/config": config(True, True, True, source="env")})
    assert out == [True, False, ""]


def test_first_run_enter_resolves_and_leaves_gate():
    out = run_app("""(async () => {
      const p = checkFirstRun(); await tick();
      await act('firstRunConsent'); await tick();
      await act('firstRunEnter');
      return [await p, el('#app').classList.contains('first-run')];
    })()""", routes={"GET /api/config": config(False, True, True),
                     "POST /api/config/consent": config(True, True, True, source="env")})
    assert out == [True, False]


def test_first_run_enter_ignored_while_key_missing():
    out = run_app("""(async () => {
      let done = false;
      checkFirstRun().then(() => { done = true; }); await tick();
      await act('firstRunEnter'); await tick();
      return [done, el('#app').classList.contains('first-run')];
    })()""", routes={"GET /api/config": config(True, True, False)})
    assert out == [False, True]


def test_first_run_saving_a_key_redraws_the_gate_instead_of_opening_settings_modal():
    out = run_app("""(async () => {
      checkFirstRun(); await tick();
      el('#key_deepseek').value = ' sk-secret-1234 ';
      await act('saveKey', {provider: 'deepseek'}); await tick();
      return [el('#key_deepseek').value, el('#mask').classList.contains('on'), el('#stage').innerHTML,
              JSON.stringify(calls.filter(c => c.path === '/api/config/key'))];
    })()""", routes={"GET /api/config": config(True, True, False),
                     "POST /api/config/key": config(True, True, True)})
    assert out[0] == "" and out[1] is False
    assert "disabled" not in out[2].split("进入剪辑台")[0].split("<button")[-1]
    assert "sk-secret-1234" not in out[2]


def test_first_run_service_unreachable_shows_retry_and_does_not_enter():
    out = run_app("""(async () => {
      let done = false;
      checkFirstRun().then(() => { done = true; }); await tick();
      const html = el('#stage').innerHTML, before = done;
      __fail = null; __respond = () => [200, %s];
      await act('firstRunRetry'); await tick();
      return [html, before, done];
    })()""" % json.dumps(config(True, True, True)),
                  routes={}, setup="__fail = '连接被拒绝'; __respond = null;")
    html, before, after = out
    assert "剪辑台服务没有响应" in html and 'data-act="firstRunRetry"' in html and "连接被拒绝" in html
    assert before is False and after is True  # 重试成功、配置齐全才放行


def test_first_run_unreachable_message_is_escaped():
    html = run_app("(async () => { checkFirstRun(); await tick(); return el('#stage').innerHTML; })()",
                   setup="__fail = '<img src=x onerror=1>';")
    assert "<img" not in html and "&lt;img" in html


def test_boot_without_projects_shows_welcome_with_big_new_button():
    out = run_app("(async () => { await boot(); return [el('#stage').innerHTML, state.project]; })()",
                  routes={"GET /api/config": config(True, True, True), "GET /api/prefs": {"sidebar_pinned": False},
                          "GET /api/projects": {"projects": [], "stale_job": None}})
    html, project = out
    assert 'data-act="openNew"' in html and "新建项目" in html and project is None


def test_boot_with_projects_waits_for_choice():
    out = run_app("(async () => { await boot(); return [el('#stage').innerHTML, el('#projects').innerHTML]; })()",
                  routes={"GET /api/config": config(True, True, True), "GET /api/prefs": {"sidebar_pinned": False},
                          "GET /api/projects": {"projects": [{"name": "p1", "title": "T", "versions": [],
                                                              "step": {"n": 2, "label": "分析"}}], "stale_job": None}})
    assert "选择左边的项目" in out[0] and "② 分析" in out[1]
