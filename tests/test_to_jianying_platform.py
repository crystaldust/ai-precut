# -*- coding: utf-8 -*-
"""to_jianying 的平台差异（M16 Task 4）：草稿根 / globalSetting / 绝对路径判定 / platform 字段 /
剪映运行检测 / 同名草稿不覆盖。Windows 分支在 Mac 上 monkeypatch plat.IS_WIN 测纯逻辑，真实行为用 WIN_ONLY。"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from pipeline import plat
from pipeline import to_jianying as tj
from platform_marks import WIN_ONLY, win_only

ROOT = Path(__file__).resolve().parent.parent


def rewrite_for_windows_platform() -> dict:
    """build_package.rewrite_for_windows 在真机验证过的 platform 值：直接跑它，从产物里读，避免两边漂移。"""
    spec = importlib.util.spec_from_file_location("build_package_under_test", ROOT / "packaging/build_package.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "draft"
        d.mkdir()
        (d / "draft_content.json").write_text(json.dumps({"materials": {}, "duration": 1}), encoding="utf-8")
        (d / "draft_meta_info.json").write_text(json.dumps({"draft_materials": []}), encoding="utf-8")
        bp.rewrite_for_windows(d)
        return json.loads((d / "draft_content.json").read_text(encoding="utf-8"))["platform"]


@pytest.fixture
def as_windows(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", True)


# ---------------------------------------------------------------- platform_fields
def test_platform_fields_mac_keeps_current_values(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert tj.platform_fields() == {
        "app_id": 0, "app_source": "", "app_version": tj.jy_version.VERIFIED_VERSION,
        "device_id": "", "hard_disk_id": "", "mac_address": "",
        "os": "mac", "os_version": __import__("platform").release()}


def test_platform_fields_windows_equal_the_verified_package_values(as_windows):
    assert tj.platform_fields() == rewrite_for_windows_platform()


def test_macify_writes_platform_fields_to_both_entry_files(tmp_path, as_windows, monkeypatch):
    d = tmp_path / "d"
    d.mkdir()
    (d / "draft_content.json").write_text(json.dumps(
        {"duration": 1, "materials": {"videos": []}, "platform": {"keep": 1}}), encoding="utf-8")
    (d / "draft_meta_info.json").write_text(json.dumps({"draft_materials": []}), encoding="utf-8")
    tj.macify(d, "T", 0, "ID", tmp_path / "root")
    for name in ("draft_content.json", "draft_info.json"):
        data = json.loads((d / name).read_text(encoding="utf-8"))
        assert data["platform"]["os"] == "windows" and data["last_modified_platform"]["os"] == "windows"
        assert data["platform"]["keep"] == 1 and data["platform"]["app_version"] == ""


# ---------------------------------------------------------------- 草稿根
def test_windows_default_draft_root_and_setting(as_windows, monkeypatch, tmp_path):
    monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
    env = {"LOCALAPPDATA": str(tmp_path / "L")}
    assert tj.resolve_draft_root(env=env) == tmp_path / "L/JianyingPro/User Data/Projects/com.lveditor.draft"


def _win_setting(tmp_path, env, value):
    setting = plat.jianying_setting(env=env)
    setting.parent.mkdir(parents=True)
    setting.write_text(f"[General]\ncurrentCustomDraftPath={value}\n", encoding="utf-8")


@pytest.mark.parametrize("value,expected", [
    ("D:/Drafts/剪映", "D:/Drafts/剪映"),
    ("D:\\\\Drafts\\\\剪映", "D:\\Drafts\\剪映"),     # Qt 把反斜杠写成 \\
    ('"D:/Drafts/\\x526a\\x6620"', "D:/Drafts/剪映"),
])
def test_windows_custom_path_accepts_drive_paths(as_windows, monkeypatch, tmp_path, value, expected):
    """is_absolute 判定按平台：Windows 上 C:/… 与 C:\\… 都认；解码后统一成 Path。"""
    env = {"LOCALAPPDATA": str(tmp_path / "L")}
    _win_setting(tmp_path, env, value)
    monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
    got = tj.resolve_draft_root(env=env)
    assert str(got).replace("\\", "/") == expected.replace("\\", "/")


def test_posix_style_path_rejected_on_windows_without_drive(as_windows, monkeypatch, tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "L")}
    _win_setting(tmp_path, env, "/Volumes/x")
    with pytest.raises(tj.InstallError):
        tj.resolve_draft_root(env=env)


def test_backslash_escape_stays_rejected_on_mac(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)
    with pytest.raises(ValueError):
        tj._decode_qt_value("/Volumes/a\\\\b")


# ---------------------------------------------------------------- jianying_running
def _run_stub(stdout="", code=0, calls=None):
    def run(argv, **kw):
        if calls is not None:
            calls.append((argv, kw))
        return SimpleNamespace(returncode=code, stdout=stdout, stderr="")
    return run


def test_mac_jianying_running_uses_same_pgrep(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)
    calls = []
    monkeypatch.setattr(tj.subprocess, "run", _run_stub(code=0, calls=calls))
    assert tj.jianying_running() is True
    assert calls[0][0] == ["pgrep", "-f", "MacOS/VideoFusion-macOS"]
    assert calls[0][1] == {"capture_output": True}


@pytest.mark.parametrize("out,expected", [
    ('"JianyingPro.exe","4321","Console","1","180,000 K"\r\n', True),
    ('"jianyingpro.exe","4321","Console","1","180,000 K"\r\n', True),
    ('"NotJianyingPro.exe","4321","Console","1","180,000 K"\r\n', False),     # 不是子串匹配
    ('"other.exe","JianyingPro.exe","Console","1","1 K"\r\n', False),            # 只看第一列
    ("信息: 没有运行的任务匹配指定标准。\r\n", False),
    ("", False),
])
def test_windows_jianying_running_parses_tasklist_csv(as_windows, monkeypatch, tmp_path, out, expected):
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Win"))
    calls = []
    monkeypatch.setattr(tj.subprocess, "run", _run_stub(stdout=out, calls=calls))
    assert tj.jianying_running() is expected
    argv, kw = calls[0]
    assert argv == [str(tmp_path / "Win" / "System32" / "tasklist.exe"), "/FI", "IMAGENAME eq JianyingPro.exe",
                    "/FO", "CSV", "/NH"]
    assert kw["capture_output"] is True and kw["encoding"] == "utf-8" and kw["errors"] == "replace"


@pytest.mark.parametrize("failure", [OSError("no tasklist"), subprocess.TimeoutExpired("tasklist", 10)])
def test_windows_tasklist_failure_is_fail_closed(as_windows, monkeypatch, failure):
    def boom(*a, **k):
        raise failure
    monkeypatch.setattr(tj.subprocess, "run", boom)
    with pytest.raises(tj.InstallError, match="无法确认剪映是否在运行"):
        tj.jianying_running()


def test_windows_tasklist_nonzero_exit_is_fail_closed(as_windows, monkeypatch):
    monkeypatch.setattr(tj.subprocess, "run", _run_stub(stdout="", code=1))
    with pytest.raises(tj.InstallError, match="无法确认剪映是否在运行"):
        tj.jianying_running()


def test_check_build_ready_blocks_when_running_state_unknown(as_windows, monkeypatch):
    from gui import settings
    from gui.settings import PrepareBlocked

    def unknown():
        raise tj.InstallError("无法确认剪映是否在运行（x）")
    monkeypatch.setattr(settings.to_jianying, "jianying_running", unknown)
    with pytest.raises(PrepareBlocked) as exc:
        settings.check_build_ready(None, {"target": "mac"})
    assert "无法确认" in str(exc.value)


def test_running_message_is_platform_specific(monkeypatch):
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert tj.running_message() == "剪映正在运行，请先完全退出（Cmd+Q）再安装" == tj.JY_RUNNING
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert "Cmd+Q" not in tj.running_message() and "剪映正在运行" in tj.running_message()


# ---------------------------------------------------------------- 同名草稿不覆盖
def test_rename_onto_existing_target_does_not_overwrite(tmp_path):
    """install 里的 os.rename(tmp, target)：目标已存在（非空目录）时 Mac / Windows 都抛 OSError，不会覆盖。"""
    import os
    tmp, target = tmp_path / ".T.aicut-tmp", tmp_path / "T"
    tmp.mkdir()
    (tmp / "new.txt").write_text("new", encoding="utf-8")
    target.mkdir()
    (target / "user.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(OSError):
        os.rename(tmp, target)
    assert (target / "user.txt").read_text(encoding="utf-8") == "keep" and not (target / "new.txt").exists()


@WIN_ONLY
def test_windows_even_empty_existing_target_is_not_replaced(tmp_path):
    """Windows 的 os.rename 目标存在一律失败（POSIX 会替换空目录）——更保守，不会覆盖。"""
    import os
    tmp, target = tmp_path / ".T.aicut-tmp", tmp_path / "T"
    tmp.mkdir()
    target.mkdir()
    with pytest.raises(FileExistsError):
        os.rename(tmp, target)


# ---------------------------------------------------------------- plat.is_absolute_path
@pytest.mark.parametrize("value,win,posix", [
    ("C:/Users/a", True, False), ("C:\\Users\\a", True, False), ("//server/share/x", True, True),
    ("/Volumes/x", False, True), ("relative/x", False, False), ("", False, False)])
def test_is_absolute_path_per_platform(monkeypatch, value, win, posix):
    monkeypatch.setattr(plat, "IS_WIN", True)
    assert plat.is_absolute_path(value) is win
    monkeypatch.setattr(plat, "IS_WIN", False)
    assert plat.is_absolute_path(value) is posix


# ---------------------------------------------------------------- 目录改名 / 替换的 Windows 重试
def test_directory_rename_retries_permission_error_on_windows_but_keeps_exists_semantics(as_windows, monkeypatch, tmp_path):
    from pipeline import schema
    monkeypatch.setattr(schema.time, "sleep", lambda s: None)
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    real, calls = schema.os.rename, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "Access is denied")
        return real(a, b)
    monkeypatch.setattr(schema.os, "rename", flaky)
    schema.rename_no_overwrite(src, dst)
    assert dst.is_dir() and len(calls) == 3
    monkeypatch.setattr(schema.os, "rename", real)
    again = tmp_path / "again"
    again.mkdir()
    (dst / "keep.txt").write_text("k", encoding="utf-8")
    with pytest.raises(OSError):
        schema.rename_no_overwrite(again, dst)    # 目标存在 → 失败，不覆盖
    assert (dst / "keep.txt").exists()


def test_posix_rename_does_not_retry(monkeypatch, tmp_path):
    from pipeline import schema
    monkeypatch.setattr(plat, "IS_WIN", False)
    calls = []

    def deny(a, b):
        calls.append(1)
        raise PermissionError(13, "x")
    monkeypatch.setattr(schema.os, "rename", deny)
    with pytest.raises(PermissionError):
        schema.rename_no_overwrite(tmp_path / "a", tmp_path / "b")
    assert len(calls) == 1


# ---------------------------------------------------------------- 真实 Windows：装一份草稿并校验
@WIN_ONLY
def test_windows_install_draft_into_temp_root_validates(tmp_path, monkeypatch):
    """真实 Windows：AI_CUT_DRAFT_ROOT 指向临时草稿根，install 后用 research/validate_draft.py 校验，
    且 draft_meta_info 里的路径字段是 Windows 路径。"""
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("需要 ffmpeg 生成测试素材")
    from test_to_jianying import full_timeline
    root = tmp_path / "draft_root"
    root.mkdir()
    (root / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [], "draft_ids": 1, "root_path": str(root)}), encoding="utf-8")
    monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(root))
    monkeypatch.setattr(tj, "jianying_running", lambda: False)
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=108x192:r=30:d=1",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", "-c:v", "mpeg4", "-c:a", "aac",
                    str(clip)], check=True)
    tl = full_timeline(clip)
    d = tj.build_staging(tl, tmp_path / "stg", "T")
    draft_id = tj.normalize(d)
    size = tj.bundle_media(d, root / "T")
    info = tj.macify(d, "T", size, draft_id, root)
    target, _ = tj.install(d, root, "T", info, size, tj.expected(tl))
    meta = json.loads((target / "draft_meta_info.json").read_text(encoding="utf-8"))
    content = json.loads((target / "draft_content.json").read_text(encoding="utf-8"))
    assert content["platform"]["os"] == "windows"
    for key in ("draft_fold_path", "draft_root_path"):
        assert PureWindowsPath(meta[key]).drive, meta[key]     # 盘符开头 = Windows 绝对路径
    assert PureWindowsPath(content["materials"]["videos"][0]["path"]).is_absolute()
    r = subprocess.run([sys.executable, str(ROOT / "research/validate_draft.py"), str(target)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr
