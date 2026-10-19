# -*- coding: utf-8 -*-
"""剪辑台 · 视频文件发送（从 gui/server.py 拆出，KI-54）。支持 Range，浏览器才能拖进度条。"""
from __future__ import annotations

import re
from pathlib import Path

CHUNK = 65536
VIDEO_CTYPE = "video/mp4"
NOT_FOUND_MSG = "文件不存在"
_RANGE_RE = re.compile(r"bytes=([0-9]*)-([0-9]*)")  # 只认单段；多段 / 其它单位按「没有 Range」整段发
RANGE_DIGITS_MAX = 15  # 超过这么多位的数字不可能落在文件里：直接 416（也避免超长数字串 int() 报错，L14）
UNSATISFIABLE = "unsatisfiable"


def parse_range(header: str | None, size: int) -> tuple[int, int] | str | None:
    """RFC 9110 §14.1.2：None=没有或不理解（200 全量）；"unsatisfiable"=416；(start, end) 闭区间。"""
    m = _RANGE_RE.fullmatch((header or "").strip())
    if not m or not (m.group(1) or m.group(2)):
        return None
    first, last = m.group(1), m.group(2)
    if max(len(first), len(last)) > RANGE_DIGITS_MAX:
        return UNSATISFIABLE
    if not first:  # bytes=-N：最后 N 字节
        n = int(last)
        return UNSATISFIABLE if n == 0 or size == 0 else (max(0, size - n), size - 1)
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:  # 语法无效：忽略 Range
        return None
    if start >= size:
        return UNSATISFIABLE
    return start, min(end, size - 1)


def _copy(handler, path: Path, start: int, length: int) -> None:
    if handler.command == "HEAD":  # 只回头（审查修复 L11）
        return
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(CHUNK, remaining))
            if not chunk:
                break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return
            remaining -= len(chunk)


def _head(handler, code: int, length: int, extra: dict | None = None) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", VIDEO_CTYPE)
    handler.send_header("Accept-Ranges", "bytes")
    for k, v in (extra or {}).items():
        handler.send_header(k, v)
    handler.send_header("Content-Length", str(length))
    handler._security_headers()
    handler.end_headers()


def serve_file(handler, path: Path, root: Path) -> None:
    """只发 root 内的普通文件：符号链接逃逸、目录一律 404。"""
    try:
        real = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        return handler._json({"error": NOT_FOUND_MSG}, 404)
    if Path(root).resolve() not in real.parents or not real.is_file():
        return handler._json({"error": NOT_FOUND_MSG}, 404)
    size = real.stat().st_size
    rng = parse_range(handler.headers.get("Range"), size)
    if rng is None:
        _head(handler, 200, size)
        return _copy(handler, real, 0, size)
    if rng == UNSATISFIABLE:  # KI-30：起点越界 / bytes=-0 / 空文件
        return _head(handler, 416, 0, {"Content-Range": f"bytes */{size}"})
    start, end = rng
    _head(handler, 206, end - start + 1, {"Content-Range": f"bytes {start}-{end}/{size}"})
    _copy(handler, real, start, end - start + 1)
