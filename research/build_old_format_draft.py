#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_old_format_draft.py —— 手写"剪映专业版旧格式"草稿（draft_content.json 体系）

不依赖 pyJianYingDraft，纯标准库生成：
    <out>/draft_content.json     # 时间线主体（materials / tracks / canvas / duration ...）
    <out>/draft_meta_info.json   # 草稿元信息（列表页显示、时长、封面路径）
    <out>/draft_settings         # INI 风格的编辑统计
    <out>/draft_cover.jpg        # 列表页封面（可选，剪映会自己重生成）

用法：
    python3 build_old_format_draft.py --out /tmp/t/我的测试草稿 \
        --video /abs/path/a.mp4 --audio /abs/path/b.m4a --draft-name 我的测试草稿

设计要点（与调研文档对应）：
  * 时间单位全部是 **微秒**（1 s = 1_000_000）。
  * 素材 / 片段 / 轨道 id 用 32 位小写 hex（无连字符）；草稿 id 用大写带连字符 UUID。
  * path 用**绝对 POSIX 路径**，不转 file://，不做 URL 编码。
  * 每条 segment 通过 material_id 指向 materials.xxx，通过 extra_material_refs 指向
    speeds / transitions / material_animations 等"附属素材"。
  * duration = 所有 track 中 target_timerange 结束时间的最大值。
"""
import argparse
import json
import os
import shutil
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE = os.path.join(HERE, "base_template_11.0.json")


# ---------------------------------------------------------------- id 工具
def uid() -> str:
    """素材 / 片段 / 轨道 id：32 位小写 hex"""
    return uuid.uuid4().hex


def duid() -> str:
    """草稿 id：大写带连字符 UUID"""
    return str(uuid.uuid4()).upper()


def tr(start_us: int, dur_us: int) -> dict:
    """timerange：单位微秒"""
    return {"start": int(start_us), "duration": int(dur_us)}


# ---------------------------------------------------------------- 素材
CROP_FULL = {
    "upper_left_x": 0.0, "upper_left_y": 0.0,
    "upper_right_x": 1.0, "upper_right_y": 0.0,
    "lower_left_x": 0.0, "lower_left_y": 1.0,
    "lower_right_x": 1.0, "lower_right_y": 1.0,
}


def video_material(path: str, duration_us: int, width: int, height: int) -> dict:
    mid = uid()
    return {
        "id": mid,
        "material_id": mid,
        "local_material_id": "",
        "path": path,
        "media_path": "",
        "material_name": os.path.basename(path),
        "type": "video",
        "duration": int(duration_us),
        "width": int(width),
        "height": int(height),
        "category_id": "",
        "category_name": "local",
        "check_flag": 63487,
        "crop": dict(CROP_FULL),
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "audio_fade": None,
    }


def audio_material(path: str, duration_us: int) -> dict:
    mid = uid()
    return {
        "id": mid,
        "local_material_id": mid,
        "music_id": mid,
        "name": os.path.basename(path),
        "path": path,
        "duration": int(duration_us),
        "type": "extract_music",
        "category_id": "",
        "category_name": "local",
        "check_flag": 3,
        "app_id": 0,
        "source_platform": 0,
        "copyright_limit_type": "none",
        "effect_id": "",
        "formula_id": "",
        "wave_points": [],
    }


def text_material(text: str, *, size: float = 8.0, color=(1.0, 1.0, 1.0),
                  align: int = 1, stroke: bool = True) -> dict:
    """字幕素材：真正的内容在 content 这个"JSON 字符串"里"""
    style = {
        "fill": {
            "alpha": 1.0,
            "content": {
                "render_type": "solid",
                "solid": {"alpha": 1.0, "color": [float(c) for c in color]},
            },
        },
        "range": [0, len(text)],
        "size": float(size),
        "bold": False,
        "italic": False,
        "underline": False,
    }
    if stroke:
        style["strokes"] = [{
            "content": {"solid": {"alpha": 1.0, "color": [0.0, 0.0, 0.0]}},
            "width": 0.08,
        }]
    return {
        "id": uid(),
        "type": "text",
        "content": json.dumps({"text": text, "styles": [style]}, ensure_ascii=False),
        "alignment": int(align),          # 0 左 / 1 中 / 2 右
        "typesetting": 0,
        "letter_spacing": 0.0,
        "line_spacing": 0.02,
        "line_feed": 1,
        "line_max_width": 0.82,
        "force_apply_line_max_width": False,
        "check_flag": 15,
        "global_alpha": 1.0,
    }


def speed_material(value: float = 1.0) -> dict:
    """变速素材：每条 segment 都要有一条，哪怕 speed=1.0"""
    return {"id": uid(), "type": "speed", "mode": 0, "speed": float(value), "curve_speed": None}


def transition_material(effect_id: str = "322577", name: str = "叠化",
                       resource_id: str = "6724845717472416269", duration_us: int = 500000) -> dict:
    """转场素材：effect_id/resource_id 必须是剪映资源库里的真实 id，否则显示"加载失败" """
    return {
        "id": uid(),
        "type": "transition",
        "name": name,
        "effect_id": effect_id,
        "resource_id": resource_id,
        "duration": int(duration_us),
        "is_overlap": True,
        "platform": "all",
        "category_id": "",
        "category_name": "",
    }


# ---------------------------------------------------------------- 片段
def _base_segment(material_id: str, target: dict, *, source=None, speed_ref=None,
                  render_index: int = 0, volume: float = 1.0, clip=None) -> dict:
    refs = [speed_ref] if speed_ref else []
    return {
        "id": uid(),
        "material_id": material_id,
        "target_timerange": target,
        "source_timerange": source,
        "speed": 1.0,
        "volume": float(volume),
        "extra_material_refs": refs,
        "common_keyframes": [],
        "keyframe_refs": [],
        "is_tone_modify": False,
        "visible": True,
        "reverse": False,
        "last_nonzero_volume": 1.0,
        "track_attribute": 0,
        "track_render_index": 0,
        "render_index": int(render_index),
        "enable_adjust": True,
        "enable_color_correct_adjust": False,
        "enable_color_curves": True,
        "enable_color_match_adjust": False,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "clip": clip,
        "uniform_scale": {"on": True, "value": 1.0},
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
    }


def clip_default(scale_x=1.0, scale_y=1.0, tx=0.0, ty=0.0, alpha=1.0, rotation=0.0) -> dict:
    """clip：画面变换。transform x/y 取值 -1..1（0 = 画面中心）"""
    return {
        "alpha": float(alpha),
        "flip": {"horizontal": False, "vertical": False},
        "rotation": float(rotation),
        "scale": {"x": float(scale_x), "y": float(scale_y)},
        "transform": {"x": float(tx), "y": float(ty)},
    }


def track(track_type: str, name: str, segments: list, *, flag: int = 0, attribute: int = 0) -> dict:
    return {
        "id": uid(),
        "type": track_type,                  # video / audio / text / effect / filter / sticker
        "name": name,
        "is_default_name": False,
        "flag": flag,                        # 0 正常；2 通常出现在主轨
        "attribute": attribute,
        "segments": segments,
    }


# ---------------------------------------------------------------- 组装
def load_base(base_path: str) -> dict:
    with open(base_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build(*, video_path=None, audio_path=None, video_duration_us=10_000_000,
          video_width=1280, video_height=720, fps=30,
          flavor="11", draft_name="程序生成草稿", base_path=DEFAULT_BASE,
          audio_duration_us=None, pip_path=None, pip_duration_us=6_000_000) -> dict:
    content = load_base(base_path)

    if flavor == "11":
        content["new_version"] = "75.0.0"     # 剪映 11.0.0 自己写出来的值
    elif flavor == "legacy":
        content["new_version"] = "110.0.0"    # 5.9 / 6.x 时代的值
    content["version"] = 360000              # 两代都是这个数
    content["fps"] = float(fps)
    content["draft_type"] = "video"
    content["source"] = "default"
    content["canvas_config"] = {"width": 1920, "height": 1080, "ratio": "original",
                                "background": None}
    content["name"] = draft_name

    mats = content["materials"]
    for key in ("videos", "audios", "texts", "speeds", "transitions"):
        mats.setdefault(key, [])

    tracks = []
    dur_max = 0

    # ---- 1) 视频主轨：2 段，第二段做入出点裁剪，中间加转场
    if video_path:
        vm = video_material(video_path, video_duration_us, video_width, video_height)
        mats["videos"].append(vm)

        sp1, sp2 = speed_material(), speed_material()
        mats["speeds"] += [sp1, sp2]
        trans = transition_material()
        mats["transitions"].append(trans)

        seg1 = _base_segment(vm["id"], tr(0, 3_000_000),
                             source=tr(2_000_000, 3_000_000),      # 从素材第 2s 起取 3s
                             speed_ref=sp1["id"], render_index=0,
                             clip=clip_default())
        seg1["extra_material_refs"].append(trans["id"])
        seg2 = _base_segment(vm["id"], tr(3_000_000, 2_000_000),
                             source=tr(6_000_000, 2_000_000),      # 从素材第 6s 起取 2s
                             speed_ref=sp2["id"], render_index=0,
                             clip=clip_default())
        tracks.append(track("video", "主视频", [seg1, seg2]))
        dur_max = max(dur_max, 5_000_000)

    # ---- 1b) 画中画轨（第二条视频轨，缩小到右上角）
    if pip_path:
        pm = video_material(pip_path, pip_duration_us, 854, 480)
        mats["videos"].append(pm)
        sp = speed_material()
        mats["speeds"].append(sp)
        seg = _base_segment(pm["id"], tr(1_000_000, 2_000_000),
                            source=tr(0, 2_000_000), speed_ref=sp["id"],
                            render_index=3,
                            clip=clip_default(scale_x=0.35, scale_y=0.35, tx=0.5, ty=0.5))
        tracks.append(track("video", "画中画", [seg]))
        dur_max = max(dur_max, 3_000_000)

    # ---- 2) 音频轨
    if audio_path:
        ad = audio_duration_us or 5_000_000
        am = audio_material(audio_path, ad)
        mats["audios"].append(am)
        sp = speed_material()
        mats["speeds"].append(sp)
        seg = _base_segment(am["id"], tr(0, min(ad, 5_000_000)),
                            source=tr(0, min(ad, 5_000_000)),
                            speed_ref=sp["id"], render_index=1, volume=0.35, clip=None)
        seg.pop("uniform_scale", None)   # 音频片段没有画面字段
        seg.pop("hdr_settings", None)
        tracks.append(track("audio", "背景音乐", [seg]))
        dur_max = max(dur_max, min(ad, 5_000_000))

    # ---- 3) 字幕文本轨
    tm = text_material("这是程序生成的字幕", size=12.0, color=(1.0, 1.0, 0.0), align=1)
    mats["texts"].append(tm)
    seg = _base_segment(tm["id"], tr(500_000, 2_500_000), source=None,
                        render_index=2, clip=clip_default(ty=-0.72))
    tracks.append(track("text", "字幕", [seg]))
    dur_max = max(dur_max, 3_000_000)

    # 规范化：render_index 必须等于所属轨道在 tracks 数组中的下标（决定叠放层级）
    for ti, t in enumerate(tracks):
        for s in t["segments"]:
            s["render_index"] = ti
            s["track_render_index"] = 0

    content["tracks"] = tracks
    content["duration"] = int(dur_max)
    content["id"] = duid()
    content["create_time"] = 0
    content["update_time"] = 0
    return content


def write_project(out_dir: str, content: dict, *, draft_name: str, cover_src: str = None) -> None:
    os.makedirs(out_dir, exist_ok=True)
    root = os.path.dirname(os.path.abspath(out_dir))

    with open(os.path.join(out_dir, "draft_content.json"), "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)

    meta = {
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": os.path.join(os.path.abspath(out_dir), "draft_cover.jpg"),
        "draft_deeplink_url": "",
        "draft_fold_path": os.path.abspath(out_dir),
        "draft_id": content["id"],
        "draft_is_ai_shorts": False,
        "draft_is_invisible": False,
        "draft_materials": [{"type": t, "value": []} for t in (0, 1, 2, 3, 6, 7, 8)],
        "draft_materials_copied_info": [],
        "draft_name": draft_name,
        "draft_new_version": "",
        "draft_removable_storage_device": "",
        "draft_root_path": root,
        "draft_segment_extra_info": [],
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "tm_draft_removed": 0,
        "tm_duration": content["duration"],
    }
    with open(os.path.join(out_dir, "draft_meta_info.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    now = int(time.time())
    with open(os.path.join(out_dir, "draft_settings"), "w", encoding="utf-8") as f:
        f.write("[General]\n"
                "cloud_last_modify_platform=mac\n"
                f"draft_create_time={now}\n"
                f"draft_last_edit_time={now}\n"
                "real_edit_keys=1\n"
                "real_edit_seconds=0\n")

    cover = os.path.join(out_dir, "draft_cover.jpg")
    if cover_src and os.path.exists(cover_src):
        shutil.copy(cover_src, cover)
    else:
        _make_cover(cover)


def _make_cover(path: str, w: int = 480, h: int = 270) -> None:
    """生成一张深色封面；没有 PIL 时写入最小合法 JPEG 占位"""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (w, h), (24, 26, 32))
        d = ImageDraw.Draw(img)
        for i in range(0, w, 40):
            d.line([(i, 0), (i, h)], fill=(38, 42, 52))
        d.rectangle([16, 16, 130, 46], outline=(120, 200, 255), width=2)
        img.save(path, "JPEG", quality=88)
    except Exception:
        # 1x1 白 JPEG
        minijpg = bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300"
            "080606070605080707070909080a0c140d0c0b0b0c1912130f"
            "141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c3031"
            "3434341f27393d38323c2e333432ffc0000b0800010001010111"
            "00ffc4001f000001050101010101010000000000000000010203"
            "0405060708090a0bffc400b5100002010303020403050504040000"
            "017d01020300041105122131410613516107227114328191a108"
            "2342b1c11552d1f02433627282090a161718191a25262728292a"
            "3435363738393a434445464748494a535455565758595a636465"
            "666768696a737475767778797a838485868788898a9293949596"
            "9798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4"
            "c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9ea"
            "f1f2f3f4f5f6f7f8f9faffda0008010100003f00fbfe8a28a3ffd9")
        with open(path, "wb") as f:
            f.write(minijpg)


def main() -> None:
    ap = argparse.ArgumentParser(description="生成剪映旧格式草稿（draft_content.json）")
    ap.add_argument("--out", required=True, help="草稿目录（会被创建，不会删除已有内容）")
    ap.add_argument("--draft-name", default=None, help="草稿名，默认取目录名")
    ap.add_argument("--video", default=None, help="视频绝对路径")
    ap.add_argument("--audio", default=None, help="音频绝对路径")
    ap.add_argument("--video-duration", type=float, default=10.0, help="素材时长（秒）")
    ap.add_argument("--video-width", type=int, default=1280)
    ap.add_argument("--video-height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--flavor", choices=["11", "legacy"], default="11",
                    help="11=写入 new_version 75.0.0（对齐剪映 11.0）；legacy=110.0.0（对齐 5.9/6.x）")
    ap.add_argument("--base-template", default=DEFAULT_BASE, help="基底 template.tmp/JSON 路径")
    ap.add_argument("--pip", default=None, help="画中画视频绝对路径（会额外生成一条缩小叠加的视频轨）")
    ap.add_argument("--pip-duration", type=float, default=6.0, help="画中画素材时长（秒）")
    args = ap.parse_args()

    name = args.draft_name or os.path.basename(os.path.abspath(args.out))
    content = build(video_path=args.video, audio_path=args.audio,
                    video_duration_us=int(args.video_duration * 1_000_000),
                    video_width=args.video_width, video_height=args.video_height,
                    fps=args.fps, flavor=args.flavor, draft_name=name,
                    base_path=args.base_template,
                    pip_path=args.pip,
                    pip_duration_us=int(args.pip_duration * 1_000_000))
    write_project(args.out, content, draft_name=name)
    print("[ok] 写入草稿:", os.path.abspath(args.out))
    print("     duration(us):", content["duration"],
          "| tracks:", [(t["type"], len(t["segments"])) for t in content["tracks"]])


if __name__ == "__main__":
    main()
