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

from pipeline.pyver import require_supported_python  # noqa: E402
require_supported_python()  # 旧解释器在这里就给出中文说明
from pipeline import applog, proc  # noqa: E402

# 打包版的任务子进程是 App 带标记重启自己（GL-17）：必须在 import webview 之前分发，
# 否则会初始化 Cocoa、多出一个 Dock 图标
if (_code := proc.dispatch(sys.argv)) is not None:
    sys.exit(_code)

import webview  # noqa: E402

from gui import jobs, server  # noqa: E402


def main() -> None:
    applog.setup("app")  # 第一件事：窗口化 App 没有终端，之后的一切都要能在日志里找到
    proc.ensure_bundled_path()
    srv, url = server.serve_in_background()
    window = webview.create_window(  # KI-88：一次性入口地址，服务端换成 HttpOnly 会话 cookie
        "AI 粗剪", server.entry_url(url), width=1380, height=900,
        min_size=(1080, 680), text_select=True)

    def pick_video():
        result = window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("视频文件 (*.mov;*.mp4;*.m4v;*.avi)", "所有文件 (*.*)"))
        return list(result or [])

    server.set_picker(pick_video)
    # KI-36：页面里的 window.open 在 pywebview 里无效，「浏览素材」等子页面由这里开新窗口
    server.set_window_opener(lambda title, url: webview.create_window(
        title, url, width=1280, height=860, min_size=(960, 600), text_select=True))
    server.report_stale_job()
    try:
        # KI-88：private_mode=True 时 pywebview（cocoa）每建一个窗口都清空共享的 WebKit 数据，
        # 开子窗口会把主窗口的会话 cookie 一起清掉；会话 cookie 不落盘、每次启动都换值
        webview.start(private_mode=False)
    finally:
        jobs.shutdown_all()  # 关窗口 = 停掉后台任务，不留孤儿进程继续计费
        srv.shutdown()


if __name__ == "__main__":
    main()
