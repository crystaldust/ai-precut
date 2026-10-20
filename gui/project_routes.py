# -*- coding: utf-8 -*-
"""剪辑台 · 项目内容类接口：浏览素材、确认与提问、剪辑偏好（从 gui/server.py 搬出，行为不变）。

路由模块范式同 gui/maintenance.py：返回 (状态码, JSON) 或 None（不是本模块的路径）；
项目解析由 server 传入。ProjectCorrupt 不在这里捕获，由 server 统一回 409。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from gui import confirm, payloads
from pipeline import review, schema, style

Lookup = Callable[[str], Path]
MISSING_ID_MSG = "缺少 id"


def _get_browse(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        return 200, payloads.browse(lookup(name), name)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}


def _get_calibrate(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        cfg = schema.load(existing(name) / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.SchemaTooNew as exc:
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}
    return 200, {"calibration": style.normalize(cfg.get("calibration")),
                 "directive": style.directive(cfg.get("calibration"))}


def _get_confirm(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        return 200, payloads.confirm(lookup(name))
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}


GET_ROUTES = {
    "/api/browse": _get_browse,
    "/api/calibrate": _get_calibrate,
    "/api/confirm": _get_confirm,
}


def handle_get(path: str, q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict] | None:
    route = GET_ROUTES.get(path)
    return route(q, lookup, existing) if route else None


def _post_calibrate(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    try:
        pdir = existing(body.get("project", ""))
        schema.load(pdir / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.SchemaTooNew as exc:
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}
    calibration = style.normalize(body.get("calibration") or {})
    schema.update_project(pdir / "project.json", lambda c: {**c, "calibration": calibration})
    return 200, {"ok": True, "directive": style.directive(calibration)}


def _post_confirm_answers(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    try:  # KI-05：「保存并确认」后服务端自动起重新选段任务
        return 200, confirm.save_answers(existing(body.get("project", "")),
                                         body.get("project", ""), body)
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}


def _post_browse_mark(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    sid = body.get("id", "")
    try:
        pdir = existing(body.get("project", ""))
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if not sid:
        return 400, {"error": MISSING_ID_MSG}
    work = pdir / "work"
    try:
        if path.endswith("level"):
            review.set_level(work, sid, int(body.get("level")))
        else:
            review.set_must(work, sid, bool(body.get("must")))
    except review.OverridesCorrupt as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    return 200, {"ok": True}


POST_ROUTES = {
    "/api/calibrate": _post_calibrate,
    "/api/confirm/answers": _post_confirm_answers,
    "/api/browse/level": _post_browse_mark,
    "/api/browse/must": _post_browse_mark,
}


def handle_post(path: str, body: dict, existing: Lookup) -> tuple[int, dict] | None:
    route = POST_ROUTES.get(path)
    return route(path, body, existing) if route else None
