# -*- coding: utf-8 -*-
"""三档判定：把文字 + 声音两路信号合成「废片 / 待定 / 可用」。

原则（对应当初那次翻车）：
  * 信息保底：只要含关键信息，就一定进「可用」，不允许被戏剧性排序挤掉；
  * 待定要少：它是"需要人 30 秒裁决"的队列，超过 40 段人就会被淹没；
  * 每条理由必须是人话，能被人反驳。

三档是处置状态，不是分数：
    废片 = 不进候选
    待定 = 交给人裁决
    可用 = 进入选段池
"""
from __future__ import annotations

import json
from pathlib import Path

# 硬信息类型：出现即「可用」
HARD_TYPES = {"金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"}
# 必留话题关键词（与 PRD 的信息骨架一致）
MUST_TOPIC_WORDS = ("合同", "退费", "费用", "价格", "就业", "工作", "工资",
                    "考证", "资格", "年龄", "签约", "缴费", "课程")
WASTE_TYPES = {"闲聊寒暄"}

MAX_PENDING_RATIO = 0.28  # 待定不超过总段数的 28%（60 分钟约 40 段）


def _topic_must(name: str) -> bool:
    return any(w in name for w in MUST_TOPIC_WORDS)


def _level_of(seg: dict, audio: dict | None, must_topic: bool) -> tuple[int, str]:
    text = seg.get("text", "")
    dur = float(seg.get("end", 0)) - float(seg.get("start", 0))
    info_type = seg.get("info_type", "")
    key = bool(seg.get("key_info"))
    entities = seg.get("entities") or []
    rel_db = (audio or {}).get("rel_db", 0.0)
    rate = (audio or {}).get("speech_rate", 0.0)
    interrupt = (audio or {}).get("interrupt", False)

    if key:
        why = "含关键信息" + (f"：{'、'.join(entities[:3])}" if entities else "")
        return 3, why
    if info_type in HARD_TYPES:
        return 3, f"信息类型为{info_type}"
    if interrupt:
        return 3, "出现抢话/被打断"
    if rel_db >= 4.0 and dur >= 4:
        return 3, f"音量突出（高于中位 {rel_db:+.1f} dB），可能是强调"
    if must_topic:
        return 2, "属于必留话题，需要你判断是否采用"
    if info_type in WASTE_TYPES:
        return 1, f"{info_type}，无关键信息"
    if dur < 3:
        return 1, f"过短且无关键信息（{dur:.1f}s）"
    if dur < 6 and not key:
        return 1, "短句且无关键信息"
    if rate < 2.0 and len(text) < 8:
        return 2, "语速慢、内容短，可能是无意义过渡"
    return 2, "有信息但主体混杂，需要你判断"


def classify(segments: list[dict], audio_by_id: dict | None = None,
             topics: list[dict] | None = None,
             total_target: float = 175.0,
             visual_by_id: dict | None = None) -> dict:
    audio_by_id = audio_by_id or {}
    topic_of = {}
    for t in topics or []:
        for sid in t.get("segment_ids", []):
            topic_of[sid] = t["name"]

    visual_by_id = visual_by_id or {}
    scored = []
    for seg in segments:
        topic = seg.get("topic") or topic_of.get(seg["id"], "")
        lv, why = _level_of(seg, audio_by_id.get(seg["id"]), _topic_must(topic))
        vis = visual_by_id.get(seg["id"], {})
        flags = vis.get("flags") or []
        if "dark" in flags and lv != 3:
            lv, why = 1, "画面过暗，不可用"
        scored.append({**seg, "topic": topic, "level": lv, "level_reason": why,
                       "visual_flags": flags})

    # 待定过多时，把"信息最弱"的待定降为废片，保证人的工作量可控
    pending = [s for s in scored if s["level"] == 2]
    limit = max(10, int(len(scored) * MAX_PENDING_RATIO))
    if len(pending) > limit:
        def weakness(s):
            a = audio_by_id.get(s["id"], {})
            return (a.get("rel_db", 0), len(s.get("text", "")))
        for s in sorted(pending, key=weakness)[:len(pending) - limit]:
            s["level"] = 1
            s["level_reason"] = "待定队列超限，按信息量判定为废片"

    return _assemble(scored, total_target)


def allocate_budget(topics: list[dict], total: float,
                    cap_ratio: float = 0.30) -> list[dict]:
    """把成片总时长分给各话题。

    budget 表示"这部片子里这个题材最多能给多少秒"，不是"可用时长"。
    规则：必留话题拿 75%，按可用时长加权、单个不超过 30%；
          其余话题分 20%，按可用时长比例（避免出现"可用 200 秒、建议 2 秒"）。
    """
    cap = total * cap_ratio
    must = [t for t in topics if t["must"] and t["usable_dur"] > 0]
    others = [t for t in topics if not (t["must"] and t["usable_dur"] > 0)]

    must_pool, others_pool = total * 0.75, total * 0.20
    wsum = sum(min(t["usable_dur"], cap) for t in must) or 1.0
    for t in must:
        t["budget"] = int(max(10, min(cap, must_pool * min(t["usable_dur"], cap) / wsum)))

    active = [t for t in others if t["usable_dur"] > 0]
    wsum2 = sum(t["usable_dur"] for t in active) or 1.0
    for t in others:
        if t["usable_dur"] <= 0:
            t["budget"] = 0
            continue
        share = int(min(cap, others_pool * t["usable_dur"] / wsum2))
        # 有实料的非必留话题，至少给 8 秒，否则界面会出现"建议 1 秒"
        t["budget"] = max(8, share) if t["usable_dur"] >= 15 else share

    total_budget = sum(t["budget"] for t in topics)
    limit = total * 1.05
    if total_budget > limit:  # 加过下限后整体缩回预算内
        scale = limit / total_budget
        for t in topics:
            t["budget"] = int(t["budget"] * scale)
    return topics


def _assemble(scored: list[dict], total_target: float = 175.0) -> dict:
    topics: dict[str, dict] = {}
    for s in scored:
        name = s.get("topic") or "未归类"
        item = topics.setdefault(name, {"name": name, "must": False,
                                        "count": 0, "usable_dur": 0.0,
                                        "duration": 0.0, "key_hits": 0})
        dur = float(s["end"]) - float(s["start"])
        item["count"] += 1
        item["duration"] += dur
        if s.get("key_info"):
            item["key_hits"] += 1
        if s["level"] == 3:
            item["usable_dur"] += dur

    topic_list = []
    for item in topics.values():
        ratio = item["key_hits"] / max(1, item["count"])
        item["must"] = _topic_must(item["name"]) or ratio >= 0.30
        topic_list.append({**item, "duration": round(item["duration"], 1),
                           "usable_dur": round(item["usable_dur"], 1), "budget": 0})
    allocate_budget(topic_list, total_target)

    summary = {name: sum(1 for s in scored if s["level"] == lv)
               for name, lv in (("waste", 1), ("pending", 2), ("usable", 3))}
    return {"summary": summary, "topics": topic_list, "segments": scored,
            "target": total_target}


def run(text_path: Path, audio_path: Path | None, out_path: Path,
        total_target: float = 175.0, visual_path: Path | None = None) -> dict:
    text = json.loads(Path(text_path).read_text(encoding="utf-8"))
    segments = text["segments"]
    audio_by_id: dict[str, dict] = {}
    if audio_path and Path(audio_path).exists():
        audio = json.loads(Path(audio_path).read_text(encoding="utf-8"))
        audio_by_id = {s["id"]: s.get("signals", {}) for s in audio["segments"]}
    visual_by_id: dict[str, dict] = {}
    if visual_path and Path(visual_path).exists():
        visual_by_id = json.loads(Path(visual_path).read_text(encoding="utf-8"))["segments"]
    result = classify(segments, audio_by_id, text.get("topics"), total_target, visual_by_id)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/segments_text.json",
              project / "work/segments_audio.json",
              project / "work/segments_scored.json")
    s = res["summary"]
    print(f"废片 {s['waste']} · 待定 {s['pending']} · 可用 {s['usable']}")
