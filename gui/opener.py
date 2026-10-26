# -*- coding: utf-8 -*-
"""剪辑台 · 调用系统「打开」（打开项目目录 / 在文件管理器中显示 / 打开剪映）的唯一入口。

对外是三个语义函数：open_path(p) / reveal(p) / open_app(app)。
Mac：`open` / `open -R` / `open -a`（命令逐字不变）；Windows：os.startfile / `explorer /select,` / os.startfile(exe)。
每次调用都有超时，超时 / 找不到命令 / 退出码非 0 都变成 OpenFailed（消息给用户看，不回显 stderr 原文）。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pipeline import applog, jy_version, plat

OPEN_TIMEOUT_S = 10
OPEN_FAILED_MSG = "没能打开：系统「打开」命令执行失败，请手动在访达或启动台里找"
OPEN_FAILED_MSG_WIN = "没能打开：系统「打开」命令执行失败，请手动在文件资源管理器或开始菜单里找"
STDERR_LOG_CHARS = 200
LOG = applog.get("gui")


class OpenFailed(RuntimeError):
    """open 没成功；消息是中文，可直接给用户看。"""


def open_failed_msg() -> str:
    return OPEN_FAILED_MSG_WIN if plat.IS_WIN else OPEN_FAILED_MSG


def _startfile(path: str) -> None:
    """Windows 的 os.startfile（测试替换点；非 Windows 上没有这个函数）。"""
    os.startfile(path)  # type: ignore[attr-defined]


def _text(err) -> str:
    return err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err or "")


def run_open(args: list[str]) -> None:
    """`open <args>`（Mac）；失败抛 OpenFailed。"""
    try:
        res = subprocess.run(["open", *args], capture_output=True, timeout=OPEN_TIMEOUT_S)
    except (subprocess.SubprocessError, OSError) as exc:  # 含超时
        LOG.warning("open 失败：%s", type(exc).__name__)
        raise OpenFailed(open_failed_msg()) from exc
    code = getattr(res, "returncode", 0)
    if code:
        err = getattr(res, "stderr", b"") or b""
        LOG.warning("open 退出码 %s：%s", code, _text(err)[:STDERR_LOG_CHARS])
        raise OpenFailed(open_failed_msg())


def _start(target) -> None:
    try:
        _startfile(str(target))
    except OSError as exc:
        LOG.warning("startfile 失败：%s", type(exc).__name__)
        raise OpenFailed(open_failed_msg()) from exc


def open_path(path: Path | str) -> None:
    """打开项目目录。Windows 上 os.startfile 会执行 / 按关联打开任何路径，所以只接受已存在的目录。"""
    if plat.IS_WIN:
        if not Path(path).is_dir():
            LOG.warning("拒绝打开：不是现存目录")
            raise OpenFailed(open_failed_msg())
        return _start(path)
    run_open([str(path)])


def reveal(path: Path | str) -> None:
    """在文件管理器里选中 path。"""
    if not plat.IS_WIN:
        return run_open(["-R", str(path)])
    cmdline = _explorer_cmdline(Path(path))
    try:  # explorer 的返回码不可靠（成功也常返回 1），只有起不来 / 超时才算失败
        subprocess.run(cmdline, capture_output=True, timeout=OPEN_TIMEOUT_S, **plat.NO_WINDOW)
    except (subprocess.SubprocessError, OSError) as exc:
        LOG.warning("explorer 失败：%s", type(exc).__name__)
        raise OpenFailed(open_failed_msg()) from exc


def _explorer_cmdline(path: Path) -> str:
    """`"<explorer>" /select,"<path>"`（单个字符串，shell=False 直接交给 CreateProcess：
    list2cmdline 会把整个 /select,… 参数一起加引号，explorer 不认）。文件不存在 → 退而打开它的上级目录。"""
    explorer = plat.explorer_exe()
    target = path if path.exists() else path.parent
    if '"' in str(target) or not target.exists():
        LOG.warning("explorer 目标不可用")
        raise OpenFailed(open_failed_msg())
    if target is path:
        return f'"{explorer}" /select,"{target}"'
    return f'"{explorer}" "{target}"'


def _is_jianying_exe(app: Path) -> bool:
    known = {os.path.normcase(str(c)) for c in jy_version.win_candidates()}
    return os.path.normcase(str(app)) in known and app.is_file()


def open_app(app: Path | str) -> None:
    """启动应用（Mac 的 .app / Windows 的 exe）。Windows 只启动已知的剪映 exe 候选路径（且必须是文件）。"""
    if plat.IS_WIN:
        if not _is_jianying_exe(Path(app)):
            LOG.warning("拒绝启动：不是已知的剪映路径")
            raise OpenFailed(open_failed_msg())
        return _start(app)
    run_open(["-a", str(app)])
