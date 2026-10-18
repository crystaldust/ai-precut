#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ASR 原始结果整理成两份东西：

  1. transcript.md   —— 带时间码的分段文稿（人读，用来判断内容和挑金句）
  2. segments.json   —— 粗分段（程序读，后面做剪辑脚本的候选池）

切段规则（宁可切碎，不要切错）：
  * 同一说话人、句间停顿 < 1.2s  → 同段
  * 换人 / 停顿 > 2.5s / 段长 > 35s → 断段

用法：
    python3 format_transcript.py transcript_raw.json -o <输出目录>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

GAP_SAME_SPEAKER = 1.2
GAP_ANY = 2.5
MAX_SEG = 35.0


def tc(sec: float) -> str:
    m, s = divmod(max(0.0, sec), 60)
    return f"{int(m):02d}:{s:05.2f}"


def load_subs(path: Path) -> tuple[list[dict], float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    # 兼容 {result:{subtitles}} / {subtitles} / [ ... ]
    if isinstance(data, list):
        subs, duration = data, 0.0
    else:
        node = data.get("result", data)
        subs = node.get("subtitles") or node.get("result", {}).get("subtitles") or []
        duration = node.get("duration", 0.0)
    out = []
    for s in subs:
        text = (s.get("subtitle_text") or s.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(s.get("start_time", 0)),
            "end": float(s.get("end_time", 0)),
            "text": text,
            "speaker": s.get("speaker") or "",
            "confidence": s.get("confidence"),
        })
    out.sort(key=lambda x: x["start"])
    return out, duration


def is_noise(text: str) -> bool:
    """纯语气词/无意义行：嗯、啊、哦、呃……（但保留"嗯，对"这类有回应的）"""
    core = re.sub(r"[，。！？、,.!?\s]", "", text)
    return len(core) <= 2 and all(c in "嗯啊哦呃唉哎哈呀吧呢" for c in core)


def build_segments(subs: list[dict]) -> list[dict]:
    segs: list[dict] = []
    cur = None
    for s in subs:
        if cur is None:
            cur = {"start": s["start"], "end": s["end"], "speaker": s["speaker"],
                   "lines": [s]}
            continue
        gap = s["start"] - cur["end"]
        same = (s["speaker"] == cur["speaker"])
        too_long = (s["end"] - cur["start"]) > MAX_SEG
        if (same and gap > GAP_SAME_SPEAKER) or (not same and gap > GAP_ANY) or too_long:
            segs.append(cur)
            cur = {"start": s["start"], "end": s["end"], "speaker": s["speaker"],
                   "lines": [s]}
        else:
            cur["end"] = s["end"]
            cur["lines"].append(s)
    if cur:
        segs.append(cur)
    for i, seg in enumerate(segs, 1):
        seg["id"] = f"S{i:03d}"
        seg["text"] = "".join(l["text"] for l in seg["lines"])
        seg["duration"] = round(seg["end"] - seg["start"], 2)
        seg["chars"] = len(re.sub(r"\s", "", seg["text"]))
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("-o", "--out", default=".")
    args = ap.parse_args()

    subs, duration = load_subs(Path(args.raw))
    if not subs:
        sys.exit("没有解析到字幕，检查 ASR 返回结构")
    subs = [s for s in subs if not is_noise(s["text"])]
    segs = build_segments(subs)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    (out / "segments.json").write_text(json.dumps({
        "duration": duration, "count": len(segs), "segments": segs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# 文稿分段（{tc(duration)}，{len(segs)} 段，{len(subs)} 句）", ""]
    for s in segs:
        who = s["speaker"] or "—"
        lines.append(f"**[{s['id']}] {tc(s['start'])}–{tc(s['end'])} "
                     f"（{s['duration']:.1f}s，{who}）**  ")
        lines.append(s["text"])
        lines.append("")
    (out / "transcript.md").write_text("\n".join(lines), encoding="utf-8")

    total_chars = sum(s["chars"] for s in segs)
    print(f"句数 {len(subs)} → 段数 {len(segs)}")
    print(f"总字数 {total_chars}，平均语速 {total_chars / max(duration, 1) * 60:.1f} 字/分")
    print(f"输出：{out/'transcript.md'} / {out/'segments.json'}")


if __name__ == "__main__":
    main()
