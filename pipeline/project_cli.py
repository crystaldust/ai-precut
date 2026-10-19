# -*- coding: utf-8 -*-
"""只读 / 维护类命令：status、list、clean（从 aicut.py 拆出，审查修复：入口文件行数）。

输出函数由调用方注入（同 config_cli），本模块不 import aicut。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from pipeline import cache, media_io, project_lock, readiness, schema, understand_text, usage

TEXT_INCOMPLETE_STATUS = "未完成"
MEDIA_SUFFIXES = (".wav", ".mp4")  # 这些产物以完成标记判定（GL-15；旧项目可被认领），其余看存在
USAGE_LINE = "LLM 用量：{used} tokens（上限 {budget}）"
USAGE_UNLIMITED = "不限"
LIST_CORRUPT = "（project.json 损坏）"
CLEAN_ITEM = "  {label}：{path}（{mb:.1f} MB）"
CLEAN_NOTHING = "没有可清理的缓存"
CLEAN_DONE = "已释放 {mb:.1f} MB"
CLEAN_BUSY = "这个项目正在运行任务（剪辑台或另一个终端），等它结束再清理缓存"
MB = 1e6


def status(pdir: Path, c: dict) -> None:
    print(f"\n项目：{c['title']}（{c['name']}）")
    print(f"预设：{c['preset']}　平台：{c['platform']}　目标：{c['target_duration']}s\n")
    text_incomplete = understand_text.is_incomplete(pdir / "work/segments_text.json")
    for label, rel in readiness.STATUS_ARTIFACTS:
        p = pdir / rel
        if p.name == "segments_text.json" and text_incomplete:
            print(f"  [!] {label}：{TEXT_INCOMPLETE_STATUS}")
            continue
        media = p.suffix in MEDIA_SUFFIXES
        done = media_io.complete_or_adopt(p, source=c["material"]) if media else p.exists()
        print(f"  [{'✓' if done else '·'}] {label}")
    outs = sorted(p.name for p in (pdir / "output").glob("v*") if p.is_dir())
    print(f"\n已出片：{outs or '无'}")
    used = usage.summary(pdir / "work")
    print(USAGE_LINE.format(used=used["total_tokens"], budget=used["budget"] or USAGE_UNLIMITED))


def list_projects(root: Path) -> None:
    for p in sorted(Path(root).glob("*/project.json")):
        try:
            c = schema.read_json(p)
        except schema.CorruptJSON:  # 一个项目坏了不影响列出其它项目
            c = {"name": p.parent.name, "title": LIST_CORRUPT}
        outs = sorted(x.name for x in (p.parent / "output").glob("v*"))
        print(f"{c['name']:28s} {c.get('title', ''):12s} {c.get('preset', ''):10s} {outs}")


def clean(pdir: Path, dry_run: bool, *, ok: Callable[[str], None], info: Callable[[str], None],
          die: Callable[[str], None]) -> None:
    """KI-33：删可重建的中间产物；有任务在用这个项目就拒绝（审查修复 M3）。"""
    try:
        with project_lock.exclusive(pdir):
            found = cache.items(pdir)
            for it in found:
                print(CLEAN_ITEM.format(label=it["label"], path=it["path"], mb=it["bytes"] / MB))
            if not found:
                return info(CLEAN_NOTHING)
            if not dry_run:
                ok(CLEAN_DONE.format(mb=cache.clean(pdir) / MB))
    except project_lock.Busy:
        die(CLEAN_BUSY)
