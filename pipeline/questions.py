# -*- coding: utf-8 -*-
"""2.4 决策问题：由内容生成 3–5 个「答案会改变剪法」的问题。

不是问卷。每个选项都挂一条 rule，选段阶段（M3）据此调整：
    {"kind": "must_topics", "value": ["讲解合同退费条款"]}
    {"kind": "ending", "value": "sign"}
    {"kind": "focus", "value": "main"}
    {"kind": "pacing", "value": "tight"}
    {"kind": "must_lines", "value": ["九千八包含所有耗材"]}

模型挂了就用固定三问兜底，保证流程不断。
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline import applog, schema, select_rules, usage
from pipeline.llm import DeepSeekClient, LLMError

ANSWERS_FILE = "brief_answers.json"
KINDS = {"must_topics", "ending", "focus", "pacing", "exclude", "must_lines"}
LABEL_MAX = 12          # 选项文字最多几个字（截断后同题重名的只留第一个，KI-04）
FALLBACK_LABEL_MAX = 10
FALLBACK_LINE_EFFECT = "强制保留这句原话"

Q_SYSTEM = "你是纪录片剪辑顾问，只输出 JSON。"

Q_USER = """基于下面的素材摘要与话题，提出 3–5 个**会改变剪法**的问题。只输出 JSON。

要求：
- 每个问题 2–4 个选项，单选 type=single 或多选 type=multi
- 每个选项给一句 effect（≤20 字），说明"选了会怎样"
- 每个选项给 rule，kind 只能是：
  focus（主角：value 只能是 main=说话最多的人 或 ensemble=群像）、
  must_topics（必须覆盖的话题）、ending（结尾：sign/leave/emotion/info/silence）、
  pacing（节奏：tight=紧凑 或 normal=正常）、exclude（不能出现什么）
- must_topics 的 value 必须来自下面的话题名
- 不要问"风格是什么"这类无法落到剪辑动作上的问题

输出：
{{"questions":[{{"id":"q1","text":"...","type":"single","options":[{{"label":"...","effect":"...","rule":{{"kind":"focus","value":"..."}}}}]}}]}}

摘要：{summary}

话题：
{topics}

关键信息：
{points}"""


def _topic_names(topics: list[dict]) -> list[str]:
    return [t.get("name", "") for t in topics if t.get("name")]


def _normalize(data: dict, topics: list[dict]) -> dict:
    names = set(_topic_names(topics))
    out = []
    for i, q in enumerate((data.get("questions") or [])[:5], 1):
        text = str(q.get("text") or "").strip()[:40]
        if not text:
            continue
        options = []
        seen: set[str] = set()
        for o in (q.get("options") or [])[:4]:
            label = str(o.get("label") or "").strip()[:LABEL_MAX]
            if not label or label in seen:
                continue
            rule = o.get("rule") or {}
            kind = rule.get("kind")
            if kind not in KINDS:
                continue
            value = rule.get("value")
            if kind == "must_topics":
                if isinstance(value, str):
                    value = [value]
                value = [v for v in (value or []) if v in names]
                if not value:
                    continue
            if kind == "must_lines":
                value = [value] if isinstance(value, str) else value
                if not isinstance(value, list) or not value or \
                        not all(isinstance(v, str) and v.strip() for v in value):
                    continue
            seen.add(label)
            options.append({"label": label,
                            "effect": str(o.get("effect") or "")[:20],
                            "rule": {"kind": kind, "value": value}})
        if len(options) < 2:
            continue
        out.append({"id": f"q{i}", "text": text,
                    "type": "multi" if q.get("type") == "multi" else "single",
                    "options": options})
    if len(out) < 3:
        raise ValueError("有效问题不足 3 个")
    return {"questions": out[:5], "fallback": False}


def fallback(topics: list[dict], segments: list[dict]) -> dict:
    names = _topic_names(topics)[:3]
    key = [s for s in segments if s.get("key_info")][:4]
    must_opts = [{"label": (n[:10] or "话题"), "effect": f"强制覆盖：{n[:10]}",
                  "rule": {"kind": "must_topics", "value": [n]}} for n in names]
    # KI-04：关键信息选项绑「这句原话」，选了真的会进片（以前绑空 must_topics，选了也没用）
    info_opts: list[dict] = []
    for text in (str(s.get("text", "")) for s in key[:4]):
        if text.strip() and text[:FALLBACK_LABEL_MAX] not in {o["label"] for o in info_opts}:
            info_opts.append({"label": text[:FALLBACK_LABEL_MAX], "effect": FALLBACK_LINE_EFFECT,
                              "rule": {"kind": "must_lines", "value": [text]}})
    return {"fallback": True, "questions": [
        {"id": "q1", "text": "这条片子主角是谁？", "type": "single", "options": [
            {"label": "出镜最多的人", "effect": "主角镜头占比 ≥40%",
             "rule": {"kind": "focus", "value": "main"}},
            {"label": "讲述者", "effect": "以旁白组织",
             "rule": {"kind": "focus", "value": "narrator"}},
            {"label": "群像", "effect": "平均分配镜头",
             "rule": {"kind": "focus", "value": "ensemble"}}]},
        {"id": "q2", "text": "必须覆盖哪些话题？", "type": "multi",
         "options": must_opts or info_opts or [
             {"label": "全部", "effect": "不设限",
              "rule": {"kind": "must_topics", "value": []}}]},
        {"id": "q3", "text": "结尾落在哪？", "type": "single", "options": [
            {"label": "最后一个关键信息", "effect": "信息收尾",
             "rule": {"kind": "ending", "value": "info"}},
            {"label": "最有力的句子", "effect": "情绪收尾",
             "rule": {"kind": "ending", "value": "emotion"}},
            {"label": "留白", "effect": "空镜收尾",
             "rule": {"kind": "ending", "value": "silence"}}]},
    ]}


class RegenerateFailed(LLMError):
    """重新生成（--force）时模型失败：原来的决策问题保持不动，不能被兜底模板替换。"""


REGENERATE_FAILED = "重新生成决策问题失败，原来的问题和答案都保持不变：{error}"


def run(summary_path: Path, scored_path: Path, out_path: Path, *,
        client=None, keep_existing: bool = False) -> dict:
    """keep_existing=True（--force 且已有题目）：模型失败时抛 RegenerateFailed，不写兜底。"""
    summary = schema.read_json(summary_path)
    scored = schema.read_json(scored_path)
    segments = schema.require_key(scored, "segments", scored_path)
    topics = scored.get("topics") or []
    client = client or DeepSeekClient()

    points = "\n".join(f'- {p.get("text", "")}' for p in (summary.get("key_points") or [])[:6])
    try:
        data = client.chat_json(
            Q_SYSTEM,
            Q_USER.format(summary=summary.get("summary", ""),
                          topics="\n".join(f"- {n}" for n in _topic_names(topics)),
                          points=points or "（无）"),
            temperature=0.4, max_tokens=1600)
        result = _normalize(data, topics)
    except usage.BudgetExceeded:  # 超预算：由调用方停下，不写兜底
        raise
    except Exception as exc:  # noqa: BLE001 - 任何失败都兜底；真实原因（含堆栈，已脱敏）进诊断日志
        if keep_existing:
            raise RegenerateFailed(REGENERATE_FAILED.format(error=str(exc)[:200]),
                                   retryable=False) from exc
        applog.get("questions").exception("决策问题生成失败，改用兜底模板")
        result = fallback(topics, segments)
        result["error"] = str(exc)[:200]

    schema.write_json(out_path, result)  # 原子写：成功才替换原来的题目
    return result


def has_legacy_focus(qs: dict | None) -> bool:
    """旧提示词生成的题目（KI-86）：focus 选项是自由文本（「妈妈」），M6 后只能报警告、不生效。"""
    known = (*select_rules.FOCUS_MAIN, *select_rules.FOCUS_NONE)
    for q in (qs or {}).get("questions") or [] if isinstance(qs, dict) else []:
        for opt in (q.get("options") or []) if isinstance(q, dict) else []:
            rule = opt.get("rule") if isinstance(opt, dict) else None
            if isinstance(rule, dict) and rule.get("kind") == "focus" and rule.get("value") \
                    and rule["value"] not in known:
                return True
    return False


def reusable(out_path: Path) -> bool:
    """已有决策问题能否直接复用（KI-22）。

    AI 生成的复用；兜底模板只在剪辑师已作答时保留（换题会让答案失效）；缺失 / 读不出来的重新生成。
    """
    try:
        data = schema.read_json(out_path, default=None)
    except schema.CorruptJSON:
        return False
    if not data:
        return False
    return not data.get("fallback") or (Path(out_path).parent / ANSWERS_FILE).exists()


MAX_ANSWER_CHARS = 200   # 一个答案（选项文字）最长多少字；超过的丢掉
MAX_MULTI_ANSWERS = 20   # 多选最多留几项


def _option_labels(question: dict) -> set[str]:
    options = question.get("options")
    return {o["label"] for o in (options if isinstance(options, list) else [])
            if isinstance(o, dict) and isinstance(o.get("label"), str) and 0 < len(o["label"]) <= MAX_ANSWER_CHARS}


def normalize_answers(qs: dict | None, answers) -> dict:
    """磁盘 / 请求里的答案 → {问题 id: str | list[str]}（KI-49）。

    只认这道题选项里的文字：单选恰好一个、多选取子集（去重、保持原顺序、最多 MAX_MULTI_ANSWERS 项）；
    对不上当前问题 id / 选项的一律丢掉（答案会进选段规则，不能让任意文字进来）。
    """
    if not isinstance(answers, dict):
        return {}
    out: dict = {}
    for q in (qs or {}).get("questions") or []:
        qid = q.get("id")
        if qid not in answers:
            continue
        value, labels = answers[qid], _option_labels(q)
        if q.get("type") == "multi":
            values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
            kept = list(dict.fromkeys(v for v in values if isinstance(v, str) and v in labels))
            out[qid] = kept[:MAX_MULTI_ANSWERS]
        elif isinstance(value, str) and value in labels:
            out[qid] = value
    return out
