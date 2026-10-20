# -*- coding: utf-8 -*-
"""aicut 的命令行解析器（从 aicut.py 拆出，KI-55）。

handler 由 aicut.main 每次调用时按全局名现取再传进来，测试对 aicut.cmd_* 的打桩照样生效。
"""
from __future__ import annotations

import argparse
from typing import Callable

from pipeline import secrets, style
from pipeline.llm import DEFAULT_MODEL  # 唯一定义在 llm（L13）

DEFAULT_PRESET = "纪实3min"
NAME_ONLY = ("prepare", "ingest", "analyze", "transcribe", "junk", "brief", "status", "quality",
             "score", "preview")


def _new(sub, handlers: dict[str, Callable]) -> None:
    p = sub.add_parser("new"); p.add_argument("name")
    p.add_argument("--material", required=True); p.add_argument("--title")
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.add_argument("--tone", choices=list(style.TONES))
    p.add_argument("--audience", default=None)
    p.add_argument("--must-lines", dest="must_lines", default=None)
    p.add_argument("--target", default=None, help="成片目标时长（秒），默认用预设")
    p.add_argument("--no-input", dest="no_input", action="store_true",
                   help="不在终端提问（GUI 调用时使用）")
    p.set_defaults(fn=handlers["new"])


def _project_commands(sub, handlers: dict[str, Callable]) -> None:
    for name in ("run", "build"):  # KI-16：run 有 shots.json 时直接调 cmd_build
        p = sub.add_parser(name); p.add_argument("name"); p.set_defaults(fn=handlers[name])
        p.add_argument("--version"); p.add_argument("--no-draft", action="store_true")
        p.add_argument("--windows", action="store_true", help="晋升后同时打 Windows 剪映包")
        p.add_argument("--require-preview", dest="require_preview", action="store_true",
                       help="只晋升已生成的当前预览片，过期就停（GUI 用）")
    for name in NAME_ONLY:
        p = sub.add_parser(name); p.add_argument("name"); p.set_defaults(fn=handlers[name])

    p = sub.add_parser("text"); p.add_argument("name")
    p.add_argument("--batch", type=int, default=40)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.set_defaults(fn=handlers["text"])

    p = sub.add_parser("export"); p.add_argument("name")
    p.add_argument("--timeline", default=None)
    p.add_argument("--package-name", dest="package_name", default=None)
    p.add_argument("-o", "--out", default="dist")
    p.set_defaults(fn=handlers["export"])

    p = sub.add_parser("select"); p.add_argument("name")
    p.add_argument("--target", default=None, help="改目标时长（秒）后只重跑选段")
    p.add_argument("--manual", choices=("keep", "replace"), default="keep",
                   help="手动分镜表：keep 保留我的修改（默认）/ replace 备份后用新的 AI 选段覆盖")
    p.set_defaults(fn=handlers["select"])

    p = sub.add_parser("questions"); p.add_argument("name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=handlers["questions"])

    p = sub.add_parser("summary"); p.add_argument("name")
    p.add_argument("--model", default=DEFAULT_MODEL)  # KI-83
    p.set_defaults(fn=handlers["summary"])

    p = sub.add_parser("scenes"); p.add_argument("name")
    p.add_argument("--threshold", type=float, default=8.0)
    p.set_defaults(fn=handlers["scenes"])

    p = sub.add_parser("clean"); p.add_argument("name")  # KI-33
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="只列出，不删除")
    p.set_defaults(fn=handlers["clean"])

    p = sub.add_parser("calibrate"); p.add_argument("name")
    p.add_argument("--tone", choices=list(style.TONES))
    p.add_argument("--audience")
    p.add_argument("--must-lines", dest="must_lines")
    p.add_argument("--show", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(fn=handlers["calibrate"])


def build_parser(handlers: dict[str, Callable]) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="aicut 视频剪辑流水线")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _new(sub, handlers)
    _project_commands(sub, handlers)

    p = sub.add_parser("config"); p.set_defaults(fn=handlers["config"])
    p.add_argument("action", nargs="?", choices=["set", "unset", "consent"])
    p.add_argument("provider", nargs="?", default="mediakit",
                   choices=list(secrets.PROVIDERS))

    p = sub.add_parser("list"); p.set_defaults(fn=handlers["list"])
    return ap
