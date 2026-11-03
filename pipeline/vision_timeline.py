# -*- coding: utf-8 -*-
"""画面理解的提示词与结果解析（纯函数）：模型输出 → 校验过的事件 → 全片时间轴。

不让模型判断「可用 / 不可用」（第 1 阶段实测它全给可用），只记客观情况，
issues 只能从 ISSUES 里选，交给第 4 阶段的判定。模型输出不可信：逐字段校验、截断、过滤，
坏事件丢掉；一个合法事件都没有才算解析失败（调用方会重提一次）。
"""
from __future__ import annotations

import json
import math
import re

from pipeline import schema, vision

ISSUES = ("背对镜头", "人物出画", "遮挡", "画面晃动", "过暗", "模糊")
TEXT_FIELDS = ("shot", "people", "action", "text_on_screen")
FIELD_MAX = 300      # 每个文字字段最多保留的字数
OBJECTS_MAX = 12     # 每个事件最多保留的物品数
EVENTS_MAX = 400     # 每段最多保留的事件数（5 分钟一段，正常 15–100 个）
TEXT_MAX = 200_000   # 模型输出超过这么长不解析（正常一段几千字）
MIN_EVENT_S = 0.5    # 换算到全片、夹到段内后短于这个就丢掉
PARSE_FAILED = "模型返回的不是可用的画面时间轴（{why}）"

PROMPT = (
    "你是纪录片剪辑助理。请逐段描述这段视频的画面，覆盖整段视频，不要遗漏没有人说话的时间段。\n"
    "只输出一个 JSON 对象，不要输出其它文字，格式：\n"
    '{"events":[{"start":秒数,"end":秒数,"shot":"景别：特写/近景/中景/全景",'
    '"people":"画面里的人数、谁在做什么、是否面向镜头","action":"发生了什么",'
    '"objects":["画面中重要的物品"],"text_on_screen":"画面上能读到的文字，没有则为空字符串",'
    '"issues":["画面问题，只能从下列选项中选，没有则为空数组"]}]}\n'
    f"issues 选项：{'、'.join(ISSUES)}。\n"
    "要求：start/end 为相对本视频开头的秒数（数字，可带一位小数），按时间顺序、首尾相接覆盖 0 到视频结尾；"
    "画面内容变化时就开始新的一段，每段一般 3–20 秒。只描述看到的事实，不要评价画面好坏。"
)

_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


class TimelineParseError(ValueError):
    """模型输出里拿不到任何合法事件。"""


def _seconds(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)  # 模型偶尔给字符串数字
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _text(raw: object) -> str:
    return raw[:FIELD_MAX] if isinstance(raw, str) else ""


def _event(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    start, end = _seconds(raw.get("start")), _seconds(raw.get("end"))
    if start is None or end is None or end <= start:
        return None
    objects = [_text(o) for o in raw.get("objects")[:OBJECTS_MAX * 2] if isinstance(o, str)] \
        if isinstance(raw.get("objects"), list) else []
    issues = raw.get("issues") if isinstance(raw.get("issues"), list) else []
    return {"start": start, "end": end, **{k: _text(raw.get(k)) for k in TEXT_FIELDS},
            "objects": objects[:OBJECTS_MAX],
            "issues": [i for i in ISSUES if i in issues]}


def _json_body(text: str) -> object:
    if len(text or "") > TEXT_MAX:
        raise TimelineParseError(PARSE_FAILED.format(why="输出过长"))
    body = _FENCE.sub("", text or "")
    first, last = body.find("{"), body.rfind("}")
    if first < 0 or last <= first:
        raise TimelineParseError(PARSE_FAILED.format(why="没有 JSON"))
    try:
        return json.loads(body[first:last + 1])
    except (ValueError, RecursionError) as exc:  # 嵌套过深是 RecursionError，不是 ValueError
        raise TimelineParseError(PARSE_FAILED.format(why="JSON 格式不对")) from exc


def parse_contents(text: str) -> list[dict]:
    """一段的模型输出 → 相对本段的事件列表（新对象）；拿不到合法事件抛 TimelineParseError。"""
    data = _json_body(text)
    raw = data.get("events") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise TimelineParseError(PARSE_FAILED.format(why="没有 events 列表"))
    events = [e for e in (_event(r) for r in raw) if e is not None][:EVENTS_MAX]
    if not events:
        raise TimelineParseError(PARSE_FAILED.format(why="没有合法事件"))
    return events


def to_global(events: list[dict], chunk: dict) -> list[dict]:
    """加上段起点、夹到段内（模型秒数可能超过段长）、丢掉太短的、按开始时间排序。"""
    out = []
    for ev in events:
        start = min(max(chunk["start"] + ev["start"], chunk["start"]), chunk["end"])
        end = min(max(chunk["start"] + ev["end"], chunk["start"]), chunk["end"])
        if end - start >= MIN_EVENT_S:
            out.append({**ev, "start": round(start, 2), "end": round(end, 2)})
    return sorted(out, key=lambda e: (e["start"], e["end"]))


def build(chunk_results: list[dict], duration: float, setting: dict) -> dict:
    """chunk_results: [{chunk, events（相对本段）, tokens}] → visual_timeline.json 的内容。"""
    ordered = sorted(chunk_results, key=lambda r: r["chunk"]["index"])
    events = [ev for r in ordered for ev in to_global(r["events"], r["chunk"])]
    return schema.stamp({
        "setting": dict(setting), "prompt_version": vision.PROMPT_VERSION, "duration": duration,
        "events": sorted(events, key=lambda e: (e["start"], e["end"])),
        "chunks": [{**{k: r["chunk"][k] for k in ("index", "start", "end")}, "tokens": r["tokens"]}
                   for r in ordered],
        "usage": {"total_tokens": sum(r["tokens"] for r in ordered)},
    })
