# -*- coding: utf-8 -*-
"""项目配置（project.json）的 schema 版本与迁移。

规则：
  * 只升不降：读到的版本高于当前，直接报错，避免"旧程序写坏新数据"；
  * 迁移是纯函数：输入旧 dict，输出新 dict + 变更说明，不碰磁盘；
  * 写盘永远是原子替换，schema_version 自动补齐。
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import glob
import json
import logging
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

CURRENT_SCHEMA = 2
# 中间产物（segments_text / segments_scored / selection / timeline）的格式版本（KI-37）。
# 只打标、不迁移：缺这个字段的旧文件按版本 0 照常读。
ARTIFACT_SCHEMA = 1


class SchemaTooNew(Exception):
    """项目由更新版本的程序创建。"""


class CorruptJSON(ValueError):
    """JSON 文件读不出来或顶层类型不对：不能当成「没有」继续（KI-21）。"""


CORRUPT_JSON_MSG = "{name} 损坏、读不出来（{detail}），程序没有用它继续：{path}"
_MISSING = object()


# 字段默认值（v1）
DEFAULTS: dict[str, Any] = {
    "schema_version": CURRENT_SCHEMA,
    "title": "",
    "preset": "纪实3min",
    "platform": "douyin",
    "target_duration": 175,
    "created": "",
    "brief": {},
    "calibration": {},
}

REQUIRED = ("name", "material")


def stamp(obj: dict) -> dict:
    """返回带 artifact_schema 的新 dict（不改输入）。"""
    return {**obj, "artifact_schema": ARTIFACT_SCHEMA}


def default_project(name: str, material: str, **overrides: Any) -> dict:
    # 深拷贝：brief / calibration 是可变 dict，不能让所有项目共享同一个（KI-26）
    cfg: dict[str, Any] = {"name": name, "material": str(material), **copy.deepcopy(DEFAULTS)}
    cfg["title"] = overrides.pop("title", name)
    cfg.update(overrides)
    return cfg


def ensure_supported(cfg: dict) -> int:
    """只校验版本号：类型不对抛 ValueError，比当前程序新抛 SchemaTooNew。"""
    ver = cfg.get("schema_version", 0)
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise ValueError(f"schema_version 必须是整数，收到 {ver!r}")
    if ver > CURRENT_SCHEMA:
        raise SchemaTooNew(
            f"项目 schema 版本 {ver} 高于当前支持 {CURRENT_SCHEMA}，请升级程序")
    return ver


def migrate(cfg: dict) -> tuple[dict, list[str]]:
    """把任意旧版配置提升到当前版本，返回 (新配置, 变更列表)。"""
    out = dict(cfg)
    changes: list[str] = []
    ver = ensure_supported(out)

    if ver < 1:
        # v0：无版本号的历史项目
        out.setdefault("title", out.get("name", ""))
        out.setdefault("preset", "纪实3min")
        out.setdefault("platform", "douyin")
        out.setdefault("target_duration", 175)
        out.setdefault("brief", {})
        out.pop("brief_v0", None)
        out["schema_version"] = 1
        changes.append("v0→v1")

    if out.get("schema_version", 1) < 2:
        out.setdefault("calibration", {})
        out["schema_version"] = 2
        changes.append("v1→v2")

    for key, value in DEFAULTS.items():
        if key not in out:
            out[key] = copy.deepcopy(value)  # KI-26
            changes.append(f"补齐 {key}")

    for key in REQUIRED:
        if not out.get(key):
            raise ValueError(f"项目配置缺少必填字段：{key}")

    return out, changes


def load(path: Path) -> dict:
    """读取并迁移，不写回（写回由调用方决定）。"""
    cfg, _ = migrate(read_json(path))  # 损坏 / 顶层不是对象 → CorruptJSON（ValueError 子类）
    return cfg


PROJECT_NAME_MAX = 100        # 字符数上限
PROJECT_NAME_MAX_BYTES = 255  # UTF-8 字节上限（macOS 文件名上限）
PROJECT_NAME_ERROR = (
    f"项目名不能以 - 或 . 开头，首尾不能有空格，不能含斜杠或控制字符，"
    f"最长 {PROJECT_NAME_MAX} 字（{PROJECT_NAME_MAX_BYTES} 字节）")
TITLE_ERROR = (
    f"片名不能为空，不能含斜杠或控制字符，"
    f"最长 {PROJECT_NAME_MAX} 字（{PROJECT_NAME_MAX_BYTES} 字节）")
_VERSION_RE = re.compile(r"v[0-9]{1,4}")  # 只认 ASCII 数字，\d 会放过 v٣
_SHOT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


LOCK_MODE = 0o600
STALE_TMP_S = 600  # 超过这么久的同名临时文件视为被强杀的写者留下的残片（KI-51）
LOCK_UNSUPPORTED = "文件锁不可用（%s），%s 退回进程内锁"
_LOG = logging.getLogger("aicut.schema")
_FALLBACK_LOCK = threading.RLock()


def _tmp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def _write_synced(tmp: Path, text: str) -> None:
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())  # 先落盘再改名：被强杀 / 断电不会留下空文件


def _fsync_dir(d: Path) -> None:
    """目录项也落盘；某些网络盘 / 外接盘不支持，忽略。"""
    with contextlib.suppress(OSError):
        fd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _clear_stale_tmps(path: Path) -> None:
    """清掉同名的陈旧临时文件；新鲜的可能是并发写者正在写的，不动。"""
    cutoff = time.time() - STALE_TMP_S
    for p in path.parent.glob(f".{glob.escape(path.name)}.*.tmp"):
        with contextlib.suppress(OSError):
            if p.stat().st_mtime < cutoff:
                p.unlink()


def write_json(path: Path, obj: Any, *, indent: int | None = 2) -> None:
    """原子写：每次用唯一临时文件，并发写同一路径不会互相踩。indent=None 写紧凑 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        _write_synced(tmp, json.dumps(obj, ensure_ascii=False, indent=indent))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)
    _clear_stale_tmps(path)


def create_json_exclusive(path: Path, obj: Any) -> None:
    """只在 path 不存在时创建（KI-69）：已存在抛 FileExistsError，绝不覆盖别人刚写的文件。

    内容先完整写进临时文件，再硬链接到目标名（原子、目标存在即失败）；文件系统不支持硬链接时退回 O_EXCL。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    tmp = _tmp_path(path)
    try:
        _write_synced(tmp, text)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:  # 不支持硬链接（如 exFAT）：O_EXCL 仍保证只有一个创建者
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
    finally:
        tmp.unlink(missing_ok=True)
    _fsync_dir(path.parent)


def lock_path(path: Path) -> Path:
    """锁加在独立的 .<名>.lock 上：os.replace 会换掉目标文件的 inode，锁不能加在目标本身。"""
    path = Path(path)
    return path.with_name(f".{path.name}.lock")


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """跨进程互斥（fcntl.flock，进程退出自动释放）；文件系统不支持时退回进程内锁并记 warning。"""
    lp = lock_path(path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lp, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), LOCK_MODE)  # 不跟随符号链接（L16）
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            _LOG.warning(LOCK_UNSUPPORTED, exc, Path(path).name)
            with _FALLBACK_LOCK:
                yield
            return
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def update(path: Path, mutate: Callable[[dict], dict]) -> dict:
    """加锁读改写任意 JSON 对象文件（缺失按 {}）；返回写入的新值。"""
    with locked(path):
        new = mutate(dict(read_json(path, default={})))
        write_json(path, new)
        return new


def update_project(path: Path, mutate: Callable[[dict], dict]) -> dict:
    """加锁读改写 project.json（读时迁移、写时补版本，KI-51）：两个写者不会互相覆盖对方的字段。"""
    with locked(path):
        new, _ = migrate(mutate(load(path)))
        write_json(path, new)
        return new


def _corrupt(path: Path, detail: str) -> CorruptJSON:
    return CorruptJSON(CORRUPT_JSON_MSG.format(name=path.name, detail=detail, path=path))


def read_json(path: Path, *, default: Any = _MISSING, expect: type | None = dict) -> Any:
    """与 write_json 对称的读取（KI-21）。

    缺失 → default（没给 default 抛 FileNotFoundError）；读不了 / 不是 UTF-8 / 不是 JSON /
    顶层类型不是 expect → CorruptJSON。报错只给行号与异常名，不带文件内容（可能是转写原文）。
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if default is _MISSING:
            raise
        return default
    except (OSError, UnicodeDecodeError) as exc:
        raise _corrupt(path, type(exc).__name__) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _corrupt(path, f"第 {exc.lineno} 行 {exc.msg}") from exc
    if expect is not None and not isinstance(data, expect):
        raise _corrupt(path, "顶层应为对象" if expect is dict else f"顶层应为 {expect.__name__}")
    return data


_TYPE_NAMES = {list: "列表", dict: "对象", str: "文字"}


def require_key(data: Any, key: str, path: Path, typ: type = list) -> Any:
    """读出来的 JSON 结构对不上（缺 key / 类型不对）→ 与损坏同样的人话（带文件名），不给 KeyError。"""
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, typ):
        raise _corrupt(Path(path), f"缺少 {key} 或类型不对，应为{_TYPE_NAMES.get(typ, typ.__name__)}")
    return value


def read_field(path: Path, key: str, typ: type = list) -> Any:
    """read_json + require_key：上一步产出的中间文件（segments.json 等）读一个必有字段。"""
    return require_key(read_json(path), key, path, typ)


def read_json_lenient(path: Path, default: Any = None) -> Any:
    """只用于「显示」：缺失或损坏都给 default。损坏必须另外让人看见（notices.corrupt_files，KI-21）。"""
    try:
        return read_json(path, default=default)
    except CorruptJSON:
        return default


def _is_safe_filename_part(text: str) -> bool:
    """不含路径分隔符和控制字符，字符数和 UTF-8 字节数都在上限内。"""
    return ("/" not in text and "\\" not in text
            and not any(ord(c) < 32 or ord(c) == 127 for c in text)
            and len(text) <= PROJECT_NAME_MAX
            and len(text.encode("utf-8")) <= PROJECT_NAME_MAX_BYTES)


def check_project_name(name: Any) -> str:
    """项目名白名单：允许中文和中间的空格，拒绝选项样式、隐藏名、首尾空白、路径分隔符和控制字符。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("项目名不能为空")
    if (name.startswith(("-", ".")) or name != name.strip()
            or not _is_safe_filename_part(name)):
        raise ValueError(PROJECT_NAME_ERROR)
    return name


def check_title(title: Any) -> str:
    """片名会成为剪映草稿目录名的一部分：渲染前就要拒绝，免得出片后才失败。"""
    if not isinstance(title, str) or not title.strip() or not _is_safe_filename_part(title):
        raise ValueError(TITLE_ERROR)
    return title


def check_version(version: Any) -> str:
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ValueError(f"版本号格式应为 v+数字（如 v3），收到 {version!r}")
    return version


TARGET_MIN, TARGET_MAX = 10, 3600  # 秒；成片时长由剪辑师决定，这里只挡明显的误输入
TARGET_ERROR = f"目标时长应为 {TARGET_MIN}–{TARGET_MAX} 秒之间的数字"


def check_target_duration(value: Any) -> int:
    """剪辑师填写的目标时长（秒）→ 整数秒。bool 是 int 子类，必须先排除。"""
    bad = ValueError(f"{TARGET_ERROR}，收到 {value!r}")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise bad
    try:
        sec = float(value.strip() if isinstance(value, str) else value)
    except ValueError as exc:
        raise bad from exc
    if not math.isfinite(sec) or not TARGET_MIN <= round(sec) <= TARGET_MAX:
        raise bad
    return int(round(sec))


def check_shot_ids(shots: Any) -> None:
    """镜头 id 会成为切片文件名：必须是安全字符且互不重复。"""
    if not isinstance(shots, list):
        raise ValueError("shots 必须是列表")
    seen: set[str] = set()
    for s in shots:
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not _SHOT_ID_RE.fullmatch(sid):
            raise ValueError(f"镜头 id 只能用字母、数字、_、-（≤32 位），收到 {sid!r}")
        if sid in seen:
            raise ValueError(f"镜头 id 重复：{sid}")
        seen.add(sid)


def _shot_time(shot: dict, key: str) -> float:
    raw = shot.get(key)
    try:
        if isinstance(raw, bool):
            raise TypeError
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"镜头 {shot['id']} 的 {key} 必须是数字，收到 {raw!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"镜头 {shot['id']} 的 {key} 必须是非负有限数，收到 {raw!r}")
    return round(value, 3)


SHOTS_MAX = 1000       # 一张分镜表最多多少镜（粗剪远用不到；防止异常数据撑爆）
SHOT_SUB_MAX = 500     # 单镜字幕最多多少字
SHOT_NOTE_MAX = 1000   # 单镜备注（选段理由等）最多多少字
_SHOT_TEXT_MAX = {"sub": SHOT_SUB_MAX, "note": SHOT_NOTE_MAX}


def _shot_text(shot: dict, key: str) -> str:
    raw = shot.get(key)
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"镜头 {shot['id']} 的 {key} 必须是文字，收到 {raw!r}")
    if len(raw) > _SHOT_TEXT_MAX[key]:
        raise ValueError(f"镜头 {shot['id']} 的 {key} 太长：最多 {_SHOT_TEXT_MAX[key]} 个字，现在有 {len(raw)} 个字")
    return raw


def clean_shots(shots: Any) -> list[dict]:
    """校验并规整分镜表，返回新列表（不改输入）；任何一镜不合法都整体拒绝。"""
    check_shot_ids(shots)
    if len(shots) > SHOTS_MAX:
        raise ValueError(f"分镜表最多 {SHOTS_MAX} 镜，现在有 {len(shots)} 镜")
    out = []
    for s in shots:
        t_in, t_out = _shot_time(s, "in"), _shot_time(s, "out")
        if t_out <= t_in:
            raise ValueError(f"镜头 {s['id']} 的出点必须晚于入点（{t_in} → {t_out}）")
        out.append({"id": s["id"], "in": t_in, "out": t_out,
                    "sub": _shot_text(s, "sub"), "note": _shot_text(s, "note")})
    return out


SHOTS_INVALID = "分镜表 {name} 不能用：{detail}"


def read_shots(path: Path) -> list[dict]:
    """读分镜表并整体校验（KI-48）：读不出 / 缺 shots / 镜头不合法 → CorruptJSON（带文件名），切片前就拒绝。

    注意 clean_shots 会把入出点规整成 3 位小数，手写的整数入出点会让切片缓存 key 变化而重切一次。
    """
    path = Path(path)
    data = read_json(path)
    try:
        return clean_shots(data.get("shots"))
    except ValueError as exc:
        raise CorruptJSON(SHOTS_INVALID.format(name=path.name, detail=exc)) from exc


def save(path: Path, cfg: dict) -> list[str]:
    """原子写入；返回迁移变更列表（通常为空）。"""
    cfg, changes = migrate(cfg)
    write_json(path, cfg)
    return changes
