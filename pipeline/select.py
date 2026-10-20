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

from pipeline import classify, fingerprints, review, schema, select_rules, shot_sub

HARD_TYPES = {"金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"}
MIN_SHOT = 1.5      # 最短镜头
MAX_SHOT = 25.0     # 最长镜头，超过就截断（访谈镜头可以长一点）
MUST_KEEP_REASON = "剪辑列表里的片段"
TOTAL_TOLERANCE = 1.10       # PRD FR-7：总时长 ±10%
TARGET_ROUND_STEP = 5        # 建议目标时长向上取整到 5 秒
MUST_KEEP_EDGE_TOLERANCE = 0.2  # 秒：必留段没被分镜表覆盖的总时长只容许帧/取整误差
_EPS = 1e-6
MUST_KEEP_OVER_WARNING = "剪辑列表共 {must}，超过目标 {target}：已全部保留，请重新设定成片时长"
TOTAL_OVER_WARNING = "成片 {total} 超出目标 {target} 的 +10%"
MUST_KEEP_EMPTY_WARNING = "剪辑列表里的片段 {ids} 时长为 0，无法进片：请检查转写时间码，或在「③ 看素材」把它移出剪辑列表"
BUDGET_LEGACY_WARNING = "话题数据是旧版本，没能按新目标重新分配话题时长；重新运行 score（或在「② 分析」点「重新分析」）后再选段"
MUST_KEEP_MISSING = "分镜表缺少 {n} 段剪辑列表里的片段：{items}；{remedy}"
MUST_KEEP_LOST_ERROR = "剪辑列表里的片段未进片：{ids}"
MUST_KEEP_REMEDY_MANUAL = "在分镜表里加回，或在「③ 看素材」把它移出剪辑列表后再出片"
MUST_KEEP_REMEDY_SELECTED = "重新选段（在「⑤ 看结果」改目标时长或重新选段）后再出片，或在「③ 看素材」把它移出剪辑列表"
MUST_KEEP_MISSING_SHOWN = 5  # 报错里最多列几段
MUST_LINE_TOO_SHORT = "指定必须保留的原话「{line}」所在的句子不足 {min} 秒，没能单独成镜"
MUST_LINE_NOT_COVERED = "指定必须保留的原话「{line}」没能完整进片：请在分镜表里手动调整这一镜的入出点"
COVER_TOLERANCE = 0.01   # 秒：出入点取两位小数的误差
MUST_TOPIC_UNMATCHED = "必留话题「{topic}」对不上任何话题，已忽略"
EXCLUDE_TOPIC_UNMATCHED = "排除话题「{topic}」对不上任何话题，没有排除任何内容"
ANSWER_UNMATCHED = "答案「{label}」不在当前的决策问题里（问题可能已重新生成），已忽略：请到「④ 定标准」重新作答"
# 结尾关键词（D4）：只收「动作已经发生」的说法；「走进」「谢谢」这类泛词会把任意镜头挪到片尾（KI-02）
END_KEYWORDS = {
    "sign": ("签合同", "签字", "签约", "签了", "缴费", "交钱", "转账", "付款", "刷卡"),
    "leave": ("走了", "离开", "出门", "下楼", "再见", "拜拜"),
}
EMOTION_MIN_REL_DB = 1.0   # 情绪结尾：音量至少高于中位 1dB 才算「有力」
ENDING_SILENCE_WARNING = "结尾选了「留白」：程序不会自动加空镜，请在剪映里手动补"
ENDING_NOT_FOUND_WARNING = "结尾偏好「{label}」没找到合适的镜头，结尾保持时间顺序：可在分镜表里手动调整"
ENDING_LABELS = {"sign": "签约 / 缴费", "leave": "离开", "emotion": "最有力的句子", "info": "最后一个关键信息"}
OVERRIDES_STALE_WARNING = "{n} 条人工裁决对应的句子在重新分析后变了，已不套用：{ids}；请在「③ 看素材」重新标"


class SelectionError(RuntimeError):
    """选段结果违反硬约束（必留段丢失）。"""


def fmt_duration(sec: float) -> str:
    """给人看的时长：「3 分 34 秒」/「45 秒」。"""
    sec = int(round(sec))
    return f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"


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
    if seg.get("focus"):  # KI-04：主角说话人加分
        s += select_rules.FOCUS_BONUS
    return round(s, 2)


def _clip(seg: dict, budget: float | None, max_shot: float = MAX_SHOT) -> tuple[float, float]:
    start, end = float(seg["start"]), float(seg["end"])
    dur = end - start
    if budget is not None and dur > budget:
        end = start + max(MIN_SHOT, budget)
    if end - start > max_shot:
        end = start + max_shot
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
    for seg in (s for s in segments if s.get("must_keep") and not s.get("unusable")):
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
        raise SelectionError(MUST_KEEP_LOST_ERROR.format(ids=", ".join(lost)))
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


def _covers(shot: dict, a: float, b: float) -> bool:
    return shot["start"] <= a + COVER_TOLERANCE and shot["end"] >= b - COVER_TOLERANCE


def _forced_bounds(seg: dict, a: float, b: float, max_shot: float) -> tuple[float, float]:
    """强制镜头的出入点：必须覆盖原话 [a, b]；尽量从更早的分句起头（不超过单镜上限）。

    原话本身比上限还长 → 这一镜不受上限（和必留一样，指定的话必须完整）。
    """
    if b - a >= max_shot:
        return round(a, 2), round(b, 2)
    starts = {float(seg["start"]), a}
    for line in seg.get("lines") or []:
        try:
            starts.add(float(line["start"]))
        except (KeyError, TypeError, ValueError):
            continue
    start = min(t for t in starts if b - max_shot - COVER_TOLERANCE <= t <= a + COVER_TOLERANCE)
    end = max(b, min(float(seg["end"]), start + max_shot))
    return round(start, 2), round(end, 2)


def _line_spans(hits: list[dict]) -> dict[str, tuple[float, float, str]]:
    """同一句命中多条原话 → 合并成一个时间区间。"""
    spans: dict[str, tuple[float, float, str]] = {}
    for h in hits:
        a, b, line = spans.get(h["id"], (h["start"], h["end"], h["line"]))
        spans[h["id"]] = (min(a, h["start"]), max(b, h["end"]), line)
    return spans


def _force_lines(segments: list[dict], shots: list[dict], hits: list[dict], target: float,
                 weights: dict | None, max_shot: float) -> tuple[list[dict], list[str]]:
    """剪辑员指定的原话（KI-03）：无论档位/预算，一律强制进片，且镜头必须覆盖原话本身。

    已入选但被截短、没覆盖到原话的镜头换成强制镜头。→ (镜头, 没能进片的原因)。
    """
    by_id = {seg["id"]: seg for seg in segments}
    out = list(shots)
    problems: list[str] = []
    for sid, (a, b, line) in _line_spans(hits).items():
        seg = by_id.get(sid)
        if seg is None or any(_covers(x, a, b) for x in out if x["segment_id"] == sid):
            continue
        start, end = _forced_bounds(seg, a, b, max_shot)
        if end - start < MIN_SHOT:
            problems.append(MUST_LINE_TOO_SHORT.format(line=line, min=MIN_SHOT))
            continue
        out = [x for x in out if x["segment_id"] != sid] + [{
            "segment_id": sid, "topic": seg.get("topic") or "未归类",
            "start": start, "end": end, "dur": round(end - start, 2),
            "reason": "剪辑员指定必须保留", "score": _score(seg, weights), "forced": True}]
    out.sort(key=lambda x: x["start"])
    out, _ = _trim(out, target)
    return out, problems


def _uncovered_lines(hits: list[dict], shots: list[dict], segments: list[dict]) -> list[str]:
    """出片前最后核对：每条命中的原话都有镜头完整覆盖（太短成不了镜的已单独报过）。"""
    dur = {s["id"]: float(s["end"]) - float(s["start"]) for s in segments}
    return [MUST_LINE_NOT_COVERED.format(line=line)
            for sid, (a, b, line) in _line_spans(hits).items()
            if dur.get(sid, 0.0) >= MIN_SHOT
            and not any(_covers(x, a, b) for x in shots if x["segment_id"] == sid)]


def select(segments: list[dict], topics: list[dict], rules: dict,
           target: float, weights: dict | None = None) -> dict:
    # KI-93 / D13：「不可用」段一开始就拿掉——不进话题池、不补时长、不被指定原话强拉、不进未采用清单
    segments = [s for s in segments if not s.get("unusable")]
    # 旧版存下的规则可能是中文描述（ending「微信缴费完成」、pacing「紧凑快剪」）：先归一
    rules = {**rules, "ending": select_rules.norm_ending(rules.get("ending")),
             "pacing": select_rules.norm_pacing(rules.get("pacing"))}
    max_shot = select_rules.max_shot_for(rules)          # KI-04：pacing=tight → 单镜 12 秒
    speakers, notes = select_rules.focus_speakers(segments, rules.get("focus"))
    if speakers:  # KI-04：主角说话人加分（新列表，不改输入）
        segments = [{**s, "focus": str(s.get("speaker") or "") in speakers} for s in segments]
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
                start, end = start0, min(end0, start0 + max_shot)
            end = min(end, start0 + max_shot)
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
                                              float(seg["start"]) + max_shot)
        if end - start < MIN_SHOT:
            continue
        shots.append({"segment_id": seg["id"], "topic": topic,
                      "start": start, "end": end, "dur": round(end - start, 2),
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
        max_end = min(float(seg["end"]), shot["start"] + max_shot)
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
    hits, line_notes = select_rules.resolve_must_lines(rules.get("must_lines") or [], segments)
    shots, line_problems = _force_lines(segments, shots, hits, target, weights, max_shot)
    line_problems += _uncovered_lines(hits, shots, segments)
    total = sum(x["dur"] for x in shots)
    shots = _build_hook(shots, segments)
    shots, ending_notes = _fix_ending(shots, segments, rules.get("ending"))
    seg_of = {x["id"]: x for x in segments}
    shots = [{**s, "id": f"sel{i:02d}",  # KI-01：字幕按最终出入点生成（整句 / 只留镜头内分句）
              "sub": shot_sub.sub_for(seg_of[s["segment_id"]], s["start"], s["end"])}
             for i, s in enumerate(shots, 1)]

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
                *line_notes, *line_problems, *notes, *ending_notes,
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
    """把最有信息量的一镜提到最前当开场（冷开场），其余保持时间顺序。返回新列表。"""
    if len(shots) < 3:
        return shots
    key_ids = {seg["id"] for seg in segments if seg.get("key_info")}
    cands = [s for s in shots if s["dur"] >= 4
             and (s["segment_id"] in key_ids or "关键信息" in (s.get("reason") or ""))]
    if not cands:
        return shots
    hook = max(cands, key=lambda s: s["score"])
    return [{**hook, "role": "hook"}, *(s for s in shots if s is not hook)]


def _ending_pick(pool: list[dict], by_id: dict, ending: str) -> dict | None:
    def seg_of(shot: dict) -> dict:
        return by_id.get(shot["segment_id"]) or {}
    if ending in END_KEYWORDS:
        hits = [s for s in pool if any(k in (seg_of(s).get("text") or "") for k in END_KEYWORDS[ending])]
        return hits[-1] if hits else None
    if ending == "info":
        hits = [s for s in pool if seg_of(s).get("key_info")]
        return hits[-1] if hits else None
    if ending == "emotion":
        def loud(s: dict) -> float:
            return float((seg_of(s).get("signals") or {}).get("rel_db") or 0.0)
        best = max(pool, key=loud, default=None)
        return best if best is not None and loud(best) >= EMOTION_MIN_REL_DB else None
    return None


def _fix_ending(shots: list[dict], segments: list[dict],
                ending: str | None) -> tuple[list[dict], list[str]]:
    """按结尾偏好把最合适的镜头放到最后；开场 hook 永远不动（KI-02）。返回 (新列表, 警告)。"""
    if not shots or not ending:
        return shots, []
    if ending == "silence":
        return shots, [ENDING_SILENCE_WARNING]
    by_id = {s["id"]: s for s in segments}
    pool = sorted((s for s in shots if s.get("role") != "hook"), key=lambda s: s["start"])
    best = _ending_pick(pool, by_id, ending)
    if best is None:  # 找不到不能静默：说出来
        return shots, [ENDING_NOT_FOUND_WARNING.format(label=ENDING_LABELS.get(ending, ending))]
    if shots[-1] is best:
        return shots, []
    return [s for s in shots if s is not best] + [best], []


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


def _current_rules(answers: dict, questions: dict | None, stored: dict | None,
                   version: object = None) -> dict:
    """已存规则只在「由当前换算版本存下」且答案仍对得上当前题目时才用；
    题目重新生成过（答案对不上）→ 按当前题目重算并报警告；旧版本存下的规则 → 重算（KI-84）。"""
    fresh = select_rules.rules_from_answers(answers, questions)
    if stored and version == select_rules.RULES_VERSION and not fresh["ignored_answers"]:
        return dict(stored)
    return fresh


def _with_lines(segments: list[dict], segments_path: Path) -> list[dict]:
    """KI-01：从 segments.json 取分句时间码（只放在内存里，不写进镜头 / selection.json）。

    文件缺失或损坏 → 没有分句，字幕按时长比例截；损坏已由 notices 在警告栏点名。
    """
    raw = schema.read_json_lenient(segments_path, {}).get("segments")
    lines = {x.get("id"): x.get("lines") for x in raw if isinstance(x, dict)} if isinstance(raw, list) else {}
    return [{**x, "lines": lines.get(x["id"]) if isinstance(lines.get(x["id"]), list) else []}
            for x in segments]


def run(scored_path: Path, answers_path: Path, out_dir: Path,
        *, questions_path: Path | None = None, title: str = "",
        material: str = "", weights: dict | None = None,
        calibration: dict | None = None, target: float | None = None) -> dict:
    # M13 D3：输入指纹在选段开始前取（选段过程中被改的输入，选完后要显示为「需要更新」）；
    # target 用传进来的值，而不是重读 project.json（cmd_select 选段成功后才保存新目标）
    inputs = fingerprints.selection_inputs(
        out_dir, {"target_duration": target, "calibration": calibration})
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
    segments = _with_lines(review.apply(scored_segments, overrides), out_dir / "segments.json")
    if not all("signals" in x for x in segments):  # KI-06：旧项目的 scored 段没并入音频信号 → 回填
        audio = classify.load_audio_signals(out_dir / "segments_audio.json")
        segments = [x if "signals" in x else {**x, "signals": dict(audio.get(x["id"]) or {})}
                    for x in segments]
    target = float(target or scored.get("target") or 175)
    topics = scored.get("topics", [])
    extra_warnings = []
    stale = review.stale_ids(scored_segments, overrides)
    if stale:  # KI-12：重新分析后对不上的裁决不套用，但要让剪辑师知道
        extra_warnings.append(OVERRIDES_STALE_WARNING.format(
            n=len(stale), ids="、".join(stale[:MUST_KEEP_MISSING_SHOWN]) + ("…" if len(stale) > MUST_KEEP_MISSING_SHOWN else "")))
    if target != float(scored.get("target") or 0):
        if all("must" in t and "usable_dur" in t for t in topics):
            # 剪辑师改了目标时长：按新目标重分话题预算（副本，不改 scored 文件），不必重跑 score
            topics = classify.allocate_budget([dict(t) for t in topics], target)
        else:
            extra_warnings.append(BUDGET_LEGACY_WARNING)
    rules = _current_rules(answers, questions, stored_rules, payload.get("rules_version"))
    # KI-03：确认页兜底题的原话 + 剪辑偏好里的原话（按换行 /「；」分，句内逗号保留）
    lines = select_rules.parse_must_lines((calibration or {}).get("must_lines"))
    rules = {**rules, "must_lines": list(dict.fromkeys(
        [*select_rules.parse_must_lines(rules.get("must_lines")), *lines]))}
    result = {**select(segments, topics, rules, target, weights), "inputs": inputs}
    if extra_warnings:
        result = {**result, "warnings": [*result["warnings"], *extra_warnings]}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "selection.json").write_text(
        json.dumps(schema.stamp(result), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "分镜表-选段.md").write_text(markdown(result), encoding="utf-8")
    if title and material:
        (out_dir / "shots-selected.json").write_text(
            json.dumps(to_shot_list(result, title, material), ensure_ascii=False, indent=2),
            encoding="utf-8")
    return result
