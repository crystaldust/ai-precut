# -*- coding: utf-8 -*-
"""⑤ 看结果 / ⑥ 导出的接口（M14 E21）：/api/result、恢复为 AI 选段、两版对比、回到这一版、当前预览片。

路由模块范式同 gui/maintenance.py：返回 (状态码, JSON) 或 None（不是本模块的路径）；
项目解析由 server 传入；ProjectCorrupt 不在这里捕获，由 server 统一回 409。写类接口在分镜表锁内读改写，
项目里有任务在跑时一律 409（避免任务结束时把这里的修改吞掉）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from gui import jobs, result_payload, wizard
from pipeline import applog, exclusions, outputs, review, schema, shots_store

Lookup = Callable[[str], Path]
BUSY_MSG = "这个项目正在{label}，完成后再试"
CURRENT_PREVIEW = "current-preview"
WRITE_FAILED_MSG = "写入失败：{reason}（请检查磁盘空间和文件权限）"
WIZARD_FAILED_MSG = "已完成，但没能读回最新的步骤状态，请刷新页面"
LOG = applog.get("gui")


def _busy(name: str) -> tuple[int, dict] | None:
    job = jobs.project_job(name)
    if job is None:
        return None
    return 409, {"error": BUSY_MSG.format(label=jobs.TASK_LABELS.get(job["task"], job["task"]))}


def _project(name: object, existing: Lookup) -> Path | tuple[int, dict]:
    try:
        return existing(name)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}


def _read_cfg(pdir: Path) -> dict:
    return schema.read_json(pdir / "project.json")


def _wizard_after_write(pdir: Path, name: str, cfg: dict) -> dict:
    """写已经成功之后才拼的附带内容：失败也要回 200（界面据 warning 重新读取），不能把成功的写说成失败。"""
    try:
        return {"wizard": wizard.derive(wizard.collect(pdir, cfg, name))}
    except Exception:  # noqa: BLE001 - 写已落盘，状态读回失败不能让界面当作没成功
        LOG.exception("写入已完成，但拼步骤状态失败：%s", name)
        return {"wizard": None, "warning": WIZARD_FAILED_MSG}


def _write_failed(exc: OSError) -> tuple[int, dict]:
    LOG.warning("分镜表写入失败：%s", type(exc).__name__)
    return 500, {"error": WRITE_FAILED_MSG.format(reason=exc.strerror or type(exc).__name__)}


def _get_result(q: dict, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    pdir = _project(name, existing)
    if isinstance(pdir, tuple):
        return pdir
    try:
        return 200, result_payload.result(pdir, name)
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (KeyError, TypeError) as exc:  # 分析结果结构不对（同 ④ 的 AnalysisIncomplete 处理）
        return 409, {"error": exclusions.BAD_DATA.format(detail=exc)}


def _get_compare(q: dict, existing: Lookup) -> tuple[int, dict]:
    pdir = _project(q.get("project", [""])[0], existing)
    if isinstance(pdir, tuple):
        return pdir
    try:
        return 200, result_payload.compare(pdir, q.get("a", [None])[0], q.get("b", [None])[0])
    except schema.CorruptJSON as exc:
        return 409, {"error": str(exc)}
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}


def _post_restore_ai(body: dict, existing: Lookup) -> tuple[int, dict]:
    """恢复为 AI 选段：备份并删除手动分镜表与基线；没有手动表是空操作。"""
    name = body.get("project", "")
    pdir = _project(name, existing)
    if isinstance(pdir, tuple):
        return pdir
    if (busy := _busy(name)) is not None:  # 快速失败；真正的判断在锁内
        return busy
    try:
        cfg = _read_cfg(pdir)  # 能失败的读先做完，再动手删
        with shots_store.locked(pdir):
            if (busy := _busy(name)) is not None:  # 拿到锁时任务可能刚起来
                return busy
            if not (pdir / shots_store.SHOTS_FILE).exists():
                saved = None
            elif not (pdir / shots_store.SELECTED_FILE).exists():
                return 409, {"error": result_payload.NO_AI_SELECTION_MSG}
            else:
                saved = shots_store.drop_manual(pdir, "restore-ai")
    except shots_store.Busy as exc:
        return 409, {"error": str(exc)}
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except OSError as exc:
        return _write_failed(exc)
    return 200, {"ok": True, "backup": saved.name if saved else None, **_wizard_after_write(pdir, name, cfg)}


def _restorable(pdir: Path, version: str) -> list[dict] | tuple[int, dict]:
    """这一版的留存分镜表；缺失 / 损坏 → (409, 原因)。"""
    snapshot = result_payload.read_snapshot(pdir / "output" / version)
    if snapshot is None:
        has_file = (pdir / "output" / version / "shots_snapshot.json").is_file()
        return 409, {"error": result_payload.RESTORE_BAD_SNAPSHOT if has_file else result_payload.RESTORE_NO_SNAPSHOT}
    return snapshot


def _prepare_restore(pdir: Path, name: str, snapshot: list[dict]) -> tuple[list[dict], list[str], dict]:
    """回到这一版之前把所有会失败的都算好：去掉不可用片段重叠的镜头、校验、读项目信息。"""
    kept, dropped = exclusions.drop_overlapping(snapshot, exclusions.spans(pdir / "work"))
    if not kept:
        raise _NothingLeft
    cleaned = schema.clean_shots(kept)
    cfg = _read_cfg(pdir)
    return cleaned, dropped, cfg


class _NothingLeft(Exception):
    """这一版的镜头全都含不可用片段。"""


def _post_restore_version(body: dict, existing: Lookup) -> tuple[int, dict]:
    """回到这一版：把这一版的留存分镜表写成当前手动分镜表；先备份当前手动表；不删除任何版本。"""
    name = body.get("project", "")
    pdir = _project(name, existing)
    if isinstance(pdir, tuple):
        return pdir
    try:
        version = result_payload.version_dir(pdir, body.get("version")).name
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if (busy := _busy(name)) is not None:  # 快速失败；真正的判断在锁内
        return busy
    snapshot = _restorable(pdir, version)
    if isinstance(snapshot, tuple):
        return snapshot
    try:
        cleaned, dropped, cfg = _prepare_restore(pdir, name, snapshot)
        meta = {"project": cfg.get("title", name), "source": cfg.get("material", "")}
        with shots_store.locked(pdir):
            if (busy := _busy(name)) is not None:  # 拿到锁时任务可能刚起来
                return busy
            saved = shots_store.backup(pdir, f"restore-{version}")
            shots_store.write_manual(pdir, cleaned, meta)
    except _NothingLeft:
        return 409, {"error": result_payload.RESTORE_EMPTY_MSG}
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (KeyError, TypeError) as exc:  # 分析结果结构不对
        return 409, {"error": exclusions.BAD_DATA.format(detail=exc)}
    except ValueError as exc:  # 镜头不合法（clean_shots）
        return 400, {"error": str(exc)}
    except shots_store.Busy as exc:
        return 409, {"error": str(exc)}
    except OSError as exc:
        return _write_failed(exc)
    return 200, {"ok": True, "count": len(cleaned), "dropped": dropped,
                 "backup": saved.name if saved else None, **_wizard_after_write(pdir, name, cfg)}


def current_preview(pdir: Path) -> Path:
    """GET /media/<项目>/current-preview 要发的文件（暂存预览片；不存在由 media.serve_file 回 404）。"""
    return outputs.staging_dir(pdir) / outputs.PREVIEW_FILE


GET_ROUTES = {"/api/result": _get_result, "/api/versions/compare": _get_compare}
POST_ROUTES = {"/api/result/restore-ai": _post_restore_ai, "/api/versions/restore": _post_restore_version}


def handle_get(path: str, q: dict, existing: Lookup) -> tuple[int, dict] | None:
    route = GET_ROUTES.get(path)
    return route(q, existing) if route else None


def handle_post(path: str, body: dict, existing: Lookup) -> tuple[int, dict] | None:
    route = POST_ROUTES.get(path)
    return route(body, existing) if route else None
