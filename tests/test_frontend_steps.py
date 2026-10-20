"""M13b ⑤⑥ 暂住与 ③④ 暂住卡片（node vm）。"""
import json

import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_result_step_renders_shot_table_escaped_with_target_button_and_player_bar():
    out = in_ready("""await go('result');
      return [el('#stage').innerHTML, el('#shotbar').innerHTML, el('#shotbar').hidden];""")
    html, bar, hidden = out
    assert "&lt;b&gt;字幕&lt;/b&gt;" in html and "<b>字幕</b>" not in html
    assert 'data-act="openTarget" data-starts-job' in html and "改目标时长" in html
    assert 'data-act="pick"' in html and "共 1 镜" in html
    assert 'id="pv2"' in bar and 'data-act="mark" data-which="in"' in bar and hidden is False
    assert "生成成片" not in html  # 出片入口只在 ⑥


def test_result_step_empty_points_to_browse_and_hides_player_bar():
    out = in_ready("""state.shots = []; await go('result'); return [el('#stage').innerHTML, el('#shotbar').hidden];""",
                   {"GET /api/state": {**READY_STATE, "shots": []}})
    assert 'data-act="go" data-step="browse"' in out[0] and "分镜表还是空的" in out[0] and out[1] is True


def test_player_bar_only_in_result_step():
    out = in_ready("""await go('result'); await go('export'); return [el('#shotbar').hidden, el('#shotbar').innerHTML];""")
    assert out == [True, ""]


def test_stale_result_banner_reselect_starts_select_job():
    stale = wizard(analyze="done", browse="done", criteria="done",
                   result=("stale", "素材标记改过了 · 重新选段", "reselect"), export="available")
    out = in_ready("""await go('result'); const banner = el('#banner').innerHTML;
      await act('reselect'); await tick();
      return [banner, calls.filter(c => c.path === '/api/job').map(c => c.body), el('#mask').classList.contains('on')];""",
                   {"GET /api/state": {**READY_STATE, "wizard": stale}})
    assert "素材标记改过了" in out[0] and 'data-act="reselect"' in out[0]
    assert out[1] == [{"project": "新项目", "task": "select"}] and out[2] is False  # 重新选段只在胶囊里


def test_change_target_modal_posts_select_with_new_target():
    out = in_ready("""openTarget(false); el('#tgtMin').value = '4'; el('#tgtSec').value = '30';
      const modal = el('#modalBody').innerHTML;
      saveTarget(); await tick();
      return [modal, calls.filter(c => c.path === '/api/job').map(c => c.body)];""")
    assert "想剪成多长？" in out[0] and "按这个时长重新选段" in out[0] and "data-starts-job" in out[0]
    assert out[1] == [{"project": "新项目", "task": "select", "target": 270}]


def test_leaving_result_for_export_keeps_shots_saved_once():
    out = in_ready("""await go('result'); state.shots[0].sub = '改了'; scheduleSave();
      await go('export'); return calls.filter(c => c.path.startsWith('/api/shots')).map(c => c.body.shots[0].sub);""",
                   {"POST /api/shots": {"ok": True}})
    assert out == ["改了"]


def test_export_step_lists_versions_with_windows_package_and_escaped_draft_names():
    html = in_ready("await go('export'); return el('#stage').innerHTML;")
    assert "生成新版本（导出到 Mac 剪映）" in html and "打开剪映" in html
    assert "&lt;i&gt;片名&lt;/i&gt;_v2" in html and "<i>" not in html
    assert html.count('data-act="exportVersion"') == 2 and "生成 Windows 剪映包" in html
    assert 'data-act="revealExport" data-i="0"' in html and "在访达中显示" in html and "已生成 v2.zip" in html
    assert "这一版只有工程，没有预览片" in html and "/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/preview/v2" in html


def test_export_step_without_versions_says_so():
    out = in_ready("await go('export'); return el('#stage').innerHTML;",
                   {"GET /api/state": {**READY_STATE, "versions": []}})
    assert "还没有导出过" in out and 'data-act="openBuild"' in out


def test_build_modal_keeps_preview_only_checkbox_and_posts_build():
    out = in_ready("""openBuild(); const modal = [el('#modalTitle').textContent, el('#modalBody').innerHTML];
      el('#noDraft').checked = true; await doBuild();
      return [modal, calls.filter(c => c.path === '/api/job').map(c => c.body)];""")
    title, body = out[0]
    assert title == "生成新版本" and "只出预览" not in body
    assert "这次只生成预览片，不导出到剪映（剪映开着时用）" in body and 'id="noDraft"' in body
    assert out[1] == [{"project": "新项目", "task": "build", "no_draft": True}]


def test_build_job_still_opens_log_modal_and_open_jianying_posts_open():
    out = in_ready("""await startJob('build', {}); const modal = el('#mask').classList.contains('on');
      await openJianying();
      return [modal, el('#modalTitle').textContent, calls.filter(c => c.path === '/api/open').map(c => c.body)];""",
                   {"POST /api/open": {"ok": True}})
    assert out == [True, "正在生成新版本", [{"project": "新项目", "target": "jianying"}]]


def test_browse_and_criteria_are_real_pages_with_no_sub_window_entry():
    out = in_ready("""await go('browse'); const b = el('#stage').innerHTML;
      await go('criteria'); const c = el('#stage').innerHTML;
      return [b, c, calls.filter(c => c.path === '/api/window').length];""")
    assert 'id="bList"' in out[0] and "窗口" not in out[0]
    assert 'id="cPending"' in out[1] and "openConfirm" not in out[1] and "窗口" not in out[1]
    assert out[2] == 0


def test_no_window_focus_hook_remains():
    out = in_ready("""await go('criteria'); const base = calls.filter(c => c.path.startsWith('/api/state')).length;
      return [typeof onWindowFocus, calls.filter(c => c.path.startsWith('/api/state')).length - base];""")
    assert out == ["undefined", 0]


def test_state_without_wizard_fields_does_not_crash_old_servers():
    out = run_app("""(async () => { await selectProject('新项目'); return [state.project, state.view]; })()""",
                  routes={**NEW_ROUTES, "GET /api/state": {k: v for k, v in NEW_STATE.items() if k != "wizard"}})
    assert out == ["新项目", "analyze"]
