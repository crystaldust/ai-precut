# -*- coding: utf-8 -*-
"""剪辑台 · 支持：一键导出诊断包（GL-19）与「关于 / 第三方许可」（GL-04，FFmpeg 合规清单第 10 条）。

路由入口 handle_get / handle_post 返回 (状态码, JSON)，不是本模块的路径返回 None；
访问控制（Host / Origin / token）在 server._deny_reason 里统一做完才会走到这里。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from pipeline import applog, diagnostics, proc

NOTICES_FILE = "THIRD-PARTY-NOTICES.txt"
NOTICES_MISSING = "（没有找到第三方许可文件，请联系开发者）"
DIAG_FAILED_MSG = "导出失败：{reason}"
REVEAL_FAILED_MSG = "诊断包已生成，但没能在访达中打开，请到「下载」文件夹里找"
BAD_PROJECT_MSG = "项目名不合法"
LOG = applog.get("gui")


def notices_path() -> Path:
    """打包版在 App 资源的 licenses/ 下（ai-cut.spec datas），开发版在 packaging/。"""
    if proc.FROZEN:
        return proc.resource_path("licenses", NOTICES_FILE)
    return proc.app_root() / "packaging" / NOTICES_FILE


def reveal(path: Path) -> bool:
    """在访达中选中文件（测试替换点）；返回是否成功。"""
    try:
        r = subprocess.run(["open", "-R", str(path)], capture_output=True, text=True)
    except OSError:
        return False
    if r.returncode != 0:
        LOG.warning("访达中选中诊断包失败：退出码 %s", r.returncode)
    return r.returncode == 0


def about_payload() -> dict:
    try:
        text = notices_path().read_text(encoding="utf-8")
    except OSError:
        text = NOTICES_MISSING
    return {"version": diagnostics.app_version(), "notices": text}


def export_diagnostics(body: dict, resolve: Callable[[str], Path]) -> tuple[int, dict]:
    name = body.get("project")
    pdir = None
    if name not in (None, ""):
        if not isinstance(name, str):
            return 400, {"error": BAD_PROJECT_MSG}
        try:
            pdir = resolve(name)  # 与其它路由同一套项目名白名单 + 存在性校验
        except FileNotFoundError as exc:
            return 404, {"error": str(exc)}
        except ValueError as exc:
            return 400, {"error": str(exc)}
    applog.register_known_secrets()  # 不弹钥匙串：只登记环境变量 / 凭证文件里的 Key
    try:
        path = diagnostics.build_bundle(diagnostics.default_out_dir(), pdir)
    except OSError as exc:
        LOG.exception("诊断包导出失败")
        return 500, {"error": DIAG_FAILED_MSG.format(reason=exc.strerror or type(exc).__name__)}
    try:
        revealed = bool(reveal(path))
    except OSError:  # 包已经生成，只是访达没打开：仍算成功
        LOG.warning("访达中选中诊断包失败", exc_info=True)
        revealed = False
    body = {"ok": True, "name": path.name, "folder": path.parent.name, "revealed": revealed}
    return 200, body if revealed else {**body, "message": REVEAL_FAILED_MSG}


def handle_get(path: str) -> tuple[int, dict] | None:
    return (200, about_payload()) if path == "/api/about" else None


def handle_post(path: str, body: dict,
                resolve: Callable[[str], Path]) -> tuple[int, dict] | None:
    return export_diagnostics(body, resolve) if path == "/api/diagnostics" else None
