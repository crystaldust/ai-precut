# -*- coding: utf-8 -*-
"""出片产物：Windows 剪映包打包（从 aicut.py 拆出，M14 E22）。

输出函数由调用方注入，本模块不 import aicut。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from pipeline import export_draft

PACKAGING = "生成草稿并打包（媒体要拷一遍，几分钟）…"


class PackageFailed(Exception):
    """Windows 包打不出来；消息直接给用户看。"""


def package_windows(timeline: Path, name: str, out: Path, *, info: Callable[[str], None],
                    warn: Callable[[str], None]) -> dict:
    """时间线 → Windows 可双击导入的剪映包；子进程成功时的警告逐条转给 warn（KI-18）。"""
    info(PACKAGING)
    try:
        res = export_draft.build_windows_package(timeline, name, out)
    except (RuntimeError, FileNotFoundError) as exc:
        raise PackageFailed(str(exc)) from exc
    for w in res.get("warnings", []):
        warn(w)
    return res
