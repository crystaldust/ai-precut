# -*- coding: utf-8 -*-
"""App 版本号（KI-37）：短版本号读 pyproject.toml，构建号取 AICUT_BUILD_NUMBER 或 git 提交数。

拿不到构建号就让构建失败（不能静默打成 1：macOS 靠 CFBundleVersion 判断新旧）。
注意 packaging/ 与 PyPI 的 packaging 包同名：spec / 测试按文件路径加载本文件，不要 import packaging.version。
"""
from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

BUILD_ENV = "AICUT_BUILD_NUMBER"
GIT_TIMEOUT_S = 30
NO_BUILD_NUMBER = ("拿不到构建号：设置环境变量 {env}（正整数），或在 git 仓库里构建（{detail}）")


def short_version(root: Path) -> str:
    data = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _positive(raw: str) -> str | None:
    """只认 ASCII 数字（str.isdigit 会放过「²」「١٢」，L20）。"""
    return raw if re.fullmatch(r"[0-9]+", raw or "") and int(raw) > 0 else None


def build_number(root: Path, *, env=os.environ, run=subprocess.run) -> str:
    """AICUT_BUILD_NUMBER（必须是正整数）→ 否则 git rev-list --count HEAD → 都不行抛 RuntimeError。"""
    if BUILD_ENV in env:
        if (value := _positive(env[BUILD_ENV])) is None:
            raise RuntimeError(NO_BUILD_NUMBER.format(env=BUILD_ENV, detail=f"{BUILD_ENV} 不是正整数"))
        return value
    try:
        r = run(["git", "rev-list", "--count", "HEAD"], cwd=str(root), capture_output=True,
                text=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(NO_BUILD_NUMBER.format(env=BUILD_ENV, detail=exc)) from exc
    if r.returncode != 0 or (value := _positive((r.stdout or "").strip())) is None:
        raise RuntimeError(NO_BUILD_NUMBER.format(env=BUILD_ENV, detail=(r.stderr or "").strip()[:200]))
    return value
