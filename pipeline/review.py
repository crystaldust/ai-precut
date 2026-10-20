# -*- coding: utf-8 -*-
"""人工裁决的持久化：剪辑师对档位/必留的修改不能因为重跑分析而丢失。

存 `work/overrides.json`：
    {"S012": {"level": 3, "must_keep": true, "unusable": false, "anchor": {"text": "<原文哈希>", "start": 12.0}}, ...}

读取时把 overrides 合并到分析结果上；写入用原子替换。
KI-12：重新分段后句子 id 会变、原文不会。写入时记锚点（原文哈希 + 起点）；读取时锚点对不上
就按原文重定位（同文取起点最近的一句），找不到就不套用、由选段报警告。没有锚点的旧裁决照旧按 id 套用。
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from pipeline import schema

LEVELS = {1: "废片", 2: "待定", 3: "可用"}
EXCLUSIVE = {"must_keep": "unusable", "unusable": "must_keep"}  # ⚑P9：剪辑列表与不可用互斥，后按的生效
BOOKKEEPING_FIELDS = {"at", "anchor"}  # 不算「人工裁决内容」的记账字段
RELOCATE_MAX_SECONDS = 30.0  # 重定位只在锚点起点前后这么多秒内找同文句子；更远的当失效（「对。」这类短句到处都有）

_LOCK = threading.Lock()  # GUI 是多线程服务，读-改-写必须串行


class OverridesCorrupt(ValueError):
    """overrides.json 读不出来：不能当空，否则下一次裁决会把人工结果全部覆盖。"""


def _path(workdir: Path) -> Path:
    return Path(workdir) / "overrides.json"


def load(workdir: Path) -> dict:
    path = _path(workdir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverridesCorrupt(f"人工裁决文件损坏，未做任何修改：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise OverridesCorrupt(f"人工裁决文件格式不对（应为对象）：{path}")
    return data


def _save(workdir: Path, data: dict) -> None:
    schema.write_json(_path(workdir), data)


def _now(*, precise: bool = False) -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds" if precise else "seconds")


def text_key(text: str) -> str:
    """锚点：去空白后的原文哈希（重新分段后句子 id 会变，原文不会）。"""
    return hashlib.sha1(re.sub(r"\s+", "", text or "").encode("utf-8")).hexdigest()[:12]


def _anchor_of(seg: dict) -> dict:
    return {"text": text_key(seg.get("text") or ""), "start": round(float(seg.get("start") or 0), 2)}


def _scored_segments(workdir: Path) -> list[dict] | None:
    """当前分析结果；没有 / 读不出来 → None（纯手工流程不记锚点，也不能让裁决接口报错）。"""
    scored = schema.read_json_lenient(Path(workdir) / "segments_scored.json", None)
    segs = scored.get("segments") if isinstance(scored, dict) else None
    if not isinstance(segs, list):
        return None
    return [s for s in segs if isinstance(s, dict) and isinstance(s.get("id"), str)]


def _rekey(data: dict, segments: list[dict]) -> tuple[dict, set[str]]:
    """把已有裁决挪到它们当前对应的句子 id 上（并刷新锚点）；对不上的保留原样（继续报失效）。

    → (新裁决表, 仍失效的键)。失效键与某个当前 id 撞名时，当前 id 上的裁决优先。
    """
    mapping, stale = _resolve_keys(segments, data)
    by_id = {s["id"]: s for s in segments}
    out = {cur: {**data[old], "anchor": _anchor_of(by_id[cur])} for cur, old in mapping.items()}
    kept = {old for old in stale if old not in out}
    return {**out, **{old: data[old] for old in kept}}, kept


def _write(workdir: Path, segment_id: str, fields: dict, exclusive: str | None = None) -> tuple[dict, str | None]:
    """锁内读改写。exclusive：本次要置 True 的互斥标记名；对方当前为 True 就在同一次写里清掉。

    → (新裁决表, 被顺带清掉的标记名或 None)。
    """
    with _LOCK:
        data = load(workdir)
        segments = _scored_segments(workdir)
        if segments:
            data, stale = _rekey(data, segments)
            if segment_id in stale:  # 同 id 的旧裁决属于别的句子（已失效），新裁决不能继承它的字段
                data = {k: v for k, v in data.items() if k != segment_id}
        prev = data.get(segment_id) if isinstance(data.get(segment_id), dict) else {}
        cleared = None
        if exclusive and prev.get(exclusive):  # ⚑P9：后按的生效，判断在锁内、_rekey 之后
            fields = {**fields, exclusive: False}
            cleared = exclusive
        item = {**prev, **fields, "at": _now()}
        if item.get("must_keep") is not True:  # 加入剪辑列表的顺序戳：只在 False→True 时记，关掉就清
            item.pop("must_at", None)
        elif not prev.get("must_keep"):
            item["must_at"] = _now(precise=True)
        anchor = next((_anchor_of(s) for s in segments or [] if s["id"] == segment_id), None)
        if anchor:
            item["anchor"] = anchor
        data = {**data, segment_id: item}
        _save(workdir, data)
        return data, cleared


def set_level(workdir: Path, segment_id: str, level: int) -> dict:
    if level not in LEVELS:
        raise ValueError(f"非法档位：{level}")
    return _write(workdir, segment_id, {"level": level})[0]


def _set_flag(workdir: Path, segment_id: str, field: str, flag: bool) -> tuple[dict, str | None]:
    return _write(workdir, segment_id, {field: bool(flag)}, EXCLUSIVE[field] if flag else None)


def set_must(workdir: Path, segment_id: str, flag: bool) -> dict:
    return _set_flag(workdir, segment_id, "must_keep", flag)[0]


def set_must_reporting(workdir: Path, segment_id: str, flag: bool) -> tuple[dict, str | None]:
    """同 set_must，另外回报被互斥清掉的标记（"unusable" / None）。"""
    return _set_flag(workdir, segment_id, "must_keep", flag)


def set_unusable(workdir: Path, segment_id: str, flag: bool) -> tuple[dict, str | None]:
    """KI-93：标 / 取消「不可用」；标记时顺带把必留清掉（回报 "must_keep"）。"""
    return _set_flag(workdir, segment_id, "unusable", flag)


def unset_level(workdir: Path, segment_id: str) -> dict:
    """只撤销档位的人工修改，保留 must_keep / unusable；条目只剩 at / anchor 就整条删。"""
    with _LOCK:
        data = load(workdir)
        segments = _scored_segments(workdir)
        mapping = _resolve_keys(segments, data)[0] if segments else {}
        key = mapping.get(segment_id, segment_id)  # KI-85：界面给的是当前 id
        item = data.get(key)
        if not isinstance(item, dict) or "level" not in item:
            return data
        rest = {k: v for k, v in item.items() if k != "level"}
        if set(rest) <= BOOKKEEPING_FIELDS:
            data = {k: v for k, v in data.items() if k != key}
        else:
            data = {**data, key: {**rest, "at": _now()}}
        _save(workdir, data)
        return data


def clear(workdir: Path, segment_id: str | None = None) -> dict:
    with _LOCK:
        if segment_id is None:  # 显式重置：不读旧文件
            _save(workdir, {})
            return {}
        data = load(workdir)
        segments = _scored_segments(workdir)
        mapping = _resolve_keys(segments, data)[0] if segments else {}
        key = mapping.get(segment_id, segment_id)  # KI-85：界面给的是当前 id，裁决可能存在旧 id 下
        data = {k: v for k, v in data.items() if k != key}
        _save(workdir, data)
        return data


def _resolve_keys(segments: list[dict], overrides: dict) -> tuple[dict[str, str], list[str]]:
    """→ ({当前段 id: 裁决的键}, 对不上任何句子的键)。

    无锚点（旧裁决）→ 按 id；有锚点 → 在原文相同、起点离锚点不超过 RELOCATE_MAX_SECONDS 的句子里
    全局按距离从近到远分配（同距离优先同 id），一句只给一条裁决；分不到 → 失效。
    """
    by_id = {s["id"]: s for s in segments}
    keys = {s["id"]: text_key(s.get("text") or "") for s in segments}
    mapping: dict[str, str] = {}
    anchored: list[str] = []
    stale: list[str] = []
    for key, ov in overrides.items():
        if not isinstance(ov, dict):
            continue
        if isinstance(ov.get("anchor"), dict):
            anchored.append(key)
        elif key in by_id:
            mapping[key] = key
        else:
            stale.append(key)
    pairs = []
    for order, key in enumerate(anchored):
        anchor = overrides[key]["anchor"]
        target = float(anchor.get("start") or 0)
        for seg in segments:
            dist = abs(float(seg.get("start") or 0) - target)
            if keys[seg["id"]] == anchor.get("text") and dist <= RELOCATE_MAX_SECONDS and seg["id"] not in mapping:
                pairs.append((dist, seg["id"] != key, order, key, seg["id"]))
    placed: set[str] = set()
    for _, _, _, key, sid in sorted(pairs):
        if key not in placed and sid not in mapping:
            mapping[sid] = key
            placed.add(key)
    return mapping, stale + [k for k in anchored if k not in placed]


def resolve(segments: list[dict], overrides: dict) -> tuple[dict[str, dict], list[str]]:
    """overrides → ({当前段 id: 裁决}, 对不上任何句子的旧 id)（KI-12）。"""
    mapping, stale = _resolve_keys(segments, overrides)
    return {cur: overrides[key] for cur, key in mapping.items()}, stale


def stale_ids(segments: list[dict], overrides: dict) -> list[str]:
    return resolve(segments, overrides)[1]


def apply(segments: list[dict], overrides: dict) -> list[dict]:
    """把人工修改合并进分析结果，保留原始判定在 base_level 里。裁决按锚点对到当前句子（KI-12）。"""
    resolved, _ = resolve(segments, overrides)
    out = []
    for seg in segments:
        item = dict(seg)
        item.setdefault("base_level", seg["level"])
        ov = resolved.get(seg["id"], {})
        if "level" in ov:
            item["level"] = ov["level"]
            item["level_reason"] = f'人工改为{LEVELS[ov["level"]]}'
            item["override"] = True
        else:
            item["override"] = False
        item["must_keep"] = bool(ov.get("must_keep", False))
        item["unusable"] = bool(ov.get("unusable", False))  # KI-93
        if item["must_keep"]:  # 剪辑列表按加入顺序排（D14）；旧裁决没有 must_at 就退回 at
            item["must_at"] = ov.get("must_at") or ov.get("at")
        out.append(item)
    return out
