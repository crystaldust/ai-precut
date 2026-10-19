# -*- coding: utf-8 -*-
"""剪辑台 · 维护类接口（KI-33）：GET /api/cache?project=、POST /api/cache/clean {project}。

路由模块范式同 gui/support.py：返回 (状态码, JSON) 或 None（不是本模块的路径）；项目解析由 server 传入。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from gui import jobs
from pipeline import applog, cache, project_lock

CACHE_LOCKED_MSG = "这个项目正在运行任务（可能是上次剪辑台留下的，或终端里的命令），等它结束再清理缓存"
CACHE_BUSY_MSG = "这个项目正在运行「{task}」，等它结束再清理缓存"
LOG = applog.get("gui")


def _resolve(name: str, resolve: Callable[[str], Path]) -> tuple[int, dict] | Path:
    try:
        return resolve(name)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:  # ProjectCorrupt 不是 ValueError：由 server 统一 409
        return 400, {"error": str(exc)}


def _listing(pdir: Path) -> dict:
    found = cache.items(pdir)
    return {"items": found, "total": sum(i["bytes"] for i in found)}


def handle_get(path: str, query: dict, resolve: Callable[[str], Path]) -> tuple[int, dict] | None:
    if path != "/api/cache":
        return None
    pdir = _resolve((query.get("project") or [""])[0], resolve)
    return pdir if isinstance(pdir, tuple) else (200, _listing(pdir))


def handle_post(path: str, body: dict, resolve: Callable[[str], Path]) -> tuple[int, dict] | None:
    if path != "/api/cache/clean":
        return None
    name = body.get("project", "")
    pdir = _resolve(name, resolve)
    if isinstance(pdir, tuple):
        return pdir
    if (running := jobs.project_job(name)) is not None:  # 正在切片 / 抽音轨时删缓存会弄坏任务
        return 409, {"error": CACHE_BUSY_MSG.format(task=jobs.TASK_LABELS.get(running["task"],
                                                                              running["task"]))}
    try:  # 审查修复 M3：上次剪辑台留下的任务、终端里的 aicut 也持着项目锁
        with project_lock.exclusive(pdir):
            freed = cache.clean(pdir)
    except project_lock.Busy:
        return 409, {"error": CACHE_LOCKED_MSG}
    LOG.info("清理缓存：释放 %d 字节", freed)
    return 200, {"freed": freed}
