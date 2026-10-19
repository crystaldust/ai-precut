# -*- coding: utf-8 -*-
"""开发态剪映草稿生成用的专用 venv（pyJianYingDraft 不装进项目环境，不污染系统 Python）。

旧版 Python（<3.11）建的 venv 不认 `-P`（KI-82）：原地 `venv --clear` 用当前解释器重建再装依赖。
版本锁定与 uv.lock 一致（KI-34）：venv 里的版本不对就重装；当前解释器（uv 环境）已装就直接用它。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from pipeline import pyver

JY_PACKAGE = "pyJianYingDraft"
JY_VERSION = "0.3.1"                       # 与 uv.lock 一致（tests/test_jy_env 守着）
JY_PIN = f"{JY_PACKAGE}=={JY_VERSION}"
VERSION_PROBE = f"import importlib.metadata as m; print(m.version({JY_PACKAGE!r}))"
VERSION_PROBE_TIMEOUT_S = 30
WRONG_VERSION = "{venv} 里的 pyJianYingDraft 是 {have}，按锁定版本 {want} 重装…"
ERR_TAIL = 300
CREATING = "首次使用：创建 {venv} 并安装 pyJianYingDraft（约 20 秒）…"
REBUILDING = "{venv} 是旧版 Python 建的（需要 3.11+），用当前 Python 重建（约 20 秒）…"


class JyEnvError(RuntimeError):
    """venv 建不起来 / 依赖装不上。"""


def _python(venv: Path) -> Path:
    return Path(venv) / "bin" / "python"


def available_here() -> bool:
    """当前解释器能不能直接 import pyJianYingDraft（uv 环境里本来就装了）。"""
    return importlib.util.find_spec(JY_PACKAGE) is not None


def _installed_version(py: Path, runner) -> str:
    try:
        r = runner([str(py), "-c", VERSION_PROBE], capture_output=True, text=True,
                   timeout=VERSION_PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _pip_install(py: Path, runner) -> None:
    r = runner([str(py), "-m", "pip", "install", "-q", JY_PIN], capture_output=True, text=True)
    if r.returncode != 0:
        raise JyEnvError(f"安装 pyJianYingDraft 失败：{(r.stderr or '')[-ERR_TAIL:]}")


def ensure(venv: Path, *, runner=subprocess.run, base_python: str = sys.executable) -> str:
    """返回可用的 venv 解释器路径；没有或 Python 太旧就（重）建，版本不对就按锁定版本重装。"""
    py = _python(venv)
    if py.exists():
        if pyver.supports_safe_path(str(py)):
            if (have := _installed_version(py, runner)) == JY_VERSION:
                return str(py)
            print(f"[!] {WRONG_VERSION.format(venv=venv, have=have or '未知', want=JY_VERSION)}")
            _pip_install(py, runner)
            return str(py)
        print(f"[!] {REBUILDING.format(venv=venv)}")
    else:
        print(f"[·] {CREATING.format(venv=venv)}")
    Path(venv).parent.mkdir(parents=True, exist_ok=True)
    r = runner([base_python, "-m", "venv", "--clear", str(venv)], capture_output=True, text=True)
    if r.returncode != 0:
        raise JyEnvError(f"创建 {venv} 失败：{(r.stderr or '')[-ERR_TAIL:]}")
    _pip_install(py, runner)
    print("[✓] 依赖就绪")
    return str(py)
