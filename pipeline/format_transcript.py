#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ASR 原始结果整理成两份东西：

  1. transcript.md   —— 带时间码的分段文稿（人读，用来判断内容和挑金句）
  2. segments.json   —— 粗分段（程序读，后面做剪辑脚本的候选池）

切段规则（宁可切碎，不要切错）：
  * 同一说话人、句间停顿 < 1.2s  → 同段
  * 换人 / 停顿 > 2.5s / 段长 > 35s → 断段

用法：
    python -m pipeline.format_transcript transcript_raw.json -o <输出目录>   # 在仓库根运行
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # 脚本方式运行时可导入 pipeline；append 防遮蔽三方包（同 render_preview）

from pipeline import schema  # noqa: E402
from pipeline.shot_sub import join_lines  # noqa: E402

GAP_SAME_SPEAKER = 1.2
GAP_ANY = 2.5
MAX_SEG = 35.0
SUBS_DROPPED_WARNING = "{n} 句缺少有效时间码，已跳过（检查 ASR 返回结构）"
NO_TIMED_SUBS = "所有句子都没有可用的时间码，检查 ASR 返回结构"


def tc(sec: float) -> str:
    cs = int(round(max(0.0, sec) * 100))  # 先按显示精度取整再进位：59.999 → 01:00.00（KI-24）
    m, cs = divmod(cs, 6000)
    return f"{m:02d}:{cs // 100:02d}.{cs % 100:02d}"


def _time(raw) -> float | None:
    """ASR 时间字段 → 非负有限秒数；缺失 / 非数 / bool → None（不能默认 0，KI-24）。"""
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def load_subs(path: Path) -> tuple[list[dict], float, int]:
    """→ (按起点排序的句子, 时长, 因时间码无效而丢弃的句数)。"""
    data = schema.read_json(path, expect=None)  # 损坏 → CorruptJSON（带文件名）
    if not isinstance(data, (list, dict)):
        raise schema.CorruptJSON(schema.CORRUPT_JSON_MSG.format(
            name=Path(path).name, detail="顶层应为对象或列表", path=path))
    # 兼容 {result:{subtitles}} / {subtitles} / [ ... ]
    if isinstance(data, list):
        subs, duration = data, 0.0
    else:
        node = data.get("result", data)
        subs = node.get("subtitles") or node.get("result", {}).get("subtitles") or []
        duration = node.get("duration", 0.0)
    out = []
    dropped = 0
    for s in subs:
        text = (s.get("subtitle_text") or s.get("text") or "").strip()
        if not text:
            continue
        start, end = _time(s.get("start_time")), _time(s.get("end_time"))
        if start is None or end is None or end < start:
            dropped += 1
            continue
        out.append({
            "start": start,
            "end": end,
            "text": text,
            "speaker": s.get("speaker") or "",
            "confidence": s.get("confidence"),
        })
    out.sort(key=lambda x: x["start"])
    return out, duration, dropped


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
            cur["end"] = max(cur["end"], s["end"])  # 包含句不能让段尾回退（KI-24）
            cur["lines"].append(s)
    if cur:
        segs.append(cur)
    for i, seg in enumerate(segs, 1):
        seg["id"] = f"S{i:03d}"
        seg["text"] = join_lines([l["text"] for l in seg["lines"]])
        seg["duration"] = round(seg["end"] - seg["start"], 2)
        seg["chars"] = len(re.sub(r"\s", "", seg["text"]))
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("-o", "--out", default=".")
    args = ap.parse_args()

    try:
        subs, duration, dropped = load_subs(Path(args.raw))
    except schema.CorruptJSON as exc:
        sys.exit(str(exc))
    if not subs and dropped:
        sys.exit(NO_TIMED_SUBS)
    if not subs:
        sys.exit("没有解析到字幕，检查 ASR 返回结构")
    warnings = [SUBS_DROPPED_WARNING.format(n=dropped)] if dropped else []
    for w in warnings:  # 同时写进 segments.json，剪辑台警告栏常驻显示（任务成功时子进程输出看不到）
        print(f"[!] {w}")
    subs = [s for s in subs if not is_noise(s["text"])]
    segs = build_segments(subs)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    (out / "segments.json").write_text(json.dumps({
        "duration": duration, "count": len(segs), "segments": segs, "warnings": warnings,
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
