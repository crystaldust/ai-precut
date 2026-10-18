#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timeline.json → 剪映专业版草稿（Mac）。

已验证环境：macOS + 剪映专业版 11.0.0（bundle com.lemon.lvpro）
依赖：pyJianYingDraft（负责生成 5.9 格式的 draft_content.json）、ffmpeg

做四件事：
  1. 用 pyJianYingDraft 在暂存目录生成草稿（视频轨/音频轨/文本轨）；
  2. Mac 版把媒体打包进草稿 Resources/（剪映是沙盒应用，草稿外路径会报"暂无访问权限"）；
  3. 补 platform 字段 + 写 draft_info.json（Mac 版入口文件名）+ 更新 draft_meta_info.json；
  4. 注册进 root_meta_info.json（先备份，失败自动回滚）。

用法：
    python3 to_jianying.py ../demo/timeline.json --name 我的粗剪_v1 --dry-run
    python3 to_jianying.py ../demo/timeline.json --name 我的粗剪_v1
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

DRAFT_ROOT = Path(os.environ.get("AI_CUT_DRAFT_ROOT")
                  or (Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"))
ROOT_META = DRAFT_ROOT / "root_meta_info.json"


# ------------------------------------------------------------------ 工具
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def us(seconds: float) -> int:
    """秒 → 微秒（剪映时间线统一单位）"""
    return int(round(seconds * 1_000_000))


def safe_name(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        sys.exit(f"非法草稿名：{name!r}")
    return name


# ------------------------------------------------------------------ 生成
def build_staging(tl: dict, staging: Path, name: str) -> Path:
    """用 pyJianYingDraft 生成 5.9 格式草稿，返回草稿目录。"""
    try:
        import pyJianYingDraft as draft
        from pyJianYingDraft import trange
    except ImportError:
        sys.exit("缺少依赖：pip install pyJianYingDraft")

    p = tl["project"]
    staging.mkdir(parents=True, exist_ok=True)
    script = draft.DraftFolder(str(staging)).create_draft(
        name, p["width"], p["height"], fps=p.get("fps", 30), allow_replace=True)

    script.append_track(draft.TrackSpec(draft.TrackType.video))
    if tl.get("audio"):
        script.append_track(draft.TrackSpec(draft.TrackType.audio))
    if tl.get("text"):
        script.append_track(draft.TrackSpec(draft.TrackType.text))

    for seg in sorted(tl["video"], key=lambda s: s["timeline_in"]):
        src = Path(seg["source"])
        if not src.exists():
            sys.exit(f"素材不存在：{src}")
        dur = seg["out"] - seg["in"]
        mat = draft.VideoMaterial(str(src))
        # ffmpeg 切出来的时长可能比请求的短几毫秒，取两者较小值，避免越界
        dur_us = min(us(dur), mat.duration)
        script.add_segment(draft.VideoSegment(
            mat,
            trange(us(seg["timeline_in"]), dur_us),
            source_timerange=trange(us(seg["in"]), dur_us),
            volume=seg.get("volume", 1.0),
        ))

    for seg in tl.get("audio", []):
        mat = draft.AudioMaterial(seg["source"])
        script.add_segment(draft.AudioSegment(
            mat, trange(us(seg["timeline_in"]), us(seg["out"] - seg["in"])),
            source_timerange=trange(us(seg["in"]), us(seg["out"] - seg["in"])),
            volume=seg.get("volume", 1.0)))

    for t in tl.get("text", []):
        st = t.get("style", {})
        align = int(st.get("align", 1))
        # 时间轴里的 align 表示"位置"：2=底部字幕、5=居中字幕卡（与 render_preview 保持一致）
        pos_y = {2: -0.72, 5: 0.10}.get(align, 0.0)
        script.add_segment(draft.TextSegment(
            t["text"],
            trange(us(t["start"]), us(t["end"] - t["start"])),
            style=draft.TextStyle(
                size=float(st.get("size", 8.0)),
                color=tuple(st.get("color", [1.0, 1.0, 1.0])),
                align=1,
                bold=bool(st.get("bold", True)),
            ),
            clip_settings=draft.ClipSettings(transform_y=pos_y)))

    script.save()
    return staging / name


def bundle_media(draft_dir: Path, final_dir: Path) -> int:
    """把媒体拷进草稿 Resources/，并把 path 改写成**安装后**的绝对路径。

    剪映 Mac 版是沙盒应用（entitlement 只有 ~/Movies 读写），引用草稿目录之外的
    路径会报"暂无访问权限"或静默丢素材，所以默认把媒体打包进 Resources/。
    """
    res = draft_dir / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    final_res = final_dir / "Resources"
    content_path = draft_dir / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    total, seen = 0, {}
    for kind in ("videos", "audios"):
        for m in content["materials"].get(kind, []):
            src = m["path"]
            if src not in seen:
                dst_name = Path(src).name
                i = 2
                while (res / dst_name).exists():
                    dst_name = f"{Path(src).stem}-{i}{Path(src).suffix}"
                    i += 1
                shutil.copy2(src, res / dst_name)
                seen[src] = str(final_res / dst_name)
                total += os.path.getsize(src)
            m["path"] = seen[src]
    write_json(content_path, content)
    return total


def normalize(draft_dir: Path) -> str:
    """修正 pyJianYingDraft 的两处坑：
    1. 草稿 id 在多个草稿间复用 → 重新生成为大写 UUID；
    2. 文本片段的 extra_material_refs 指向未写入的素材 → 摘掉悬空引用。
    """
    content_path = draft_dir / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    all_ids = {m["id"] for v in content["materials"].values()
               if isinstance(v, list) for m in v if isinstance(m, dict) and "id" in m}
    for track in content["tracks"]:
        for seg in track["segments"]:
            if seg.get("extra_material_refs"):
                seg["extra_material_refs"] = [r for r in seg["extra_material_refs"]
                                              if r in all_ids]
    new_id = str(uuid.uuid4()).upper()
    content["id"] = new_id
    write_json(content_path, content)
    return new_id



def align_with_template(draft_dir: Path, template: Path) -> None:
    """把生成结果套进剪映 11.0 自己写出的空草稿骨架。

    pyJianYingDraft 产出的是 5.9 结构（materials 只有 46 个分类、缺 11.0 新增的
    顶层字段）。以 11.0 的 template 为骨、生成的 tracks/materials 为肉，
    可以保证结构与剪映自己写出的完全同构，降低"打开后异常"的概率。
    """
    if not template.exists():
        print(f"[warn] 找不到 11.0 模板 {template}，跳过骨架对齐")
        return
    base = json.loads(template.read_text(encoding="utf-8"))
    gen = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    for k, v in gen.items():
        if k != "materials":
            base[k] = v
    for k, v in gen["materials"].items():
        if v:
            base["materials"][k] = v
    write_json(draft_dir / "draft_content.json", base)


def macify(draft_dir: Path, name: str, materials_size: int, draft_id: str) -> dict:
    """补 Mac 版字段并写入口文件 draft_info.json。"""
    content_path = draft_dir / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    now = int(time.time() * 1_000_000)

    # 11.0 自己写出的空草稿里 platform 指纹就是空串，实测可加载
    platform = {"app_id": 0, "app_source": "", "app_version": "11.0.0",
                "device_id": "", "hard_disk_id": "", "mac_address": "",
                "os": "mac", "os_version": os.uname().release}
    for k in ("platform", "last_modified_platform"):
        content[k] = {**content.get(k, {}), **platform}
    content["id"] = draft_id
    content["update_time"] = now
    write_json(content_path, content)
    write_json(draft_dir / "draft_info.json", content)   # Mac 版入口文件名

    meta_path = draft_dir / "draft_meta_info.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update({
        "draft_id": draft_id,
        "draft_fold_path": str(DRAFT_ROOT / name),
        "draft_root_path": str(DRAFT_ROOT),
        "draft_name": name,
        "tm_draft_create": now,
        "tm_draft_modified": now,
        "tm_duration": content["duration"],
        "draft_timeline_materials_size_": materials_size,
    })
    for group in meta.get("draft_materials", []):
        if group.get("type") == 0:
            group["value"] = [{
                "create_time": now // 1_000_000, "duration": m["duration"],
                "extra_info": m.get("material_name") or Path(m["path"]).name,
                "file_Path": m["path"], "height": m.get("height", 0),
                "id": str(uuid.uuid4()), "import_time": now // 1_000_000,
                "import_time_ms": now, "item_source": 1, "md5": "",
                "metetype": "music" if m.get("type") == "extract_music" else "video",
                "roughcut_time_range": {"duration": -1, "start": -1},
                "sub_time_range": {"duration": -1, "start": -1},
                "type": 0, "width": m.get("width", 0),
            } for m in content["materials"].get("videos", [])]
    write_json(meta_path, meta)

    videos = content["materials"].get("videos", [])
    if videos:
        # 此时 path 已指向安装后的最终位置，抽帧要用暂存目录里的副本
        cover_src = draft_dir / "Resources" / Path(videos[0]["path"]).name
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i",
                        str(cover_src), "-frames:v", "1",
                        str(draft_dir / "draft_cover.jpg")], check=False)
    return {"draft_id": content["id"], "duration": content["duration"]}


def register(info: dict, name: str, materials_size: int = 0) -> None:
    """注册进 root_meta_info.json（先备份，异常回滚）。"""
    bak = ROOT_META.with_suffix(ROOT_META.suffix + f".{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(ROOT_META, bak)
    root = json.loads(ROOT_META.read_text(encoding="utf-8"))
    entry = {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": str(DRAFT_ROOT / name / "draft_cover.jpg"),
        "draft_fold_path": str(DRAFT_ROOT / name),
        "draft_id": info["draft_id"],
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False, "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_json_file": str(DRAFT_ROOT / name / "draft_info.json"),
        "draft_name": name, "draft_new_version": "",
        "draft_root_path": str(DRAFT_ROOT),
        "draft_timeline_materials_size": materials_size, "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "", "pippit_extra_info": "", "pippit_id": "",
        "pippit_user_name": "", "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "tm_draft_removed": 0, "tm_duration": info["duration"],
    }
    root["all_draft_store"] = [e for e in root["all_draft_store"]
                               if e.get("draft_name") != name]
    root["all_draft_store"].insert(0, entry)
    try:
        write_json(ROOT_META, root)
    except BaseException:
        shutil.copy2(bak, ROOT_META)
        raise
    print(f"已注册；注册表备份：{bak}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("--name", default="AI粗剪")
    ap.add_argument("--staging", default=str(Path.home() / ".aicut/staging"))
    ap.add_argument("--dry-run", action="store_true",
                    help="只生成到暂存目录，不安装进剪映")
    args = ap.parse_args()

    name = safe_name(args.name)
    tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
    staging = Path(args.staging)
    draft_dir = build_staging(tl, staging, name)
    draft_id = normalize(draft_dir)
    size = bundle_media(draft_dir, DRAFT_ROOT / name)
    align_with_template(draft_dir, Path(__file__).parent.parent / "research/base_template_11.0.json")
    info = macify(draft_dir, name, size, draft_id)
    print(f"草稿已生成：{draft_dir}（{info['duration'] / 1e6:.2f}s，媒体 {size / 1e6:.1f}MB）")

    if args.dry_run:
        print("dry-run：未安装进剪映")
        return

    if subprocess.run(["pgrep", "-f", "MacOS/VideoFusion-macOS"],
                      capture_output=True).returncode == 0:
        sys.exit("剪映正在运行，请先完全退出（Cmd+Q）再安装")

    target = DRAFT_ROOT / name
    if target.exists():
        sys.exit(f"草稿已存在：{target}（换名字或先删除）")
    shutil.move(str(draft_dir), str(target))
    register(info, name, materials_size=size)
    print(f"完成。打开剪映 → 本地草稿 → {name}")


if __name__ == "__main__":
    main()
