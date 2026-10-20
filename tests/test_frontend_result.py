"""M14 T9/T10/T13：⑤ 看结果页面（node vm）：顶栏、改时长、预览片、闸门 B、分镜表、播放器、只读、步骤条 ✓。"""
import pytest

from fe_harness import NODE
from fe_result import (PREVIEW_FRESH, PREVIEW_NONE, PROJECT_Q, RESULT, RSTATE, SHOTS, in_result, js,
                       result_wizard, text_of)

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

OVER = {**RESULT["topbar"], "over_target": True, "must_total": 220, "suggested_target": 220}
BUSY_SELECT = {"id": "j9", "task": "select", "project": "新项目", "label": "重新选段"}


# ---------------------------------------------------------------- 顶栏
def test_landing_on_result_loads_api_result_once_and_shows_the_top_bar():
    paths, top = in_result("return [rcalls().map(c => c.path), el('#rTop').innerHTML];")
    assert paths == [f"/api/result?project={PROJECT_Q}"]
    assert "目标 3:00" in text_of(top) and "当前 2:58" in text_of(top) and "镜头 2" in text_of(top)
    assert "剪辑列表 6/6 进片 ✓" in text_of(top)
    assert 'data-act="editTarget"' in top and "data-starts-job" in top


def test_current_total_and_count_follow_local_edits_without_redrawing_the_top_bar():
    out = in_result("""state.shots[1].out = 138; state.shots.pop(); renderView();
      return [el('#rCur').textContent, el('#rCnt').textContent];""")
    assert out == ["1:40", "1"]


def test_clip_list_not_fully_covered_is_flagged():
    top = in_result("return el('#rTop').innerHTML;", result={"topbar": {
        **RESULT["topbar"], "clip": {"count": 6, "covered": 5, "missing": ["S4"]}}})
    assert "5/6 进片" in text_of(top) and "✓" not in text_of(top) and 'class="warn"' in top


def test_top_bar_numbers_are_sanitised_through_num():
    top = in_result("return el('#rTop').innerHTML;", result={"topbar": {
        **RESULT["topbar"], "target": "<img src=x>", "clip": {"count": "<b>", "covered": "1);alert(1)", "missing": []}}})
    assert "<img" not in top and "alert" not in top and "目标 0:00" in text_of(top)


def test_over_target_shows_warning_with_suggested_target_button():
    top = in_result("return el('#rTop').innerHTML;", result={"topbar": OVER})
    assert "剪辑列表共 3 分 40 秒，超过目标 3 分 0 秒 · 建议改为 3 分 40 秒" in text_of(top)
    assert 'data-act="applySuggested"' in top and "改为 3 分 40 秒" in text_of(top)


def test_no_over_target_warning_when_within_target_and_no_auto_modal_after_select():
    out = in_result("return [el('#rTop').innerHTML.includes('applySuggested'), el('#mask').classList.contains('on')];")
    assert out == [False, False]


def test_edit_target_opens_minutes_and_seconds_inline_and_cancel_restores():
    out = in_result("""act('editTarget'); const open = el('#rTop').innerHTML;
      act('cancelTarget'); return [open, el('#rTop').innerHTML];""")
    assert 'id="tgtMin"' in out[0] and 'id="tgtSec"' in out[0] and "applyTarget" in out[0] and "cancelTarget" in out[0]
    assert 'id="tgtMin"' not in out[1] and 'data-act="editTarget"' in out[1]


def test_apply_target_without_manual_edits_reselects_with_replace_and_no_prompt():
    out = in_result("""act('editTarget'); el('#tgtMin').value = '4'; el('#tgtSec').value = '30';
      await act('applyTarget'); await tick();
      return [jobs(), el('#mask').classList.contains('on')];""")
    assert out == [[{"project": "新项目", "task": "select", "target": 270, "manual": "replace"}], False]


def test_apply_target_rejects_out_of_range_without_any_request():
    out = in_result("""act('editTarget'); el('#tgtMin').value = '0'; el('#tgtSec').value = '5';
      await act('applyTarget'); return [jobs().length, el('#toast').textContent];""")
    assert out[0] == 0 and "10 秒到 60 分钟" in out[1]


def test_apply_suggested_reselects_with_the_suggested_target():
    out = in_result("await act('applySuggested'); await tick(); return jobs();", result={"topbar": OVER})
    assert out == [{"project": "新项目", "task": "select", "target": 220, "manual": "replace"}]


# ---------------------------------------------------------------- 预览片
def test_preview_none_offers_manual_generation_and_no_player():
    out = in_result("return [el('#rPvNote').innerHTML, el('#rVideo').innerHTML];")
    assert "还没有预览片" in out[0] and 'data-act="makePreview" data-starts-job' in out[0] and "生成预览片" in out[0]
    assert "<video" not in out[1]


def test_fresh_preview_plays_current_preview_url():
    out = in_result("return [el('#rVideo').innerHTML, el('#rPvNote').innerHTML, R().mode];",
                    result={"preview": PREVIEW_FRESH})
    assert "<video" in out[0] and f'src="/media/{PROJECT_Q}/current-preview?v=2026-10-20T14%3A02%3A00"' in out[0]
    assert "makePreview" not in out[1] and out[2] == "preview"


@pytest.mark.parametrize("reasons, copy", [(["table"], "分镜表改过了 · 重新生成预览片"),
                                           (["unusable"], "有片段标成了不可用 · 重新生成预览片")])
def test_outdated_preview_says_why_and_offers_regeneration(reasons, copy):
    out = in_result("return [el('#rPvNote').innerHTML, el('#rVideo').innerHTML];",
                    result={"preview": {**PREVIEW_FRESH, "status": "outdated", "reasons": reasons}})
    assert copy in out[0] and 'data-act="makePreview"' in out[0] and "<video" in out[1]


def test_server_preview_url_is_escaped():
    out = in_result("return el('#rVideo').innerHTML;",
                    result={"preview": {**PREVIEW_FRESH, "url": '/x"><script>alert(1)</script>'}})
    assert "<script>" not in out


def test_make_preview_saves_pending_edits_first_then_starts_job_without_log_window():
    out = in_result("""state.shots[0].sub = '改了'; scheduleSave();
      await act('makePreview'); await tick();
      return [calls.filter(c => c.method === 'POST').map(c => c.path), jobs(), el('#mask').classList.contains('on')];""")
    assert out[0] == ["/api/shots?project=" + PROJECT_Q, "/api/job"]
    assert out[1] == [{"project": "新项目", "task": "preview"}] and out[2] is False


def test_make_preview_does_not_start_when_save_failed():
    out = in_result("""state.shots[0].sub = '改了'; scheduleSave();
      await act('makePreview'); await tick(); return [jobs().length, el('#toast').textContent];""",
                    routes={"POST /api/shots": [500, {"error": "写不进去"}]})
    assert out[0] == 0 and "分镜表还没保存成功" in out[1]


def test_make_preview_refuses_an_empty_shot_table():
    out = in_result("await act('makePreview'); return [jobs().length, el('#toast').textContent];",
                    state={"shots": []})
    assert out[0] == 0 and "分镜表" in out[1]


def test_finished_preview_job_reloads_result_and_shows_the_preview():
    done = {"GET /api/job/": {"status": "done", "task": "preview", "log": [], "elapsed_s": 3, "project": "新项目"}}
    out = in_result(f"""const fresh = {js({**RESULT, 'preview': PREVIEW_FRESH})}; let n = 0;
      window.__respond = (m, p, b) => (m === 'GET' && p.startsWith('/api/result') && ++n > 0) ? [200, fresh] : respond(m, p, b);
      await act('makePreview');
      for (let i = 0; i < 4; i++) await runTimers();
      return [rcalls().length, el('#rVideo').innerHTML.includes('<video'), R().mode, el('#toast').textContent];""",
                    routes=done)
    assert out[0] == 2 and out[1] is True and out[2] == "preview" and out[3] == "预览片已生成"


# ---------------------------------------------------------------- 闸门 B
def test_gate_b_is_disabled_until_the_current_table_has_a_preview():
    nav = in_result("return el('#nav').innerHTML;")
    assert "看过了，去导出 →" in nav and 'aria-disabled="true"' in nav and "先生成当前分镜表的预览片" in nav
    assert 'data-step="export"' not in nav


def test_gate_b_clicked_while_disabled_only_explains():
    out = in_result("await act('gateBHint'); return [el('#toast').textContent, state.view];")
    assert out == ["先生成当前分镜表的预览片", "result"]


def test_gate_b_is_enabled_with_a_fresh_preview_and_goes_to_export():
    nav = in_result("return el('#nav').innerHTML;", result={"preview": PREVIEW_FRESH})
    assert 'data-act="go" data-step="export"' in nav and 'aria-disabled="true"' not in nav.split("看过了")[0].split("<button")[-1]


def test_gate_b_follows_the_server_state_before_result_loads():
    nav = in_result("return el('#nav').innerHTML;", state={"preview": {"status": "fresh"}},
                    routes={"GET /api/result": [500, {"error": "炸了"}]})
    assert 'data-act="go" data-step="export"' in nav


# ---------------------------------------------------------------- 步骤条 ✓（T13）与旧响应
def test_step_bar_shows_done_mark_when_result_payload_says_the_step_is_done():
    out = in_result("return el('#steps').innerHTML;",
                    result={"preview": PREVIEW_FRESH, "wizard": result_wizard(result="done")})
    assert "⑤看结果 ✓" in out


LATE_SETUP = """const bumped = JSON.parse(JSON.stringify(%s)); bumped.topbar.target = 999;
  const orig = window.fetch, held = []; let armed = true;
  window.fetch = (p, o) => (armed && String(p).startsWith('/api/result'))
    ? (armed = false, new Promise(r => held.push(() => r(orig(p, o)))))
    : orig(p, o);
  window.__respond = (m, p, b) => (m === 'GET' && p.startsWith('/api/result') ? [200, bumped] : respond(m, p, b));"""


def test_late_result_response_after_leaving_the_step_is_dropped():
    out = in_result(LATE_SETUP % js(RESULT) + """
      loadResult(); await tick();
      await go('browse');
      held.forEach(r => r()); await tick(); await tick();
      return R().data.topbar.target;""")
    assert out == 180


def test_late_result_response_for_another_project_is_dropped():
    out = in_result(LATE_SETUP % js(RESULT) + """
      loadResult(); await tick();
      window.__respond = (m, p, b) => respond(m, p, b);   // 新项目拿到的是正常数据
      await selectProject('别的项目'); await tick(); await tick();
      held.forEach(r => r()); await tick(); await tick();
      return [state.project, R().data.topbar.target];""")
    assert out == ["别的项目", 180]


def test_result_load_failure_is_explained_and_the_table_still_works():
    out = in_result("return [el('#toast').textContent, el('#rTable').innerHTML.includes('textarea')];",
                    routes={"GET /api/result": [409, {"error": "素材标记文件损坏<b>"}]})
    assert "素材标记文件损坏<b>" in out[0] and out[1] is True


# ---------------------------------------------------------------- 分镜表（T10）
def test_each_row_has_editable_subtitle_why_topic_and_alternatives_count_all_escaped():
    html = in_result("return el('#rTable').innerHTML;")
    assert html.count("<textarea") == 2 and 'data-input="editSub"' in html
    assert "&lt;b&gt;字幕&lt;/b&gt;" in html and "<b>字幕</b>" not in html
    assert "为什么选它：含金额&lt;b&gt;" in html and "讲合同" in html and "<b>含金额" not in html
    assert "▸ 替代句 1" in html and html.count("替代句") == 1  # sh02 没有替代句
    assert "为什么选它：手动添加" in html


def test_rows_without_notes_do_not_show_the_why_line():
    html = in_result("return el('#rTable').innerHTML;", result={"notes": {}})
    assert "为什么选它" not in html and "替代句" not in html


def test_expanding_alternatives_toggles_only_that_row_without_redrawing_the_table():
    out = in_result("""const before = el('#rTable').innerHTML;
      act('toggleAlt', {i: '0'});
      return [el('#alt0').classList.contains('open'), el('#rTable').innerHTML === before];""")
    assert out == [True, True]


def test_alternative_rows_offer_audition_and_add_back_with_escaped_text():
    html = in_result("return el('#rTable').innerHTML;")
    assert 'data-act="audition" data-id="U1"' in html and 'data-act="addBack" data-id="U1"' in html
    assert "替代&lt;i&gt;句" in html


def test_picking_a_row_switches_to_material_mode_and_seeks_to_its_in_point():
    out = in_result("""act('pick', {i: '1'});
      return [R().mode, el('#rVideo').innerHTML, el('#rPv').currentTime, el('#rTools').innerHTML];""")
    assert out[0] == "material" and f"/media/{PROJECT_Q}/proxy" in out[1] and out[2] == 100
    assert 'data-act="mark" data-which="in"' in out[3] and 'data-which="out"' in out[3] and 'data-act="playSel"' in out[3]


def test_switching_back_to_the_preview_hides_the_in_out_buttons():
    out = in_result("""act('pick', {i: '0'}); act('playerMode', {mode: 'preview'});
      return [R().mode, el('#rTools').innerHTML];""", result={"preview": PREVIEW_FRESH})
    assert out == ["preview", ""]


def test_mark_in_and_out_save_the_current_position_of_the_material_player():
    out = in_result("""act('pick', {i: '0'}); el('#rPv').currentTime = 12.5; await act('mark', {which: 'in'});
      el('#rPv').currentTime = 40; await act('mark', {which: 'out'}); await tick();
      return [state.shots[0].in, state.shots[0].out, shotPosts().length];""")
    assert out == [12.5, 40, 2]


def test_mark_without_a_selected_row_asks_to_select_one():
    out = in_result("await act('mark', {which: 'in'}); return [el('#toast').textContent, shotPosts().length];")
    assert out == ["先在分镜表里选中一行", 0]


def test_audition_current_shot_stops_at_its_out_point_using_timeupdate_not_a_timer():
    out = in_result("""act('pick', {i: '0'}); let paused = 0; el('#rPv').pause = () => { paused++; };
      act('playSel'); el('#rPv').currentTime = 50; fire('#rPv', 'timeupdate');
      const mid = paused; el('#rPv').currentTime = 100; fire('#rPv', 'timeupdate');
      return [mid, paused, intervals.length];""")
    assert out == [0, 1, 0]


def test_reorder_delete_duplicate_blank_and_sort_go_through_the_save_queue():
    out = in_result("""await act('move', {i: '0', d: '1'}); await tick();
      await act('dup', {i: '0'}); await tick();
      await act('del', {i: '2'}); await tick();
      await act('addBlank'); await tick(); await act('sortShots'); await tick();
      return shotPosts().map(b => b.shots.map(s => s.id));""")
    assert out[0] == ["sh02", "sh01"] and len(out) == 5
    assert out[1] == ["sh02", "sh03", "sh01"] and out[2] == ["sh02", "sh03"]


def test_table_is_repainted_after_structural_edits_but_not_by_a_plain_refresh():
    out = in_result("""el('#rTable').innerHTML = 'SENTINEL'; renderView(); const plain = el('#rTable').innerHTML;
      await act('del', {i: '1'}); await tick(); return [plain, el('#rTable').innerHTML.includes('textarea')];""")
    assert out == ["SENTINEL", True]


def test_refresh_while_typing_never_repaints_the_table_and_keeps_the_typed_text():
    out = in_result("""state.shots[0].sub = '正在输入'; scheduleSave();
      el('#rTable').innerHTML = 'SENTINEL'; renderView(); return [el('#rTable').innerHTML, state.shots[0].sub];""")
    assert out == ["SENTINEL", "正在输入"]


def test_player_is_not_rebuilt_on_every_render():
    out = in_result("el('#rVideo').innerHTML = 'SENTINEL'; renderView(); renderView(); return el('#rVideo').innerHTML;")
    assert out == "SENTINEL"


def test_each_successful_save_reloads_result_but_burst_saves_reload_once():
    out = in_result("""const before = rcalls().length;
      await act('del', {i: '1'}); await tick(); await act('dup', {i: '0'}); await tick();
      const mid = rcalls().length; await runTimers(); await tick();
      return [mid - before, rcalls().length - before];""")
    assert out == [0, 1]


def test_failed_save_does_not_reload_result():
    out = in_result("""const before = rcalls().length; await act('del', {i: '1'}); await tick(); await runTimers();
      return rcalls().length - before;""", routes={"POST /api/shots": [500, {"error": "写不进去"}]})
    assert out == 0


def test_empty_table_points_to_browse_and_keeps_blank_shot_entry():
    html = in_result("return el('#rTable').innerHTML;", state={"shots": []})
    assert "分镜表还是空的" in html and 'data-act="go" data-step="browse"' in html and 'data-act="addBlank"' in html


# ---------------------------------------------------------------- E10：重新选段期间只读
def test_table_is_read_only_while_a_select_job_runs():
    html = in_result("return el('#rTable').innerHTML;", state={"busy": BUSY_SELECT})
    assert html.count("readonly") == 2 and "正在重新选段，完成后再改分镜表" in html
    assert "disabled" in html and 'data-act="addBlank"' in html


def test_table_is_editable_again_when_the_select_job_is_gone():
    out = in_result("""state.data = {...state.data, busy: null}; syncResultLock(); return el('#rTable').innerHTML;""",
                    state={"busy": BUSY_SELECT})
    assert "readonly" not in out and "正在重新选段" not in out


def test_other_tasks_do_not_lock_the_table():
    html = in_result("return el('#rTable').innerHTML;",
                     state={"busy": {**BUSY_SELECT, "task": "preview", "label": "生成预览片"}})
    assert "readonly" not in html


def test_edit_attempts_while_locked_are_ignored():
    out = in_result("""await act('del', {i: '0'}); await act('move', {i: '0', d: '1'}); await act('sortShots');
      return [state.shots.length, shotPosts().length];""", state={"busy": BUSY_SELECT})
    assert out == [2, 0]


# ---------------------------------------------------------------- /api/shots 409
def test_stale_409_refreshes_the_page_and_busy_409_keeps_edits_and_retries_later():
    stale = in_result("""await act('del', {i: '1'}); await tick(); await runTimers(); await tick();
      return calls.filter(c => c.path.startsWith('/api/state')).length;""",
                      routes={"POST /api/shots": [409, {"error": "选段刚刚被覆盖", "stale": True}]})
    assert stale >= 2  # 进入项目一次 + 过期后重新读取
    out = in_result("""await act('del', {i: '1'}); await tick();
      return [state.shots.length, el('#toast').textContent, timers.some(t => t.fn && t.ms >= 1000)];""",
                    routes={"POST /api/shots": [409, {"error": "正在重新选段，完成后再改分镜表"}]})
    assert out[0] == 1 and "正在重新选段" in out[1] and out[2] is True


# ---------------------------------------------------------------- 任务文案与完成后的刷新（jobs.js）
SELECT_DONE = {"GET /api/job/": {"status": "done", "task": "select", "log": [], "elapsed_s": 3, "project": "新项目"}}


def test_preview_task_has_titles_labels_and_done_text():
    out = in_result("return [JOB_TITLES.preview, JOB_LABELS.preview, JOB_DONE.preview, MODAL_TASKS.has('preview')];")
    assert out == ["正在生成预览片", "生成预览片", "预览片已生成", False]


def test_select_job_finishing_no_longer_pops_the_target_dialog_even_when_over_target():
    over_state = {"selection": {"over_target": True, "must_keep_total": 220, "suggested_target": 220}}
    out = in_result("""await startJob('select', {manual: 'replace'});
      for (let i = 0; i < 4; i++) await runTimers();
      return [el('#mask').classList.contains('on'), el('#modalTitle').textContent, el('#toast').textContent];""",
                    routes=SELECT_DONE, state=over_state)
    assert out[0] is False and "超过目标" not in out[1] and out[2] == "已重新选段"


def test_select_job_finishing_on_result_reloads_result_and_repaints_the_new_table():
    new_shots = [{"id": "sel01", "in": 5, "out": 15, "sub": "新的 AI 字幕", "note": ""}]
    out = in_result(f"""const before = rcalls().length; let done = false;
      window.__respond = (m, p, b) => (m === 'GET' && p.startsWith('/api/state') && done)
        ? [200, {{...state.data, shots: {js(new_shots)}}}] : (m === 'GET' && p.startsWith('/api/job/') && (done = true))
        ? respond(m, p, b) : respond(m, p, b);
      await startJob('select', {{manual: 'replace'}});
      for (let i = 0; i < 5; i++) await runTimers();
      return [rcalls().length - before, el('#rTable').innerHTML.includes('新的 AI 字幕'), state.shots.map(s => s.id)];""",
                    routes=SELECT_DONE)
    assert out == [1, True, ["sel01"]]


def test_starting_preview_job_with_unsaved_edits_saves_them_first():
    out = in_result("""state.shots[0].sub = '改了'; scheduleSave(); await startJob('preview');
      return calls.filter(c => c.method === 'POST').map(c => c.path.split('?')[0]);""")
    assert out == ["/api/shots", "/api/job"]


def test_gate_b_turns_off_at_once_when_the_table_is_edited_locally():
    out = in_result("""const before = el('#nav').innerHTML.includes('data-step="export"');
      await act('del', {i: '1'}); const after = el('#nav').innerHTML;
      return [before, after.includes('data-step="export"'), after.includes('aria-disabled="true"')];""",
                    result={"preview": PREVIEW_FRESH})
    assert out == [True, False, True]


def test_buttons_painted_by_a_late_result_load_are_greyed_while_another_task_runs():
    out = in_result("""const b = node({'data-starts-job': ''}); lists['[data-starts-job]'] = [b];
      state.data = {...state.data, busy: {id: 'j7', task: 'prepare', project: '别的项目', label: '分析'}};
      await loadResult(); return [b.disabled, b.attrs.title];""")
    assert out[0] is True and "正在分析" in out[1]
