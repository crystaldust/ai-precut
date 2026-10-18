# -*- coding: utf-8 -*-
"""项目配置（project.json）的 schema 版本与迁移。

规则：
  * 只升不降：读到的版本高于当前，直接报错，避免"旧程序写坏新数据"；
  * 迁移是纯函数：输入旧 dict，输出新 dict + 变更说明，不碰磁盘；
  * 写盘永远是原子替换，schema_version 自动补齐。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CURRENT_SCHEMA = 1


class SchemaTooNew(Exception):
    """项目由更新版本的程序创建。"""


# 字段默认值（v1）
DEFAULTS: dict[str, Any] = {
    "schema_version": CURRENT_SCHEMA,
    "title": "",
    "preset": "纪实3min",
    "platform": "douyin",
    "target_duration": 175,
    "created": "",
    "brief": {},
}

REQUIRED = ("name", "material")


def default_project(name: str, material: str, **overrides: Any) -> dict:
    cfg: dict[str, Any] = {"name": name, "material": str(material), **DEFAULTS}
    cfg["title"] = overrides.pop("title", name)
    cfg.update(overrides)
    return cfg


def migrate(cfg: dict) -> tuple[dict, list[str]]:
    """把任意旧版配置提升到当前版本，返回 (新配置, 变更列表)。"""
    out = dict(cfg)
    changes: list[str] = []
    ver = out.get("schema_version", 0)
    if not isinstance(ver, int):
        raise ValueError(f"schema_version 必须是整数，收到 {ver!r}")
    if ver > CURRENT_SCHEMA:
        raise SchemaTooNew(
            f"项目 schema 版本 {ver} 高于当前支持 {CURRENT_SCHEMA}，请升级程序")

    if ver < 1:
        # v0：无版本号的历史项目
        out.setdefault("title", out.get("name", ""))
        out.setdefault("preset", "纪实3min")
        out.setdefault("platform", "douyin")
        out.setdefault("target_duration", 175)
        out.setdefault("brief", {})
        out.pop("brief_v0", None)
        out["schema_version"] = 1
        changes.append("v0→v1")

    for key, value in DEFAULTS.items():
        if key not in out:
            out[key] = value
            changes.append(f"补齐 {key}")

    for key in REQUIRED:
        if not out.get(key):
            raise ValueError(f"项目配置缺少必填字段：{key}")

    return out, changes


def load(path: Path) -> dict:
    """读取并迁移，不写回（写回由调用方决定）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("project.json 顶层必须是对象")
    cfg, _ = migrate(data)
    return cfg


def save(path: Path, cfg: dict) -> list[str]:
    """原子写入；返回迁移变更列表（通常为空）。"""
    cfg, changes = migrate(cfg)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return changes
