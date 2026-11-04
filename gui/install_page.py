# -*- coding: utf-8 -*-
"""「安装不完整」提示页：静态文件缺失（zip 没解压完整、杀毒软件隔离）时代替主页。

自包含的内联 HTML，不含脚本、不引用外部样式；文件名一律转义。
"""
from __future__ import annotations

import html

from pipeline import plat

MAX_LISTED = 10
TITLE = "安装不完整"
INTRO = "App 缺少运行所需的文件，所以没法正常打开。"
TOTAL_FMT = "共缺少 {n} 个文件（文件名供开发排查）"
MORE_FMT = "…另外还有 {m} 个"
LAST_RESORT = "还不行：把这个页面截图发给开发。"
REMEDY_WIN = (
    "关掉 App，把下载的 zip 解压到一个新文件夹。",
    "从 GitHub 下载的是两层 zip，里外两层都要右键「全部提取」；不要打开压缩包直接把文件夹拖出来。",
    "解压后仍然缺文件，请检查杀毒软件的隔离区，把被隔离的文件恢复。",
    LAST_RESORT,
)
REMEDY_MAC = (
    "关掉 App，重新解压 zip，或重新拷贝「AI粗剪.app」。",
    "仍然缺文件，请检查杀毒软件有没有把文件隔离。",
    LAST_RESORT,
)
PAGE_FMT = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{title}</title></head>'
    '<body style="font-family:-apple-system,sans-serif;padding:48px;color:#333;max-width:720px">'
    "<h2>{title}</h2><p>{intro}</p><p>{total}</p>"
    '<ul style="font-family:monospace">{files}</ul><p>怎么办：</p><ol>{steps}</ol></body></html>'
)


def _listed(names: list[str]) -> str:
    items = "".join(f"<li>{html.escape(n)}</li>" for n in names[:MAX_LISTED])
    hidden_count = len(names) - MAX_LISTED
    if hidden_count > 0:
        items += f"<li>{html.escape(MORE_FMT.format(m=hidden_count))}</li>"
    return items


def render(missing: list[str]) -> bytes:
    """安装不完整页的 UTF-8 字节；补救步骤按平台区分。"""
    remedy = REMEDY_WIN if plat.IS_WIN else REMEDY_MAC
    steps = "".join(f"<li>{html.escape(s)}</li>" for s in remedy)
    return PAGE_FMT.format(title=TITLE, intro=INTRO, total=html.escape(TOTAL_FMT.format(n=len(missing))), files=_listed(missing), steps=steps).encode("utf-8")
