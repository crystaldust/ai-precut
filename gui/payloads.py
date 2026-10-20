# -*- coding: utf-8 -*-
"""剪辑台 · 「浏览素材」「确认与提问」两页的数据（从 server.py 拆出，KI-21 / KI-49）。

不依赖 server：调用方先用 server.project_path 校验项目名再传 pdir 进来。
读不出来的主数据不能当「没有」：project.json / 三档判定 / 决策问题损坏抛 schema.CorruptJSON，
由 server 路由回 409；只用于显示的附属文件坏了按「没有」显示（警告栏已由 notices 点名）。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import notices, questions, review, schema, select, topic_names

NO_SCORED_MSG = "还没有三档判定，先跑 analyze/text/score"
NO_QUESTIONS_MSG = "还没有决策问题，先跑 questions"
STALE_QUESTIONS_HINT = ("这组决策问题是旧版程序生成的：「主角」一题的选项是人名，现在的选段认不出来，"
                        "选了也不生效。点「重新生成决策问题」按新规则重出一组（已保存的答案需要重新选）")
DEFAULT_TARGET_S = 175  # 项目没写目标时长时的默认值（与选段一致）
_jload = schema.read_json_lenient


IN_CUT_OVERLAP_S = 1.0   # 与某一镜重叠超过这么久算「已进片」
COVER_EPS_S = 0.01       # 整段落在某一镜内（含取整误差）也算已进片


def in_cut(seg: dict, shots: list[dict]) -> bool:
    """这一段是否已经在分镜表里（③ 看素材的「已用」与 ⑤ 的未采用清单共用这一条规则）。

    与某一镜重叠超过 IN_CUT_OVERLAP_S 秒，或整段落在某一镜内。第二条是为不足 1 秒的短句：
    它再怎么被完整用进片，重叠也不可能超过 1 秒，只按第一条会被误报成「没用上 / 未采用」。
    """
    start, end = float(seg["start"]), float(seg["end"])
    for sh in shots:
        lo, hi = float(sh["in"]), float(sh["out"])
        if min(end, hi) - max(start, lo) > IN_CUT_OVERLAP_S:
            return True
        if lo - COVER_EPS_S <= start and end <= hi + COVER_EPS_S:
            return True
    return False


def browse(pdir: Path, name: str) -> dict:
    cfg = schema.read_json(pdir / "project.json", default={})  # 损坏 → CorruptJSON → 409（KI-21）
    try:
        cfg = schema.load(pdir / "project.json")
    except (OSError, ValueError, schema.SchemaTooNew):  # 旧项目迁移不了就用原始 json（只用于显示）
        pass
    work = pdir / "work"
    scored = schema.read_json(work / "segments_scored.json", default=None)  # 损坏 → 409，不是「还没有」
    if not scored:
        raise FileNotFoundError(NO_SCORED_MSG)

    overrides = review.load(work)
    segments = review.apply(schema.require_key(scored, "segments", work / "segments_scored.json"), overrides)

    # KI-99：已用 / 未用以「当前分镜表」为准：手动的优先，没有就用 AI 选段的结果（同 views.project_state）
    shots = (_jload(pdir / "shots.json", {}).get("shots") or
             _jload(work / "shots-selected.json", {}).get("shots") or [])

    # 统计按当前（含人工裁决后的）分档重算：先清零，scored 里存的值不能再叠加一次（审查修复 M9）
    topics = {t["name"]: {**t, "count": 0, "duration": 0.0, "usable_dur": 0.0}
              for t in scored.get("topics", []) if isinstance(t, dict) and "name" in t}
    for s in segments:
        t = topics.setdefault(s.get("topic") or "未归类",
                             {"name": s.get("topic") or "未归类", "must": False,
                              "count": 0, "duration": 0.0, "usable_dur": 0.0,
                              "budget": 0})
        t["count"] += 1
        t["duration"] += s["end"] - s["start"]
        if s["level"] == 3:
            t["usable_dur"] += s["end"] - s["start"]

    summary = _jload(work / "content_summary.json") or {}
    try:
        material_duration = _jload(work / "materials.json")["items"][0]["duration"]
    except Exception:  # noqa: BLE001
        material_duration = 0.0

    names = topic_names.load(work)  # P3：只改显示，topic_raw 仍是匹配键
    for s in segments:
        s["inCut"] = in_cut(s, shots)
        s["dur"] = round(s["end"] - s["start"], 2)
        s["topic_raw"] = s.get("topic")
        s["topic"] = topic_names.display(s.get("topic"), names)

    goal = cfg.get("target_duration") or DEFAULT_TARGET_S
    return {
        "project": {"name": cfg.get("name", name), "title": cfg.get("title", name),
                    "preset": cfg.get("preset"), "platform": cfg.get("platform"),
                    "target_duration": cfg.get("target_duration")},
        "material_duration": material_duration,
        "summary": summary,
        "counts": {k: sum(1 for s in segments if s["level"] == v)
                   for k, v in (("waste", 1), ("pending", 2), ("usable", 3))},
        "topics": sorted(({**t, "topic_raw": t["name"], "name": topic_names.display(t["name"], names)}
                          for t in topics.values()), key=lambda t: -t["duration"]),
        "segments": segments,
        "has_overrides": bool(overrides),
        "speakers": speakers(segments),
        "clip_list": clip_list(segments, goal),
        "warnings": notices.project_warnings(work),  # 损坏文件 / 兜底等，页面顶部警告条显示
    }


SEGMENT_TEXT_MAX_CHARS = 400   # ④ 页面里每段文字 / 依据最多带多少字（原文留在磁盘，不整段往界面灌）
INCOMPLETE_MSG = "分析结果不完整：{detail}。请回到「② 分析」点「重新分析」"
LEVELS = (1, 2, 3)


class AnalysisIncomplete(schema.CorruptJSON):
    """segments_scored.json 能读但内容不全 / 类型不对：和文件损坏同样处理（409），不当作「没有分段」。"""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_segment(index: int, seg) -> None:
    ok = (isinstance(seg, dict) and isinstance(seg.get("id"), str) and seg["id"]
          and _is_number(seg.get("start")) and _is_number(seg.get("end")) and seg.get("level") in LEVELS)
    if not ok:
        raise AnalysisIncomplete(INCOMPLETE_MSG.format(detail=f"第 {index + 1} 段缺少或写错了 id / 起止时间 / 档位"))


def _applied_segments(work: Path, scored) -> list[dict]:
    """④ 用的分段：与 ③ 同一份裁决（review.apply）。没有分析结果 → 空；有但不完整 → AnalysisIncomplete（409）。"""
    if not isinstance(scored, dict) or "segments" not in scored:
        return []
    listed = scored["segments"]
    if not isinstance(listed, list):
        raise AnalysisIncomplete(INCOMPLETE_MSG.format(detail="分段列表的格式不对"))
    for i, seg in enumerate(listed):
        _check_segment(i, seg)
    return review.apply(listed, review.load(work))  # overrides 损坏 → OverridesCorrupt → 409


applied_segments = _applied_segments  # 公开别名：⑤ 看结果与 ④ 用同一份裁决后的分段


def _clip(text) -> str:
    return str(text if text is not None else "")[:SEGMENT_TEXT_MAX_CHARS]


def _pending_items(segments: list[dict]) -> list[dict]:
    """待定（level 2）且没标不可用的段，按时间排；只给 id 和起止，文字在 segments 里读（不重复一份）。"""
    live = sorted((s for s in segments if s["level"] == 2 and not s.get("unusable")), key=lambda s: s["start"])
    return [{"id": s["id"], "start": s["start"], "end": s["end"]} for s in live]


def _compact_segment(s: dict) -> dict:
    return {"id": s["id"], "start": s["start"], "end": s["end"], "dur": round(s["end"] - s["start"], 2),
            "level": s["level"], "level_reason": _clip(s.get("level_reason")), "override": bool(s.get("override")),
            "unusable": bool(s.get("unusable")), "topic": s.get("topic"), "topic_raw": s.get("topic_raw"),
            "text": _clip(s.get("text"))}


def confirm(pdir: Path) -> dict:
    work = pdir / "work"
    q = schema.read_json(work / "questions.json", default=None)  # 损坏 → CorruptJSON → 409（KI-21）
    if q is None:
        raise FileNotFoundError(NO_QUESTIONS_MSG)
    summary = _jload(work / "content_summary.json", {})  # 只用于显示；坏了警告栏已点名，不挡整页
    try:
        stored, unreadable = schema.read_json(work / "brief_answers.json", default={}), False
    except schema.CorruptJSON:  # KI-49：答案读不出来 → 清空让剪辑师重答，页面照常打开
        stored, unreadable = {}, True
    scored = schema.read_json(work / "segments_scored.json", default={})  # 损坏 → CorruptJSON → 409，不当作没有分段
    names = topic_names.load(work)
    segments = _applied_segments(work, scored)
    for s in segments:  # P3：显示名只用于界面，topic_raw 仍是匹配键
        s["topic_raw"] = s.get("topic")
        s["topic"] = topic_names.display(s.get("topic"), names)
    counts: dict[str, int] = {}
    for s in segments:
        counts[s["topic_raw"]] = counts.get(s["topic_raw"], 0) + 1
    topics = [{"topic": topic_names.display(t["name"], names), "topic_raw": t["name"],
               "count": counts.get(t["name"], 0)}
              for t in (scored.get("topics") if isinstance(scored, dict) else None) or []
              if isinstance(t, dict) and isinstance(t.get("name"), str)]
    answers = questions.normalize_answers(q, stored.get("answers"))
    pending = _pending_items(segments)
    return {"questions": q.get("questions") or [], "fallback": q.get("fallback", False),
            "topics": topics, "segments": [_compact_segment(s) for s in sorted(segments, key=lambda s: s["start"])],
            "pending": pending, "speakers": speakers(segments),
            "summary": summary, "answers": answers,
            "confirmed": stored.get("confirmed", False), "answers_unreadable": unreadable,
            "stale_questions": questions.has_legacy_focus(q), "stale_hint": STALE_QUESTIONS_HINT,  # KI-86
            "warnings": notices.project_warnings(work)}


def clip_list(segments: list[dict], target: float) -> dict:
    """剪辑列表（D14）：必留且可用的段，按加入顺序；合计 / 超出 / 建议时长在服务端算，与选段同一规则。"""
    marked = sorted((s for s in segments if s.get("must_keep") and not s.get("unusable")),
                    key=lambda s: str(s.get("must_at") or ""))
    items = [{"id": s["id"], "start": s["start"], "end": s["end"], "dur": round(s["end"] - s["start"], 2),
              "topic": s.get("topic"), "text": s.get("text", "")} for s in marked]
    total = round(sum(i["dur"] for i in items), 2)
    over = total > target
    step = select.TARGET_ROUND_STEP
    return {"items": items, "total": total, "target": target, "over_target": over,
            "over_by": round(total - target, 2) if over else 0,
            "suggested_target": int(-(-total // step) * step) if over else None}


def speakers(segments: list[dict]) -> list[dict]:
    """说话人及其总时长（秒），按时长降序；没有名字的句子不计。"""
    total: dict[str, float] = {}
    for s in segments:
        name = s.get("speaker")
        try:
            span = float(s["end"]) - float(s["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(name, str) and name and span > 0:
            total[name] = total.get(name, 0.0) + span
    return [{"name": n, "seconds": round(t, 2)} for n, t in sorted(total.items(), key=lambda kv: -kv[1])]
