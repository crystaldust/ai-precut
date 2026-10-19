# -*- coding: utf-8 -*-
"""终端问答（从 aicut.py 拆出，KI-55）：非交互环境（含 GUI 起的任务）一律不提问。"""
from __future__ import annotations

import sys

from pipeline import schema, style

TARGET_PROMPT = "想剪成多长的片子？（秒，回车用预设 {default} 秒）"
CALIBRATION_INTRO = "\n先问三个问题，答案会写进提示词（回车沿用当前值）："


def ask_target(default: int) -> int:
    """在终端里问成片时长；非交互环境（含 GUI）直接用预设值。"""
    if not sys.stdin.isatty():
        return default
    while True:
        raw = input(TARGET_PROMPT.format(default=default) + "\n  > ").strip()
        if not raw:
            return default
        try:
            return schema.check_target_duration(raw)
        except ValueError as exc:
            print(f"  {exc}")


def ask_calibration(existing: dict) -> dict:
    """在终端里问剪辑员三个问题（非交互环境直接返回原值）。"""
    cur = style.normalize(existing)
    if not sys.stdin.isatty():
        return cur
    print(CALIBRATION_INTRO)
    for key, question in style.QUESTIONS:
        default = cur.get(key, "")
        suffix = f" [{default}]" if default else ""
        raw = input(f"  {question}{suffix}\n  > ").strip()
        if raw:
            cur[key] = raw
    cur = style.normalize(cur)
    print(f"  已记录：{style.TONES[cur['tone']]}"
          + (f" · 观众 {cur['audience']}" if cur["audience"] else "")
          + (" · 含指定原话" if cur["must_lines"] else ""))
    return cur
