# -*- coding: utf-8 -*-
"""剪辑台 · 「浏览素材」「确认与提问」两页的数据（从 server.py 拆出，KI-21 / KI-49）。

不依赖 server：调用方先用 server.project_path 校验项目名再传 pdir 进来。
读不出来的主数据不能当「没有」：project.json / 三档判定 / 决策问题损坏抛 schema.CorruptJSON，
由 server 路由回 409；只用于显示的附属文件坏了按「没有」显示（警告栏已由 notices 点名）。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import notices, questions, review, schema

NO_SCORED_MSG = "还没有三档判定，先跑 analyze/text/score"
NO_QUESTIONS_MSG = "还没有决策问题，先跑 questions"
_jload = schema.read_json_lenient


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

    shots = _jload(pdir / "shots.json", {}).get("shots", [])

    def in_cut(s):
        return any(max(0, min(s["end"], sh["in"] + sh["out"] - sh["in"]) -
                       max(s["start"], sh["in"])) > 1.0 for sh in shots)

    topics = {t["name"]: dict(t) for t in scored.get("topics", [])}
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

    for s in segments:
        s["inCut"] = in_cut(s)
        s["dur"] = round(s["end"] - s["start"], 2)

    return {
        "project": {"name": cfg.get("name", name), "title": cfg.get("title", name),
                    "preset": cfg.get("preset"), "platform": cfg.get("platform"),
                    "target_duration": cfg.get("target_duration")},
        "material_duration": material_duration,
        "summary": summary,
        "counts": {k: sum(1 for s in segments if s["level"] == v)
                   for k, v in (("waste", 1), ("pending", 2), ("usable", 3))},
        "topics": sorted(topics.values(), key=lambda t: -t["duration"]),
        "segments": segments,
        "has_overrides": bool(overrides),
        "warnings": notices.project_warnings(work),  # 损坏文件 / 兜底等，页面顶部警告条显示
    }


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
    return {"questions": q.get("questions") or [], "fallback": q.get("fallback", False),
            "summary": summary, "answers": questions.normalize_answers(q, stored.get("answers")),
            "confirmed": stored.get("confirmed", False), "answers_unreadable": unreadable,
            "warnings": notices.project_warnings(work)}
