"""M13c Task 16：快捷键（node vm）：键位解析、冲突、录制编辑器、恢复默认、输入框与弹窗守卫。"""
import pytest

from fe_browse import in_browse, js, mark_ok
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

SHORTCUTS = {"play": "Space", "prev": "ArrowUp", "next": "ArrowDown", "toggle_list": "KeyS",
             "mark_usable": "KeyA", "mark_waste": "KeyD", "mark_unusable": "KeyX", "undo": "KeyZ"}


def prefs_payload(**custom):
    return {"shortcuts": {**SHORTCUTS, **custom}, "sidebar_pinned": False,
            "actions": [{"id": k, "label": k, "default": v} for k, v in SHORTCUTS.items()]}


def keys(script, routes=None, pre="await loadPrefs(); "):
    return in_browse(pre + script, {"GET /api/prefs": prefs_payload(), "POST /api/prefs": prefs_payload(),
                                    **(routes or {})})


# ---------------------------------------------------------------- 与服务端同值
def test_defaults_and_labels_match_the_server():
    from gui import prefs
    out = run_app("({d: DEFAULT_SHORTCUTS, l: ACTION_LABELS, k: KEY_LABELS})")
    assert out["d"] == prefs.DEFAULT_SHORTCUTS and out["l"] == prefs.ACTIONS
    assert all(out["k"][code] == label for code, label in prefs.KEY_LABELS.items())


def test_key_label_formats_letters_digits_and_named_keys():
    out = run_app("[keyLabel('KeyS'), keyLabel('Digit3'), keyLabel('Space'), keyLabel('ArrowUp'), keyLabel('Comma')]")
    assert out == ["S", "3", "空格", "↑", ","]


# ---------------------------------------------------------------- keyAction
@pytest.mark.parametrize("ev,expected", [
    ({"code": "KeyS"}, "toggle_list"), ({"code": "Space"}, "play"), ({"code": "ArrowUp"}, "prev"),
    ({"code": "ArrowDown"}, "next"), ({"code": "KeyA"}, "mark_usable"), ({"code": "KeyD"}, "mark_waste"),
    ({"code": "KeyX"}, "mark_unusable"), ({"code": "KeyZ"}, "undo"),
    ({"code": "KeyZ", "metaKey": True}, "undo"), ({"code": "KeyZ", "ctrlKey": True}, "undo"),
    ({"code": "KeyZ", "metaKey": True, "shiftKey": True}, None),
    ({"code": "KeyS", "metaKey": True}, None), ({"code": "KeyS", "ctrlKey": True}, None),
    ({"code": "KeyS", "altKey": True}, None), ({"code": "KeyS", "shiftKey": True}, None),
    ({"code": "KeyS", "isComposing": True}, None), ({"code": "KeyQ"}, None), ({"code": ""}, None),
    ({"code": "KeyS", "target": {"tagName": "INPUT"}}, None),
    ({"code": "KeyS", "target": {"tagName": "TEXTAREA"}}, None),
    ({"code": "KeyS", "target": {"tagName": "SELECT"}}, None),
    ({"code": "KeyS", "target": {"tagName": "DIV", "isContentEditable": True}}, None),
    ({"code": "KeyS", "target": {"tagName": "BUTTON"}}, "toggle_list"),
])
def test_key_action_table(ev, expected):
    assert run_app(f"keyAction({js(ev)}, DEFAULT_SHORTCUTS)") == expected


def test_key_action_uses_custom_map_and_handles_missing_pieces():
    out = run_app("""[keyAction({code: 'KeyQ'}, {...DEFAULT_SHORTCUTS, toggle_list: 'KeyQ'}),
                      keyAction({code: 'KeyS'}, {...DEFAULT_SHORTCUTS, toggle_list: 'KeyQ'}),
                      keyAction(null, DEFAULT_SHORTCUTS), keyAction({code: 'KeyS'}, null)]""")
    assert out == ["toggle_list", None, None, None]


def test_find_conflict_returns_other_action_name():
    out = run_app("""[findConflict(DEFAULT_SHORTCUTS, 'mark_waste', 'KeyA'), findConflict(DEFAULT_SHORTCUTS, 'mark_usable', 'KeyA'),
                      findConflict(DEFAULT_SHORTCUTS, 'mark_usable', 'KeyQ')]""")
    assert out == ["mark_usable", None, None]


# ---------------------------------------------------------------- 守卫：只在 ③、没有弹窗时生效
def test_shortcuts_do_nothing_outside_browse_view():
    out = keys("""act('jumpSeg', {i: '0'}); state.view = 'result'; await press('KeyS'); await press('Space'); return posts();""")
    assert out == []


def test_shortcuts_do_nothing_while_a_modal_is_open():
    out = keys("""act('jumpSeg', {i: '0'}); el('#mask').classList.add('on'); await press('KeyS'); return posts();""")
    assert out == []


def test_custom_keys_loaded_from_prefs_drive_the_actions():
    out = keys("""act('jumpSeg', {i: '0'}); await press('KeyS'); const old = posts().length;
      await press('KeyQ'); return [old, posts()];""", {"GET /api/prefs": prefs_payload(toggle_list="KeyQ"),
                                                         "POST /api/browse/must": mark_ok({"id": "S1", "must_keep": True})})
    assert out[0] == 0 and out[1] == [["/api/browse/must", {"project": "新项目", "id": "S1", "must": True}]]


def test_prefs_failure_keeps_defaults():
    out = keys("""return [state.shortcuts.toggle_list];""", {"GET /api/prefs": [500, {"error": "x"}]})
    assert out == ["KeyS"]


def test_space_on_video_or_button_is_left_to_the_browser():
    out = keys("""await press('ArrowDown'); let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      el('#bPv').paused = true; const a = await press('Space', {target: {tagName: 'VIDEO'}});
      const b = await press('Space', {target: {tagName: 'BUTTON'}}); return [played, a.prevented, b.prevented];""")
    assert out == [0, False, False]


def test_handled_keys_are_prevented_and_unhandled_are_not():
    out = keys("""const a = await press('ArrowDown'); const b = await press('KeyQ'); return [a.prevented, b.prevented];""")
    assert out == [True, False]


# ---------------------------------------------------------------- 编辑器
def test_shortcut_editor_lists_actions_with_key_labels_and_defaults_button():
    out = keys("openShortcuts(); return [el('#modalTitle').textContent, el('#modalBody').innerHTML];")
    assert out[0] == "快捷键"
    body = out[1]
    for label in ("播放 / 暂停", "放入 / 移出剪辑列表", "标为不可用", "撤销"):
        assert label in body
    assert "空格" in body and "<kbd>S</kbd>" in body and "恢复默认" in body and 'data-act="recordKey"' in body
    assert "必留" not in body


def test_record_key_saves_new_key_via_prefs_and_refreshes_list():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); const rec = state.recording;
      const ev = await press('KeyQ'); return [rec, state.recording, ev.prevented, posts().filter(p => p[0] === '/api/prefs'),
                                              state.shortcuts.mark_waste, el('#modalBody').innerHTML];""",
               {"POST /api/prefs": prefs_payload(mark_waste="KeyQ")})
    assert out[0] == "mark_waste" and out[1] is None and out[2] is True
    assert out[3] == [["/api/prefs", {"shortcuts": {"mark_waste": "KeyQ"}}]]
    assert out[4] == "KeyQ" and "<kbd>Q</kbd>" in out[5]


def test_record_conflict_is_rejected_locally_with_message_and_not_saved():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); await press('KeyA');
      return [posts().filter(p => p[0] === '/api/prefs').length, state.shortcuts.mark_waste, el('#shortcutMsg').textContent];""")
    assert out[0] == 0 and out[1] == "KeyD" and out[2] == "「A」已经用于「标为可用」"


def test_record_server_rejection_shows_server_error_as_text():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); await press('KeyQ');
      return [state.shortcuts.mark_waste, el('#shortcutMsg').textContent, state.recording];""",
               {"POST /api/prefs": [400, {"error": "「Q」已经用于「<b>别的</b>」"}]})
    assert out[0] == "KeyD" and out[1] == "「Q」已经用于「<b>别的</b>」" and out[2] is None  # textContent：浏览器按文本显示，不会解析成标签


def test_record_escape_cancels_without_saving_or_closing_modal():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); const ev = await press('Escape');
      return [state.recording, ev.stopped, ev.prevented, posts().length];""")
    assert out == [None, True, True, 0]


def test_record_ignores_pure_modifier_keys_and_rejects_combos():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); await press('ShiftLeft');
      const still = state.recording; await press('KeyQ', {metaKey: true});
      return [still, state.recording, posts().length, el('#shortcutMsg').textContent];""")
    assert out[0] == "mark_waste" and out[1] == "mark_waste" and out[2] == 0 and "组合键" in out[3]


def test_record_rejects_keys_the_server_does_not_allow_without_a_request():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); await press('Enter');
      return [posts().length, el('#shortcutMsg').textContent];""")
    assert out[0] == 0 and "单个字母" in out[1]


def test_browse_shortcuts_are_suspended_while_recording():
    out = keys("""act('jumpSeg', {i: '0'}); openShortcuts(); el('#mask').classList.add('on');
      act('recordKey', {action: 'mark_waste'}); await press('KeyS'); return posts().filter(p => p[0].startsWith('/api/browse'));""")
    assert out == []


def test_record_same_key_as_current_is_a_quiet_no_op():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); await press('KeyD');
      return [posts().length, state.recording];""")
    assert out == [0, None]


def test_closing_the_editor_stops_recording():
    out = keys("""openShortcuts(); act('recordKey', {action: 'mark_waste'}); closeModal(); await press('KeyQ');
      return [state.recording, posts().length];""")
    assert out == [None, 0]


def test_restore_defaults_posts_reset_and_applies_response():
    out = keys("""state.shortcuts = {...state.shortcuts, mark_waste: 'KeyQ'}; openShortcuts();
      await act('resetShortcuts'); return [posts().filter(p => p[0] === '/api/prefs/reset'), state.shortcuts.mark_waste,
                                           el('#modalBody').innerHTML.includes('<kbd>D</kbd>')];""",
               {"POST /api/prefs/reset": prefs_payload()})
    assert out == [[["/api/prefs/reset", {"what": "shortcuts"}]], "KeyD", True]


def test_restore_defaults_failure_shows_error():
    out = keys("""openShortcuts(); await act('resetShortcuts'); return el('#shortcutMsg').textContent;""",
               {"POST /api/prefs/reset": [500, {"error": "配置目录不可写"}]})
    assert out == "配置目录不可写"


def test_shortcut_editor_works_without_a_project():
    out = run_app("""(async () => { await loadPrefs(); openShortcuts(); return el('#modalBody').innerHTML; })()""",
                  routes={"GET /api/prefs": prefs_payload()})
    assert "恢复默认" in out
