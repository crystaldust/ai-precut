# -*- coding: utf-8 -*-
"""c 路（第一层）：镜头切分。

只做一件确定的事：找出画面发生实质变化的时间点，形成镜头序列。
不做景别/人脸/道具识别——那些要抽帧后送视觉模型，成本高，按需再上。

实现用 ffmpeg 的 scdet 滤镜（场景变化分数），在 540p 代理片上跑，
比在原始素材上跑快 5–10 倍，切点精度对粗剪足够。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

CUT_RE = re.compile(r"lavfi\.scd\.time:\s*([\d.]+)")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8").stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def detect_cuts(video: Path, *, threshold: float = 8.0,
                timeout: float = 1800) -> list[float]:
    """返回切点时间（秒），升序。threshold 越大越不敏感。"""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
           "-vf", f"scdet=threshold={threshold}", "-an", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    times = sorted(float(x) for x in CUT_RE.findall(proc.stderr))
    return times


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
    if duration <= 0:
        raise ValueError(f"读不到时长：{video}")
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
                  height: int = 90, timeout: float = 1800):
    """一次解码，按 fps 抽灰度小图，逐帧算亮度/运动/清晰度。

    返回 [{t, bright, motion, blur}]；不保留图像本身，内存恒定。
    """
    import subprocess as sp

    size = width * height
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(video),
           "-vf", f"fps={fps},scale={width}:{height},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.DEVNULL)
    out: list[dict] = []
    prev = None
    idx = 0
    try:
        while True:
            buf = proc.stdout.read(size)
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
    finally:
        proc.kill()
        proc.wait()
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
    segments = _json.loads(Path(segments_path).read_text(encoding="utf-8"))["segments"]
    result = quality(Path(video), segments, fps=fps)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(_json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return result
