"""M13d Task 19：④ 定标准页面（node vm）：目录、分析对不对、裁决待定、决策问题与草稿保存。闸门见 test_frontend_gate.py。"""
import json

import pytest

from fe_criteria import ALL_DECIDED, CONFIRM, OK_LEVEL, in_criteria
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


# ---------------------------------------------------------------- 骨架与加载
def test_criteria_stage_is_a_stable_skeleton_with_player():
    out = in_criteria("return el('#stage').innerHTML;")
    for part in ('id="cToc"', 'id="cAnalysis"', 'id="cPending"', 'id="cQuestions"', 'id="cPv"'):
        assert part in out
    assert "openConfirm" not in out and "窗口" not in out


def test_enter_loads_confirm_once_and_points_player_at_proxy():
    out = in_criteria("return [el('#cPv').src, calls.filter(c => c.path.startsWith('/api/confirm')).map(c => c.path)];")
    assert out[0] == "/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/proxy"
    assert out[1] == ["/api/confirm?project=%E6%96%B0%E9%A1%B9%E7%9B%AE"]


def test_missing_questions_offers_regenerate_instead_of_a_dead_page():
    out = in_criteria("return [el('#cQuestions').innerHTML, el('#cPending').innerHTML];",
                      {"GET /api/confirm": [404, {"error": "还没有决策问题，先跑 questions"}]})
    assert "还没有决策问题" in out[0] and 'data-act="critRegen"' in out[0] and "先跑 questions" not in out[0]
    assert out[1] == ""


def test_load_error_is_escaped_and_conflict_message_is_shown():
    out = in_criteria("return el('#cQuestions').innerHTML;",
                      {"GET /api/confirm": [409, {"error": "文件<b>损坏</b>"}]})
    assert "文件&lt;b&gt;损坏&lt;/b&gt;" in out and "<b>损坏" not in out


def test_stale_load_for_previous_project_is_dropped():
    out = in_criteria("""resetCriteria(); el('#cQuestions').innerHTML = ''; const gate = []; const orig = window.fetch;
      window.fetch = (p, o) => String(p).startsWith('/api/confirm?') ? new Promise(r => gate.push(() => r(orig(p, o)))) : orig(p, o);
      const first = enterCriteria(); await tick();
      state.project = '别的项目'; resetCriteria();
      gate.forEach(g => g()); await first; await tick();
      return [state.criteria, el('#cQuestions').innerHTML];""")
    assert out == [None, ""]


def test_reset_clears_page_state_and_pending_draft_timer():
    out = in_criteria("""act('critPick', {q: '0', o: '0'});
      resetCriteria(); await runTimers(); return [state.criteria, draftPosts().length];""")
    assert out == [None, 0]


# ---------------------------------------------------------------- 目录（P7）
def test_toc_states_initial_and_after_progress():
    out = in_criteria("""const a = tocItems(C()).map(i => [i.key, i.done, i.text]);
      act('critPick', {q: '0', o: '1'}); act('critPick', {q: '1', o: '0'});
      const b = tocItems(C()).map(i => [i.key, i.done, i.text]); return [a, b];""")
    assert out[0] == [["analysis", False, "可选"], ["pending", False, "还有 3 段待定"], ["questions", False, "已答 0/2"]]
    assert out[1][2] == ["questions", True, "已答 2/2"]


def test_toc_pending_done_when_zero_and_analysis_never_blocks():
    out = in_criteria("return [tocItems(C()).map(i => [i.key, i.done]), el('#cToc').innerHTML];",
                      {"GET /api/confirm": ALL_DECIDED})
    assert out[0] == [["analysis", False], ["pending", True], ["questions", True]]
    assert 'data-act="critJump"' in out[1] and "✓" in out[1]


def test_toc_click_scrolls_to_section():
    out = in_criteria("""let hit = null; el('#cPending').scrollIntoView = o => { hit = o; };
      act('critJump', {sec: 'pending'}); return hit;""")
    assert out is not None


# ---------------------------------------------------------------- 决策问题
def test_questions_render_escaped_with_effect_line():
    html = in_criteria("return el('#cQuestions').innerHTML;")
    assert "结尾&lt;b&gt;怎么收&lt;/b&gt;" in html and "<b>怎么收" not in html
    assert "签字&lt;i&gt;" in html and "结尾落在&lt;u&gt;签字&lt;/u&gt;" in html
    assert html.count("选了会怎样：") == 4
    assert 'data-act="critPick" data-q="0" data-o="0"' in html and 'type="checkbox"' in html


def test_pick_single_and_multi_update_immutably_and_never_touch_loaded_answers():
    out = in_criteria("""const loaded = C().data.answers; const orig = C().answers;
      act('critPick', {q: '0', o: '1'}); act('critPick', {q: '1', o: '0'}); act('critPick', {q: '1', o: '1'});
      const mid = JSON.stringify(C().answers); act('critPick', {q: '1', o: '0'});
      return [mid, JSON.stringify(C().answers), JSON.stringify(loaded), C().answers !== orig];""")
    assert json.loads(out[0]) == {"q1": "全部", "q2": ["合同", "吃饭"]}
    assert json.loads(out[1]) == {"q1": "全部", "q2": ["吃饭"]}
    assert out[2] == "{}" and out[3] is True


def test_pick_tolerates_non_array_stored_multi_answer():
    out = in_criteria("act('critPick', {q: '1', o: '1'}); return JSON.stringify(C().answers);",
                      {"GET /api/confirm": {**CONFIRM, "answers": {"q2": "合同"}}})
    assert json.loads(out) == {"q2": ["合同", "吃饭"]}


def test_pick_ignores_bad_indices():
    out = in_criteria("act('critPick', {q: '9', o: '0'}); act('critPick', {q: '0', o: '9'}); await runTimers(); return draftPosts().length;")
    assert out == 0


def test_picks_are_saved_as_one_debounced_draft_without_confirmed_key():
    out = in_criteria("""act('critPick', {q: '0', o: '0'}); act('critPick', {q: '0', o: '1'}); act('critPick', {q: '1', o: '0'});
      const before = draftPosts().length; await runTimers(); return [before, draftPosts()];""")
    assert out[0] == 0
    assert out[1] == [{"project": "新项目", "answers": {"q1": "全部", "q2": ["合同"]}}]
    assert "confirmed" not in out[1][0]


def test_draft_saved_status_and_wizard_from_response_updates_step_bar():
    from fe_harness import wizard
    stale = wizard(analyze="done", browse="done", criteria="done",
                   result=("stale", "答案改过了 · 重新选段", "reselect"), export="available")
    out = in_criteria("""act('critPick', {q: '0', o: '0'}); await runTimers();
      return [el('#cStatus').innerHTML, el('#steps').innerHTML.includes('⚠')];""",
                      {"POST /api/confirm/answers": {"ok": True, "job_id": None, "wizard": stale}})
    assert out == ["已保存", True]


def test_draft_failure_is_loud_keeps_selection_and_retries_next_time():
    out = in_criteria("""window.__respond = (m, p, b) => m === 'POST' && p === '/api/confirm/answers' && window.__bad
        ? [409, {error: '答案文件<b>坏了</b>'}] : respond(m, p);
      window.__bad = true; act('critPick', {q: '0', o: '0'}); await runTimers();
      const first = [el('#cStatus').innerHTML, el('#toast').textContent, JSON.stringify(C().answers)];
      window.__bad = false; const ok = await flushCriteriaDraft();
      return [first, ok, draftPosts().length];""")
    assert "答案文件&lt;b&gt;坏了&lt;/b&gt;" in out[0][0] and "答案文件<b>坏了</b>" in out[0][1]
    assert json.loads(out[0][2]) == {"q1": "签字<i>"}
    assert out[1] is True and out[2] == 2


def test_fallback_stale_and_unreadable_notices():
    out = in_criteria("return el('#cQuestions').innerHTML;", {"GET /api/confirm": {
        **CONFIRM, "fallback": True, "stale_questions": True, "stale_hint": "旧版<b>问题</b>", "answers_unreadable": True}})
    assert "（兜底模板生成）" in out and "旧版&lt;b&gt;问题&lt;/b&gt;" in out
    assert "读不出来" in out and 'data-act="critRegen"' in out


def test_regenerate_starts_questions_job_and_reloads_page_when_done():
    out = in_criteria("""const html = el('#cQuestions').innerHTML;
      await act('critRegen'); await runTimers(); await runTimers(); await runTimers(); await runTimers();
      return [html.includes('data-starts-job'), calls.filter(c => c.path === '/api/job' && c.method === 'POST').map(c => c.body),
              calls.filter(c => c.path.startsWith('/api/confirm?')).length];""",
                      {"POST /api/job": {"job_id": "q1"},
                       "GET /api/job/": {"status": "done", "task": "questions", "log": [], "project": "新项目"}})
    assert out[0] is True
    assert out[1] == [{"project": "新项目", "task": "questions"}]
    assert out[2] == 2  # 进入时一次，出题完成后再读一次


def test_regenerate_flushes_unsent_draft_first():
    out = in_criteria("""act('critPick', {q: '0', o: '0'}); await act('critRegen');
      return calls.filter(c => c.method === 'POST').map(c => c.path);""",
                      {"POST /api/job": {"job_id": "q1"}})
    assert out[:2] == ["/api/confirm/answers", "/api/job"]


# ---------------------------------------------------------------- 分析对不对
def test_analysis_collapsed_by_default_shows_summary_only():
    html = in_criteria("return el('#cAnalysis').innerHTML;")
    assert "讲了&lt;i&gt;合同&lt;/i&gt;" in html and "<i>合同" not in html
    assert 'data-act="critToggleAnalysis"' in html and "聊吃饭" not in html and "老王" not in html


def test_analysis_expands_to_topics_key_points_and_speakers_escaped():
    html = in_criteria("act('critToggleAnalysis'); return el('#cAnalysis').innerHTML;")
    assert "聊吃饭&lt;b&gt;" in html and "<b>聊吃饭" not in html
    assert "关键&lt;b&gt;点&lt;/b&gt;" in html and "因为&lt;x&gt;" in html and "00:12.0" in html
    assert "老王&lt;b&gt; · 3:20" in html and "小李 · 1:05" in html
    assert 'data-act="critJumpAt" data-t="12"' in html


def test_key_point_click_plays_from_a_bit_before_and_stops_after_a_few_seconds():
    out = in_criteria("""act('critToggleAnalysis'); let played = 0; el('#cPv').play = () => { played++; return Promise.resolve(); };
      act('critJumpAt', {t: '12'}); return [el('#cPv').currentTime, C().stopAt, played];""")
    assert out == [11.7, 16, 1]


def test_topic_expands_to_its_segments_with_level_dropdown():
    html = in_criteria("""act('critToggleAnalysis'); const closed = el('#cAnalysis').innerHTML.includes('critLevel');
      act('critTopicToggle', {i: '0'}); return [closed, el('#cAnalysis').innerHTML];""")
    assert html[0] is False
    assert "甲&lt;b&gt;粗体&lt;/b&gt;" in html[1] and 'data-change="critLevel"' in html[1]
    assert '<option value="3" selected>' in html[1]


def test_rename_posts_raw_name_and_updates_display_everywhere():
    out = in_criteria("""act('critToggleAnalysis');
      await act('critRename', {i: '0'}, {value: ' 谈合同 '});
      return [calls.filter(c => c.path === '/api/topics/rename').map(c => c.body),
              C().data.topics[0].topic, C().segs[0].topic, el('#cAnalysis').innerHTML.includes('谈合同')];""",
                      {"POST /api/topics/rename": {"ok": True, "topic_names": {"讲合同": "谈合同"}}})
    assert out[0] == [{"project": "新项目", "name": "讲合同", "display": "谈合同"}]
    assert out[1:] == ["谈合同", "谈合同", True]


def test_rename_failure_restores_old_name_and_says_why():
    out = in_criteria("""act('critToggleAnalysis');
      await act('critRename', {i: '0'}, {value: '聊吃饭<b>'});
      return [C().data.topics[0].topic, el('#toast').textContent, el('#cAnalysis').innerHTML.includes('value="讲合同"')];""",
                      {"POST /api/topics/rename": [400, {"error": "已经有叫「聊吃饭」的话题"}]})
    assert out == ["讲合同", "已经有叫「聊吃饭」的话题", True]


def test_rename_unchanged_or_gone_topic_sends_nothing():
    out = in_criteria("""act('critToggleAnalysis'); await act('critRename', {i: '0'}, {value: '讲合同'});
      await act('critRename', {i: '9'}, {value: 'x'}); return calls.filter(c => c.path === '/api/topics/rename').length;""")
    assert out == 0


def test_level_dropdown_posts_optimistically_and_pending_follows():
    out = in_criteria("""act('critToggleAnalysis'); act('critTopicToggle', {i: '0'});
      const p = act('critLevel', {i: '0'}, {value: '2'});
      const optimistic = [C().segs[0].level, queueIds()]; await p;
      return [optimistic, levelPosts()];""")
    assert out[0] == [2, ["S1", "S2", "S3", "S4"]]  # 甲改成待定 → 按时间排在最前
    assert out[1] == [{"project": "新项目", "id": "S1", "level": 2}]


def test_level_dropdown_failure_rolls_back_to_confirmed_state():
    out = in_criteria("""act('critToggleAnalysis'); act('critTopicToggle', {i: '0'});
      await act('critLevel', {i: '1'}, {value: '3'});
      return [C().segs[1].level, C().segs[1].level_reason, queueIds(), el('#toast').textContent];""",
                      {"POST /api/browse/level": [500, {"error": "炸了"}]})
    assert out[0] == 2 and out[1] == "不确定<i>" and out[2] == ["S2", "S3", "S4"] and "炸了" in out[3]


def test_level_dropdown_ignores_bad_values():
    out = in_criteria("""act('critToggleAnalysis'); act('critTopicToggle', {i: '0'});
      await act('critLevel', {i: '0'}, {value: '9'}); await act('critLevel', {i: '99'}, {value: '1'});
      return levelPosts().length;""")
    assert out == 0


# ---------------------------------------------------------------- 裁决待定
def test_pending_shows_first_by_time_with_text_reason_and_keys_escaped():
    html = in_criteria("return el('#cPending').innerHTML;")
    assert "还有 3 段待定" in html and "乙" in html and "不确定&lt;i&gt;" in html and "<i>" not in html
    assert "<kbd>A</kbd>" in html and "<kbd>D</kbd>" in html
    for act_name in ("critDecide", "critSkip", "critAiRest"):
        assert f'data-act="{act_name}"' in html


def test_pending_none_left_message():
    html = in_criteria("return el('#cPending').innerHTML;", {"GET /api/confirm": ALL_DECIDED})
    assert "没有待定的片段了" in html and "critDecide" not in html


def test_decide_usable_posts_level_three_and_moves_to_next_and_cues_player():
    out = in_criteria("""el('#cPv').paused = true;
      const p = act('critDecide', {level: '3'});
      const optimistic = [queueIds(), el('#cPending').innerHTML.includes('丙')]; await p;
      return [optimistic, levelPosts(), C().segs[1].level, el('#cPv').currentTime];""")
    assert out[0] == [["S3", "S4"], True]
    assert out[1] == [{"project": "新项目", "id": "S2", "level": 3}]
    assert out[2] == 3 and out[3] == 19.7  # 下一段（20 秒）入点前 0.3


def test_decide_waste_posts_level_one():
    out = in_criteria("await act('critDecide', {level: '1'}); return [levelPosts(), queueIds()];")
    assert out == [[{"project": "新项目", "id": "S2", "level": 1}], ["S3", "S4"]]


def test_decide_failure_puts_segment_back_in_front_with_reason():
    out = in_criteria("""await act('critDecide', {level: '3'});
      return [queueIds(), C().segs[1].level, el('#toast').textContent, el('#cPending').innerHTML.includes('不确定')];""",
                      {"POST /api/browse/level": [500, {"error": "写不进去"}]})
    assert out[0] == ["S2", "S3", "S4"] and out[1] == 2 and "写不进去" in out[2] and out[3] is True


def test_decide_with_nothing_pending_does_nothing():
    out = in_criteria("await act('critDecide', {level: '3'}); return levelPosts().length;",
                      {"GET /api/confirm": ALL_DECIDED})
    assert out == 0


def test_decide_updates_toc_and_wizard_from_response():
    from fe_harness import wizard
    stale = wizard(analyze="done", browse="done", criteria="available",
                   result=("stale", "素材标记改过了 · 重新选段", "reselect"), export="available")
    out = in_criteria("""await act('critDecide', {level: '3'});
      return [tocItems(C())[1].text, el('#steps').innerHTML.includes('⚠')];""",
                      {"POST /api/browse/level": {**OK_LEVEL, "wizard": stale}})
    assert out == ["还有 2 段待定", True]


def test_skip_moves_current_to_the_end_without_any_write():
    out = in_criteria("""act('critSkip'); const a = queueIds(); act('critSkip'); act('critSkip');
      return [a, queueIds(), levelPosts().length, el('#cPending').innerHTML.includes('还有 3 段待定')];""")
    assert out == [["S3", "S4", "S2"], ["S2", "S3", "S4"], 0, True]


def test_skip_with_single_item_keeps_it():
    out = in_criteria("act('critSkip'); return queueIds();",
                      {"GET /api/confirm": {**CONFIRM, "pending": CONFIRM["pending"][:1]}})
    assert out == ["S2"]


def test_pending_playback_stops_at_out_point_plus_pad_without_global_timer():
    out = in_criteria("""const pv = el('#cPv'); let paused = 0; pv.paused = false; pv.pause = () => { paused++; };
      cuePending(); const s = C().stopAt; pv.currentTime = 10; fire('#cPv', 'play'); const live = intervals.filter(i => !i.cleared).length;
      intervals[intervals.length - 1].fn(); pv.currentTime = 16.5; intervals[intervals.length - 1].fn();
      return [s, live, paused, C().stopAt];""")
    assert out[0] == 16.3 and out[1] == 1 and out[2] == 1 and out[3] is None


def test_manual_seek_past_out_point_is_not_stopped():
    out = in_criteria("""const pv = el('#cPv'); let paused = 0; pv.paused = false; pv.pause = () => { paused++; };
      cuePending(); fire('#cPv', 'play'); pv.currentTime = 12; intervals[intervals.length - 1].fn();
      fire('#cPv', 'seeking'); pv.currentTime = 40; intervals[intervals.length - 1].fn(); return paused;""")
    assert out == 0


# ---------------------------------------------------------------- 快捷键（沿用自定义键位）
def test_default_keys_decide_and_skip_in_criteria_view():
    out = in_criteria("""const a = await press('KeyA'); const d = await press('KeyD'); const n = await press('ArrowDown');
      return [levelPosts().map(b => [b.id, b.level]), a.prevented, d.prevented, queueIds()];""")
    assert out[0] == [["S2", 3], ["S3", 1]] and out[1] is True and out[2] is True and out[3] == ["S4"]


def test_custom_shortcuts_are_used_and_old_keys_stop_working():
    out = in_criteria("""state.shortcuts = {...state.shortcuts, mark_usable: 'KeyJ', mark_waste: 'KeyK'};
      await press('KeyA'); await press('KeyJ'); await press('KeyK');
      return levelPosts().map(b => [b.id, b.level]);""")
    assert out == [["S2", 3], ["S3", 1]]


def test_keys_ignored_while_typing_in_modal_or_with_repeat():
    out = in_criteria("""await press('KeyA', {target: {tagName: 'INPUT'}}); await press('KeyA', {repeat: true});
      el('#mask').classList.add('on'); await press('KeyA'); el('#mask').classList.remove('on');
      return levelPosts().length;""")
    assert out == 0


def test_keys_not_meant_for_criteria_are_left_to_the_browser():
    out = in_criteria("""const z = await press('KeyZ'); const s = await press('KeyS'); const x = await press('KeyX');
      return [z.prevented, s.prevented, x.prevented, levelPosts().length, calls.filter(c => c.path.startsWith('/api/browse/')).length];""")
    assert out == [False, False, False, 0, 0]


def test_space_toggles_player_but_not_when_a_button_has_focus():
    out = in_criteria("""const pv = el('#cPv'); let played = 0, paused = 0; pv.play = () => { played++; return Promise.resolve(); };
      pv.pause = () => { paused++; }; pv.paused = true;
      const e1 = await press('Space'); pv.paused = false; await press('Space');
      pv.paused = true; const e3 = await press('Space', {target: {tagName: 'BUTTON'}});
      return [played, paused, e1.prevented, e3.prevented];""")
    assert out == [1, 1, True, False]


def test_keys_do_nothing_on_other_steps():
    out = in_criteria("""state.view = 'export'; await press('KeyA'); return levelPosts().length;""")
    assert out == 0


# ---------------------------------------------------------------- P1：剩下的按 AI 建议
def test_ai_rest_asks_first_with_p1_copy_and_cancel_changes_nothing():
    out = in_criteria("""act('critAiRest'); const m = [el('#modalTitle').textContent, el('#modalBody').innerHTML, el('#mask').classList.contains('on')];
      closeModal(); return [m, C().aiRest, calls.filter(c => c.method === 'POST').length];""")
    assert "3 段" in out[0][0] and "先不进片" in out[0][1] and "不会替你标" in out[0][1]
    assert 'data-act="critAiRestGo"' in out[0][1] and "取消" in out[0][1]
    assert out[0][2] is True and out[1] is False and out[2] == 0


def test_ai_rest_writes_no_verdicts_and_marks_queue_handled_locally():
    out = in_criteria("""await act('critDecide', {level: '3'}); const before = calls.filter(c => c.method === 'POST').length;
      act('critAiRest'); act('critAiRestGo'); await tick();
      return [calls.filter(c => c.method === 'POST').length - before, C().aiRest, queueIds(),
              C().segs.filter(s => s.level === 2).map(s => s.id), el('#cPending').innerHTML,
              tocItems(C())[1], el('#mask').classList.contains('on')];""")
    assert out[0] == 0 and out[1] is True and out[2] == ["S3", "S4"] and out[3] == ["S3", "S4"]
    assert "剩下 2 段按 AI 建议：先不进片" in out[4] and "critDecide" not in out[4]
    assert out[5]["done"] is True and out[6] is False


def test_ai_rest_with_nothing_left_is_a_noop():
    out = in_criteria("act('critAiRest'); return el('#mask').classList.contains('on');",
                      {"GET /api/confirm": ALL_DECIDED})
    assert out is False
