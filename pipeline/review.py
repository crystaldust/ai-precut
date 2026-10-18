# -*- coding: utf-8 -*-
"""人工裁决的持久化：剪辑师对档位/必留的修改不能因为重跑分析而丢失。

存 `work/overrides.json`：
    {"S012": {"level": 3, "must_keep": true, "note": ""}, ...}

读取时把 overrides 合并到分析结果上；写入用原子替换。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LEVELS = {1: "废片", 2: "待定", 3: "可用"}


def _path(workdir: Path) -> Path:
    return Path(workdir) / "overrides.json"


def load(workdir: Path) -> dict:
    path = _path(workdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(workdir: Path, data: dict) -> None:
    path = _path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def set_level(workdir: Path, segment_id: str, level: int) -> dict:
    if level not in LEVELS:
        raise ValueError(f"非法档位：{level}")
    data = load(workdir)
    item = data.setdefault(segment_id, {})
    item["level"] = level
    item["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(workdir, data)
    return data


def set_must(workdir: Path, segment_id: str, flag: bool) -> dict:
    data = load(workdir)
    item = data.setdefault(segment_id, {})
    item["must_keep"] = bool(flag)
    item["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(workdir, data)
    return data


def clear(workdir: Path, segment_id: str | None = None) -> dict:
    if segment_id is None:
        _save(workdir, {})
        return {}
    data = load(workdir)
    data.pop(segment_id, None)
    _save(workdir, data)
    return data


def apply(segments: list[dict], overrides: dict) -> list[dict]:
    """把人工修改合并进分析结果，保留原始判定在 base_level 里。"""
    out = []
    for seg in segments:
        item = dict(seg)
        item.setdefault("base_level", seg["level"])
        ov = overrides.get(seg["id"], {})
        if "level" in ov:
            item["level"] = ov["level"]
            item["level_reason"] = f'人工改为{LEVELS[ov["level"]]}'
            item["override"] = True
        else:
            item["override"] = False
        item["must_keep"] = bool(ov.get("must_keep", False))
        out.append(item)
    return out
