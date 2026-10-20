"""M13b ⑤ 的跨步骤行为与 ③④ 暂住卡片（node vm）。⑤ 的测试在 test_frontend_result / unused / reselect，⑥ 在 test_frontend_export*。"""
import json

import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def test_stale_result_banner_reselect_starts_select_job():
    stale = wizard(analyze="done", browse="done", criteria="done",
                   result=("stale", "素材标记改过了 · 重新选段", "reselect"), export="available")
    out = in_ready("""await go('result'); const banner = el('#banner').innerHTML;
      await act('reselect'); await tick();
      return [banner, calls.filter(c => c.path === '/api/job').map(c => c.body), el('#mask').classList.contains('on')];""",
                   {"GET /api/state": {**READY_STATE, "wizard": stale}})
    assert "素材标记改过了" in out[0] and 'data-act="reselect"' in out[0]
    assert out[1] == [{"project": "新项目", "task": "select", "manual": "replace"}] and out[2] is False  # 没手动改过：不询问；重新选段只在胶囊里


def test_leaving_result_for_export_keeps_shots_saved_once():
    out = in_ready("""await go('result'); state.shots[0].sub = '改了'; scheduleSave();
      await go('export'); return calls.filter(c => c.path.startsWith('/api/shots')).map(c => c.body.shots[0].sub);""",
                   {"POST /api/shots": {"ok": True}})
    assert out == ["改了"]


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
