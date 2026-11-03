# -*- coding: utf-8 -*-
"""画面片段（没有对白、画面有内容的时段，id 为 V001…）在 ③ / 选段 / 导出里的共用读取。

来源：segments_scored.json 的 visual_segments（classify_visual 已判档）；关闭画面理解时没有这一项，
这里返回空，下游行为与关闭时完全相同。画面片段可以改档、标不可用、放进剪辑列表，
但不进档位计数、话题时长、待定决策队列和 AI 自动选段——这些地方用 is_visual 排除。
"""
from __future__ import annotations

import re
from pathlib import Path

from pipeline import schema

KIND = "visual"
TOPIC = "画面片段"
TITLE_MAX = 40
LEVELS = (1, 2, 3)
ID_RE = re.compile(r"V\d{3,}")   # 本机生成的编号（vision_align.VISUAL_ID）；不能与对白句 S### 撞


def is_visual(seg: dict) -> bool:
    return seg.get("kind") == KIND


def _valid(v: object) -> bool:
    if not isinstance(v, dict) or not isinstance(v.get("id"), str) or not ID_RE.fullmatch(v["id"]) \
            or not is_visual(v) or not isinstance(v.get("visual", {}), dict):
        return False
    start, end = v.get("start"), v.get("end")
    nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (start, end))
    return nums and end > start and v.get("level") in LEVELS


def from_scored(scored: dict | None) -> list[dict]:
    """scored 里能用的画面片段（新 dict，主题记为「画面片段」、正文为空）；写坏的项丢掉。"""
    items = scored.get("visual_segments") if isinstance(scored, dict) else None
    if not isinstance(items, list):
        return []
    out, seen = [], set()
    for v in items:
        if _valid(v) and v["id"] not in seen:  # 重复编号只取第一个
            seen.add(v["id"])
            out.append({**v, "topic": TOPIC, "text": ""})
    return out


def with_visual(scored: dict) -> list[dict]:
    """对白片段（原样）+ 画面片段，按起点排序：所有「能标记的片段」。"""
    if not isinstance(scored, dict):  # 结构不对交给调用方的 require_key 报（不在这里崩成 500）
        return []
    speech = list(scored.get("segments") or [])
    visual = from_scored(scored)
    if not visual:  # 关闭画面理解：原样（不重排），与改版前逐项相同
        return speech
    return sorted([s for s in speech if isinstance(s, dict)] + visual, key=_start)


def _start(seg: dict) -> float:
    start = seg.get("start")
    return float(start) if isinstance(start, (int, float)) and not isinstance(start, bool) else 0.0


def markable(scored: dict, path: Path) -> list[dict]:
    """segments_scored.json → 能标记的全部片段；segments 缺失或类型不对 → schema.CorruptJSON（同 require_key）。"""
    schema.require_key(scored, "segments", path)
    return with_visual(scored)


def title(seg: dict) -> str:
    """没有对白时给人看的名字：标题 → 画面描述 → 「画面片段」。"""
    text = seg.get("label") or (seg.get("visual") or {}).get("desc") or TOPIC
    return str(text)[:TITLE_MAX]
