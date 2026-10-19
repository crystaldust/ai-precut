# -*- coding: utf-8 -*-
"""策划分派单 markdown（从 aicut.py 拆出，KI-55）：只拼文本，读写盘由 cmd_brief 负责。"""
from __future__ import annotations

DEFAULT_MAX_CHARS = 14


def render_brief(c: dict, preset: dict, segs: list[dict], junk: list[dict]) -> str:
    lines = [f"# 策划分派单 · {c['title']}", "",
             f"- 原片：`{c['material']}`",
             f"- 预设：{preset.get('name')}（{preset.get('duration')}s，{c['platform']}）",
             f"- 结构建议：{' → '.join(preset.get('structure', []))}",
             f"- 字幕：≤{preset.get('subtitle', {}).get('max_chars', DEFAULT_MAX_CHARS)} 字/行",
             "", f"## 分段文稿（{len(segs)} 段）", ""]
    for s in segs:
        lines.append(f"**[{s['id']}] {s['start']:.1f}–{s['end']:.1f}s** {s['text']}")
    if junk:
        lines += ["", "## 规则层废片候选", ""]
        for j in junk:
            lines.append(f"- {j['start_tc']}–{j['end_tc']} {j['reason']}（{j['suggest']}）")
    lines += ["", "## 产出要求", "",
              "写 `shots.json`：每镜含 id / in / out / sub / note；",
              "再跑 `python3 aicut.py build <项目> --version v1` 出片。"]
    return "\n".join(lines)
