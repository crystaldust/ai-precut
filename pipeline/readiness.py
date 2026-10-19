# -*- coding: utf-8 -*-
"""「处理素材」前的就绪检查（GL-02）：命令行和剪辑台共用一套判断。

缺 Key 必须在开始前一次说清，不能跑到一半才失败，更不能静默跳过文本分析。
已经转写过的项目不再需要语音转写的 Key。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import secrets

TRANSCRIPT_RAW = "transcript_raw.json"  # 与 aicut.cmd_transcribe 的跳过条件一致


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
