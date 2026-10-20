# -*- coding: utf-8 -*-
"""剪辑台 · 项目内容类接口：浏览素材、确认与提问、剪辑偏好（从 gui/server.py 搬出，行为不变）。

路由模块范式同 gui/maintenance.py：返回 (状态码, JSON) 或 None（不是本模块的路径）；
项目解析由 server 传入。ProjectCorrupt 不在这里捕获，由 server 统一回 409。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from gui import confirm, payloads
from pipeline import exclusions, review, schema, shots_store, style

Lookup = Callable[[str], Path]
MISSING_ID_MSG = "缺少 id"
BAD_PARAM_MSG = "参数不对：id 必须是文本，{flag} 必须是 true 或 false"
SHOTS_BACKUP = "shots.before-unusable.json"  # work/ 下最近一次移除镜头前的分镜表备份（供以后撤销）
UNKNOWN_SEGMENT_MSG = "找不到片段 {id}：先完成分析，或刷新后重试"
DEFAULT_TARGET_S = 175  # 项目没写目标时长时的默认值（与选段一致）


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


def _mark_target(body: dict, existing: Lookup, flag: str | None = None) -> tuple[int, dict] | Path:
    """标记类接口的公共前置：解析项目、校验 id（文本）与开关（真正的布尔）。"""
    try:
        pdir = existing(body.get("project", ""))
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    sid = body.get("id")
    if sid is None or sid == "":
        return 400, {"error": MISSING_ID_MSG}
    if not isinstance(sid, str) or (flag and not isinstance(body.get(flag), bool)):
        return 400, {"error": BAD_PARAM_MSG.format(flag=flag or "id")}
    return pdir


def _post_browse_mark(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    is_level = path.endswith("level")
    target = _mark_target(body, existing, None if is_level else "must")
    if isinstance(target, tuple):
        return target
    sid, work, cleared = body["id"], target / "work", None
    try:
        if is_level:
            review.set_level(work, sid, int(body.get("level")))
        else:
            _, cleared = review.set_must_reporting(work, sid, body["must"])
    except review.OverridesCorrupt as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, TypeError) as exc:
        return 400, {"error": str(exc)}
    return 200, {"ok": True, "cleared": cleared}


def _remove_manual_shots(pdir: Path, marked: list) -> list[dict]:
    """D12：手动分镜表里与不可用片段重叠的镜头整镜移除；没有分镜表不新建。返回被移除的完整镜头。

    读-改-写在 shots_store.LOCK 内（与「保存分镜表」互斥）；真正移除之前先把原文件备份到 work/ 下。
    """
    shots_path = pdir / "shots.json"
    with shots_store.LOCK:
        if not shots_path.exists():
            return []
        raw = schema.read_json(shots_path)
        shots = schema.read_shots(shots_path)
        kept, dropped = exclusions.drop_overlapping(shots, marked)
        if not dropped:
            return []
        schema.write_json(pdir / "work" / SHOTS_BACKUP, raw)
        schema.write_json(shots_path, {**raw, "shots": kept})
        gone = set(dropped)
        return [sh for sh in shots if sh["id"] in gone]


def _post_browse_unusable(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    """KI-93：标 / 取消「不可用」；标记时顺带移出剪辑列表、移除手动分镜表里重叠的镜头。

    先把会失败的读（分析结果、手动分镜表、项目配置）全做完，再写 overrides：失败时不留半截状态。
    """
    target = _mark_target(body, existing, "unusable")
    if isinstance(target, tuple):
        return target
    pdir, sid, work, flag = target, body["id"], target / "work", body["unusable"]
    try:
        scored = schema.read_json(work / "segments_scored.json", default=None)
        known = {s.get("id") for s in (scored or {}).get("segments", []) if isinstance(s, dict)}
        if sid not in known:
            return 400, {"error": UNKNOWN_SEGMENT_MSG.format(id=sid)}
        scored_segments = schema.require_key(scored, "segments", work / "segments_scored.json")
        goal = float(schema.read_json(pdir / "project.json", default={}).get("target_duration")
                     or DEFAULT_TARGET_S)
        if flag and (pdir / "shots.json").exists():
            schema.read_shots(pdir / "shots.json")  # 手动分镜表读不懂就别动 overrides
        _, cleared = review.set_unusable(work, sid, flag)
        removed = _remove_manual_shots(pdir, exclusions.spans(work)) if flag else []
        segments = review.apply(scored_segments, review.load(work))
        segment = next((s for s in segments if s["id"] == sid), None)
        if segment is None:  # 理论上 known 已校验；锚点重定位失败时兜底，不要 500
            return 409, {"error": UNKNOWN_SEGMENT_MSG.format(id=sid)}
        return 200, {"ok": True, "segment": segment, "removed_shots": removed, "cleared": cleared,
                     "clip_list": payloads.clip_list(segments, goal)}
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}


POST_ROUTES = {
    "/api/calibrate": _post_calibrate,
    "/api/confirm/answers": _post_confirm_answers,
    "/api/browse/level": _post_browse_mark,
    "/api/browse/must": _post_browse_mark,
    "/api/browse/unusable": _post_browse_unusable,
}


def handle_post(path: str, body: dict, existing: Lookup) -> tuple[int, dict] | None:
    route = POST_ROUTES.get(path)
    return route(path, body, existing) if route else None
