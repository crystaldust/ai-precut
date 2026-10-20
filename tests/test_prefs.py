# -*- coding: utf-8 -*-
"""M13 T9a：界面偏好接口（快捷键 + 项目栏固定），服务端校验冲突。"""
import json

import pytest

from conftest import call
from gui import prefs
from pipeline import secrets


def get(gs):
    status, raw, _ = call(gs, "GET", "/api/prefs")
    return status, json.loads(raw)


def post(gs, body, path="/api/prefs"):
    status, raw, _ = call(gs, "POST", path, body)
    return status, json.loads(raw)


def prefs_file():
    return secrets.config_dir() / prefs.FILENAME


def test_defaults_without_file(gui_server):
    status, data = get(gui_server)
    assert status == 200
    assert data["shortcuts"] == prefs.DEFAULT_SHORTCUTS
    assert data["sidebar_pinned"] is False and "warning" not in data
    assert [a["id"] for a in data["actions"]] == list(prefs.ACTIONS)
    assert all(a["label"] and a["default"] == prefs.DEFAULT_SHORTCUTS[a["id"]] for a in data["actions"])
    assert not prefs_file().exists()  # 读默认不落盘


def test_prefs_file_lives_under_config_dir_not_home(gui_server, tmp_path):
    post(gui_server, {"sidebar_pinned": True})
    assert prefs_file().parent == secrets.config_dir()
    assert str(tmp_path) in str(prefs_file())


def test_save_and_read_back_shortcut(gui_server):
    status, data = post(gui_server, {"shortcuts": {"toggle_list": "KeyK"}})
    assert status == 200 and data["shortcuts"]["toggle_list"] == "KeyK"
    assert get(gui_server)[1]["shortcuts"] == {**prefs.DEFAULT_SHORTCUTS, "toggle_list": "KeyK"}
    assert json.loads(prefs_file().read_text(encoding="utf-8"))["version"] == prefs.PREFS_VERSION


def test_conflict_with_default_key_is_400_naming_both_actions_and_keeps_file(gui_server):
    post(gui_server, {"shortcuts": {"toggle_list": "KeyK"}})
    before = prefs_file().read_bytes()
    status, data = post(gui_server, {"shortcuts": {"toggle_list": "KeyA"}})
    assert status == 400
    assert prefs.ACTIONS["toggle_list"] in data["error"] and prefs.ACTIONS["mark_usable"] in data["error"]
    assert prefs_file().read_bytes() == before


def test_swap_two_keys_in_one_request_is_allowed(gui_server):
    status, data = post(gui_server, {"shortcuts": {"mark_usable": "KeyD", "mark_waste": "KeyA"}})
    assert status == 200 and data["shortcuts"]["mark_usable"] == "KeyD"
    assert data["shortcuts"]["mark_waste"] == "KeyA"


@pytest.mark.parametrize("key", ["Escape", "Tab", "Enter", "Backspace", "Meta+KeyS", "Ctrl+KeyS",
                                 "<script>", "", "keys", "KeyAA", 3, None, ["KeyA"], True])
def test_illegal_key_is_400(gui_server, key):
    status, data = post(gui_server, {"shortcuts": {"toggle_list": key}})
    assert status == 400 and data["error"]
    assert not prefs_file().exists()


def test_unknown_action_is_400(gui_server):
    assert post(gui_server, {"shortcuts": {"launch_missiles": "KeyQ"}})[0] == 400


def test_shortcuts_must_be_object(gui_server):
    assert post(gui_server, {"shortcuts": ["KeyS"]})[0] == 400
    assert post(gui_server, {"shortcuts": "KeyS"})[0] == 400


def test_sidebar_pinned_alone_keeps_shortcuts(gui_server):
    post(gui_server, {"shortcuts": {"toggle_list": "KeyK"}})
    status, data = post(gui_server, {"sidebar_pinned": True})
    assert status == 200 and data["sidebar_pinned"] is True
    assert data["shortcuts"]["toggle_list"] == "KeyK"


def test_sidebar_pinned_must_be_bool(gui_server):
    assert post(gui_server, {"sidebar_pinned": "yes"})[0] == 400
    assert post(gui_server, {"sidebar_pinned": 1})[0] == 400


def test_empty_body_is_400(gui_server):
    assert post(gui_server, {})[0] == 400


def test_reset_shortcuts_keeps_sidebar(gui_server):
    post(gui_server, {"shortcuts": {"toggle_list": "KeyK"}, "sidebar_pinned": True})
    status, data = post(gui_server, {"what": "shortcuts"}, "/api/prefs/reset")
    assert status == 200 and data["shortcuts"] == prefs.DEFAULT_SHORTCUTS
    assert data["sidebar_pinned"] is True
    assert get(gui_server)[1]["sidebar_pinned"] is True


def test_reset_rejects_unknown_target(gui_server):
    assert post(gui_server, {"what": "everything"}, "/api/prefs/reset")[0] == 400
    assert post(gui_server, {}, "/api/prefs/reset")[0] == 400


def test_corrupt_file_reads_defaults_with_warning_and_post_repairs(gui_server):
    prefs_file().parent.mkdir(parents=True, exist_ok=True)
    prefs_file().write_text("{坏", encoding="utf-8")
    status, data = get(gui_server)
    assert status == 200 and data["shortcuts"] == prefs.DEFAULT_SHORTCUTS and data["warning"]
    status, data = post(gui_server, {"sidebar_pinned": True})
    assert status == 200 and "warning" not in data
    assert json.loads(prefs_file().read_text(encoding="utf-8"))["sidebar_pinned"] is True


def test_conflicting_hand_edited_file_falls_back_to_defaults_with_warning(gui_server):
    prefs_file().parent.mkdir(parents=True, exist_ok=True)
    prefs_file().write_text(json.dumps({"shortcuts": {"play": "KeyA"}}), encoding="utf-8")
    data = get(gui_server)[1]
    assert data["shortcuts"] == prefs.DEFAULT_SHORTCUTS and data["warning"]


def test_non_object_file_is_treated_as_corrupt(gui_server):
    prefs_file().parent.mkdir(parents=True, exist_ok=True)
    prefs_file().write_text("[1]", encoding="utf-8")
    assert get(gui_server)[1]["warning"]


def test_requires_session(gui_server):
    assert call(gui_server, "GET", "/api/prefs", token=False)[0] == 403
    assert call(gui_server, "POST", "/api/prefs", {"sidebar_pinned": True}, token=False)[0] == 403


def test_default_shortcuts_are_valid_and_conflict_free():
    assert prefs.validate_shortcuts({}) == prefs.DEFAULT_SHORTCUTS
    assert len(set(prefs.DEFAULT_SHORTCUTS.values())) == len(prefs.DEFAULT_SHORTCUTS)
    assert set(prefs.DEFAULT_SHORTCUTS) == set(prefs.ACTIONS)


# ---------------------------------------------------------------- 评审修复
def test_load_drops_only_invalid_keys_and_names_them(gui_server):
    prefs_file().parent.mkdir(parents=True, exist_ok=True)
    prefs_file().write_text(json.dumps({"shortcuts": {"play": "KeyA", "toggle_list": "KeyK",
                                                      "undo": "Escape"}, "sidebar_pinned": True}),
                            encoding="utf-8")
    data = get(gui_server)[1]
    assert data["shortcuts"]["toggle_list"] == "KeyK"  # 合法的自定义保留
    assert data["shortcuts"]["play"] == prefs.DEFAULT_SHORTCUTS["play"]
    assert data["shortcuts"]["undo"] == prefs.DEFAULT_SHORTCUTS["undo"]
    assert prefs.ACTIONS["play"] in data["warning"] and prefs.ACTIONS["undo"] in data["warning"]
    assert prefs.ACTIONS["toggle_list"] not in data["warning"]
    assert data["sidebar_pinned"] is True


def test_load_keeps_valid_swap(gui_server):
    prefs_file().parent.mkdir(parents=True, exist_ok=True)
    prefs_file().write_text(json.dumps({"shortcuts": {"mark_usable": "KeyD", "mark_waste": "KeyA"}}),
                            encoding="utf-8")
    data = get(gui_server)[1]
    assert data["shortcuts"]["mark_usable"] == "KeyD" and "warning" not in data


def test_save_uses_cross_process_lock(gui_server, monkeypatch):
    seen = []
    real = prefs.schema.locked

    def spy(path):
        seen.append(path.name)
        return real(path)

    monkeypatch.setattr(prefs.schema, "locked", spy)
    assert post(gui_server, {"sidebar_pinned": True})[0] == 200
    assert prefs.FILENAME in seen


def test_save_oserror_is_clear_chinese_500(gui_server, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(prefs.schema, "write_json", boom)
    status, data = post(gui_server, {"sidebar_pinned": True})
    assert status == 500 and data["error"] == prefs.SAVE_FAILED_MSG and "disk full" not in data["error"]
    status, data = post(gui_server, {"what": "shortcuts"}, "/api/prefs/reset")
    assert status == 500 and data["error"] == prefs.SAVE_FAILED_MSG
