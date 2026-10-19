# -*- coding: utf-8 -*-
"""项目配置（project.json）的 schema 版本与迁移。

规则：
  * 只升不降：读到的版本高于当前，直接报错，避免"旧程序写坏新数据"；
  * 迁移是纯函数：输入旧 dict，输出新 dict + 变更说明，不碰磁盘；
  * 写盘永远是原子替换，schema_version 自动补齐。
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any

CURRENT_SCHEMA = 2


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
    "calibration": {},
}

REQUIRED = ("name", "material")


def default_project(name: str, material: str, **overrides: Any) -> dict:
    cfg: dict[str, Any] = {"name": name, "material": str(material), **DEFAULTS}
    cfg["title"] = overrides.pop("title", name)
    cfg.update(overrides)
    return cfg


def ensure_supported(cfg: dict) -> int:
    """只校验版本号：类型不对抛 ValueError，比当前程序新抛 SchemaTooNew。"""
    ver = cfg.get("schema_version", 0)
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise ValueError(f"schema_version 必须是整数，收到 {ver!r}")
    if ver > CURRENT_SCHEMA:
        raise SchemaTooNew(
            f"项目 schema 版本 {ver} 高于当前支持 {CURRENT_SCHEMA}，请升级程序")
    return ver


def migrate(cfg: dict) -> tuple[dict, list[str]]:
    """把任意旧版配置提升到当前版本，返回 (新配置, 变更列表)。"""
    out = dict(cfg)
    changes: list[str] = []
    ver = ensure_supported(out)

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

    if out.get("schema_version", 1) < 2:
        out.setdefault("calibration", {})
        out["schema_version"] = 2
        changes.append("v1→v2")

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


PROJECT_NAME_MAX = 100        # 字符数上限
PROJECT_NAME_MAX_BYTES = 255  # UTF-8 字节上限（macOS 文件名上限）
PROJECT_NAME_ERROR = (
    f"项目名不能以 - 或 . 开头，首尾不能有空格，不能含斜杠或控制字符，"
    f"最长 {PROJECT_NAME_MAX} 字（{PROJECT_NAME_MAX_BYTES} 字节）")
TITLE_ERROR = (
    f"片名不能为空，不能含斜杠或控制字符，"
    f"最长 {PROJECT_NAME_MAX} 字（{PROJECT_NAME_MAX_BYTES} 字节）")
_VERSION_RE = re.compile(r"v[0-9]{1,4}")  # 只认 ASCII 数字，\d 会放过 v٣
_SHOT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


def write_json(path: Path, obj: Any) -> None:
    """原子写：每次用唯一临时文件，并发写同一路径不会互相踩。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _is_safe_filename_part(text: str) -> bool:
    """不含路径分隔符和控制字符，字符数和 UTF-8 字节数都在上限内。"""
    return ("/" not in text and "\\" not in text
            and not any(ord(c) < 32 or ord(c) == 127 for c in text)
            and len(text) <= PROJECT_NAME_MAX
            and len(text.encode("utf-8")) <= PROJECT_NAME_MAX_BYTES)


def check_project_name(name: Any) -> str:
    """项目名白名单：允许中文和中间的空格，拒绝选项样式、隐藏名、首尾空白、路径分隔符和控制字符。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("项目名不能为空")
    if (name.startswith(("-", ".")) or name != name.strip()
            or not _is_safe_filename_part(name)):
        raise ValueError(PROJECT_NAME_ERROR)
    return name


def check_title(title: Any) -> str:
    """片名会成为剪映草稿目录名的一部分：渲染前就要拒绝，免得出片后才失败。"""
    if not isinstance(title, str) or not title.strip() or not _is_safe_filename_part(title):
        raise ValueError(TITLE_ERROR)
    return title


def check_version(version: Any) -> str:
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ValueError(f"版本号格式应为 v+数字（如 v3），收到 {version!r}")
    return version


TARGET_MIN, TARGET_MAX = 10, 3600  # 秒；成片时长由剪辑师决定，这里只挡明显的误输入
TARGET_ERROR = f"目标时长应为 {TARGET_MIN}–{TARGET_MAX} 秒之间的数字"


def check_target_duration(value: Any) -> int:
    """剪辑师填写的目标时长（秒）→ 整数秒。bool 是 int 子类，必须先排除。"""
    bad = ValueError(f"{TARGET_ERROR}，收到 {value!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise bad
    try:
        sec = float(value.strip() if isinstance(value, str) else value)
    except ValueError as exc:
        raise bad from exc
    if not math.isfinite(sec) or not TARGET_MIN <= round(sec) <= TARGET_MAX:
        raise bad
    return int(round(sec))


def check_shot_ids(shots: Any) -> None:
    """镜头 id 会成为切片文件名：必须是安全字符且互不重复。"""
    if not isinstance(shots, list):
        raise ValueError("shots 必须是列表")
    seen: set[str] = set()
    for s in shots:
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not _SHOT_ID_RE.fullmatch(sid):
            raise ValueError(f"镜头 id 只能用字母、数字、_、-（≤32 位），收到 {sid!r}")
        if sid in seen:
            raise ValueError(f"镜头 id 重复：{sid}")
        seen.add(sid)


def _shot_time(shot: dict, key: str) -> float:
    raw = shot.get(key)
    try:
        if isinstance(raw, bool):
            raise TypeError
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"镜头 {shot['id']} 的 {key} 必须是数字，收到 {raw!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"镜头 {shot['id']} 的 {key} 必须是非负有限数，收到 {raw!r}")
    return round(value, 3)


def _shot_text(shot: dict, key: str) -> str:
    raw = shot.get(key)
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"镜头 {shot['id']} 的 {key} 必须是文字，收到 {raw!r}")
    return raw


def clean_shots(shots: Any) -> list[dict]:
    """校验并规整分镜表，返回新列表（不改输入）；任何一镜不合法都整体拒绝。"""
    check_shot_ids(shots)
    out = []
    for s in shots:
        t_in, t_out = _shot_time(s, "in"), _shot_time(s, "out")
        if t_out <= t_in:
            raise ValueError(f"镜头 {s['id']} 的出点必须晚于入点（{t_in} → {t_out}）")
        out.append({"id": s["id"], "in": t_in, "out": t_out,
                    "sub": _shot_text(s, "sub"), "note": _shot_text(s, "note")})
    return out


def save(path: Path, cfg: dict) -> list[str]:
    """原子写入；返回迁移变更列表（通常为空）。"""
    cfg, changes = migrate(cfg)
    write_json(path, cfg)
    return changes
