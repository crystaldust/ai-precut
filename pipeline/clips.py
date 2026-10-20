# -*- coding: utf-8 -*-
"""镜头切片：切一镜（出片与旧版本补切共用同一条 media_io / encode 路径），
以及每一版出片时记下的分镜表快照（审查修复 H2）。

KI-89：切片按内容命名 `work/clips/<id>-<clip_key>.mp4`，时间线 `source` 指向带键的文件。
新一版改了某镜入出点只会切出新文件，旧版本引用的切片永远不被改写。旧程序出的版本指向
`<id>.mp4`，照常可用：`manifest.json`（旧缓存的 {id: key}）只读，键一致就硬链接复用。
出片后清掉不再被任何版本时间线引用的切片（任一时间线读不出就不清）。

「清理缓存」会删掉 work/clips/；导出 Windows 包前按这一版的分镜表快照只补切缺失的切片，
补到时间线里写的那个路径。没有快照（审查修复 H2 之前出的版本）就说明原因，请剪辑师重新生成成片。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Callable

from pipeline import build_documentary, encode, media_io, schema

CLIP_VF = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
           "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")
CLIP_AUDIO = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
CLIP_TIMEOUT_FACTOR = 10  # 切片要从长素材里 seek + 转码：按镜头时长 × 10 给 ffmpeg 超时（D6）
CLIPS_DIR = "work/clips"
SNAPSHOT_FILE = "shots_snapshot.json"
MANIFEST = "manifest.json"
RECUT_NOTE = "[·] 这一版的切片被清理过，按当时的分镜表重新切 {n} 镜…"
CUT_NOTE = "切镜头 {id}（{dur:.1f}s）"
CUT_SUMMARY = "切片：{new} 个新切，{reused} 个复用"
CUT_FAILED = "切镜头 {id} 失败：{exc}"
PRUNE_MIN_AGE_S = 3600  # 一小时内写的切片不清：可能是别的出片任务刚切、还没写进时间线
KEY_MISMATCH = ("{version} 的镜头 {id} 需要补切，但素材或入出点已和当时不同（素材被换过或移动过），"
                "补切出来会和当初不一致：请重新生成这一版成片后再导出")
NEED_REBUILD = ("{version} 的切片已被清理（「清理缓存」），而这一版是旧程序生成的、没有记下当时的分镜表，"
                "无法自动重切：请在「⑥ 导出」生成新版本后再导出")


class ClipsUnavailable(RuntimeError):
    """切片缺失且无法补切。"""


class CutFailed(RuntimeError):
    """某一镜切片失败（消息里带镜头 id）。"""


def clip_name(shot: dict, src: Path) -> str:
    """带内容键的切片文件名（KI-89）：素材 / 入出点 / id 任一变化就是另一个文件。"""
    return f"{shot['id']}-{build_documentary.clip_key(shot, src)}.mp4"


def clip_source(clips: dict[str, Path] | Path, sid: str) -> Path:
    """{id: 切片路径}，或旧调用方式（目录，旧命名 <id>.mp4）。"""
    return clips[sid] if isinstance(clips, dict) else Path(clips) / f"{sid}.mp4"


def cut_clip(dst: Path, src: Path, shot: dict) -> Path:
    """切一镜：1080×1920 竖屏、VideoToolbox 编码、原子落盘（失败抛 MediaError）。"""
    dur = shot["out"] - shot["in"]
    return media_io.ffmpeg_to(dst, ["-ss", f"{shot['in']:.3f}", "-t", f"{dur:.3f}",
                                    "-i", str(src), "-vf", CLIP_VF,
                                    *encode.h264_args("clip"), *CLIP_AUDIO],
                              timeout=media_io.timeout_for(dur * CLIP_TIMEOUT_FACTOR))


def _legacy_clip(clips_dir: Path, shot: dict, src: Path, manifest: dict) -> Path | None:
    """旧程序切的 <id>.mp4：缓存键一致且完整才可复用。"""
    legacy = clips_dir / f"{shot['id']}.mp4"
    if manifest.get(shot["id"]) != build_documentary.clip_key(shot, src):
        return None
    return legacy if media_io.complete_or_adopt(legacy) else None


def _adopt(legacy: Path, dst: Path) -> bool:
    """旧切片硬链接（跨卷等失败退回复制）成带键文件；原子落盘，失败就当没有缓存。"""
    try:
        with media_io.atomic_output(dst) as tmp:
            try:
                os.link(legacy, tmp)
            except OSError:
                shutil.copy2(legacy, tmp)
    except (OSError, media_io.MediaError):
        return False
    return True


def _cached(clips_dir: Path, shot: dict, src: Path, manifest: dict, dst: Path) -> bool:
    if media_io.complete_or_adopt(dst):
        return True
    legacy = _legacy_clip(clips_dir, shot, src, manifest)
    return legacy is not None and _adopt(legacy, dst)


def ensure(pdir: Path, src: Path, shots: list[dict],
           say: Callable[[str], None] = print) -> dict[str, Path]:
    """只切缓存里没有的镜头，返回 {镜头 id: 切片路径}；切失败抛 CutFailed（已切好的留着，下次不重切）。"""
    clips_dir = Path(pdir) / CLIPS_DIR
    clips_dir.mkdir(parents=True, exist_ok=True)
    manifest = media_io.read_manifest(clips_dir / MANIFEST)  # 只读：旧缓存；损坏 → 提示后当空
    out: dict[str, Path] = {}
    changed = 0
    for sh in shots:
        dst = out[sh["id"]] = clips_dir / clip_name(sh, src)
        if _cached(clips_dir, sh, src, manifest, dst):
            continue
        say(CUT_NOTE.format(id=sh["id"], dur=sh["out"] - sh["in"]))
        try:
            cut_clip(dst, src, sh)
        except media_io.MediaError as exc:
            raise CutFailed(CUT_FAILED.format(id=sh["id"], exc=exc)) from exc
        changed += 1
    say(CUT_SUMMARY.format(new=changed, reused=len(shots) - changed))
    return out


def pending_cut_seconds(pdir: Path, material: Path, shots: list[dict]) -> float:
    """这次生成成片还要（重）切的镜头总时长：带键切片完整、或旧缓存可复用的不算（磁盘预检用，M5）。"""
    clips_dir = Path(pdir) / CLIPS_DIR
    manifest = media_io.read_manifest(clips_dir / MANIFEST)
    return sum(s["out"] - s["in"] for s in shots
               if not media_io.complete_or_adopt(clips_dir / clip_name(s, material))
               and _legacy_clip(clips_dir, s, material, manifest) is None)


def save_snapshot(vdir: Path, shots: list[dict]) -> None:
    schema.write_json(Path(vdir) / SNAPSHOT_FILE, {"shots": shots})


def load_snapshot(vdir: Path) -> list[dict] | None:
    """这一版出片时的分镜表；没有或读不出 → None。"""
    try:
        return schema.read_shots(Path(vdir) / SNAPSHOT_FILE)
    except (FileNotFoundError, schema.CorruptJSON):
        return None


def _missing(timeline: dict, clips_dir: Path) -> list[tuple[str, Path]]:
    """时间线里指向 work/clips 但文件已不在（或不完整）的 (镜头 id, 切片路径)。"""
    out = []
    for v in timeline.get("video") or [] if isinstance(timeline, dict) else []:
        src = Path(str(v.get("source") or ""))
        # 只认 work/clips 下的 .mp4：时间线是磁盘上的文件，不能借它覆盖 manifest 之类
        if src.parent == clips_dir and src.suffix == ".mp4" and not media_io.is_complete(src):
            out.append((v.get("id"), src))
    return out


def restore_missing(pdir: Path, timeline_path: Path, material: Path,
                    say: Callable[[str], None] = print) -> int:
    """只补切缺失的切片，返回补切的数量；补不了抛 ClipsUnavailable（切片失败抛 MediaError）。"""
    clips_dir = Path(pdir) / CLIPS_DIR
    try:
        timeline = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0  # 读不出的时间线由导出本身报错
    missing = _missing(timeline, clips_dir)
    if not missing:
        return 0
    vdir = Path(timeline_path).parent
    by_id = {s["id"]: s for s in load_snapshot(vdir) or []}
    if any(sid not in by_id for sid, _ in missing):
        raise ClipsUnavailable(NEED_REBUILD.format(version=vdir.name))
    for sid, dst in missing:  # 带键文件名必须与按现在素材算出的一致，否则补切内容会变
        if dst.name != f"{sid}.mp4" and dst.name != clip_name(by_id[sid], material):
            raise ClipsUnavailable(KEY_MISMATCH.format(version=vdir.name, id=sid))
    say(RECUT_NOTE.format(n=len(missing)))
    manifest_path = clips_dir / MANIFEST
    for sid, dst in missing:  # 补到时间线里写的那个文件（带键或旧命名）
        cut_clip(dst, material, by_id[sid])
        if dst.name == f"{sid}.mp4":  # 旧命名：缓存键跟着内容走，免得被当成别的入出点复用
            manifest = {**media_io.read_manifest(manifest_path),
                        sid: build_documentary.clip_key(by_id[sid], material)}
            schema.write_json(manifest_path, manifest)
    return len(missing)


def _referenced(pdir: Path) -> set[str] | None:
    """所有版本时间线引用的切片文件名；任一时间线读不出 → None（不能判断就不清理）。"""
    names: set[str] = set()
    for tl_path in (Path(pdir) / "output").glob("*/timeline.json"):
        try:
            timeline = json.loads(tl_path.read_text(encoding="utf-8"))
            names |= {Path(str(v.get("source") or "")).name for v in timeline.get("video") or []}
        except (OSError, ValueError, AttributeError, TypeError):
            return None
    return names


def prune_unreferenced(pdir: Path, *, now: Callable[[], float] = time.time) -> int:
    """删掉不被任何版本时间线引用、且一小时内没写过的切片（连同完成标记），返回删除数（KI-89）。"""
    clips_dir = Path(pdir) / CLIPS_DIR
    keep = _referenced(pdir) if clips_dir.is_dir() else None
    if keep is None:
        return 0
    removed, cutoff = 0, now() - PRUNE_MIN_AGE_S
    for clip in clips_dir.glob("*.mp4"):
        try:
            recent = clip.stat().st_mtime > cutoff
        except OSError:
            continue
        if clip.name not in keep and not recent:
            clip.unlink(missing_ok=True)
            media_io.done_marker(clip).unlink(missing_ok=True)
            removed += 1
    return removed
