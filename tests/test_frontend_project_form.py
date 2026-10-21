"""M13b ① 新建弹窗与项目设置（node vm）。"""
import json

import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_new_modal_has_two_sections_prefs_collapsed_with_info_default():
    html = run_app("(async () => { await openNew(); return el('#modalBody').innerHTML; })()", routes=NEW_ROUTES)
    assert "素材与成片" in html and "剪辑偏好（可跳过）" in html
    assert '<details class="prefs" id="npPrefs">' in html  # 没有 open 属性 = 默认折叠
    assert 'name="npTone" value="info" checked' in html and 'value="balanced"' not in html
    assert "必须保留的原话（每行一句，最多 3 句）" in html and "创建并开始分析" in html
    assert "&lt;b&gt;" in html and "<b>" not in html  # 预设警告过 esc
    assert html.index("npMin") < html.index("npPreset")  # KI-92：时长在预设上面


def test_read_calibration_cleans_blank_lines_and_rejects_more_than_three():
    out = run_app("""(() => {
      el('input[name="npTone"]:checked').value = 'emotion';
      el('#npAudience').value = ' 家长 ';
      el('#npMust').value = '第一句\\n\\n  第二句  \\n第三句；';
      const ok = readCalibration('np');
      el('#npMust').value = 'a\\nb\\nc\\nd';
      const bad = readCalibration('np');
      return [ok, bad, el('#toast').textContent];
    })()""")
    assert out[0] == {"tone": "emotion", "audience": "家长", "must_lines": "第一句\n第二句\n第三句"}
    assert out[1] is None and out[2] == "必须保留的原话最多 3 句"


def test_create_posts_new_with_calibration_then_starts_analysis_and_lands_on_step_two():
    out = run_app("""(async () => {""" + FILL_NEW + """
      await createAndAnalyze();
      const order = calls.filter(c => c.method === 'POST').map(c => c.path);
      return [order, calls.find(c => c.path === '/api/new').body, calls.find(c => c.path === '/api/job').body,
              state.project, state.view, el('#mask').classList.contains('on')];
    })()""", routes=NEW_ROUTES)
    order, new_body, job_body, project, view, modal = out
    assert order == ["/api/new", "/api/job"]
    assert new_body == {"material": "/m/a.mp4", "name": "新项目", "title": "片名", "preset": "纪实3min",
                        "target": 180, "calibration": {"tone": "info", "audience": "", "must_lines": ""}}
    assert job_body == {"project": "新项目", "task": "prepare"}
    assert (project, view, modal) == ("新项目", "analyze", False)


def test_create_failure_keeps_modal_shows_reason_and_starts_nothing():
    out = run_app("""(async () => {""" + FILL_NEW + """
      showModal('新建项目', 'x');
      await createAndAnalyze();
      return [el('#mask').classList.contains('on'), el('#toast').textContent,
              calls.filter(c => c.path === '/api/job').length, state.project];
    })()""", routes={**NEW_ROUTES, "POST /api/new": [400, {"error": "项目已存在"}]})
    assert out == [True, "项目已存在", 0, None]


def test_create_rejects_too_many_lines_without_posting():
    out = run_app("""(async () => {""" + FILL_NEW + """
      el('#npMust').value = '1\\n2\\n3\\n4';
      await createAndAnalyze();
      return [calls.filter(c => c.method === 'POST').length, el('#toast').textContent];
    })()""", routes=NEW_ROUTES)
    assert out == [0, "必须保留的原话最多 3 句"]


@pytest.mark.parametrize("field,toast_text", [("#npPath", "先选素材"), ("#npName", "填个项目名")])
def test_create_requires_material_and_name(field, toast_text):
    out = run_app("(async () => {" + FILL_NEW + f"el({field!r}).value = ''; await createAndAnalyze();"
                  " return [calls.length, el('#toast').textContent]; })()", routes=NEW_ROUTES)
    assert out == [0, toast_text]


def test_create_with_missing_keys_stays_on_analysis_page_without_settings_modal():
    cfg = {"consent": True, "providers": [provider("mediakit", True), provider("deepseek", False)]}
    out = run_app("""(async () => {""" + FILL_NEW + """
      await createAndAnalyze();
      return [state.view, state.block && state.block.need, el('#mask').classList.contains('on'),
              el('#stage').innerHTML];
    })()""", routes={**NEW_ROUTES, "GET /api/config": cfg,
                     "POST /api/job": [409, {"error": "还没有填写 API Key：DeepSeek", "need": "keys",
                                             "missing": ["deepseek"]}]})
    view, need, modal, html = out
    assert (view, need, modal) == ("analyze", "keys", False)
    assert 'id="key_deepseek"' in html and "还没有填写 API Key" in html
    assert "disabled" in html.split("填好了，继续分析")[0].split("<button")[-1]


def test_project_settings_prefills_and_offers_legacy_balanced_only_when_current():
    cal_state = {**NEW_STATE, "project": {**NEW_STATE["project"], "title": "<b>片</b>",
                                          "calibration": {"tone": "balanced", "audience": "同行", "must_lines": "甲\n乙"}}}
    html = run_app("(async () => { await selectProject('新项目'); await openProjectSettings(); return el('#modalBody').innerHTML; })()",
                   routes={**NEW_ROUTES, "GET /api/state": cal_state})
    assert "&lt;b&gt;片&lt;/b&gt;" in html and "<b>片</b>" not in html
    assert 'value="balanced" checked' in html and "均衡（改版前的设置）" in html
    assert 'value="同行"' in html and "甲\n乙" in html and "selected" in html
    info = run_app("(async () => { await selectProject('新项目'); await openProjectSettings(); return el('#modalBody').innerHTML; })()",
                   routes={**NEW_ROUTES, "GET /api/state": {**NEW_STATE, "project": {
                       **NEW_STATE["project"], "calibration": {"tone": "emotion"}}}})
    assert "均衡（改版前的设置）" not in info and 'value="emotion" checked' in info


def test_save_project_settings_redraws_steps_from_returned_wizard():
    stale = wizard(analyze=("stale", "剪辑偏好或预设改过了 · 重新分析", "reanalyze"), browse="done",
                   criteria="available", result=("locked", "先完成「④ 定标准」", None),
                   export=("locked", "先完成「④ 定标准」", None))
    out = run_app("""(async () => {
      await selectProject('新项目'); await openProjectSettings();
      el('#psTitle').value = '新片名'; el('#psPreset').value = '纪实3min'; el('#psMin').value = '2'; el('#psSec').value = '55';
      el('input[name="psTone"]:checked').value = 'emotion';
      await saveProjectSettings();
      return [calls.find(c => c.path === '/api/project/settings').body, el('#steps').innerHTML.includes('st-stale'),
              el('#mask').classList.contains('on'), state.data.project.title];
    })()""", routes={**NEW_ROUTES, "POST /api/project/settings": {
        "ok": True, "project": {**NEW_STATE["project"], "title": "新片名"}, "wizard": stale}})
    body, has_stale, modal, title = out
    assert body == {"project": "新项目", "title": "新片名", "preset": "纪实3min",
                    "calibration": {"tone": "emotion", "audience": "", "must_lines": ""}}
    assert has_stale is True and modal is False and title == "新片名"


def test_save_project_settings_error_keeps_modal_open():
    out = run_app("""(async () => {
      await selectProject('新项目'); await openProjectSettings(); el('#psMin').value = '2'; el('#psSec').value = '55';
      await saveProjectSettings();
      return [el('#mask').classList.contains('on'), el('#toast').textContent];
    })()""", routes={**NEW_ROUTES, "POST /api/project/settings": [400, {"error": "片名不合法 <x>"}]})
    assert out == [True, "片名不合法 <x>"]


# ---------------------------------------------------------------- KI-104：项目设置里改成片时长
T_STATE = {**NEW_STATE, "project": {**NEW_STATE["project"], "target_duration": 175}}
T_ROUTES = {**NEW_ROUTES, "GET /api/state": T_STATE}
OPEN_SETTINGS = "await selectProject('新项目'); await openProjectSettings(); el('#psMin').value = '2'; el('#psSec').value = '55';"  # 桩元素不读 HTML，回显由单独的测试看
STALE_RESULT = wizard(analyze="done", browse="done", criteria="done",
                      result=("stale", "目标时长改过了 · 重新选段", "reselect"), export="available")


def test_settings_shows_current_target_as_minutes_and_seconds_above_title():
    out = run_app("(async () => {" + OPEN_SETTINGS + """
      return [el('#modalBody').innerHTML]; })()""", routes=T_ROUTES)
    html = out[0]
    assert "psMin" in html and "psSec" in html and 'value="2"' in html and 'value="55"' in html
    assert html.index("psMin") < html.index("psTitle")  # 最上面
    assert "成片时长" in html


def test_settings_without_stored_target_shows_default_175():
    state = {**NEW_STATE, "project": {k: v for k, v in NEW_STATE["project"].items() if k != "target_duration"}}
    html = run_app("(async () => {" + OPEN_SETTINGS + " return el('#modalBody').innerHTML; })()",
                   routes={**NEW_ROUTES, "GET /api/state": state})
    assert 'id="psMin" type="number" min="0" max="60" step="1" value="2"' in html
    assert 'id="psSec" type="number" min="0" max="59" step="1" value="55"' in html


def test_save_settings_without_change_does_not_send_target():
    out = run_app("(async () => {" + OPEN_SETTINGS + """
      await saveProjectSettings();
      return calls.find(c => c.path === '/api/project/settings').body; })()""",
                  routes={**T_ROUTES, "POST /api/project/settings": {"ok": True, "project": T_STATE["project"], "wizard": wizard()}})
    assert "target" not in out and out["project"] == "新项目"


def test_save_settings_with_changed_duration_sends_target_seconds():
    saved = {"ok": True, "project": {**T_STATE["project"], "target_duration": 180}, "wizard": wizard()}
    out = run_app("(async () => {" + OPEN_SETTINGS + """
      el('#psMin').value = '3'; el('#psSec').value = '';
      await saveProjectSettings();
      return [calls.find(c => c.path === '/api/project/settings').body, state.data.project.target_duration]; })()""",
                  routes={**T_ROUTES, "POST /api/project/settings": saved})
    assert out[0]["target"] == 180 and out[1] == 180


def test_save_settings_changing_preset_does_not_touch_target():
    out = run_app("(async () => {" + OPEN_SETTINGS + """
      el('#psPreset').value = '纪实3min'; await saveProjectSettings();
      return [calls.find(c => c.path === '/api/project/settings').body]; })()""",
                  routes={**T_ROUTES, "POST /api/project/settings": {"ok": True, "project": T_STATE["project"], "wizard": wizard()}})
    assert "target" not in out[0]


@pytest.mark.parametrize("minutes,seconds", [("", "5"), ("0", "9"), ("1", "60"), ("61", "0"), ("0", "0"), ("x", "1")])
def test_save_settings_rejects_bad_duration_without_posting(minutes, seconds):
    out = run_app("(async () => {" + OPEN_SETTINGS + f"""
      el('#psMin').value = {minutes!r}; el('#psSec').value = {seconds!r};
      await saveProjectSettings();
      return [calls.filter(c => c.method === 'POST').length, el('#toast').textContent, el('#mask').classList.contains('on')]; }})()""",
                  routes=T_ROUTES)
    assert out == [0, "时长要在 10 秒到 60 分钟之间（秒填 0–59 的整数）", True]


def test_save_settings_server_409_toasts_reason_and_keeps_modal():
    out = run_app("(async () => {" + OPEN_SETTINGS + """
      el('#psMin').value = '3';
      await saveProjectSettings();
      return [el('#toast').textContent, el('#mask').classList.contains('on'), state.data.project.target_duration]; })()""",
                  routes={**T_ROUTES, "POST /api/project/settings": [409, {"error": "正在处理这个项目，完成后再改时长"}]})
    assert out == ["正在处理这个项目，完成后再改时长", True, 175]


def test_save_settings_new_target_with_stale_result_uses_stale_toast():
    saved = {"ok": True, "project": {**T_STATE["project"], "target_duration": 180}, "wizard": STALE_RESULT}
    out = run_app("(async () => {" + OPEN_SETTINGS + """
      el('#psMin').value = '3'; el('#psSec').value = '0';
      await saveProjectSettings();
      return [el('#toast').textContent, el('#steps').innerHTML.includes('st-stale')]; })()""",
                  routes={**T_ROUTES, "POST /api/project/settings": saved})
    assert out == ["已保存。⑤ 看结果需要重新选段才会按新时长出分镜表", True]


def test_save_settings_stale_result_without_target_change_uses_plain_toast():
    saved = {"ok": True, "project": T_STATE["project"], "wizard": STALE_RESULT}
    out = run_app("(async () => {" + OPEN_SETTINGS + " await saveProjectSettings(); return el('#toast').textContent; })()",
                  routes={**T_ROUTES, "POST /api/project/settings": saved})
    assert out == "项目设置已保存"


def test_save_settings_target_change_on_browse_view_rereads_browse():
    from fe_browse import BROWSE, BROWSE_STATE
    saved = {"ok": True, "project": {**T_STATE["project"], "target_duration": 180}, "wizard": BROWSE_STATE["wizard"]}
    out = run_app("""(async () => {
      await selectProject('新项目'); await go('browse'); await tick(); await tick();
      await openProjectSettings(); el('#psMin').value = '3'; el('#psSec').value = '0';
      const before = calls.filter(c => c.path.startsWith('/api/browse')).length;
      await saveProjectSettings(); await tick(); await tick();
      return calls.filter(c => c.path.startsWith('/api/browse')).length - before; })()""",
                  routes={**NEW_ROUTES, "GET /api/state": {**BROWSE_STATE, "project": {**BROWSE["project"], "target_duration": 175}},
                          "GET /api/browse": BROWSE, "POST /api/project/settings": saved})
    assert out == 1
