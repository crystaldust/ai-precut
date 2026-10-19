# -*- coding: utf-8 -*-
"""选段规则：确认页答案 → 规则、结尾/节奏归一、必留原话解析与命中、主角映射（M6）。

为什么单独成模块：
    select.py 管「怎么剪」，这里管「剪辑师要什么」。规则解释错了（跨题同名 label 互相覆盖、
    pacing 看 label 不看 value、必留原话被逗号切成「嗯」「对」碎片强制进片）都是这一层的问题。
所有函数返回新对象，不改输入。
"""
from __future__ import annotations

import re

ENDINGS = ("sign", "leave", "emotion", "silence", "info")
PACINGS = ("tight", "normal")
DEFAULT_PACING = "normal"
PACING_MAX_SHOT = {"tight": 12.0, "normal": 25.0}   # 秒：紧凑节奏单镜上限（D3）
FOCUS_BONUS = 2.0                                     # 主角说话人每段加分（D2）
FOCUS_MAIN = ("main", "narrator")                    # 「出镜最多的人」「讲述者」→ 说话总时长最多的人
FOCUS_NONE = ("ensemble",)                           # 群像：不加分
FOCUS_UNMAPPED_WARNING = "主角「{focus}」无法对应到说话人，这条偏好没有生效"

MUST_LINE_MIN_CHARS = 4      # 逗号碎片少于这么多字就太容易误中（「嗯」「对」），忽略
MUST_LINE_SHOWN_CHARS = 12   # 警告里引用原话最多几个字
MUST_LINE_NOT_FOUND = "指定必须保留的原话「{line}」在转写里找不到，没能进片：检查是否和原话一字不差（可能被分成了两句）"
MUST_LINE_FRAGMENT_SHORT = "指定原话片段「{line}」太短（少于 {n} 字），已忽略：请写成完整的一句"
MUST_LINE_MIN_WHOLE = 2      # 整句原话至少几个字：单字（「对」）几乎每句都有，没法可靠定位
MUST_LINE_WHOLE_SHORT = "指定原话「{line}」太短（少于 {n} 字），没法可靠定位，已忽略：请写成完整的一句"

_ENDING_WORDS = (("sign", ("签", "缴费", "转账", "付款")),
                 ("leave", ("离", "走", "出门", "背影")),
                 ("info", ("信息",)),
                 ("emotion", ("情绪", "有力", "金句", "感动")),
                 ("silence", ("留白", "空镜", "静")))
_TIGHT_WORDS = ("紧", "快")
_NEGATIONS = ("不", "别", "勿", "没", "无需", "无须")
NEGATION_WINDOW = 3          # 「紧/快」前几个字内出现否定词就不算（「不要太紧」）
_QUOTE_SPLIT = re.compile(r"[\n\r；;]+")
_FRAGMENT_SPLIT = re.compile(r"[，,、]+")
_PUNCT = re.compile(r"[\s，。！？、,.!?；;：:“”\"'‘’…（）()《》\-—]+")


# 「答案 → 规则」的换算版本（KI-84）：存下的规则版本不等于它就按当前题目重算，不沿用旧逻辑的结果
RULES_VERSION = 2

def norm_ending(value) -> str | None:
    """把模型生成的中文结尾描述归一到枚举（含兜底题的 info）。"""
    if not value or not isinstance(value, str):
        return None
    if value in ENDINGS:
        return value
    for canon, keys in _ENDING_WORDS:
        if any(k in value for k in keys):
            return canon
    return None


def norm_pacing(value) -> str:
    """规则 value 优先；自由文本含「紧/快」→ tight，其余 normal（KI-04：不再看 label）。"""
    if value in PACINGS:
        return value
    if isinstance(value, str) and any(_affirmed(value, i) for i, c in enumerate(value) if c in _TIGHT_WORDS):
        return "tight"
    return DEFAULT_PACING


def _affirmed(text: str, i: int) -> bool:
    before = text[max(0, i - NEGATION_WINDOW):i]
    return not any(n in before for n in _NEGATIONS)


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _apply_rule(rules: dict, rule: dict) -> dict:
    kind, val = rule.get("kind"), rule.get("value")
    if kind == "must_topics":
        return {**rules, "must_topics": [*rules["must_topics"], *_as_list(val)]}
    if kind == "exclude":
        return {**rules, "exclude_topics": [*rules["exclude_topics"], *_as_list(val)]}
    if kind == "ending":
        return {**rules, "ending": norm_ending(val)}
    if kind == "focus":
        return {**rules, "focus": str(val) if val else None}
    if kind == "pacing":
        return {**rules, "pacing": norm_pacing(val)}
    if kind == "must_lines":
        lines = [v.strip() for v in _as_list(val) if isinstance(v, str) and v.strip()]
        return {**rules, "must_lines": [*rules["must_lines"], *lines]}
    return rules


def _options_by_question(questions: dict | None) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for q in (questions or {}).get("questions") or []:
        if not isinstance(q, dict):
            continue
        opts: dict[str, dict] = {}
        for o in q.get("options") or []:
            if isinstance(o, dict) and o.get("label") not in opts:
                opts[o.get("label")] = o.get("rule") if isinstance(o.get("rule"), dict) else {}
        out[q.get("id")] = opts
    return out


def rules_from_answers(answers: dict, questions: dict | None) -> dict:
    """答案 → 选段规则。按「题 id → label」查：不同题里同名的 label 不再互相覆盖（KI-04）。

    对不上当前题目任何选项的答案记进 ignored_answers（KI-23），由选段转成警告。
    """
    rules: dict = {"must_topics": [], "exclude_topics": [], "ending": None,
                   "focus": None, "pacing": DEFAULT_PACING, "must_lines": []}
    ignored: list[str] = []
    by_q = _options_by_question(questions)
    for qid, value in (answers if isinstance(answers, dict) else {}).items():
        options = by_q.get(qid) or {}
        for label in _as_list(value):
            if not isinstance(label, str) or not label:
                continue
            if label not in options:
                ignored.append(label)
                continue
            rules = _apply_rule(rules, options[label])
    return {**rules, "ignored_answers": ignored}


# ---------------------------------------------------------------- 必留原话（KI-03）
def parse_must_lines(raw) -> list[str]:
    """剪辑偏好里的原话 → 一条条原话。按换行 /「；」分，句内逗号保留（D5）。"""
    if isinstance(raw, list):
        items = [x for x in raw if isinstance(x, str)]
    elif isinstance(raw, str):
        items = _QUOTE_SPLIT.split(raw)
    else:
        return []
    return [x.strip() for x in items if x.strip()]


def _bare(text: str) -> str:
    return _PUNCT.sub("", text or "")


def _span(seg: dict, a: int, b: int) -> tuple[float, float]:
    """原话在去标点原文里的字符区间 [a, b) → 时间区间：有分句时间码取覆盖到的分句，否则按字数比例。"""
    s0, s1 = float(seg["start"]), float(seg["end"])
    lines = [x for x in seg.get("lines") or [] if isinstance(x, dict)]
    try:
        bare = [(_bare(str(x.get("text") or "")), float(x["start"]), float(x["end"])) for x in lines]
    except (KeyError, TypeError, ValueError):
        bare = []
    if bare and "".join(t for t, _, _ in bare) == _bare(seg.get("text") or ""):
        pos, hit = 0, []
        for text, ls, le in bare:
            if pos < b and pos + len(text) > a:
                hit.append((ls, le))
            pos += len(text)
        if hit:
            return round(min(x for x, _ in hit), 2), round(max(y for _, y in hit), 2)
    n = len(_bare(seg.get("text") or "")) or 1
    return round(s0 + (s1 - s0) * a / n, 2), round(s0 + (s1 - s0) * b / n, 2)


def _first_hit(needle: str, quote: str, segments: list[dict]) -> dict | None:
    for seg in segments:
        a = _bare(seg.get("text") or "").find(needle)
        if a >= 0:
            start, end = _span(seg, a, a + len(needle))
            return {"id": seg["id"], "line": quote, "start": start, "end": end}
    return None


def resolve_must_lines(quotes: list[str], segments: list[dict]) -> tuple[list[dict], list[str]]:
    """原话 → 强制进片的命中 [{id, line, start, end}]（每条原话 / 碎片只取时间上最早的一段）+ 警告。

    start/end 是原话在句子里的时间范围（审查 HIGH：强制镜头必须覆盖它，而不是只从句首截）。
    先整句（去标点）匹配；整句找不到才按逗号拆成碎片，碎片少于 MUST_LINE_MIN_CHARS 字的忽略；
    部分碎片找不到也要说出来。
    """
    ordered = sorted(segments, key=lambda s: float(s.get("start") or 0))
    hits: list[dict] = []
    notes: list[str] = []
    for quote in quotes:
        if len(_bare(quote)) < MUST_LINE_MIN_WHOLE:
            notes.append(MUST_LINE_WHOLE_SHORT.format(line=quote, n=MUST_LINE_MIN_WHOLE))
            continue
        hit = _first_hit(_bare(quote), quote, ordered)
        if hit:
            hits.append(hit)
            continue
        fragments = [f.strip() for f in _FRAGMENT_SPLIT.split(quote) if f.strip()]
        missed: list[str] = []
        found = False
        for frag in fragments if len(fragments) > 1 else []:
            if len(_bare(frag)) < MUST_LINE_MIN_CHARS:
                notes.append(MUST_LINE_FRAGMENT_SHORT.format(line=frag, n=MUST_LINE_MIN_CHARS))
                continue
            frag_hit = _first_hit(_bare(frag), frag, ordered)
            if frag_hit:
                hits.append(frag_hit)
                found = True
            else:
                missed.append(frag)
        if not found:
            notes.append(MUST_LINE_NOT_FOUND.format(line=quote[:MUST_LINE_SHOWN_CHARS]))
        else:
            notes += [MUST_LINE_NOT_FOUND.format(line=f[:MUST_LINE_SHOWN_CHARS]) for f in missed]
    return hits, notes


# ---------------------------------------------------------------- 节奏 / 主角（KI-04）
def max_shot_for(rules: dict | None) -> float:
    """pacing → 单镜上限（必留段不受此限，GL-08）。"""
    pacing = (rules or {}).get("pacing")
    return PACING_MAX_SHOT.get(pacing if pacing in PACINGS else DEFAULT_PACING)


def focus_speakers(segments: list[dict], focus) -> tuple[set[str], list[str]]:
    """focus → 要加分的说话人集合 + 警告。只能映射到「说话总时长最多的人」（D2）。"""
    if not focus or focus in FOCUS_NONE:
        return set(), []
    warn = [FOCUS_UNMAPPED_WARNING.format(focus=focus)]
    if focus not in FOCUS_MAIN:
        return set(), warn
    talk: dict[str, float] = {}
    for s in segments:
        spk = str(s.get("speaker") or "")
        if spk:
            talk[spk] = talk.get(spk, 0.0) + float(s["end"]) - float(s["start"])
    if not talk:
        return set(), warn
    return {max(talk, key=lambda k: (talk[k], k))}, []
