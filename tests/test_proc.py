import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pipeline import proc
from platform_marks import posix_only


def test_app_root_points_to_repo_in_dev():
    root = proc.app_root()
    assert (root / "pipeline").is_dir()


def test_user_data_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_CUT_PROJECTS", str(tmp_path))
    assert proc.user_data_root() == tmp_path


def test_user_data_root_dev_default_is_repo_projects(monkeypatch):
    monkeypatch.delenv("AI_CUT_PROJECTS", raising=False)
    monkeypatch.setattr(proc, "FROZEN", False)
    assert proc.user_data_root() == proc.app_root() / "projects"


def test_user_data_root_frozen_default_is_documents(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_CUT_PROJECTS", raising=False)
    monkeypatch.setattr(proc, "FROZEN", True)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert proc.user_data_root() == tmp_path / "Documents" / "AI粗剪"  # 不能写进 .app


def test_run_inprocess_captures_system_exit():
    code, out = proc.run_inprocess("pipeline.proc", [])
    assert code == 1  # 该模块没有 main()，应被兜住而不是抛异常
    assert "main" in out


def test_app_root_frozen_is_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))
    assert proc.app_root() == tmp_path
    assert proc.resource_path("presets", "a.json") == tmp_path / "presets" / "a.json"


def test_bundled_bin_none_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))  # app_root() 指向假的 App 资源目录
    (tmp_path / "bin").mkdir()                           # 目录在、但没有 ffmpeg 也不算
    assert proc.bundled_bin() is None


def test_bundled_bin_found_and_prepended_once(monkeypatch, tmp_path):
    monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ffmpeg").write_bytes(b"")
    monkeypatch.setenv("PATH", "/usr/bin")
    assert proc.bundled_bin() == tmp_path / "bin"
    proc.ensure_bundled_path()
    proc.ensure_bundled_path()  # 幂等：不重复插入
    assert os.environ["PATH"].split(os.pathsep) == [str(tmp_path / "bin"), "/usr/bin"]


def test_bundled_bin_accepts_ffmpeg_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ffmpeg.exe").write_bytes(b"")
    assert proc.bundled_bin() == tmp_path / "bin"


def test_ensure_bundled_path_noop_without_bin(monkeypatch, tmp_path):
    monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    proc.ensure_bundled_path()
    assert os.environ["PATH"] == "/usr/bin"


# ---------------------------------------------------------------- GL-11 / GL-12
def _fake_module(tmp_path, monkeypatch, name, body):
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def test_run_inprocess_keeps_text_of_sys_exit_string(tmp_path, monkeypatch):
    mod = _fake_module(tmp_path, monkeypatch, "fake_exit_text", """
        import sys
        def main():
            print("开始")
            sys.exit("找不到剪映草稿库")
    """)
    code, out = proc.run_inprocess(mod, [])
    assert code == 1
    assert "找不到剪映草稿库" in out  # GL-12：文字不能丢，也不能抛 ValueError
    assert "开始" in out


@pytest.mark.parametrize("ret, expected", [(None, 0), (0, 0), (1, 1), (3, 3)])
def test_run_inprocess_honors_main_return_value(tmp_path, monkeypatch, ret, expected):
    mod = _fake_module(tmp_path, monkeypatch, f"fake_ret_{expected}_{ret}", f"""
        def main():
            return {ret!r}
    """)
    code, _ = proc.run_inprocess(mod, [])
    assert code == expected  # GL-11：validate_draft.main() 返回 1 必须透传


@pytest.mark.parametrize("exit_arg, expected", [(None, 0), (0, 0), (2, 2), (True, 1)])
def test_run_inprocess_int_exit_codes(tmp_path, monkeypatch, exit_arg, expected):
    mod = _fake_module(tmp_path, monkeypatch, f"fake_exit_{expected}_{exit_arg}", f"""
        import sys
        def main():
            sys.exit({exit_arg!r})
    """)
    assert proc.run_inprocess(mod, [])[0] == expected


def test_run_inprocess_restores_argv(tmp_path, monkeypatch):
    before = list(sys.argv)
    mod = _fake_module(tmp_path, monkeypatch, "fake_exit_restore", """
        import sys
        def main():
            sys.exit("x")
    """)
    proc.run_inprocess(mod, ["a"])
    assert sys.argv == before


# ---------------------------------------------------------------- GL-17 / GL-14：自启子进程
def test_cli_cmd_dev_uses_aicut_py(monkeypatch):
    monkeypatch.setattr(proc, "FROZEN", False)
    cmd = proc.cli_cmd(["prepare", "p1"])
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("aicut.py") and cmd[2:] == ["prepare", "p1"]


def test_cli_cmd_frozen_relaunches_self(monkeypatch):
    monkeypatch.setattr(proc, "FROZEN", True)
    assert proc.cli_cmd(["prepare", "p1"]) == [sys.executable, "--aicut-cli", "prepare", "p1"]


def test_module_cmd_dev_uses_bootstrap(monkeypatch):
    # KI-15：开发态不再以脚本路径运行（pipeline/ 会成为 sys.path[0]，select.py 遮蔽标准库）
    monkeypatch.setattr(proc, "FROZEN", False)
    cmd = proc.module_cmd("pipeline.to_jianying", ["a"])
    assert cmd[:2] == [sys.executable, "-P"] and cmd[-2:] == ["pipeline.to_jianying", "a"]
    assert not any(str(c).endswith(".py") for c in cmd)


def _shadow_tree(tmp_path):
    """包目录和 cwd 里都放一个遮蔽标准库 json 的 json.py（模拟 pipeline/select.py）。"""
    pkg = tmp_path / "root" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    shadow = "raise ImportError('shadowed stdlib')\n"
    (pkg / "json.py").write_text(shadow)
    (tmp_path / "json.py").write_text(shadow)
    (pkg / "tool.py").write_text("import json, sys\nprint(json.__file__)\n"
                                 "print(sys.argv[1:])\nsys.exit(3)\n")
    return tmp_path / "root"


def _run_shadowed(python, tmp_path):
    cmd = proc.dev_module_cmd(python, "pkg.tool", ["x", "y"], root=_shadow_tree(tmp_path))
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 3, r.stderr                 # 退出码原样透传
    out = r.stdout.splitlines()
    assert "pkg" not in out[0] and str(tmp_path) not in out[0]   # 拿到的是标准库 json
    assert out[1] == "['x', 'y']"                      # 参数原样传给模块
    return cmd


def test_dev_module_cmd_does_not_put_package_dir_or_cwd_first(tmp_path):
    # 用机制复现，不依赖本机 select 是不是内建模块（uv 的 3.12 里是内建，复现不了）
    cmd = _run_shadowed(sys.executable, tmp_path)
    assert cmd[1] == "-P"


def test_dev_module_cmd_without_safe_path_flag_still_isolates(tmp_path, monkeypatch):
    # 审查修复 1：<3.11 的解释器不认 -P，退回由引导代码自己剔除 sys.path 里的 cwd
    monkeypatch.setattr(proc.pyver, "supports_safe_path", lambda py: False)
    cmd = _run_shadowed(sys.executable, tmp_path)
    assert "-P" not in cmd


def _old_python() -> str | None:
    py = "/usr/bin/python3"
    if not Path(py).exists():
        return None
    r = subprocess.run([py, "-c", "import sys; print(sys.version_info < (3, 11))"],
                       capture_output=True, text=True)
    return py if r.returncode == 0 and r.stdout.strip() == "True" else None


@pytest.mark.skipif(_old_python() is None, reason="需要一个 <3.11 的 Python（如 macOS 自带 3.9）")
def test_dev_module_cmd_runs_under_old_python(tmp_path):
    cmd = _run_shadowed(_old_python(), tmp_path)
    assert "-P" not in cmd


def test_dev_module_cmd_defaults_to_app_root(monkeypatch):
    monkeypatch.setattr(proc.pyver, "supports_safe_path", lambda py: True)
    cmd = proc.dev_module_cmd("py", "pipeline.render_preview", ["a"])
    assert cmd[0] == "py" and cmd[1] == "-P"
    assert cmd[-3:] == [str(proc.app_root()), "pipeline.render_preview", "a"]


def _python_with_dynamic_select() -> str | None:
    """找一个 select 不是内建模块、版本 ≥3.11 的 Python（如 Homebrew）；KI-15 只在这种 Python 上暴露。"""
    for py in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3"):
        if not Path(py).exists():
            continue
        r = subprocess.run([py, "-c", "import sys; print('select' in sys.builtin_module_names, "
                                      "sys.version_info >= (3, 11))"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.split() == ["False", "True"]:
            return py
    return None


@pytest.mark.skipif(_python_with_dynamic_select() is None,
                    reason="需要 select 不是内建模块的 Python（如 Homebrew）")
@pytest.mark.parametrize("module", ["pipeline.render_preview", "pipeline.junk_detect",
                                    "pipeline.format_transcript"])
def test_pipeline_help_runs_under_homebrew_python(module):
    py = _python_with_dynamic_select()
    r = subprocess.run(proc.dev_module_cmd(py, module, ["--help"]),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_module_cmd_frozen_relaunches_self(monkeypatch):
    monkeypatch.setattr(proc, "FROZEN", True)
    assert proc.module_cmd("pipeline.to_jianying", ["a"]) == \
        [sys.executable, "--aicut-module", "pipeline.to_jianying", "a"]


def test_dispatch_returns_none_without_flag():
    assert proc.dispatch(["app"]) is None
    assert proc.dispatch(["app", "--other"]) is None


def test_dispatch_runs_module_and_returns_exit_code(tmp_path, monkeypatch):
    mod = _fake_module(tmp_path, monkeypatch, "fake_dispatch_exit", """
        import sys
        if __name__ == "__main__":
            print("args", sys.argv[1:])
            sys.exit(3)
    """)
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    monkeypatch.setattr(proc, "ALLOWED_MODULES", frozenset({mod}))
    before = list(sys.argv)
    assert proc.dispatch(["app", "--aicut-module", mod, "x"]) == 3
    assert sys.argv == before


def test_dispatch_module_text_exit_is_printed(tmp_path, monkeypatch, capsys):
    mod = _fake_module(tmp_path, monkeypatch, "fake_dispatch_text", """
        import sys
        if __name__ == "__main__":
            sys.exit("找不到剪映草稿库")
    """)
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    monkeypatch.setattr(proc, "ALLOWED_MODULES", frozenset({mod}))
    assert proc.dispatch(["app", "--aicut-module", mod]) == 1
    assert "找不到剪映草稿库" in capsys.readouterr().err


def test_dispatch_module_without_name_fails(monkeypatch, capsys):
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    assert proc.dispatch(["app", "--aicut-module"]) == 2


def test_dispatch_cli_calls_run_cli(monkeypatch):
    import aicut
    seen = {}
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    monkeypatch.setattr(aicut, "run_cli", lambda argv: seen.setdefault("argv", argv) and 5)
    assert proc.dispatch(["app", "--aicut-cli", "list"]) == 5
    assert seen["argv"] == ["list"]


def test_app_entry_dispatches_before_webview_import():
    src = (proc.app_root() / "app" / "main.py").read_text(encoding="utf-8")
    assert "proc.dispatch(sys.argv)" in src
    assert src.index("proc.dispatch(sys.argv)") < src.index("\nimport webview")


# ---------------------------------------------------------------- 审查修复 2：父进程没了就自尽（HIGH-1）
@posix_only("看门狗靠进程组 + SIGTERM/SIGKILL + getppid；Windows 由 Job Object 的 KILL_ON_JOB_CLOSE 保证")
def test_parent_watchdog_kills_own_group_when_parent_dies(tmp_path):
    """剪辑台（父）被强杀后，任务子进程连同它的孙进程都要自己退出，不能变成孤儿继续计费。"""
    import os
    import subprocess
    root = proc.app_root()
    child = ("import os,subprocess,sys,time;"
             "sys.path.insert(0, %r);" % str(root) +
             "from pipeline import proc;"
             "proc.WATCHDOG_INTERVAL_S = 0.1; proc.WATCHDOG_GRACE_S = 0.3;"
             "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
             "proc.start_parent_watchdog();"
             "print(os.getpid(), g.pid, flush=True); time.sleep(60)")
    parent = ("import os,subprocess,sys;"
              "env = dict(os.environ, %s=str(os.getpid()));" % proc.PARENT_PID_ENV +
              "c = subprocess.Popen([sys.executable, '-c', %r], env=env, stdout=subprocess.PIPE," % child +
              " stderr=subprocess.DEVNULL,"
              " text=True, start_new_session=True);"
              "print(c.stdout.readline().strip(), flush=True)")
    out = subprocess.run([sys.executable, "-c", parent], capture_output=True, text=True,
                         timeout=20).stdout.split()
    pids = [int(x) for x in out]
    assert len(pids) == 2

    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
        return bool(r.stdout.strip()) and not r.stdout.strip().startswith("Z")

    import time
    deadline = time.time() + 10
    while time.time() < deadline and any(alive(p) for p in pids):
        time.sleep(0.1)
    assert not any(alive(p) for p in pids)


def test_parent_watchdog_is_noop_on_windows_but_still_consumes_env(monkeypatch):
    # Windows：Job Object KILL_ON_JOB_CLOSE 已保证剪辑台没了任务就没了；不装信号处理、不起线程
    monkeypatch.setenv(proc.PARENT_PID_ENV, str(os.getppid()))
    monkeypatch.setattr(proc.plat, "IS_WIN", True)
    monkeypatch.setattr(proc.threading, "Thread", lambda *a, **k: pytest.fail("不该起看门狗线程"))
    monkeypatch.setattr(proc.signal, "signal", lambda *a: pytest.fail("不该装信号处理"))
    assert proc.start_parent_watchdog() is False
    assert proc.PARENT_PID_ENV not in os.environ  # 子孙进程不会误判


def test_proc_module_has_no_posix_only_names_at_top_level():
    import ast
    tree = ast.parse(Path(proc.__file__).read_text(encoding="utf-8"))
    banned = {"killpg", "SIGKILL", "getpgrp", "SIGHUP"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            assert not (isinstance(sub, ast.Attribute) and sub.attr in banned), sub.attr


def test_parent_watchdog_inactive_without_env(monkeypatch):
    monkeypatch.delenv(proc.PARENT_PID_ENV, raising=False)
    assert proc.start_parent_watchdog() is False


@posix_only("走 POSIX 看门狗路径（装 SIGTERM 处理）")
def test_parent_watchdog_env_not_inherited_by_grandchildren(monkeypatch):
    import os
    monkeypatch.setenv(proc.PARENT_PID_ENV, str(os.getppid()))
    monkeypatch.setattr(proc, "_watch_parent", lambda *a: None)
    monkeypatch.setattr(proc.signal, "signal", lambda *a: None)  # 不在 pytest 进程里真的装 SIGTERM 处理
    assert proc.start_parent_watchdog() is True
    assert proc.PARENT_PID_ENV not in os.environ  # aicut 再拉起的 --aicut-module 不能误判


def test_dispatch_starts_watchdog(monkeypatch):
    import aicut
    seen = []
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    monkeypatch.setattr(proc, "start_parent_watchdog", lambda: seen.append(1) or False)
    monkeypatch.setattr(aicut, "run_cli", lambda argv: 0)
    proc.dispatch(["app", "--aicut-cli", "list"])
    assert seen == [1]


def test_aicut_script_entry_starts_watchdog():
    src = (proc.app_root() / "aicut.py").read_text(encoding="utf-8")
    tail = src[src.index('if __name__ == "__main__":'):]
    assert "proc.start_parent_watchdog()" in tail



# ---------------------------------------------------------------- 审查修复 2：--aicut-module 白名单（LOW-9）
def test_dispatch_rejects_module_outside_allowlist(monkeypatch, capsys):
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    monkeypatch.setattr(proc, "start_parent_watchdog", lambda: False)
    assert proc.dispatch(["app", "--aicut-module", "os"]) == 2
    assert "pipeline.to_jianying" in capsys.readouterr().err


def test_module_cmd_rejects_module_outside_allowlist():
    with pytest.raises(ValueError):
        proc.module_cmd("pipeline.secrets", [])


# ---------------------------------------------------------------- KI-72：看门狗不依赖 pgrep
def _orphaned_child_scenario(tmp_path, child_body):
    import subprocess
    parent = ("import os,subprocess,sys;"
              "env = dict(os.environ, %s=str(os.getpid()));" % proc.PARENT_PID_ENV +
              "c = subprocess.Popen([sys.executable, '-c', %r], env=env, stdout=subprocess.PIPE," % child_body +
              " stderr=subprocess.DEVNULL, text=True, start_new_session=True);"
              "print(c.stdout.readline().strip(), flush=True)")
    return subprocess.run([sys.executable, "-c", parent], capture_output=True, text=True,
                          timeout=20).stdout.split()


@posix_only("看门狗靠进程组 + SIGTERM")
def test_watchdog_does_not_need_pgrep(tmp_path):
    """PATH 里没有 pgrep 时，孙进程（ffmpeg）仍先收到 SIGTERM（体面退出），而不是直接被 SIGKILL。"""
    import time
    flag = tmp_path / "got_term"
    empty = tmp_path / "empty_bin"
    empty.mkdir()
    grandchild = ("import signal,sys,time;"
                  f"signal.signal(signal.SIGTERM, lambda *a: (open({str(flag)!r}, 'w').close(), sys.exit(0)));"
                  "print('ready', flush=True); time.sleep(60)")
    child = ("import os,subprocess,sys,time;"
             "sys.path.insert(0, %r);" % str(proc.app_root()) +
             "from pipeline import proc;"
             "proc.WATCHDOG_INTERVAL_S = 0.1; proc.WATCHDOG_GRACE_S = 1.0;"
             f"os.environ['PATH'] = {str(empty)!r};"
             f"g = subprocess.Popen([sys.executable, '-c', {grandchild!r}], stdout=subprocess.PIPE, text=True);"
             "g.stdout.readline();"
             "proc.start_parent_watchdog();"
             "print(os.getpid(), flush=True); time.sleep(60)")
    out = _orphaned_child_scenario(tmp_path, child)
    assert len(out) == 1
    deadline = time.time() + 10
    while time.time() < deadline and not flag.exists():
        time.sleep(0.1)
    assert flag.exists()


@posix_only("SIGTERM 默认语义 / 退出码 -SIGTERM")
def test_sigterm_without_self_kill_keeps_default_behavior(tmp_path):
    """装了处理函数后，外部发来的 SIGTERM（剪辑台取消任务）仍按默认语义结束进程。"""
    import os
    import signal
    import subprocess
    import time
    child = ("import os,sys,time;"
             "sys.path.insert(0, %r);" % str(proc.app_root()) +
             "from pipeline import proc;"
             "assert proc.start_parent_watchdog();"
             "print('ready', flush=True); time.sleep(60)")
    env = dict(os.environ, **{proc.PARENT_PID_ENV: str(os.getpid())})
    p = subprocess.Popen([sys.executable, "-c", child], env=env, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ready"
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=10) == -signal.SIGTERM
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
