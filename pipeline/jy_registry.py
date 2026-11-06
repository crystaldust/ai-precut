# -*- coding: utf-8 -*-
"""剪映草稿注册表（root_meta_info.json）：定位、读取、条目合并、备份 / 还原 / 清理。

从 to_jianying 拆出来保持单文件体量。只处理注册表，不碰草稿内容。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from pipeline import plat, schema

ROOT_META_NAME = "root_meta_info.json"
BACKUP_KEEP = 5                         # 注册表备份只留最新几份
BACKUP_RE = re.compile(r"root_meta_info\.json\.\d{8}-\d{6}(-\d+)?\.bak")   # 只清自己生成的备份名
DRAFT_META_NAME = "draft_meta_info.json"

JY_MISSING = ("找不到剪映草稿库：{meta}\n"
              "请确认已安装剪映专业版并至少打开过一次；如果在剪映「全局设置 → 草稿位置」"
              "改过目录，请确认该目录（含外接盘）当前可以访问。")
JY_NOT_ROOT_HINT = ("\n草稿位置 {root} 里没有剪映的草稿记录，不能确定它是剪映的草稿目录。"
                    "如果刚在剪映里改过草稿位置，请先在剪映里新建一个草稿（让剪映认下这个目录），"
                    "关掉剪映后再导出。")
JY_FALLBACK_NOTE = "草稿放在 {root}，登记到剪映的全局草稿注册表 {meta}"


class InstallError(RuntimeError):
    """安装进剪映失败；已回滚，剪映草稿库保持原样。"""


def norm(path) -> str:
    """路径比较用：剪映写 `F:/x`，我们是 `F:\\x`（Windows 上 normpath 统一分隔符、normcase 忽略大小写）。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def _read_store(meta: Path) -> list:
    try:
        reg = json.loads(meta.read_text(encoding="utf-8"))
        store = reg.get("all_draft_store")
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        return []
    return store if isinstance(store, list) else []


def _looks_like_draft_root(root: Path, default_meta: Path) -> bool:
    """证据：全局注册表里有条目登记在 root 下，或 root 下有带 draft_meta_info.json 的草稿目录。"""
    target = norm(root)
    if any(isinstance(e, dict) and e.get("draft_root_path") and norm(e["draft_root_path"]) == target
           for e in _read_store(default_meta)):
        return True
    try:
        return any((child / DRAFT_META_NAME).is_file() for child in root.iterdir() if child.is_dir())
    except OSError:
        return False


def registry_path(root: Path, env=None, home: Path | None = None) -> Path:
    """注册表实际位置。

    约定：草稿根内的 root_meta_info.json 优先（老版剪映 / Mac 每个草稿根各一份）；
    剪映 11.x Windows 只在默认位置保留唯一一份全局注册表，草稿位置改到别处时根内没有它。
    退回默认位置须同时满足：Windows、没设 AI_CUT_DRAFT_ROOT、root 是已存在且不同于默认位置的目录、
    默认注册表存在、且有证据表明 root 是剪映的草稿目录；否则报错，绝不去改一个无关的注册表。
    """
    env = os.environ if env is None else env
    meta = root / ROOT_META_NAME
    if root.is_dir() and meta.is_file():
        return meta
    tried = [str(meta)]
    extra = ""
    if root.is_dir() and plat.IS_WIN and not env.get("AI_CUT_DRAFT_ROOT"):
        default = plat.jianying_draft_root(env=env, home=home)
        if norm(default) != norm(root):
            fallback = default / ROOT_META_NAME
            tried.append(str(fallback))
            if fallback.is_file():
                if _looks_like_draft_root(root, fallback):
                    return fallback
                extra = JY_NOT_ROOT_HINT.format(root=root)
    raise InstallError(JY_MISSING.format(meta="\n或 ".join(tried)) + extra)


def load_registry(root: Path, env=None, home: Path | None = None,
                  notify=None) -> tuple[Path, dict]:
    """读剪映草稿注册表，返回 (注册表路径, 内容)；用到了根外的全局注册表时调用 notify(说明)。"""
    meta = registry_path(root, env, home)
    try:
        reg = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"剪映草稿注册表读不了（{exc}）：{meta}；未做任何改动") from exc
    if not isinstance(reg, dict) or not isinstance(reg.get("all_draft_store"), list):
        raise InstallError(f"剪映草稿注册表格式不认识：{meta}；未做任何改动")
    if notify and meta.parent != root:
        notify(JY_FALLBACK_NOTE.format(root=root, meta=meta))
    return meta, reg


def with_entry(registry: dict, entry: dict) -> dict:
    """返回新注册表：同一草稿目录的旧条目去掉（其他草稿根下的同名草稿保留），新条目放最前（不改入参）。"""
    fold = entry.get("draft_fold_path")
    rest = [e for e in registry["all_draft_store"]
            if not (fold and e.get("draft_fold_path") and norm(e["draft_fold_path"]) == norm(fold))]
    return {**registry, "all_draft_store": [entry, *rest]}


def is_registered(registry: dict, target: Path) -> bool:
    want = norm(target)
    return any(e.get("draft_fold_path") and norm(e["draft_fold_path"]) == want
               for e in registry["all_draft_store"])


def backup_registry(meta: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = meta.with_name(f"{meta.name}.{stamp}.bak")
    i = 2
    while bak.exists():
        bak = meta.with_name(f"{meta.name}.{stamp}-{i}.bak")
        i += 1
    shutil.copy2(meta, bak)
    return bak


def restore_registry(bak: Path, meta: Path) -> None:
    """用备份还原注册表：先写同目录临时文件再 os.replace，还原过程中断也不会留下半个注册表。"""
    tmp = meta.with_name(f".{meta.name}.{uuid.uuid4().hex}.restore")
    try:
        shutil.copy2(bak, tmp)
        schema.atomic_replace(tmp, meta)
    finally:
        tmp.unlink(missing_ok=True)


def prune_backups(meta_dir: Path) -> None:
    """只清自己名字格式的旧备份；尽力而为——清理出岔子不能让已注册成功的安装变成失败。"""
    try:
        baks = sorted((p for p in meta_dir.iterdir() if BACKUP_RE.fullmatch(p.name)),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in baks[BACKUP_KEEP:]:
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
