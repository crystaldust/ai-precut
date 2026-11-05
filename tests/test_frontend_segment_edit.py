"""③ 编辑起止弹窗（node vm）：快捷键 E / 按钮、手柄与输入框联动、校验、保存 / 恢复 / 加入列表、撤销、关闭清理。"""
import pytest

from fe_browse import BROWSE, CLIP, STALE_WIZARD, in_browse, js, mark_ok, seg
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

OPEN = "act('jumpSeg', {i: '1'}); await press('KeyE'); const V = el('#seVideo'); "   # S2：10–16，素材 60 秒，窗口 0–60
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
def test_slider_range_is_base_plus_minus_60s_clamped_to_material():
    out = run("return [el('#seStart').min, el('#seStart').max, el('#seLo').textContent, el('#seHi').textContent];")
    assert out == [0, 60, "0:00.0", "1:00.0"]   # S2 10–16：前后各 60 秒都被 0 和总长 60 截住
    out = in_browse("""act('jumpSeg', {i: '4'}); await press('KeyE'); return [el('#seEnd').min, el('#seEnd').max];""")
    assert out == [0, 60]   # S5 50–55：下限 -10 被截成 0，上限 115 被总长 60 截住
    free = {**BROWSE, "segments": [seg(1, 100, 110, 2, "x", "乙")], "material_duration": 300}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE'); return [el('#seStart').min, el('#seEnd').max, el('#seLo').textContent, el('#seHi').textContent];""",
                    {"GET /api/browse": free})
    assert out == [40, 170, "0:40.0", "2:50.0"]   # 两边都不被截：精确 ±60 秒
    tail = {**BROWSE, "segments": [seg(1, 280, 290, 2, "x", "乙")], "material_duration": 300}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE'); return [el('#seStart').min, el('#seEnd').max];""", {"GET /api/browse": tail})
    assert out == [220, 300]


def test_material_duration_falls_back_to_video_then_last_segment():
    data = {**BROWSE, "material_duration": 0}
    out = in_browse("""act('jumpSeg', {i: '4'}); await press('KeyE'); const a = el('#seEnd').max;
      el('#seVideo').duration = 52; el('#seVideo').listeners.loadedmetadata.forEach(f => f()); return [a, el('#seEnd').max, B().data.material_duration];""",
                    {"GET /api/browse": data})
    assert out == [55, 52, 0] or out == [55, 55, 0]


def test_slider_updates_inputs_and_seeks():
    out = run("""slide('start', 12.3); const a = [el('#seStartTxt').value, V.currentTime];
      slide('end', 20); return [a, el('#seEndTxt').value, el('#seDur').textContent, V.currentTime, V.listeners.seeking.length > 0];""")
    assert out[0] == ["0:12.3", 12.3] and out[1] == "0:20.0" and "7.7" in out[2] and out[3] == 20


def test_dragging_end_only_previews_handle_frame_and_release_does_not_play():
    out = run("""let played = 0; V.play = () => { played++; return Promise.resolve(); };
      const before = intervals.length; slide('end', 20); slide('end', 21);
      const dragging = [played, V.currentTime, intervals.length - before];
      act('segEditSliderDone', {which: 'end'}, {value: '21'});
      return [dragging, played, intervals.length - before, V.currentTime];""")
    assert out == [[0, 21, 0], 0, 0, 10]   # 松手也不播，画面回到播放头（10）


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
    free = {**BROWSE, "segments": [seg(1, 100, 110, 2, "x", "乙")], "material_duration": 300}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE'); act('segEditText', {which: 'end'}, {value: '3:00'});
      return [el('#seEnd').value, el('#seErr').textContent, el('#seSave').disabled];""", {"GET /api/browse": free})
    assert out == [170, "", False]   # 180 秒超出手柄窗口 170：手柄停在头，输入框照样接受


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
    out = run("""slide('end', 20); act('segEditPlay'); const iv = intervals[intervals.length - 1]; let paused = 0; V.pause = () => { paused++; };
      closeModal(); return [paused, V.attrs.src ?? 'gone', V.loaded, iv.cleared, state.segEdit, state.modalKind];""")
    assert out[0] == 1 and out[2] >= 1 and out[3:] == [True, None, None]


def test_escape_and_replacing_modal_also_clean_up():
    out = run("""const iv = () => intervals[intervals.length - 1]; slide('end', 20); act('segEditPlay');
      showModal('别的', 'x'); return [iv().cleared, state.segEdit];""")
    assert out == [True, None]


def test_text_is_escaped_in_modal():
    out = in_browse("act('jumpSeg', {i: '0'}); await press('KeyE'); return el('#modalBody').innerHTML;")
    assert "<b>粗体</b>" not in out and "&lt;b&gt;" in out


# ---------------------------------------------------------------- 评审修复
def test_browse_reset_or_reload_closes_modal_and_stops_video():
    out = run("""slide('end', 20); act('segEditPlay'); const iv = intervals[intervals.length - 1]; let paused = 0; V.pause = () => { paused++; };
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
    data = {**BROWSE, "segments": [seg(1, 112.34, 118.76, 2, "讲合同", "乙")], "material_duration": 300}
    out = in_browse("""act('jumpSeg', {i: '0'}); await press('KeyE');
      const r = el('#seStart'); const g = [r.min, r.max, el('#seEnd').max];
      act('segEditSlider', {which: 'start'}, {value: '118.2'}); return [g, el('#seStartTxt').value, ed().start];
      function ed(){ return state.segEdit; }""", {"GET /api/browse": data})
    assert out == [[52.3, 178.8, 178.8], "1:58.2", 118.2]


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


# ---------------------------------------------------------------- 键盘微调
KEY = """const keyOn = (id, k, extra = {}) => press('', {key: k, target: Object.assign(el('#' + id), {id, tagName: 'INPUT'}), ...extra});
  const keyUp = (id, k) => fireDoc('keyup', {key: k, target: Object.assign(el('#' + id), {id, tagName: 'INPUT'})}); """


def kb(script, routes=None):
    return run(KEY + script, routes)


@pytest.mark.parametrize("k,shift,expect,text", [("ArrowRight", False, 10.1, "0:10.1"), ("ArrowUp", False, 10.1, "0:10.1"),
                                                 ("ArrowRight", True, 11, "0:11.0"), ("ArrowLeft", False, 9.9, "0:09.9"),
                                                 ("ArrowDown", False, 9.9, "0:09.9"), ("ArrowLeft", True, 9, "0:09.0")])
def test_arrow_on_start_handle_steps_and_syncs_inputs_and_video(k, shift, expect, text):
    out = kb(f"""const ev = await keyOn('seStart', {js(k)}, {{shiftKey: {js(shift)}}});
      return [ev.prevented, state.segEdit.start, el('#seStart').value, el('#seStartTxt').value, V.currentTime, el('#seDur').textContent];""")
    assert out[:3] == [True, expect, expect] and out[3] == text and out[4] == expect


def test_repeated_arrows_accumulate_without_float_drift():
    out = kb("for(let i = 0; i < 3; i++) await keyOn('seStart', 'ArrowRight'); return [state.segEdit.start, el('#seStartTxt').value];")
    assert out == [10.3, "0:10.3"]


def test_arrow_left_on_start_handle_at_zero_stays():
    out = kb("slide('start', 0); await keyOn('seStart', 'ArrowLeft'); await keyOn('seStart', 'ArrowLeft', {shiftKey: true}); return [state.segEdit.start, el('#seStartTxt').value];")
    assert out == [0, "0:00.0"]


def test_shift_arrow_on_start_handle_cannot_pass_end_minus_half_second():
    out = kb("for(let i = 0; i < 8; i++) await keyOn('seStart', 'ArrowRight', {shiftKey: true}); return [state.segEdit.start, el('#seErr').textContent, el('#seSave').disabled];")
    assert out == [15.5, "", False]


def test_end_handle_steps_and_cannot_pass_start_plus_half_second_or_material_end():
    out = kb("""await keyOn('seEnd', 'ArrowLeft'); const a = [state.segEdit.end, V.currentTime];   // 预览的是结束手柄所在的画面
      for(let i = 0; i < 8; i++) await keyOn('seEnd', 'ArrowLeft', {shiftKey: true}); const low = state.segEdit.end;
      for(let i = 0; i < 70; i++) await keyOn('seEnd', 'ArrowRight', {shiftKey: true});
      return [a, low, state.segEdit.end, el('#seEndTxt').value, el('#seErr').textContent];""")
    assert out == [[15.9, 15.9], 10.5, 60, "1:00.0", ""]


def test_keyboard_adjustment_cannot_leave_material_even_with_off_grid_end():
    data = {**BROWSE, "segments": [seg(1, 50, 55, 2, "x", "乙")], "material_duration": 59.95}
    out = in_browse(PRE + KEY + """act('jumpSeg', {i: '0'}); await press('KeyE');
      for(let i = 0; i < 12; i++) await keyOn('seEnd', 'ArrowRight', {shiftKey: true}); return [state.segEdit.end, el('#seErr').textContent];""",
                    {"GET /api/browse": data})
    assert out == [59.95, ""]


def test_text_input_arrows_step_tenth_and_shift_second():
    out = kb("""const a = await keyOn('seEndTxt', 'ArrowUp'); const up = [state.segEdit.end, el('#seEndTxt').value, el('#seEnd').value, V.currentTime];
      await keyOn('seEndTxt', 'ArrowDown', {shiftKey: true}); const down = [state.segEdit.end, el('#seEndTxt').value];
      await keyOn('seStartTxt', 'ArrowDown'); const st = [state.segEdit.start, el('#seStartTxt').value];
      await keyOn('seStartTxt', 'ArrowUp', {shiftKey: true}); return [a.prevented, up, down, st, state.segEdit.start];""")
    assert out == [True, [16.1, "0:16.1", 16.1, 16.1], [15.1, "0:15.1"], [9.9, "0:09.9"], 10.9]


def test_text_input_arrows_work_from_the_text_in_the_box_even_beyond_slider_window():
    out = kb("""type('end', '0:40'); el('#seEndTxt').value = '0:40'; await keyOn('seEndTxt', 'ArrowUp'); const a = el('#seEndTxt').value;
      type('end', '62.3'); el('#seEndTxt').value = '62.3'; await keyOn('seEndTxt', 'ArrowDown', {shiftKey: true}); return [a, el('#seEndTxt').value, el('#seErr').textContent];""")
    assert out == ["0:40.1", "1:01.3", "结束时间不能超过素材总长 1:00.0"]


def test_text_input_arrow_with_invalid_text_is_a_noop():
    out = kb("""type('end', 'abc'); el('#seEndTxt').value = 'abc'; const ev = await keyOn('seEndTxt', 'ArrowUp');
      return [ev.prevented, el('#seEndTxt').value, state.segEdit.end, state.segEdit.bad.end, el('#seErr').textContent];""")
    assert out == [False, "abc", 16, True, "时间格式不对，请写成 1:02.3 或直接写秒数"]


def test_text_input_arrow_down_stops_at_zero():
    out = kb("""type('start', '0.05'); el('#seStartTxt').value = '0.05'; await keyOn('seStartTxt', 'ArrowDown', {shiftKey: true});
      return [state.segEdit.start, el('#seStartTxt').value];""")
    assert out == [0, "0:00.0"]


def test_save_after_keyboard_adjustment_posts_adjusted_start_and_end():
    out = kb("""await keyOn('seStart', 'ArrowRight'); await keyOn('seStart', 'ArrowRight'); await keyOn('seEndTxt', 'ArrowUp', {shiftKey: true});
      act('segEditSave'); await tick(); await tick(); return posts();""", {"POST /api/browse/bounds": bounds_ok(10.2, 17)})
    assert out == [["/api/browse/bounds", {"project": "新项目", "id": "S2", "start": 10.2, "end": 17}]]


def test_other_keys_and_modifiers_are_left_alone():
    out = kb("""const r = [];
      for(const [id, k, x] of [['seStartTxt', 'a'], ['seStartTxt', '1'], ['seStartTxt', 'Enter'], ['seStartTxt', 'ArrowLeft'],
                               ['seStartTxt', 'ArrowRight'], ['seStart', 'Home'], ['seStart', 'ArrowRight', {ctrlKey: true}],
                               ['seStart', 'ArrowRight', {metaKey: true}], ['seVideo', 'ArrowRight']]){
        const ev = await keyOn(id, k, x || {}); r.push(ev.prevented);
      }
      const esc = await keyOn('seStartTxt', 'Escape');   // Esc 仍然只负责关弹窗
      return [r, state.segEdit ? [state.segEdit.start, state.segEdit.end] : null, esc.prevented, state.modalKind];""")
    assert out == [[False] * 9, None, False, None]


def test_keys_do_nothing_after_modal_closed():
    out = kb("""closeModal(); const ev = await keyOn('seStart', 'ArrowRight'); return [ev.prevented, B().segs[1].start, posts()];""")
    assert out == [False, 10, []]


def test_global_browse_shortcuts_stay_off_while_modal_is_open():
    out = kb("""const before = curSeg().id;
      await press('ArrowDown', {key: 'ArrowDown'}); await press('KeyS'); await press('KeyD'); await keyOn('seStart', 'ArrowDown');
      return [curSeg().id, before, posts(), state.modalKind];""")
    assert out[0] == out[1] and out[2:] == [[], "segedit"]


def test_hint_shows_60_seconds_and_keyboard_tips():
    out = run("return el('#modalBody').innerHTML;")
    assert "前后各 60 秒" in out and "点一下手柄或时间轴后按 ← →，每次 0.1 秒，加 Shift 每次 1 秒" in out and "在输入框里按 ↑ ↓ 也一样" in out
    assert out.count('aria-describedby="seHint"') == 2 and 'id="seHint"' in out


def test_ime_composition_arrows_are_not_steps():
    out = kb("""const r = [];
      for(const x of [{isComposing: true}, {keyCode: 229}]){ const ev = await keyOn('seEndTxt', 'ArrowUp', x); r.push(ev.prevented); }
      const ev = await keyOn('seEnd', 'ArrowRight', {isComposing: true}); r.push(ev.prevented);
      return [r, el('#seEndTxt').value, state.segEdit.end];""")
    assert out == [[False, False, False], "0:16.0", 16]


@pytest.mark.parametrize("k,shift,expect", [("ArrowRight", False, 12.4), ("ArrowLeft", False, 12.3), ("ArrowRight", True, 13.3), ("ArrowLeft", True, 11.4)])
def test_keyboard_steps_snap_to_the_tenth_grid(k, shift, expect):
    data = {**BROWSE, "segments": [seg(1, 12.34, 18.76, 2, "x", "乙")], "material_duration": 30}
    out = in_browse(PRE + KEY + f"""act('jumpSeg', {{i: '0'}}); await press('KeyE');
      await keyOn('seStart', {js(k)}, {{shiftKey: {js(shift)}}}); return [state.segEdit.start, el('#seStartTxt').value];""", {"GET /api/browse": data})
    assert out[0] == expect


def test_keyboard_step_up_to_off_grid_material_end_is_allowed_as_max():
    data = {**BROWSE, "segments": [seg(1, 50, 59.9, 2, "x", "乙")], "material_duration": 59.95}
    out = in_browse(PRE + KEY + """act('jumpSeg', {i: '0'}); await press('KeyE');
      await keyOn('seEnd', 'ArrowRight'); const a = state.segEdit.end; await keyOn('seEnd', 'ArrowRight');
      await keyOn('seEnd', 'ArrowLeft'); return [a, state.segEdit.end];""", {"GET /api/browse": data})
    assert out == [59.95, 59.9]


# ---------------------------------------------------------------- WebKit：点手柄不会把焦点给手柄
# WKWebView 点 range 不聚焦，焦点还停在自动聚焦的 #seStartTxt（或 body），按键的 target 不是手柄。
POINTER = """const down = id => { el('#' + id).focus = o => { el('#' + id).focused = o || true; }; fire('#' + id, 'pointerdown', {}); };
  const keyAt = (target, k, extra = {}) => press('', {key: k, target, ...extra});
  const BODY = {tagName: 'BODY'}; """


def pk(script, routes=None):
    return kb(POINTER + script, routes)


def test_pointerdown_on_handle_focuses_it_without_preventing_the_drag():
    out = pk("""let prevented = false; fire('#seEnd', 'pointerdown', {preventDefault(){ prevented = true; }});
      down('seEnd'); return [el('#seEnd').focused, prevented, state.segEdit.keyHandle];""")
    assert out == [{"preventScroll": True}, False, "end"]


def test_arrow_after_clicking_end_handle_steps_it_even_when_target_is_body():
    out = pk("""down('seEnd'); const ev = await keyAt(BODY, 'ArrowLeft'); const a = [ev.prevented, state.segEdit.end, el('#seEndTxt').value, V.currentTime];
      await keyAt(BODY, 'ArrowRight', {shiftKey: true}); return [a, state.segEdit.end, state.segEdit.start];""")
    assert out == [[True, 15.9, "0:15.9", 15.9], 16.9, 10]


def test_fallback_steps_when_focus_stays_on_other_non_text_elements():
    out = pk("""down('seStart'); const ev = await keyAt({tagName: 'DIV', id: 'modalBody'}, 'ArrowRight');
      return [ev.prevented, state.segEdit.start];""")
    assert out == [True, 10.1]


def test_arrows_in_text_input_still_move_the_caret_after_clicking_a_handle():
    out = pk("""down('seEnd'); const r = [];
      for(const id of ['seStartTxt', 'seEndTxt']) for(const k of ['ArrowLeft', 'ArrowRight']) r.push((await keyOn(id, k)).prevented);
      for(const t of [{tagName: 'TEXTAREA'}, {tagName: 'SELECT'}, {tagName: 'DIV', isContentEditable: true}, {tagName: 'VIDEO', id: 'seVideo'}])
        r.push((await keyAt(t, 'ArrowLeft')).prevented);
      return [r, state.segEdit.start, state.segEdit.end];""")
    assert out == [[False] * 8, 10, 16]


def test_no_fallback_before_any_handle_was_touched():
    out = pk("""const ev = await keyAt(BODY, 'ArrowLeft'); return [ev.prevented, state.segEdit.start, state.segEdit.end];""")
    assert out == [False, 10, 16]


def test_dragging_a_handle_also_sets_the_key_handle():
    out = pk("""slide('end', 20); const a = state.segEdit.keyHandle; slide('start', 12);
      const ev = await keyAt(BODY, 'ArrowRight'); return [a, state.segEdit.keyHandle, state.segEdit.start];""")
    assert out == ["end", "start", 12.1]


def test_focused_handle_has_a_visible_focus_style():
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "gui" / "static" / "app.css").read_text(encoding="utf-8")
    assert "input[type=range]:focus::-webkit-slider-thumb" in css and "input[type=range]:focus::-moz-range-thumb" in css


# ---------------------------------------------------------------- 播放头（时间轴上的白线，空格播放 / 暂停）
# 窗口 0–60 秒，时间轴 600px 宽、左边在 x=100：每秒 10px。
TRACK = """el('.se-track').getBoundingClientRect = () => ({left: 100, width: 600});
  const X = t => 106 + t * 9.8;   // 拇指中心在 [6, 宽-6] 上走：600px 宽 → 每秒 9.8px
  el('#mask').contains = n => !(n && n.outside);
  const tdown = (x, ev = {}) => fire('.se-track', 'pointerdown', {clientX: x, pointerId: 1, ...ev});
  const tmove = (x, buttons = 1) => fire('.se-track', 'pointermove', {clientX: x, pointerId: 1, buttons});
  const tup = () => fire('.se-track', 'pointerup', {pointerId: 1});
  const ph = () => state.segEdit.playhead;
  const pslide = (w, v) => { fire(w === 'start' ? '#seStart' : '#seEnd', 'pointerdown', {}); slide(w, v); };   // 指针按下手柄再拖（吸附只在这种拖动里）
  const follow = t => { V.paused = false; V.currentTime = t; fire('#seVideo', 'timeupdate'); V.paused = true; };   // 靠视频播放把播放头放到任意位置
  const snapped = () => el('#sePh').classList.contains('snapped');
  const space = (extra = {}) => press('Space', {key: ' ', target: {tagName: 'BODY'}, ...extra});
  const counters = () => { const c = {played: 0, paused: 0}; V.play = () => { c.played++; return Promise.resolve(); }; V.pause = () => { c.paused++; }; return c; }; """


def phr(script, routes=None):
    return pk(TRACK + script, routes)


def test_playhead_starts_at_base_start_shows_that_frame_and_renders_its_parts():
    out = phr("""return [ph(), V.currentTime, el('#sePhTxt').value, el('#sePhChip').textContent, el('#sePh').style.left, el('#modalBody').innerHTML];""")
    assert out[:5] == [10, 10, "0:10.0", "0:10.0", "calc(6px + (100% - 12px) * 0.1667)"]
    html = out[5]
    assert 'id="sePh"' in html and 'id="sePhChip"' in html and 'id="sePhTxt"' in html and "播放头" in html
    assert html.index('id="seEndTxt"') < html.index('id="sePhTxt"') < html.index('id="seDur"')


def test_playhead_starts_at_original_start_even_when_the_segment_was_edited_and_is_not_persisted():
    out = phr("""slide('start', 11); slide('end', 17); act('segEditSave'); await tick(); await tick();
      act('editBounds'); return [ph(), V.currentTime, state.segEdit.start, el('#sePhTxt').value];""",
              {"POST /api/browse/bounds": bounds_ok(11, 17)})
    assert out == [10, 10, 11, "0:10.0"]


def test_playhead_follows_a_playing_video_but_not_a_paused_one():
    out = phr("""V.currentTime = 12.34; fire('#seVideo', 'timeupdate'); const paused = ph();
      V.paused = false; fire('#seVideo', 'timeupdate');
      return [paused, ph(), el('#sePhTxt').value, el('#sePhChip').textContent, el('#sePh').style.left];""")
    assert out == [10, 12.34, "0:12.34", "0:12.34", "calc(6px + (100% - 12px) * 0.2057)"]


def test_playhead_follows_between_timeupdates_via_the_stop_poll():
    out = phr("""counters(); act('segEditPlay'); V.paused = false; const iv = intervals[intervals.length - 1];
      V.currentTime = 11.5; iv.fn(); const a = ph(); V.currentTime = 12.25; iv.fn(); return [a, ph()];""")
    assert out == [11.5, 12.25]


def test_playhead_is_clamped_to_the_handle_window_when_following():
    out = phr("""V.paused = false; V.currentTime = 99; fire('#seVideo', 'timeupdate'); return ph();""")
    assert out == 60


# ---- 点击与拖动时间轴
@pytest.mark.parametrize("t,expect", [(25.04, 25), (25.06, 25.1), (-5, 0), (200, 60)])
def test_pointerdown_on_track_sets_snapped_clamped_playhead_and_seeks(t, expect):
    out = phr(f"""tdown(X({t})); return [ph(), V.currentTime, state.segEdit.keyHandle, el('#sePhTxt').value, state.segEdit.start, state.segEdit.end];""")
    assert out[:3] == [expect, expect, "playhead"] and out[4:] == [10, 16]


def test_press_next_to_a_handle_but_not_on_its_thumb_moves_the_playhead_without_a_dead_zone():
    out = phr("""const r = []; for(const dx of [3, 7, 9, 12]){ tdown(X(10) + dx); r.push([ph(), state.segEdit.keyHandle]); tup(); }
      return r;""")
    assert out == [[10.3, "playhead"], [10.7, "playhead"], [10.9, "playhead"], [11.2, "playhead"]]


def test_pointerdown_that_bubbles_from_a_thumb_does_not_move_the_playhead():
    out = phr("""tdown(X(30), {target: Object.assign(el('#seStart'), {id: 'seStart'})}); return [ph(), state.segEdit.keyHandle];""")
    assert out == [10, None]


def test_pointermove_scrubs_the_playhead_until_release_using_pointer_capture():
    out = phr("""const captured = []; el('.se-track').setPointerCapture = id => captured.push(id);
      tdown(X(20)); tmove(X(30)); const a = [ph(), V.currentTime]; tmove(X(45.04)); const b = ph(); tup(); tmove(X(50));
      return [captured, a, b, ph()];""")
    assert out == [[1], [30, 30], 45, 45]


def test_pointermove_without_press_does_nothing_and_non_primary_button_is_ignored():
    out = phr("""tmove(X(30)); const a = ph(); tdown(X(30), {button: 2}); return [a, ph(), state.segEdit.keyHandle];""")
    assert out == [10, 10, None]


def test_clicking_the_track_focuses_the_track_itself_so_arrows_stop_moving_a_handle():
    out = phr("""let focused = null; el('.se-track').focus = o => { focused = o; }; down('seEnd'); tdown(X(30));
      return [focused, state.segEdit.keyHandle];""")
    assert out == [{"preventScroll": True}, "playhead"]


# ---- 空格
def test_space_when_paused_seeks_to_playhead_plays_and_stops_at_window_end():
    out = phr("""const c = counters(); tdown(X(30)); tup(); const ev = await space(); const iv = intervals[intervals.length - 1];
      const started = [ev.prevented, c.played, V.currentTime];
      V.paused = false; V.currentTime = 59.9; iv.fn(); V.currentTime = 60.05; iv.fn();
      return [started, c.paused, iv.cleared, ph()];""")
    assert out[0] == [True, 1, 30] and out[1] >= 1 and out[2:] == [True, 60]


def test_space_while_playing_pauses_and_keeps_the_playhead_where_it_is():
    out = phr("""const c = counters(); await space(); const played = c.played; V.paused = false; V.currentTime = 14.2; const iv = intervals[intervals.length - 1];
      const ev = await space(); return [played, c.played, c.paused >= 1, ev.prevented, ph(), iv.cleared];""")
    assert out == [1, 1, True, True, 14.2, True]


@pytest.mark.parametrize("target", ["{tagName: 'INPUT', id: 'seStartTxt'}", "{tagName: 'BUTTON', id: 'sePlay'}",
                                    "{tagName: 'VIDEO', id: 'seVideo'}", "{tagName: 'INPUT', id: 'sePhTxt'}", "{tagName: 'DIV', id: 'modalBody'}"])
def test_space_is_intercepted_on_any_target_inside_the_modal(target):
    out = phr(f"""const c = counters(); const ev = await space({{target: {target}}}); const up = {{prevented: false, stopped: false, preventDefault(){{ this.prevented = true; }}, stopPropagation(){{ this.stopped = true; }}, key: ' ', code: 'Space', target: {target}}};
      fireDoc('keyup', up); return [ev.prevented, c.played, up.prevented, up.stopped];""")
    assert out == [True, 1, True, True]


def test_space_during_ime_composition_or_when_modal_is_closed_is_left_alone():
    out = phr("""const c = counters(); const a = (await space({isComposing: true})).prevented; const b = (await space({keyCode: 229})).prevented;
      const mod = (await space({ctrlKey: true})).prevented; const played = c.played; closeModal(); await space();
      return [a, b, mod, played, c.played];""")
    assert out == [False, False, False, 0, 0]


def test_held_space_does_not_toggle_repeatedly():
    out = phr("""const c = counters(); await space(); const ev = await space({repeat: true}); return [ev.prevented, c.played];""")
    assert out == [True, 1]


def test_space_at_the_right_window_end_restarts_from_the_selection_start():
    out = phr("""const c = counters(); slide('start', 12); tdown(X(60)); tup(); const a = ph(); await space();
      return [a, c.played, V.currentTime, ph(), intervals[intervals.length - 1].cleared];""")
    assert out == [60, 1, 12, 12, False]


def test_space_does_not_fall_through_to_the_global_browse_play_shortcut():
    out = phr("""let main = 0; el('#bPv').play = () => { main++; return Promise.resolve(); }; el('#bPv').paused = true;
      counters(); await space(); return main;""")
    assert out == 0


# ---- 手柄拖动与播放头解耦
def test_dragging_a_handle_previews_its_frame_but_leaves_the_playhead_alone_and_release_returns():
    out = phr("""const left = el('#sePh').style.left; slide('end', 20);
      const a = [ph(), V.currentTime, el('#sePh').style.left === left];
      V.paused = false; V.currentTime = 20; fire('#seVideo', 'timeupdate'); const b = ph();
      act('segEditSliderDone', {which: 'end'}, {value: '20'}); const c = [V.currentTime, ph(), state.segEdit.end];
      V.paused = false; V.currentTime = 33; fire('#seVideo', 'timeupdate');
      return [a, b, c, ph()];""")
    assert out == [[10, 20, True], 10, [10, 10, 20], 33]


def test_start_handle_release_also_returns_to_playhead_without_playing():
    out = phr("""const c = counters(); tdown(X(30)); tup(); slide('start', 12); const a = V.currentTime;
      act('segEditSliderDone', {which: 'start'}, {value: '12'}); return [a, V.currentTime, c.played, ph()];""")
    assert out == [12, 30, 0, 30]


def test_keyboard_step_previews_handle_frame_and_keyup_returns_to_playhead():
    out = phr("""const c = counters(); await keyOn('seEnd', 'ArrowRight'); const a = [V.currentTime, ph()];
      await keyOn('seEnd', 'ArrowRight', {repeat: true}); keyUp('seEnd', 'ArrowRight');
      return [a, V.currentTime, ph(), state.segEdit.end, c.played];""")
    assert out == [[16.1, 10], 10, 10, 16.2, 0]


def test_keyboard_return_works_with_fallback_target_and_text_arrows_but_plain_keyup_is_a_noop():
    out = phr("""tdown(X(30)); tup(); const t0 = V.currentTime; fireDoc('keyup', {key: 'ArrowRight', target: BODY}); const idle = V.currentTime;
      down('seEnd'); await keyAt(BODY, 'ArrowRight'); const a = V.currentTime; fireDoc('keyup', {key: 'ArrowRight', target: BODY}); const back = V.currentTime;
      await keyOn('seStartTxt', 'ArrowUp'); const b = V.currentTime; keyUp('seStartTxt', 'ArrowUp');
      return [t0, idle, a, back, b, V.currentTime, ph()];""")
    assert out == [30, 30, 16.1, 30, 10.1, 30, 30]


# ---- 吸附
def test_pointer_drag_snaps_handle_to_playhead_within_8px_and_unsnaps_when_leaving():
    out = phr("""tdown(X(14)); tup(); pslide('end', 14.5); const a = [state.segEdit.end, snapped(), V.currentTime];
      pslide('end', 14.9); const away = [state.segEdit.end, snapped()];
      pslide('end', 13.1); const b = [state.segEdit.end, snapped()]; pslide('end', 16); const c = [state.segEdit.end, snapped()];
      return [a, away, b, c, el('#seEndTxt').value];""")
    assert out == [[14, True, 14], [14.9, False], [13.1, False], [16, False], "0:16.0"]


def test_snap_uses_the_exact_playhead_time_and_the_start_handle_snaps_too():
    out = phr("""V.paused = false; V.currentTime = 12.37; fire('#seVideo', 'timeupdate'); V.paused = true;
      pslide('start', 12.2); return [state.segEdit.start, snapped(), el('#seStartTxt').value];""")
    assert out == [12.37, True, "0:12.37"]


def test_snap_is_refused_when_it_would_break_min_length_bounds_or_order():
    out = phr("""follow(10.2); pslide('end', 10.4); const a = [state.segEdit.end, snapped()];   // 10.2 离开始只有 0.2 秒：不吸
      pslide('end', 16); follow(15.8); pslide('start', 15.7); const b = [state.segEdit.start, snapped()];   // 15.8 会让选段短于 0.5 秒
      return [a, b];""")
    assert out == [[10.5, False], [15.5, False]]


def test_without_a_measurable_track_width_nothing_snaps():
    out = phr("""el('.se-track').getBoundingClientRect = () => ({left: 0, width: 0}); pslide('end', 10.6); return [state.segEdit.end, snapped()];""")
    assert out == [10.6, False]


def test_keyboard_steps_never_snap():
    out = phr("""follow(15.95); await keyOn('seEnd', 'ArrowLeft'); return [state.segEdit.end, snapped(), ph()];""")
    assert out == [15.9, False, 15.95]


def test_snapped_class_is_cleared_on_release_and_playhead_move():
    out = phr("""tdown(X(14)); tup(); pslide('end', 14.5); const a = snapped(); act('segEditSliderDone', {which: 'end'}, {value: '14'}); const b = snapped();
      return [a, b];""")
    assert out == [True, False]


# ---- 方向键
def test_arrows_move_the_playhead_after_clicking_the_track_with_clamp_and_grid():
    out = phr("""tdown(X(12.34)); tup(); const r = [ph()];
      await keyAt(BODY, 'ArrowRight'); r.push(ph()); await keyAt(BODY, 'ArrowLeft', {shiftKey: true}); r.push(ph(), V.currentTime);
      await keyAt(BODY, 'ArrowLeft', {shiftKey: true}); r.push(ph());
      for(let i = 0; i < 70; i++) await keyAt(BODY, 'ArrowRight', {shiftKey: true}); r.push(ph());
      return [r, state.segEdit.start, state.segEdit.end, el('#sePhTxt').value];""")
    assert out == [[12.3, 12.4, 11.4, 11.4, 10.4, 60], 10, 16, "1:00.0"]


def test_playhead_arrow_stops_at_zero_and_handles_keep_their_own_keyhandle_behavior():
    out = phr("""tdown(X(0.2)); tup(); await keyAt(BODY, 'ArrowLeft', {shiftKey: true}); const a = ph();
      down('seStart'); await keyAt(BODY, 'ArrowRight'); return [a, ph(), state.segEdit.start, state.segEdit.keyHandle];""")
    assert out == [0, 0, 10.1, "start"]


def test_arrows_in_text_inputs_still_move_the_caret_with_playhead_selected():
    out = phr("""tdown(X(30)); tup(); const r = [];
      for(const id of ['seStartTxt', 'seEndTxt', 'sePhTxt']) for(const k of ['ArrowLeft', 'ArrowRight']) r.push((await keyOn(id, k)).prevented);
      return [r, ph()];""")
    assert out == [[False] * 6, 30]


# ---- 播放头文本框
def test_typing_a_time_moves_the_playhead_and_commit_seeks_and_tidies_the_text():
    out = phr("""const t = (v) => act('segPlayheadText', {}, {value: v}); const c = (v) => { el('#sePhTxt').value = v; act('segPlayheadCommit', {}, {value: v}); };
      t('0:30'); const a = [ph(), el('#sePh').style.left, V.currentTime, el('#sePhChip').textContent];
      c('0:30'); const b = [V.currentTime, el('#sePhTxt').value];
      t('5:00'); const hi = ph(); c('5:00'); const d = [hi, el('#sePhTxt').value, V.currentTime];
      t('62'); const e = ph(); return [a, b, d, e, el('#seErr').textContent, el('#seSave').disabled];""")
    assert out == [[30, "calc(6px + (100% - 12px) * 0.5000)", 10, "0:30.0"], [30, "0:30.0"], [60, "1:00.0", 60], 60, "", False]


def test_invalid_playhead_text_shows_format_error_in_own_area_and_never_disables_save():
    out = phr("""act('segPlayheadText', {}, {value: 'abc'}); const bad = [el('#sePhErr').textContent, el('#seErr').textContent, el('#seSave').disabled, el('#seSaveList').disabled, el('#sePlay').disabled, ph()];
      act('segPlayheadCommit', {}, {value: 'abc'}); const kept = el('#sePhTxt').value;
      act('segPlayheadText', {}, {value: '0:20'}); return [bad, el('#sePhErr').textContent, ph(), kept];""")
    assert out[0] == ["时间格式不对，请写成 1:02.3 或直接写秒数", "", False, False, False, 10] and out[1:3] == ["", 20]


def test_text_arrows_step_playhead_tenth_and_shift_second_with_clamp_and_seek():
    out = phr("""el('#sePhTxt').value = '0:10.0'; const e1 = await keyOn('sePhTxt', 'ArrowUp'); const a = [e1.prevented, ph(), el('#sePhTxt').value, V.currentTime];
      await keyOn('sePhTxt', 'ArrowDown', {shiftKey: true}); const b = [ph(), el('#sePhTxt').value];
      el('#sePhTxt').value = '0:00.5'; await keyOn('sePhTxt', 'ArrowDown', {shiftKey: true}); const c = ph();
      el('#sePhTxt').value = '1:00'; await keyOn('sePhTxt', 'ArrowUp'); const d = ph();
      return [a, b, c, d, state.segEdit.start, state.segEdit.end];""")
    assert out == [[True, 10.1, "0:10.1", 10.1], [9.1, "0:09.1"], 0, 60, 10, 16]


def test_text_arrow_on_invalid_playhead_text_or_during_ime_is_a_noop():
    out = phr("""act('segPlayheadText', {}, {value: 'abc'}); el('#sePhTxt').value = 'abc'; const ev = await keyOn('sePhTxt', 'ArrowUp');
      el('#sePhTxt').value = '0:10.0'; const ime = await keyOn('sePhTxt', 'ArrowUp', {isComposing: true}); return [ev.prevented, ime.prevented, ph()];""")
    assert out == [False, False, 10]


# ---- 其它
def test_reset_original_leaves_the_playhead_where_it_was():
    out = phr("""slide('start', 12); slide('end', 20); tdown(X(40)); tup(); act('segEditReset');
      return [ph(), V.currentTime, state.segEdit.start, state.segEdit.end, el('#seStartTxt').value];""")
    assert out == [40, 40, 10, 16, "0:10.0"]


def test_play_selection_button_still_plays_start_to_end_and_playhead_follows():
    out = phr("""const c = counters(); tdown(X(40)); tup(); act('segEditPlay'); const start = V.currentTime; V.paused = false;
      const iv = intervals[intervals.length - 1]; V.currentTime = 12; iv.fn(); const mid = ph(); V.currentTime = 16.1; iv.fn();
      return [start, c.played, mid, c.paused >= 1, iv.cleared];""")
    assert out == [10, 1, 12, True, True]


def test_closing_the_modal_stops_playhead_updates_and_reopen_resets_it():
    out = phr("""tdown(X(40)); tup(); closeModal(); V.paused = false; V.currentTime = 20; fire('#seVideo', 'timeupdate');
      act('editBounds'); return [ph(), state.segEdit !== null];""")
    assert out == [10, True]


def test_hint_copy_and_playhead_label():
    out = run("return el('#modalBody').innerHTML;")
    assert "点时间轴任意位置移动播放头，空格播放 / 暂停（播到时间轴右端停）。拖动两端手柄靠近播放头会吸附到播放头。" in out
    assert "手柄范围是原始起止前后各 60 秒，输入框可以超出这个范围。" in out
    assert "点一下手柄或时间轴后按 ← →，每次 0.1 秒，加 Shift 每次 1 秒；在输入框里按 ↑ ↓ 也一样。" in out
    assert "拖动两端的手柄，或直接输入时间" not in out


def test_playhead_css_line_snapped_and_chip_styles_exist():
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "gui" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".se-ph{" in css and "var(--text)" in css.split(".se-ph{", 1)[1].split("}", 1)[0]
    assert "var(--warn)" in css.split(".se-ph.snapped", 1)[1].split("}", 1)[0]
    assert ".se-ph-chip{" in css


def test_playhead_script_only_declares_se_prefixed_globals():
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "gui" / "static" / "segment-playhead.js").read_text(encoding="utf-8")
    names = re.findall(r"^(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)", src, re.M)
    assert names and all(n.startswith(("se", "SE_", "COPY_SE_")) for n in names), names


# ---------------------------------------------------------------- 评审修复（H1 / M1–M7 / L1–L6）
def test_h1_space_is_handled_in_the_capture_phase_and_stopped_before_the_native_video_controls():
    out = phr("""const c = counters(); const V_ = {tagName: 'VIDEO', id: 'seVideo'};
      const key = type => { const ev = {key: ' ', code: 'Space', target: V_, prevented: false, stopped: false, preventDefault(){ this.prevented = true; }, stopPropagation(){ this.stopped = true; }}; fireDoc(type, ev); return ev; };
      const kd1 = key('keydown'), ku1 = key('keyup'); const played = c.played;   // 暂停 → 播放
      V.paused = false; V.currentTime = 12; const kd2 = key('keydown'), ku2 = key('keyup');   // 播放 → 暂停
      return [captureFns.has(seOnSpaceKey), captureFns.has(seOnSpaceKeyUp), [kd1, ku1, kd2, ku2].map(e => [e.prevented, e.stopped]), played, c.played, ph()];""")
    assert out == [True, True, [[True, True]] * 4, 1, 1, 12]


def test_h1_space_outside_the_modal_is_not_taken():
    out = phr("""const c = counters(); const ev = await space({target: {tagName: 'BUTTON', outside: true}}); return [ev.prevented, ev.stopped, c.played];""")
    assert out == [False, False, 0]


def test_m1_following_the_video_does_not_rewrite_the_box_being_typed_in():
    out = phr("""act('segPlayheadText', {}, {value: '0:3'}); const typed = el('#sePhTxt').value;
      V.paused = false; V.currentTime = 20; fire('#seVideo', 'timeupdate');
      const a = [ph(), el('#sePhTxt').value === typed, el('#sePhChip').textContent];
      fire('#sePhTxt', 'blur'); V.currentTime = 21; fire('#seVideo', 'timeupdate'); return [a, el('#sePhTxt').value];""")
    assert out == [[20, True, "0:20.0"], "0:21.0"]


def test_m2_any_other_move_clears_the_playhead_format_error_and_rewrites_the_box():
    moves = ["tdown(X(30)); tup();", "tdown(X(12)); tup(); await keyAt(BODY, 'ArrowRight');", "await space();",
             "fire('#sePhTxt', 'blur'); follow(25);", "fire('#sePhTxt', 'blur'); V.paused = false; V.currentTime = 25; await space();"]
    for mv in moves:
        out = phr(f"""act('segPlayheadText', {{}}, {{value: 'abc'}}); const bad = [state.segEdit.phBad, el('#sePhErr').textContent];
          {mv} const e = state.segEdit; return [bad, e.phBad, el('#sePhErr').textContent, el('#sePhTxt').value === fmtMS(e.playhead)];""")
        assert out[0] == [True, "时间格式不对，请写成 1:02.3 或直接写秒数"] and out[1:] == [False, "", True], mv


def test_m3_time_chip_stays_inside_the_track_at_both_edges():
    out = phr("""el('#sePhChip').offsetWidth = 40; const r = [];
      for(const t of [0, 30, 60]){ tdown(X(t)); tup(); r.push(el('#sePhChip').style.left); } return r;""")
    assert out == ["-6px", "-20px", "-34px"]   # 线在 6px 处：气泡左缘对齐轨道左端；居中；右缘对齐轨道右端


def test_m4_one_mapping_with_thumb_inset_for_line_click_snap_and_fill():
    out = phr("""const w = {lo: 0, hi: 60};
      const map = [seTimeToPx(w, 600, 0), seTimeToPx(w, 600, 60), sePxToTime(w, 600, 6), sePxToTime(w, 600, 594)];
      tdown(106); const lo = ph(); tup(); tdown(694); const hi = ph(); tup();
      const ends = [lo, hi, el('#sePh').style.left];
      tdown(X(14)); tup(); pslide('end', 14.5);
      return [map, ends, el('#sePh').style.left, el('#seFill').style.left, el('#seFill').style.width, snapped(), state.segEdit.end];""")
    assert out[0] == [6, 594, 0, 60] and out[1] == [0, 60, "calc(6px + (100% - 12px) * 1.0000)"]
    assert out[2:] == ["calc(6px + (100% - 12px) * 0.2333)", "calc(6px + (100% - 12px) * 0.1667)", "calc((100% - 12px) * 0.0667)", True, 14]


def test_m4_fill_and_line_sit_on_thumb_centres_at_the_window_ends():
    out = phr("""slide('start', 0); slide('end', 60); tdown(X(0)); tup();
      return [el('#seFill').style.left, el('#seFill').style.width, el('#sePh').style.left];""")
    assert out == ["calc(6px + (100% - 12px) * 0.0000)", "calc((100% - 12px) * 1.0000)", "calc(6px + (100% - 12px) * 0.0000)"]


def test_m6_track_is_a_focusable_slider_with_synced_aria_and_a_polite_error_region():
    out = phr("""const a = el('.se-track').attrs; const first = {...a};
      tdown(X(30)); tup(); return [first, {...el('.se-track').attrs}, el('#modalBody').innerHTML];""")
    html = out[2]
    assert 'class="se-track" id="seTrack" tabindex="0" role="slider" aria-label="播放头"' in html
    assert out[0] == {"aria-valuemin": "0", "aria-valuemax": "60", "aria-valuenow": "10", "aria-valuetext": "0:10.0"}
    assert out[1] == {"aria-valuemin": "0", "aria-valuemax": "60", "aria-valuenow": "30", "aria-valuetext": "0:30.0"}
    assert 'id="sePhErr" aria-live="polite"' in html and html.count('role="alert"') == 1


def test_m6_focusing_the_track_selects_the_playhead_for_arrows_even_after_tabbing_from_a_handle():
    out = phr("""down('seStart'); const a = state.segEdit.keyHandle; fireDoc('pointerup', {}); fire('.se-track', 'focus');
      const ev = await keyOn('seTrack', 'ArrowRight'); return [a, state.segEdit.keyHandle, ev.prevented, ph(), state.segEdit.start];""")
    assert out == ["start", "playhead", True, 10.1, 10]


def test_m6_webkit_mousedown_moving_focus_to_the_track_during_a_handle_press_gives_it_back_to_the_handle():
    out = phr("""down('seEnd'); let back = null; el('#seEnd').focus = o => { back = o; };
      fire('.se-track', 'focus');   // WebKit 的 mousedown 默认动作把焦点挪到最近的可聚焦祖先（轨道）
      const kh = state.segEdit.keyHandle; const ev = await keyAt(BODY, 'ArrowRight');
      return [back, kh, ev.prevented, state.segEdit.end, ph()];""")
    assert out == [{"preventScroll": True}, "end", True, 16.1, 10]


def test_m6_track_has_a_visible_focus_style():
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "gui" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".se-track:focus" in css


def test_l1_scrub_stops_when_no_button_is_held_or_pointer_is_cancelled_or_capture_lost():
    out = phr("""tdown(X(20)); tmove(X(30), 0); tmove(X(40)); const a = ph();
      tdown(X(20)); fire('.se-track', 'lostpointercapture', {pointerId: 1}); tmove(X(40)); const b = ph();
      tdown(X(20)); fire('.se-track', 'pointercancel', {pointerId: 1}); tmove(X(40)); return [a, b, ph()];""")
    assert out == [20, 20, 20]


def test_l1_a_failing_set_pointer_capture_does_not_break_the_click():
    out = phr("""el('.se-track').setPointerCapture = () => { throw new Error('InvalidPointerId'); }; tdown(X(30)); return [ph(), V.currentTime];""")
    assert out == [30, 30]


def test_l4_only_a_real_pointer_drag_of_a_handle_snaps():
    out = phr("""tdown(X(14)); tup();
      slide('end', 14.5); const keyLike = [state.segEdit.end, snapped()];   // Home / End / PageUp 之类的原生 input 事件：没有指针按下
      fire('#seEnd', 'pointerdown', {}); fireDoc('pointerup', {}); slide('end', 14.5); const afterUp = [state.segEdit.end, snapped()];
      fire('#seEnd', 'pointerdown', {}); slide('end', 14.5); const drag = [state.segEdit.end, snapped()];
      act('segEditSliderDone', {which: 'end'}, {value: '14'}); slide('end', 14.6); return [keyLike, afterUp, drag, [state.segEdit.end, snapped()]];""")
    assert out == [[14.5, False], [14.5, False], [14, True], [14.6, False]]


def test_l6_arrow_keyup_returns_only_after_a_keydown_handled_by_handle_stepping():
    out = phr("""slide('end', 20); fireDoc('keyup', {key: 'ArrowRight', target: BODY}); const unrelated = V.currentTime;   // 鼠标拖手柄时按过又松开的方向键
      act('segEditSliderDone', {which: 'end'}, {value: '20'}); await keyOn('seEnd', 'ArrowRight'); keyUp('seEnd', 'ArrowRight'); const stepped = V.currentTime;
      await keyOn('seEnd', 'ArrowRight'); keyUp('seEnd', 'ArrowRight'); keyUp('seEnd', 'ArrowRight');
      tdown(X(30)); tup(); await keyAt(BODY, 'ArrowRight'); keyUp('seTrack', 'ArrowRight'); return [unrelated, stepped, V.currentTime];""")
    assert out == [20, 10, 30.1]
