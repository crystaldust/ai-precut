"""M13d 评审修复：④ 的异步竞态（离开后回包、闸门等队列、加载占位、草稿失败拦导航、③④ 先后顺序、按键不吞滚动、不冲掉输入）。"""
import pytest

from fe_browse import BROWSE
from fe_criteria import ALL_DECIDED, CONFIRM, in_criteria
from fe_harness import NODE
from test_frontend_gate import DONE_W, JOB_DONE, gate_setup

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")
BROWSE_ROUTES = {"GET /api/browse": BROWSE,
                 "POST /api/browse/must": {"ok": True, "segment": None, "clip_list": None, "wizard": None}}
SENTINEL = "el('#cPending').innerHTML = 'SENT'; el('#cToc').innerHTML = 'SENT'; el('#cAnalysis').innerHTML = 'SENT'; el('#cQuestions').innerHTML = 'SENT'; el('#toast').textContent = '';"
SENT_ALL = "[el('#cPending').innerHTML, el('#cToc').innerHTML, el('#cAnalysis').innerHTML, el('#cQuestions').innerHTML]"


# ---------------------------------------------------------------- HIGH-1：离开 ④ 后才回包
def test_level_success_after_leaving_criteria_renders_nothing_and_toasts_nothing():
    out = in_criteria(f"""const held = hold(p => p === '/api/browse/level');
      const p = act('critDecide', {{level: '3'}}); await tick();
      await go('browse'); await tick(); {SENTINEL}
      held.forEach(f => f()); await p; await tick();
      return [{SENT_ALL}, el('#toast').textContent, C().segs[1].level];""", BROWSE_ROUTES)
    assert out[0] == ["SENT"] * 4 and out[1] == "" and out[2] == 3


def test_level_failure_after_leaving_criteria_rolls_back_state_but_never_touches_dom():
    out = in_criteria(f"""const held = hold(p => p === '/api/browse/level');
      const p = act('critDecide', {{level: '3'}}); await tick();
      await go('browse'); await tick(); {SENTINEL}
      held.forEach(f => f()); await p; await tick();
      return [{SENT_ALL}, el('#toast').textContent, C().segs[1].level, queueIds()];""",
                      {**BROWSE_ROUTES, "POST /api/browse/level": [500, {"error": "炸了"}]})
    assert out[0] == ["SENT"] * 4 and "炸了" in out[1] and "TypeError" not in out[1]
    assert out[2] == 2 and out[3] == ["S2", "S3", "S4"]


@pytest.mark.parametrize("route,ok", [({"ok": True, "topic_names": {"讲合同": "谈合同"}}, True),
                                      ([400, {"error": "重名了"}], False)])
def test_rename_response_after_leaving_criteria_updates_state_only(route, ok):
    out = in_criteria(f"""act('critToggleAnalysis'); const held = hold(p => p === '/api/topics/rename');
      const p = act('critRename', {{i: '0'}}, {{value: '谈合同'}}); await tick();
      await go('browse'); await tick(); {SENTINEL}
      held.forEach(f => f()); await p; await tick();
      return [{SENT_ALL}, el('#toast').textContent, C().data.topics[0].topic];""",
                      {**BROWSE_ROUTES, "POST /api/topics/rename": route})
    assert out[0] == ["SENT"] * 4
    assert (out[1] == "" and out[2] == "谈合同") if ok else ("重名了" in out[1] and out[2] == "讲合同")


# ---------------------------------------------------------------- HIGH-2：闸门等队列
def _gate(script, routes=None):
    one = {"GET /api/confirm": {**CONFIRM, "pending": CONFIRM["pending"][:1]}}
    return in_criteria(f"{gate_setup([200, {'ok': True, 'job_id': 'sel1', 'wizard': DONE_W}])} {script}",
                       {**JOB_DONE, **one, **(routes or {})}, wiz=DONE_W)


def test_gate_waits_for_in_flight_level_changes_before_confirming():
    out = _gate("""const held = hold(p => p === '/api/browse/level');
      const d = act('critDecide', {level: '3'}); await tick();
      const g = act('gate'); await tick(); await tick(); const early = gatePosts().length;
      held.forEach(f => f()); await d; await g; return [early, gatePosts().length];""")
    assert out == [0, 1]


def test_gate_stops_and_says_so_when_a_queued_level_change_fails():
    out = _gate("""const held = hold(p => p === '/api/browse/level');
      const d = act('critDecide', {level: '3'}); await tick();
      const g = act('gate'); await tick();
      held.forEach(f => f()); await d; await g;
      return [gatePosts().length, el('#cStatus').innerHTML, el('#toast').textContent];""",
                {"POST /api/browse/level": [500, {"error": "写不进去"}]})
    assert out[0] == 0 and "档位改动没保存成功" in out[1] and "档位改动没保存成功" in out[2]


def test_gate_is_not_blocked_by_a_level_failure_the_user_already_saw():
    out = _gate("""await act('critDecide', {level: '3'});   // 失败并已回滚、已提示
      await act('gate'); await act('gateGo'); return [gatePosts().length, C().queue.length];""",
                {"POST /api/browse/level": [500, {"error": "之前的失败"}]})
    assert out == [1, 1]


# ---------------------------------------------------------------- MEDIUM-1：加载占位
def test_reloading_criteria_installs_placeholder_and_ignores_decide_keys():
    out = in_criteria("""const held = hold(p => p.startsWith('/api/confirm?'));
      const e = enterCriteria(); await tick(); await tick();
      const during = [!!state.criteria.loading, state.criteria.data];
      await press('KeyA'); await press('KeyD'); const posts = levelPosts().length;
      held.forEach(f => f()); await e; await tick();
      return [during, posts, !!C().data, !!C().loading];""")
    assert out == [[True, None], 0, True, False]


# ---------------------------------------------------------------- MEDIUM-2：草稿存不上
def test_go_is_blocked_with_a_retry_message_when_the_draft_cannot_be_saved():
    out = in_criteria("""window.__respond = (m, p) => m === 'POST' && p === '/api/confirm/answers' && window.__bad
        ? [500, {error: '磁盘满了'}] : respond(m, p);
      window.__bad = true; act('critPick', {q: '0', o: '0'});
      await go('browse'); const blocked = [state.view, el('#cStatus').innerHTML, el('#toast').textContent];
      window.__bad = false; await go('browse'); return [blocked, state.view];""", BROWSE_ROUTES)
    assert out[0][0] == "criteria" and "答案还没存上" in out[0][1] and "磁盘满了" in out[0][1] and "再点一次" in out[0][2]
    assert out[1] == "browse"


def test_project_switch_with_unsaved_draft_shows_a_long_toast_and_still_switches():
    out = in_criteria("""window.__respond = (m, p) => m === 'POST' && p === '/api/confirm/answers' ? [500, {error: '磁盘满了'}] : respond(m, p);
      act('critPick', {q: '0', o: '0'}); await selectProject('别的项目');
      return [state.project, el('#toast').textContent, Math.max(...timers.map(t => t.ms || 0))];""")
    assert out[0] == "别的项目" and "新项目" in out[1] and "没存上" in out[1] and "磁盘满了" in out[1] and out[2] >= 10000


def test_go_and_project_switch_flush_the_draft_first():
    out = in_criteria("""act('critPick', {q: '0', o: '0'}); await go('browse'); const a = [draftPosts().length, state.view];
      await go('criteria'); await tick(); await tick(); act('critPick', {q: '0', o: '1'});
      await selectProject('别的项目'); return [a, draftPosts().map(b => b.project)];""", BROWSE_ROUTES)
    assert out[0] == [1, "browse"] and out[1] == ["新项目", "新项目"]


def test_status_does_not_claim_saved_while_a_newer_pick_is_unsaved():
    out = in_criteria("""const held = hold(p => p === '/api/confirm/answers');
      act('critPick', {q: '0', o: '0'}); const f = flushCriteriaDraft(); await tick();
      act('critPick', {q: '0', o: '1'}); held.forEach(fn => fn()); await f; await tick();
      return [el('#cStatus').innerHTML, C().dirty];""")
    assert "正在保存" in out[0] and out[1] is True


# ---------------------------------------------------------------- MEDIUM-3：③ ④ 先后顺序
def test_entering_browse_waits_for_criteria_level_changes():
    out = in_criteria("""const held = hold(p => p === '/api/browse/level');
      const d = act('critDecide', {level: '3'}); await tick();
      const g = go('browse'); await tick(); await tick();
      const n = () => calls.filter(c => c.path.startsWith('/api/browse?')).length; const early = n();
      held.forEach(f => f()); await d; await g; await tick(); await tick(); await tick();
      return [early, n()];""", BROWSE_ROUTES)
    assert out == [0, 1]


def test_entering_criteria_waits_for_browse_marks_in_flight():
    out = in_criteria("""await go('browse'); await tick(); await tick(); await press('ArrowDown');
      const held = hold(p => p === '/api/browse/must'); await press('KeyS');
      const n = () => calls.filter(c => c.path.startsWith('/api/confirm?')).length; const before = n();
      const g = go('criteria'); await tick(); await tick(); const early = n();
      held.forEach(f => f()); await g; await tick(); await tick(); await tick();
      return [before, early, n()];""", BROWSE_ROUTES)
    assert out[1] == out[0] and out[2] == out[0] + 1


def test_re_entering_criteria_starts_from_fresh_state():
    out = in_criteria("""act('critAiRest'); act('critAiRestGo'); await go('browse'); await tick(); await go('criteria');
      await tick(); await tick(); await tick(); return [C().aiRest, C().queue.length, !!C().loading];""", BROWSE_ROUTES)
    assert out == [False, 3, False]


# ---------------------------------------------------------------- MEDIUM-4：按键不吞滚动
@pytest.mark.parametrize("code", ["Space", "ArrowDown", "KeyA", "KeyD"])
def test_keys_keep_default_behavior_when_no_pending_segment_is_shown(code):
    out = in_criteria(f"const ev = await press('{code}'); return ev.prevented;", {"GET /api/confirm": ALL_DECIDED})
    assert out is False


def test_keys_keep_default_behavior_after_ai_rest():
    out = in_criteria("""act('critAiRest'); act('critAiRestGo'); const a = await press('Space'); const b = await press('ArrowDown');
      return [a.prevented, b.prevented];""")
    assert out == [False, False]


# ---------------------------------------------------------------- MEDIUM-5：不冲掉正在输入的框
def test_background_rerender_waits_while_a_topic_input_has_focus():
    out = in_criteria("""act('critToggleAnalysis'); el('#cAnalysis').innerHTML = 'MINE';
      el('#cAnalysis').contains = () => true; document.activeElement = {tagName: 'INPUT'};
      await press('KeyA'); const kept = el('#cAnalysis').innerHTML; const dirty = C().analysisDirty;
      document.activeElement = null; fireDoc('focusout', {}); await runTimers();
      return [kept, dirty, el('#cAnalysis').innerHTML !== 'MINE', C().analysisDirty];""")
    assert out == ["MINE", True, True, False]
