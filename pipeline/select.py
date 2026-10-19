# -*- coding: utf-8 -*-
"""M3 覆盖式选段：先按话题预算立骨架，再在话题内择优。

为什么不是"按分数排序取前 N"：
    上一版就是这么剪的，结果"可选的故事"拿了 37 秒、"必留的就业承诺"只有 7 秒。
    正确顺序是：话题预算 → 每话题内择优 → 全局约束校验 → 未用清单。

输入：segments_scored.json（含话题预算）、brief_answers.json（决策答案）
输出：selection.json（shots + unused + 覆盖情况），可直接转成 shots.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline import classify, review, schema

HARD_TYPES = {"金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"}
MIN_SHOT = 1.5      # 最短镜头
MAX_SHOT = 25.0     # 最长镜头，超过就截断（访谈镜头可以长一点）
MUST_KEEP_REASON = "剪辑师标记必留"
TOTAL_TOLERANCE = 1.10       # PRD FR-7：总时长 ±10%
TARGET_ROUND_STEP = 5        # 建议目标时长向上取整到 5 秒
MUST_KEEP_EDGE_TOLERANCE = 0.2  # 秒：必留段没被分镜表覆盖的总时长只容许帧/取整误差
_EPS = 1e-6
MUST_KEEP_OVER_WARNING = "必留内容共 {must}，超过目标 {target}：已全部保留，请重新设定成片时长"
TOTAL_OVER_WARNING = "成片 {total} 超出目标 {target} 的 +10%"
MUST_KEEP_EMPTY_WARNING = "必留段 {ids} 时长为 0，无法进片：请检查转写时间码，或在「浏览素材」取消★"
BUDGET_LEGACY_WARNING = "话题数据是旧版本，没能按新目标重新分配话题时长；重新运行 score（或「处理素材」）后再选段"
MUST_KEEP_MISSING = "分镜表缺少 {n} 段必留内容：{items}；{remedy}"
MUST_KEEP_REMEDY_MANUAL = "在分镜表里加回，或在「浏览素材」取消★后再出片"
MUST_KEEP_REMEDY_SELECTED = "重新选段（「改目标时长」或重新「处理素材」）后再出片，或在「浏览素材」取消★"
MUST_KEEP_MISSING_SHOWN = 5  # 报错里最多列几段
MUST_LINE_UNMATCHED = "指定必须保留的原话「{line}」在转写里找不到，没能进片：检查是否和原话一字不差"
MUST_LINE_TOO_SHORT = "指定必须保留的原话「{line}」所在的句子不足 {min} 秒，没能单独成镜"
MUST_TOPIC_UNMATCHED = "必留话题「{topic}」对不上任何话题，已忽略"
EXCLUDE_TOPIC_UNMATCHED = "排除话题「{topic}」对不上任何话题，没有排除任何内容"
ANSWER_UNMATCHED = "答案「{label}」不在当前的决策问题里（问题可能已重新生成），已忽略：请到「确认与提问」重新作答"
END_KEYWORDS = {
    "sign": ("签", "缴费", "转账", "落笔"),
    "leave": ("走", "离开", "出门", "下楼"),
    "emotion": ("谢", "信", "钱", "白学", "放心"),
}


class SelectionError(RuntimeError):
    """选段结果违反硬约束（必留段丢失）。"""


def fmt_duration(sec: float) -> str:
    """给人看的时长：「3 分 34 秒」/「45 秒」。"""
    sec = int(round(sec))
    return f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"


def _norm_ending(value: str | None) -> str | None:
    """把模型生成的中文结尾描述归一到枚举。"""
    if not value:
        return None
    if value in {"sign", "leave", "emotion", "silence"}:
        return value
    for canon, keys in (("sign", ("签", "缴费", "转账", "付款")),
                        ("leave", ("离", "走", "出门", "背影")),
                        ("emotion", ("情绪", "有力", "金句", "感动")),
                        ("silence", ("留白", "空镜", "静"))):
        if any(k in value for k in keys):
            return canon
    return None


def _best_topic(value: str, names: list[str]) -> str | None:
    """把一个自由描述匹配到最相近的话题名（最长公共子串 ≥2 字）。"""
    if value in names:
        return value
    best, best_len = None, 1
    for name in names:
        for i in range(len(value)):
            for j in range(i + best_len + 1, len(value) + 1):
                sub = value[i:j]
                if sub in name:
                    if j - i > best_len:
                        best, best_len = name, j - i
    return best


def _match_topics(values: list[str], names: list[str]) -> list[str]:
    out = []
    for v in values or []:
        hit = _best_topic(str(v), names)
        if hit and hit not in out:
            out.append(hit)
    return out


def _score(seg: dict, weights: dict | None = None) -> float:
    w = weights or {"info": 1.0, "emotion": 1.0}
    s = 0.0
    if seg.get("key_info"):
        s += 5 * w.get("info", 1.0)
    if seg.get("info_type") in HARD_TYPES:
        s += 2 * w.get("info", 1.0)
    if seg.get("must_keep"):
        s += 10
    signals = seg.get("signals") or {}
    s += min(2.0, max(0.0, signals.get("rel_db", 0) / 3)) * w.get("emotion", 1.0)
    dur = float(seg["end"]) - float(seg["start"])
    if 4 <= dur <= 15:
        s += 1
    if seg.get("level") == 3:
        s += 1
    return round(s, 2)


def _rules(answers: dict, questions: dict | None) -> dict:
    """把答案翻译成选段规则。对不上任何选项的答案记进 ignored_answers（KI-23）。"""
    rules = {"must_topics": [], "exclude_topics": [], "ending": None,
             "focus": None, "pacing": "normal"}
    ignored: list[str] = []
    labels: dict[str, dict] = {}
    for q in (questions or {}).get("questions", []):
        for o in q.get("options", []):
            labels[o["label"]] = o.get("rule") or {}

    for value in answers.values():
        values = value if isinstance(value, list) else [value]
        for v in values:
            rule = labels.get(v)
            if not rule:
                if isinstance(v, str) and v:
                    ignored.append(v)
                continue
            kind, val = rule.get("kind"), rule.get("value")
            if kind == "must_topics":
                rules["must_topics"].extend(val if isinstance(val, list) else [val])
            elif kind == "exclude":
                rules["exclude_topics"].extend(val if isinstance(val, list) else [val])
            elif kind == "ending":
                rules["ending"] = _norm_ending(val)
            elif kind == "focus":
                rules["focus"] = val
            elif kind == "pacing":
                rules["pacing"] = "tight" if "紧凑" in v or "快" in v else "normal"
    rules["ignored_answers"] = ignored
    return rules


def _clip(seg: dict, budget: float | None) -> tuple[float, float]:
    start, end = float(seg["start"]), float(seg["end"])
    dur = end - start
    if budget is not None and dur > budget:
        end = start + max(MIN_SHOT, budget)
    if end - start > MAX_SHOT:
        end = start + MAX_SHOT
    return round(start, 2), round(end, 2)


def _trim(shots: list[dict], target: float) -> tuple[list[dict], float]:
    """超时长时整条丢弃低分镜头（保留 hook / 强制 / 必留），不要把镜头剪碎。"""
    total = sum(x["dur"] for x in shots)
    while total > target * 1.05:
        pool = [x for x in shots
                if not x.get("forced") and x.get("role") != "hook"
                and "指定" not in (x.get("reason") or "")]
        if not pool or len(shots) <= 1:  # 有必留/强制镜头时，非强制的可以全部丢掉
            break
        worst = min(pool, key=lambda x: (x["score"], -x["dur"]))
        shots.remove(worst)
        total -= worst["dur"]
    return shots, total


def _has_length(seg: dict) -> bool:
    return round(float(seg["end"]), 2) > round(float(seg["start"]), 2)


def _must_keep_shot(seg: dict, weights: dict | None) -> dict:
    start, end = round(float(seg["start"]), 2), round(float(seg["end"]), 2)
    why = seg.get("level_reason") or ""
    return {"segment_id": seg["id"], "topic": seg.get("topic") or "未归类",
            "start": start, "end": end, "dur": round(end - start, 2),
            "sub": (seg.get("text") or "")[:28],
            "reason": MUST_KEEP_REASON + (f"；{why}" if why else ""),
            "score": _score(seg, weights), "forced": True, "must_keep": True}


def _ensure_must_keep(segments: list[dict], shots: list[dict],
                      weights: dict | None) -> list[dict]:
    """GL-08：必留段无视档位/话题/预算/exclude/镜头长度，一律整段进片；已入选但被截短的恢复整段。"""
    must = {s["id"]: s for s in segments if s.get("must_keep")}
    kept = [x for x in shots if x["segment_id"] not in must]
    restored = [_must_keep_shot(seg, weights) for seg in must.values() if _has_length(seg)]
    return sorted(kept + restored, key=lambda x: x["start"])


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def uncovered_must_keep(segments: list[dict], shots: list[dict]) -> list[dict]:
    """GL-25：按时间核对分镜表（in/out）是否覆盖每个必留段，返回没覆盖到的段。"""
    spans = _merge_spans([(float(s["in"]), float(s["out"])) for s in shots])
    missing = []
    for seg in (s for s in segments if s.get("must_keep")):
        start, end = float(seg["start"]), float(seg["end"])
        covered = sum(max(0.0, min(end, b) - max(start, a)) for a, b in spans)
        if (end - start) - covered > MUST_KEEP_EDGE_TOLERANCE + _EPS:
            missing.append(seg)
    return missing


def missing_must_keep(workdir: Path, shots: list[dict]) -> list[dict]:
    """GL-25：出片前核对分镜表；没有分析结果（纯手工流程）就不查。

    overrides.json 损坏时抛 review.OverridesCorrupt，由调用方报错。
    """
    scored_path = Path(workdir) / "segments_scored.json"
    scored = schema.read_json(scored_path, default=None)  # 损坏 → CorruptJSON（带文件名），不当「没分析过」
    if scored is None:
        return []
    segments = review.apply(schema.require_key(scored, "segments", scored_path), review.load(workdir))
    return uncovered_must_keep(segments, shots)


SUMMARY_KEYS = ("total", "target", "must_keep_total", "over_target", "suggested_target",
                "over_target_warning", "warnings", "missing_must_topics")


def summary(selection: dict | None) -> dict | None:
    """selection.json → 界面需要的摘要（不带整张镜头表）。"""
    if not isinstance(selection, dict) or not selection:
        return None
    return {k: selection.get(k) for k in SUMMARY_KEYS}


def describe_missing(missing: list[dict], *, from_selection: bool = False) -> str:
    """缺失必留段 → 给剪辑师看的一句话（时间码 + 原话开头 + 怎么补救）。

    from_selection：分镜表来自自动选段（没有手存的 shots.json），补救办法是重新选段。
    """
    def tc(sec: float) -> str:
        return f"{int(sec // 60):02d}:{int(sec % 60):02d}"
    items = "；".join(f'{tc(float(s["start"]))} "{(s.get("text") or "")[:20]}"'
                     for s in missing[:MUST_KEEP_MISSING_SHOWN])
    if len(missing) > MUST_KEEP_MISSING_SHOWN:
        items += "…"
    remedy = MUST_KEEP_REMEDY_SELECTED if from_selection else MUST_KEEP_REMEDY_MANUAL
    return MUST_KEEP_MISSING.format(n=len(missing), items=items, remedy=remedy)


def _must_keep_report(segments: list[dict], shots: list[dict], covered: list[str],
                      target: float, total: float) -> dict:
    """守卫 + 汇总：必留段必须全部进片；必留合计超过目标时给出建议时长。"""
    used = {x["segment_id"] for x in shots}
    must = [s for s in segments if s.get("must_keep")]
    must_ids = [s["id"] for s in must if _has_length(s)]
    skipped = [s["id"] for s in must if not _has_length(s)]
    lost = [i for i in must_ids if i not in used]
    if lost:
        raise SelectionError(f"必留段未进片：{', '.join(lost)}")
    must_total = round(sum(x["dur"] for x in shots if x.get("must_keep")), 2)
    for topic in dict.fromkeys(x["topic"] for x in shots if x.get("must_keep")):
        if topic not in covered:
            covered.append(topic)
    over = must_total > target
    warnings = [MUST_KEEP_EMPTY_WARNING.format(ids="、".join(skipped))] if skipped else []
    if not over and total > target * TOTAL_TOLERANCE:
        warnings.append(TOTAL_OVER_WARNING.format(total=fmt_duration(total),
                                                  target=fmt_duration(target)))
    over_msg = (MUST_KEEP_OVER_WARNING.format(must=fmt_duration(must_total),
                                              target=fmt_duration(target)) if over else None)
    suggested = int(-(-must_total // TARGET_ROUND_STEP) * TARGET_ROUND_STEP) if over else None
    return {"must_keep_ids": must_ids, "must_keep_skipped": skipped,
            "must_keep_total": must_total, "over_target": over,
            "over_target_warning": over_msg, "suggested_target": suggested,
            "warnings": warnings}


def _force_lines(segments: list[dict], shots: list[dict], lines: list[str],
                 target: float, weights: dict | None) -> tuple[list[dict], list[str]]:
    """剪辑员指定必须保留的原话：无论档位/预算，一律强制进片。→ (镜头, 没能进片的原因)（KI-23）。"""
    used = {s["segment_id"] for s in shots}
    problems: list[str] = []
    for line in lines:
        hits = [seg for seg in segments if line in (seg.get("text") or "")]
        if not hits:
            problems.append(MUST_LINE_UNMATCHED.format(line=line))
            continue
        placed = any(seg["id"] in used for seg in hits)
        for seg in hits:
            if seg["id"] in used:
                continue
            start, end = _clip(seg, MAX_SHOT)
            if end - start < MIN_SHOT:
                continue
            shots.append({"segment_id": seg["id"], "topic": seg.get("topic") or "未归类",
                          "start": start, "end": end, "dur": round(end - start, 2),
                          "sub": (seg.get("text") or "")[:28],
                          "reason": "剪辑员指定必须保留", "score": _score(seg, weights),
                          "forced": True})
            used.add(seg["id"])
            placed = True
        if not placed:
            problems.append(MUST_LINE_TOO_SHORT.format(line=line, min=MIN_SHOT))
    shots.sort(key=lambda x: x["start"])
    shots, _ = _trim(shots, target)
    return shots, problems


def select(segments: list[dict], topics: list[dict], rules: dict,
           target: float, weights: dict | None = None) -> dict:
    names = [t.get("name", "") for t in topics]
    unmatched_topics = [str(v) for v in rules.get("must_topics") or []
                        if v and not _best_topic(str(v), names)]
    unmatched_excludes = [str(v) for v in rules.get("exclude_topics") or []
                          if v and not _best_topic(str(v), names)]
    must_topics = set(_match_topics(rules.get("must_topics") or [], names))
    exclude = set(_match_topics(rules.get("exclude_topics") or [], names))
    by_topic: dict[str, list[dict]] = {}
    for s in segments:
        if s.get("level") != 3 and not s.get("must_keep"):
            continue
        t = s.get("topic") or "未归类"
        if t in exclude:
            continue
        by_topic.setdefault(t, []).append(s)

    budget_of = {t["name"]: int(t.get("budget") or 0) for t in topics}
    for t in must_topics:  # 必留话题保底 8 秒
        budget_of[t] = max(8, budget_of.get(t, 0))

    shots: list[dict] = []
    covered: list[str] = []
    for topic in sorted(by_topic, key=lambda t: -budget_of.get(t, 0)):
        pool = sorted(by_topic[topic], key=lambda s: (-_score(s, weights), s["start"]))
        budget = budget_of.get(topic, 0)
        if budget <= 0:
            continue
        used = 0.0
        picked = []
        for seg in pool:
            start0, end0 = float(seg["start"]), float(seg["end"])
            dur = end0 - start0
            remaining = budget - used
            if not picked:
                start = start0
                end = min(end0, start0 + max(MIN_SHOT, budget))
            else:
                if remaining < 3.0:      # 剩太少就停，不切碎镜
                    break
                if dur > remaining * 1.15 and dur > 4:  # 放不下就跳过
                    continue
                start, end = start0, min(end0, start0 + MAX_SHOT)
            end = min(end, start0 + MAX_SHOT)
            if end - start < MIN_SHOT:
                continue
            picked.append((start, end, seg))
            used += end - start
        if not picked:
            continue
        picked.sort(key=lambda x: x[0])
        for start, end, seg in picked:
            shots.append({"segment_id": seg["id"], "topic": topic,
                          "start": start, "end": end,
                          "dur": round(end - start, 2),
                          "sub": (seg.get("text") or "")[:28],
                          "reason": seg.get("level_reason") or "",
                          "score": _score(seg, weights)})
        covered.append(topic)

    shots.sort(key=lambda x: x["start"])
    total = sum(s["dur"] for s in shots)

    # 时长不够：先用未入选片段补齐（不切碎、尊重话题额度）
    used_ids = {x["segment_id"] for x in shots}
    topic_used: dict[str, float] = {}
    for x in shots:
        topic_used[x["topic"]] = topic_used.get(x["topic"], 0.0) + x["dur"]
    pool = [x for x in segments if x.get("level") == 3 and x["id"] not in used_ids]
    for seg in sorted(pool, key=lambda x: -_score(x, weights)):
        if total >= target * 0.97:
            break
        room = target - total
        if room < 3.0:
            break
        topic = seg.get("topic") or "未归类"
        if topic in exclude:
            continue
        dur = float(seg["end"]) - float(seg["start"])
        cap = max(8.0, budget_of.get(topic, 0)) * 1.1
        if topic_used.get(topic, 0.0) + min(dur, room) > cap:
            continue
        if dur > room + 3:
            continue
        start, end = float(seg["start"]), min(float(seg["end"]),
                                              float(seg["start"]) + MAX_SHOT)
        if end - start < MIN_SHOT:
            continue
        shots.append({"segment_id": seg["id"], "topic": topic,
                      "start": start, "end": end, "dur": round(end - start, 2),
                      "sub": (seg.get("text") or "")[:28],
                      "reason": seg.get("level_reason") or "",
                      "score": _score(seg, weights)})
        total += end - start
        topic_used[topic] = topic_used.get(topic, 0.0) + end - start

    # 仍然不够：延伸已有镜头到该片段自己的结尾
    by_id = {x["id"]: x for x in segments}
    topic_extra = {t: max(0.0, max(8.0, budget_of.get(t, 0)) * 1.1 - u)
                   for t, u in topic_used.items()}
    for shot in sorted(shots, key=lambda x: -x["score"]):
        if total >= target * 0.98:
            break
        seg = by_id.get(shot["segment_id"])
        if not seg:
            continue
        max_end = min(float(seg["end"]), shot["start"] + MAX_SHOT)
        room = min(max_end - shot["end"], target - total,
                   topic_extra.get(shot["topic"], 0.0))
        if room <= 0:
            continue
        shot["end"] = round(shot["end"] + room, 2)
        shot["dur"] = round(shot["end"] - shot["start"], 2)
        total += room
        topic_extra[shot["topic"]] = topic_extra.get(shot["topic"], 0.0) - room

    shots.sort(key=lambda x: x["start"])

    shots = _ensure_must_keep(segments, shots, weights)
    shots, total = _trim(shots, target)
    shots, line_problems = _force_lines(segments, shots, rules.get("must_lines") or [],
                                        target, weights)
    total = sum(x["dur"] for x in shots)
    shots = _build_hook(shots, segments)
    shots = _fix_ending(shots, segments, rules.get("ending"))
    for i, s in enumerate(shots, 1):
        s["id"] = f"sel{i:02d}"

    used_ids = {s["segment_id"] for s in shots}
    unused = [{"segment_id": s["id"], "topic": s.get("topic"),
               "reason": ("话题未入选" if (s.get("topic") in exclude)
                          else "超出话题预算" if s.get("topic") in by_topic
                          else "不在候选池")}
              for s in segments
              if s.get("level") == 3 and s["id"] not in used_ids]
    report = _must_keep_report(segments, shots, covered, target, total)
    warnings = [*report["warnings"],
                *[MUST_TOPIC_UNMATCHED.format(topic=t) for t in unmatched_topics],
                *[EXCLUDE_TOPIC_UNMATCHED.format(topic=t) for t in unmatched_excludes],
                *line_problems,
                *[ANSWER_UNMATCHED.format(label=x) for x in rules.get("ignored_answers") or []]]

    return {
        **report,
        "warnings": warnings,
        "target": target, "total": round(total, 2),
        "rules": rules,
        "covered_topics": covered,
        "missing_must_topics": [t for t in must_topics if t not in covered],
        "shots": shots,
        "unused": unused,
        "stats": {"shots": len(shots),
                  "usable_total": sum(1 for s in segments if s.get("level") == 3),
                  "used": len(used_ids),
                  "must_keep": len(report["must_keep_ids"])},
    }


def _build_hook(shots: list[dict], segments: list[dict]) -> list[dict]:
    """把最有信息量的一镜提到最前当开场（冷开场），其余保持时间顺序。"""
    if len(shots) < 3:
        return shots
    key_ids = {seg["id"] for seg in segments if seg.get("key_info")}
    cands = [s for s in shots if s["dur"] >= 4
             and (s["segment_id"] in key_ids or "关键信息" in (s.get("reason") or ""))]
    if not cands:
        return shots
    hook = max(cands, key=lambda s: s["score"])
    if shots[0] is hook:
        return shots
    shots.remove(hook)
    hook["role"] = "hook"
    shots.insert(0, hook)
    return shots


def _fix_ending(shots: list[dict], segments: list[dict], ending: str | None):
    """按结尾偏好把最合适的镜头放到最后。"""
    if not shots or not ending:
        return shots
    keys = END_KEYWORDS.get(ending)
    if not keys:
        return shots
    by_id = {s["id"]: s for s in segments}
    best = None
    for shot in shots:
        text = (by_id.get(shot["segment_id"], {}).get("text") or "")
        if any(k in text for k in keys):
            best = shot
            break
    if best is None and ending == "emotion":
        best = max(shots, key=lambda s: (by_id.get(s["segment_id"], {})
                                         .get("signals", {}).get("rel_db", 0)))
    if best is not None:
        shots.remove(best)
        shots.append(best)
    return shots


def to_shot_list(selection: dict, title: str, material: str) -> dict:
    """转成 build_documentary.py 能吃的时间线。"""
    shots = []
    for s in selection["shots"]:
        shots.append({"id": s["id"], "in": s["start"], "out": s["end"],
                      "sub": s["sub"], "note": s["topic"]})
    return {"project": title, "source": material, "target_duration": selection["target"],
            "shots": shots}


def markdown(selection: dict) -> str:
    def tc(x: float) -> str:
        return f"{int(x // 60):02d}:{x % 60:05.2f}"
    lines = [f"# 选段表（目标 {selection['target']}s，实际 {selection['total']}s）", "",
             "| # | 时间码 | 时长 | 话题 | 台词 | 为什么选 |", "|---|---|---|---|---|---|"]
    for s in selection["shots"]:
        lines.append(f'| {s["id"]} | {tc(s["start"])}–{tc(s["end"])} | {s["dur"]:.1f}s | '
                     f'{s["topic"]} | {s["sub"]} | {s["reason"]} |')
    notes = [w for w in [selection.get("over_target_warning"), *(selection.get("warnings") or [])]
             if w]
    if notes:
        lines += ["", "## 警告", ""]
        lines += [f"- {w}" for w in notes]
    if selection["missing_must_topics"]:
        lines += ["", "## 未覆盖的必留话题", ""]
        lines += [f"- {t}" for t in selection["missing_must_topics"]]
    if selection["unused"]:
        lines += ["", "## 可用但未采用", ""]
        for u in selection["unused"][:30]:
            lines.append(f'- {u["segment_id"]}（{u["topic"]}）：{u["reason"]}')
    return "\n".join(lines)


def _current_rules(answers: dict, questions: dict | None, stored: dict | None) -> dict:
    """已存规则只在答案仍对得上当前题目时才用；题目重新生成过（答案对不上）→ 按当前题目重算并报警告。"""
    fresh = _rules(answers, questions)
    if stored and not fresh["ignored_answers"]:
        return dict(stored)
    return fresh


def run(scored_path: Path, answers_path: Path, out_dir: Path,
        *, questions_path: Path | None = None, title: str = "",
        material: str = "", weights: dict | None = None,
        calibration: dict | None = None, target: float | None = None) -> dict:
    scored = schema.read_json(scored_path)
    scored_segments = schema.require_key(scored, "segments", scored_path)  # 结构不对 → CorruptJSON
    # 答案 / 题目坏了不能当「没答」：CorruptJSON（带文件名）由调用方给人话（M8 审查）
    payload = schema.read_json(answers_path, default={})
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict):
        schema.require_key(payload, "answers", answers_path, dict)
    stored_rules = payload.get("rules")
    if stored_rules is not None and not isinstance(stored_rules, dict):
        schema.require_key(payload, "rules", answers_path, dict)
    questions = schema.read_json(questions_path, default=None) if questions_path else None

    out_dir = Path(out_dir)
    overrides = review.load(out_dir)
    segments = review.apply(scored_segments, overrides)
    target = float(target or scored.get("target") or 175)
    topics = scored.get("topics", [])
    extra_warnings = []
    if target != float(scored.get("target") or 0):
        if all("must" in t and "usable_dur" in t for t in topics):
            # 剪辑师改了目标时长：按新目标重分话题预算（副本，不改 scored 文件），不必重跑 score
            topics = classify.allocate_budget([dict(t) for t in topics], target)
        else:
            extra_warnings.append(BUDGET_LEGACY_WARNING)
    rules = _current_rules(answers, questions, stored_rules)
    lines = [x.strip() for x in str((calibration or {}).get("must_lines") or "")
             .replace("，", ",").replace("；", ",").split(",") if x.strip()]
    if lines:
        rules["must_lines"] = lines
    result = select(segments, topics, rules, target, weights)
    if extra_warnings:
        result = {**result, "warnings": [*result["warnings"], *extra_warnings]}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "selection.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "分镜表-选段.md").write_text(markdown(result), encoding="utf-8")
    if title and material:
        (out_dir / "shots-selected.json").write_text(
            json.dumps(to_shot_list(result, title, material), ensure_ascii=False, indent=2),
            encoding="utf-8")
    return result
