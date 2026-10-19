#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把分镜表（shots.json）变成：切片文件 + timeline.json + 分镜表.md

流程：
  1. 按 in/out 从原片切出每一镜（顺手转正、统一 1080x1920/30fps、压成小文件）
  2. 字幕按标点拆成 2 行以内的小卡，时长按字数分配（贴合 12–14 字/行的可读性）
  3. 输出 timeline.json（给 render_preview / to_jianying 共用）
  4. 输出分镜表.md（人看）

用法：
    python3 build_documentary.py shots.json -o <项目目录>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # 脚本方式运行时可导入 pipeline.media_io；append 防遮蔽三方包

from pipeline import media_io  # noqa: E402

MAX_CHARS = 14          # 单行最多 14 字（1080 宽下 63px 字号刚好不溢出）
W, H, FPS = 1080, 1920, 30
CARD_SIZE = 6.8
CARD_ALIGN = 5          # 时间轴约定：2=底部字幕、5=居中字幕卡（见 to_jianying / render_preview）
# D1（产品默认）：字幕卡起点超出成片时长 → 跳过并提示
CARD_SKIPPED_WARNING = "[warn] 字幕卡 {text!r} 在 {at:.1f}s，超出成片时长 {total:.1f}s，已跳过"
CARD_SHORTENED_WARNING = ("[warn] 字幕卡 {text!r} 原定 {dur:.1f}s，被成片结尾 {total:.1f}s "
                          "截短为 {kept:.1f}s")


def split_sub(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """按标点拆字幕卡，每张不超过 max_chars 字"""
    parts = re.split(r"(?<=[，。！？；])", text)
    cards, cur = [], ""
    for p in parts:
        if not p:
            continue
        if len(cur) + len(p) <= max_chars:
            cur += p
        else:
            if cur:
                cards.append(cur)
            while len(p) > max_chars:      # 超长单句按硬切
                cards.append(p[:max_chars])
                p = p[max_chars:]
            cur = p
    if cur:
        cards.append(cur)
    return cards or [text]


def cut_shot(src: Path, dst: Path, start: float, dur: float) -> None:
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}")
    media_io.ffmpeg_to(dst, ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                             "-vf", vf,
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                             "-movflags", "+faststart"])


def card_entries(cards: list[dict], total: float, size: float = CARD_SIZE) -> list[dict]:
    """片头/片尾字幕卡 → 时间轴文字项；超出成片时长的卡跳过，结尾截到 total（GL-10）。"""
    out = []
    for card in cards:
        start = float(card["at"])
        end = min(start + float(card["dur"]), total)
        if end <= start:
            print(CARD_SKIPPED_WARNING.format(text=card["text"], at=start, total=total))
            continue
        if end < start + float(card["dur"]):
            print(CARD_SHORTENED_WARNING.format(text=card["text"], dur=float(card["dur"]),
                                                total=total, kept=end - start))
        out.append({"id": f"card_{card['at']}", "text": card["text"],
                    "start": start, "end": round(end, 3),
                    "style": {"size": size, "color": [1, 1, 1], "bold": True,
                              "align": CARD_ALIGN}})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shots")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    spec = json.loads(Path(args.shots).read_text(encoding="utf-8"))
    src = Path(spec["source"])
    if not src.exists():
        sys.exit(f"原片不存在：{src}")
    out = Path(args.out); clips = out / "clips"; clips.mkdir(parents=True, exist_ok=True)

    timeline = {"project": {"name": spec["project"], "width": W, "height": H,
                            "fps": FPS, "platform": "douyin"},
                "video": [], "audio": [], "text": []}
    t = 0.0
    rows = []
    for sh in spec["shots"]:
        dur = round(sh["out"] - sh["in"], 3)
        clip = clips / f"{sh['id']}.mp4"
        if not media_io.complete_or_adopt(clip):
            try:
                cut_shot(src, clip, sh["in"], dur)
            except media_io.MediaError as exc:
                sys.exit(f"切镜头 {sh['id']} 失败：{exc}")
        timeline["video"].append({
            "id": sh["id"], "source": str(clip), "in": 0.0, "out": dur,
            "timeline_in": round(t, 3), "role": "broll" if not sh["sub"] else "speech",
            "caption": sh.get("note", ""),
        })
        if sh["sub"]:
            cards = split_sub(sh["sub"])
            total_chars = sum(len(c) for c in cards)
            ct = t
            for c in cards:
                cd = dur * len(c) / total_chars
                timeline["text"].append({
                    "id": f"{sh['id']}_t", "text": c,
                    "start": round(ct, 3), "end": round(ct + cd, 3),
                    "style": {"size": 6.5, "color": [1, 1, 1], "bold": True, "align": 2},
                })
                ct += cd
        rows.append((sh["id"], t, t + dur, dur, sh["sub"] or "（无字幕）", sh.get("note", "")))
        t += dur

    # 片头/片尾字幕卡
    timeline["text"] += card_entries(spec.get("cards", []), t)

    (out / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")

    def tc(x: float) -> str:
        return f"{int(x // 60):02d}:{x % 60:05.2f}"

    md = [f"# 分镜表 · {spec['project']}", "",
          f"源片：`{src.name}`　成片：{tc(t)}　镜头数：{len(rows)}", "",
          "| # | 时间码 | 时长 | 画面 | 字幕 / 说明 |", "|---|---|---|---|---|"]
    for sid, s, e, d, sub, note in rows:
        md.append(f"| {sid} | {tc(s)}–{tc(e)} | {d:.1f}s | {note} | {sub} |")
    (out / "分镜表.md").write_text("\n".join(md), encoding="utf-8")

    print(f"镜头 {len(rows)} 个，成片 {tc(t)}（{t:.1f}s）")
    print(f"字幕卡 {len(timeline['text'])} 张")
    print(f"输出：{out/'timeline.json'} / {out/'分镜表.md'} / {clips}")


if __name__ == "__main__":
    main()
