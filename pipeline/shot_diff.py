# -*- coding: utf-8 -*-
"""镜头配对与差异（M14 E8）：「你手动改过分镜表（N 处）」与「两版对比」共用的纯函数。

AI 选段每次都从 sel01 编号，同一个 id 在两张表里可能是完全不同的内容，所以不能只按 id 比：
先按 id 且时间重叠配对，剩下的按时间重叠率（交 / 并）贪心配对，配不上的才是新增 / 删除。
所有函数都不改入参。
"""
from __future__ import annotations

PAIR_MIN_IOU = 0.5          # 时间重叠率（交 / 并）达到这么多才算同一镜（E8）
RETIME_TOLERANCE_S = 0.05   # 入出点变化不超过这个不算改（入出点保留两位小数）
DESCRIBE_SUB_CHARS = 12     # 改动清单里字幕最多显示几个字
DESCRIBE_LIMIT = 8          # 改动清单默认最多列几条
SECONDS_PER_MIN = 60

ADDED = "新增第 {n} 镜「{sub}」"
REMOVED = "删除了 {tc} 那一镜"
SUB_CHANGED = "第 {n} 镜改了字幕"
RETIMED = "第 {n} 镜改了入出点"
REORDERED = "调整了镜头顺序"


def _span(shot: dict) -> tuple[float, float]:
    return float(shot.get("in", 0)), float(shot.get("out", 0))


def _sub(shot: dict) -> str:
    return str(shot.get("sub") or "").strip()


def _overlap(a: dict, b: dict) -> tuple[float, float]:
    """(交, 并)，单位秒。"""
    a0, a1 = _span(a)
    b0, b1 = _span(b)
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    return inter, max(a1, b1) - min(a0, b0)


def _iou(a: dict, b: dict) -> float:
    inter, union = _overlap(a, b)
    return inter / union if union > 0 else 0.0


def _greedy(old: list[dict], new: list[dict], taken_old: set, taken_new: set,
            accept) -> list[tuple[int, int]]:
    """按重叠率降序挑，避免先到先得配错；accept(i, j, iou) 决定候选是否合格。"""
    cands = []
    for i, o in enumerate(old):
        for j, n in enumerate(new):
            iou = _iou(o, n)
            if iou > 0 and accept(o, n, iou):
                cands.append((-iou, i, j))
    pairs = []
    for _, i, j in sorted(cands):
        if i in taken_old or j in taken_new:
            continue
        taken_old.add(i)
        taken_new.add(j)
        pairs.append((i, j))
    return pairs


def pair(old: list[dict], new: list[dict]) -> list[tuple[int, int]]:
    """镜头配对：先 id 相同且时间重叠，再按重叠率 ≥ PAIR_MIN_IOU；返回 [(旧下标, 新下标)]。"""
    taken_old: set = set()
    taken_new: set = set()
    by_id = _greedy(old, new, taken_old, taken_new, lambda o, n, _iou_: o.get("id") == n.get("id"))
    by_time = _greedy(old, new, taken_old, taken_new, lambda o, n, iou: iou >= PAIR_MIN_IOU)
    return sorted([*by_id, *by_time])


def _retimed(o: dict, n: dict) -> bool:
    (o0, o1), (n0, n1) = _span(o), _span(n)
    return abs(o0 - n0) > RETIME_TOLERANCE_S or abs(o1 - n1) > RETIME_TOLERANCE_S


def diff(old: list[dict], new: list[dict]) -> dict:
    """{added, removed, sub_changed, retimed, reordered}；每条带 index（新增 / 改动用新表位置，删除用旧表位置）。"""
    pairs = pair(old, new)
    paired_old = {i for i, _ in pairs}
    paired_new = {j for _, j in pairs}
    sub_changed, retimed = [], []
    for i, j in pairs:
        if _sub(old[i]) != _sub(new[j]):
            sub_changed.append({"index": j, "before": _sub(old[i]), "after": _sub(new[j])})
        if _retimed(old[i], new[j]):
            retimed.append({"index": j, "before": _span(old[i]), "after": _span(new[j])})
    news = [j for _, j in pairs]  # pairs 已按旧表顺序排；新表位置不递增就是调过顺序
    return {
        "added": [{"index": j, "shot": new[j]} for j in range(len(new)) if j not in paired_new],
        "removed": [{"index": i, "shot": old[i]} for i in range(len(old)) if i not in paired_old],
        "sub_changed": sorted(sub_changed, key=lambda x: x["index"]),
        "retimed": sorted(retimed, key=lambda x: x["index"]),
        "reordered": news != sorted(news),
    }


def count(d: dict) -> int:
    """改了几处：新增 / 删除 / 改字幕 / 改入出点各算一处，顺序变了算一处。"""
    return (len(d["added"]) + len(d["removed"]) + len(d["sub_changed"]) + len(d["retimed"])
            + (1 if d["reordered"] else 0))


def _tc(sec: float) -> str:
    return f"{int(sec // SECONDS_PER_MIN):02d}:{int(sec % SECONDS_PER_MIN):02d}"


def describe(d: dict, new: list[dict], limit: int = DESCRIBE_LIMIT) -> tuple[list[str], int]:
    """改动清单的人话：(最多 limit 条, 余下几条)。new 仅为接口对称保留，镜号取自 diff 里的 index。"""
    del new
    lines = [ADDED.format(n=x["index"] + 1, sub=_sub(x["shot"])[:DESCRIBE_SUB_CHARS]) for x in d["added"]]
    lines += [REMOVED.format(tc=_tc(_span(x["shot"])[0])) for x in d["removed"]]
    lines += [SUB_CHANGED.format(n=x["index"] + 1) for x in d["sub_changed"]]
    lines += [RETIMED.format(n=x["index"] + 1) for x in d["retimed"]]
    if d["reordered"]:
        lines.append(REORDERED)
    return lines[:limit], max(0, len(lines) - limit)
