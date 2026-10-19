# -*- coding: utf-8 -*-
"""云端客户端共用的 urllib 加固（cloud.py / llm.py）。

  * 不跟随重定向：urllib 跟随时会把 Authorization: Bearer 原样带去新地址；3xx 原样交给调用方当错误；
  * 响应体读取有上限：异常的超大响应不会撑爆内存。
"""
from __future__ import annotations

import urllib.request

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ResponseTooLarge(ValueError):
    """响应体超过 MAX_RESPONSE_BYTES。"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def open_url(req: urllib.request.Request, timeout: float):
    return OPENER.open(req, timeout=timeout)


def read_capped(resp) -> str:
    """读响应体（UTF-8，容错）；超过上限抛 ResponseTooLarge。"""
    data = resp.read(MAX_RESPONSE_BYTES + 1) if resp is not None else b""
    if len(data or b"") > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge(f"响应超过 {MAX_RESPONSE_BYTES // 1024 // 1024} MB")
    return (data or b"").decode("utf-8", "replace")
