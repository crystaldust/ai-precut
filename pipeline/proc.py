# -*- coding: utf-8 -*-
"""打包运行时：资源路径与"冻结后怎么跑子任务"。

开发时脚本以子进程执行（隔离好、日志实时）；打包成 .app 后没有可用的
Python 解释器路径，改为**同进程导入执行**，并把输出捕获进任务日志。
"""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
import traceback
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
MEIPASS = getattr(sys, "_MEIPASS", None)


def app_root() -> Path:
    """代码/资源根目录：打包后在 _MEIPASS，开发时在仓库根。"""
    if MEIPASS:
        return Path(MEIPASS)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)


def user_data_root() -> Path:
    """用户数据（项目、临时文件）必须可写，不能放在 .app 里。"""
    env = os.environ.get("AI_CUT_PROJECTS")
    if env:
        return Path(env).expanduser()
    if FROZEN:
        return Path.home() / "Documents" / "AI粗剪"
    return app_root() / "projects"


def bundled_bin() -> Path | None:
    """App 内置的 ffmpeg/ffprobe 目录。"""
    d = resource_path("bin")
    return d if (d / "ffmpeg").exists() else None


def ensure_bundled_path() -> None:
    """把内置二进制目录加到 PATH 最前面，让所有 subprocess 都能找到。"""
    bin_dir = bundled_bin()
    if not bin_dir:
        return
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) not in parts:
        os.environ["PATH"] = os.pathsep.join([str(bin_dir), *parts])


def run_inprocess(module_name: str, argv: list[str]) -> tuple[int, str]:
    """导入模块并以 argv 运行它的 main()，返回 (退出码, 输出)。"""
    out = io.StringIO()
    old_argv = sys.argv
    sys.argv = [module_name, *argv]
    code = 0
    try:
        module = importlib.import_module(module_name)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            module.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    except Exception:  # noqa: BLE001 - 打包环境里必须把错误变成日志
        code = 1
        out.write(traceback.format_exc())
    finally:
        sys.argv = old_argv
    return code, out.getvalue()
