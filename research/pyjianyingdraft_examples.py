#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pyjianyingdraft_examples.py —— pyJianYingDraft 0.3.1 的 5 段可直接运行示例

每个示例单独建一个草稿目录，互不干扰。运行前准备好两个素材：
    ffmpeg -y -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=10" \
           -c:v libx264 -pix_fmt yuv420p /tmp/media/testsrc_10s.mp4
    ffmpeg -y -f lavfi -i "sine=frequency=440:duration=10" -c:a aac /tmp/media/tone_10s.m4a

运行：
    python3 pyjianyingdraft_examples.py --root /tmp/libout --video ... --audio ...

注意：0.3.1 的轨道 API 是 append_track(TrackSpec(...)) -> TrackRef，
老教程里的 add_track(TrackType.video, "名字") 已经不存在。
"""
import argparse
import os

from pyJianYingDraft import (
    AudioSegment, ClipSettings, DraftFolder, ScriptFile, TextBorder, TextSegment,
    TextStyle, TrackSpec, TrackType, TransitionType, VideoSegment, trange,
)


# ---------------------------------------------------------------- 示例 1
def ex1_video_with_trim(folder: DraftFolder, video: str, name: str) -> ScriptFile:
    """视频轨 + 入出点裁剪（source_timerange）：取素材第 2s 起 3s，放到时间线 0s 处"""
    draft = folder.create_draft(name, 1920, 1080, fps=30, allow_replace=True)
    track = draft.append_track(TrackSpec(TrackType.video, "主视频"))
    seg = VideoSegment(
        video,
        trange("0s", "3s"),                 # target_timerange：时间线上的位置与长度
        source_timerange=trange("2s", "3s"),  # 从素材第 2 秒开始取 3 秒
    )
    draft.add_segment(seg, track)
    draft.save()
    return draft


# ---------------------------------------------------------------- 示例 2
def ex2_audio(folder: DraftFolder, audio: str, name: str) -> ScriptFile:
    """音频轨 + 音量 + 淡入淡出"""
    draft = folder.create_draft(name, 1920, 1080, fps=30, allow_replace=True)
    track = draft.append_track(TrackSpec(TrackType.audio, "背景音乐"))
    seg = AudioSegment(audio, trange("0s", "5s"), volume=0.35)
    seg.add_fade("0.5s", "0.5s")            # 淡入 / 淡出（注意：只认 h/m/s，"500ms" 会报错）
    draft.add_segment(seg, track)
    draft.save()
    return draft


# ---------------------------------------------------------------- 示例 3
def ex3_text(folder: DraftFolder, name: str) -> ScriptFile:
    """字幕文本轨：字号/颜色/居中/描边/位置"""
    draft = folder.create_draft(name, 1920, 1080, fps=30, allow_replace=True)
    track = draft.append_track(TrackSpec(TrackType.text, "字幕"))
    seg = TextSegment(
        "这是程序生成的字幕",
        trange("0.5s", "2.5s"),
        style=TextStyle(size=12.0, color=(1.0, 1.0, 0.0), align=1),
        border=TextBorder(),
        clip_settings=ClipSettings(transform_y=-0.72),  # y=-0.72 ≈ 画面下缘
    )
    draft.add_segment(seg, track)
    draft.save()
    return draft


# ---------------------------------------------------------------- 示例 4
def ex4_transition(folder: DraftFolder, video: str, name: str) -> ScriptFile:
    """两段相邻视频 + 它们之间的转场（转场挂在**前一段**的 extra_material_refs 上）"""
    draft = folder.create_draft(name, 1920, 1080, fps=30, allow_replace=True)
    track = draft.append_track(TrackSpec(TrackType.video, "主视频"))
    a = VideoSegment(video, trange("0s", "2s"), source_timerange=trange("0s", "2s"))
    b = VideoSegment(video, trange("2s", "2s"), source_timerange=trange("5s", "2s"))
    a.add_transition(TransitionType.叠化)   # 叠化；TransitionType 共 453 个值
    draft.add_segment(a, track)
    draft.add_segment(b, track)
    draft.save()
    return draft


# ---------------------------------------------------------------- 示例 5
def ex5_multitrack(folder: DraftFolder, video: str, name: str) -> ScriptFile:
    """多轨道：主轨 + 画中画 + 字幕 + 音频，四条轨一次建好"""
    draft = folder.create_draft(name, 1920, 1080, fps=30, allow_replace=True)
    refs = draft.append_tracks([
        TrackSpec(TrackType.video, "主视频"),
        TrackSpec(TrackType.video, "画中画"),
        TrackSpec(TrackType.text, "字幕"),
        TrackSpec(TrackType.audio, "音乐"),
    ])
    main, pip, text, audio = refs

    draft.add_segment(VideoSegment(video, trange("0s", "4s"),
                                   source_timerange=trange("1s", "4s")), main)
    draft.add_segment(VideoSegment(video, trange("1s", "2s"),
                                   clip_settings=ClipSettings(scale_x=0.35, scale_y=0.35,
                                                              transform_x=0.5, transform_y=0.5)), pip)
    draft.add_segment(TextSegment("画中画演示", trange("0s", "3s"),
                                  style=TextStyle(size=10.0, align=0)), text)
    if os.path.exists(args.audio):
        draft.add_segment(AudioSegment(args.audio, trange("0s", "4s"), volume=0.5), audio)
    draft.save()
    return draft


def main() -> None:
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp/libout", help="草稿根目录")
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", default="")
    args = ap.parse_args()
    os.makedirs(args.root, exist_ok=True)
    folder = DraftFolder(args.root)

    ex1_video_with_trim(folder, args.video, "EX1_视频裁剪")
    ex2_audio(folder, args.audio or args.video, "EX2_音频")
    ex3_text(folder, "EX3_字幕")
    ex4_transition(folder, args.video, "EX4_转场")
    ex5_multitrack(folder, args.video, "EX5_多轨道")

    for n in ("EX1_视频裁剪", "EX2_音频", "EX3_字幕", "EX4_转场", "EX5_多轨道"):
        p = os.path.join(args.root, n)
        print("[ok]", n, sorted(os.listdir(p)))


if __name__ == "__main__":
    main()
