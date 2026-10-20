# -*- coding: utf-8 -*-
"""KI-93「不可用」片段的排除：区间、分镜表重叠剔除、旧版本命中检查。

「不可用」= 剪辑师标记的隐私 / 口误等不能出现在成片里的片段：
选段在入口处整段剔除（pipeline/select.py）；这里负责选段之外的两道防线——
手动 / 旧分镜表出片前再剔一次，以及已出过的旧版本导出前的检查。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import applog, review, schema, select

UNUSABLE_OVERLAP_S = 0.1   # D12：与不可用片段重叠超过这么多秒的镜头整镜剔除（隐私优先）
DROPPED_WARNING = "已自动剔除 {n} 个含「不可用」片段的镜头：{ids}"
ALL_DROPPED = "分镜表里的镜头都含「不可用」片段，剔除后没有可出的镜头：回到 ③ 看素材检查标记，或在 ⑤ 看结果重新选段"
EXPORT_BLOCKED = "这一版含 {n} 段已标为不可用的片段，不能再导出；请生成新版本"
DROPPED_SHOWN = 5  # 提示里最多列几个镜头 id

SNAPSHOT_FILE = "shots_snapshot.json"  # 与 pipeline.clips.SNAPSHOT_FILE 一致（出片时存的分镜表）
EXPORT_NO_SNAPSHOT = "无法确认这一版是否含已标为不可用的片段（这一版没有留存分镜表），请生成新版本"
EXPORT_BAD_SNAPSHOT = "无法确认这一版是否含已标为不可用的片段（这一版留存的分镜表已损坏），请生成新版本"
MUST_KEEP_LOST = ("剔除含「不可用」片段的镜头 {shot} 后，剪辑列表里的片段 {must}（{when}）会丢失：它和不可用片段 {bad} "
                  "在同一个镜头里。请先在分镜表里把这个镜头拆成两镜，只留下剪辑列表里的部分")
BAD_DATA = "分析结果或人工裁决读不出来，无法核对「不可用」片段：{detail}"
LOG = applog.get("gui")

Span = tuple[float, float, str]


class ExclusionError(RuntimeError):
    """不可用排除这一步不能放行（消息是人话，调用方直接给剪辑师看）。"""


def spans(workdir: Path) -> list[Span]:
    """当前标为不可用的片段 → [(起, 止, 句子 id)]。没有分析结果（纯手工流程）→ []。

    overrides.json 损坏抛 review.OverridesCorrupt；segments_scored.json 损坏抛 schema.CorruptJSON。
    """
    scored_path = Path(workdir) / "segments_scored.json"
    scored = schema.read_json(scored_path, default=None)
    if scored is None:
        return []
    segments = review.apply(schema.require_key(scored, "segments", scored_path), review.load(workdir))
    return [(float(s["start"]), float(s["end"]), s["id"]) for s in segments if s.get("unusable")]


def _is_hit(shot: dict, span: Span) -> bool:
    """镜头与不可用片段重叠超过 min(阈值, 片段时长的一半)；零长度片段落在镜头内就算。"""
    start, end, _ = span
    lo, hi = max(float(shot["in"]), start), min(float(shot["out"]), end)
    if end - start <= 0:
        return float(shot["in"]) <= start <= float(shot["out"])
    return hi - lo > min(UNUSABLE_OVERLAP_S, (end - start) * 0.5)


def hits(shots: list[dict], marked: list[Span]) -> list[dict]:
    """与任一不可用片段重叠的镜头（阈值见 _is_hit）。"""
    return [sh for sh in shots if any(_is_hit(sh, sp) for sp in marked)]


def drop_overlapping(shots: list[dict], marked: list[Span]) -> tuple[list[dict], list[str]]:
    """→ (保留的镜头, 被剔除的镜头 id)；不改入参。"""
    bad = {id(sh) for sh in hits(shots, marked)}
    kept = [sh for sh in shots if id(sh) not in bad]
    return kept, [sh["id"] for sh in shots if id(sh) in bad]


def _mmss(sec: float) -> str:
    return f"{int(sec) // 60:02d}:{int(sec) % 60:02d}"


def filter_shots(workdir: Path, shots: list[dict]) -> tuple[list[dict], list[str]]:
    """出片前：剔除含不可用片段的镜头。→ (保留的镜头, 被剔除的镜头 id)。

    剔除会让某个必留片段不再被覆盖（它和不可用片段在同一镜里）→ 抛 ExclusionError，点名三者。
    读不出分析结果 / 裁决（含结构不对）→ ExclusionError，不抛 traceback。
    """
    try:
        marked = spans(workdir)
        kept, dropped = drop_overlapping(shots, marked)
        if not dropped:
            return kept, dropped
        lost = select.missing_must_keep(Path(workdir), kept)
    except (review.OverridesCorrupt, schema.CorruptJSON, KeyError, TypeError, ValueError) as exc:
        raise ExclusionError(BAD_DATA.format(detail=exc)) from exc
    if lost:
        seg = lost[0]
        gone = [sh for sh in shots if sh["id"] in dropped]
        shot = next((sh for sh in gone if min(float(sh["out"]), float(seg["end"]))
                     > max(float(sh["in"]), float(seg["start"]))), gone[0])
        bad = next((sp[2] for sp in marked if _is_hit(shot, sp)), "")
        raise ExclusionError(MUST_KEEP_LOST.format(shot=shot["id"], must=seg["id"],
                                                   when=_mmss(float(seg["start"])), bad=bad))
    return kept, dropped


def timeline_hits(workdir: Path, vdir: Path, marked: list[Span] | None = None) -> int:
    """某一版（输出目录 vdir）出片时的分镜表里，有几镜含不可用片段。

    时间线里的 in/out 是切片内时间，不是素材时间：要看出片时存下的分镜表快照。
    项目里有不可用标记、而这一版的快照缺失 / 损坏 → 无法确认，失败即关闭（ExclusionError）。
    没有任何不可用标记 → 不需要快照，返回 0。marked：调用方已读好的 spans(workdir)（列版本卡片时只读一遍）。
    """
    if marked is None:
        try:
            marked = spans(workdir)
        except (review.OverridesCorrupt, schema.CorruptJSON, KeyError, TypeError, ValueError) as exc:
            raise ExclusionError(BAD_DATA.format(detail=exc)) from exc
    if not marked:
        return 0
    path = Path(vdir) / SNAPSHOT_FILE
    if not path.exists():
        LOG.warning("导出拦截：%s 没有留存分镜表，无法核对不可用片段", Path(vdir).name)
        raise ExclusionError(EXPORT_NO_SNAPSHOT)
    try:
        snapshot = schema.read_shots(path)
    except (schema.CorruptJSON, OSError) as exc:
        LOG.warning("导出拦截：%s 的留存分镜表损坏，无法核对不可用片段", Path(vdir).name)
        raise ExclusionError(EXPORT_BAD_SNAPSHOT) from exc
    return len(hits(snapshot, marked))
