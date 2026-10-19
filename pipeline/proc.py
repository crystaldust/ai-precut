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


def exit_code(exc: SystemExit, out=None) -> int:
    """SystemExit → 退出码。sys.exit("文字") 按 Python 语义记 1，并把文字写进 out（GL-12）。"""
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):  # bool 是 int 的子类：True → 1
        return int(code)
    if out is not None:
        out.write(f"{code}\n")
    return 1


def run_inprocess(module_name: str, argv: list[str]) -> tuple[int, str]:
    """导入模块并以 argv 运行它的 main()，返回 (退出码, 输出)。

    main() 返回 int 时视为退出码（validate_draft.main 返回 1 表示 FAIL，GL-11）。
    """
    out = io.StringIO()
    old_argv = sys.argv
    sys.argv = [module_name, *argv]
    code = 0
    try:
        module = importlib.import_module(module_name)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            ret = module.main()
        if isinstance(ret, int):
            code = int(ret)
    except SystemExit as exc:
        code = exit_code(exc, out)
    except Exception:  # noqa: BLE001 - 打包环境里必须把错误变成日志
        code = 1
        out.write(traceback.format_exc())
    finally:
        sys.argv = old_argv
    return code, out.getvalue()
