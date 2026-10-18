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
