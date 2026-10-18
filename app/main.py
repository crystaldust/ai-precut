# -*- coding: utf-8 -*-
"""桌面壳：本地服务 + pywebview 窗口。

开发：uv run python app/main.py
打包：PyInstaller 以本文件为入口，内置 ffmpeg、静态资源与流水线代码。
"""
from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webview  # noqa: E402

from pipeline import proc  # noqa: E402
from gui import server  # noqa: E402


def main() -> None:
    proc.ensure_bundled_path()
    srv, url = server.serve_in_background()
    window = webview.create_window(
        "AI 粗剪", url, width=1380, height=900,
        min_size=(1080, 680), text_select=True)

    def pick_video():
        result = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("视频文件 (*.mov;*.mp4;*.m4v;*.avi)", "所有文件 (*.*)"))
        return list(result or [])

    server.set_picker(pick_video)
    try:
        webview.start()
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
