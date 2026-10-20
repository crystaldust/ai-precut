# -*- coding: utf-8 -*-
"""剪辑台 · 剪映专业版检测（KI-98）：不写死路径，没装就不显示「打开剪映」。

检测与进程内缓存在 pipeline/jy_version（installed_version 与本模块共用同一份缓存）；
这里只是剪辑台的入口。打开用 gui/opener.run_open。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from gui import opener
from pipeline import jy_version

JIANYING_CACHE_S = jy_version.CACHE_S
OPEN_TIMEOUT_S = opener.OPEN_TIMEOUT_S
NOT_FOUND_MSG = "没找到剪映专业版：请先安装剪映，或直接从启动台打开它"


def reset_cache() -> None:
    """清掉缓存（测试用；也可在用户刚装好剪映后调用）。"""
    jy_version.reset_cache()


def find(*, refresh: bool = False, now: Callable[[], float] = time.monotonic) -> Path | None:
    """剪映 .app 的路径；缓存 JIANYING_CACHE_S 秒（含「没装」），refresh=True 强制重新检测。"""
    return jy_version.cached_find(refresh=refresh, now=now)


def installed(*, refresh: bool = False) -> bool:
    return find(refresh=refresh) is not None
