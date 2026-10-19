import json
import sys
import zipfile
from pathlib import Path

import pytest

from pipeline import export_draft as ex


def fake_draft(tmp_path):
    d = tmp_path / "draft" / "MyDraft"
    (d / "Resources").mkdir(parents=True)
    (d / "Resources" / "clip01.mp4").write_bytes(b"fake")
    content = {
        "duration": 10_000_000,
        "platform": {"os": "mac"},
        "materials": {
            "videos": [{"path": str(d / "Resources/clip01.mp4"), "duration": 5_000_000,
                        "width": 1080, "height": 1920, "type": "video"}],
            "audios": [],
        },
        "tracks": [],
    }
    (d / "draft_content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (d / "draft_info.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (d / "draft_meta_info.json").write_text(json.dumps({"draft_id": "OLD"}, ensure_ascii=False),
                                            encoding="utf-8")
    return d


def test_package_draft_rewrites_paths_and_adds_installer(tmp_path):
    d = fake_draft(tmp_path)
    out = tmp_path / "out" / "Pkg.zip"
    ex.package_draft(d, "Test_Pack", out)
    info = ex.inspect_package(out)
    assert info["install"] and info["fix_paths"]
    assert info["placeholder"] is True
    assert info["drafts"], "应包含 draft_content.json"
    with zipfile.ZipFile(out) as z:
        content = json.loads(z.read(info["drafts"][0]).decode("utf-8"))
        path = content["materials"]["videos"][0]["path"]
        assert path.startswith("__DRAFT_DIR__")
        assert content["platform"]["os"] == "windows"


def test_ascii_name_sanitized(tmp_path):
    assert ex._api_name("九月一号 v4") == "v4"
    assert ex._api_name("ShangYue_v4") == "ShangYue_v4"
    assert ex._api_name("!!!") == "JianYing_Draft"


def test_missing_timeline_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        ex.build_windows_package(tmp_path / "nope.json", "x", tmp_path / "o.zip")


# ---------------------------------------------------------------- 审查修复 2：导出包校验
def _leftovers(out_dir):
    return [p.name for p in out_dir.iterdir()] if out_dir.exists() else []


def test_package_missing_installer_is_rejected(tmp_path, monkeypatch):
    d = fake_draft(tmp_path)
    monkeypatch.setattr(ex, "write_installer", lambda pkg: None)
    out = tmp_path / "out" / "Pkg.zip"
    with pytest.raises(RuntimeError, match="INSTALL.bat"):
        ex.package_draft(d, "Test_Pack", out)
    assert _leftovers(out.parent) == []  # 不留坏 zip、不留 _pkg 临时目录


def test_package_without_placeholder_is_rejected(tmp_path, monkeypatch):
    d = fake_draft(tmp_path)
    monkeypatch.setattr(ex, "rewrite_for_windows", lambda target: None)
    out = tmp_path / "out" / "Pkg.zip"
    with pytest.raises(RuntimeError, match="占位符"):
        ex.package_draft(d, "Test_Pack", out)
    assert _leftovers(out.parent) == []


def test_package_failure_cleans_temp_dir(tmp_path, monkeypatch):
    d = fake_draft(tmp_path)

    def boom(target):
        raise OSError("disk full")
    monkeypatch.setattr(ex, "rewrite_for_windows", boom)
    out = tmp_path / "out" / "Pkg.zip"
    with pytest.raises(OSError):
        ex.package_draft(d, "Test_Pack", out)
    assert _leftovers(out.parent) == []


def test_package_success_leaves_only_zip(tmp_path):
    out = tmp_path / "out" / "Pkg.zip"
    ex.package_draft(fake_draft(tmp_path), "Test_Pack", out)
    assert _leftovers(out.parent) == ["Pkg.zip"]  # 用户输出目录里不放 .done 标记


# ---------------------------------------------------------------- GL-14：打包版也能导出
def _capture_run(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return type("R", (), {"returncode": 1, "stdout": "boom", "stderr": ""})()

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    return seen


def test_build_uses_module_cmd_when_frozen(tmp_path, monkeypatch):
    from pipeline import proc
    tl = tmp_path / "timeline.json"
    tl.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(proc, "FROZEN", True)
    seen = _capture_run(monkeypatch)
    with pytest.raises(RuntimeError, match="生成草稿失败"):
        ex.build_windows_package(tl, "片名_v1", tmp_path / "o.zip")
    assert seen["argv"][1:3] == ["--aicut-module", "pipeline.to_jianying"]
    assert seen["kw"]["stdin"] is ex.subprocess.DEVNULL
    root = seen["kw"]["env"]["AI_CUT_DRAFT_ROOT"]
    assert root.startswith(tempfile_root()) and "aicut-export-" in root


def test_build_dev_runs_to_jianying_via_bootstrap(tmp_path, monkeypatch):
    from pipeline import proc
    tl = tmp_path / "timeline.json"
    tl.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(proc, "FROZEN", False)
    seen = _capture_run(monkeypatch)
    with pytest.raises(RuntimeError):
        ex.build_windows_package(tl, "x", tmp_path / "o.zip")
    assert seen["argv"][1] == "-P" and "pipeline.to_jianying" in seen["argv"]   # KI-15
    assert not any(str(a).endswith("to_jianying.py") for a in seen["argv"])


def tempfile_root():
    import tempfile
    return tempfile.gettempdir()


# ---------------------------------------------------------------- M7：KI-64 / KI-18 警告透传
def test_package_output_never_shows_partial_zip(tmp_path, capsys):
    ex.package_draft(fake_draft(tmp_path), "N", tmp_path / "out" / "N.zip")
    assert ".partial-" not in capsys.readouterr().out


def test_build_returns_to_jianying_warnings(tmp_path, monkeypatch):
    import subprocess
    tl = tmp_path / "timeline.json"
    tl.write_text("{}", encoding="utf-8")

    def fake_run(argv, **kw):
        staging = Path(argv[argv.index("--staging") + 1])
        (staging / "x").mkdir(parents=True)
        return subprocess.CompletedProcess(argv, 0, "[!] 1 条警告\n  - 字幕顺延\n", "")
    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    monkeypatch.setattr(ex, "package_draft", lambda d, n, out: Path(out).write_bytes(b"z"))
    res = ex.build_windows_package(tl, "x", tmp_path / "o.zip")
    assert res["warnings"] == ["字幕顺延"] and res["size"] == 1


# ---------------------------------------------------------------- KI-18 / KI-78：INSTALL.bat 如实报告、不删已有草稿
def _installer(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    ex.write_installer(pkg)
    return ((pkg / "INSTALL.bat").read_bytes(), (pkg / "fix_paths.ps1").read_text(encoding="utf-8-sig"),
            (pkg / "README.txt").read_text(encoding="utf-8-sig"))


def _bp():
    return sys.modules[ex.write_installer.__module__]


def test_install_scripts_are_pure_ascii():
    assert _bp().BAT.isascii() and _bp().PS1.isascii()   # cmd 的代码页不可控；写出时非 ASCII 会变成 ?


def test_install_bat_reports_failure_instead_of_ok(tmp_path):
    bat = _installer(tmp_path)[0].decode("ascii").replace("\r\n", "\n")
    assert 'set "FAILED=0"' in bat and 'set "FAILED=1"' in bat
    ps_line = next(line for line in bat.splitlines() if "fix_paths.ps1" in line)
    assert ">nul" not in ps_line                               # 失败原因要看得见
    assert bat.split(ps_line, 1)[1].lstrip().startswith("if errorlevel 1")   # PS1 失败被检查
    assert bat.index('if "%FAILED%"=="1"') < bat.index("[OK] Done.")
    assert bat.count("exit /b 1") >= 5      # 无根目录 / 剪映在跑 / 包里没草稿 / 同名 / 安装失败
    assert 'if "%COUNT%"=="0"' in bat


def test_install_bat_never_deletes_an_existing_draft(tmp_path):
    bat = _installer(tmp_path)[0].decode("ascii").replace("\r\n", "\n")
    first_copy = bat.index("xcopy ")
    conflict = bat.index('if "%CONFLICT%"=="1"')
    assert bat.index('if exist "%ROOT%\\%%~nxD"') < conflict < first_copy   # 拷之前先查同名
    assert "already exists" in bat[:first_copy]
    assert "exit /b 1" in bat[conflict:first_copy]                         # 同名就停，什么都不装
    assert "rd /s /q" not in bat[:first_copy]
    for line in bat[first_copy:].splitlines():                             # 只删本次自己半装的副本
        if "rd /s /q" in line:
            assert '"%ROOT%\\!NAME!"' in line


def test_fix_paths_ps1_prints_reason_on_failure(tmp_path):
    ps1 = _installer(tmp_path)[1]
    catch = ps1.split("catch", 1)[1]
    assert "Write-Host" in catch and "exit 1" in catch


def test_readme_matches_install_behaviour(tmp_path):
    readme = _installer(tmp_path)[2]
    assert "不会动你已有的任何草稿" in readme
    assert "同名" in readme and "[X]" in readme


def test_install_bat_echoes_root_with_delayed_expansion(tmp_path):
    # %LOCALAPPDATA% 可能含 ")"（如 C:\Users\Bob (work)）：括号块里解析期展开的 %ROOT% 会提前闭合块
    bat = _installer(tmp_path)[0].decode("ascii")
    assert [line for line in bat.splitlines() if "echo" in line and "%ROOT%" in line] == []


# ---------------------------------------------------------------- 审查修复 2：cmd 特殊字符的草稿名一律拒绝
BAD_BAT_CHARS = ["!", "%", "^", "&", "|", "<", ">", '"']


@pytest.mark.parametrize("ch", BAD_BAT_CHARS)
def test_write_installer_refuses_draft_names_cmd_would_mangle(tmp_path, ch):
    pkg = tmp_path / "pkg"
    (pkg / "drafts" / f"a{ch}b").mkdir(parents=True)
    with pytest.raises(ValueError, match="草稿名"):
        ex.write_installer(pkg)
    assert not (pkg / "INSTALL.bat").exists()


@pytest.mark.parametrize("name", ["九月一号!v3", "a%PATH%b", "x^y", 'q"r', "<>|&"])
def test_api_name_always_yields_installable_names(tmp_path, name):
    pkg = tmp_path / "pkg"
    (pkg / "drafts" / ex._api_name(name)).mkdir(parents=True)
    ex.write_installer(pkg)
    assert (pkg / "INSTALL.bat").exists()


def test_build_package_cli_refuses_bad_name_before_doing_work(tmp_path, monkeypatch):
    src = tmp_path / "draft"
    src.mkdir()
    monkeypatch.setattr(sys, "argv", ["build_package.py", "--draft", str(src), "--name", "a!b",
                                      "-o", str(tmp_path / "out")])
    with pytest.raises(SystemExit) as exc:
        _bp().main()
    assert exc.value.code not in (0, None) and "草稿名" in str(exc.value.code)
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------- KI-79：延迟扩展下 echo 里的孤立 ! 会被吞
def test_install_bat_echo_lines_have_no_stray_bang(tmp_path):
    bat = _installer(tmp_path)[0].decode("ascii")
    for line in bat.splitlines():
        if line.strip().startswith("echo"):
            assert "!" not in line.replace("!ROOT!", "").replace("!NAME!", ""), line


# ---------------------------------------------------------------- KI-81：独立打包脚本的模板走 jy_version，缺失即失败
def test_build_package_uses_jy_version_template():
    src = (Path(ex.__file__).resolve().parent.parent / "packaging/build_package.py").read_text(
        encoding="utf-8")
    assert "base_template_11.0" not in src and "jy_version.TEMPLATE" in src


def test_minimal_draft_fails_when_template_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_bp().jy_version, "TEMPLATE", tmp_path / "nope.json")
    with pytest.raises(SystemExit) as exc:
        _bp().make_minimal_draft(tmp_path / "d" / "N", [])
    assert exc.value.code not in (0, None) and "nope.json" in str(exc.value.code)
    assert not (tmp_path / "d").exists()
