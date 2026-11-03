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


def flatten_lines(raw_segments: object) -> list[dict]:
    """work/segments.json 的 segments → 全部句子的分句（时间码可读的才留）。手改起止的镜头跨句取字幕要用。"""
    if not isinstance(raw_segments, list):
        return []
    return [line for seg in raw_segments if isinstance(seg, dict) and isinstance(seg.get("lines"), list)
            for line in seg["lines"] if _span(line)]


def _edited_sub(seg: dict, start: float, end: float, all_lines: list[dict]) -> str:
    """手改过起止的片段：镜头内的分句（跨所有句子，按时间、去重），不限于本句自己的分句。"""
    spans = sorted({x for x in (_span(line) for line in all_lines) if x})
    return join_lines([t for a, b, t in spans if _inside(a, b, start, end)])


def sub_for(seg: dict, start: float, end: float, all_lines: list[dict] | None = None) -> str:
    """镜头 [start, end] 的字幕：整句；截短时只留镜头内的分句（KI-01）。

    seg 手改过起止（bounds_edited）且给了全部分句 all_lines：取镜头内所有句子的分句（截短去字、延伸带上邻句的字）；
    「整句」判断始终用分析给的原始起止 base_start / base_end，不用手改后的。没有分句 → 按原句比例截。
    """
    text = seg.get("text") or ""
    edited = bool(seg.get("bounds_edited"))
    s0 = float(seg["base_start"] if edited else seg["start"])
    s1 = float(seg["base_end"] if edited else seg["end"])
    covers = start <= s0 + WHOLE_TOLERANCE and end >= s1 - WHOLE_TOLERANCE
    spills = start < s0 - WHOLE_TOLERANCE or end > s1 + WHOLE_TOLERANCE  # 延伸到了邻句：整句之外还要带邻句的字
    if not text or s1 <= s0 or (covers and not (edited and all_lines and spills)):
        return text
    if edited and all_lines:
        picked = _edited_sub(seg, start, end, all_lines)
        if picked:
            return picked
    spans = [x for x in (_span(line) for line in seg.get("lines") or []) if x]
    picked = join_lines([t for a, b, t in spans if _inside(a, b, start, end)])
    return picked or _proportional(text, s0, s1, start, end)
