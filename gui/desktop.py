# -*- coding: utf-8 -*-
"""剪辑台 · App 内开子窗口（KI-36 / D8）。

pywebview（cocoa）只处理用户点链接的导航，页面里的 window.open 会被直接吞掉。
桌面壳启动时注入窗口打开器；页面 POST /api/window，这里在 App 内开新窗口。
没有打开器（浏览器模式）或打开失败 → {"opened": false}，页面自己退回 window.open。
每个新窗口的地址都带自己的一次性 nonce，自己换会话 cookie（KI-88），不依赖窗口间共享 cookie。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import quote

from gui import session
from pipeline import applog

WINDOW_PAGES = {"browse": "浏览素材", "calibrate": "剪辑偏好", "confirm": "确认与提问"}
WINDOW_TITLE = "{label} · {project}"
UNKNOWN_PAGE_MSG = "不认识的页面"
PAGE_URL = "http://127.0.0.1:{port}/static/{page}.html?project={project}"
OPENER: Callable[[str, str], object] | None = None
LOG = applog.get("gui")


def set_window_opener(fn: Callable[[str, str], object] | None) -> None:
    global OPENER
    OPENER = fn


def handle_post(path: str, body: dict, resolve: Callable[[str], Path],
                port: int) -> tuple[int, dict] | None:
    if path != "/api/window":
        return None
    page, name = body.get("page"), body.get("project", "")
    if not isinstance(page, str) or page not in WINDOW_PAGES:
        return 400, {"error": UNKNOWN_PAGE_MSG}
    try:
        resolve(name)  # 项目名白名单 + 存在性（ProjectCorrupt 由 server 统一 409）
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if OPENER is None:
        return 200, {"opened": False}
    url = session.entry_url(PAGE_URL.format(port=int(port), page=page, project=quote(name, safe="")))
    try:
        OPENER(WINDOW_TITLE.format(label=WINDOW_PAGES[page], project=name), url)
    except Exception:  # noqa: BLE001 - 开不了窗口就让页面自己 window.open，不当成失败
        LOG.exception("App 内开窗口失败，页面退回 window.open")
        return 200, {"opened": False}
    return 200, {"opened": True}
