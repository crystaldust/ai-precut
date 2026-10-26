# -*- coding: utf-8 -*-
"""packaging/build_win.py 的纯逻辑 + spec / NOTICES / workflow 的文本守卫。不构建、不联网。"""
import importlib.util
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(f"t_{name}", ROOT / "packaging" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bw, fw, ver = _load("build_win"), _load("fetch_ffmpeg_win"), _load("version")


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _vendor(tmp_path):
    for d, names in (("licenses", ["FFmpeg-COPYING.LGPLv3", "FFmpeg-COPYING.GPLv3"]), ("sources", ["a.tar.gz"])):
        (tmp_path / d).mkdir()
        for n in names:
            (tmp_path / d / n).write_text(n, encoding="utf-8")
    return tmp_path


def test_zip_name_is_ascii_with_version_and_build():
    assert bw.zip_name("0.4.0", "123") == "ai-cut-windows-x64-0.4.0-123.zip"


@pytest.mark.parametrize("short,build", [("", "1"), ("1.0", ""), ("1.0/x", "1"), ("1.0", "1 2"), ("版本", "1")])
def test_zip_name_rejects_unsafe_parts(short, build):
    with pytest.raises(ValueError):
        bw.zip_name(short, build)


def test_extra_files_with_vendor(tmp_path):
    rels = sorted(rel for _, rel in bw.extra_files(ROOT, _vendor(tmp_path)))
    assert rels == ["THIRD-PARTY-NOTICES.txt", "licenses/FFmpeg-COPYING.GPLv3", "licenses/FFmpeg-COPYING.LGPLv3",
                    "sources/a.tar.gz", "首次打开说明-Windows.txt"]


def test_extra_files_fails_when_sources_missing(tmp_path):
    v = _vendor(tmp_path)
    (v / "sources" / "a.tar.gz").unlink()
    with pytest.raises(FileNotFoundError, match="sources"):
        bw.extra_files(ROOT, v)


def test_extra_files_fails_when_vendor_absent(tmp_path):
    with pytest.raises(FileNotFoundError, match="licenses"):
        bw.extra_files(ROOT, tmp_path / "none")


def test_stage_and_zip_have_top_level_dir_and_utf8_names(tmp_path):
    app = tmp_path / "app"
    (app / "_internal").mkdir(parents=True)
    (app / "ai-cut.exe").write_bytes(b"MZ")
    (app / "_internal" / "x.dll").write_bytes(b"x")
    vendor = tmp_path / "v"
    vendor.mkdir()
    bw.stage_extras(app, bw.extra_files(ROOT, _vendor(vendor)))
    out = bw.make_zip(app, tmp_path / "out" / "z.zip")
    names = zipfile.ZipFile(out).namelist()
    assert all(n.startswith("ai-cut/") for n in names)
    assert {"ai-cut/ai-cut.exe", "ai-cut/_internal/x.dll", "ai-cut/首次打开说明-Windows.txt",
            "ai-cut/THIRD-PARTY-NOTICES.txt", "ai-cut/licenses/FFmpeg-COPYING.LGPLv3",
            "ai-cut/sources/a.tar.gz"} <= set(names)
    assert zipfile.ZipFile(out).testzip() is None


def test_make_zip_overwrites_and_rejects_missing_dir(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "a.txt").write_text("1")
    z = tmp_path / "z.zip"
    z.write_text("old")
    bw.make_zip(app, z)
    assert zipfile.ZipFile(z).namelist() == ["ai-cut/a.txt"]
    with pytest.raises(FileNotFoundError):
        bw.make_zip(tmp_path / "none", z)


def test_main_reports_pyinstaller_failure(monkeypatch, capsys):
    monkeypatch.setattr(bw.sys, "platform", "win32")
    monkeypatch.setattr(bw, "_load", lambda name: type("F", (), {"main": staticmethod(lambda a: 0)}))

    def fail(*a, **k):
        raise subprocess.CalledProcessError(3, a[0])
    monkeypatch.setattr(bw.subprocess, "run", fail)
    assert bw.main() == 3
    assert "PyInstaller 构建失败" in capsys.readouterr().err


def test_main_refuses_on_non_windows(capsys, monkeypatch):
    monkeypatch.setattr(bw.sys, "platform", "darwin")
    assert bw.main() == 1


# ---------------------------------------------------------------- build_info.json
def test_build_info_has_version_build_commit():
    ok = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="abc1234\n", stderr="")
    info = ver.build_info(ROOT, env={"AICUT_BUILD_NUMBER": "7"}, run=ok)
    assert info == {"version": ver.short_version(ROOT), "build": "7", "commit": "abc1234"}
    json.dumps(info)


def test_git_commit_env_override_and_fallbacks():
    assert ver.git_commit(ROOT, env={"AICUT_GIT_COMMIT": " deadbeef "}) == "deadbeef"
    bad = lambda *a, **k: subprocess.CompletedProcess(a, 128, stdout="", stderr="no git")
    assert ver.git_commit(ROOT, env={}, run=bad) == "unknown"

    def boom(*a, **k):
        raise OSError("no git")
    assert ver.git_commit(ROOT, env={}, run=boom) == "unknown"
    junk = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="not a hash!", stderr="")
    assert ver.git_commit(ROOT, env={}, run=junk) == "unknown"


def test_diagnostics_reads_build_info_version_key():
    assert ver.BUILD_ENV and 'info["version"]' in _read("pipeline/diagnostics.py")
    assert "version" in ver.build_info.__doc__


# ---------------------------------------------------------------- spec / NOTICES / workflow 文本守卫
def test_spec_windows_branch_contents():
    spec = _read("packaging/ai-cut.spec")
    compile(spec, "ai-cut.spec", "exec")
    assert 'IS_WIN = sys.platform == "win32"' in spec
    for name in ("webview.platforms.winforms", "webview.platforms.edgechromium", "clr_loader", "pythonnet",
                 "webview.platforms.cocoa", "webview.platforms.gtk", "webview.platforms.qt",
                 "PyQt5", "PyQt6", "PySide2", "PySide6"):
        assert f'"{name}"' in spec
    assert '("X utf8", None, "OPTION")' in spec and "utf8_mode" not in spec
    assert "if not IS_WIN:" in spec and "BUNDLE(" in spec
    assert "None if IS_WIN" in spec and "build_info.json" in spec and "console=False" in spec


def test_notices_in_sync_with_pinned_windows_ffmpeg():
    text = _read("packaging/THIRD-PARTY-NOTICES.txt")
    for const in ("RELEASE_TAG", "FFMPEG_COMMIT", "BUILD_SCRIPTS_COMMIT", "ZIP_NAME", "FFMPEG_ZIP_SHA256",
                  "FFMPEG_SRC_SHA256", "BUILD_SCRIPTS_SHA256", "FFMPEG_SRC_NAME", "BUILD_SCRIPTS_NAME"):
        assert getattr(fw, const) in text, const
    assert fw.FFMPEG_VERSION_PREFIX in text
    assert "LGPL" in text and "h264_mf" in text and "libopenh264" in text
    for lic in fw.LICENSE_FILES:
        assert lic in text


def test_windows_readme_mentions_key_steps():
    t = _read("packaging/首次打开说明-Windows.txt")
    for key in ("仍要运行", "更多信息", "WebView2", "ai-cut.exe", "文档\\AI粗剪", "%LOCALAPPDATA%\\剪辑台\\logs"):
        assert key in t


def test_workflow_build_job():
    wf = _read(".github/workflows/windows.yml")
    build = wf[wf.index("\n  build:"):]
    assert "needs: [verify, test]" in build and "windows-2022" in build
    assert "fetch-depth: 0" in build and "persist-credentials: false" in build
    assert "uv run python packaging/build_win.py" in build and "retention-days: 14" in build
    from pipeline import proc
    assert f'"{proc.CLI_FLAG}"' in build
    for env in ("AI_CUT_SECRETS: file", "AI_CUT_CONFIG_DIR", "AI_CUT_PROJECTS", "AI_CUT_DRAFT_ROOT", "AI_CUT_LOG_DIR"):
        assert env in build
    assert "timeout-minutes: 3" in build and "WaitForExit(120000)" in build and "Stop-Process" in build
    assert "-NoNewWindow" not in build and "Python.Runtime.dll" in build and "WebView2Loader.dll" in build
    assert re.search(r"upload-artifact@[0-9a-f]{40} # v", build)
    run_blocks = re.findall(r"run: \|\n((?:          .*\n)+)", build)
    assert not any("${{" in b for b in run_blocks)  # 表达式只放 env:
