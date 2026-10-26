#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 timeline.json 渲染审片用的预览片（ffmpeg，不依赖剪映）。

与 to_jianying.py 共用同一份 timeline.json，保证"预览"和"剪映工程"内容一致。
支持：多镜头硬切拼接、原声保留、按时间轴叠字幕/字幕卡。

字幕走 drawtext 的 textfile + expansion=none（KI-13/KI-76）：文字不经过滤镜图转义，引号、%、冒号原样显示。
无音轨镜头补静音，所有音轨统一成 48k 立体声（KI-14）。

用法（在仓库根运行）：
    python -m pipeline.render_preview projects/xxx/output/v1/timeline.json -o projects/xxx/output/v1/preview.mp4
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # 脚本方式运行时可导入 pipeline.encode；append 防遮蔽三方包

from pipeline import encode, media_io, plat  # noqa: E402

SAMPLE_RATE = 48000
AUDIO_NORM = f"aresample={SAMPLE_RATE},aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
SAFE_FILTER_PATH = re.compile(r"[A-Za-z0-9/._-]+")  # 滤镜图里不用转义就能放的路径
FALLBACK_TMP = "/tmp"
# Windows：盘符路径（反斜杠 / 冒号交给 _filter_path 转义），但只认纯 ASCII、无空格——中文用户名的临时目录 ffmpeg 读不稳
SAFE_WIN_FILTER_PATH = re.compile(r"[A-Za-z]:[\\/][A-Za-z0-9\\/._-]*")
WIN_FALLBACK_SUBDIR = Path("Documents") / "aicut-tmp"  # 相对 %PUBLIC%
TEXT_DIR_PREFIX = "aicut-preview-"

# 首选简体黑体（KI-73 / D10）：drawtext 只能取 .ttc 第 0 个字形——
#   Hiragino Sans GB #0 = W3 简体；STHeiti Medium #0 = 繁体字形；新版 macOS 的 PingFang 已不在 /System/Library/Fonts
MAC_FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",                 # 旧版 macOS
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
]
WIN_FONT_FILES = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"]  # 微软雅黑 / 雅黑粗体 / 黑体 / 宋体


def win_font_candidates(env=None) -> list[str]:
    fonts = plat.windows_dir(env) / "Fonts"
    return [str(fonts / name) for name in WIN_FONT_FILES]


FONT_CANDIDATES: list[str] | None = None  # 测试覆盖点；None = 按当前平台取 font_candidates()


def font_candidates() -> list[str]:
    """本平台的字体候选（调用时才看平台，测试可用 plat.IS_WIN 切换）。"""
    if FONT_CANDIDATES is not None:
        return FONT_CANDIDATES
    return win_font_candidates() if plat.IS_WIN else MAC_FONT_CANDIDATES


def _filter_path(p) -> str:
    """路径放进 drawtext 的 fontfile='…' / textfile='…' 前的转义：反斜杠 → /，: → \\:，' → '\\''（收引号、转义、再开引号）。
    Mac 上的安全路径（字母数字 / . _ - 与空格）原样返回。"""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")


def pick_font() -> str:
    for f in font_candidates():
        if Path(f).exists():
            return f
    sys.exit("找不到可用中文字体")


def text_dir_base() -> str:
    """字幕文件放哪：$TMPDIR 含滤镜图元字符（: , [ ; 空格 …）时退回 /tmp；
    Windows 上临时目录不是纯 ASCII 无空格（如中文用户名）时退回 %PUBLIC%\\Documents\\aicut-tmp。"""
    base = tempfile.gettempdir()
    if not plat.IS_WIN:
        return base if SAFE_FILTER_PATH.fullmatch(base) else FALLBACK_TMP
    if SAFE_WIN_FILTER_PATH.fullmatch(base):
        return base
    # 注意：%PUBLIC% 下的文件本机其他用户也读得到——这里只放字幕文字，且预览渲染完就随临时目录删除
    fallback = plat.public_dir() / WIN_FALLBACK_SUBDIR
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:  # 建不出来（权限 / 磁盘）：退回原临时目录，至少不比改动前差
        return base
    return str(fallback)


def _sorted_texts(texts: list[dict]) -> list[dict]:
    return sorted(texts, key=lambda x: x["start"])


def subtitle_files(texts: list[dict], text_dir: Path) -> list[Path]:
    """每条字幕写成一个 UTF-8 文件（按 start 排序），drawtext 用 textfile 读入，不经过任何转义。

    末尾不加换行：drawtext 会把它渲染成多出来的一行。
    """
    out = []
    for i, t in enumerate(_sorted_texts(texts)):
        p = Path(text_dir) / f"{i}.txt"
        p.write_text(t["text"], encoding="utf-8")
        out.append(p)
    return out


def _audio_branch(i: int, s: dict, dur: float, has: bool) -> str:
    """有音轨：裁剪原声；没有：补同长静音（KI-14）。都统一成 48k 立体声，免得整片跟着首段走。"""
    src = (f"[{i}:a]atrim=start={s['in']}:duration={dur},asetpts=PTS-STARTPTS"
           if has else f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={dur}")
    return f"{src},{AUDIO_NORM}[a{i}]"


def build(tl: dict, *, text_paths: list[Path], has_audio: list[bool]) -> tuple[str, int]:
    """滤镜图。text_paths 与按 start 排序后的 tl["text"] 一一对应；has_audio 与按 timeline_in 排序后的镜头对应。"""
    W, H = tl["project"]["width"], tl["project"]["height"]
    fps = tl["project"].get("fps", 30)
    segs = sorted(tl["video"], key=lambda s: s["timeline_in"])

    parts, vlabels, alabels = [], [], []
    for i, s in enumerate(segs):
        dur = s["out"] - s["in"]
        parts.append(
            f"[{i}:v]trim=start={s['in']}:duration={dur},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={fps},setsar=1[v{i}]"
        )
        parts.append(_audio_branch(i, s, dur, has_audio[i]))
        vlabels.append(f"[v{i}]")
        alabels.append(f"[a{i}]")
    # concat 的输入必须"视频/音频"交替，不能先把视频标签全列完
    interleaved = "".join(v + a for v, a in zip(vlabels, alabels))
    parts.append(interleaved + f"concat=n={len(segs)}:v=1:a=1[vc][ac]")

    chain = "[vc]"
    font = pick_font() if tl.get("text") else ""  # 只选一次：所有字幕同一字体
    for i, (t, path) in enumerate(zip(_sorted_texts(tl.get("text", [])), text_paths)):
        st = t.get("style", {})
        size = int(st.get("size_px") or st.get("size", 7.0) * 9)
        color = st.get("color", [1, 1, 1])
        hexcolor = "0x" + "".join(f"{int(c * 255):02X}" for c in color[:3])
        align = st.get("align", 1)
        # 2=底部字幕（避开快手/抖音 UI），5=居中字幕卡
        y = {2: "h*0.74", 5: "h*0.42"}.get(align, "(h-text_h)/2")
        parts.append(
            f"{chain}drawtext=fontfile='{_filter_path(font)}':textfile='{_filter_path(path)}':expansion=none:"
            f"fontsize={size}:fontcolor={hexcolor}:"
            f"borderw={max(2, size // 16)}:bordercolor=black@0.85:"
            f"x=(w-text_w)/2:y={y}:"
            f"enable='between(t,{t['start']},{t['end']})'[vt{i}]"
        )
        chain = f"[vt{i}]"
    parts.append(f"{chain}format=yuv420p[vout]")
    return ";\n".join(parts), len(segs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("timeline")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
    segs = sorted(tl["video"], key=lambda s: s["timeline_in"])
    try:
        audio = [media_io.has_audio(Path(s["source"])) for s in segs]
        with tempfile.TemporaryDirectory(prefix=TEXT_DIR_PREFIX, dir=text_dir_base()) as tmp:
            fc, n = build(tl, text_paths=subtitle_files(tl.get("text", []), Path(tmp)),
                          has_audio=audio)
            inputs = [a for s in segs for a in ("-i", s["source"])]
            print(f"渲染 {n} 个镜头 → {args.out}")
            # 原子写出：独立运行也不留半成品。完成标记由调用方负责（aicut 传入的 -o 已是它的临时文件）
            with media_io.atomic_output(Path(args.out), mark=False) as out:
                media_io.run_ffmpeg([*inputs, "-filter_complex", fc,
                                     "-map", "[vout]", "-map", "[ac]",
                                     *encode.h264_args("preview"),
                                     "-c:a", "aac", "-b:a", "192k",
                                     "-movflags", "+faststart", str(out)])
    except media_io.MediaError as exc:
        sys.exit(f"预览片渲染失败：{exc}")
    total = sum(s["out"] - s["in"] for s in segs)
    print(f"完成：{total:.1f}s")


if __name__ == "__main__":
    main()
