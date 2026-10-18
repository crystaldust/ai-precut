# -*- coding: utf-8 -*-
"""1.5 内容摘要：给剪辑师一句话说明"素材讲了什么"，外加 3–6 个关键信息。

摘要不是给机器看的元数据，是给人在 10 秒内判断"这条素材能不能用"的东西。
所以要求：一句话、≤80 字、带 3–6 个可回查的时间点。

失败不阻塞流程：模型挂了就退回"话题罗列式"摘要，并在结果里标记 fallback。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline.llm import DeepSeekClient, LLMError

SUMMARY_SYSTEM = "你是纪录片剪辑助理，只输出 JSON。"

SUMMARY_USER = """根据下面的素材结构，写一段内容摘要。只输出 JSON。

要求：
- summary：一句话说明素材讲了什么，**不超过 80 字**，不要形容词堆砌
- key_points：3–6 条最重要的信息，每条 text ≤20 字，at 用给定时间（秒），why ≤15 字
- cast：主要角色，最多 3 个，name ≤6 字，desc ≤15 字
- 只能使用下面出现过的信息，不要编造

输出格式：
{{"summary":"...","key_points":[{{"text":"...","at":123.4,"why":"..."}}],"cast":[{{"name":"...","desc":"..."}}]}}

话题：
{topics}

关键信息（时间 文本）：
{points}"""


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", "", text or "")
    return text[:n]


def _listing(topics: list[dict], segments: list[dict]) -> tuple[str, str]:
    t_lines = []
    for t in topics:
        t_lines.append(f'- {t.get("name", "")}（{t.get("duration", 0):.0f}s，'
                       f'可用 {t.get("usable_dur", 0):.0f}s）')
    p_lines = []
    for s in segments:
        if s.get("key_info"):
            p_lines.append(f'{s["start"]:.1f} {_clip(s.get("text", ""), 40)}')
    return "\n".join(t_lines), "\n".join(p_lines[:40])


def _snap(at: float, segments: list[dict]) -> float:
    """把模型给的时间吸附到最近的关键句起点，避免对不上素材。"""
    starts = [float(s["start"]) for s in segments]
    if not starts:
        return round(float(at), 1)
    nearest = min(starts, key=lambda x: abs(x - float(at)))
    return round(nearest, 1)


def fallback(segments: list[dict], topics: list[dict]) -> dict:
    names = [t.get("name", "") for t in topics if t.get("name")]
    key = [s for s in segments if s.get("key_info")][:4]
    return {
        "summary": _clip("素材包含：" + "、".join(names[:4]) + "等内容", 80),
        "key_points": [{"text": _clip(s.get("text", ""), 20),
                        "at": round(float(s["start"]), 1),
                        "why": s.get("reason", "")[:15]} for s in key],
        "cast": [],
        "fallback": True,
    }


def _normalize(data: dict, segments: list[dict]) -> dict:
    summary = _clip(data.get("summary", ""), 80)
    points = []
    for p in (data.get("key_points") or [])[:6]:
        text = _clip(p.get("text", ""), 20)
        if not text:
            continue
        points.append({"text": text, "at": _snap(p.get("at", 0), segments),
                       "why": _clip(p.get("why", ""), 15)})
    cast = []
    for c in (data.get("cast") or [])[:3]:
        name = _clip(c.get("name", ""), 6)
        if name:
            cast.append({"name": name, "desc": _clip(c.get("desc", ""), 15)})
    points.sort(key=lambda p: p["at"])  # 按时间排，方便在时间轴上看
    return {"summary": summary, "key_points": points, "cast": cast, "fallback": False}


def run(text_path: Path, scored_path: Path, out_path: Path,
        *, client=None, model: str | None = None) -> dict:
    text = json.loads(Path(text_path).read_text(encoding="utf-8"))
    scored = json.loads(Path(scored_path).read_text(encoding="utf-8"))
    segments = scored["segments"]
    topics = scored.get("topics") or text.get("topics") or []

    client = client or DeepSeekClient()
    t_list, p_list = _listing(topics, segments)
    try:
        data = client.chat_json(
            SUMMARY_SYSTEM,
            SUMMARY_USER.format(topics=t_list or "（无）", points=p_list or "（无）"),
            temperature=0.2, max_tokens=1200)
        result = _normalize(data, segments)
        if not result["summary"]:
            raise LLMError("摘要为空")
    except Exception as exc:  # noqa: BLE001 - 任何失败都退回兜底
        result = fallback(segments, topics)
        result["error"] = str(exc)[:200]

    result["model"] = model or getattr(client, "model", "")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/segments_text.json",
              project / "work/segments_scored.json",
              project / "work/content_summary.json")
    print(res["summary"])
