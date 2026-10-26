# -*- coding: utf-8 -*-
"""H.264 编码参数的唯一来源：Mac 用 VideoToolbox，Windows 用 libopenh264 / h264_mf（随包 ffmpeg 是 LGPL 构建，不含 x264 编码器，GL-04）。

只给「编码参数」，写盘仍走 media_io.ffmpeg_to / atomic_output（临时文件 → 原子改名 → .done）。
VideoToolbox 不支持 -crf/-preset，码率显式给出；-pix_fmt yuv420p 兜住 10-bit/HDR 素材；
-allow_sw 1 让硬件会话不可用（被占满 / 虚拟机）时退回软件编码，而不是整条流水线失败。
"""
from __future__ import annotations

import subprocess
import sys
import threading

from pipeline import media_io

# 按平台的候选编码器（先到先得）。Mac 只有 VideoToolbox；Windows 优先 libopenh264（能出 High profile），
# h264_mf（Media Foundation，不认命名 profile）兜底；其它平台（Linux 开发机）沿用 Mac 的列表。
ENCODERS = {"darwin": ["h264_videotoolbox"], "win32": ["libopenh264", "h264_mf"]}
# 每个编码器自己的额外参数（插在 -b:v 之后、-pix_fmt 之前）
ENCODER_ARGS = {
    "h264_videotoolbox": ["-profile:v", "high", "-allow_sw", "1"],
    "libopenh264": ["-profile:v", "high"],
    "h264_mf": [],
}
PIX_FMT = "yuv420p"
PROXY_BITRATE = "1500k"   # 540p 分析代理（原 x264 ultrafast crf30）
CLIP_BITRATE = "12M"      # 1080×1920 镜头切片，进剪映（原 veryfast crf18）
PREVIEW_BITRATE = "8M"    # 审片预览（原 veryfast crf20）
BITRATES = {"proxy": PROXY_BITRATE, "clip": CLIP_BITRATE, "preview": PREVIEW_BITRATE}


def candidates() -> list[str]:
    """本平台的候选编码器（新列表）。"""
    return list(ENCODERS.get(sys.platform, ENCODERS["darwin"]))


def encoder() -> str:
    """本进程里经过预检的编码器。还没预检过就先预检一次（每个进程最多一次 0.1 秒的探测，成功后缓存）：
    切片 / 预览 / 代理可能跑在独立子进程里，不能拿未验证的首个候选直接编。预检失败抛 MediaError（带平台文案），
    各调用方本来就捕获 MediaError 并给用户看。"""
    with _LOCK:
        if "result" not in _PREFLIGHT and (problem := preflight()):
            raise media_io.MediaError(problem)
        return _PREFLIGHT.get("encoder") or candidates()[0]


def h264_args(kind: str, enc: str | None = None) -> list[str]:
    """kind ∈ BITRATES；未知类型抛 KeyError。每次返回新列表，调用方可放心拼接。"""
    enc = enc or encoder()
    return ["-c:v", enc, "-b:v", BITRATES[kind], *ENCODER_ARGS[enc], "-pix_fmt", PIX_FMT]


# ------------------------------------------------------------------ 预检（GL-04）
# 付费步骤（转写 / LLM）之前先确认本机真能出片，免得钱花了最后切片失败
ENCODER_UNAVAILABLE = ("本机无法使用 VideoToolbox 硬件编码（{detail}），分析后也无法生成切片和预览，"
                       "已在调用云端之前停下。请确认是 Apple 芯片 Mac 并重启电脑后再试；仍不行请导出诊断包发给开发者")
ENCODER_UNAVAILABLE_WIN = ("本机无法使用 Windows 视频编码组件（{detail}），分析后也无法生成切片和预览，"
                           "已在调用云端之前停下。请确认系统是 Windows 10/11 完整版（N 版需安装「媒体功能包」）"
                           "后重启再试；仍不行请导出诊断包发给开发者")
PREFLIGHT_SOURCE = "color=c=black:s=320x240:r=30:d=0.1"
PREFLIGHT_TIMEOUT_S = 20
PREFLIGHT_DETAIL_MAX = 160
_PREFLIGHT: dict = {}  # 每个进程只成功试一次：{"result": None, "encoder": 选中的编码器}；失败不缓存，下次再探
_LOCK = threading.RLock()


def unavailable_text() -> str:
    return ENCODER_UNAVAILABLE_WIN if sys.platform == "win32" else ENCODER_UNAVAILABLE


def _try(enc: str, runner) -> str | None:
    """用 enc 试编一次；成功返回 None，失败返回原因。"""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", PREFLIGHT_SOURCE,
           *h264_args("proxy", enc), "-f", "null", "-"]
    try:
        r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=PREFLIGHT_TIMEOUT_S)
        return None if r.returncode == 0 else \
            ((r.stderr or "").strip().splitlines() or [f"退出码 {r.returncode}"])[-1]
    except (OSError, subprocess.SubprocessError) as exc:
        return f"无法运行 ffmpeg：{type(exc).__name__}"


def preflight(runner=subprocess.run) -> str | None:
    """用 0.1 秒的测试画面按候选顺序试编；有一个可用返回 None 并记住它，否则返回给用户看的中文说明。
    只缓存成功（编码器与结果一起写入）；线程安全。"""
    with _LOCK:
        if "result" in _PREFLIGHT:
            return _PREFLIGHT["result"]
        detail = None
        for enc in candidates():
            detail = _try(enc, runner)
            if detail is None:
                _PREFLIGHT.update(encoder=enc, result=None)
                return None
        return unavailable_text().format(detail=detail[:PREFLIGHT_DETAIL_MAX])
