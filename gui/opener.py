# -*- coding: utf-8 -*-
"""剪辑台 · 调用系统 `open`（打开项目目录 / 在访达中显示 / 打开剪映）的唯一入口。

每次调用都有超时，超时 / 找不到命令 / 退出码非 0 都变成 OpenFailed（消息给用户看，不回显 stderr 原文）。
"""
from __future__ import annotations

import subprocess

from pipeline import applog

OPEN_TIMEOUT_S = 10
OPEN_FAILED_MSG = "没能打开：系统「打开」命令执行失败，请手动在访达或启动台里找"
STDERR_LOG_CHARS = 200
LOG = applog.get("gui")


class OpenFailed(RuntimeError):
    """open 没成功；消息是中文，可直接给用户看。"""


def run_open(args: list[str]) -> None:
    """`open <args>`；失败抛 OpenFailed。"""
    try:
        res = subprocess.run(["open", *args], capture_output=True, timeout=OPEN_TIMEOUT_S)
    except (subprocess.SubprocessError, OSError) as exc:  # 含超时
        LOG.warning("open 失败：%s", type(exc).__name__)
        raise OpenFailed(OPEN_FAILED_MSG) from exc
    code = getattr(res, "returncode", 0)
    if code:
        err = getattr(res, "stderr", b"") or b""
        LOG.warning("open 退出码 %s：%s", code, err.decode("utf-8", "replace")[:STDERR_LOG_CHARS])
        raise OpenFailed(OPEN_FAILED_MSG)
