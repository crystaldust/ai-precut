# -*- coding: utf-8 -*-
"""界面偏好（M13 D5/D6）：快捷键 + 项目栏固定，存 ~/.config/ai-cut/ui_prefs.json。

放服务端而不是 localStorage：剪辑台端口会顺延（换端口 = 换源 = 设置丢失），App（WKWebView）与浏览器模式
也是两份存储；冲突校验放这里才能在 pytest 里测。位置由 secrets.config_dir() 决定（与 consent.json 同处，
测试里经 AI_CUT_CONFIG_DIR 隔离）。键位用 KeyboardEvent.code，只允许单键；⌘Z / Ctrl+Z 固定为「撤销」的别名，不存。
文件损坏只是界面偏好：GET 给默认值并提示，POST 直接覆盖修复。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from pipeline import applog, schema, secrets

LOG = applog.get("gui")
FILENAME = "ui_prefs.json"
PREFS_VERSION = 1
ACTIONS = {"play": "播放 / 暂停", "prev": "上一段", "next": "下一段",
           "toggle_list": "放入 / 移出剪辑列表", "mark_usable": "标为可用",
           "mark_waste": "标为废片", "mark_unusable": "标为不可用", "undo": "撤销"}
DEFAULT_SHORTCUTS = {"play": "Space", "prev": "ArrowUp", "next": "ArrowDown", "toggle_list": "KeyS",
                     "mark_usable": "KeyA", "mark_waste": "KeyD", "mark_unusable": "KeyX",
                     "undo": "KeyZ"}
# 单键：字母、数字、空格、方向键、常用符号键；不含 Esc / Tab / Enter / Backspace 和任何组合键
KEY_CODE_RE = re.compile(r"Key[A-Z]|Digit[0-9]|Space|Arrow(?:Up|Down|Left|Right)|"
                         r"Comma|Period|Slash|Semicolon|Quote|Bracket(?:Left|Right)|Minus|Equal|"
                         r"Backquote|Backslash")
KEY_LABELS = {"Space": "空格", "ArrowUp": "↑", "ArrowDown": "↓", "ArrowLeft": "←", "ArrowRight": "→",
              "Comma": ",", "Period": ".", "Slash": "/", "Semicolon": ";", "Quote": "'",
              "BracketLeft": "[", "BracketRight": "]", "Minus": "-", "Equal": "=",
              "Backquote": "`", "Backslash": "\\"}
RESET_TARGETS = ("shortcuts",)

CONFLICT_MSG = "「{key}」已经用于「{other}」，不能同时用于「{this}」"
BAD_KEY_MSG = "「{action}」的快捷键不能用：只能是单个字母、数字、空格、方向键或常用符号键"
UNKNOWN_ACTION_MSG = "未知的操作：{action}"
SHORTCUTS_NOT_OBJECT_MSG = "shortcuts 必须是对象（{操作: 键位}）"
PINNED_NOT_BOOL_MSG = "sidebar_pinned 必须是 true 或 false"
NOTHING_TO_SAVE_MSG = "没有可保存的内容"
BAD_RESET_MSG = "不支持重置这一项：{what}"
CORRUPT_WARNING = "界面偏好文件读不出来，已使用默认设置；保存一次即可修复"
DROPPED_WARNING = "这些快捷键设置不能用（不合法或和别的操作冲突），已恢复默认：{names}"
SAVE_FAILED_MSG = "界面设置保存失败：配置目录不可写（磁盘已满或没有权限），请检查后重试"

class PrefsInvalid(ValueError):
    """请求里的偏好不合法（人话，→ 400）。"""


def _path() -> Path:
    return secrets.config_dir() / FILENAME


def key_label(code: str) -> str:
    if code.startswith("Key") or code.startswith("Digit"):
        return code[-1]
    return KEY_LABELS.get(code, code)


def validate_shortcuts(raw: object, *, base: dict | None = None) -> dict[str, str]:
    """把 raw（可只含部分操作）合并到 base（默认 = 出厂键位）后整体校验；返回完整键位表。"""
    if not isinstance(raw, dict):
        raise PrefsInvalid(SHORTCUTS_NOT_OBJECT_MSG)
    merged = dict(DEFAULT_SHORTCUTS if base is None else base)
    for action, code in raw.items():
        if action not in ACTIONS:
            raise PrefsInvalid(UNKNOWN_ACTION_MSG.format(action=action))
        if not isinstance(code, str) or not KEY_CODE_RE.fullmatch(code):
            raise PrefsInvalid(BAD_KEY_MSG.format(action=ACTIONS[action]))
        merged[action] = code
    owner: dict[str, str] = {}
    for action in ACTIONS:  # 校验在「合并默认后」做：只改一个键也可能撞上别的默认键
        code = merged[action]
        if code in owner:
            first = owner[code]
            this, other = (first, action) if first in raw and action not in raw else (action, first)
            raise PrefsInvalid(CONFLICT_MSG.format(key=key_label(code), other=ACTIONS[other],
                                                   this=ACTIONS[this]))
        owner[code] = action
    return merged


def _sanitize(stored: dict) -> tuple[dict[str, str], list[str]]:
    """文件里的快捷键 → (可用的完整键位表, 被丢掉的动作)：只丢不合法 / 冲突的那几个，其余自定义保留。"""
    custom, dropped = {}, []
    for action in ACTIONS:
        if action not in stored:
            continue
        code = stored[action]
        if isinstance(code, str) and KEY_CODE_RE.fullmatch(code):
            custom[action] = code
        else:
            dropped.append(action)
    merged = {**DEFAULT_SHORTCUTS, **custom}
    while True:  # 默认键位本身无冲突，所以每个冲突里至少有一个自定义项可以丢
        owners: dict[str, list[str]] = {}
        for action in ACTIONS:
            owners.setdefault(merged[action], []).append(action)
        clash = next((acts for acts in owners.values() if len(acts) > 1), None)
        if clash is None:
            return merged, dropped
        for action in (a for a in clash if a in custom):
            custom.pop(action)
            dropped.append(action)
            merged[action] = DEFAULT_SHORTCUTS[action]


def _load() -> tuple[dict, str | None]:
    """→ (偏好, 警告)。没文件 = 默认；坏文件 = 默认 + 警告；个别键位不合法 / 冲突 = 只恢复那几个 + 警告点名。"""
    defaults = {"shortcuts": dict(DEFAULT_SHORTCUTS), "sidebar_pinned": False}
    try:
        data = schema.read_json(_path(), default=None)
    except schema.CorruptJSON:
        return defaults, CORRUPT_WARNING
    if data is None:
        return defaults, None
    stored = data.get("shortcuts") if isinstance(data.get("shortcuts"), dict) else {}
    shortcuts, dropped = _sanitize(stored)
    warning = DROPPED_WARNING.format(names="、".join(ACTIONS[a] for a in dropped)) if dropped else None
    return {"shortcuts": shortcuts, "sidebar_pinned": data.get("sidebar_pinned") is True}, warning


def _payload(current: dict, warning: str | None = None) -> dict:
    out = {**current, "actions": [{"id": a, "label": label, "default": DEFAULT_SHORTCUTS[a]}
                                  for a, label in ACTIONS.items()]}
    return {**out, "warning": warning} if warning else out


def _save(current: dict) -> None:
    schema.write_json(_path(), {"version": PREFS_VERSION, **current})


def _update(change: Callable[[dict], dict]) -> tuple[int, dict]:
    """跨进程加锁（schema.locked）读-改-写；坏文件从默认值起步，保存即修复。写盘失败给人话，不透传系统报错。"""
    try:
        with schema.locked(_path()):
            current, _ = _load()
            updated = change(current)
            _save(updated)
    except PrefsInvalid as exc:
        return 400, {"error": str(exc)}
    except OSError as exc:
        LOG.warning("保存界面偏好失败：%s", type(exc).__name__)
        return 500, {"error": SAVE_FAILED_MSG}
    return 200, _payload(updated)


def _post_prefs(body: dict) -> tuple[int, dict]:
    has_shortcuts, has_pinned = "shortcuts" in body, "sidebar_pinned" in body
    if not (has_shortcuts or has_pinned):
        return 400, {"error": NOTHING_TO_SAVE_MSG}
    if has_pinned and not isinstance(body["sidebar_pinned"], bool):
        return 400, {"error": PINNED_NOT_BOOL_MSG}

    def change(current: dict) -> dict:
        shortcuts = (validate_shortcuts(body["shortcuts"], base=current["shortcuts"])
                     if has_shortcuts else current["shortcuts"])
        return {"shortcuts": shortcuts,
                "sidebar_pinned": body["sidebar_pinned"] if has_pinned else current["sidebar_pinned"]}

    status, payload = _update(change)
    if status == 200:
        LOG.info("保存界面偏好：快捷键 %s，项目栏固定 %s", "已改" if has_shortcuts else "未改",
                 payload["sidebar_pinned"])
    return status, payload


def _post_reset(body: dict) -> tuple[int, dict]:
    what = body.get("what")
    if what not in RESET_TARGETS:
        return 400, {"error": BAD_RESET_MSG.format(what=what)}
    status, payload = _update(lambda current: {**current, "shortcuts": dict(DEFAULT_SHORTCUTS)})
    if status == 200:
        LOG.info("重置界面偏好：%s", what)
    return status, payload


POST_ROUTES = {"/api/prefs": _post_prefs, "/api/prefs/reset": _post_reset}


def handle_get(path: str) -> tuple[int, dict] | None:
    if path != "/api/prefs":
        return None
    current, warning = _load()
    return 200, _payload(current, warning)


def handle_post(path: str, body: dict) -> tuple[int, dict] | None:
    route = POST_ROUTES.get(path)
    return route(body) if route else None
