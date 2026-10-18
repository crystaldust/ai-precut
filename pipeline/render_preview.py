#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 timeline.json 渲染审片用的预览片（ffmpeg，不依赖剪映）。

与 to_jianying.py 共用同一份 timeline.json，保证"预览"和"剪映工程"内容一致。
支持：多镜头硬切拼接、原声保留、按时间轴叠字幕/字幕卡。

用法：
    python3 render_preview.py ../projects/xxx/output/timeline.json -o ../projects/xxx/output/preview.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
]


def pick_font() -> str:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    sys.exit("找不到可用中文字体")


def esc(text: str) -> str:
    """drawtext 转义"""
    return (text.replace("\\", r"\\").replace(":", r"\:")
                .replace("'", r"\'").replace("%", r"\%"))


def build(tl: dict) -> tuple[str, int]:
    W, H = tl["project"]["width"], tl["project"]["height"]
    fps = tl["project"].get("fps", 30)
    segs = sorted(tl["video"], key=lambda s: s["timeline_in"])

    parts, vlabels, alabels = [], [], []
    for i, s in enumerate(segs):
        dur = s["out"] - s["in"]
        parts.append(
            f"[{i}:v]trim=start={s['in']}:duration={dur},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={fps},setsar=1[v{i}]"
        )
        parts.append(f"[{i}:a]atrim=start={s['in']}:duration={dur},"
                     f"asetpts=PTS-STARTPTS,aresample=48000[a{i}]")
        vlabels.append(f"[v{i}]")
        alabels.append(f"[a{i}]")
    # concat 的输入必须"视频/音频"交替，不能先把视频标签全列完
    interleaved = "".join(v + a for v, a in zip(vlabels, alabels))
    parts.append(interleaved + f"concat=n={len(segs)}:v=1:a=1[vc][ac]")

    chain = "[vc]"
    for i, t in enumerate(sorted(tl.get("text", []), key=lambda x: x["start"])):
        st = t.get("style", {})
        size = int(st.get("size_px") or st.get("size", 7.0) * 9)
        color = st.get("color", [1, 1, 1])
        hexcolor = "0x" + "".join(f"{int(c * 255):02X}" for c in color[:3])
        align = st.get("align", 1)
        # 2=底部字幕（避开快手/抖音 UI），5=居中字幕卡
        y = {2: "h*0.74", 5: "h*0.42"}.get(align, "(h-text_h)/2")
        parts.append(
            f"{chain}drawtext=fontfile='{pick_font()}':text='{esc(t['text'])}':"
            f"fontsize={size}:fontcolor={hexcolor}:"
            f"borderw={max(2, size // 16)}:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y={y}:"
            f"enable='between(t,{t['start']},{t['end']})'[vt{i}]"
        )
        chain = f"[vt{i}]"
    parts.append(f"{chain}format=yuv420p[vout]")
    return ";\n".join(parts), len(segs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
    segs = sorted(tl["video"], key=lambda s: s["timeline_in"])
    filter_complex, n = build(tl)

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for s in segs:
        cmd += ["-i", s["source"]]
    cmd += ["-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[ac]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", args.out]
    print(f"渲染 {n} 个镜头 → {args.out}")
    subprocess.run(cmd, check=True)
    total = sum(s["out"] - s["in"] for s in segs)
    print(f"完成：{total:.1f}s")


if __name__ == "__main__":
    main()
