# -*- coding: utf-8 -*-
"""ASR 断点续查状态：work/asr_task.json（GL-16）。

绑定 (schema 版本, backend, 音频 sha256 + 大小)，任一不符就作废并删除，避免：
  * 换了音频还去查旧任务；
  * 换了转写实现（GL-01：mediakit-cli → HTTP）后拿旧 task_id 去查新服务。
只有「可重试」的失败（超时 / 网络）保留状态；终态失败由调用方 clear()，下次重新提交。
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from pipeline import schema

FILENAME = "asr_task.json"
SCHEMA_VERSION = 1
MAX_AGE_S = 86400 * 3  # 云端任务结果保留期
_CHUNK = 1 << 20


def fingerprint(audio: Path) -> dict:
    """音频内容指纹。不用 mtime：原子重写（GL-15）会改 mtime 但内容不变。"""
    h = hashlib.sha256()
    with open(audio, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "size": Path(audio).stat().st_size}


def _path(workdir: Path) -> Path:
    return Path(workdir) / FILENAME


def _valid(data: object, audio: Path, backend: str, now: float) -> bool:
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return False
    if data.get("backend") != backend:
        return False
    task_id, at = data.get("task_id"), data.get("at")
    if not isinstance(task_id, str) or not task_id:
        return False
    if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
        return False
    if not 0 <= now - at < MAX_AGE_S:
        return False
    try:
        return data.get("audio") == fingerprint(audio)
    except OSError:
        return False


def load(workdir: Path, audio: Path, backend: str, *, now=time.time) -> str | None:
    """返回可续查的 task_id；不匹配 / 过期 / 损坏时删除状态文件并返回 None。"""
    path = _path(workdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        clear(workdir)
        return None
    if not _valid(data, audio, backend, now()):
        clear(workdir)
        return None
    return data["task_id"]


def save(workdir: Path, audio: Path, backend: str, task_id: str, *, now=time.time) -> None:
    schema.write_json(_path(workdir), {
        "schema": SCHEMA_VERSION, "backend": backend, "task_id": task_id,
        "audio": fingerprint(audio), "at": now()})


def clear(workdir: Path) -> None:
    _path(workdir).unlink(missing_ok=True)
