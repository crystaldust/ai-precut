# -*- coding: utf-8 -*-
"""b 路：让 LLM 把文稿切成话题，并标注每句的信息类型与关键信息。

两件事分两次调用：
  1. 话题分段：把整段对话归成 8–15 个话题（全局视角，一次调用）
  2. 逐句标注：信息类型、实体、是否关键信息（分批，每批 40 句）

设计取舍：
  * 不让模型自由发挥，只让它做"分类 + 抽取"，输出必须能落到枚举里；
  * key_info 的判定标准写在 prompt 里，而且是可验证的（金额/期限/条件/承诺/资格/数字/专名）；
  * 批处理失败先重试；仍失败的句子标 annotation_failed、结果落盘后报错，重跑只补这些句子。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from pipeline import schema
from pipeline.llm import DeepSeekClient, LLMError, describe

ANNOTATE_RETRIES = 2  # 每批在客户端 HTTP 重试之外，再整批/补漏重试的次数（覆盖 JSON 解析失败、漏 id）
ANNOTATION_RETRY_HINT = "结果已保存；检查网络/额度后重新运行「处理素材」，只会重跑这 {n} 句"
ANNOTATE_BACKOFF = (2.0, 5.0)  # 批次重试前等待的秒数（第 1 次、第 2 次…）
ANNOTATION_MISSING_ERROR = "模型漏标 {n} 句"
ANNOTATION_SHAPE_ERROR = "标注结果结构异常：{detail}"
ANNOTATION_SKIPPED_ERROR = "前面的批次遇到无法重试的错误，未调用：{error}"
_sleep = time.sleep  # 测试里替换成空操作
_ANN_KEYS = ("info_type", "key_info", "entities", "reason")


class AnnotationIncomplete(LLMError):
    """逐句标注重试后仍有句子没拿到结果——不能当作「无关键信息」继续往下走。"""

    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        head = ", ".join(ids[:10]) + ("…" if len(ids) > 10 else "")
        super().__init__(f"{len(ids)} 句逐句标注失败（每批已重试 {ANNOTATE_RETRIES} 次）：{head}；"
                         + ANNOTATION_RETRY_HINT.format(n=len(ids)))


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


def _normalize(item: dict) -> dict:
    """模型给的形状不对（如 entities 是数字）→ LLMError，让这一批重试，而不是让整个任务崩掉。"""
    entities = item.get("entities") or []
    if not isinstance(entities, list):
        raise LLMError(ANNOTATION_SHAPE_ERROR.format(
            detail=f"entities 是 {type(entities).__name__}"))
    return {"info_type": str(item.get("info_type") or "事实陈述")[:12],
            "key_info": bool(item.get("key_info")),
            "entities": [str(e)[:30] for e in entities][:8],
            "reason": str(item.get("reason") or "")[:40]}


def _annotate_once(client, chunk: list[dict], style: str) -> dict[str, dict]:
    prompt = ANNOTATE_USER.format(listing=_listing(chunk))
    if style:
        prompt = f"{prompt}\n\n{style}"
    data = client.chat_json(ANNOTATE_SYSTEM, prompt, temperature=0.1, max_tokens=4000)
    items = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise LLMError(ANNOTATION_SHAPE_ERROR.format(detail=describe(str(data))))
    wanted = {s["id"] for s in chunk}
    return {item["id"]: _normalize(item) for item in items
            if isinstance(item.get("id"), str) and item["id"] in wanted}


def annotate(client, segments: list[dict], *, batch: int = 40, style: str = "",
             retries: int = ANNOTATE_RETRIES, sleep=None) -> tuple[dict, list[dict]]:
    """逐批标注；失败整批重试（带退避），漏标的 id 单独补问；仍拿不到的记进 failures。

    遇到不可重试的错误（鉴权/参数/余额）立刻停：这一批和后面的批次都记为失败，不再调用。
    """
    sleep = sleep or _sleep
    result: dict[str, dict] = {}
    failures: list[dict] = []
    fatal = ""
    for chunk in _chunks(segments, batch):
        if fatal:
            failures.append({"ids": [s["id"] for s in chunk],
                             "error": ANNOTATION_SKIPPED_ERROR.format(error=fatal)})
            continue
        todo, error = list(chunk), ""
        for attempt in range(retries + 1):
            if attempt:
                sleep(ANNOTATE_BACKOFF[min(attempt - 1, len(ANNOTATE_BACKOFF) - 1)])
            try:
                got = _annotate_once(client, todo, style)
            except LLMError as exc:
                error = str(exc)[:200]
                if not exc.retryable:
                    fatal = error
                    break
                continue
            result = {**result, **got}
            todo = [s for s in todo if s["id"] not in got]
            if not todo:
                break
            error = ANNOTATION_MISSING_ERROR.format(n=len(todo))
        if todo:
            failures.append({"ids": [s["id"] for s in todo], "error": error})
    return result, failures


def _fingerprint(segments: list[dict], style: str, model: str) -> str:
    payload = json.dumps([[s["id"], s.get("text", "")] for s in segments] + [style, model],
                         ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def partial_path(out_path: Path) -> Path:
    """未完成的结果单独存：不覆盖上一次完整的 segments_text.json，重跑时从这里续。"""
    out_path = Path(out_path)
    return out_path.with_name(f"{out_path.stem}.partial{out_path.suffix}")


def is_incomplete(out_path: Path) -> bool:
    """逐句标注是否还有没完成的句子（含旧版程序留下的 failures）。"""
    if partial_path(out_path).exists():
        return True
    try:
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and (data.get("complete") is False
                                       or bool(data.get("failures")))


def _resumable(partial: Path, fingerprint: str) -> dict | None:
    """上次未完成且输入没变 → 可以只补失败句子。"""
    try:
        prev = json.loads(Path(partial).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (isinstance(prev, dict) and prev.get("complete") is False
          and prev.get("input_hash") == fingerprint)
    return prev if ok else None


def _merge(segments: list[dict], topics: list[dict], annotations: dict,
           failed: set[str]) -> list[dict]:
    topic_of = {sid: t["name"] for t in topics for sid in t["segment_ids"]}
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
            "annotation_failed": s["id"] in failed,
        })
    return merged


def run(segments_path: Path, out_path: Path, *, client=None,
        batch: int = 40, model: str | None = None, style: str = "",
        sleep=None) -> dict:
    segments = json.loads(Path(segments_path).read_text(encoding="utf-8"))["segments"]
    # 只把有文本的句子送进模型
    usable = [s for s in segments if (s.get("text") or "").strip()]
    client = client or DeepSeekClient()
    label = model or getattr(client, "model", "")
    fp = _fingerprint(segments, style, label)
    partial = partial_path(out_path)
    prev = _resumable(partial, fp)
    if prev:
        topics = prev["topics"]
        done = {s["id"]: {k: s[k] for k in _ANN_KEYS}
                for s in prev["segments"] if not s.get("annotation_failed")}
        fresh, failures = annotate(client, [s for s in usable if s["id"] not in done],
                                   batch=batch, style=style, sleep=sleep)
        annotations = {**done, **fresh}
    else:
        topics = segment_topics(client, usable)
        annotations, failures = annotate(client, usable, batch=batch, style=style,
                                         sleep=sleep)
    failed = {sid for f in failures for sid in f["ids"]}

    result = {
        "model": label,
        "topics": topics,
        "failures": failures,
        "complete": not failed,
        "input_hash": fp,
        "resumed": bool(prev),
        "segments": _merge(segments, topics, annotations, failed),
    }
    if failed:  # 先落盘（单独的 partial 文件）再报错：重跑时只补这些句子
        schema.write_json(partial, result)
        raise AnnotationIncomplete(sorted(failed))
    schema.write_json(out_path, result)
    partial.unlink(missing_ok=True)
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/segments.json", project / "work/segments_text.json")
    key = sum(1 for s in res["segments"] if s["key_info"])
    print(f"话题 {len(res['topics'])} 个 · 关键信息 {key} 句 · 失败批次 {len(res['failures'])}")
