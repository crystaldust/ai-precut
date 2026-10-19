# -*- coding: utf-8 -*-
"""c 路：画面（PRD FR-2）。

一期只做两件确定的事，全部在本地 540p 代理片上跑，画面帧不出本机（PRD §7）：
  1. 镜头切分（ffmpeg scdet 场景变化分数）：只对多镜头 / 剪辑过的素材有意义，
     一镜到底素材几乎没有切点；在代理片上跑比原始素材快 5–10 倍，切点精度对粗剪足够；
  2. 画面质量（sample_frames / quality）：1fps 灰度小图算亮度、运动、清晰度，
     标出过暗 / 静止 / 抖动 / 虚焦。
景别、人脸、OCR、道具识别是 P2（PRD FR-2），如做须本地实现，不送云端视觉模型。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from pipeline import media_io, schema

CUT_RE = re.compile(r"lavfi\.scd\.time:\s*([\d.]+)")
FRAMES_EMPTY = "抽帧失败：一帧画面也没读到"
FRAMES_FAILED = "抽帧失败（退出码 {code}）：{tail}"
FRAMES_STUCK = "抽帧失败：画面读完后 ffmpeg {sec} 秒没有退出"
QUALITY_SKIPPED = "画面质量分析失败，已跳过（这次分档不识别过暗画面）：{reason}"
FRAMES_EXIT_WAIT_S = 30  # 读到 EOF 后等 ffmpeg 自己退出的上限


def probe_duration(path: Path) -> float:
    return media_io.probe_duration(path)  # 读不出正时长抛 MediaError，带 ffprobe 原因（KI-19）


def detect_cuts(video: Path, *, threshold: float = 8.0,
                timeout: float = 1800) -> list[float]:
    """返回切点时间（秒），升序。threshold 越大越不敏感。ffmpeg 失败抛 MediaError（KI-19）。"""
    log = media_io.run_analysis(["-i", str(video), "-vf", f"scdet=threshold={threshold}",
                                 "-an", "-f", "null", "-"], timeout=timeout)
    return sorted(float(x) for x in CUT_RE.findall(log))


def build_shots(cuts: list[float], duration: float,
                *, min_len: float = 0.5) -> list[dict]:
    """把切点转成镜头区间；过短的镜头并入前一个。"""
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    shots: list[dict] = []
    for start, end in zip(bounds, bounds[1:]):
        if end - start < min_len and shots:
            shots[-1]["end"] = round(end, 2)
            shots[-1]["duration"] = round(shots[-1]["end"] - shots[-1]["start"], 2)
            continue
        shots.append({"index": len(shots) + 1, "start": round(start, 2),
                      "end": round(end, 2), "duration": round(end - start, 2)})
    return shots


def analyze(video: Path, *, threshold: float = 8.0) -> dict:
    duration = probe_duration(video)
    cuts = detect_cuts(video, threshold=threshold)
    shots = build_shots(cuts, duration)
    return {"source": str(video), "duration": round(duration, 2),
            "threshold": threshold, "cut_count": len(cuts), "shots": shots}


def run(video: Path, out_path: Path, *, threshold: float = 8.0) -> dict:
    result = analyze(Path(video), threshold=threshold)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    import json
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover
    import sys

    project = Path(sys.argv[1])
    res = run(project / "work/proxy.mp4", project / "work/shots_visual.json")
    print(f"镜头 {len(res['shots'])} 个（切点 {res['cut_count']}）")


# ---------------------------------------------------------------- 画面质量
def sample_frames(video: Path, *, fps: float = 1.0, width: int = 160,
                  height: int = 90, timeout: float = 1800, popen=None):
    """一次解码，按 fps 抽灰度小图，逐帧算亮度/运动/清晰度。

    返回 [{t, bright, motion, blur}]；不保留图像本身，内存恒定。
    ffmpeg 非零退出或一帧都没读到抛 MediaError（KI-19），不再当成「无明显异常」。
    """
    popen = popen or subprocess.Popen
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(video),
           "-vf", f"fps={fps},scale={width}:{height},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    out: list[dict] = []
    with tempfile.TemporaryFile() as err:  # stderr 不走 PIPE：避免和 stdout 互相堵塞
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=err)
        code = None
        try:
            out = _read_frames(proc.stdout, fps=fps, width=width, height=height)
            code = proc.wait(timeout=FRAMES_EXIT_WAIT_S)
        except subprocess.TimeoutExpired as exc:
            raise media_io.MediaError(FRAMES_STUCK.format(sec=FRAMES_EXIT_WAIT_S)) from exc
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if code != 0:
            err.seek(0)
            tail = err.read().decode("utf-8", "replace").strip()[-media_io.STDERR_TAIL:]
            raise media_io.MediaError(FRAMES_FAILED.format(code=code, tail=tail))
    if not out:
        raise media_io.MediaError(FRAMES_EMPTY)
    return out


def _read_frames(stream, *, fps: float, width: int, height: int) -> list[dict]:
    size = width * height
    out: list[dict] = []
    prev = None
    idx = 0
    while True:
        buf = stream.read(size)
        if not buf or len(buf) < size:
            break
        bright = sum(buf) / size
        motion = 0.0
        if prev is not None:
            motion = sum(abs(a - b) for a, b in zip(buf, prev)) / size
        # 4 邻域拉普拉斯方差：越模糊越小
        lap = 0
        for y in range(1, height - 1):
            row = y * width
            for x in range(1, width - 1):
                i = row + x
                v = buf[i] * 4 - buf[i - 1] - buf[i + 1] - buf[i - width] - buf[i + width]
                lap += v * v
        blur = lap / ((width - 2) * (height - 2))
        out.append({"t": round(idx / fps, 2), "bright": round(bright, 1),
                    "motion": round(motion, 2), "blur": round(blur, 1)})
        prev = buf
        idx += 1
    return out


def aggregate_by_segment(samples: list[dict], segments: list[dict]) -> dict[str, dict]:
    """把逐帧指标按句子的时间区间取平均。"""
    result: dict[str, dict] = {}
    for seg in segments:
        start, end = float(seg["start"]), float(seg["end"])
        frames = [s for s in samples if start <= s["t"] < end]
        if not frames:
            continue
        n = len(frames)
        result[seg["id"]] = {
            "bright": round(sum(f["bright"] for f in frames) / n, 1),
            "motion": round(sum(f["motion"] for f in frames) / n, 2),
            "blur": round(sum(f["blur"] for f in frames) / n, 1),
            "dark_ratio": round(sum(1 for f in frames if f["bright"] < 16) / n, 2),
            "still_ratio": round(sum(1 for f in frames if f["motion"] < 0.5) / n, 2),
            "soft_ratio": round(sum(1 for f in frames if f["blur"] < 20) / n, 2),
            "frames": n,
        }
    return result


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    ordered = sorted(vals)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def quality(video: Path, segments: list[dict], *, fps: float = 1.0) -> dict:
    samples = sample_frames(Path(video), fps=fps)
    by_id = aggregate_by_segment(samples, segments)
    if by_id:
        blurs = [v["blur"] for v in by_id.values()]
        motions = [v["motion"] for v in by_id.values()]
        # 相对阈值：不同机器/场景的绝对亮度与细节差异太大，用本条素材的分位数
        # 下限 20 防小样本/纯色时 p10=0；上限 150 防把正常素材全判糊
        soft_line = min(150.0, max(20.0, _pct(blurs, 0.10) * 0.8))
        still_line = max(0.5, _pct(motions, 0.10) * 0.8)
        shaky_line = _pct(motions, 0.90) * 1.3
        for v in by_id.values():
            flags = []
            if v["blur"] < soft_line:
                flags.append("soft")
            if v["motion"] < still_line:
                flags.append("still")
            if v["motion"] > shaky_line:
                flags.append("shaky")
            if v["bright"] < 16 or v["dark_ratio"] > 0.5:
                flags.append("dark")
            v["flags"] = flags
        stats = {"blur_p10": round(_pct(blurs, 0.10), 1),
                 "blur_p50": round(_pct(blurs, 0.50), 1),
                 "motion_p10": round(_pct(motions, 0.10), 2),
                 "motion_p90": round(_pct(motions, 0.90), 2),
                 "soft_line": round(soft_line, 1),
                 "shaky_line": round(shaky_line, 2)}
    else:
        stats = {}
    return {"source": str(video), "fps": fps, "samples": len(samples),
            "stats": stats, "segments": by_id}


def run_quality(video: Path, segments_path: Path, out_path: Path,
                *, fps: float = 1.0) -> dict:
    import json as _json
    segments = schema.read_field(segments_path, "segments")  # 结构不对 → CorruptJSON（带文件名）
    try:
        result = quality(Path(video), segments, fps=fps)
    except media_io.MediaError:
        Path(out_path).unlink(missing_ok=True)  # 旧结果不能被分档当成这次的
        raise
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(_json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return result
