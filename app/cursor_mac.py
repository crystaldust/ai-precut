# -*- coding: utf-8 -*-
"""macOS：让 WKWebView 处理完按键后不再把鼠标指针藏起来。

WHY：WebKit 在 UI 进程的 WebViewImpl::doneWithKeyEvent 里，只要页面处理了某个 keydown，
就会调用 [NSCursor setHiddenUntilMouseMoves:YES]。剪辑员按空格播放/暂停时指针随之消失，
而指针正是他们在时间轴上的参照点。做法：启动时用 PyObjC category 把这个类方法换成空操作。

取舍：作用于整个进程（WebKit 调用点没有别的开关），所以在输入框里打字时指针同样不再隐藏。
"""
from __future__ import annotations

import sys

from pipeline import applog

_log = applog.get("cursor")
_installed = False  # PyObjC 不允许同名 category 类重复定义，用模块级标志保证幂等


def keep_cursor_visible() -> bool:
    """装上空操作；成功（含已装过）返回 True。非 macOS 或没有 PyObjC 时什么都不做并返回 False。"""
    global _installed
    if sys.platform != "darwin":
        return False
    if _installed:
        return True
    try:
        import AppKit
        import objc
    except ImportError:
        _log.warning("PyObjC 不可用，指针仍会在按键后被 WebKit 隐藏", exc_info=True)
        return False

    try:
        class NSCursor(objc.Category(AppKit.NSCursor)):  # PyObjC 要求 category 类与 ObjC 类同名
            @classmethod
            def setHiddenUntilMouseMoves_(cls, flag):
                pass
    except Exception:  # 只是体验优化：装不上（PyObjC 版本差异等）也不能挡住启动
        _log.warning("替换 NSCursor.setHiddenUntilMouseMoves: 失败，指针仍会在按键后隐藏", exc_info=True)
        return False

    _installed = True
    return True
