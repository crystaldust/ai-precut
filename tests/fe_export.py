"""⑥ 导出前端测试共用的数据与小工具（node vm）：版本卡片载荷、带版本的状态、进入 ⑥ 的入口。"""
import json
import re

from fe_fixtures import NEW_ROUTES, NEW_STATE
from fe_harness import run_app, wizard

SHOTS = [{"id": "sh01", "in": 0, "out": 100, "sub": "一", "note": ""},
         {"id": "sh02", "in": 100, "out": 178, "sub": "二", "note": ""}]
EXPORT_WIZARD = {**wizard(analyze="done", browse="done", criteria="done", result="done", export="available"),
                 "next": "export"}


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def text_of(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def ver(name, **over):
    """一张版本卡片（/api/state.versions 的一项），默认是「新流程、没导出过、有快照、有预览片」。"""
    base = {"name": name, "preview": True, "shots": 18, "duration": 178, "draft": None, "mtime": "10-20 11:00",
            "exports": {"mac": None, "windows": None}, "legacy": False, "current": False, "has_snapshot": True,
            "unusable_hits": 0, "blocked": None, "windows_zip": None, "windows_mb": 0}
    return {**base, **over}


def mac_export(name, draft=None):
    return {"mac": {"draft": draft or f"片名_{name}", "at": "2026-10-20T06:00:00+00:00"}, "windows": None}


EXPORT_STATE = {**NEW_STATE, "wizard": EXPORT_WIZARD, "shots": SHOTS, "shots_from_selection": True,
                "selection_digest": "d1", "manual": {"edited": False, "count": 0, "changes": [], "more": 0},
                "preview": {"status": "fresh", "at": "2026-10-20T14:02:00"}, "jianying": {"installed": True},
                "next_version": "v4", "versions": []}
EXPORT_ROUTES = {**NEW_ROUTES, "GET /api/state": EXPORT_STATE}


# 等条件成立（而不是固定让几次微任务）：until(() => 条件) 最多让出 200 次事件循环
SETTLE = """
var until = async (cond, n = 200) => { for (let i = 0; i < n && !cond(); i++) await tick(); return cond(); };
"""


def in_export(script, routes=None, *, state=None, setup=""):
    """打开项目、进入 ⑥，再跑 script。state 覆盖 /api/state 的字段。"""
    st = {**EXPORT_STATE, **(state or {})}
    body = "(async () => { await selectProject('新项目'); await go('export'); await enterExport();" + script + " })()"
    return run_app(body, routes={**EXPORT_ROUTES, "GET /api/state": st, **(routes or {})}, setup=SETTLE + setup)
