# -*- coding: utf-8 -*-
"""M16 Task 4 的平台适配：applog / secrets / diagnostics / /api/pick / subprocess 编码。
Windows 分支在 Mac 上 monkeypatch plat.IS_WIN（或删掉 os.fchmod）测纯逻辑。"""
import json
import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import call
from pipeline import applog, diagnostics, plat, proc, secrets


# ---------------------------------------------------------------- applog
def test_log_dir_defaults_per_platform(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_CUT_LOG_DIR", raising=False)
    monkeypatch.setattr(plat, "IS_WIN", False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert applog.log_dir() == tmp_path / "Library" / "Logs" / "剪辑台"
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "L"))
    assert applog.log_dir() == tmp_path / "L" / "剪辑台" / "logs"


def test_env_log_dir_still_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(tmp_path / "x"))
    assert applog.log_dir() == tmp_path / "x"


def test_log_file_works_without_os_fchmod(monkeypatch, tmp_path):
    """Windows 的 os 没有 fchmod：不能因此让日志（以及 proc.dispatch）崩掉。"""
    monkeypatch.delattr(os, "fchmod", raising=False)
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(tmp_path / "lg"))
    logger = applog.setup("app")
    logger.info("hello 你好")
    for h in logger.handlers:
        h.flush()
    assert "hello 你好" in applog.current_log_file().read_text(encoding="utf-8")


@pytest.mark.parametrize("raw,expected", [
    ("读 C:\\Users\\张三\\x.mp4 失败", "读 ~\\x.mp4 失败"),
    ("读 C:/Users/张三/x.mp4 失败", "读 ~/x.mp4 失败"),
    ("d:\\users\\bob smith\\a.txt", "~\\a.txt"),
    ("https://example.com/Users/x", "https://example.com/Users/x"),
    ("C:\\Program Files\\x", "C:\\Program Files\\x"),
])
def test_redact_windows_user_profile_paths(monkeypatch, raw, expected):
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert applog.redact(raw) == expected


def test_redact_handles_json_escaped_backslashes(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert applog.redact('{"p": "C:\\\\Users\\\\bob\\\\x.mp4"}') == '{"p": "~\\\\x.mp4"}'


def test_windows_rules_are_linear_on_pathological_input(monkeypatch):
    import time
    monkeypatch.setattr(plat, "IS_WIN", True)
    t = time.perf_counter()
    applog.redact("C:" + "\\" * 50000 + "Users" + "\\" * 50000 + "a" * 50000)
    applog.strip_paths("C:\\" + "a\\" * 50000 + "\u0000")
    assert time.perf_counter() - t < 2


@pytest.mark.parametrize("raw", ["读 C:\\Users\\张三\\x.mp4 失败", "C:/Users/bob/a.txt", "a C:\\Work\\x.mp4 b"])
def test_windows_rules_do_not_touch_mac_output(monkeypatch, raw):
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert applog.redact(raw) == raw and applog.strip_paths(raw) == raw


def test_strip_paths_reduces_windows_absolute_paths_to_filename(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert applog.strip_paths("a C:\\Work\\proj\\x.mp4 b") == "a x.mp4 b"
    assert applog.strip_paths("a ~\\AppData\\Local\\x.log b") == "a x.log b"
    assert applog.strip_paths("同 /Users/me/a/b.txt") == "同 b.txt"  # POSIX 行为不变


# ---------------------------------------------------------------- secrets
def test_secrets_config_dir_per_platform(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_CUT_CONFIG_DIR", raising=False)
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "R"))
    assert secrets.config_dir() == tmp_path / "R" / "ai-cut"
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "c"))
    assert secrets.config_dir() == tmp_path / "c"
    monkeypatch.delenv("AI_CUT_CONFIG_DIR")
    monkeypatch.setattr(plat, "IS_WIN", False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert secrets.config_dir() == tmp_path / ".config" / "ai-cut"


# ---------------------------------------------------------------- diagnostics
def test_frozen_version_on_windows_reads_build_info(monkeypatch, tmp_path):
    (tmp_path / "build_info.json").write_text(json.dumps({"version": "1.2.3", "build": "9"}), encoding="utf-8")
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setattr(diagnostics.proc, "FROZEN", True)
    monkeypatch.setattr(diagnostics.proc, "resource_path", lambda *p: tmp_path.joinpath(*p))
    assert diagnostics.app_version() == "1.2.3"


def test_frozen_version_on_windows_unknown_when_build_info_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setattr(diagnostics.proc, "FROZEN", True)
    monkeypatch.setattr(diagnostics.proc, "resource_path", lambda *p: tmp_path.joinpath(*p))
    assert diagnostics.app_version() == "unknown"


def test_ffmpeg_info_subprocess_has_encoding(monkeypatch):
    seen = []

    def run(argv, **kw):
        seen.append(kw)
        return SimpleNamespace(stdout="ffmpeg version 8\nx")
    monkeypatch.setattr(diagnostics.shutil, "which", lambda n: "/x/ffmpeg")
    monkeypatch.setattr(diagnostics.subprocess, "run", run)
    diagnostics.ffmpeg_info()
    assert all(k["encoding"] == "utf-8" and k["errors"] == "replace" for k in seen) and len(seen) == 2


# ---------------------------------------------------------------- /api/pick
def test_pick_on_windows_without_picker_is_empty_path(gui_server, monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", True)
    monkeypatch.setattr(gui_server.module, "PICKER", None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("不该起 osascript"))
    status, raw, _ = call(gui_server, "POST", "/api/pick", {})
    assert status == 200 and json.loads(raw) == {"path": ""}


# ---------------------------------------------------------------- 其余文本 subprocess 都显式 UTF-8
def test_pyver_probe_passes_utf8(monkeypatch):
    from pipeline import pyver
    seen = {}

    def runner(argv, **kw):
        seen.update(kw)
        return SimpleNamespace(returncode=0, stdout="1", stderr="")
    pyver.supports_safe_path("python", runner=runner)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"


def test_jy_env_runners_pass_utf8(monkeypatch, tmp_path):
    from pipeline import jy_env
    seen = []

    def runner(argv, **kw):
        seen.append(kw)
        return SimpleNamespace(returncode=0, stdout="0.3.1", stderr="")
    jy_env._installed_version(tmp_path / "py", runner)
    jy_env._pip_install(tmp_path / "py", runner)
    assert len(seen) == 2 and all(k["encoding"] == "utf-8" and k["errors"] == "replace" for k in seen)


def test_build_number_git_call_passes_utf8(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("version_under_test", Path(__file__).resolve().parent.parent / "packaging/version.py")
    pv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pv)
    seen = {}

    def run(argv, **kw):
        seen.update(kw)
        return SimpleNamespace(returncode=0, stdout="12\n", stderr="")
    pv.build_number(tmp_path, env={}, run=run)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
