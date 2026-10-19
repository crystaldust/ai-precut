# -*- coding: utf-8 -*-
"""把各环节落在 work/ 里的警告收拢成一张清单，给剪辑台常驻显示（M2）。

只读、不抛异常：任何文件缺失或读不出来都当作「没有警告」，不能让界面打不开。
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline import understand_text

TEXT_INCOMPLETE_NOTICE = "上次逐句标注没有完成，部分句子还没有 AI 标注：重新点「① 处理素材」只会补跑这些句子"
MISSING_TOPICS_NOTICE = "这些必留话题在成片里没有镜头：{topics}"


def _read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _texts(values) -> list[str]:
    return [str(v) for v in values or [] if v] if isinstance(values, list) else []


def project_warnings(workdir: Path) -> list[str]:
    """标注未完成 → 分档警告 → 选段警告（超目标、其他、未覆盖的必留话题）。"""
    workdir = Path(workdir)
    out: list[str] = []
    if understand_text.is_incomplete(workdir / "segments_text.json"):
        out.append(TEXT_INCOMPLETE_NOTICE)
    out += _texts(_read(workdir / "segments_scored.json").get("warnings"))
    sel = _read(workdir / "selection.json")
    out += _texts([sel.get("over_target_warning")]) + _texts(sel.get("warnings"))
    topics = _texts(sel.get("missing_must_topics"))
    if topics:
        out.append(MISSING_TOPICS_NOTICE.format(topics="、".join(topics)))
    return out
