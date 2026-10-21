# -*- coding: utf-8 -*-
"""KI-103 · ③ 看素材的批量标记接口：一次请求改多段，整批成功或整批不写。

路由模块范式同 gui/project_routes.py：返回 (状态码, JSON) 或 None；项目解析由 server 传入。
单段接口里的镜头移除 / 放回、响应兜底沿用 project_routes 的实现，不复制。
"""
from __future__ import annotations

from pathlib import Path

from gui import payloads, project_routes, wizard
from gui.project_routes import Lookup
from pipeline import applog, exclusions, review, schema, shots_store

LOG = applog.get("gui")
BATCH_ITEMS_MAX = 2000  # 一次最多标记几段（请求体上限；一部素材的句子数远小于它）
BATCH_PATH = "/api/browse/batch"
BAD_ITEMS_MSG = "items 必须是片段列表（1 到 {max} 条）"
NO_ANALYSIS_MSG = "还没有分析结果，不能批量标记：先完成分析"
SHOTS_SYNC_FAILED_MSG = "标记已保存，但手动分镜表没能同步：{why}；出片前会自动剔除，可稍后重试"


def _check_items(raw: object) -> list[dict]:
    """请求里的 items：条数上限在这里，逐条规则统一在 review.check_batch；不合法抛 ValueError（人话）。"""
    if not isinstance(raw, list) or len(raw) > BATCH_ITEMS_MAX:
        raise ValueError(BAD_ITEMS_MSG.format(max=BATCH_ITEMS_MAX))
    return review.check_batch(raw)


def _batch_response(pdir: Path, name: str, ids: list[str], cleared: dict, **extra) -> dict:
    """写已落盘之后才拼：这批各段最新状态 + 剪辑列表合计 + 步骤状态；拼不出来 → 200 + warning。"""
    try:
        work = pdir / "work"
        cfg = schema.read_json(pdir / "project.json", default={})
        scored = schema.read_json(work / "segments_scored.json")
        segments = review.apply(schema.require_key(scored, "segments", work / "segments_scored.json"),
                                review.load(work))
        by_id = {s["id"]: s for s in segments}
        clip = payloads.clip_list(segments, float(cfg.get("target_duration") or project_routes.DEFAULT_TARGET_S))
        return {"ok": True, "segments": [by_id[i] for i in ids], "cleared": cleared, "clip_list": clip,
                "wizard": wizard.derive(wizard.collect(pdir, cfg, name)), **extra}
    except Exception:  # noqa: BLE001 - 写已落盘，响应拼装失败不能让界面回滚
        LOG.exception("批量标记已保存，但拼响应失败（%d 段）", len(ids))
        return {"ok": True, "segments": None, "cleared": cleared, "clip_list": None, "wizard": None,
                "warning": project_routes.SAVED_BUT_STALE_MSG, **extra}


def _sync_shots(pdir: Path, unusable: bool, restore: list[dict]) -> tuple[list[dict], int, int, str | None]:
    """overrides 已落盘之后同步手动分镜表：任何失败都不能再回 4xx，只带回 warning。

    → (被移除的镜头, 放回几镜, 没放回几镜, warning 或 None)。移除与放回各自独立兜底，已成功的部分照实回报。
    """
    removed: list[dict] = []
    restored, skipped, warning = 0, 0, None
    try:
        if unusable:
            removed = project_routes._remove_manual_shots(pdir, exclusions.spans(pdir / "work"))
        if restore:
            restored, skipped = project_routes._restore_manual_shots(pdir, restore)
    except shots_store.Busy:  # 重试同一操作即可；出片前会再剔一次（D12）
        LOG.warning("批量标记已保存，但分镜表正忙")
        warning = project_routes.UNUSABLE_SHOTS_BUSY_MSG
    except Exception as exc:  # noqa: BLE001 - 写已落盘，不能让界面回滚
        LOG.exception("批量标记已保存，但同步手动分镜表失败")
        warning = SHOTS_SYNC_FAILED_MSG.format(why=exc)
    return removed, restored, skipped, warning


def _post_browse_batch(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    """先把会失败的校验与读全做完（含手动分镜表可读、restore_shots），再写 overrides；
    写之后的失败只变 warning（_sync_shots / _batch_response），不再有 4xx。"""
    name = body.get("project", "")
    try:
        pdir = existing(name)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    work = pdir / "work"
    try:
        items = _check_items(body.get("items"))
        restore = project_routes._clean_restore(body.get("restore_shots"))
        scored = schema.read_json(work / "segments_scored.json", default=None)
        if scored is None:
            return 400, {"error": NO_ANALYSIS_MSG}
        known = {s.get("id") for s in schema.require_key(scored, "segments", work / "segments_scored.json")
                 if isinstance(s, dict)}
        for item in items:
            if item["id"] not in known:
                return 400, {"error": project_routes.UNKNOWN_SEGMENT_MSG.format(id=item["id"])}
        marks_unusable = any(i.get("unusable") is True for i in items)
        if (marks_unusable or restore) and (pdir / "shots.json").exists():
            schema.read_shots(pdir / "shots.json")  # 手动分镜表读不懂就别动 overrides
        _, cleared = review.set_batch(work, items)
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, TypeError, OSError) as exc:
        return 400, {"error": str(exc)}
    removed, restored, skipped, warning = _sync_shots(pdir, marks_unusable, restore)
    extra = {"removed_shots": removed, "restored": restored, "not_restored": skipped,
             **({"warning": warning} if warning else {})}
    return 200, _batch_response(pdir, name, [i["id"] for i in items], cleared, **extra)


def handle_post(path: str, body: dict, existing: Lookup) -> tuple[int, dict] | None:
    return _post_browse_batch(path, body, existing) if path == BATCH_PATH else None
