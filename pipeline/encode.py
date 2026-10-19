# -*- coding: utf-8 -*-
"""H.264 编码参数的唯一来源：一律 VideoToolbox（随包 ffmpeg 是 LGPL 构建，不含 x264 编码器，GL-04）。

只给「编码参数」，写盘仍走 media_io.ffmpeg_to / atomic_output（临时文件 → 原子改名 → .done）。
VideoToolbox 不支持 -crf/-preset，码率显式给出；-pix_fmt yuv420p 兜住 10-bit/HDR 素材；
-allow_sw 1 让硬件会话不可用（被占满 / 虚拟机）时退回软件编码，而不是整条流水线失败。
"""
from __future__ import annotations

import subprocess

ENCODER = "h264_videotoolbox"
PROFILE = "high"
PIX_FMT = "yuv420p"
PROXY_BITRATE = "1500k"   # 540p 分析代理（原 x264 ultrafast crf30）
CLIP_BITRATE = "12M"      # 1080×1920 镜头切片，进剪映（原 veryfast crf18）
PREVIEW_BITRATE = "8M"    # 审片预览（原 veryfast crf20）
BITRATES = {"proxy": PROXY_BITRATE, "clip": CLIP_BITRATE, "preview": PREVIEW_BITRATE}


def h264_args(kind: str) -> list[str]:
    """kind ∈ BITRATES；未知类型抛 KeyError。每次返回新列表，调用方可放心拼接。"""
    return ["-c:v", ENCODER, "-b:v", BITRATES[kind], "-profile:v", PROFILE,
            "-allow_sw", "1", "-pix_fmt", PIX_FMT]


# ------------------------------------------------------------------ 预检（GL-04）
# 付费步骤（转写 / LLM）之前先确认本机真能用 VideoToolbox 出片，免得钱花了最后切片失败
ENCODER_UNAVAILABLE = ("本机无法使用 VideoToolbox 硬件编码（{detail}），处理素材后也无法生成切片和预览，"
                       "已在调用云端之前停下。请确认是 Apple 芯片 Mac 并重启电脑后再试；仍不行请导出诊断包发给开发者")
PREFLIGHT_SOURCE = "color=c=black:s=320x240:r=30:d=0.1"
PREFLIGHT_TIMEOUT_S = 20
PREFLIGHT_DETAIL_MAX = 160
_PREFLIGHT: dict = {}  # 每个进程只试一次


def preflight(runner=subprocess.run) -> str | None:
    """用 0.1 秒的测试画面试编一次；可用返回 None，否则返回给用户看的中文说明。结果按进程缓存。"""
    if "result" in _PREFLIGHT:
        return _PREFLIGHT["result"]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", PREFLIGHT_SOURCE,
           *h264_args("proxy"), "-f", "null", "-"]
    try:
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=PREFLIGHT_TIMEOUT_S)
        detail = None if r.returncode == 0 else \
            ((r.stderr or "").strip().splitlines() or [f"退出码 {r.returncode}"])[-1]
    except (OSError, subprocess.SubprocessError) as exc:
        detail = f"无法运行 ffmpeg：{type(exc).__name__}"
    result = None if detail is None else \
        ENCODER_UNAVAILABLE.format(detail=detail[:PREFLIGHT_DETAIL_MAX])
    _PREFLIGHT["result"] = result
    return result
