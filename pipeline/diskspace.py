# -*- coding: utf-8 -*-
"""磁盘空间预检（KI-33 / D5）：按码率估算这一步要写多少，再加 1 GB 余量；不够就在开始前说明。"""
from __future__ import annotations

import shutil
from pathlib import Path

from pipeline import encode

MARGIN_BYTES = 1 * 1024 ** 3
WAV_BYTES_PER_S = 16000 * 2           # 16 kHz 单声道 s16
PROXY_AUDIO_BPS = 64_000              # 与 aicut.cmd_junk 的 -b:a 64k 一致
CLIP_AUDIO_BPS = 192_000              # 与 aicut.ensure_clips 的 -b:a 192k 一致
PREVIEW_AUDIO_BPS = 192_000
GB = 1024 ** 3
DISK_LOW = ("磁盘空间不够：这一步大约需要 {need:.1f} GB，{path} 所在磁盘只剩 {free:.1f} GB。"
            "清理磁盘（或在剪辑台点「清理缓存」）后再试")


def _bits(rate: str) -> float:
    """'1500k' / '12M' → 每秒比特数。"""
    unit = {"k": 1e3, "m": 1e6}.get(rate[-1].lower(), 1.0)
    return float(rate[:-1] if unit != 1.0 else rate) * unit


def _bytes_per_s(video: str, audio_bps: int) -> float:
    return (_bits(video) + audio_bps) / 8


def _with_margin(nbytes: float, anything: bool) -> int:
    """要写东西才加余量；什么都不写 → 0（不查磁盘，审查修复 M5）。"""
    return int(nbytes) + MARGIN_BYTES if anything else 0


def need_for_prepare(media_s: float, *, wav: bool = True, proxy: bool = True) -> int:
    """处理素材：还没完成的抽音轨（wav）和 / 或 540p 分析代理。"""
    per_s = (WAV_BYTES_PER_S if wav else 0) + \
        (_bytes_per_s(encode.PROXY_BITRATE, PROXY_AUDIO_BPS) if proxy else 0)
    return _with_margin(max(0.0, media_s or 0.0) * per_s, wav or proxy)


def need_for_build(cut_s: float, preview_s: float) -> int:
    """生成成片：要（重）切的镜头 + 要渲染的预览片（剪映草稿只引用切片，不另占空间）。"""
    cut_s, preview_s = max(0.0, cut_s or 0.0), max(0.0, preview_s or 0.0)
    nbytes = (cut_s * _bytes_per_s(encode.CLIP_BITRATE, CLIP_AUDIO_BPS)
              + preview_s * _bytes_per_s(encode.PREVIEW_BITRATE, PREVIEW_AUDIO_BPS))
    return _with_margin(nbytes, cut_s > 0 or preview_s > 0)


def _existing(path: Path) -> Path:
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def shortfall(path: Path, need: int, *, usage=shutil.disk_usage) -> str | None:
    """空间够 / 不需要写 → None；不够 → 给剪辑师看的说明。查不到（网络盘等）不阻断。"""
    if need <= 0:
        return None
    where = _existing(path)
    try:
        free = usage(where).free
    except OSError:
        return None
    if free >= need:
        return None
    return DISK_LOW.format(need=need / GB, free=free / GB, path=where)
