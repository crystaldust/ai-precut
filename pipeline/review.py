# -*- coding: utf-8 -*-
"""人工裁决的持久化：剪辑师对档位/必留的修改不能因为重跑分析而丢失。

存 `work/overrides.json`：
    {"S012": {"level": 3, "must_keep": true, "note": ""}, ...}

读取时把 overrides 合并到分析结果上；写入用原子替换。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from pipeline import schema

LEVELS = {1: "废片", 2: "待定", 3: "可用"}

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_level(workdir: Path, segment_id: str, level: int) -> dict:
    if level not in LEVELS:
        raise ValueError(f"非法档位：{level}")
    with _LOCK:
        data = load(workdir)
        item = data.setdefault(segment_id, {})
        item["level"] = level
        item["at"] = _now()
        _save(workdir, data)
        return data


def set_must(workdir: Path, segment_id: str, flag: bool) -> dict:
    with _LOCK:
        data = load(workdir)
        item = data.setdefault(segment_id, {})
        item["must_keep"] = bool(flag)
        item["at"] = _now()
        _save(workdir, data)
        return data


def clear(workdir: Path, segment_id: str | None = None) -> dict:
    with _LOCK:
        if segment_id is None:  # 显式重置：不读旧文件
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
