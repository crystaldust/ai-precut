# -*- coding: utf-8 -*-
"""剪辑台 · 一次性入口 nonce → 会话 cookie（KI-88）。

页面里不再放任何长期秘密：桌面壳 / 浏览器启动器打开 `/?nonce=<一次性随机串>`，
服务端兑换一次，下发 HttpOnly + SameSite=Strict 的会话 cookie 并跳回不带 nonce 的地址；
之后页面、`/api/*`、`/media/*` 都只认这个 cookie。同机其他用户 `GET /` 拿不到任何凭证。

cookie 不按端口隔离（RFC 6265），名字带端口，两个剪辑台实例互不覆盖。
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable

SECRET = secrets.token_hex(32)   # 每次启动随机；只经 Set-Cookie 下发，不进页面
NONCE_TTL_S = 300                # 浏览器冷启动可能要几十秒（D1）
MAX_PENDING = 64                 # 未兑换的 nonce 上限，超出丢最旧的
NONCE_PARAM = "nonce"
COOKIE_NAME = "aicut_session_{port}"
COOKIE_ATTRS = "Path=/; HttpOnly; SameSite=Strict"  # 会话 cookie：不设 Max-Age，关浏览器即失效

_PENDING: OrderedDict[str, float] = OrderedDict()  # nonce → 过期时刻（monotonic）
_LOCK = threading.Lock()


def issue_nonce(*, now: Callable[[], float] = time.monotonic) -> str:
    nonce = secrets.token_urlsafe(32)
    with _LOCK:
        _PENDING[nonce] = now() + NONCE_TTL_S
        while len(_PENDING) > MAX_PENDING:
            _PENDING.popitem(last=False)
    return nonce


def redeem(nonce: str | None, *, now: Callable[[], float] = time.monotonic) -> bool:
    """兑换一次：存在且未过期 → True；无论成败都作废这个 nonce。"""
    if not isinstance(nonce, str) or not nonce:
        return False
    with _LOCK:
        expires = _PENDING.pop(nonce, None)
    return expires is not None and now() <= expires


def cookie_name(port: int) -> str:
    return COOKIE_NAME.format(port=int(port))


def cookie_header(port: int) -> str:
    return f"{cookie_name(port)}={SECRET}; {COOKIE_ATTRS}"


def has_valid_cookie(raw: str | None, port: int) -> bool:
    """手工解析 Cookie 头：别的本地应用写的畸形 cookie 不能连累我们（SimpleCookie 会整串放弃）。"""
    if not raw:
        return False
    name, want = cookie_name(port), SECRET.encode()
    for part in raw.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key == name and hmac.compare_digest(value.strip().encode(), want):
            return True
    return False


def entry_url(url: str) -> str:
    """给桌面壳窗口 / 浏览器启动器用的一次性入口地址。"""
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}{NONCE_PARAM}={issue_nonce()}"
