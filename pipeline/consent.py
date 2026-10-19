# -*- coding: utf-8 -*-
"""首次使用的「数据外发告知」确认记录（PRD §7，GL-02）。

存在配置目录（与凭证同处），不进项目文件；告知内容变了就提升 CONSENT_VERSION，
用户需要重新确认。剪辑台（gui/settings.py）和命令行（aicut.py）共用这一份记录：
任何会把数据发到云端的步骤之前都先 accepted()。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline import schema, secrets

CONSENT_VERSION = 1
FILENAME = "consent.json"

# 命令行版告知文案（剪辑台的同款文案在 gui/static/settings.js 顶部，改一处要同步另一处）
NOTICE_TITLE = "使用前请知悉：哪些数据会发到云端"
NOTICE_LINES = (
    "原片和画面不会离开这台电脑。为了完成粗剪，会有两类数据发到云端：",
    "  · 素材的音轨（16kHz 单声道）→ 火山引擎语音识别，用于转写成文字",
    "  · 转写出的文字 → DeepSeek，用于理解内容、找出重要片段",
    "两个服务的 API Key 只保存在本机钥匙串，不会写进日志或项目文件。",
)
CLI_REQUIRED_MSG = ("这一步会把数据发到云端（音轨 → 火山引擎，文字 → DeepSeek），"
                    "请先阅读外发说明：运行 `uv run python aicut.py config consent`，"
                    "或在剪辑台里点「我知道了，继续」")


def _path() -> Path:
    return secrets.config_dir() / FILENAME


def accepted() -> bool:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("version") == CONSENT_VERSION


def accept() -> None:
    schema.write_json(_path(), {
        "version": CONSENT_VERSION,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
