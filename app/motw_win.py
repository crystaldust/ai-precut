# -*- coding: utf-8 -*-
"""Windows：处理「从网页下载的 zip」带来的下载标记（Mark of the Web）。

WHY：浏览器 / 网盘下载的 zip 用资源管理器「全部提取」后，每个文件都带 NTFS 备用数据流
`<文件>:Zone.Identifier`。.NET Framework 拒绝加载带标记的 `Python.Runtime.dll`，
pywebview 随后退回 coreclr（未安装）并抛错，窗口打不开。
做法：启动时把包目录里 dll / exe / pyd 的标记流删掉；仍失败时弹出中文说明，而不是 PyInstaller 的英文报错框。
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

from pipeline import applog

_log = applog.get("motw")

_BINARY_SUFFIXES = frozenset({".dll", ".exe", ".pyd"})
_STREAM = ":Zone.Identifier"
_CLR_MARKERS = ("python.runtime", "you must have pythonnet installed")
_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT

_MB_OK = 0x0
_MB_ICONERROR = 0x10
_MB_SETFOREGROUND = 0x10000
_BOX_TITLE = "AI 粗剪"
_BOX_TEXT = (
    "App 的窗口组件（.NET）加载失败。\n\n"
    "可能的原因和办法：\n"
    "1. 从网页下载的 zip 被 Windows 锁定：删掉解压出来的 ai-cut 文件夹（项目在「文档\\AI粗剪」，不会丢），"
    "右键 zip →「属性」→ 勾选「解除锁定」→「确定」，再「全部提取」。\n"
    "2. 电脑缺 .NET Framework 4.7.2 或更高版本：到 https://dotnet.microsoft.com/download/dotnet-framework 安装。\n"
    "3. 杀毒软件拦截：查看隔离区，恢复 ai-cut 文件夹里被隔离的文件。\n\n"
    "日志位置：%LOCALAPPDATA%\\剪辑台\\logs"
)


def _is_reparse_point(path: str) -> bool:
    """联接 / 符号链接（FILE_ATTRIBUTE_REPARSE_POINT）。读不到属性时按「是」处理，宁可跳过。"""
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return True


def _candidates(exe_dir: Path, bundle_dir: Path):
    """要处理的文件：exe 所在目录的顶层文件 + 资源目录（_internal）递归；跳过联接 / 符号链接。"""
    for entry in os.listdir(exe_dir):
        path = os.path.join(exe_dir, entry)
        if os.path.isfile(path) and not _is_reparse_point(path):
            yield path
    for dirpath, dirs, files in os.walk(bundle_dir):
        dirs[:] = [d for d in dirs if not _is_reparse_point(os.path.join(dirpath, d))]
        for name in files:
            path = os.path.join(dirpath, name)
            if not _is_reparse_point(path):
                yield path


def strip_download_marks(exe_dir: Path | None = None, bundle_dir: Path | None = None, *,
                         remove: Callable[[str], None] = os.remove) -> int:
    """删掉 dll / exe / pyd 的下载标记，返回清掉的个数。非 Windows 打包版返回 0；不抛异常。

    范围：exe 所在目录的顶层文件（不递归，用户可能把 exe 放在下载 / 桌面文件夹里），
    加上资源目录（默认 sys._MEIPASS，否则 exe 目录下的 _internal）的全部子树。
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return 0
    cleared = failed = 0
    try:
        exe_dir = exe_dir if exe_dir is not None else Path(sys.executable).resolve().parent
        bundle_dir = bundle_dir if bundle_dir is not None else Path(getattr(sys, "_MEIPASS", exe_dir / "_internal"))
        for path in _candidates(exe_dir, bundle_dir):
            if os.path.splitext(path)[1].lower() not in _BINARY_SUFFIXES:
                continue
            try:
                remove(path + _STREAM)
            except FileNotFoundError:
                continue  # 没有标记：正常情况
            except OSError as exc:
                failed += 1
                if failed == 1:
                    _log.warning("清除下载标记失败：%s（%s）", path, exc)
                continue
            cleared += 1
    except Exception:  # 只是预防措施：任何意外都不能挡住启动
        _log.warning("清除下载标记时出错", exc_info=True)
    if failed > 1:
        _log.warning("另有 %d 个文件清除失败", failed - 1)
    if cleared:
        _log.info("已清除 %d 个文件的下载标记", cleared)
    return cleared


def is_clr_load_error(exc: BaseException) -> bool:
    """像不像 pythonnet / .NET 加载失败（含 pywebview 把 ImportError 包成的 WebViewException）。"""
    text = str(exc).lower()
    return any(marker in text for marker in _CLR_MARKERS)


def _native_message_box(title: str, text: str) -> None:
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, title, _MB_OK | _MB_ICONERROR | _MB_SETFOREGROUND)  # type: ignore[attr-defined]


def explain_load_failure(exc: BaseException, *, message_box: Callable[[str, str], None] | None = None) -> None:
    """仅 Windows：记日志并弹中文说明框。弹框本身失败也不抛。"""
    if sys.platform != "win32":
        return
    _log.error("窗口组件（.NET / pythonnet）加载失败", exc_info=exc)
    try:
        (message_box or _native_message_box)(_BOX_TITLE, _BOX_TEXT)
    except Exception:
        _log.warning("弹出说明框失败", exc_info=True)
