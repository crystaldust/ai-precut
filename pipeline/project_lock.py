# -*- coding: utf-8 -*-
"""项目级忙碌锁（审查修复 M3）：会读写项目产物的命令持共享锁，「清理缓存」要独占锁。

命令行和剪辑台起的任务（子进程里同样跑 aicut）都经过 aicut.main，所以只要有任务在用这个项目，
不论它来自哪个剪辑台实例、还是终端，清理都拿不到独占锁 → 拒绝。进程退出（含被强杀）锁自动释放。
文件系统不支持 flock 时不阻断（记 warning）：锁是保护，不能让剪辑跑不起来。
"""
from __future__ import annotations

import contextlib
import fcntl
import logging
import os
from pathlib import Path
from typing import Iterator

LOCK_FILE = ".aicut-busy.lock"
LOCK_MODE = 0o600
UNSUPPORTED = "项目锁不可用（%s），%s 不加锁继续"
_LOG = logging.getLogger("aicut.project_lock")


class Busy(RuntimeError):
    """这个项目正在被某个任务使用。"""


def _open(pdir: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    return os.open(Path(pdir) / LOCK_FILE, flags, LOCK_MODE)


@contextlib.contextmanager
def _locked(pdir: Path, mode: int) -> Iterator[None]:
    fd = _open(pdir)
    try:
        try:
            fcntl.flock(fd, mode)
        except BlockingIOError as exc:
            raise Busy(str(pdir)) from exc
        except OSError as exc:
            _LOG.warning(UNSUPPORTED, exc, Path(pdir).name)
            yield
            return
        yield
    finally:
        os.close(fd)  # 关闭即释放


def busy(pdir: Path):
    """任务使用项目期间持有的共享锁（多个任务可同时持有；等独占的清理做完）。"""
    return _locked(pdir, fcntl.LOCK_SH)


def exclusive(pdir: Path):
    """清理用的独占锁；有任何任务持有共享锁时立即抛 Busy，不等待。"""
    return _locked(pdir, fcntl.LOCK_EX | fcntl.LOCK_NB)
