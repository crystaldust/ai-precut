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

from pipeline import schema

# 硬信息类型：出现即「可用」
HARD_TYPES = {"金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"}
# 必留话题判定参数：预设 presets/<名>.json 的 "must_topic" 可覆盖（KI-07 / D6）
#   words：话题名命中即必留；key_ratio + min_key_hits：话题内关键信息句占比与最少句数
DEFAULT_MUST_TOPIC = {"words": ("合同", "退费", "价格", "就业", "工资", "资格", "签约", "缴费"),
                      "key_ratio": 0.30, "min_key_hits": 2}
INTERRUPT_MAX_DUR = 30.0      # 秒：≥30s 的句子多半是 35s 长度上限切出来的假边界（KI-08 / D7）
INTERRUPT_MIN_REL_DB = 1.0    # 抢话代理信号还要求音量高于中位 1dB
WASTE_TYPES = {"闲聊寒暄"}

MAX_PENDING_RATIO = 0.28  # 待定不超过总段数的 28%（60 分钟约 40 段）
ANNOTATION_FAILED_REASON = "AI 标注失败，需要你判断"
PENDING_DEMOTED_REASON = "待定队列超限，按信息量判定为废片"
DARK_REASON = "画面过暗，不可用"
TEXT_INCOMPLETE_ERROR = ("逐句标注未完成（segments_text.json 标记为未完成），不能据此分档："
                         "先在「② 分析」点「重新分析」或运行 `aicut.py text` 补齐")
LEGACY_FAILED_WARNING = ("{n} 句 AI 标注失败（旧版结果），已放进待定由你判断；"
                         "想让 AI 补标注，删掉 work/segments_text.json 后在「② 分析」点「重新分析」")
AUDIO_MISSING_WARNING = ("没有声音特征（segments_audio.json）：本次分档没用上音量 / 语速 / 抢话，"
                         "在「② 分析」点「重新分析」可补上")
VISUAL_MISSING_WARNING = "没有画面质量结果（visual_quality.json）：本次分档没有识别过暗画面"
PENDING_OVER_WARNING = ("待定 {left} 段超过上限 {limit} 段：其中 {kept} 段属于必留话题或 AI 标注失败，"
                        "不自动降级，需要你逐条裁决")


class TextIncomplete(ValueError):
    """文本标注结果不完整：分档会把没标注的句子当成「无关键信息」。"""


def attach_signals(segments: list[dict], audio_by_id: dict) -> list[dict]:
    """KI-06：把 a 路信号并入每句（新列表），选段打分与情绪结尾才拿得到 rel_db。"""
    return [{**s, "signals": dict(audio_by_id.get(s["id"]) or {})} for s in segments]


def load_audio_signals(audio_path: Path) -> dict[str, dict]:
    """segments_audio.json → {句 id: signals}。没有文件 → {}；损坏 → CorruptJSON（不当「没有」）。"""
    audio = schema.read_json(audio_path, default=None)
    if audio is None:
        return {}
    return {s["id"]: s.get("signals", {})
            for s in schema.require_key(audio, "segments", audio_path) if isinstance(s, dict) and "id" in s}


def must_topic_config(raw: dict | None) -> dict:
    """预设里的 must_topic → 规整后的配置；缺省 / 类型不对的字段用默认值。"""
    raw = raw if isinstance(raw, dict) else {}
    cfg = dict(DEFAULT_MUST_TOPIC)
    words = raw.get("words")
    if isinstance(words, list):
        cfg["words"] = tuple(w for w in words if isinstance(w, str) and w)
    ratio = raw.get("key_ratio")
    if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and 0 < ratio <= 1:
        cfg["key_ratio"] = float(ratio)
    hits = raw.get("min_key_hits")
    if isinstance(hits, int) and not isinstance(hits, bool) and hits >= 1:
        cfg["min_key_hits"] = hits
    return cfg


def _topic_must(name: str, words: tuple[str, ...]) -> bool:
    return any(w in name for w in words)


def _is_interrupt(audio: dict, seg_dur: float) -> bool:
    """真重叠 → 抢话；「换人且停顿 <0.25s」的代理信号只在短句且音量抬高时才算（KI-08）。"""
    if audio.get("overlap"):
        return True
    return (bool(audio.get("interrupt"))
            and float(audio.get("duration") or seg_dur) < INTERRUPT_MAX_DUR
            and float(audio.get("rel_db") or 0.0) >= INTERRUPT_MIN_REL_DB)


def _level_of(seg: dict, audio: dict | None, must_topic: bool) -> tuple[int, str]:
    text = seg.get("text", "")
    dur = float(seg.get("end", 0)) - float(seg.get("start", 0))
    info_type = seg.get("info_type", "")
    key = bool(seg.get("key_info"))
    entities = seg.get("entities") or []
    rel_db = (audio or {}).get("rel_db", 0.0)
    rate = (audio or {}).get("speech_rate", 0.0)
    interrupt = _is_interrupt(audio or {}, dur)

    if key:
        why = "含关键信息" + (f"：{'、'.join(entities[:3])}" if entities else "")
        return 3, why
    if info_type in HARD_TYPES:
        return 3, f"信息类型为{info_type}"
    if interrupt:
        return 3, "出现抢话/被打断"
    if rel_db >= 4.0 and dur >= 4:
        return 3, f"音量突出（高于中位 {rel_db:+.1f} dB），可能是强调"
    if seg.get("annotation_failed"):  # GL-09：没拿到标注 ≠ 没有关键信息，交给人判断
        return 2, ANNOTATION_FAILED_REASON
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


def _must_topic_names(scored: list[dict], cfg: dict | None = None) -> set[str]:
    """必留话题 = 名称命中关键词，或话题内关键信息句 ≥ min_key_hits 且占比 ≥ key_ratio。

    只依赖 topic / key_info：先定口径再判档位，档位与 topics[].must 用同一份结果（KI-58）。
    """
    cfg = cfg or must_topic_config(None)
    count: dict[str, int] = {}
    keys: dict[str, int] = {}
    for s in scored:
        name = s.get("topic") or "未归类"
        count[name] = count.get(name, 0) + 1
        keys[name] = keys.get(name, 0) + (1 if s.get("key_info") else 0)
    return {n for n in count if _topic_must(n, cfg["words"])
            or (keys[n] >= cfg["min_key_hits"] and keys[n] / count[n] >= cfg["key_ratio"])}


def _protected(s: dict, must_names: set[str]) -> bool:
    """必留话题段、标注失败段：只能由人判废片（GL-09 / GL-24）。"""
    return (s.get("topic") or "未归类") in must_names or bool(s.get("annotation_failed"))


def _apply_dark(s: dict, must_names: set[str]) -> dict:
    if "dark" not in s["visual_flags"] or s["level"] == 3:
        return s
    if s["level"] == 2 and _protected(s, must_names):  # 只防降级，不把废片抬成待定
        return {**s, "level": 2, "level_reason": f"画面过暗；{s['level_reason']}"}
    return {**s, "level": 1, "level_reason": DARK_REASON}


def _cap_pending(scored: list[dict], must_names: set[str],
                 audio_by_id: dict) -> tuple[list[dict], dict, list[str]]:
    """待定过多时，把非保护段里「信息最弱」的降为废片；保护段超限只给警告。"""
    limit = max(10, int(len(scored) * MAX_PENDING_RATIO))

    def weakness(s: dict) -> tuple:
        a = audio_by_id.get(s["id"], {})
        return (a.get("rel_db", 0), len(s.get("text", "")))

    pending = [s for s in scored if s["level"] == 2]
    excess = max(0, len(pending) - limit)
    demotable = sorted((s for s in pending if not _protected(s, must_names)), key=weakness)
    demote = {s["id"] for s in demotable[:excess]}
    out = [{**s, "level": 1, "level_reason": PENDING_DEMOTED_REASON}
           if s["id"] in demote else s for s in scored]
    left = sum(1 for s in out if s["level"] == 2)
    kept = sum(1 for s in out if s["level"] == 2 and _protected(s, must_names))
    warnings = ([PENDING_OVER_WARNING.format(left=left, limit=limit, kept=kept)]
                if left > limit else [])
    return out, {"limit": limit, "demoted": len(demote)}, warnings


def classify(segments: list[dict], audio_by_id: dict | None = None,
             topics: list[dict] | None = None,
             total_target: float = 175.0,
             visual_by_id: dict | None = None, *, must_topic: dict | None = None) -> dict:
    audio_by_id = audio_by_id or {}
    visual_by_id = visual_by_id or {}
    topic_of = {}
    for t in topics or []:
        for sid in t.get("segment_ids", []):
            topic_of[sid] = t["name"]

    topical = [{**seg, "topic": seg.get("topic") or topic_of.get(seg["id"], "")} for seg in segments]
    must_names = _must_topic_names(topical, must_topic_config(must_topic))  # KI-58：先定口径
    base = []
    for seg in attach_signals(topical, audio_by_id):  # KI-06：scored 段带 signals
        lv, why = _level_of(seg, seg["signals"], (seg["topic"] or "未归类") in must_names)
        flags = visual_by_id.get(seg["id"], {}).get("flags") or []
        base.append({**seg, "level": lv, "level_reason": why, "visual_flags": flags})
    scored = [_apply_dark(s, must_names) for s in base]
    scored, pending, warnings = _cap_pending(scored, must_names, audio_by_id)
    result = _assemble(scored, total_target, must_names)
    return {**result, "pending": pending, "warnings": warnings}


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


def _assemble(scored: list[dict], total_target: float = 175.0,
              must_names: set[str] | None = None) -> dict:
    must_names = _must_topic_names(scored) if must_names is None else must_names
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
        item["must"] = item["name"] in must_names
        topic_list.append({**item, "duration": round(item["duration"], 1),
                           "usable_dur": round(item["usable_dur"], 1), "budget": 0})
    allocate_budget(topic_list, total_target)

    summary = {name: sum(1 for s in scored if s["level"] == lv)
               for name, lv in (("waste", 1), ("pending", 2), ("usable", 3))}
    return {"summary": summary, "topics": topic_list, "segments": scored,
            "target": total_target}


def run(text_path: Path, audio_path: Path | None, out_path: Path,
        total_target: float = 175.0, visual_path: Path | None = None,
        must_topic: dict | None = None) -> dict:
    text = schema.read_json(text_path)
    if text.get("complete") is False:
        raise TextIncomplete(TEXT_INCOMPLETE_ERROR)
    # 旧版程序：失败批次只记在 failures 里，句子本身看不出来 → 补上标记
    legacy_failed = {sid for f in text.get("failures") or [] for sid in f.get("ids") or []}
    segments = [{**s, "annotation_failed": True} if s["id"] in legacy_failed else s
                for s in schema.require_key(text, "segments", text_path)]
    # KI-21：给了路径但没有文件 → 说出来；文件损坏 → CorruptJSON，不当成「没有」
    missing: list[str] = []
    audio_by_id: dict[str, dict] = {}
    if audio_path:
        if not Path(audio_path).exists():
            missing.append(AUDIO_MISSING_WARNING)
        else:
            audio_by_id = load_audio_signals(audio_path)
    visual_by_id: dict[str, dict] = {}
    if visual_path:
        visual = schema.read_json(visual_path, default=None)
        if visual is None:
            missing.append(VISUAL_MISSING_WARNING)
        else:
            visual_by_id = schema.require_key(visual, "segments", visual_path, dict)
    result = classify(segments, audio_by_id, text.get("topics"), total_target, visual_by_id,
                      must_topic=must_topic)
    marked = sum(1 for s in segments if s["id"] in legacy_failed)
    legacy = [LEGACY_FAILED_WARNING.format(n=marked)] if marked else []
    if missing or legacy:
        result = {**result, "warnings": [*missing, *legacy, *result["warnings"]]}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema.stamp(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/segments_text.json",
              project / "work/segments_audio.json",
              project / "work/segments_scored.json")
    s = res["summary"]
    print(f"废片 {s['waste']} · 待定 {s['pending']} · 可用 {s['usable']}")
