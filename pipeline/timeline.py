# -*- coding: utf-8 -*-
"""分镜表 → 时间线 JSON（从 aicut.py 拆出，KI-55）。纯函数：不读写磁盘。"""
from __future__ import annotations

import re
from pathlib import Path

from pipeline import build_documentary

SUB_BREAK = re.compile(r"(?<=[，。！？；])")  # 字幕卡只在这些标点后断开
DEFAULT_MAX_CHARS = 14
DEFAULT_SUB_SIZE = 6.5


def split_sub(text: str, max_chars: int) -> list[str]:
    """一镜字幕按标点切成不超过 max_chars 的字幕卡；单句过长就硬切。"""
    cards, cur = [], ""
    for p in SUB_BREAK.split(text):
        if not p:
            continue
        if len(cur) + len(p) <= max_chars:
            cur += p
            continue
        if cur:
            cards.append(cur)
        while len(p) > max_chars:
            cards.append(p[:max_chars])
            p = p[max_chars:]
        cur = p
    if cur:
        cards.append(cur)
    return cards or [text]


def compose_timeline(c: dict, preset: dict, shots: list[dict], clips_dir: Path,
                     durations: dict[str, float]) -> dict:
    max_chars = preset.get("subtitle", {}).get("max_chars", DEFAULT_MAX_CHARS)
    tl = {"project": {"name": c["title"], "width": 1080, "height": 1920,
                      "fps": 30, "platform": c.get("platform", "douyin")},
          "video": [], "audio": [], "text": []}
    t = 0.0
    for sh in shots:
        dur = durations.get(sh["id"], round(sh["out"] - sh["in"], 3))
        tl["video"].append({"id": sh["id"], "source": str(clips_dir / f"{sh['id']}.mp4"),
                            "in": 0.0, "out": dur, "timeline_in": round(t, 3),
                            "role": "broll" if not sh.get("sub") else "speech",
                            "caption": sh.get("note", "")})
        if sh.get("sub"):
            cards = split_sub(sh["sub"], max_chars)
            total = sum(len(x) for x in cards)
            ct = t
            for card in cards:
                cd = dur * len(card) / total
                tl["text"].append({"id": f"{sh['id']}_{len(tl['text'])}",
                                   "text": card, "start": round(ct, 3),
                                   "end": round(ct + cd, 3),
                                   "style": {"size": preset.get("subtitle", {}).get("size", DEFAULT_SUB_SIZE),
                                             "color": [1, 1, 1], "bold": True, "align": 2}})
                ct += cd
        t += dur
    tl["text"] += build_documentary.card_entries(
        preset.get("cards", []), t,
        size=preset.get("card", {}).get("size", build_documentary.CARD_SIZE))
    return tl
