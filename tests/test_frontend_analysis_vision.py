"""画面理解第 2 阶段 · ② 页卡片（node vm）：各状态显示、运行中锁定、保存、竞态、出错、转义。"""
import pytest

from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

ON = {"enabled": True, "tier": "balanced"}
STALE_WIZARD = {**DONE_WIZARD, "steps": [{**s, "status": "stale"} if s["key"] == "analyze" else s
                                         for s in DONE_WIZARD["steps"]]}
SAVED = {"ok": True, "vision": {"enabled": True, "tier": "economy"}, "wizard": STALE_WIZARD}


def _view(p):
    return run_app(f"viewAnalyze({js(p)})")


@pytest.mark.parametrize("p", [progress(done=0), progress(done=11, complete=True), progress(done=6),
                               progress(done=6, failed={"key": "s6", "label": "AI 理解对话", "reason": "x"})])
def test_card_shows_switch_tiers_and_privacy_when_not_running(p):
    html = _view(p)
    assert "画面理解（AI 多模态）" in html and "可选 · 默认关闭" in html
    assert 'role="switch"' in html and 'aria-checked="false"' in html and 'data-act="toggleVision"' in html
    for label in ("省钱（默认）", "均衡", "精细"):
        assert label in html
    assert html.count('data-act="setVisionTier"') == 3
    assert "低清代理视频（不是原始视频）" in html and "火山引擎" in html


def test_card_comes_before_the_start_button_but_after_the_complete_card():
    fresh = _view(progress(done=0))
    assert fresh.index("画面理解（AI 多模态）") < fresh.index('data-act="startAnalysis"')
    done = _view(progress(done=11, complete=True))
    assert done.index("分析完成") < done.index("画面理解（AI 多模态）")


def test_tiers_are_disabled_while_switch_is_off_and_enabled_when_on():
    off = _view(progress(done=0))
    assert all("disabled" in b for b in off.split('data-act="setVisionTier"')[1:])
    on = _view(progress(done=0, vision=ON))
    assert 'aria-checked="true"' in on
    tiers = [b.split(">")[0] for b in on.split('data-act="setVisionTier"')[1:]]
    assert all("disabled" not in t for t in tiers)
    assert sum('aria-pressed="true"' in t for t in tiers) == 1 and 'data-tier="balanced"' in on


def test_running_shows_only_a_lock_strip_with_current_setting():
    html = run_app(f"""(() => {{
      jobUi.view = {{id: 'j1', task: 'prepare', status: 'running', elapsed_s: 5}};
      return viewAnalyze({js(progress(done=3, running=3, vision=ON))}); }})()""")
    assert "画面理解：已开启 · 均衡" in html and "分析中不能修改" in html
    assert 'data-act="toggleVision"' not in html and 'data-act="setVisionTier"' not in html


def test_running_with_vision_off_says_not_enabled():
    html = run_app(f"""(() => {{
      jobUi.view = {{id: 'j1', task: 'prepare', status: 'running'}};
      return viewAnalyze({js(progress(done=3, running=3))}); }})()""")
    assert "画面理解：未开启" in html


def test_toggle_posts_setting_redraws_and_applies_wizard():
    out = in_project("""await act('toggleVision'); await tick();
      const post = calls.find(c => c.path === '/api/project/vision');
      return [post && post.body, el('#stage').innerHTML,
              state.data.wizard.steps.find(s => s.key === 'analyze').status];""",
                     {"POST /api/project/vision": SAVED})
    body, html, status = out
    assert body == {"project": "新项目", "enabled": True, "tier": "economy"}
    assert 'aria-checked="true"' in html and status == "stale"


def test_set_tier_keeps_switch_and_sends_chosen_tier():
    out = in_project("""analysisUi.data = {...analysisUi.data, vision: {enabled: true, tier: 'economy'}};
      await act('setVisionTier', {tier: 'quality'}); await tick();
      return calls.find(c => c.path === '/api/project/vision').body;""",
                     {"POST /api/project/vision": {**SAVED, "vision": {"enabled": True, "tier": "quality"}}})
    assert out == {"project": "新项目", "enabled": True, "tier": "quality"}


def test_unknown_tier_from_dom_is_ignored():
    out = in_project("""await act('setVisionTier', {tier: 'pro'}); await tick();
      return calls.filter(c => c.path === '/api/project/vision').length;""")
    assert out == 0


def test_409_while_running_toasts_reason_and_keeps_switch():
    out = in_project("""await act('toggleVision'); await tick();
      return [el('#toast').textContent, analysisUi.data.vision.enabled,
              calls.filter(c => c.path.startsWith('/api/analysis')).length];""",
                     {"POST /api/project/vision": [409, {"error": "正在处理这个项目，停止或完成后再改画面理解<b>"}]})
    assert out[0].startswith("正在处理这个项目") and out[1] is False
    assert out[2] >= 2  # 进入 ② 读一次 + 409 后刷新进度（卡片换成锁定条）


def test_late_reply_after_switching_project_is_dropped():
    out = in_project("""await tick(); const p = act('toggleVision'); state.project = '别的项目'; await p; await tick();
      return [analysisUi.data.vision.enabled, state.data.wizard.steps.find(s => s.key === 'analyze').status];""",
                     {"POST /api/project/vision": SAVED})
    assert out == [False, "available"]


def test_double_click_sends_one_request():
    out = in_project("""const a = act('toggleVision'); const b = act('toggleVision'); await Promise.all([a, b]); await tick();
      return calls.filter(c => c.path === '/api/project/vision').length;""",
                     {"POST /api/project/vision": SAVED})
    assert out == 1


def test_block_page_does_not_show_the_card():
    out = in_project("""state.block = {need: 'consent', missing: []}; return viewAnalyze(analysisUi.data);""")
    assert 'data-act="toggleVision"' not in out
