# -*- coding: utf-8 -*-
"""「清理缓存」（KI-33 / D4）：只删可重建的中间产物。

会删：work/clips/（切片缓存，连同 manifest）、各处 .aicut-partial/ 与旧格式 .*.partial-* 临时文件、
以及转写与声音分析都已完成时的 work/audio/asr.wav（含完成标记）。
不删：分析代理、预览、成片、任何 JSON。一律只看项目目录下的固定相对路径，不跟随符号链接。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from pipeline import media_io

CLIPS_LABEL = "镜头切片缓存（重新生成成片、导出旧版本时按需重新切）"
PARTIAL_LABEL = "未完成的临时文件"
WAV_LABEL = "转写用音轨（转写与声音分析已完成）"
CLIPS_DIR = "work/clips"
WAV = "work/audio/asr.wav"


def _file_size(p: Path) -> int:
    return p.stat().st_size


def _tree_bytes(d: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(d, followlinks=False):
        for name in files:
            p = Path(root) / name
            try:  # 并发删掉 / 写完改名的文件：跳过（L12）
                total += 0 if p.is_symlink() else _file_size(p)
            except FileNotFoundError:
                continue
    return total


def _inside(pdir: Path, p: Path) -> bool:
    """p 真实存在、本身不是符号链接，且解析后仍在项目目录里（work/ 被换成符号链接也不越界，L15）。"""
    try:
        return not p.is_symlink() and Path(pdir).resolve(strict=True) in p.resolve(strict=True).parents
    except (OSError, RuntimeError):
        return False


def _real_dir(pdir: Path, p: Path) -> bool:
    return _inside(pdir, p) and p.is_dir()


def _real_file(pdir: Path, p: Path) -> bool:
    return _inside(pdir, p) and p.is_file()


def _partials(pdir: Path) -> list[Path]:
    found = []
    for root, dirs, files in os.walk(pdir, followlinks=False):
        here = Path(root)
        if media_io.PARTIAL_DIR in dirs and _real_dir(pdir, here / media_io.PARTIAL_DIR):
            found.append(here / media_io.PARTIAL_DIR)
        dirs[:] = [d for d in dirs if d != media_io.PARTIAL_DIR]
        found += [here / f for f in files
                  if f.startswith(".") and media_io.PARTIAL_TAG in f and _real_file(pdir, here / f)]
    return sorted(found)


def _wav_removable(pdir: Path) -> bool:
    work = pdir / "work"
    return (_real_file(pdir, pdir / WAV) and (work / "transcript_raw.json").is_file()
            and (work / "segments_audio.json").is_file())


def items(pdir: Path) -> list[dict]:
    """[{"label", "path"(相对项目目录), "bytes"}]；没有可清理的返回空列表。"""
    pdir = Path(pdir)
    out = []
    if _real_dir(pdir, pdir / CLIPS_DIR):
        out.append({"label": CLIPS_LABEL, "path": CLIPS_DIR, "bytes": _tree_bytes(pdir / CLIPS_DIR)})
    for p in _partials(pdir):
        try:
            size = _tree_bytes(p) if p.is_dir() else _file_size(p)
        except FileNotFoundError:  # 刚被写完改名：不算（L12）
            continue
        out.append({"label": PARTIAL_LABEL, "path": p.relative_to(pdir).as_posix(), "bytes": size})
    if _wav_removable(pdir):
        marker = media_io.done_marker(pdir / WAV)
        try:
            size = _file_size(pdir / WAV) + (_file_size(marker) if _real_file(pdir, marker) else 0)
            out.append({"label": WAV_LABEL, "path": WAV, "bytes": size})
        except FileNotFoundError:
            pass
    return out


def clean(pdir: Path) -> int:
    """删除 items() 列出的各项，返回释放的字节数。"""
    pdir = Path(pdir)
    freed = 0
    for item in items(pdir):
        p = pdir / item["path"]
        if not _inside(pdir, p):  # 列出之后被换成了符号链接 / 已不在：不删
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)
            if item["path"] == WAV:
                media_io.done_marker(p).unlink(missing_ok=True)
        freed += item["bytes"]
    return freed
