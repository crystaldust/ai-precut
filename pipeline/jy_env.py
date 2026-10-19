# -*- coding: utf-8 -*-
"""开发态剪映草稿生成用的专用 venv（pyJianYingDraft 不装进项目环境，不污染系统 Python）。

旧版 Python（<3.11）建的 venv 不认 `-P`（KI-82）：原地 `venv --clear` 用当前解释器重建再装依赖。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pipeline import pyver

JY_PACKAGE = "pyJianYingDraft"
ERR_TAIL = 300
CREATING = "首次使用：创建 {venv} 并安装 pyJianYingDraft（约 20 秒）…"
REBUILDING = "{venv} 是旧版 Python 建的（需要 3.11+），用当前 Python 重建（约 20 秒）…"


class JyEnvError(RuntimeError):
    """venv 建不起来 / 依赖装不上。"""


def _python(venv: Path) -> Path:
    return Path(venv) / "bin" / "python"


def ensure(venv: Path, *, runner=subprocess.run, base_python: str = sys.executable) -> str:
    """返回可用的 venv 解释器路径；没有或版本太旧就（重）建并安装 pyJianYingDraft。"""
    py = _python(venv)
    if py.exists():
        if pyver.supports_safe_path(str(py)):
            return str(py)
        print(f"[!] {REBUILDING.format(venv=venv)}")
    else:
        print(f"[·] {CREATING.format(venv=venv)}")
    Path(venv).parent.mkdir(parents=True, exist_ok=True)
    r = runner([base_python, "-m", "venv", "--clear", str(venv)], capture_output=True, text=True)
    if r.returncode != 0:
        raise JyEnvError(f"创建 {venv} 失败：{(r.stderr or '')[-ERR_TAIL:]}")
    r = runner([str(py), "-m", "pip", "install", "-q", JY_PACKAGE], capture_output=True, text=True)
    if r.returncode != 0:
        raise JyEnvError(f"安装 pyJianYingDraft 失败：{(r.stderr or '')[-ERR_TAIL:]}")
    print("[✓] 依赖就绪")
    return str(py)
