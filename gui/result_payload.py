# -*- coding: utf-8 -*-
"""⑤ 看结果的数据组装（M14 E13 / E14 / E17）：顶栏、每镜说明与替代句、未采用清单、两版对比。

纯数据：不写盘、不起任务。主数据读不懂抛 schema.CorruptJSON / review.OverridesCorrupt（路由回 409），
不当作「没有」；只用于显示的附属文件（selection.json、segments.json 的分句）坏了按没有处理。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from gui import payloads, wizard
from pipeline import fingerprints, media_io, outputs, schema, select, shot_diff, shot_sub, shots_store, topic_names

CAUSE_MUST, CAUSE_REMOVED, CAUSE_OTHER = "must", "removed", "other"
CAUSE_LABELS = {
    CAUSE_MUST: "剪辑列表里的片段 · 出片前必须加回",
    CAUSE_REMOVED: "你从分镜表里删掉了",
    select.CAUSE_EXCLUDED: "你在决策问题里排除了这个话题",
    select.CAUSE_NOT_MUST: "未勾选为必须记住的信息",
    select.CAUSE_DURATION: "因时长：这个话题的时长已经用完",
    CAUSE_OTHER: "没有进片",
}  # 选段没有去重判断，所以没有「因重复」（KI-101，⚑Q4）
LEGACY_REASON_CAUSE = {"话题未入选": select.CAUSE_EXCLUDED, "超出话题预算": select.CAUSE_DURATION,
                       "不在候选池": CAUSE_OTHER}  # 改版前的选段结果只有 reason 文字
MANUAL_WHY = "手动添加"
ALTERNATIVES_MAX = 3          # 每镜最多展开几条替代句（⚑Q7：同话题里没进片的可用段）
IN_CUT_OVERLAP_S = payloads.IN_CUT_OVERLAP_S   # 「已进片」规则与 ③ 共用（payloads.in_cut）
COMPARE_NO_SNAPSHOT = "有一版没有留存分镜表，只能并排播放预览片，没法逐镜比较"
COMPARE_SAME_MSG = "请选两个不同的版本"
VERSION_NOT_FOUND_MSG = "找不到版本 {version}"
NO_AI_SELECTION_MSG = "还没有 AI 选段，没法恢复：请先在「④ 定标准」确认并生成选段"
RESTORE_NO_SNAPSHOT = "这一版没有留存分镜表，不能回到这一版"
RESTORE_EMPTY_MSG = "这一版的镜头都含已标为不可用的片段，回到这一版后分镜表会是空的，没有执行"
RESTORE_BAD_SNAPSHOT = "这一版留存的分镜表已损坏，不能回到这一版"
SHOTS_FILE = shots_store.SHOTS_FILE


def _lenient_dict(path: Path) -> dict:
    data = schema.read_json_lenient(path, {})
    return data if isinstance(data, dict) else {}


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def _cause(seg: dict, source: str | None, ai_ids: set, recorded: dict) -> str:
    """未采用的原因：你删掉的 → 选段记录的原因 → 旧版 reason 文字 → 没有进片（剪辑列表段由调用方先判）。"""
    if source == shots_store.SOURCE_MANUAL and seg.get("id") in ai_ids:
        return CAUSE_REMOVED
    entry = recorded.get(seg.get("id"))
    if not entry:
        return CAUSE_OTHER
    cause = entry.get("cause")
    if cause in CAUSE_LABELS and cause not in (CAUSE_MUST, CAUSE_REMOVED):
        return cause
    return LEGACY_REASON_CAUSE.get(entry.get("reason"), CAUSE_OTHER)


def _unused(segments: list[dict], shots: list[dict], source: str | None, selection: dict,
            missing: list[dict], names: dict, with_lines: dict) -> list[dict]:
    """E13：可用（含人工裁决）且不在当前分镜表里的段；不在表里的剪辑列表段排最前。"""
    must_ids = {s.get("id") for s in missing}
    ai_ids = {x.get("segment_id") for x in selection.get("shots") or [] if isinstance(x, dict)}
    recorded = {x.get("segment_id"): x for x in selection.get("unused") or [] if isinstance(x, dict)}
    rows = []
    for seg in sorted(segments, key=lambda s: s["start"]):
        if seg.get("unusable"):
            continue
        is_must = seg.get("id") in must_ids
        if not is_must and (seg.get("level") != 3 or payloads.in_cut(seg, shots)):
            continue
        cause = CAUSE_MUST if is_must else _cause(seg, source, ai_ids, recorded)
        start, end = float(seg["start"]), float(seg["end"])
        rows.append({
            "id": seg.get("id"), "start": start, "end": end,
            "topic": topic_names.display(seg.get("topic"), names), "topic_raw": seg.get("topic"),
            "text": payloads._clip(seg.get("text")),
            "cause": cause, "cause_label": CAUSE_LABELS[cause],
            "shot": {"in": round(start, 2), "out": round(end, 2),
                     "sub": shot_sub.sub_for(with_lines.get(seg["id"], seg), start, end)},
        })
    return sorted(rows, key=lambda r: r["cause"] != CAUSE_MUST)  # 稳定排序：剪辑列表段在前，各自仍按时间


def _alternatives(unused: list[dict], topic_raw: str | None) -> list[dict]:
    if topic_raw is None:
        return []
    same = sorted((u for u in unused if u["topic_raw"] == topic_raw), key=lambda u: u["start"])
    return [{"id": u["id"], "start": u["start"], "end": u["end"], "text": u["text"]}
            for u in same[:ALTERNATIVES_MAX]]


def _note(shot: dict, ai_by_id: dict, segments: list[dict], unused: list[dict], names: dict) -> dict:
    """一镜的「为什么选它」：AI 选的镜头用选段理由；手动添加 / 挪过的按压住的片段找理由。"""
    lo, hi = float(shot["in"]), float(shot["out"])
    ai = ai_by_id.get(shot["id"])
    if ai and _overlap(float(ai["start"]), float(ai["end"]), lo, hi) > 0:  # 同 id 但时间不重叠 = 另一镜（AI 每次都从 sel01 编号）
        topic_raw, why, seg_id = ai.get("topic"), ai.get("reason") or "", ai.get("segment_id")
    else:
        seg = max((s for s in segments if _overlap(float(s["start"]), float(s["end"]), lo, hi) > 0),
                  key=lambda s: _overlap(float(s["start"]), float(s["end"]), lo, hi), default=None)
        if seg is None:
            return {"why": MANUAL_WHY, "topic": None, "segment_id": None, "alternatives": []}
        topic_raw, why, seg_id = seg.get("topic"), seg.get("level_reason") or MANUAL_WHY, seg.get("id")
    return {"why": why, "topic": topic_names.display(topic_raw, names) if topic_raw else None,
            "segment_id": seg_id, "alternatives": _alternatives(unused, topic_raw)}


def _ai_shots_by_id(selection: dict) -> dict:
    out = {}
    for x in selection.get("shots") or []:
        if isinstance(x, dict) and isinstance(x.get("id"), str) \
                and all(isinstance(x.get(k), (int, float)) for k in ("start", "end")):
            out[x["id"]] = x
    return out


def _topbar(cfg: dict, shots: list[dict], segments: list[dict]) -> dict:
    target = cfg.get("target_duration") or payloads.DEFAULT_TARGET_S
    clip = payloads.clip_list(segments, float(target))
    missing = [s["id"] for s in select.uncovered_must_keep(segments, shots)]
    return {"target": target,
            "total": round(sum(float(s["out"]) - float(s["in"]) for s in shots), 2),
            "shots": len(shots),
            "clip": {"count": len(clip["items"]), "covered": len(clip["items"]) - len(missing),
                     "missing": missing},
            "over_target": clip["over_target"], "must_total": clip["total"],
            "suggested_target": clip["suggested_target"]}


def preview_view(pdir: Path, cfg: dict, name: str, inputs: dict | None = None) -> dict:
    state = outputs.preview_state(pdir, cfg, inputs)
    url = None if state["status"] == "none" else f"/media/{quote(name)}/current-preview?v={quote(str(state['at']))}"
    return {**state, "url": url}


def result(pdir: Path, name: str) -> dict:
    """GET /api/result：⑤ 页面需要的全部服务端数字（分镜表本身仍走 /api/state.shots 与保存队列）。"""
    cfg = schema.read_json(pdir / "project.json")
    work = pdir / "work"
    shots, source = shots_store.current(pdir)  # 损坏 → CorruptJSON，不当作没有
    # applied_segments 已校验每段都有 id / 起止 / 档位（不完整 → AnalysisIncomplete → 409），下面的读取才能直接索引
    segments = payloads.applied_segments(work, schema.read_json(work / "segments_scored.json", default=None))
    selection = _lenient_dict(work / "selection.json")
    names = topic_names.load(work)
    missing = select.uncovered_must_keep(segments, shots)
    with_lines = {s["id"]: s for s in select.with_lines(segments, work / "segments.json")}
    unused = _unused(segments, shots, source, selection, missing, names, with_lines)
    ai_by_id = _ai_shots_by_id(selection)
    inputs = fingerprints.preview_inputs(pdir, cfg)
    return {
        "topbar": _topbar(cfg, shots, segments),
        "notes": {sh["id"]: _note(sh, ai_by_id, segments, unused, names) for sh in shots} if segments else {},
        "unused": unused,
        "preview": preview_view(pdir, cfg, name, inputs),
        "manual": shots_store.manual_changes(pdir),
        "source": source,
        "wizard": wizard.derive(wizard.collect(pdir, cfg, name, preview_inputs=inputs)),
    }


def read_snapshot(vdir: Path) -> list[dict] | None:
    """某一版出片时存下的分镜表；缺失 / 损坏 → None。"""
    path = Path(vdir) / "shots_snapshot.json"
    if not path.is_file():
        return None
    try:
        return schema.read_shots(path)
    except (ValueError, OSError):  # CorruptJSON 是 ValueError 的子类
        return None


def version_dir(pdir: Path, version: object) -> Path:
    version = schema.check_version(version)  # 非法版本号（含 preview、路径穿越）→ ValueError → 400
    found = next((d for d in outputs.version_dirs(pdir) if d.name == version), None)
    if found is None:
        raise FileNotFoundError(VERSION_NOT_FOUND_MSG.format(version=version))
    return found


def _side(d: Path, snapshot: list[dict] | None) -> dict:
    shots, duration = outputs.version_facts(d)
    return {"name": d.name, "preview": media_io.is_complete(d / outputs.PREVIEW_FILE),
            "shots": shots, "duration": duration, "has_snapshot": snapshot is not None}


def compare(pdir: Path, a: object, b: object) -> dict:
    """GET /api/versions/compare：两版并排所需的信息 + 镜头差异（KI-94）；任一版缺快照 → diff 为 null。"""
    da, db = version_dir(pdir, a), version_dir(pdir, b)
    if da == db:
        raise ValueError(COMPARE_SAME_MSG)
    sa, sb = read_snapshot(da), read_snapshot(db)
    base = {"a": _side(da, sa), "b": _side(db, sb)}
    if sa is None or sb is None:
        return {**base, "diff": None, "count": None, "lines": [], "more": 0, "note": COMPARE_NO_SNAPSHOT}
    d = shot_diff.diff(sa, sb)
    lines, more = shot_diff.describe(d, sb)
    return {**base, "diff": d, "count": shot_diff.count(d), "lines": lines, "more": more, "note": None}
