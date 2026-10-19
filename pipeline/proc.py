# -*- coding: utf-8 -*-
"""打包运行时：资源路径与"冻结后怎么跑子任务"。

GUI 的任务一律是子进程（GL-17：可取消、不共享 stdout/sys.argv）：
开发时用解释器跑 aicut.py / pipeline 脚本；打包成 .app 后没有独立解释器，
就让 App 自己带标记重启（`cli_cmd` / `module_cmd`），入口最先调用 `dispatch` 分发。
aicut 子进程内部（单线程）仍可用 `run_inprocess` 同进程跑 pipeline 模块。
"""
from __future__ import annotations

import contextlib
import importlib
import io
import os
import runpy
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from pipeline import pyver

FROZEN = bool(getattr(sys, "frozen", False))
MEIPASS = getattr(sys, "_MEIPASS", None)
CLI_FLAG = "--aicut-cli"        # 冻结 App 自启：跑一条 aicut 子命令
MODULE_FLAG = "--aicut-module"  # 冻结 App 自启：以 __main__ 跑某个 pipeline 模块
ALLOWED_MODULES = frozenset({"pipeline.to_jianying"})  # --aicut-module 只认这些
PARENT_PID_ENV = "AI_CUT_PARENT_PID"  # 剪辑台起任务时注入；任务进程据此发现剪辑台没了
WATCHDOG_INTERVAL_S = 1.0  # 多久看一眼父进程还在不在
WATCHDOG_GRACE_S = 5.0     # 发 SIGTERM 后等多久补 SIGKILL（与 gui/jobs.CANCEL_GRACE_S 一致）


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


# ------------------------------------------------------------------ 自启子进程（GL-17 / GL-14）
def cli_cmd(args: list[str]) -> list[str]:
    """一条 aicut 命令的子进程 argv：开发=解释器+aicut.py，打包=App 自身+标记。"""
    if FROZEN:
        return [sys.executable, CLI_FLAG, *args]
    return [sys.executable, str(app_root() / "aicut.py"), *args]


# 开发态跑 pipeline 模块（KI-15）：不能以脚本路径运行，否则 pipeline/ 成为 sys.path[0]，
# pipeline/select.py、secrets.py 会遮蔽标准库（Homebrew Python 下 subprocess → import select 直接崩）。
# `-c` 时 sys.path[0] 是 ''（cwd）：3.11+ 用 -P 不加它；更旧的解释器不认 -P，由引导代码先把它剔掉
# （import sys 是内建模块，不会被遮蔽），再导入 runpy。仓库根 append 到末尾，免得 packaging/ 遮蔽 PyPI 的 packaging。
DEV_BOOTSTRAP = ("import sys; sys.path[:] = [p for p in sys.path if p not in ('', '.')]; "
                 "import runpy; sys.path.append(sys.argv.pop(1)); "
                 "runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)")


def dev_module_cmd(python: str, module_name: str, args: list[str],
                   root: Path | None = None) -> list[str]:
    """开发态以 __main__ 跑 module_name 的子进程 argv（任意 cwd 可用，相对路径参数含义不变）。"""
    safe_path = ["-P"] if pyver.supports_safe_path(python) else []
    return [python, *safe_path, "-c", DEV_BOOTSTRAP, str(root or app_root()), module_name, *args]


def module_cmd(module_name: str, args: list[str]) -> list[str]:
    """跑一个 pipeline 模块的子进程 argv：打包后 App 自启（不能用 sys.executable 跑 .py），开发态走引导。"""
    if module_name not in ALLOWED_MODULES:
        raise ValueError(f"不允许以子进程运行的模块：{module_name}")
    if FROZEN:
        return [sys.executable, MODULE_FLAG, module_name, *args]
    return dev_module_cmd(sys.executable, module_name, args)


def _line_buffered_stdio() -> None:
    """窗口化构建下 stdout 可能是块缓冲或 None；GUI 要逐行看日志。"""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(fd, "w", encoding="utf-8", errors="replace",
                                    buffering=1, closefd=False))
        elif hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _run_module_main(module_name: str, rest: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = [module_name, *rest]
    try:
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        return exit_code(exc, sys.stderr)  # sys.exit("文字")：文字不能丢（GL-12）
    finally:
        sys.argv = old_argv
    return 0


def dispatch(argv: list[str]) -> int | None:
    """App 入口最先调用：带标记就当子任务跑完并返回退出码，否则返回 None 继续开窗口。"""
    if len(argv) < 2 or argv[1] not in (CLI_FLAG, MODULE_FLAG):
        return None
    _line_buffered_stdio()
    from pipeline import applog  # 打包版的任务子进程：窗口化 App 没有终端，只能靠 cli.log（GL-19）
    applog.setup("cli")
    ensure_bundled_path()
    start_parent_watchdog()
    if argv[1] == CLI_FLAG:
        from aicut import run_cli
        return run_cli(argv[2:])
    if len(argv) < 3 or argv[2] not in ALLOWED_MODULES:
        print(f"用法：{MODULE_FLAG} <{'|'.join(sorted(ALLOWED_MODULES))}> [参数…]",
              file=sys.stderr)
        return 2
    return _run_module_main(argv[2], argv[3:])


# ------------------------------------------------------------------ 父进程看门狗（不留孤儿任务）
def _group_members(pgid: int) -> list[int]:
    try:
        out = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def _kill_own_group() -> None:
    """先给同组其它进程（ffmpeg 等）发 SIGTERM 让它们体面退出，宽限期后 SIGKILL 整组（含自己）。

    信号处理函数只能在主线程设置，看门狗在子线程里，所以不能先忽略自己的 SIGTERM，只能这样分两步。
    """
    pgid = os.getpgrp()
    if pgid != os.getpid():  # 不是自己的进程组（例如终端里直接跑），只退自己
        os._exit(1)
    for pid in _group_members(pgid):
        if pid != os.getpid():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
    time.sleep(WATCHDOG_GRACE_S)
    os.killpg(pgid, signal.SIGKILL)


def _watch_parent(parent_pid: int) -> None:
    while os.getppid() == parent_pid:
        time.sleep(WATCHDOG_INTERVAL_S)
    _kill_own_group()


def start_parent_watchdog() -> bool:
    """剪辑台起的任务进程：剪辑台崩溃 / 被强杀（父进程变了）就带着整组退出。

    环境变量用后即删，aicut 再拉起的子进程（如 --aicut-module）不会误判。
    """
    raw = os.environ.pop(PARENT_PID_ENV, None)
    if not raw or not raw.isdigit():
        return False
    threading.Thread(target=_watch_parent, args=(int(raw),), daemon=True,
                     name="aicut-parent-watchdog").start()
    return True
