# -*- coding: utf-8 -*-
"""Python 版本门槛（审查修复 1 / KI-82）：项目要求 ≥3.11（`-P`、tomllib 等）。

本文件要能被旧解释器（如 macOS 自带 3.9）正常导入并给出中文提示，所以只用 3.6+ 的语法和标准库。
"""
from __future__ import annotations

import subprocess
import sys

# 与 pipeline.plat.NO_WINDOW 同义；本文件要能被旧解释器导入，不 import plat
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
MIN_PYTHON = (3, 11)
TOO_OLD = ("AI 粗剪需要 Python {need} 或更新版本，当前是 {found}（{exe}）。\n"
           "请在仓库根用 `uv run python …` 运行（uv 会准备好合适的 Python），或安装 Python {need}+。")
PROBE = "import sys; print(sys.version_info[:2] >= (3, 11))"   # 与 MIN_PYTHON 一致
PROBE_TIMEOUT_S = 15


def _fmt(v) -> str:
    return ".".join(str(x) for x in tuple(v)[:3])


def require_supported_python(version_info=None, executable: str | None = None) -> None:
    """入口最先调用：解释器太旧就带着中文说明退出（退出码 1），而不是在后面某处语法 / 参数报错。"""
    v = tuple(version_info or sys.version_info)
    if v[:2] < MIN_PYTHON:
        sys.exit(TOO_OLD.format(need=_fmt(MIN_PYTHON), found=_fmt(v),
                                exe=executable or sys.executable))


def supports_safe_path(python: str, runner=subprocess.run) -> bool:
    """该解释器认不认 `-P`（3.11+）。当前解释器直接看版本；别的解释器（如 ~/.aicut/venv）跑一下探针。"""
    if python == sys.executable:
        return sys.version_info[:2] >= MIN_PYTHON
    try:
        r = runner([python, "-c", PROBE], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=PROBE_TIMEOUT_S, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and (r.stdout or "").strip() == "True"
