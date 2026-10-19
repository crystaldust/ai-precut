# -*- coding: utf-8 -*-
"""`aicut config`：凭证查看（掩码）/ 设置 / 删除 / 外发告知（从 aicut.py 拆出，KI-55）。

输出函数由调用方注入（ok / info / die），本模块不 import aicut，没有循环依赖。
"""
from __future__ import annotations

import sys
from typing import Callable

from pipeline import consent, secrets

KEY_EMPTY = "Key 为空，已取消"


def _show(info: Callable[[str], None]) -> None:
    st = secrets.status()
    for name, item in st.items():
        mark = "✓" if item["configured"] else "·"
        src = f"（来源 {item['source']}）" if item["source"] else ""
        print(f"[{mark}] {name:9s} {item['masked'] or '未配置'} {src}")
    if not st["mediakit"]["configured"]:
        info("设置：uv run python aicut.py config set mediakit")


def _read_key(provider: str) -> str:
    if sys.stdin.isatty():
        import getpass
        return getpass.getpass(f"粘贴 {provider} 的 Key（输入不回显）：").strip()
    return sys.stdin.readline().strip()


def run(args, *, ok: Callable[[str], None], info: Callable[[str], None],
        die: Callable[[str], None]) -> None:
    if not args.action:
        return _show(info)
    if args.action == "consent":
        print(consent.NOTICE_TITLE)
        print("\n".join(consent.NOTICE_LINES))
        consent.accept()
        return ok("已记录：你已阅读数据外发说明")
    provider = args.provider
    if args.action == "set":
        value = _read_key(provider)
        if not value:
            return die(KEY_EMPTY)
        backend = secrets.set(provider, value)
        return ok(f"已保存到 {backend}：{secrets.mask(value)}")
    if args.action == "unset":
        secrets.delete(provider)
        return ok(f"已删除 {provider}")
    die(f"未知操作：{args.action}")
