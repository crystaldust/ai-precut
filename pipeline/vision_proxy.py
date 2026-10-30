# -*- coding: utf-8 -*-
"""画面理解的画面代理：从浏览小样切出 5 分钟一段、去掉音轨的低清画面，只给云端模型看。

切点只按时长等分（模型自己找画面变化）；最后一段太短就并进前一段，免得浪费一次提交。
每段 5 fps、300 kbps：接口按 fps 再抽帧，5 fps 够 2–3 fps 档用，文件约 2 MB / 分钟。
写盘走 media_io.ffmpeg_to（临时文件 → 原子改名 → .done 绑定浏览小样指纹）。
要上传，所以去掉全部元数据与章节：手机素材的拍摄时间、设备型号、GPS 会从原始视频一路带进浏览小样。
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from pipeline import encode, media_io, vision

CHUNK_FPS = 5
CHUNK_NAME = "chunk_{index:03d}.mp4"
STRIP_METADATA = ("-map_metadata", "-1", "-map_chapters", "-1")


def plan_chunks(duration_s: float, chunk_s: float = vision.CHUNK_S,
                min_tail_s: float = vision.MIN_TAIL_S) -> list[dict]:
    """[{index, start, end}]，首尾相接覆盖 0–duration；时长不是正的有限数抛 ValueError。"""
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError(f"素材时长不对：{duration_s}")
    bounds = [float(t) for t in range(0, math.ceil(duration_s), int(chunk_s))]
    if len(bounds) > 1 and duration_s - bounds[-1] < min_tail_s:
        bounds = bounds[:-1]
    ends = [*bounds[1:], float(duration_s)]
    return [{"index": i, "start": start, "end": end}
            for i, (start, end) in enumerate(zip(bounds, ends))]


def chunk_path(folder: Path, index: int) -> Path:
    return Path(folder) / CHUNK_NAME.format(index=index)


def encode_chunk(proxy: Path, chunk: dict, dst: Path, *, runner=subprocess.run) -> Path:
    """-ss 放在 -i 前：快速定位，重编码从准确时间开始。失败抛 MediaError，不留半截文件。"""
    length = chunk["end"] - chunk["start"]
    args = ["-ss", f"{chunk['start']:.3f}", "-i", str(proxy), "-t", f"{length:.3f}",
            "-vf", f"fps={CHUNK_FPS}", "-an", *STRIP_METADATA, *encode.h264_args("vision")]
    return media_io.ffmpeg_to(dst, args, runner=runner, timeout=media_io.timeout_for(length),
                              source=proxy)
