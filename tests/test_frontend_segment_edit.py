"""③ 编辑起止弹窗（node vm）：快捷键 E / 按钮、手柄与输入框联动、校验、保存 / 恢复 / 加入列表、撤销、关闭清理。"""
import pytest

from fe_browse import BROWSE, CLIP, STALE_WIZARD, in_browse, js, mark_ok, seg
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

OPEN = "act('jumpSeg', {i: '1'}); await press('KeyE'); const V = el('#seVideo'); "   # S2：10–16，窗口 0–26
SLIDE = "const slide = (w, v) => act('segEditSlider', {which: w}, {value: String(v)}); "
TYPE = "const type = (w, t) => act('segEditText', {which: w}, {value: t}); "
PRE = OPEN + SLIDE + TYPE + """const SECOND = (s, e) => ({ok: true, cleared: null, manual_table: false, clip_list: B().clip, wizard: null,
  segment: {id: 'S2', start: s, end: e, dur: e - s, base_start: 10, base_end: 16, bounds_edited: !(s === 10 && e === 16)}}); """


def bounds_ok(start, end, base=(10, 16), **extra):
    edited = (start, end) != base
    return mark_ok({"id": "S2", "start": start, "end": end, "dur": round(end - start, 2), "base_start": base[0],
                    "base_end": base[1], "bounds_edited": edited, "level": 2, "level_reason": "不确定",
                    "override": False, "must_keep": extra.pop("must_keep", False), "unusable": False},
                   manual_table=extra.pop("manual_table", False), **extra)


def run(script, routes=None):
    return in_browse(PRE + script, {"POST /api/browse/bounds": bounds_ok(11, 17), **(routes or {})})


# ---------------------------------------------------------------- 打开
def test_e_opens_modal_only_with_current_segment_in_browse():
    out = in_browse("""await press('KeyE'); const none = state.modalKind;
      act('jumpSeg', {i: '1'}); await press('KeyE');
      return [none, state.modalKind, el('#mask').classList.contains('on'), el('#seVideo').src, el('#seVideo').currentTime];""")
    assert out == [None, "segedit", True, "/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/proxy", 10]


def test_e_does_not_open_while_typing_or_in_other_view():
    out = in_browse("""act('jumpSeg', {i: '1'});
      await press('KeyE', {target: {tagName: 'INPUT'}}); const typing = state.modalKind;
      state.view = 'result'; await press('KeyE'); return [typing, state.modalKind];""")
    assert out == [None, None]


def test_edit_button_in_now_panel_opens_modal_and_pauses_main_player():
    out = in_browse("""act('jumpSeg', {i: '1'}); const html = el('#bNow').innerHTML;
      let paused = 0; el('#bPv').pause = () => { paused++; };
      act('editBounds'); return [html.includes('data-act="editBounds"'), state.modalKind, paused];""")
    assert out == [True, "segedit", 1]


def test_visual_segment_opens_and_saves():
    v = {**seg(1, 3, 8, 2, "画面", "", reason=""), "id": "V001", "kind": "visual", "label": "走廊"}
    data = {**BROWSE, "segments": [*BROWSE["segments"], v]}
    out = in_browse("""act('jumpSeg', {i: '5'}); await press('KeyE'); act('segEditSlider', {which: 'start'}, {value: '4'});
      act('segEditSave'); await tick(); await tick(); return posts();""",
                    {"GET /api/browse": data, "POST /api/browse/bounds": bounds_ok(4, 8)})
    assert out == [["/api/browse/bounds", {"project": "新项目", "id": "V001", "start": 4, "end": 8}]]


# ---------------------------------------------------------------- 手柄与输入框
def test_slider_range_is_base_plus_minus_10s_clamped_to_material():
    out = run("return [el('#seStart').min, el('#seStart').max, el('#seLo').textContent, el('#seHi').textContent];")
    assert out == [0, 26, "0:00.0", "0:26.0"]
    out = in_browse("""act('jumpSeg', {i: '4'}); await press('KeyE'); return [el('#seEnd').min, el('#seEnd').max];""")
    assert out == [40, 60]   # S5 50–55：下限 40，上限被总长 60 截住


def test_material_duration_falls_back_to_video_then_last_segment():
    data = {**BROWSE, "material_duration": 0}
    out = in_browse("""act('jumpSeg', {i: '4'}); await press('KeyE'); const a = el('#seEnd').max;
      el('#seVideo').duration = 52; el('#seVideo').listeners.loadedmetadata.forEach(f => f()); return [a, el('#seEnd').max, B().data.material_duration];""",
                    {"GET /api/browse": data})
    assert out == [55, 52, 0] or out == [55, 55, 0]


def test_slider_updates_inputs_and_seeks():
    out = run("""slide('start', 12.3); const a = [el('#seStartTxt').value, V.currentTime];
      slide('end', 20); return [a, el('#seEndTxt').value, el('#seDur').textContent, V.currentTime, V.listeners.seeking.length > 0];""")
    assert out[0] == ["0:12.3", 12.3] and out[1] == "0:20.0" and "7.7" in out[2] and out[3] == 19


def test_dragging_end_only_seeks_and_plays_to_end_on_release():
    out = run("""let played = 0, paused = 0; V.play = () => { played++; return Promise.resolve(); }; V.pause = () => { paused++; };
      const before = intervals.length; slide('end', 20); slide('end', 21);
      const dragging = [played, V.currentTime, intervals.length - before];
      act('segEditSliderDone', {which: 'end'}, {value: '21'}); const iv = intervals[intervals.length - 1];
      V.currentTime = 20; iv.fn(); V.currentTime = 21.05; iv.fn();
      return [dragging, played, iv.cleared];""")
    assert out == [[0, 20, 0], 1, True]


def test_releasing_start_handle_does_not_play():
    out = run("""let played = 0; V.play = () => { played++; return Promise.resolve(); };
      slide('start', 12); act('segEditSliderDone', {which: 'start'}, {value: '12'}); return played;""")
    assert out == 0


def test_play_selection_button_plays_start_to_end_and_stops():
    out = run("""let played = 0, paused = 0; V.play = () => { played++; return Promise.resolve(); }; V.pause = () => { paused++; };
      act('segEditPlay'); const start = V.currentTime; const iv = intervals[intervals.length - 1];
      V.currentTime = 11; iv.fn(); const mid = paused; V.currentTime = 16.1; iv.fn(); return [start, played, mid, paused, iv.cleared];""")
    assert out == [10, 1, 0, 1, True]


def test_inputs_sync_slider_and_parse_both_formats():
    out = run("""type('start', '0:12.5'); const a = [el('#seStart').value];
      type('end', '20'); a.push(el('#seEnd').value, el('#seErr').textContent); return a;""")
    assert out == [12.5, 20, ""]


@pytest.mark.parametrize("text,sec", [("1:02.3", 62.3), ("62.3", 62.3), ("0:05", 5), ("1：02", 62), ("12", 12)])
def test_parse_time(text, sec):
    assert abs(run_app(f"parseTime({js(text)})", files=["common.js", "base.js", "segment-edit.js"]) - sec) < 1e-9


@pytest.mark.parametrize("text", ["", "abc", "1:75", "-3", "1:2:3"])
def test_parse_time_rejects(text):
    assert run_app(f"Number.isNaN(parseTime({js(text)}))") is True


def test_fmt_ms_rounds_to_tenths():
    assert run_app("[fmtMS(62.34), fmtMS(59.96), fmtMS(0), fmtMS(8), fmtMS(59.95), fmtMS(59.999)]") == ["1:02.34", "0:59.96", "0:00.0", "0:08.0", "0:59.95", "1:00.0"]


def test_input_may_exceed_slider_window_but_slider_clamps():
    out = run("type('end', '0:40'); return [el('#seEnd').value, el('#seErr').textContent, el('#seSave').disabled];")
    assert out == [26, "", False]


# ---------------------------------------------------------------- 校验
@pytest.mark.parametrize("w,t,msg", [("start", "abc", "时间格式"), ("start", "-1", "时间格式"), ("end", "10.2", "至少 0.5 秒"),
                                      ("end", "1:10", "素材总长"), ("start", "17", "至少 0.5 秒")])
def test_invalid_input_shows_error_and_disables_saves(w, t, msg):
    out = run(f"type({js(w)}, {js(t)}); return [el('#seErr').textContent, el('#seSave').disabled, el('#seSaveList').disabled, el('#sePlay').disabled];")
    assert msg in out[0] and out[1:] == [True, True, True]


def test_save_is_refused_while_invalid_and_recovers_when_fixed():
    out = run("""type('end', '10.1'); act('segEditSave'); await tick(); const bad = [posts().length, state.modalKind];
      type('end', '17'); return [bad, el('#seSave').disabled, el('#seErr').textContent];""")
    assert out == [[0, "segedit"], False, ""]


def test_start_below_zero_via_slider_never_crosses_end():
    out = run("slide('start', 25); return [el('#seStartTxt').value, el('#seErr').textContent];")
    assert out == ["0:15.5", ""]


# ---------------------------------------------------------------- 保存
def test_save_posts_start_end_and_merges_into_row_now_density_and_clip():
    out = run("""slide('start', 11); slide('end', 17); act('segEditSave'); await tick(); await tick();
      const s = B().segs[1];
      return [posts(), s.start, s.end, s.dur, s.bounds_edited, state.modalKind, el('#r1').classList.contains('edited'),
              el('#tc1').textContent, el('#du1').textContent, el('#ed1').attrs.title, el('#bNow').innerHTML.includes('00:11.0'),
              el('#d1').style.width, el('#d1').attrs.title];""")
    assert out[0] == [["/api/browse/bounds", {"project": "新项目", "id": "S2", "start": 11, "end": 17}]]
    assert out[1:] == [11, 17, 6, True, None, True, "00:11.0", "6.0s", "原始 0:10.0–0:16.0", True, "10.000%", "00:11.0 待定 · 讲合同"]


def test_save_and_add_to_list_posts_must_and_updates_clip_list():
    clip = {**CLIP, "items": [*CLIP["items"], {"id": "S2", "start": 11, "end": 17, "dur": 6, "topic": "讲合同", "text": "乙"}], "total": 11}
    out = run("""slide('start', 11); slide('end', 17); act('segEditSaveList'); await tick(); await tick();
      return [posts(), B().segs[1].must_keep, B().clip.items.map(i => i.id), el('#bPanel').innerHTML.includes('00:11.0')];""",
              {"POST /api/browse/bounds": {**bounds_ok(11, 17, must_keep=True), "clip_list": clip}})
    assert out[0] == [["/api/browse/bounds", {"project": "新项目", "id": "S2", "start": 11, "end": 17, "must": True}]]
    assert out[1:] == [True, ["S4", "S2"], True]


def test_restore_original_posts_nulls_after_edit():
    out = in_browse(PRE + """
      let n = 0; window.__respond = (m, p, body) => m === 'POST' && p === '/api/browse/bounds'
        ? [200, ++n === 1 ? SECOND(11, 17) : SECOND(10, 16)] : respond(m, p);
      slide('start', 11); slide('end', 17); act('segEditSave'); await tick(); await tick();
      act('editBounds'); const fields = [el('#seStartTxt').value, el('#seEndTxt').value];
      act('segEditReset'); const after = [el('#seStartTxt').value, el('#seEndTxt').value];
      act('segEditSave'); await tick(); await tick();
      return [fields, after, posts().pop()[1], B().segs[1].bounds_edited, el('#r1').classList.contains('edited')];""",
                    {})
    assert out == [["0:11.0", "0:17.0"], ["0:10.0", "0:16.0"], {"project": "新项目", "id": "S2", "start": None, "end": None}, False, False]


def test_save_without_change_closes_without_request():
    out = run("act('segEditSave'); await tick(); return [posts(), state.modalKind];")
    assert out == [[], None]


def test_save_and_add_without_bounds_change_only_marks_list():
    out = run("act('segEditSaveList'); await tick(); await tick(); return posts().map(p => p[0]);",
              {"POST /api/browse/must": mark_ok({"id": "S2", "must_keep": True})})
    assert out == ["/api/browse/must"]


def test_manual_table_notice_is_shown():
    out = run("""slide('start', 11); act('segEditSave'); await tick(); await tick(); return el('#toast').textContent;""",
              {"POST /api/browse/bounds": bounds_ok(11, 16, manual_table=True)})
    assert "⑤ 的分镜表是手动改过的，去 ④ 重新选段后新起止才会生效" in out


def test_failed_save_rolls_back_and_toasts():
    out = run("""slide('start', 11); act('segEditSave'); await tick(); await tick();
      return [B().segs[1].start, B().segs[1].bounds_edited, el('#toast').textContent, el('#tc1').textContent];""",
              {"POST /api/browse/bounds": [409, {"error": "起止不合法"}]})
    assert out[0] == 10 and not out[1] and "起止不合法" in out[2] and out[3] == "00:10.0"


def test_warning_response_with_null_fields_keeps_optimistic_value_and_resyncs():
    edited = {**BROWSE, "segments": [BROWSE["segments"][0], {**BROWSE["segments"][1], "start": 11, "dur": 5, "bounds_edited": True},
                                      *BROWSE["segments"][2:]]}
    out = run("""const seen = []; const orig = toast; toast = (m, ms) => { seen.push(m); orig(m, ms); };
      const plain = window.__respond;   // 保存之后服务端才是新值
      window.__respond = (m, p, b) => m === 'GET' && p.startsWith('/api/browse?') ? [200, EDITED] : respond(m, p);
      slide('start', 11); act('segEditSave'); await tick(); await tick(); await tick(); await tick();
      return [B().segs[1].start, seen.join('|'), B().segs[1].bounds_edited];""".replace("EDITED", js(edited)),
              {"POST /api/browse/bounds": {"ok": True, "segment": None, "clip_list": None, "wizard": None, "warning": "已保存，但刷新失败"}})
    assert out == [11, "已保存，但刷新失败", True]


def test_missing_base_fields_count_as_unedited():
    out = run("return [B().segs[1].base_start, null, baseOf(B().segs[1])];")
    assert out[2] == {"start": 10, "end": 16}


# ---------------------------------------------------------------- 撤销
def test_undo_posts_previous_bounds_or_nulls_when_previously_unedited():
    out = in_browse(PRE + """
      let n = 0; window.__respond = (m, p, body) => m === 'POST' && p === '/api/browse/bounds'
        ? [200, ++n === 1 ? SECOND(11, 17) : n === 2 ? SECOND(12, 17) : SECOND(11, 17)] : respond(m, p);
      slide('start', 11); slide('end', 17); act('segEditSave'); await tick(); await tick();
      act('editBounds'); slide('start', 12); act('segEditSave'); await tick(); await tick();
      await press('KeyZ'); await tick(); const first = [posts().pop()[1], B().segs[1].start];
      await press('KeyZ'); await tick(); await tick();
      return [first, posts().pop()[1], B().segs[1].start, B().segs[1].bounds_edited];""", {})
    assert out[0] == [{"project": "新项目", "id": "S2", "start": 11, "end": 17}, 11]
    assert out[1] == {"project": "新项目", "id": "S2", "start": None, "end": None}


# ---------------------------------------------------------------- 关闭
def test_close_stops_video_releases_src_and_clears_interval():
    out = run("""slide('end', 20); act('segEditSliderDone', {which: 'end'}, {value: '20'}); const iv = intervals[intervals.length - 1]; let paused = 0; V.pause = () => { paused++; };
      closeModal(); return [paused, V.attrs.src ?? 'gone', V.loaded, iv.cleared, state.segEdit, state.modalKind];""")
    assert out[0] == 1 and out[2] >= 1 and out[3:] == [True, None, None]


def test_escape_and_replacing_modal_also_clean_up():
    out = run("""const iv = () => intervals[intervals.length - 1]; slide('end', 20); act('segEditSliderDone', {which: 'end'}, {value: '20'});
      showModal('别的', 'x'); return [iv().cleared, state.segEdit];""")
    assert out == [True, None]


def test_text_is_escaped_in_modal():
    out = in_browse("act('jumpSeg', {i: '0'}); await press('KeyE'); return el('#modalBody').innerHTML;")
    assert "<b>粗体</b>" not in out and "&lt;b&gt;" in out


# ---------------------------------------------------------------- 评审修复
def test_browse_reset_or_reload_closes_modal_and_stops_video():
    out = run("""slide('end', 20); act('segEditSliderDone', {which: 'end'}, {value: '20'}); const iv = intervals[intervals.length - 1]; let paused = 0; V.pause = () => { paused++; };
      resetBrowse(); return [state.modalKind, state.segEdit, paused, iv.cleared, el('#mask').classList.contains('on')];""")
    assert out == [None, None, 1, True, False]


def test_changing_step_closes_modal():
    out = run("state.view = 'criteria'; renderView(); return [state.modalKind, state.segEdit];")
    assert out == [None, None]


def test_save_on_stale_state_closes_toasts_and_posts_nothing():
    out = run("""slide('start', 11); state.browse = {...B()};   // 浏览状态被换成另一个对象，但没人通知弹窗
      act('segEditSave'); await tick(); return [posts(), state.modalKind, el('#toast').textContent];""")
    assert out == [[], None, "片段列表刚刷新，请重新打开编辑"]


def test_two_decimal_rounding_matches_server_for_short_pair():
    out = run("""type('start', '0.2'); type('end', '0.7'); const ok = [B().segs ? el('#seErr').textContent : null, el('#seSave').disabled];
      type('end', '0.69'); return [ok, el('#seErr').textContent.includes('至少'), el('#seSave').disabled];""")
    assert out == [["", False], True, True]


def test_values_are_rounded_to_two_decimals_before_validation_and_send():
    out = run("""type('start', '11.004'); type('end', '16.996'); act('segEditSave'); await tick(); await tick(); return posts();""",
              {"POST /api/browse/bounds": bounds_ok(11, 17)})
    assert out == [["/api/browse/bounds", {"project": "新项目", "id": "S2", "start": 11, "end": 17}]]


def test_drag_to_collision_keeps_exact_half_second_gap():
    out = run("""type('end', '16.3'); slide('start', 16.2); const s = el('#seStartTxt').value;
      return [s, B().segs[1].start, el('#seErr').textContent, el('#seSave').disabled];""")
    assert out == ["0:15.8", 10, "", False]
    out = run("""type('end', '16.3'); slide('start', 16.2); act('segEditSave'); await tick(); await tick(); return posts()[0][1];""")
    assert out["start"] == 15.8 and out["end"] == 16.3


def test_slider_grid_is_tenths_and_values_shown_equal_values_sent():
    data = {**BROWSE, "segments": [seg(1, 12.34, 18.76, 2, "讲合同", "乙")], "material_duration": 30}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE');
      const r = el('#seStart'); const g = [r.min, r.max, el('#seEnd').max];
      act('segEditSlider', {which: 'start'}, {value: '18.2'}); return [g, el('#seStartTxt').value, ed().start];
      function ed(){ return state.segEdit; }""", {"GET /api/browse": data})
    assert out == [[2.3, 28.8, 28.8], "0:18.2", 18.2]


def test_end_handle_reaches_exact_material_end_when_not_on_grid():
    data = {**BROWSE, "segments": [seg(1, 50, 55, 2, "x", "乙")], "material_duration": 59.95}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE');
      const max = el('#seEnd').max; act('segEditSlider', {which: 'end'}, {value: String(max)});
      return [max, el('#seEndTxt').value, el('#seErr').textContent, state.segEdit.end, el('#seHi').textContent];""", {"GET /api/browse": data})
    assert out == [60, "0:59.95", "", 59.95, "1:00.0"]


def test_displayed_max_limit_is_accepted_when_typed():
    data = {**BROWSE, "segments": [seg(1, 50, 55, 2, "x", "乙")], "material_duration": 59.999}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE'); act('segEditText', {which: 'end'}, {value: '1:00'});
      const err = el('#seErr').textContent; const m = /总长 (\\S+)/.exec(err)[1];
      act('segEditText', {which: 'end'}, {value: m}); return [err, m, el('#seErr').textContent];""", {"GET /api/browse": data})
    assert out[1] == "0:59.99" and out[2] == ""


def test_aria_valuetext_and_initial_focus():
    out = run("""slide('start', 12.5); return [el('#seStart').attrs['aria-valuetext'], el('#seEnd').attrs['aria-valuetext']];""")
    assert out == ["0:12.5", "0:16.0"]


def test_modal_focuses_start_input_on_open():
    out = in_browse("""act('jumpSeg', {i: '1'}); let focused = 0; el('#seStartTxt').focus = () => { focused++; };
      act('editBounds'); return focused;""")
    assert out == 1


def test_unbound_edit_key_hides_hint_in_now_panel():
    out = in_browse("""state.shortcuts = {...state.shortcuts, edit: ''}; act('jumpSeg', {i: '1'}); await press('KeyE');
      return [el('#bNow').innerHTML.includes('<kbd>'), state.modalKind];""")
    assert out == [False, None]   # 没有键位：按 E 也不会打开
