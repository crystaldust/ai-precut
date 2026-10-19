# -*- coding: utf-8 -*-
"""镜头字幕：按镜头 [start, end] 生成（KI-01）。

以前一律取原句前 28 字：镜头被预算截短后字幕还是整句开头，长句后半被吞掉。
现在：镜头覆盖整句 → 原文全文；截短 → 只留大半落在镜头里的分句（work/segments.json 的 lines
时间码）；没有分句时间码 → 按时长比例截字（D11）。超长字幕由 compose_timeline 按 max_chars 拆卡。
"""
from __future__ import annotations

LINE_INSIDE_RATIO = 0.5   # 分句至少一半落在镜头里才算这镜的字幕
_EPS = 1e-6
WHOLE_TOLERANCE = 0.01    # 秒：镜头出入点取两位小数，差这么点仍算整句


def _ascii_word_edge(ch: str) -> bool:
    """ASCII 字母 / 数字 / 标点（不含空白）：两边都是它才需要补空格。"""
    return "!" <= ch <= "~"


def join_lines(texts: list[str]) -> str:
    """分句拼整句（KI-87）：中文直接相连；两侧都是 ASCII 字母 / 数字 / 标点时补一个空格（"world. Good"）。"""
    out = ""
    for text in texts:
        if out and text and _ascii_word_edge(out[-1]) and _ascii_word_edge(text[0]):
            out += " "
        out += text
    return out


def _span(line) -> tuple[float, float, str] | None:
    if not isinstance(line, dict):
        return None
    try:
        a, b = float(line["start"]), float(line["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return a, b, str(line.get("text") or "")


def _inside(a: float, b: float, start: float, end: float) -> bool:
    if b <= a:
        return start - _EPS <= a <= end + _EPS
    return (min(b, end) - max(a, start)) / (b - a) >= LINE_INSIDE_RATIO - _EPS


def _proportional(text: str, s0: float, s1: float, start: float, end: float) -> str:
    """按时间位置截对应的那段字（句首 / 句中 / 句尾都适用）。"""
    i = round(len(text) * (max(start, s0) - s0) / (s1 - s0))
    j = round(len(text) * (min(end, s1) - s0) / (s1 - s0))
    return text[i:j] if j > i else ""


def sub_for(seg: dict, start: float, end: float) -> str:
    """镜头 [start, end] 的字幕：整句；截短时只留镜头内的分句（KI-01）。"""
    text = seg.get("text") or ""
    s0, s1 = float(seg["start"]), float(seg["end"])
    if not text or s1 <= s0 or (start <= s0 + WHOLE_TOLERANCE and end >= s1 - WHOLE_TOLERANCE):
        return text
    spans = [x for x in (_span(line) for line in seg.get("lines") or []) if x]
    picked = join_lines([t for a, b, t in spans if _inside(a, b, start, end)])
    return picked or _proportional(text, s0, s1, start, end)
