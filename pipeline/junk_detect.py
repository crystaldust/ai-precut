#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""废片检测：黑场 / 冻帧 / 静音 / 镜头切换，一次解码全部拿到。

设计原则：
  * 只标记，不删素材。输出的每一行都是"建议"，最终由剪辑师确认。
  * 单次 pass：三个 ffmpeg filter 串在一条命令里，避免反复解码大文件。
  * 输出两份：junk_report.json（给程序）+ junk_report.csv（给人看）。

用法：
    python3 junk_detect.py <视频> -o <输出目录> [--scene]
    python3 junk_detect.py proxy.mp4 -o analysis/ --scene

依赖：ffmpeg（脚本只用标准库）
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

# ffmpeg 的日志行样例：
#   [blackdetect @ 0x...] black_start:12.5 black_end:14.2 black_duration:1.7
#   [freezedetect @ 0x...] lavfi.freezedetect.freeze_start: 100.5
#   [silencedetect @ 0x...] silence_start: 33.1
#   [scdet @ 0x...] lavfi.scd.time: 12.345
RE_BLACK = re.compile(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)")
RE_FREEZE_START = re.compile(r"freeze_start:\s*([\d.]+)")
RE_FREEZE_END = re.compile(r"freeze_end:\s*([\d.]+)")
RE_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
RE_SIL_END = re.compile(r"silence_end:\s*([\d.]+)")
RE_SCENE = re.compile(r"lavfi\.scd\.time:\s*([\d.]+)")


def ts(sec: float) -> str:
    """秒 → HH:MM:SS.mmm，方便对时间码"""
    h, rem = divmod(max(0.0, sec), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def merge(intervals: list[tuple[float, float, str]], gap: float = 0.3):
    """合并同一类型、间隔 < gap 的相邻区间"""
    intervals.sort(key=lambda x: (x[2], x[0]))
    out: list[tuple[float, float, str]] = []
    for start, end, kind in intervals:
        if out and out[-1][2] == kind and start - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], end), kind)
        else:
            out.append((start, end, kind))
    return out


def detect(media: Path, silence_db: float, freeze_sec: float,
           black_sec: float, scene: bool) -> tuple[list, float]:
    vf = (f"blackdetect=d={black_sec}:pix_th=0.10,"
          f"freezedetect=n=-60dB:d={freeze_sec}")
    if scene:
        vf += ",scdet=threshold=10"
    af = f"silencedetect=noise={silence_db}dB:d=1.0"

    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
           "-vf", vf, "-af", af, "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    log = proc.stderr

    raw: list[tuple[float, float, str]] = []
    for m in RE_BLACK.finditer(log):
        raw.append((float(m.group(1)), float(m.group(2)), "black"))
    for m in RE_FREEZE_START.finditer(log):
        raw.append((float(m.group(1)), float(m.group(1)), "freeze_open"))
    for m in RE_FREEZE_END.finditer(log):
        raw.append((float(m.group(1)), float(m.group(1)), "freeze_close"))
    for m in RE_SIL_START.finditer(log):
        raw.append((float(m.group(1)), float(m.group(1)), "silence_open"))
    for m in RE_SIL_END.finditer(log):
        raw.append((float(m.group(1)), float(m.group(1)), "silence_close"))

    # 把 open/close 成对拼起来
    def pair(open_kind: str, close_kind: str, name: str):
        opens: list[float] = []
        items = []
        for start, end, kind in sorted(raw, key=lambda x: x[0]):
            if kind == open_kind:
                opens.append(start)
            elif kind == close_kind and opens:
                s = opens.pop(0)
                items.append((s, start, name))
        return items

    intervals = [(a, b, "black") for a, b, k in raw if k == "black"]
    intervals += pair("freeze_open", "freeze_close", "freeze")
    intervals += pair("silence_open", "silence_close", "silence")

    duration = 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", log)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    scenes = [float(x) for x in RE_SCENE.findall(log)]
    return merge(intervals), duration


def judge(intervals, duration, silence_db) -> list[dict]:
    """规则判废：单信号给"参考"，多信号重叠给"建议删"。"""
    rows = []
    tl = sorted(intervals, key=lambda x: x[0])
    for i, (s, e, kind) in enumerate(tl):
        length = e - s
        overlapping = {(k) for (s2, e2, k) in tl
                       if k != kind and s2 < e and e2 > s}
        if kind == "silence" and length < 3.0:
            continue
        if kind == "freeze" and length < 2.0:
            continue
        kind_cn = {"black": "黑场", "freeze": "冻帧", "silence": "静音"}[kind]
        score, reason = 0.55, f"{kind_cn} {length:.1f}s"
        if kind == "black":
            score = 0.95
        if "freeze" in overlapping and "silence" in overlapping:
            score, reason = 0.97, f"无语音 + 画面静止 {length:.1f}s（强废片信号）"
        elif "silence" in overlapping:
            score = max(score, 0.7)
            reason += " + 同期静音"
        action = "删" if score >= 0.85 else ("待定" if score >= 0.6 else "参考")
        rows.append({
            "start": round(s, 3), "end": round(e, 3), "duration": round(length, 3),
            "start_tc": ts(s), "end_tc": ts(e),
            "type": kind, "reason": reason, "score": round(score, 2),
            "suggest": action,
            "coverage_pct": round(100 * length / duration, 2) if duration else 0,
        })
    # 合并"删"的相邻项，减少表格行数
    rows.sort(key=lambda r: r["start"])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("-o", "--out", default=".")
    ap.add_argument("--silence-db", type=float, default=-35.0)
    ap.add_argument("--freeze-sec", type=float, default=2.0)
    ap.add_argument("--black-sec", type=float, default=0.5)
    ap.add_argument("--scene", action="store_true", help="同时检测镜头切换点")
    args = ap.parse_args()

    media = Path(args.media)
    if not media.exists():
        sys.exit(f"找不到媒体：{media}")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    print(f"分析中：{media}（单次解码，请稍候）")
    intervals, duration = detect(media, args.silence_db,
                                 args.freeze_sec, args.black_sec, args.scene)
    rows = judge(intervals, duration, args.silence_db)

    (out / "junk_report.json").write_text(
        json.dumps({"media": str(media), "duration": duration,
                    "items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(out / "junk_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["start_tc", "end_tc", "duration",
                                          "type", "reason", "score", "suggest"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})

    total = sum(r["duration"] for r in rows if r["suggest"] == "删")
    print(f"完成：{len(rows)} 条信号，建议删除 {total:.1f}s"
          f"（占 {100*total/duration:.1f}%）")
    print(f"输出：{out/'junk_report.csv'} / {out/'junk_report.json'}")


if __name__ == "__main__":
    main()
