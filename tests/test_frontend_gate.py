"""M13d Task 19：④ 的闸门「确认，生成分镜表」（node vm）：待定先问、不写任何裁决（P1）、草稿先落盘、任务跟踪、跨项目完成、旧项目提示。"""
import pytest

from fe_criteria import ALL_DECIDED, CONFIRM, in_criteria, js
from fe_harness import NODE, wizard

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

DONE_W = wizard(analyze="done", browse="done", criteria="done", result="available", export="available")
STALE_W = wizard(analyze="done", browse="done", criteria="done",
                 result=("stale", "答案改过了 · 重新选段", "reselect"), export="available")
JOB_DONE = {"GET /api/job/": {"status": "done", "task": "select", "log": [], "project": "新项目", "elapsed_s": 3}}


def gate_setup(confirm_resp):
    """草稿保存（不带 confirmed）永远成功；带 confirmed:true 的按测试给的响应回答。"""
    return f"""const CONFIRM_RESP = {js(confirm_resp)};
      window.__respond = (m, p, b) => m === 'POST' && p === '/api/confirm/answers'
        ? (b.confirmed === true ? CONFIRM_RESP : [200, {{ok: true, job_id: null, wizard: null}}]) : respond(m, p, b);
      const gatePosts = () => draftPosts().filter(b => b.confirmed === true);"""


def run_gate(script, confirm_resp=None, routes=None, wiz=DONE_W):
    resp = confirm_resp if confirm_resp is not None else [200, {"ok": True, "job_id": "sel1", "wizard": DONE_W}]
    return in_criteria(f"{gate_setup(resp)} {script}", {**JOB_DONE, **(routes or {})}, wiz=wiz)


# ---------------------------------------------------------------- 入口在底部导航里
def test_nav_in_criteria_ends_with_the_gate_button_not_a_plain_next():
    out = in_criteria("return el('#nav').innerHTML;")
    assert 'data-act="gate"' in out and "data-starts-job" in out and "确认，生成分镜表" in out
    assert "去看结果" not in out and "← 上一步" in out


def test_other_steps_keep_the_plain_next_button():
    out = in_criteria("await go('browse'); return el('#nav').innerHTML;")
    assert "下一步：去定标准 →" in out and 'data-act="gate"' not in out


# ---------------------------------------------------------------- 待定没裁完：先问，不拦
def test_gate_with_pending_asks_first_and_sends_nothing_yet():
    out = run_gate("""await act('gate'); return [el('#modalTitle').textContent, el('#modalBody').innerHTML, gatePosts().length];""")
    assert out[0] == "还有 3 段待定，按 AI 建议处理？"
    assert "先不进片" in out[1] and 'data-act="gateGo"' in out[1] and "回去裁决" in out[1]
    assert out[2] == 0


def test_gate_go_confirms_without_writing_any_verdict():
    out = run_gate("""await act('gate'); await act('gateGo');
      return [gatePosts(), levelPosts().length, el('#mask').classList.contains('on'), C().segs.filter(s => s.level === 2).length];""")
    assert out[0] == [{"project": "新项目", "answers": {}, "confirmed": True, "manual": "replace"}]
    assert out[1] == 0 and out[2] is False and out[3] == 3


def test_going_back_to_adjudicate_closes_the_question_and_sends_nothing():
    out = run_gate("""await act('gate'); await act('closeModal'); return [gatePosts().length, el('#mask').classList.contains('on')];""")
    assert out == [0, False]


def test_gate_without_pending_goes_straight_through():
    out = run_gate("await act('gate'); return [el('#mask').classList.contains('on'), gatePosts().length];",
                   routes={"GET /api/confirm": ALL_DECIDED})
    assert out == [False, 1]


def test_gate_after_ai_rest_does_not_ask_again():
    out = run_gate("""act('critAiRest'); act('critAiRestGo'); await act('gate');
      return [el('#mask').classList.contains('on'), gatePosts().length, levelPosts().length];""")
    assert out == [False, 1, 0]


def test_gate_confirms_even_if_questions_are_unanswered():
    out = run_gate("await act('gate'); return gatePosts().length;",
                   routes={"GET /api/confirm": {**CONFIRM, "pending": []}})
    assert out == 1


def test_gate_before_the_page_has_loaded_questions_explains_instead_of_failing_silently():
    out = run_gate("await act('gate'); return [el('#toast').textContent, draftPosts().length];",
                   routes={"GET /api/confirm": [404, {"error": "还没有决策问题，先跑 questions"}]})
    assert "还没有决策问题" in out[0] and out[1] == 0


# ---------------------------------------------------------------- 草稿先落盘
def test_gate_flushes_unsent_draft_before_confirming_and_sends_latest_answers():
    out = run_gate("""act('critPick', {q: '0', o: '0'}); act('critPick', {q: '1', o: '1'});
      await act('gate'); return draftPosts();""", routes={"GET /api/confirm": ALL_DECIDED})
    assert len(out) == 2 and "confirmed" not in out[0] and out[1]["confirmed"] is True
    assert out[0]["answers"] == out[1]["answers"] == {"q1": "签字<i>", "q2": ["合同", "吃饭"]}


def test_gate_stops_when_the_draft_cannot_be_saved():
    out = run_gate("""window.__respond = (m, p) => m === 'POST' && p === '/api/confirm/answers' ? [500, {error: '写不进去'}] : respond(m, p);
      act('critPick', {q: '0', o: '0'}); await act('gate');
      return [draftPosts().map(b => 'confirmed' in b), el('#toast').textContent];""",
                   routes={"GET /api/confirm": ALL_DECIDED})
    assert out[0] == [False] and "答案还没保存成功" in out[1]


def test_double_click_on_the_gate_sends_one_confirmation():
    out = run_gate("""const a = act('gate'); const b = act('gate'); await a; await b; return gatePosts().length;""",
                   routes={"GET /api/confirm": ALL_DECIDED})
    assert out == 1


# ---------------------------------------------------------------- 任务跟踪与完成
def test_started_job_shows_in_chip_at_once_and_page_says_it_is_reselecting():
    out = run_gate("""await act('gate'); await act('gateGo');
      return [jobUi.view, el('#chip').textContent, el('#chip').hidden, el('#cStatus').innerHTML];""")
    assert out[0] == {"id": "sel1", "task": "select", "status": "running"}
    assert out[1] == "正在重新选段…" and out[2] is False and "正在按你的答案重新选段" in out[3]


def test_gate_applies_wizard_from_response_to_the_step_bar():
    out = run_gate("await act('gate'); await act('gateGo'); return el('#steps').innerHTML.includes('⚠');",
                   confirm_resp=[200, {"ok": True, "job_id": "sel1", "wizard": STALE_W}])
    assert out is True


def test_job_completion_goes_to_result_when_still_on_criteria():
    out = run_gate("""await act('gate'); await act('gateGo');
      for (let i = 0; i < 4; i++) await runTimers();
      return [state.view, el('#toast').textContent];""")
    assert out == ["result", "已重新选段"]


def test_job_completion_for_another_project_does_not_move_the_page():
    out = run_gate("""await act('gate'); await act('gateGo');
      await selectProject('别的项目'); await tick(); const view = state.view;
      for (let i = 0; i < 4; i++) await runTimers();
      return [view, state.view, state.project, el('#toast').textContent];""")
    assert out[1] == out[0] == "criteria" and out[2] == "别的项目"
    assert out[3] == "「新项目」：已重新选段"


def test_job_error_keeps_answers_and_explains_in_page_and_toast_escaped():
    out = run_gate("await act('gate'); await act('gateGo'); return [el('#cStatus').innerHTML, el('#toast').textContent, state.view, jobUi.view];",
                   confirm_resp=[200, {"ok": True, "job_id": None, "job_error": "已有任务在运行<b>", "wizard": STALE_W}])
    assert "答案已保存，但没能开始重新选段：已有任务在运行&lt;b&gt;" in out[0]
    assert "答案已保存，但没能开始重新选段：已有任务在运行<b>" in out[1]
    assert out[2] == "criteria" and out[3] is None


def test_server_refusal_is_shown_verbatim_and_no_job_is_tracked():
    out = run_gate("await act('gate'); await act('gateGo'); return [el('#toast').textContent, jobUi.view, C().gating];",
                   confirm_resp=[409, {"error": "决策问题文件损坏"}])
    assert out == ["决策问题文件损坏", None, False]


def test_gate_can_be_used_again_after_a_refusal():
    out = run_gate("""window.__n = 0;
      const base = window.__respond;
      window.__respond = (m, p, b) => (m === 'POST' && p === '/api/confirm/answers' && b.confirmed === true && window.__n++ === 0)
        ? [500, {error: '暂时不行'}] : base(m, p, b);
      await act('gate'); await act('gate'); return gatePosts().length;""",
                   routes={"GET /api/confirm": ALL_DECIDED})
    assert out == 2


# ---------------------------------------------------------------- 旧项目（P2）
def test_legacy_wizard_banner_shows_on_criteria_and_confirm_still_works():
    note = "这个项目在改版前已出过片，没经过定标准；需要时可以在这里确认一次"
    out = run_gate("""const banner = el('#banner').innerHTML; await act('gate'); await act('gateGo');
      return [banner, gatePosts().length];""",
                   wiz=wizard(analyze="done", browse="done", criteria=("done", note, None),
                              result="available", export="available"))
    assert note in out[0] and out[1] == 1
