"""KI-34 / KI-37：启动脚本走 uv；构建号、CHANGELOG、签名告警。不构建、不联网。"""
import os
import re
import runpy
import subprocess
import tomllib
from pathlib import Path

import pytest

from platform_marks import posix_only

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "启动剪辑台.command"


def _version_module():
    return runpy.run_path(str(ROOT / "packaging" / "version.py"))  # 不能 import packaging（与 PyPI 包同名）


def _run_launcher(tmp_path, path_dirs, home):
    env = {"PATH": os.pathsep.join(str(d) for d in path_dirs), "HOME": str(home)}
    return subprocess.run(["/bin/bash", str(LAUNCHER)], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=20)


@posix_only("测试的是 macOS 双击启动脚本 启动剪辑台.command（/bin/bash + uv 桩）；Windows 没有该脚本的等价物")
def test_launcher_execs_uv_run(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    record = tmp_path / "args.txt"
    uv = stubs / "uv"
    uv.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {record}\n')
    uv.chmod(0o755)
    r = _run_launcher(tmp_path, [stubs, "/usr/bin", "/bin"], tmp_path / "home")
    assert r.returncode == 0, r.stdout + r.stderr
    assert record.read_text().split("\n")[:-1] == ["run", "--locked", "--python", "3.12", "python",
                                                    "gui/server.py", "--open"]


@posix_only("测试的是 macOS 双击启动脚本 启动剪辑台.command（/bin/bash + uv 桩）；Windows 没有该脚本的等价物")
def test_launcher_finds_uv_in_home_local_bin(tmp_path):
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    record = tmp_path / "args.txt"
    uv = home / ".local/bin/uv"
    uv.write_text(f'#!/bin/bash\necho "$@" > {record}\n')
    uv.chmod(0o755)
    r = _run_launcher(tmp_path, ["/usr/bin", "/bin"], home)
    assert r.returncode == 0 and record.exists()


@posix_only("测试的是 macOS 双击启动脚本 启动剪辑台.command（/bin/bash + uv 桩）；Windows 没有该脚本的等价物")
def test_launcher_without_uv_explains_and_exits(tmp_path):
    r = _run_launcher(tmp_path, ["/usr/bin", "/bin"], tmp_path / "empty_home")
    assert r.returncode == 1 and "uv" in r.stdout
    assert "python3" not in LAUNCHER.read_text(encoding="utf-8")  # D12：不回落系统 python3


# ---------------------------------------------------------------- KI-37：版本号
def test_short_version_reads_pyproject():
    v = _version_module()
    want = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert v["short_version"](ROOT) == want


def test_build_number_prefers_env():
    v = _version_module()
    assert v["build_number"](ROOT, env={"AICUT_BUILD_NUMBER": "42"}, run=None) == "42"


def test_build_number_from_git_commit_count():
    v = _version_module()

    def run(cmd, **kw):
        assert cmd[:3] == ["git", "rev-list", "--count"]
        return subprocess.CompletedProcess(cmd, 0, "137\n", "")
    assert v["build_number"](ROOT, env={}, run=run) == "137"


@pytest.mark.parametrize("env", [{"AICUT_BUILD_NUMBER": "abc"}, {"AICUT_BUILD_NUMBER": "0"}, {}])
def test_build_number_fails_loudly(env):
    v = _version_module()

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 128, "", "not a git repo")
    with pytest.raises(RuntimeError):
        v["build_number"](ROOT, env=env, run=run)


def test_spec_uses_computed_versions():
    spec = (ROOT / "packaging/ai-cut.spec").read_text(encoding="utf-8")
    assert '"CFBundleVersion": "1"' not in spec and '"CFBundleShortVersionString": "0.1.0"' not in spec
    assert "build_number(" in spec and "short_version(" in spec and "version.py" in spec


def test_changelog_mentions_current_version_and_upgrade_note():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    want = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert want in text and "升级须知" in text and "adhoc" in text


def test_build_script_warns_without_signing_identity():
    sh = (ROOT / "packaging/build_app.sh").read_text(encoding="utf-8")
    assert "CODESIGN_IDENTITY" in sh and re.search(r"\[!\].*adhoc", sh)


def test_launcher_uses_locked_dependencies():  # 审查修复 L19
    assert "run --locked --python 3.12" in LAUNCHER.read_text(encoding="utf-8")


@pytest.mark.parametrize("raw", ["١٢", "²", "12a", " 12 "])
def test_build_number_rejects_non_ascii_digits(raw):  # 审查修复 L20
    v = _version_module()
    with pytest.raises(RuntimeError):
        v["build_number"](ROOT, env={"AICUT_BUILD_NUMBER": raw}, run=None)


def test_single_default_model():  # 审查修复 L13
    from pipeline import cli_args, llm
    assert cli_args.DEFAULT_MODEL is llm.DEFAULT_MODEL
    assert '"deepseek-chat"' not in (ROOT / "pipeline/cli_args.py").read_text(encoding="utf-8")
