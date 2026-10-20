# -*- coding: utf-8 -*-
"""手动分镜表 shots.json 的读改写互斥、基线与备份（M14 E7 / E9 / E11）。

剪辑台是多线程服务：「保存分镜表」和「标记不可用时移除重叠镜头」都会整体重写 shots.json，
不串行的话后写的会丢掉先写的修改（丢更新）。M14 起「覆盖」发生在 `aicut select --manual=replace`
子进程里，与剪辑台进程的保存是跨进程竞争，线程锁挡不住：所有整体重写 / 删除 shots.json 的路径
都必须在 locked(pdir)（线程锁 + 项目内文件锁）内完成读-改-写。

基线（work/manual_base.json）：第一次写出 shots.json 时的 AI 选段，「你手动改了几处」与它比，
而不是与之后变化的 AI 选段比。删除 shots.json（覆盖 / 恢复为 AI 选段）时一并删基线。
"""
from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pipeline import schema, shot_diff

FILE_LOCK = ".aicut-shots.lock"
LOCK_MODE = 0o600
SHOTS_FILE = "shots.json"
SELECTED_FILE = "work/shots-selected.json"
BASE_FILE = "work/manual_base.json"
BACKUP_DIR = "work/shots_backups"
BACKUP_KEEP = 10
BUSY_TIMEOUT_S = 10.0         # 等锁最久这么久，超时抛 Busy（调用方变成 409 / 命令行提示），不无限挂着
BUSY_POLL_S = 0.05
BUSY_MSG = "分镜表正忙，请稍后再试"
SOURCE_MANUAL = "manual"
SOURCE_SELECTION = "selection"
MANUAL_MODES = ("replace", "keep")  # 重新选段时对手动分镜表的处理：覆盖 / 保留我的修改
BAD_MANUAL_MSG = "manual 只能是 replace 或 keep"
STALE_SELECTION_MSG = "分镜表刚被重新选段覆盖了，请刷新"
SHOTS_BUSY_MSG = "正在重新选段，完成后再改分镜表"
LOCK_UNSUPPORTED = "分镜表文件锁不可用（%s），%s 不加锁继续"
_LOG = logging.getLogger("aicut.shots_store")


class Busy(RuntimeError):
    """等了 BUSY_TIMEOUT_S 秒仍拿不到分镜表锁（另一个进程 / 线程占着）。"""


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def thread_lock(pdir: Path) -> threading.Lock:
    """每个项目一把线程锁（按解析后的路径），不同项目的保存互不阻塞。"""
    key = str(Path(pdir).resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


def _flock_bounded(fd: int, pdir: Path) -> None:
    """flock(LOCK_NB) + 有限重试；文件系统不支持 flock 时只记 warning 放行。"""
    deadline = time.monotonic() + BUSY_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise Busy(BUSY_MSG) from None
            time.sleep(BUSY_POLL_S)
        except OSError as exc:
            _LOG.warning(LOCK_UNSUPPORTED, exc, Path(pdir).name)
            return


@contextlib.contextmanager
def locked(pdir: Path) -> Iterator[None]:
    """先拿本项目的线程锁再拿文件锁（避免同进程两线程都去 flock），释放顺序相反。

    两把锁都有 BUSY_TIMEOUT_S 的等待上限，超时抛 Busy：跨进程的另一方只是一次删文件 / 写文件，
    正常很快；卡住时调用方要能给出明确提示而不是挂死。
    """
    lock = thread_lock(pdir)
    if not lock.acquire(timeout=BUSY_TIMEOUT_S):
        raise Busy(BUSY_MSG)
    try:
        fd = os.open(Path(pdir) / FILE_LOCK, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), LOCK_MODE)
        try:
            _flock_bounded(fd, pdir)
            yield
        finally:
            os.close(fd)  # 关闭即释放
    finally:
        lock.release()


def selection_replaced(pdir: Path, loaded_digest: object) -> bool:
    """页面读到的 AI 选段指纹与现在不同，且手动表已经不在了（= 期间被「覆盖」过）→ 这次保存会存进过期的页面。

    只在 locked 内调用。没带指纹（旧客户端）或手动表还在 → 不拦（手动表就是权威）。
    """
    if not isinstance(loaded_digest, str) or (Path(pdir) / SHOTS_FILE).exists():
        return False
    from pipeline import fingerprints  # 局部导入：fingerprints 也依赖本模块（读当前分镜表）
    return fingerprints.file_digest(Path(pdir) / SELECTED_FILE) != loaded_digest


def check_manual(value: object) -> str:
    """白名单：replace | keep；其它抛 ValueError。"""
    if not isinstance(value, str) or value not in MANUAL_MODES:
        raise ValueError(BAD_MANUAL_MSG)
    return value


def _read(path: Path) -> list[dict]:
    return schema.read_shots(path)


def current(pdir: Path) -> tuple[list[dict], str | None]:
    """当前分镜表与来源：手动表优先，其次 AI 选段，都没有 → ([], None)。读不懂抛 CorruptJSON（不当没有）。"""
    pdir = Path(pdir)
    if (pdir / SHOTS_FILE).exists():
        return _read(pdir / SHOTS_FILE), SOURCE_MANUAL
    if (pdir / SELECTED_FILE).exists():
        return _read(pdir / SELECTED_FILE), SOURCE_SELECTION
    return [], None


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ai_shots(pdir: Path) -> list[dict]:
    """当前 AI 选段；没有 / 读不懂 → []（基线缺失不能挡住用户保存）。"""
    try:
        return _read(Path(pdir) / SELECTED_FILE) if (Path(pdir) / SELECTED_FILE).exists() else []
    except schema.CorruptJSON as exc:
        _LOG.warning("AI 选段读不出，基线按空表记：%s", type(exc).__name__)
        return []


def write_manual(pdir: Path, shots: list[dict], meta: dict) -> None:
    """写 shots.json（调用方已持 locked）。第一次写出时先把当时的 AI 选段存为基线。"""
    pdir = Path(pdir)
    if not (pdir / SHOTS_FILE).exists():
        schema.write_json(pdir / BASE_FILE, {"shots": _ai_shots(pdir), "at": _utc_stamp()})
    schema.write_json(pdir / SHOTS_FILE, {**meta, "shots": shots})


def _seq_of(path: Path) -> int:
    m = re.match(r"(\d+)-", path.name)
    return int(m.group(1)) if m else 0


def _fsync_path(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(pdir: Path, reason: str) -> Path | None:
    """把现有 shots.json 原样拷到 work/shots_backups/<序号>-<UTC 时间>-<原因>.json 并落盘。

    序号单调递增（调用方已持 locked），只留序号最大的 BACKUP_KEEP 份：不靠时间字符串排序，时钟回拨也不会删错。
    """
    pdir = Path(pdir)
    src = pdir / SHOTS_FILE
    if not src.exists():
        return None
    folder = pdir / BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    existing = list(folder.glob("*.json"))
    seq = max((_seq_of(p) for p in existing), default=0) + 1
    dest = folder / f"{seq:06d}-{_utc_stamp()}-{reason}.json"
    shutil.copyfile(src, dest)
    _fsync_path(dest)
    _fsync_path(folder)
    for old in sorted(existing + [dest], key=_seq_of)[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return dest


def drop_manual(pdir: Path, reason: str) -> Path | None:
    """先备份再删 shots.json 与基线（调用方已持 locked）；没有 shots.json → None、什么都不做。"""
    pdir = Path(pdir)
    saved = backup(pdir, reason)
    if saved is None:
        return None
    (pdir / SHOTS_FILE).unlink(missing_ok=True)
    (pdir / BASE_FILE).unlink(missing_ok=True)
    return saved


def manual_changes(pdir: Path, limit: int = shot_diff.DESCRIBE_LIMIT) -> dict:
    """{"edited", "count", "changes", "more"}：手动表与基线（没有则与当前 AI 选段）逐镜比对。

    只用于显示，永远不抛：读不出 → edited=False 并带 error。0 处改动不算改过（⚑Q5）。
    """
    pdir = Path(pdir)
    none = {"edited": False, "count": 0, "changes": [], "more": 0}
    if not (pdir / SHOTS_FILE).exists():
        return none
    try:
        manual = _read(pdir / SHOTS_FILE)
        base_raw = schema.read_json(pdir / BASE_FILE, default=None)
        base = (schema.clean_shots(base_raw.get("shots")) if isinstance(base_raw, dict)
                else _ai_shots(pdir))
    except (schema.CorruptJSON, ValueError, OSError) as exc:
        _LOG.warning("手动改动清单读不出：%s", type(exc).__name__)
        return {**none, "error": str(exc)}
    d = shot_diff.diff(base, manual)
    lines, more = shot_diff.describe(d, manual, limit)
    n = shot_diff.count(d)
    return {"edited": n > 0, "count": n, "changes": lines, "more": more}
