# -*- coding: utf-8 -*-
"""镜头切片：切一镜（ensure_clips 与旧版本补切共用同一条 media_io / encode 路径），
以及每一版出片时记下的分镜表快照（审查修复 H2）。

「清理缓存」会删掉 work/clips/；旧版本的 timeline.json 仍指向那里。导出 Windows 包前，
按这一版的分镜表快照只补切缺失的切片；还在的不动（可能已被新一版重切过，不能覆盖）。
没有快照（本次修复之前出的版本）就说明原因，请剪辑师重新生成成片。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from pipeline import build_documentary, encode, media_io, schema

CLIP_VF = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
           "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30")
CLIP_AUDIO = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
CLIP_TIMEOUT_FACTOR = 10  # 切片要从长素材里 seek + 转码：按镜头时长 × 10 给 ffmpeg 超时（D6）
CLIPS_DIR = "work/clips"
SNAPSHOT_FILE = "shots_snapshot.json"
RECUT_NOTE = "[·] 这一版的切片被清理过，按当时的分镜表重新切 {n} 镜…"
NEED_REBUILD = ("{version} 的切片已被清理（「清理缓存」），而这一版是旧程序生成的、没有记下当时的分镜表，"
                "无法自动重切：请重新生成成片（点「生成成片」）后再导出")


class ClipsUnavailable(RuntimeError):
    """切片缺失且无法补切。"""


def cut_clip(dst: Path, src: Path, shot: dict) -> Path:
    """切一镜：1080×1920 竖屏、VideoToolbox 编码、原子落盘（失败抛 MediaError）。"""
    dur = shot["out"] - shot["in"]
    return media_io.ffmpeg_to(dst, ["-ss", f"{shot['in']:.3f}", "-t", f"{dur:.3f}",
                                    "-i", str(src), "-vf", CLIP_VF,
                                    *encode.h264_args("clip"), *CLIP_AUDIO],
                              timeout=media_io.timeout_for(dur * CLIP_TIMEOUT_FACTOR))


def pending_cut_seconds(pdir: Path, material: Path, shots: list[dict]) -> float:
    """这次生成成片还要（重）切的镜头总时长：缓存键对得上且切片完整的不算（磁盘预检用，M5）。"""
    clips_dir = Path(pdir) / CLIPS_DIR
    manifest = media_io.read_manifest(clips_dir / "manifest.json")
    return sum(s["out"] - s["in"] for s in shots
               if manifest.get(s["id"]) != build_documentary.clip_key(s, material)
               or not media_io.complete_or_adopt(clips_dir / f"{s['id']}.mp4"))


def save_snapshot(vdir: Path, shots: list[dict]) -> None:
    schema.write_json(Path(vdir) / SNAPSHOT_FILE, {"shots": shots})


def load_snapshot(vdir: Path) -> list[dict] | None:
    """这一版出片时的分镜表；没有或读不出 → None。"""
    try:
        return schema.read_shots(Path(vdir) / SNAPSHOT_FILE)
    except (FileNotFoundError, schema.CorruptJSON):
        return None


def _missing(timeline: dict, clips_dir: Path) -> list[str]:
    """时间线里指向 work/clips 但文件已不在（或不完整）的镜头 id。"""
    out = []
    for v in timeline.get("video") or [] if isinstance(timeline, dict) else []:
        src = Path(str(v.get("source") or ""))
        if src.parent == clips_dir and not media_io.is_complete(src):
            out.append(v.get("id"))
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
    if any(sid not in by_id for sid in missing):
        raise ClipsUnavailable(NEED_REBUILD.format(version=vdir.name))
    say(RECUT_NOTE.format(n=len(missing)))
    manifest_path = clips_dir / "manifest.json"
    manifest = media_io.read_manifest(manifest_path)
    for sid in missing:
        cut_clip(clips_dir / f"{sid}.mp4", material, by_id[sid])
        manifest = {**manifest, sid: build_documentary.clip_key(by_id[sid], material)}
        schema.write_json(manifest_path, manifest)
    return len(missing)
