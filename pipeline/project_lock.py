# -*- coding: utf-8 -*-
"""项目级忙碌锁（审查修复 M3）：会读写项目产物的命令持共享锁，「清理缓存」要独占锁。

命令行和剪辑台起的任务（子进程里同样跑 aicut）都经过 aicut.main，所以只要有任务在用这个项目，
不论它来自哪个剪辑台实例、还是终端，清理都拿不到独占锁 → 拒绝。进程退出（含被强杀）锁自动释放。
文件系统不支持 flock 时不阻断（记 warning）：锁是保护，不能让剪辑跑不起来。

出片的「切片 → 写时间线 → 清理不再引用的切片」另持一把**独占**的出片锁（KI-89 复审）：
否则两个并发出片时，后一个的清理会删掉前一个刚切好、还没写进时间线的切片。
"""
from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Iterator

from pipeline import filelock

LOCK_FILE = ".aicut-busy.lock"
BUILD_LOCK_FILE = ".aicut-build.lock"
LOCK_MODE = 0o600
UNSUPPORTED = "项目锁不可用（%s），%s 不加锁继续"
_LOG = logging.getLogger("aicut.project_lock")


class Busy(RuntimeError):
    """这个项目正在被某个任务使用。"""


def _open(pdir: Path, name: str = LOCK_FILE) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    return os.open(Path(pdir) / name, flags, LOCK_MODE)


@contextlib.contextmanager
def _locked(pdir: Path, mode: int, name: str = LOCK_FILE) -> Iterator[None]:
    fd = _open(pdir, name)
    held = False
    try:
        try:
            filelock.flock(fd, mode)
            held = True
        except BlockingIOError as exc:
            raise Busy(str(pdir)) from exc
        except OSError as exc:
            _LOG.warning(UNSUPPORTED, exc, Path(pdir).name)
            yield
            return
        yield
    finally:
        if held:
            try:  # 显式解锁（Windows 关句柄后释放是异步的）；失败不掩盖原异常
                filelock.flock(fd, filelock.LOCK_UN)
            except OSError as exc:
                _LOG.debug("解锁失败（忽略）：%s", exc)
        os.close(fd)  # 关闭即释放


def busy(pdir: Path):
    """任务使用项目期间持有的共享锁（多个任务可同时持有；等独占的清理做完）。"""
    return _locked(pdir, filelock.LOCK_SH)


def build_section(pdir: Path, *, blocking: bool = True):
    """出片关键段的独占锁：默认等前一个出片做完；blocking=False 时拿不到立即抛 Busy。"""
    mode = filelock.LOCK_EX if blocking else filelock.LOCK_EX | filelock.LOCK_NB
    return _locked(pdir, mode, BUILD_LOCK_FILE)


def exclusive(pdir: Path):
    """清理用的独占锁；有任何任务持有共享锁时立即抛 Busy，不等待。"""
    return _locked(pdir, filelock.LOCK_EX | filelock.LOCK_NB)
