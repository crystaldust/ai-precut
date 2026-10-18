#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 草稿兼容性验证脚本（一次性，用于判断 Windows 版能否完整支持）。

它做一件事：用程序生成一份**明文**剪映草稿，写进本机剪映草稿库，然后你打开剪映看能不能看到、能不能打开。

用法（Windows）：
    pip install pyJianYingDraft
    python spike.py --video "D:\\素材\\test.mp4" --name "WIN测试_程序生成"

如果想指定草稿目录：
    python spike.py --video ... --draft-root "D:\\剪映草稿"

判定标准见同目录 README-Windows测试.md。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

IS_WIN = sys.platform.startswith("win")


def default_draft_root() -> Path:
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / "JianyingPro/User Data/Projects/com.lveditor.draft"
    return Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"


def probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, encoding="utf-8").stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def mp4_duration(path: Path) -> float:
    """纯 Python 读 mp4 的 mvhd 时长，避免依赖 ffprobe（Windows 上可能没装）。

    moov/mvhd 可能在文件头（faststart）也可能在文件尾（ffmpeg 默认），所以两头都找。
    """
    def parse(buf: bytes) -> float:
        i = buf.find(b"mvhd")
        if i < 0 or i + 24 > len(buf):
            return 0.0
        ver = buf[i + 4]
        if ver == 0:
            timescale = int.from_bytes(buf[i + 16:i + 20], "big")
            duration = int.from_bytes(buf[i + 20:i + 24], "big")
        else:
            timescale = int.from_bytes(buf[i + 24:i + 28], "big")
            duration = int.from_bytes(buf[i + 28:i + 36], "big")
        return duration / timescale if timescale else 0.0

    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            d = parse(f.read(min(size, 2 * 1024 * 1024)))
            if d:
                return d
            f.seek(max(0, size - 2 * 1024 * 1024))
            return parse(f.read())
    except Exception:
        return 0.0


def build(video: Path, root: Path, name: str) -> Path:
    import pyJianYingDraft as draft

    duration = probe_duration(video) or mp4_duration(video) or 10.0
    seg = min(3.0, max(1.0, duration / 3))

    staging = Path.home() / ".aicut-win-spike"
    staging.mkdir(parents=True, exist_ok=True)
    script = draft.DraftFolder(str(staging)).create_draft(
        name, 1080, 1920, fps=30, allow_replace=True)
    script.append_track(draft.TrackSpec(draft.TrackType.video))
    script.append_track(draft.TrackSpec(draft.TrackType.text))

    us = lambda x: int(round(x * 1_000_000))  # noqa: E731
    T = draft.Timerange
    script.add_segment(draft.VideoSegment(
        str(video), T(0, us(seg)), source_timerange=T(0, us(seg))))
    script.add_segment(draft.VideoSegment(
        str(video), T(us(seg), us(seg)), source_timerange=T(us(seg), us(seg))))
    script.add_segment(draft.TextSegment(
        "程序生成的字幕 1/2", T(0, us(seg)),
        style=draft.TextStyle(size=8.0, color=(1.0, 1.0, 1.0), align=1, bold=True)))
    script.add_segment(draft.TextSegment(
        "程序生成的字幕 2/2", T(us(seg), us(seg)),
        style=draft.TextStyle(size=8.0, color=(1.0, 1.0, 1.0), align=1, bold=True)))
    script.save()

    src_dir = staging / name
    # 素材打包进 Resources，避免沙箱/权限问题
    res = src_dir / "Resources"
    res.mkdir(exist_ok=True)
    content_path = src_dir / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    final_res = root / name / "Resources"
    for kind in ("videos", "audios"):
        for m in content["materials"].get(kind, []):
            p = Path(m["path"])
            if not p.exists():
                continue
            dst = res / p.name
            if not dst.exists():
                shutil.copy2(p, dst)
            m["path"] = str(final_res / p.name)
    # 清理悬空引用 + 重写草稿 id（pyJianYingDraft 会在多个草稿间复用同一个 id）
    all_ids = {m["id"] for v in content["materials"].values()
               if isinstance(v, list) for m in v if isinstance(m, dict) and "id" in m}
    for track in content["tracks"]:
        for seg in track["segments"]:
            if seg.get("extra_material_refs"):
                seg["extra_material_refs"] = [r for r in seg["extra_material_refs"]
                                              if r in all_ids]
    draft_id = str(uuid.uuid4()).upper()
    content["id"] = draft_id

    # 如果带了 11.0 空草稿骨架，把结构对齐过去（字段级同构，兼容性最好）
    tpl = Path(__file__).with_name("base_template_11.0.json")
    if tpl.exists():
        base = json.loads(tpl.read_text(encoding="utf-8"))
        for k, v in content.items():
            if k != "materials":
                base[k] = v
        for k, v in content["materials"].items():
            if v:
                base["materials"][k] = v
        content = base

    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    # 关键：同时写 draft_info.json（6+ 入口）和 draft_content.json（5.x 入口），内容一致
    (src_dir / "draft_info.json").write_text(
        json.dumps(content, ensure_ascii=False), encoding="utf-8")

    # platform 留空，避免被判定为"别的平台生成的"
    meta_path = src_dir / "draft_meta_info.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    now = int(time.time() * 1_000_000)
    meta.update({
        "draft_id": draft_id,
        "draft_name": name,
        "draft_fold_path": str(root / name),
        "draft_root_path": str(root),
        "tm_draft_create": now,
        "tm_draft_modified": now,
        "tm_duration": content["duration"],
    })
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return src_dir


def register(root: Path, name: str, draft_id: str, duration: int) -> None:
    meta_path = root / "root_meta_info.json"
    if meta_path.exists():
        shutil.copy2(meta_path, meta_path.with_suffix(".json.spike.bak"))
        root_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        root_meta = {"all_draft_store": [], "draft_ids": [], "root_path": str(root)}
    now = int(time.time() * 1_000_000)
    root_meta["all_draft_store"] = [
        e for e in root_meta.get("all_draft_store", []) if e.get("draft_name") != name]
    root_meta["all_draft_store"].insert(0, {
        "draft_id": draft_id,
        "draft_name": name,
        "draft_fold_path": str(root / name),
        "draft_root_path": str(root),
        "draft_json_file": str(root / name / "draft_info.json"),
        "draft_cover": "",
        "draft_timeline_materials_size": 0,
        "draft_cloud_sync": False, "draft_is_cloud_temp_draft": False,
        "streaming_edit_draft_ready": True,
        "tm_draft_create": now, "tm_draft_modified": now,
        "tm_duration": duration,
    })
    meta_path.write_text(json.dumps(root_meta, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="本机一个 mp4 的路径")
    ap.add_argument("--name", default="WIN测试_程序生成")
    ap.add_argument("--draft-root", default="")
    args = ap.parse_args()

    video = Path(args.video).expanduser()
    if not video.exists():
        sys.exit(f"视频不存在：{video}")
    root = Path(args.draft_root).expanduser() if args.draft_root else default_draft_root()
    if not root.exists():
        sys.exit(f"草稿目录不存在：{root}\n请先打开一次剪映，或用 --draft-root 指定")

    print(f"草稿目录：{root}")
    src = build(video, root, args.name)
    target = root / args.name
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(src), str(target))

    meta = json.loads((target / "draft_meta_info.json").read_text(encoding="utf-8"))
    register(root, args.name, meta["draft_id"], meta.get("tm_duration", 0))

    print("\n完成。现在：")
    print("  1. 完全退出剪映（包括托盘图标），再重新打开；")
    print(f"  2. 在『本地草稿』里找『{args.name}』；")
    print("  3. 双击打开，看时间线是否有 2 段视频 + 2 条字幕。")
    print("\n把结果（截图 + 是否有报错）反馈给开发者。")


if __name__ == "__main__":
    main()
