# -*- coding: utf-8 -*-
"""「处理素材」前的就绪检查（GL-02）：命令行和剪辑台共用一套判断。

缺 Key 必须在开始前一次说清，不能跑到一半才失败，更不能静默跳过文本分析。
已经转写过的项目不再需要语音转写的 Key。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import secrets

TRANSCRIPT_RAW = "transcript_raw.json"  # 与 aicut.cmd_transcribe 的跳过条件一致
# 「处理素材」依次跑的步骤（aicut.cmd_<名>），每段计时进 work/timings.json
PREPARE_STEPS = ("ingest", "transcribe", "analyze", "text", "junk", "scenes", "quality",
                 "score", "summary", "questions", "select", "brief")
# `aicut status` 逐项列出的产物（标签, 相对项目目录的路径）
STATUS_ARTIFACTS = (
    ("素材台账", "work/materials.json"), ("音轨", "work/audio/asr.wav"),
    ("转写", "work/transcript_raw.json"), ("分段文稿", "work/transcript.md"),
    ("声音特征 (a)", "work/segments_audio.json"), ("文本标注 (b)", "work/segments_text.json"),
    ("分析代理", "work/proxy.mp4"), ("废片表", "work/junk_report.csv"),
    ("镜头切分 (c)", "work/shots_visual.json"), ("三档判定", "work/segments_scored.json"),
    ("内容摘要", "work/content_summary.json"), ("决策问题", "work/questions.json"),
    ("人工裁决", "work/overrides.json"), ("策划分派单", "work/brief.md"),
    ("分镜表", "shots.json"), ("选段时间线", "work/shots-selected.json"),
)


def needed_keys(work: Path) -> list[str]:
    need = [] if (Path(work) / TRANSCRIPT_RAW).exists() else ["mediakit"]
    return [*need, "deepseek"]


def missing_keys(work: Path) -> list[str]:
    """处理这个项目还缺哪些 Key（provider 名，顺序同 secrets.PROVIDERS）。"""
    return [k for k in needed_keys(work) if not secrets.get(k)]


def describe(providers: list[str]) -> str:
    """「语音转写（火山引擎）MEDIAKIT_API_KEY、…」：界面名 + 环境变量名，命令行和界面都看得懂。"""
    return "、".join(f"{secrets.PROVIDER_LABELS[k]['label']} {secrets.ENV_KEYS[k]}"
                    for k in providers)
