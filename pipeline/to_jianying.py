#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timeline.json → 剪映专业版草稿（Mac）。

已验证环境：macOS + 剪映专业版（版本与骨架模板见 pipeline/jy_version.py，bundle com.lemon.lvpro）
依赖：pyJianYingDraft（负责生成 5.9 格式的 draft_content.json）、ffmpeg

做四件事：
  1. 用 pyJianYingDraft 在暂存目录生成草稿（视频轨/音频轨/文本轨）；
  2. Mac 版把媒体打包进草稿 Resources/（剪映是沙盒应用，草稿外路径会报"暂无访问权限"）；
  3. 补 platform 字段 + 写 draft_info.json（Mac 版入口文件名）+ 更新 draft_meta_info.json；
  4. 安装：移入草稿根 → 静态校验 → 注册进 root_meta_info.json；任一步失败整体回滚
     （草稿挪回暂存目录、注册表还原），剪映草稿库保持原样（GL-11 / GL-13）。

草稿根：AI_CUT_DRAFT_ROOT > 剪映「全局设置 → 草稿位置」> 默认 ~/Movies/JianyingPro/...。

用法（在仓库根运行）：
    python -m pipeline.to_jianying demo/timeline.json --name 我的粗剪_v1 --dry-run
    python -m pipeline.to_jianying demo/timeline.json --name 我的粗剪_v1
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    # 脚本方式运行时让 pipeline / research 可导入；append 而非 insert(0)，
    # 免得仓库根的 packaging/ 遮蔽 PyPI 的 packaging
    sys.path.append(str(ROOT))

from pipeline import jy_version, schema  # noqa: E402

DEFAULT_DRAFT_ROOT = Path("Movies/JianyingPro/User Data/Projects/com.lveditor.draft")  # 相对 home
JY_SETTING = Path("Movies/JianyingPro/User Data/Config/globalSetting")                  # 相对 home
ROOT_META_NAME = "root_meta_info.json"
INSTALL_MARKER = ".aicut_installing"   # 安装中标记：只有带它且未注册的目录才允许自动清理
TMP_SUFFIX = ".aicut-tmp"               # 草稿根内的同卷临时目录：.<草稿名>.aicut-tmp
VALIDATION_FAIL_LINES = 10              # 校验失败时最多列出几条 FAIL
VALIDATION_WARN_LINES = 3               # 校验 WARN 汇总时列出几条
BACKUP_KEEP = 5                         # 注册表备份只留最新几份
BACKUP_GLOB = "root_meta_info.json.*.bak"
COVER_ERR_TAIL = 200
TEMPLATE = jy_version.TEMPLATE   # 保留这个名字：测试会替换它

JY_RUNNING = "剪映正在运行，请先完全退出（Cmd+Q）再安装"
TEMPLATE_MISSING = jy_version.TEMPLATE_MISSING
DRAFT_EXISTS = "草稿已存在：{target}（换名字，或先在剪映里删除）"
JY_MISSING = ("找不到剪映草稿库：{meta}\n"
              "请确认已安装剪映专业版并至少打开过一次；如果在剪映「全局设置 → 草稿位置」"
              "改过目录，请确认该目录（含外接盘）当前可以访问。")


# 给 aicut 解析的输出约定（审查修复 1）：成功时最后打印这几行
REPORT_DRAFT = "草稿位置："
REPORT_BACKUP = "注册表备份："
REPORT_WARN_HEADER = "[!] {n} 条警告"
REPORT_WARN_ITEM = "  - "


class InstallError(RuntimeError):
    """安装进剪映失败；已回滚，剪映草稿库保持原样。"""


# ------------------------------------------------------------------ 警告汇总
_WARNINGS: list[str] = []   # 每次 main() 开头清空；冻结版同进程串行复用（并发见 GL-17）


def reset_warnings() -> None:
    _WARNINGS.clear()


def warnings() -> list[str]:
    return list(_WARNINGS)


def warn(msg: str) -> None:
    """打印并记入汇总：成功时 aicut 会把汇总里的每条再报一次，免得淹没在日志里。"""
    print(f"[warn] {msg}")
    _WARNINGS.append(msg)


def parse_report(output: str) -> dict:
    """从 to_jianying 的输出里取出草稿位置、注册表备份与警告汇总（供 aicut 调用）。"""
    rep: dict = {"warnings": [], "draft_path": None, "backup": None}
    in_warns = False
    header = re.compile(r"^\[!\] \d+ 条警告$")
    for line in output.splitlines():
        if line.startswith(REPORT_DRAFT):
            rep["draft_path"] = line[len(REPORT_DRAFT):].strip()
        elif line.startswith(REPORT_BACKUP):
            rep["backup"] = line[len(REPORT_BACKUP):].strip()
        elif header.match(line):
            in_warns, rep["warnings"] = True, []
        elif in_warns and line.startswith(REPORT_WARN_ITEM):
            rep["warnings"].append(line[len(REPORT_WARN_ITEM):])
        else:
            in_warns = False
    return rep


def print_report(draft_path: Path, backup: Path | None = None) -> None:
    print(f"{REPORT_DRAFT}{draft_path}")
    if backup:
        print(f"{REPORT_BACKUP}{backup}")
    if _WARNINGS:
        print(REPORT_WARN_HEADER.format(n=len(_WARNINGS)))
        for w in _WARNINGS:
            print(f"{REPORT_WARN_ITEM}{w}")


# ------------------------------------------------------------------ 工具
def write_json(path: Path, obj: dict) -> None:
    """原子写紧凑 JSON（唯一临时名，GL-18 同款）。"""
    schema.write_json(path, obj, indent=None)


def us(seconds: float) -> int:
    """秒 → 微秒（剪映时间线统一单位）"""
    return int(round(seconds * 1_000_000))


SUBTITLE_TRACK, CARD_TRACK = "subtitle", "card"   # D2（产品默认）：剪映里两条文本轨的名字
CARD_ALIGN = 5            # 时间轴约定：2=底部字幕、5=居中字幕卡（与 render_preview 一致）
MIN_TEXT_SECONDS = 0.001  # 短于 1ms 的文字段视为无效


def layout_texts(items: list[dict]) -> dict[str, list[dict]]:
    """字幕与字幕卡分两条文本轨；丢弃非正时长；同轨重叠时把后者起点推到前者终点（GL-10）。

    负起点截到 0；被丢弃的逐条警告，被顺延的按轨汇总条数警告（审查修复 8）。
    """
    out: dict[str, list[dict]] = {SUBTITLE_TRACK: [], CARD_TRACK: []}
    shifted = {SUBTITLE_TRACK: 0, CARD_TRACK: 0}
    for t in sorted(items, key=lambda x: (float(x["start"]), float(x["end"]))):
        align = int(t.get("style", {}).get("align", 1))
        track = CARD_TRACK if align == CARD_ALIGN else SUBTITLE_TRACK
        prev_end = out[track][-1]["end"] if out[track] else 0.0
        start = max(float(t["start"]), 0.0, prev_end)
        if float(t["end"]) - start < MIN_TEXT_SECONDS:
            warn(f"跳过时长无效的文字 {t['text'][:20]!r}（{t['start']}–{t['end']}s）")
            continue
        if start > max(float(t["start"]), 0.0):
            shifted = {**shifted, track: shifted[track] + 1}
        out[track] = [*out[track], {**t, "start": start, "end": float(t["end"])}]
    label = {SUBTITLE_TRACK: "字幕", CARD_TRACK: "字幕卡"}
    for track, n in shifted.items():
        if n:
            warn(f"{n} 条{label[track]}与前一条重叠，起点已顺延（显示时间变短）")
    return out


def expected(tl: dict, texts: dict[str, list[dict]] | None = None) -> dict:
    """时间线 → 校验门要核对的数字（视频段数、文字段数、视频终点微秒）。"""
    texts = layout_texts(tl.get("text", [])) if texts is None else texts
    video = tl.get("video", [])
    end = max((us(v["timeline_in"]) + us(v["out"] - v["in"]) for v in video), default=0)
    return {"videos": len(video), "texts": sum(len(v) for v in texts.values()),
            "video_end_us": end}


def safe_name(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        sys.exit(f"非法草稿名：{name!r}")
    return name


# ------------------------------------------------------------------ 生成
def build_staging(tl: dict, staging: Path, name: str,
                  texts: dict[str, list[dict]] | None = None) -> Path:
    """用 pyJianYingDraft 生成 5.9 格式草稿，返回草稿目录。texts 为 layout_texts 结果（可复用）。"""
    try:
        import pyJianYingDraft as draft
        from pyJianYingDraft import trange, trange_seconds
    except ImportError:
        sys.exit("缺少依赖：pip install pyJianYingDraft")

    p = tl["project"]
    staging.mkdir(parents=True, exist_ok=True)
    script = draft.DraftFolder(str(staging)).create_draft(
        name, p["width"], p["height"], fps=p.get("fps", 30), allow_replace=True)

    script.append_track(draft.TrackSpec(draft.TrackType.video))
    if tl.get("audio"):
        script.append_track(draft.TrackSpec(draft.TrackType.audio))
    texts = layout_texts(tl.get("text", [])) if texts is None else texts
    for track_name in (SUBTITLE_TRACK, CARD_TRACK):  # 后追加的在上层：卡片压在字幕上方
        if texts[track_name]:
            script.append_track(draft.TrackSpec(draft.TrackType.text, name=track_name))

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

    for track_name, items in texts.items():
        for t in items:
            st = t.get("style", {})
            align = int(st.get("align", 1))
            # 时间轴里的 align 表示"位置"：2=底部字幕、5=居中字幕卡（与 render_preview 保持一致）
            pos_y = {2: -0.72, 5: 0.10}.get(align, 0.0)
            # 共用绝对终点：避免 us(a)+us(b-a)≠us(b) 造成相邻字幕 1µs 重叠
            script.add_segment(draft.TextSegment(
                t["text"],
                trange_seconds(t["start"], end=t["end"]),
                style=draft.TextStyle(
                    size=float(st.get("size", 8.0)),
                    color=tuple(st.get("color", [1.0, 1.0, 1.0])),
                    align=1,
                    bold=bool(st.get("bold", True)),
                ),
                clip_settings=draft.ClipSettings(transform_y=pos_y)), track_name)

    script.save()
    return staging / name


def bundle_media(draft_dir: Path, final_dir: Path) -> int:
    """把媒体拷进草稿 Resources/，并把 path 改写成**安装后**的绝对路径。

    剪映 Mac 版是沙盒应用（entitlement 只有 ~/Movies 读写），引用草稿目录之外的
    路径会报"暂无访问权限"或静默丢素材，所以默认把媒体打包进 Resources/。
    """
    res = draft_dir / "Resources"
    res.mkdir(parents=True, exist_ok=True)
    final_res = Path(os.path.abspath(final_dir)) / "Resources"  # KI-80：剪映只认绝对路径
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
    """把生成结果套进剪映（jy_version.VERIFIED_SERIES）自己写出的空草稿骨架。

    pyJianYingDraft 产出的是 5.9 结构（materials 只有 46 个分类、缺新版新增的
    顶层字段）。以已验证版本的 template 为骨、生成的 tracks/materials 为肉，
    可以保证结构与剪映自己写出的完全同构，降低"打开后异常"的概率。
    缺模板 = 安装包不完整，直接失败（KI-18，产品决策 D1），不交付 5.9 结构的草稿。
    """
    _require_template(template)
    base = json.loads(template.read_text(encoding="utf-8"))
    gen = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
    for k, v in gen.items():
        if k != "materials":
            base[k] = v
    for k, v in gen["materials"].items():
        if v:
            base["materials"][k] = v
    write_json(draft_dir / "draft_content.json", base)


def macify(draft_dir: Path, name: str, materials_size: int, draft_id: str,
           root: Path, *, runner=subprocess.run) -> dict:
    """补 Mac 版字段并写入口文件 draft_info.json。"""
    content_path = draft_dir / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    now = int(time.time() * 1_000_000)

    # 剪映 11.0 自己写出的空草稿里 platform 指纹就是空串，实测可加载；版本号写已验证版本（D3）
    platform = {"app_id": 0, "app_source": "", "app_version": jy_version.VERIFIED_VERSION,
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
        "draft_fold_path": str(root / name),
        "draft_root_path": str(root),
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
        _make_cover(cover_src, draft_dir / "draft_cover.jpg", runner)
    return {"draft_id": content["id"], "duration": content["duration"]}


def _make_cover(src: Path, dst: Path, runner) -> None:
    """抽首帧做封面：失败只警告（剪映会自己补）；没有 ffmpeg 说明环境坏了，直接报错。"""
    try:
        r = runner(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-frames:v", "1",
                    str(dst)], capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
    except OSError as exc:
        raise InstallError(f"找不到 ffmpeg，无法生成草稿（{exc}）") from exc
    if r.returncode != 0:
        warn(f"草稿封面生成失败（不影响剪辑）：{(r.stderr or '').strip()[-COVER_ERR_TAIL:]}")


# ------------------------------------------------------------------ 草稿根与注册表
def _decode_qt_value(raw: str) -> str:
    """解 Qt INI 的值：去引号、\\xHHHH 按 UTF-16 码元解码（含代理对）；其他转义一律不认。"""
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        raw = raw[1:-1]
    if raw.startswith("@"):
        raise ValueError("Qt 特殊类型值")
    units: list[int] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\":
            units.extend(int.from_bytes(b, "little")
                         for b in _chunks(ch.encode("utf-16-le"), 2))
            i += 1
            continue
        m = re.match(r"x([0-9a-fA-F]{4})", raw[i + 1:])
        if not m:
            raise ValueError(f"不认识的转义 {raw[i:i + 2]!r}")
        units.append(int(m.group(1), 16))
        i += 1 + len(m.group(0))
    text = b"".join(u.to_bytes(2, "little") for u in units).decode("utf-16-le", "surrogatepass")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise ValueError("不成对的 UTF-16 代理")
    return text


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


def _custom_draft_path(home: Path) -> Path | None:
    """读剪映「全局设置 → 草稿位置」（Qt INI 的 currentCustomDraftPath）。

    没有设置文件 / 没有该键 / 值为空 → None（用默认位置）；
    有值但读不了、解不了或不是绝对路径 → InstallError，绝不悄悄退回默认目录（审查修复 3）。
    """
    setting = home / JY_SETTING
    try:
        text = setting.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise InstallError(f"读不了剪映全局设置 {setting}（{exc}），无法确定草稿位置；"
                           "可设置环境变量 AI_CUT_DRAFT_ROOT 指定草稿目录") from exc
    m = re.search(r"^currentCustomDraftPath=(.*)$", text, re.M)
    if not m or m.group(1).strip() in ("", '""'):
        return None
    raw = m.group(1).strip()
    try:
        value = _decode_qt_value(raw)
    except ValueError as exc:
        value = None
        reason = str(exc)
    else:
        reason = "不是绝对路径"
    if value is None or not value.startswith("/"):
        raise InstallError(f"剪映「全局设置 → 草稿位置」的值无法使用（{reason}）：{raw}\n"
                           f"设置文件：{setting}；可设置环境变量 AI_CUT_DRAFT_ROOT 指定草稿目录")
    return Path(value)


def resolve_draft_root(env=None, home: Path | None = None) -> Path:
    """草稿根：AI_CUT_DRAFT_ROOT > 剪映自定义草稿位置 > 默认位置。只算路径，不做存在性检查。"""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if env.get("AI_CUT_DRAFT_ROOT"):
        return Path(env["AI_CUT_DRAFT_ROOT"]).expanduser()
    return _custom_draft_path(home) or home / DEFAULT_DRAFT_ROOT


def load_registry(root: Path) -> dict:
    """读剪映草稿注册表；剪映没装 / 目录不可访问 / 格式不认识都给出可读的 InstallError。"""
    meta = root / ROOT_META_NAME
    if not root.is_dir() or not meta.is_file():
        raise InstallError(JY_MISSING.format(meta=meta))
    try:
        reg = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"剪映草稿注册表读不了（{exc}）：{meta}；未做任何改动") from exc
    if not isinstance(reg, dict) or not isinstance(reg.get("all_draft_store"), list):
        raise InstallError(f"剪映草稿注册表格式不认识：{meta}；未做任何改动")
    return reg


def jianying_running() -> bool:
    return subprocess.run(["pgrep", "-f", "MacOS/VideoFusion-macOS"],
                          capture_output=True).returncode == 0


def build_entry(info: dict, name: str, root: Path, materials_size: int = 0) -> dict:
    """root_meta_info.json 里的一条草稿记录。"""
    now = int(time.time() * 1_000_000)
    return {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": str(root / name / "draft_cover.jpg"),
        "draft_fold_path": str(root / name),
        "draft_id": info["draft_id"],
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False, "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_json_file": str(root / name / "draft_info.json"),
        "draft_name": name, "draft_new_version": "",
        "draft_root_path": str(root),
        "draft_timeline_materials_size": materials_size, "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "", "pippit_extra_info": "", "pippit_id": "",
        "pippit_user_name": "", "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now, "tm_draft_modified": now,
        "tm_draft_removed": 0, "tm_duration": info["duration"],
    }


def with_entry(registry: dict, entry: dict) -> dict:
    """返回新注册表：同名旧条目去掉，新条目放最前（不改入参）。"""
    rest = [e for e in registry["all_draft_store"] if e.get("draft_name") != entry["draft_name"]]
    return {**registry, "all_draft_store": [entry, *rest]}


# ------------------------------------------------------------------ 安装事务
def _is_registered(registry: dict, target: Path) -> bool:
    return any(e.get("draft_fold_path") == str(target) for e in registry["all_draft_store"])


def _is_own_orphan(target: Path, registry: dict) -> bool:
    """上次安装被强杀留下的目录：带安装中标记且未注册。"""
    return (target / INSTALL_MARKER).exists() and not _is_registered(registry, target)


def _ensure_name_free(root: Path, name: str, registry: dict) -> None:
    """同名草稿要在拷媒体之前就报（KI-59）；自家孤儿不算，install() 会清掉。"""
    target = root / name
    if target.exists() and not _is_own_orphan(target, registry):
        raise InstallError(DRAFT_EXISTS.format(target=target))


def _clear_own_orphan(target: Path, registry: dict) -> None:
    """上次安装被强杀留下的目录（带安装中标记且未注册）可以安全清掉。"""
    if _is_own_orphan(target, registry):
        print(f"[warn] 清理上次未完成的安装：{target}")
        shutil.rmtree(target)


def _validate_or_raise(draft: Path, expect: dict | None, *, relocate=None,
                       fail_title: str = "草稿静态校验未通过，已撤销安装") -> None:
    """静态校验门：FAIL → InstallError；WARN 进警告汇总。"""
    from research import validate_draft  # 冻结版为 hiddenimport（ai-cut.spec）
    res = validate_draft.check(str(draft), expect=expect, relocate=relocate)
    if res["fails"]:
        lines = "\n".join(f"  [FAIL] {m}" for m in res["fails"][:VALIDATION_FAIL_LINES])
        more = len(res["fails"]) - VALIDATION_FAIL_LINES
        tail = f"\n  …另有 {more} 条" if more > 0 else ""
        raise InstallError(f"{fail_title}：\n{lines}{tail}")
    if res["warns"]:
        warn(f"静态校验有 {len(res['warns'])} 条 WARN："
             + "；".join(res["warns"][:VALIDATION_WARN_LINES]))
    print(f"校验通过：OK={len(res['oks'])} WARN={len(res['warns'])} FAIL=0")


def _ensure_not_running() -> None:
    if jianying_running():
        raise InstallError(JY_RUNNING)


def _backup_registry(meta: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = meta.with_name(f"{meta.name}.{stamp}.bak")
    i = 2
    while bak.exists():
        bak = meta.with_name(f"{meta.name}.{stamp}-{i}.bak")
        i += 1
    shutil.copy2(meta, bak)
    return bak


def _restore_registry(bak: Path, meta: Path) -> None:
    """用备份还原注册表：先写同目录临时文件再 os.replace，还原过程中断也不会留下半个注册表。"""
    tmp = meta.with_name(f".{meta.name}.{uuid.uuid4().hex}.restore")
    try:
        shutil.copy2(bak, tmp)
        os.replace(tmp, meta)
    finally:
        tmp.unlink(missing_ok=True)


def _prune_backups(root: Path) -> None:
    baks = sorted(root.glob(BACKUP_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in baks[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)


def _place_in_root(draft_dir: Path, tmp: Path, name: str) -> bool:
    """把暂存草稿放到草稿根内的同卷临时目录 tmp；返回 True 表示是改名（暂存目录已被消耗）。

    跨卷时先建 tmp 并**先写安装中标记**再拷内容，任何时候中断留下的半拷目录都认得出是我们的。
    """
    (draft_dir / INSTALL_MARKER).write_text(name, encoding="utf-8")
    try:
        os.rename(draft_dir, tmp)
        return True
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    tmp.mkdir()
    (tmp / INSTALL_MARKER).write_text(name, encoding="utf-8")
    shutil.copytree(draft_dir, tmp, dirs_exist_ok=True)
    return False


def _undo_placement(draft_dir: Path, placed: Path, renamed: bool) -> None:
    """回滚放置：改名来的挪回暂存目录；拷贝来的直接删（暂存原件还在）。报告删了 / 留了什么。"""
    if renamed and placed.exists():
        os.rename(placed, draft_dir)
        print(f"未安装的草稿已挪回暂存目录：{draft_dir}")
    elif placed.exists():
        if not (placed / INSTALL_MARKER).exists():
            raise InstallError(f"{placed} 不带安装中标记，拒绝删除，请人工检查")
        shutil.rmtree(placed)
        print(f"已删除草稿库中未完成的副本：{placed}；暂存目录保留：{draft_dir}")
    (draft_dir / INSTALL_MARKER).unlink(missing_ok=True)


def _rollback(steps: list, original: BaseException) -> None:
    """逐步回滚，每步独立 try；任何一步失败都大声报，并以原始错误为因抛出。"""
    errors = []
    for label, step in steps:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - 回滚要尽量把每一步都做完
            errors.append(f"{label}：{exc}")
    if errors:
        detail = "；".join(errors)
        print(f"[ERROR] 回滚失败：{detail}")
        raise InstallError(f"安装失败（{original}），且回滚失败：{detail}；"
                           "请人工检查剪映草稿库与注册表备份") from original


def install(draft_dir: Path, root: Path, name: str, info: dict, size: int,
            expect: dict | None = None) -> tuple[Path, Path]:
    """放入草稿根 → 校验 → 注册，任何一步失败都回滚到安装前（GL-13 / GL-11）。

    返回 (草稿目录, 注册表备份)。
    """
    registry = load_registry(root)
    target, tmp = root / name, root / f".{name}{TMP_SUFFIX}"
    _clear_own_orphan(target, registry)
    _clear_own_orphan(tmp, registry)
    _ensure_name_free(root, name, registry)
    _ensure_not_running()
    meta = root / ROOT_META_NAME
    bak = _backup_registry(meta)
    state = {"renamed": False, "placed": tmp, "registering": False}
    try:
        state["renamed"] = _place_in_root(draft_dir, tmp, name)
        os.rename(tmp, target)
        state["placed"] = target
        _validate_or_raise(target, expect)
        _ensure_not_running()
        new_registry = with_entry(registry, build_entry(info, name, root, size))
        state["registering"] = True
        write_json(meta, new_registry)
        (target / INSTALL_MARKER).unlink()
    except BaseException as exc:
        steps = []
        if state["registering"]:
            steps.append(("还原注册表", lambda: _restore_registry(bak, meta)))
        steps.append(("撤回草稿目录",
                      lambda: _undo_placement(draft_dir, state["placed"], state["renamed"])))
        _rollback(steps, exc)
        bak.unlink(missing_ok=True)  # 已完整回滚：本次备份没用了
        raise
    if not state["renamed"]:
        shutil.rmtree(draft_dir, ignore_errors=True)  # 跨卷拷贝成功：暂存原件不再需要
    _prune_backups(root)
    print(f"已注册；注册表备份：{bak}")
    return target, bak


# ------------------------------------------------------------------ 入口
def _require_template(template: Path) -> None:
    if not template.exists():
        raise InstallError(TEMPLATE_MISSING.format(series=jy_version.VERIFIED_SERIES,
                                                   path=template))


def _prepare_root(dry_run: bool, name: str) -> Path:
    """花几分钟拷媒体之前先把能提前发现的问题都报出来：模板缺失（dry-run 也查）、
    剪映在跑、草稿库不可用、同名草稿（KI-59）；本机剪映跨大版本只进警告汇总（KI-17）。"""
    root = resolve_draft_root()  # 每次现算：冻结版同进程多次调用、测试隔离都依赖这一点
    _require_template(TEMPLATE)
    if not dry_run:
        _ensure_not_running()
        _ensure_name_free(root, name, load_registry(root))
        if note := jy_version.compat_warning(jy_version.installed_version()):
            warn(note)
    return root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("--name", default="AI粗剪")
    ap.add_argument("--staging", default=str(Path.home() / ".aicut/staging"))
    ap.add_argument("--dry-run", action="store_true",
                    help="只生成到暂存目录，不安装进剪映（仍做静态校验）")
    args = ap.parse_args()

    reset_warnings()
    name = safe_name(args.name)
    try:
        root = _prepare_root(args.dry_run, name)
        tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
        texts = layout_texts(tl.get("text", []))
        expect = expected(tl, texts)
        # KI-80：相对 --staging 会让草稿与 dry-run 校验里的素材路径变成相对路径
        staging = Path(os.path.abspath(Path(args.staging).expanduser()))
        draft_dir = build_staging(tl, staging, name, texts=texts)
        draft_id = normalize(draft_dir)
        size = bundle_media(draft_dir, root / name)
        align_with_template(draft_dir, TEMPLATE)
        info = macify(draft_dir, name, size, draft_id, root)
        print(f"草稿已生成：{draft_dir}（{info['duration'] / 1e6:.2f}s，媒体 {size / 1e6:.1f}MB）")
        if args.dry_run:
            _validate_or_raise(draft_dir, expect, relocate=(str(root / name), str(draft_dir)),
                               fail_title="草稿静态校验未通过")
            print("dry-run：未安装进剪映")
            print_report(draft_dir)
            return
        target, bak = install(draft_dir, root, name, info, size, expect)
    except InstallError as exc:
        sys.exit(str(exc))
    print(f"完成。打开剪映 → 本地草稿 → {name}")
    print_report(target, bak)


if __name__ == "__main__":
    main()
