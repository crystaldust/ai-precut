# -*- coding: utf-8 -*-
"""画面与对白整合（纯本地，不调模型）：画面时间轴 → 挂到对白片段 + 无对白时段的画面片段。

产物 work/vision_aligned.json：
  * by_segment：对白片段 id → {desc, text_on_screen, objects, issues}（没有重叠画面事件的片段不出现）；
  * visual_segments：没人说话、但画面有内容的时段（id 为 V001…，与对白片段的 S### 区分），
    判档后在 ③ 里按时间显示、可手动放进剪辑列表，不进自动选段（见 pipeline/visual_clips.py）。
时间都由程序按重叠计算，不让模型改时间。画面文字来自另一个模型，只当数据：截断后原样传给下游。
关闭画面理解时什么都不做、也不删旧文件——所有读取方都要以 vision.is_on 为闸。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline import schema, vision, vision_run
from pipeline.vision_timeline import ISSUES

ALIGNED_FILE = "vision_aligned.json"
SEGMENTS_FILE = "segments.json"
SHOTS_FILE = "shots_visual.json"
# 对白片段只按这几类判画面问题；过暗 / 模糊交给本机画质检查（visual_quality.json，更可靠）
JUDGED_ISSUES = ("背对镜头", "人物出画", "遮挡", "画面晃动")
ISSUE_COVER = 0.5     # 带某个问题的事件覆盖片段时长至少这个比例，才算这段有这个问题
DESC_EVENTS = 2       # 片段描述取重叠最多的前几个事件
DESC_MAX = 120        # 片段描述最多字数
TEXT_MAX = 60         # 画面文字最多字数
OBJECTS_MAX = 8       # 物品最多个数
MIN_GAP_S = 3.0       # 对白之间的空档至少这么长，才找画面片段
MIN_VISUAL_S = 3.0    # 画面片段至少这么长
MAX_SEG_S = 35.0      # 画面片段最长，与 format_transcript.MAX_SEG 一致（测试比对）
SNAP_S = 1.0          # 片段边界吸附到这个距离内的镜头切点
HASH_CHARS = 16
VISUAL_ID = "V{n:03d}"
STALE_TIMELINE = "画面时间轴不是最新的，先重新分析（或先跑 aicut vision）"
ALIGN_STALE = "画面整合不是最新的：先跑 `aicut align`（或在「② 分析」点重新分析）"
SHOTS_MISSING = "没有镜头切点（shots_visual.json），画面片段的边界没有对齐镜头切换"


class AlignError(RuntimeError):
    """开着画面理解，但没有可用的当前时间轴：不能当作没开继续。"""


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _unique(items) -> list:
    seen: list = []
    for x in items:
        if x and x not in seen:
            seen.append(x)
    return seen


def _describe(pairs: list[tuple[float, dict]], span: float, allowed: tuple) -> dict:
    """pairs：(重叠秒数, 事件)。重叠多的排前面；问题按覆盖比例认定。"""
    top = sorted(pairs, key=lambda p: -p[0])
    desc = "；".join(_unique("，".join(x for x in (_text(ev.get("people"), DESC_MAX),
                                                  _text(ev.get("action"), DESC_MAX)) if x)
                             for _, ev in top[:DESC_EVENTS]))
    text = "；".join(_unique(_text(ev.get("text_on_screen"), TEXT_MAX) for _, ev in top))
    objects = _unique(_text(o, TEXT_MAX) for _, ev in top
                      for o in (ev.get("objects") if isinstance(ev.get("objects"), list) else []))
    issues = [i for i in allowed
              if sum(ov for ov, ev in pairs if i in (ev.get("issues") or [])) >= ISSUE_COVER * span]
    return {"desc": desc[:DESC_MAX], "text_on_screen": text[:TEXT_MAX],
            "objects": objects[:OBJECTS_MAX], "issues": issues}


def attach(segments: list[dict], events: list[dict]) -> dict[str, dict]:
    """对白片段 id → 画面信息；没有重叠事件的片段不出现。"""
    out: dict[str, dict] = {}
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"])
        pairs = [(ov, ev) for ev in events
                 if (ov := _overlap(s0, s1, float(ev["start"]), float(ev["end"]))) > 0]
        if pairs and s1 > s0:
            out[seg["id"]] = _describe(pairs, s1 - s0, JUDGED_ISSUES)
    return out


def _gaps(segments: list[dict], duration: float) -> list[tuple[float, float]]:
    spans = sorted((float(s["start"]), float(s["end"])) for s in segments)
    gaps, cursor = [], 0.0
    for s0, s1 in spans:
        if s0 - cursor >= MIN_GAP_S:
            gaps.append((cursor, s0))
        cursor = max(cursor, s1)
    if duration - cursor >= MIN_GAP_S:
        gaps.append((cursor, duration))
    return gaps


def _split(lo: float, hi: float) -> list[tuple[float, float]]:
    n = max(1, -int(-(hi - lo) // MAX_SEG_S))  # 向上取整：每块不超过 MAX_SEG_S
    step = (hi - lo) / n
    return [(lo + k * step, lo + (k + 1) * step) for k in range(n)]


def _snap(t: float, cuts: list[float], lo: float, hi: float) -> float:
    near = [c for c in cuts if lo <= c <= hi and abs(c - t) <= SNAP_S]
    return min(near, key=lambda c: abs(c - t)) if near else t


def visual_segments(segments: list[dict], events: list[dict], cuts: list[float],
                    duration: float) -> list[dict]:
    """对白空档里有画面事件的时段 → 画面片段（按时间排序、互不重叠）。"""
    pieces: list[tuple[float, float, dict]] = []
    for g0, g1 in _gaps(segments, duration):
        for ev in events:
            lo, hi = max(g0, float(ev["start"])), min(g1, float(ev["end"]))
            if hi - lo <= 0:
                continue
            for a, b in _split(lo, hi):
                sa, sb = _snap(a, cuts, g0, g1), _snap(b, cuts, g0, g1)
                pieces.append((sa, sb, ev) if sb - sa <= MAX_SEG_S else (a, b, ev))  # 吸附后超长就不吸附
    out: list[dict] = []
    last_end = 0.0
    for a, b, ev in sorted(pieces, key=lambda p: (p[0], p[1])):
        a = max(a, last_end)  # 事件互相重叠时，后一块从前一块结束处开始
        if b - a < MIN_VISUAL_S:
            continue
        out.append({"id": VISUAL_ID.format(n=len(out) + 1), "kind": "visual",
                    "start": round(a, 2), "end": round(b, 2), "duration": round(b - a, 2),
                    "speaker": "", "text": "", "visual": _describe([(b - a, ev)], b - a, ISSUES)})
        last_end = b
    return out


def _segments_hash(work: Path) -> str | None:
    try:
        return hashlib.sha1((Path(work) / SEGMENTS_FILE).read_bytes()).hexdigest()[:HASH_CHARS]
    except OSError:
        return None


def _cuts_hash(cuts: list[float] | None) -> str | None:
    return None if cuts is None else hashlib.sha1(json.dumps(cuts).encode("utf-8")).hexdigest()[:HASH_CHARS]


def _cuts(work: Path) -> list[float] | None:
    shots = schema.read_json_lenient(Path(work) / SHOTS_FILE)
    rows = shots.get("shots") if isinstance(shots, dict) else None
    if not isinstance(rows, list):
        return None
    return [float(s["start"]) for s in rows[1:]
            if isinstance(s, dict) and isinstance(s.get("start"), (int, float))]


def run(work: Path, cfg: dict) -> dict:
    """开着画面理解且时间轴是当前的 → 写 vision_aligned.json；关着 → {"skipped": True}，不碰文件。"""
    if not vision.is_on(cfg):
        return {"skipped": True}
    work = Path(work)
    if not vision_run.timeline_current(work, cfg):
        raise AlignError(STALE_TIMELINE)
    timeline = schema.read_json(work / vision_run.TIMELINE_FILE)
    events = schema.require_key(timeline, "events", work / vision_run.TIMELINE_FILE)
    segments = schema.read_field(work / SEGMENTS_FILE, "segments")
    cuts = _cuts(work)
    duration = float(timeline.get("duration") or max((float(e["end"]) for e in events), default=0.0))
    result = schema.stamp({
        "timeline_key": timeline.get("key"), "segments_hash": _segments_hash(work),
        "cuts_hash": _cuts_hash(cuts),
        "by_segment": attach(segments, events),
        "visual_segments": visual_segments(segments, events, cuts or [], duration),
        "warnings": [] if cuts is not None else [SHOTS_MISSING],
    })
    schema.write_json(work / ALIGNED_FILE, result)
    return result


def current(work: Path, cfg: dict) -> bool:
    """开着画面理解、时间轴是当前的，且整合结果对应这份时间轴和这份对白片段。"""
    if not vision.is_on(cfg) or not vision_run.timeline_current(work, cfg):
        return False
    aligned = schema.read_json_lenient(Path(work) / ALIGNED_FILE)
    timeline = schema.read_json_lenient(Path(work) / vision_run.TIMELINE_FILE)
    seg_hash = _segments_hash(work)
    return seg_hash is not None and isinstance(aligned, dict) and isinstance(timeline, dict) \
        and aligned.get("timeline_key") == timeline.get("key") \
        and aligned.get("segments_hash") == seg_hash \
        and aligned.get("cuts_hash") == _cuts_hash(_cuts(work))


def score_key(work: Path, cfg: dict) -> str | bool:
    """给三档判定核对标注用：关着 → False；开着 → 当前整合结果的时间轴 key（不是最新的 → 空串）。"""
    if not vision.is_on(cfg):
        return False
    if not current(work, cfg):
        return ""
    aligned = schema.read_json_lenient(Path(work) / ALIGNED_FILE)
    return str(aligned.get("timeline_key") or "") if isinstance(aligned, dict) else ""


def for_text(work: Path, cfg: dict) -> dict | None:
    """逐句标注要用的整合结果：关着 → None；开着就必须是当前的，不能悄悄按没开处理。"""
    if not vision.is_on(cfg):
        return None
    if not current(work, cfg):
        raise AlignError(ALIGN_STALE)
    return schema.read_json(Path(work) / ALIGNED_FILE)
