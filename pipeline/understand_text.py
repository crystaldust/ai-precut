# -*- coding: utf-8 -*-
"""b 路：让 LLM 把文稿切成话题，并标注每句的信息类型与关键信息。

两件事分两次调用：
  1. 话题分段：把整段对话归成 8–15 个话题（全局视角，一次调用）
  2. 逐句标注：信息类型、实体、是否关键信息（分批，每批 40 句）

设计取舍：
  * 不让模型自由发挥，只让它做"分类 + 抽取"，输出必须能落到枚举里；
  * key_info 的判定标准写在 prompt 里，而且是可验证的（金额/期限/条件/承诺/资格/数字/专名）；
  * 批处理失败只丢那一批，其余照常，结果文件里记下失败批次。
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.llm import DeepSeekClient, LLMError

TOPIC_SYSTEM = "你是纪录片剪辑助理。只输出 JSON，不要解释。"

TOPIC_USER = """下面是一段现场对话的逐句清单（id 起始时间 文本）。
请把它归并成 8–15 个话题（**最多 15 个，超过算不合格**），覆盖全部句子，每句只出现一次。

要求：
- 话题名 6–12 个字，用"做什么"的动宾结构，例如"讲解合同条款""谈课程与价格"
- 按时间顺序排列
- segment_ids 必须来自清单，不能编造

只输出 JSON：
{{"topics":[{{"name":"...","segment_ids":["S001","S002"]}}]}}

清单：
{listing}"""

ANNOTATE_SYSTEM = "你是纪录片剪辑助理，只输出 JSON。"

ANNOTATE_USER = """给下面每句话标注三类信息。只输出 JSON。

规则：
- info_type 只能是：金额价格、条款期限、承诺保证、资格限制、异议质疑、事实陈述、个人故事、闲聊寒暄
- **异议质疑**：说话人提出怀疑、追问、反驳、担心时用它，例如"找不到工作不白学吗""能保证吗""这也太贵了吧"
- key_info：**只有"观众需要记住、会影响判断"的信息才给 true**，仅限这几类：
  金额/价格、费用构成、期限、退费条件、就业承诺、资格限制、课程内容与时长
- 以下一律 false（即使出现了人名或数字）：
  打招呼、方位停车、天气、日常作息时间、对人名的寒暄、口头禅、重复的客套话
- entities：只填**具体值或专名**（如"九千八""三个月""16 周岁""济南""皮肤管理高级班"），
  不要填"合同""老师""美容师"这类普通名词；没有就给 []
- reason：≤20 字的判定依据

只输出 JSON：
{{"segments":[{{"id":"S001","info_type":"...","key_info":true,"entities":["九千八"],"reason":"..."}}]}}

句子：
{listing}"""


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _listing(segments: list[dict], *, max_chars: int = 60) -> str:
    lines = []
    for s in segments:
        text = s.get("text", "").replace("\n", " ")[:max_chars]
        lines.append(f'{s["id"]} {int(s["start"] // 60):02d}:{int(s["start"] % 60):02d} {text}')
    return "\n".join(lines)


MERGE_SYSTEM = "你是纪录片剪辑助理，只输出 JSON。"
MERGE_USER = """下面是 {n} 个话题。请合并成不超过 15 个，语义相近的合并，保持时间顺序。
只输出 JSON：{{"groups":[{{"name":"合并后的话题名","indexes":[0,1]}}]}}

话题清单：
{listing}"""


def _merge_topics_via_llm(client, topics: list[dict], max_n: int = 15) -> list[dict] | None:
    listing = "\n".join(f'{i}. {t["name"]}' for i, t in enumerate(topics))
    try:
        data = client.chat_json(MERGE_SYSTEM,
                                MERGE_USER.format(n=len(topics), listing=listing),
                                temperature=0.1, max_tokens=1200)
    except Exception:  # noqa: BLE001 - 合并失败就走体量兜底
        return None
    groups = data.get("groups") or []
    used: set[int] = set()
    out = []
    for g in groups:
        idx = [i for i in (g.get("indexes") or []) if isinstance(i, int)
               and 0 <= i < len(topics) and i not in used]
        if not idx:
            continue
        used.update(idx)
        ids: list[str] = []
        for i in idx:
            ids.extend(topics[i]["segment_ids"])
        out.append({"name": str(g.get("name") or topics[idx[0]]["name"])[:20],
                    "segment_ids": ids})
    if len(used) != len(topics) or len(out) > max_n or not out:
        return None
    return out


def _split_large(topics: list[dict], max_segments: int = 12) -> list[dict]:
    """单话题过大时按时间切成若干段，避免界面上出现 40 句一坨。"""
    out: list[dict] = []
    for t in topics:
        ids = t["segment_ids"]
        if len(ids) <= max_segments:
            out.append(t)
            continue
        parts = [ids[i:i + max_segments] for i in range(0, len(ids), max_segments)]
        for n, part in enumerate(parts, 1):
            out.append({"name": f'{t["name"]}({n}/{len(parts)})'[:24],
                        "segment_ids": part})
    return out


def _cap_topics(topics: list[dict], max_n: int = 15) -> list[dict]:
    """话题过多时，反复合并"最短的相邻两个"，保证不超过 max_n。"""
    out = [t for t in topics if t["segment_ids"]]
    while len(out) > max_n:
        sizes = [len(t["segment_ids"]) for t in out]
        i = min(range(len(out) - 1), key=lambda k: sizes[k] + sizes[k + 1])
        merged = {
            "name": (out[i]["name"] + "·" + out[i + 1]["name"])[:20],
            "segment_ids": out[i]["segment_ids"] + out[i + 1]["segment_ids"],
        }
        out[i:i + 2] = [merged]
    return out


def segment_topics(client, segments: list[dict]) -> list[dict]:
    prompt = TOPIC_USER.format(listing=_listing(segments, max_chars=40))
    data = client.chat_json(TOPIC_SYSTEM, prompt, temperature=0.1, max_tokens=3000)
    topics = data.get("topics") or []
    valid = {s["id"] for s in segments}
    seen: set[str] = set()
    out = []
    for t in topics:
        ids = [i for i in (t.get("segment_ids") or []) if i in valid and i not in seen]
        if not ids:
            continue
        seen.update(ids)
        out.append({"name": str(t.get("name") or "未命名")[:20], "segment_ids": ids})
    missing = valid - seen
    if missing:  # 模型漏掉的句子兜底并入最后一个话题
        if out:
            out[-1]["segment_ids"].extend(sorted(missing))
        else:
            out = [{"name": "全部内容", "segment_ids": sorted(missing)}]
    if len(out) > 15:
        out = _merge_topics_via_llm(client, out) or _cap_topics(out)
    return _split_large(out)


def annotate(client, segments: list[dict], *, batch: int = 40,
             style: str = "") -> tuple[dict, list[dict]]:
    result: dict[str, dict] = {}
    failures: list[dict] = []
    for chunk in _chunks(segments, batch):
        prompt = ANNOTATE_USER.format(listing=_listing(chunk))
        if style:
            prompt = f"{prompt}\n\n{style}"
        try:
            data = client.chat_json(ANNOTATE_SYSTEM, prompt, temperature=0.1, max_tokens=4000)
        except LLMError as exc:
            failures.append({"ids": [s["id"] for s in chunk], "error": str(exc)[:200]})
            continue
        for item in data.get("segments") or []:
            sid = item.get("id")
            if sid:
                result[sid] = {
                    "info_type": str(item.get("info_type") or "事实陈述")[:12],
                    "key_info": bool(item.get("key_info")),
                    "entities": [str(e)[:30] for e in (item.get("entities") or [])][:8],
                    "reason": str(item.get("reason") or "")[:40],
                }
    return result, failures


def run(segments_path: Path, out_path: Path, *, client=None,
        batch: int = 40, model: str | None = None, style: str = "") -> dict:
    segments = json.loads(Path(segments_path).read_text(encoding="utf-8"))["segments"]
    # 只把有文本的句子送进模型
    usable = [s for s in segments if (s.get("text") or "").strip()]
    client = client or DeepSeekClient()
    topics = segment_topics(client, usable)
    annotations, failures = annotate(client, usable, batch=batch, style=style)

    topic_of: dict[str, str] = {}
    for topic in topics:
        for sid in topic["segment_ids"]:
            topic_of[sid] = topic["name"]

    merged = []
    for s in segments:
        ann = annotations.get(s["id"], {})
        merged.append({
            "id": s["id"], "start": s.get("start"), "end": s.get("end"),
            "speaker": s.get("speaker"), "text": s.get("text", ""),
            "topic": topic_of.get(s["id"], ""),
            "info_type": ann.get("info_type", ""),
            "key_info": ann.get("key_info", False),
            "entities": ann.get("entities", []),
            "reason": ann.get("reason", ""),
        })

    result = {
        "model": model or getattr(client, "model", ""),
        "topics": topics,
        "failures": failures,
        "segments": merged,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/segments.json", project / "work/segments_text.json")
    key = sum(1 for s in res["segments"] if s["key_info"])
    print(f"话题 {len(res['topics'])} 个 · 关键信息 {key} 句 · 失败批次 {len(res['failures'])}")
