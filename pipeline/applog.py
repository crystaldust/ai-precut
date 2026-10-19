# -*- coding: utf-8 -*-
"""日志落盘：~/Library/Logs/剪辑台/（PRD FR-13，GL-19）。

  * 标准库 logging + RotatingFileHandler（5 MB × 5 份），UTF-8；目录可用 AI_CUT_LOG_DIR 覆盖（测试必设）；
  * GUI 进程写 app.log，命令行进程写 cli.log —— RotatingFileHandler 不支持多进程写同一文件；
  * RedactFilter：已登记的密钥值 → secrets.mask()；Bearer 令牌、sk- 令牌、URL 查询串（预签名）一律打码；
  * 未捕获异常（主线程 / 子线程）记 ERROR 带堆栈；
  * stage()：阶段耗时写 work/timings.json，诊断包会带上。
目录不可写时退回 NullHandler，绝不因为日志让 App 起不来。
"""
from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pipeline import schema, secrets

ROOT_LOGGER = "aicut"
LOG_DIR_ENV = "AI_CUT_LOG_DIR"
APP_LOG_DIRNAME = "剪辑台"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5
MIN_SECRET_LEN = 8
TIMINGS_FILE = "timings.json"
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"
CLI_LOG_KEEP = 20          # 命令行进程每次运行一个文件（多进程不共写一个轮转文件），只留最近这么多个
DIR_MODE, FILE_MODE = 0o700, 0o600
_PATTERNS = (
    (re.compile(r"\b(Bearer|Basic)(\s+)[A-Za-z0-9._~+/=\-]+", re.I), r"\1\2****"),
    (re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*", re.I), r"\1?…"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}", re.I), "sk-****"),       # 含 sk-proj-…
    (re.compile(r"\b(AK(?:LT|TP))[A-Za-z0-9+/=_\-]{8,}"), r"\1****"),  # 火山引擎 / MediaKit Key
)
# 绝对路径（含 ~/）只留最后一段文件名；URL（前面是 :/）与相对路径不动
_ABS_PATH = re.compile(
    r"(?<![\w.:/~\\])~?/(?:[^\s/'\"<>|:;，；：、（）()\[\]]+/)+([^\s/'\"<>|:;，；：、（）()\[\]]+)")
_SECRETS: set[str] = set()
_LOCK = threading.Lock()
_SETUP_LOCK = threading.Lock()
_ORIG_SYS_HOOK = sys.excepthook
_ORIG_THREAD_HOOK = threading.excepthook
_STATE: dict = {"file": None, "saved_hooks": None}  # saved_hooks：reset 时原样还原
SKIP_MAX_S = 1.0  # 比上次成功耗时短、且不到 1 秒的成功运行视为「已完成、跳过」，不覆盖已记录的时长

# setup() 之前（或日志目录不可写时）的记录既不落盘也不走 logging.lastResort（它不脱敏、直接打到 stderr）
logging.getLogger(ROOT_LOGGER).addHandler(logging.NullHandler())
logging.getLogger(ROOT_LOGGER).propagate = False


def log_dir() -> Path:
    """日志目录（不创建）。"""
    if custom := os.environ.get(LOG_DIR_ENV):
        return Path(custom).expanduser()
    return Path.home() / "Library" / "Logs" / APP_LOG_DIRNAME


def current_log_file() -> Path | None:
    """本进程正在写的日志文件；没装或退回 NullHandler 时为 None。"""
    return _STATE["file"]


def register_secret(value: str | None) -> None:
    """客户端拿到 Key 时登记；之后任何日志里出现原文都换成掩码。"""
    if value and len(value) >= MIN_SECRET_LEN:
        with _LOCK:
            _SECRETS.add(value)


def register_known_secrets() -> None:
    """GUI 进程：登记不需要钥匙串授权就能拿到的 Key（环境变量 / 凭证文件），不为脱敏去弹钥匙串。"""
    for provider in secrets.PROVIDERS:
        try:
            register_secret(secrets.peek(provider))
        except Exception:  # noqa: BLE001 - 脱敏辅助，不能影响主流程
            continue


def strip_paths(text: str) -> str:
    """绝对路径 → 文件名（尽力而为：含空格的路径只能截掉空格前那段）。"""
    return _ABS_PATH.sub(r"\1", text)


def redact(text: str) -> str:
    with _LOCK:
        known = sorted(_SECRETS, key=len, reverse=True)
    for value in known:
        text = text.replace(value, secrets.mask(value))
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    """先合并 %s 参数再脱敏（否则参数里的 Key 漏网），异常堆栈同样脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - 格式串与参数不匹配也不能把异常抛回业务代码
            message = f"{record.msg} {record.args!r}"
        record.msg = redact(str(message))
        record.args = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def get(child: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{child}")


def _ours(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, "_aicut", False)]


def _private_open(self) -> object:
    """日志文件一创建就是 0600（不经过默认权限）；已有文件也收紧。"""
    fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE)
    os.fchmod(fd, FILE_MODE)
    return os.fdopen(fd, "a", encoding=self.encoding, errors=self.errors)


class _PrivateRotatingHandler(logging.handlers.RotatingFileHandler):
    _open = _private_open


class _PrivateFileHandler(logging.FileHandler):
    _open = _private_open


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:  # 别的进程刚删掉
        return 0.0


def _prune_cli_logs(d: Path) -> None:
    """多个命令行进程可能同时清理：单个文件删不掉 / 已不存在都忽略，绝不因此关掉日志。"""
    olds = sorted(d.glob("cli-*.log"), key=_mtime, reverse=True)
    for old in olds[CLI_LOG_KEEP - 1:]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            continue


def _file_handler(d: Path, name: str, max_bytes: int, backups: int) -> tuple[logging.Handler, Path]:
    if name == "cli":  # 可能同时有多个命令行进程：各写各的文件，不共用一个轮转文件
        _prune_cli_logs(d)
        path = d / f"cli-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
        return _PrivateFileHandler(path, encoding="utf-8"), path
    path = d / f"{name}.log"
    return _PrivateRotatingHandler(path, maxBytes=max_bytes, backupCount=backups,
                                   encoding="utf-8"), path


def _make_handler(name: str, max_bytes: int, backups: int) -> logging.Handler:
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, DIR_MODE)
        handler, path = _file_handler(d, name, max_bytes, backups)
        _STATE["file"] = path
    except OSError:
        handler = logging.NullHandler()  # 只读 home 等：不记日志也要能用
        _STATE["file"] = None
    handler._aicut = True  # type: ignore[attr-defined]
    handler.addFilter(RedactFilter())
    handler.setFormatter(logging.Formatter(FORMAT))
    return handler


def _sys_hook(exc_type, exc, tb) -> None:
    if not issubclass(exc_type, KeyboardInterrupt):
        logging.getLogger(ROOT_LOGGER).error("未捕获异常", exc_info=(exc_type, exc, tb))
    _ORIG_SYS_HOOK(exc_type, exc, tb)


def _thread_hook(args) -> None:
    if args.exc_type is not SystemExit:
        name = getattr(args.thread, "name", "?")
        logging.getLogger(ROOT_LOGGER).error(
            "线程 %s 未捕获异常", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    _ORIG_THREAD_HOOK(args)


def _install_hooks() -> None:
    global _ORIG_SYS_HOOK, _ORIG_THREAD_HOOK
    if _STATE["saved_hooks"] is not None:
        return
    _STATE["saved_hooks"] = (sys.excepthook, threading.excepthook)
    _ORIG_SYS_HOOK, _ORIG_THREAD_HOOK = _STATE["saved_hooks"]  # 记完日志后交还原钩子
    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def setup(name: str = "app", *, max_bytes: int = MAX_BYTES,
          backups: int = BACKUPS) -> logging.Logger:
    """装文件日志 + 异常钩子；重复调用是空操作。不在这里读 Key（钥匙串会弹窗）。"""
    logger = logging.getLogger(ROOT_LOGGER)
    with _SETUP_LOCK:
        if _ours(logger):
            return logger
        logger.addHandler(_make_handler(name, max_bytes, backups))
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _install_hooks()
    logger.info("启动 pid=%s frozen=%s python=%s", os.getpid(),
                bool(getattr(sys, "frozen", False)), sys.version.split()[0])
    return logger


def reset_for_tests() -> None:
    """卸掉本模块装的 handler、清空已登记密钥、还原异常钩子。"""
    logger = logging.getLogger(ROOT_LOGGER)
    for h in _ours(logger):
        logger.removeHandler(h)
        h.close()
    with _LOCK:
        _SECRETS.clear()
    saved = _STATE["saved_hooks"]
    if saved is not None:
        if sys.excepthook is _sys_hook:
            sys.excepthook = saved[0]
        if threading.excepthook is _thread_hook:
            threading.excepthook = saved[1]
    _STATE.update(file=None, saved_hooks=None)


def _record_timing(workdir: Path, key: str, entry: dict) -> None:
    path = Path(workdir) / TIMINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("timings.json 不是对象")
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        get("stage").warning("timings.json 损坏，重建：%s", exc)
        data = {}
    prev = data.get(key)
    if (entry["ok"] and isinstance(prev, dict) and prev.get("ok") is True
            and isinstance(prev.get("seconds"), (int, float))
            and entry["seconds"] < min(SKIP_MAX_S, prev["seconds"])):
        entry = {**prev, "last_skipped": entry["started"]}  # 已完成的步骤被跳过：保留真实耗时
    try:
        schema.write_json(path, {**data, key: entry})
    except OSError as exc:
        get("stage").warning("记录阶段耗时失败：%s", exc)


@contextlib.contextmanager
def stage(workdir: Path, key: str) -> Iterator[None]:
    """计时一个流水线阶段；正常结束 ok=True，任何异常（含 die() 的 SystemExit）ok=False 并继续抛。"""
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    ok = False
    try:
        yield
        ok = True
    finally:
        secs = round(time.monotonic() - t0, 2)
        _record_timing(workdir, key, {"started": started, "seconds": float(secs), "ok": ok})
        get("stage").info("阶段 %s %s %.1fs", key, "完成" if ok else "失败", secs)
