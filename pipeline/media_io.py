# -*- coding: utf-8 -*-
"""媒体产物的「临时文件 → 原子改名 → 完成标记」（GL-15）。

规则：ffmpeg 永远写到同目录、同扩展名的临时文件，成功后 os.replace 到最终路径，
再写 `<文件名>.done`；判断"已完成"只认标记且大小一致，不认 exists()。
编码参数由调用方给（GL-04 会把 libx264 换成 h264_videotoolbox），本模块不关心。
"""
from __future__ import annotations

import contextlib
import glob
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Iterator

PARTIAL_TAG = ".partial-"
DONE_SUFFIX = ".done"
STDERR_TAIL = 800       # 失败时带回的 ffmpeg stderr 末尾字符数
FFMPEG_BASE = ["ffmpeg", "-y", "-loglevel", "error"]


class MediaError(RuntimeError):
    """ffmpeg 产物生成失败（临时文件已清理）。"""


def done_marker(dst: Path) -> Path:
    dst = Path(dst)
    return dst.with_name(dst.name + DONE_SUFFIX)


def is_complete(dst: Path) -> bool:
    """产物存在、有完成标记且大小与标记一致才算完成；旧版本留下的无标记文件不算。"""
    dst = Path(dst)
    marker = done_marker(dst)
    if not dst.is_file() or not marker.is_file():
        return False
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(meta, dict) and meta.get("size") == dst.stat().st_size


def _partial_path(dst: Path) -> Path:
    # 保留原扩展名：ffmpeg 按输出扩展名推断封装格式
    return dst.with_name(f".{dst.stem}{PARTIAL_TAG}{uuid.uuid4().hex[:8]}{dst.suffix}")


def _clear_stale_partials(dst: Path) -> None:
    """清掉上次被强杀留下的临时文件（文件名可能含 glob 元字符，必须转义）。"""
    pattern = f".{glob.escape(dst.stem)}{PARTIAL_TAG}*{glob.escape(dst.suffix)}"
    for p in dst.parent.glob(pattern):
        p.unlink(missing_ok=True)


def _write_marker(dst: Path) -> None:
    marker = done_marker(dst)
    tmp = marker.with_name(f".{marker.name}.{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(json.dumps({"size": dst.stat().st_size}), encoding="utf-8")
        os.replace(tmp, marker)
    finally:
        tmp.unlink(missing_ok=True)


@contextlib.contextmanager
def atomic_output(dst: Path) -> Iterator[Path]:
    """yield 一个临时路径；块正常结束才改名到 dst 并写完成标记，任何异常（含中断）都不留半成品。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    done_marker(dst).unlink(missing_ok=True)  # 决定重做就先作废旧结果
    _clear_stale_partials(dst)
    tmp = _partial_path(dst)
    try:
        yield tmp
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise MediaError(f"没有产出有效文件：{dst.name}")
        os.replace(tmp, dst)
        _write_marker(dst)
    finally:
        tmp.unlink(missing_ok=True)


def run_ffmpeg(args: list[str], *, runner=subprocess.run) -> None:
    """ffmpeg <args>；非零退出抛 MediaError 并带上 stderr 末尾。"""
    try:
        r = runner([*FFMPEG_BASE, *args], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError as exc:  # 没装 ffmpeg / 不可执行
        raise MediaError(f"无法运行 ffmpeg：{exc}") from exc
    if r.returncode != 0:
        tail = (r.stderr or "").strip()[-STDERR_TAIL:]
        raise MediaError(f"ffmpeg 失败（退出码 {r.returncode}）：{tail}")


def ffmpeg_to(dst: Path, args: list[str], *, runner=subprocess.run) -> Path:
    """ffmpeg <args> <临时文件> → 原子落到 dst。args 不含 `ffmpeg -y -loglevel` 与输出路径。"""
    with atomic_output(dst) as tmp:
        run_ffmpeg([*args, str(tmp)], runner=runner)
    return Path(dst)


FFPROBE_DURATION = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "csv=p=0"]


def _probe_duration(path: Path, runner) -> float:
    try:
        r = runner([*FFPROBE_DURATION, str(path)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError:
        return 0.0
    if r.returncode != 0:
        return 0.0
    try:
        return float((r.stdout or "").strip())
    except ValueError:
        return 0.0


def complete_or_adopt(dst: Path, *, runner=subprocess.run) -> bool:
    """已完成，或是旧版本（无标记）留下且 ffprobe 读得出正时长的产物 → 补写标记并认领。

    只认领"完全没有标记"的旧文件；标记存在但大小不符说明被改动过，不认领。
    """
    dst = Path(dst)
    if is_complete(dst):
        return True
    if done_marker(dst).exists() or not dst.is_file() or dst.stat().st_size == 0:
        return False
    if _probe_duration(dst, runner) <= 0:
        return False
    _write_marker(dst)
    return True
