"""M13b ② 分析页、任务胶囊、置灰、任务完成后的跳转、KI-97（node vm）。"""
import json

import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_analyze_page_lists_eleven_human_steps_with_icons_and_times():
    html = run_app(f"viewAnalyze({js(progress(done=3, running=3, seconds=74))})")
    assert html.count("<li") == 11
    for label in LABELS:
        assert label in html
    assert html.count("✓") == 3 and "1 分 14 秒" in html and "●" in html
    assert "可以关掉窗口，回来接着跑" in html


def test_analyze_page_failure_names_step_reason_and_offers_retry_diag_and_keys():
    failed = {"key": "s6", "label": "AI 理解对话", "reason": "额度用完 <script>x</script>"}
    html = run_app(f"viewAnalyze({js(progress(done=6, failed=failed))})")
    assert "「AI 理解对话」失败：额度用完 &lt;script&gt;x&lt;/script&gt;" in html and "<script>" not in html
    assert "重试（从这一步接着跑）" in html and 'data-act="startAnalysis"' in html
    assert 'data-act="exportDiag"' in html and "导出诊断包" in html
    assert 'data-act="openSettings"' in html and "去填 Key" in html
    assert "✕" in html


def test_analyze_page_failure_without_reason_still_says_something():
    failed = {"key": "s6", "label": "AI 理解对话", "reason": None}
    assert "没有记录到具体原因" in run_app(f"viewAnalyze({js(progress(done=6, failed=failed))})")


def test_analyze_page_interrupted_asks_to_continue_never_auto_restarts():
    out = run_app(f"""(async () => {{
      state.project = 'p'; state.data = {{project: {{name: 'p'}}, wizard: {js(NEW_WIZARD)}, shots: []}};
      return [viewAnalyze({js(progress(done=6))}), calls.length]; }})()""")
    assert "上次分析没跑完（已完成 6/11）" in out[0] and "继续分析" in out[0] and out[1] == 0


def test_analyze_page_not_started_and_complete():
    fresh = run_app(f"viewAnalyze({js(progress(done=0))})")
    assert "开始分析" in fresh and "data-starts-job" in fresh
    done = run_app(f"viewAnalyze({js(progress(done=11, complete=True))})")
    assert "分析完成" in done and 'data-act="go" data-step="browse"' in done


def test_analyze_page_while_running_shows_progress_headline_and_elapsed():
    out = run_app(f"""(() => {{
      jobUi.view = {{id: 'j1', task: 'prepare', status: 'running', elapsed_s: 200}};
      return viewAnalyze({js(progress(done=6, running=6))}); }})()""")
    assert "正在分析 6/11" in out and "3 分钟" in out and "data-starts-job" not in out


def test_consent_409_is_handled_inline_on_the_analysis_page():
    out = in_project("""await startAnalysis();
      return [state.block && state.block.need, el('#stage').innerHTML, el('#mask').classList.contains('on')];""",
                     {"POST /api/job": [409, {"error": "请先阅读并确认数据外发说明", "need": "consent"}]})
    need, html, modal = out
    assert need == "consent" and modal is False
    assert "火山引擎" in html and 'data-act="analysisConsent"' in html and "我知道了，继续" in html
    assert "暂不使用" not in html


def test_consent_then_restarts_analysis():
    out = in_project("""await startAnalysis(); await act('analysisConsent'); await tick();
      return calls.filter(c => c.method === 'POST').map(c => c.path);""",
                     {"POST /api/job": [409, {"error": "x", "need": "consent"}], "POST /api/config/consent": {"consent": True}})
    assert out == ["/api/job", "/api/config/consent", "/api/job"]


@pytest.mark.parametrize("need", ["encoder", "mystery"])
def test_encoder_and_unknown_need_open_explaining_modal_with_diagnostics(need):
    out = in_project("""await startAnalysis();
      return [el('#modalTitle').textContent, el('#modalBody').innerHTML, state.block];""",
                     {"POST /api/job": [409, {"error": "这台 Mac 的编码器不可用 <b>", "need": need}]})
    title, body, block = out
    assert title == "这台 Mac 暂时不能分析" and block is None
    assert "这台 Mac 的编码器不可用 &lt;b&gt;" in body and "<b>" not in body
    assert 'data-act="exportDiag"' in body and "知道了" in body


def test_job_conflict_on_start_is_toasted_and_adopts_the_running_job():
    out = in_project("""await startAnalysis();
      return [el('#toast').textContent, jobUi.id, jobUi.polling];""",
                     {"POST /api/job": [409, {"error": "已有任务在运行：别的项目 · 分析", "job_id": "other",
                                              "task": "prepare"}]})
    assert out == ["已有任务在运行：别的项目 · 分析", "other", "other"]


def test_analysis_poll_runs_while_analyzing_and_stops_when_leaving():
    out = in_project("""await go('analyze');
      jobUi.view = {id: 'j1', task: 'prepare', status: 'running'};
      const first = calls.filter(c => c.path.startsWith('/api/analysis')).length;
      await runTimers(); await runTimers();
      const polled = calls.filter(c => c.path.startsWith('/api/analysis')).length;
      stopAnalysisPoll(); const timersBefore = timers.length;
      await runTimers();
      return [first, polled, calls.filter(c => c.path.startsWith('/api/analysis')).length === polled];""")
    assert out[0] >= 1 and out[1] > out[0] and out[2] is True


def test_analysis_response_for_a_project_we_left_is_dropped():
    out = in_project("""const slow = loadAnalysis();   // 请求已发出
      state.project = '别的项目';          // 响应回来前切走了
      await slow;
      return [analysisUi.data, analysisUi.project];""")
    assert out == [None, None]


def test_landing_on_analysis_step_loads_progress_without_clicking():
    out = in_project("await tick(); return [state.view, calls.filter(c => c.path.startsWith('/api/analysis')).length > 0,"
                     " el('#stage').innerHTML.includes('开始分析')];")
    assert out == ["analyze", True, True]


@pytest.mark.parametrize("view,busy,prog,expected", [
    ({"status": "running", "task": "prepare", "elapsed_s": 190}, None, {"done": 6, "total": 11},
     {"text": "正在分析 6/11 · 3 分钟", "cls": ""}),
    ({"status": "running", "task": "prepare", "elapsed_s": 20}, None, None, {"text": "正在分析 · 不到 1 分钟", "cls": ""}),
    ({"status": "running", "task": "select"}, None, None, {"text": "正在重新选段…", "cls": ""}),
    (None, {"task": "build"}, None, {"text": "正在导出…", "cls": ""}),
    ({"status": "failed", "task": "select"}, None, None, {"text": "失败 · 查看", "cls": "failed"}),
    ({"status": "cancelled", "task": "select"}, None, None, {"text": "已取消 · 查看", "cls": "failed"}),
    ({"status": "done", "task": "build", "warned": True}, None, None, {"text": "完成，有提示 · 查看", "cls": "warn"}),
    ({"status": "done", "task": "build"}, None, None, None),
    ({"status": "failed", "task": "select", "seen": True}, None, None, None),
    (None, None, None, None),
])
def test_chip_model(view, busy, prog, expected):
    assert run_app(f"chipModel({js(view)}, {js(busy)}, {js(prog)})") == expected


def test_render_chip_shows_failed_and_opens_detail_with_log():
    out = run_app("""(() => {
      jobUi.view = {id: 'j1', task: 'select', status: 'failed', log: ['[x] 选段失败 <b>']};
      renderChip();
      const chip = [el('#chip').hidden, el('#chip').textContent, el('#chip').classList.contains('failed')];
      openJobDetail();
      return [chip, [el('#log').textContent, el('#jobActions').innerHTML], el('#chip').hidden]; })()""")
    chip, (log, actions), hidden_after = out
    assert chip == [False, "失败 · 查看", True]
    assert log == "[x] 选段失败 <b>" and 'data-act="exportDiag"' in actions
    assert 'data-act="retryJob"' not in actions  # 不知道当初的参数：不给重试
    assert hidden_after is True  # 看过了，胶囊收起


def test_chip_hidden_without_job():
    assert run_app("renderChip(); [el('#chip').hidden, el('#chip').textContent]") == [True, ""]


def test_busy_guard_disables_job_starters_with_reason():
    out = run_app("""(() => {
      const mk = () => { const b = el('b' + Math.random()); return b; };
      const a = mk(), b = mk(); lists['[data-starts-job]'] = [a, b];
      jobUi.view = {id: 'j1', task: 'prepare', status: 'running'};
      applyBusyGuard();
      const busy = [a.disabled, a.getAttribute('title')];
      jobUi.view = {id: 'j1', task: 'prepare', status: 'done'};
      applyBusyGuard();
      return [busy, a.disabled, a.getAttribute('title')]; })()""")
    assert out == [[True, "正在分析，完成后再试"], False, None]


def test_busy_guard_uses_global_busy_from_state_for_other_projects():
    out = run_app("""(() => {
      const a = el('a'); lists['[data-starts-job]'] = [a];
      state.data = {busy: {id: 'z', task: 'build', project: '别的项目', label: '导出'}};
      applyBusyGuard(); return [a.disabled, a.getAttribute('title')]; })()""")
    assert out == [True, "正在导出，完成后再试"]


def test_prepare_done_while_viewing_analysis_goes_to_browse():
    view, toast_text, _ = run_job_done("analyze")
    assert view == "browse" and toast_text == "分析完成"


def test_prepare_done_elsewhere_does_not_pull_the_user_away():
    view, _, _ = run_job_done("criteria")
    assert view == "criteria"


def test_select_done_while_viewing_criteria_goes_to_result():
    w = wizard(analyze="done", browse="done", criteria="done", result="available", export="available")
    view, toast_text, _ = run_job_done("criteria", task="select", state_wizard=w)
    assert view == "result" and toast_text == "已重新选段"


def test_prepare_done_with_must_keep_over_target_no_longer_pops_a_dialog():
    """E16：超目标改为 ⑤ 顶栏的警告条，不再在分析 / 选段完成后自动弹窗打断跳转。"""
    view, _, modal = run_job_done("analyze", extra_state={"selection": {"over_target": True, "must_keep_total": 300,
                                                                        "suggested_target": 300}})
    assert view == "browse" and modal is False


def test_failed_prepare_refreshes_analysis_for_the_failure_card():
    out = in_project("""await go('analyze');
      await startJob('prepare', undefined, {});
      const before = calls.filter(c => c.path.startsWith('/api/analysis')).length;
      await runTimers(); await runTimers();
      return [calls.filter(c => c.path.startsWith('/api/analysis')).length > before, el('#chip').textContent];""",
                     {"GET /api/job/": {"status": "failed", "task": "prepare", "log": ["[x] boom"], "elapsed_s": 5}})
    assert out == [True, "失败 · 查看"]
