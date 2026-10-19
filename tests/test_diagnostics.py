"""一键诊断包（GL-19）：版本、阶段耗时、错误栈（日志）、脱敏配置；不含转写 / 媒体 / Key。"""
import json
import zipfile
from pathlib import Path

import pytest

from pipeline import applog, diagnostics

KEY = "AKLTsecretkey123456"


@pytest.fixture
def env(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(logs))
    (logs / "app.log").write_text(f"2026 INFO 启动\n2026 ERROR 失败 key={KEY}\n", encoding="utf-8")
    (logs / "app.log.1").write_text("旧日志\n", encoding="utf-8")
    (logs / "cli.log").write_text("Traceback (most recent call last):\n  boom\n", encoding="utf-8")
    pdir = tmp_path / "projects" / "p1"
    work = pdir / "work"
    (work / "audio").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "name": "p1", "title": "片名", "preset": "纪实3min", "schema_version": 2,
        "material": "/Users/x/Movies/秘密素材.mov",
        "calibration": {"must_lines": "隐私必留台词"}}, ensure_ascii=False), encoding="utf-8")
    (work / "timings.json").write_text(json.dumps({"transcribe": {"seconds": 1.5, "ok": False}}),
                                       encoding="utf-8")
    (work / "failed.json").write_text(json.dumps(
        [{"stage": "asr", "error": f"HTTP 401 {KEY}", "context": {"audio": str(work)}}]),
        encoding="utf-8")
    (work / "transcript.md").write_text("隐私原话", encoding="utf-8")
    (work / "segments.json").write_text('{"segments": [{"text": "隐私原话"}]}', encoding="utf-8")
    (work / "audio/asr.wav").write_bytes(b"RIFF" + b"\0" * 100)
    (work / "proxy.mp4").write_bytes(b"\0" * 10)
    applog.register_secret(KEY)
    monkeypatch.setattr(diagnostics, "ffmpeg_info", lambda: None)
    out = tmp_path / "out"
    out.mkdir()
    return pdir, out


def _zip(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_bundle_contains_meta_logs_and_safe_project_files(env):
    pdir, out = env
    files = _zip(diagnostics.build_bundle(out, pdir))
    assert {"meta.json", "logs/app.log", "logs/app.log.1", "logs/cli.log",
            "project/project.json", "project/work/timings.json", "project/work/failed.json",
            "project/files.txt"} <= set(files)
    assert "Traceback" in files["logs/cli.log"]
    assert json.loads(files["project/work/timings.json"])["transcribe"]["seconds"] == 1.5


def test_bundle_excludes_transcripts_media_and_user_text(env):
    pdir, out = env
    files = _zip(diagnostics.build_bundle(out, pdir))
    names = set(files)
    assert not any(n.endswith((".md", ".wav", ".mp4")) or "segments" in n for n in names)
    blob = "\n".join(files.values())
    assert "隐私原话" not in blob and "隐私必留台词" not in blob
    listing = files["project/files.txt"].splitlines()
    assert "work/audio/asr.wav\t104" in listing and "work/transcript.md\t12" in listing


def test_bundle_redacts_secrets_home_and_material_path(env):
    pdir, out = env
    files = _zip(diagnostics.build_bundle(out, pdir))
    blob = "\n".join(files.values())
    assert KEY not in blob and "****3456" in blob  # KI-67 新掩码
    assert str(Path.home()) not in blob
    proj = json.loads(files["project/project.json"])
    assert proj["material"] == "秘密素材.mov" and "片名" not in json.dumps(proj, ensure_ascii=False)
    assert "calibration" not in proj


def test_meta_has_versions_and_masked_credentials(env, monkeypatch):
    pdir, out = env
    monkeypatch.setattr(diagnostics.secrets, "status", lambda: {
        "mediakit": {"configured": True, "source": "keyring", "masked": "AKLT****3456"}})
    meta = json.loads(_zip(diagnostics.build_bundle(out, pdir))["meta.json"])
    assert meta["credentials"]["mediakit"] == {"configured": True, "source": "keyring"}  # 掩码也不带
    for k in ("app_version", "macos", "arch", "python", "frozen", "ffmpeg", "created",
              "consent", "project"):
        assert k in meta
    assert meta["ffmpeg"] is None and meta["app_version"] == "0.1.0" and meta["project"] == "p1"


def test_credentials_failure_does_not_break_bundle(env, monkeypatch):
    pdir, out = env

    def locked():
        raise RuntimeError(f"keychain locked {KEY}")
    monkeypatch.setattr(diagnostics.secrets, "status", locked)
    meta = json.loads(_zip(diagnostics.build_bundle(out, pdir))["meta.json"])
    assert "error" in meta["credentials"] and KEY not in json.dumps(meta)


def test_bundle_without_project(env):
    _, out = env
    files = _zip(diagnostics.build_bundle(out, None))
    assert "meta.json" in files and not any(n.startswith("project/") for n in files)


def test_bundle_name_is_timestamped_unique_and_atomic(env):
    pdir, out = env
    a = diagnostics.build_bundle(out, pdir)
    b = diagnostics.build_bundle(out, pdir)
    assert a != b and a.name.startswith("剪辑台诊断-") and a.suffix == ".zip"
    assert sorted(p.name for p in out.iterdir()) == sorted([a.name, b.name])  # 无 .part 残留


def test_bundle_failure_leaves_no_partial(env, monkeypatch):
    pdir, out = env
    monkeypatch.setattr(diagnostics, "_meta", lambda *a: (_ for _ in ()).throw(OSError("满")))
    with pytest.raises(OSError):
        diagnostics.build_bundle(out, pdir)
    assert list(out.iterdir()) == []


def test_symlinks_in_work_are_not_followed(env, tmp_path):
    pdir, out = env
    secret_dir = tmp_path / "elsewhere"
    secret_dir.mkdir()
    (secret_dir / "x.txt").write_text("x", encoding="utf-8")
    (pdir / "work/link").symlink_to(secret_dir)
    listing = _zip(diagnostics.build_bundle(out, pdir))["project/files.txt"]
    assert "x.txt" not in listing


def test_default_out_dir_prefers_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics.Path, "home", lambda: tmp_path)
    assert diagnostics.default_out_dir() == tmp_path / "Desktop"
    (tmp_path / "Downloads").mkdir()
    assert diagnostics.default_out_dir() == tmp_path / "Downloads"


def test_ffmpeg_info_reports_license(monkeypatch):
    from types import SimpleNamespace
    outs = {"-version": "ffmpeg version 8.1.3 Copyright\nbuilt with clang",
            "-L": "GNU Lesser General Public\nLicense"}
    monkeypatch.setattr(diagnostics.shutil, "which", lambda n: "/x/ffmpeg")
    monkeypatch.setattr(diagnostics.subprocess, "run", lambda cmd, **k: SimpleNamespace(
        returncode=0, stdout=outs[cmd[-1]]))
    info = diagnostics.ffmpeg_info()
    assert info == {"path": "/x/ffmpeg", "version": "ffmpeg version 8.1.3 Copyright", "lgpl": True}
    monkeypatch.setattr(diagnostics.shutil, "which", lambda n: None)
    assert diagnostics.ffmpeg_info() is None


def test_title_is_user_text_and_excluded(env):
    pdir, out = env
    proj = json.loads(_zip(diagnostics.build_bundle(out, pdir))["project/project.json"])
    assert "title" not in proj and proj["name"] == "p1"


def test_scrub_handles_resolved_home_and_root_home(monkeypatch, tmp_path):
    real = tmp_path / "real_home"
    real.mkdir()
    link = tmp_path / "home_link"
    link.symlink_to(real)
    monkeypatch.setattr(diagnostics.Path, "home", lambda: link)
    assert diagnostics._scrub(f"{real}/x and {link}/y") == "x and y"  # 绝对路径只留文件名
    monkeypatch.setattr(diagnostics.Path, "home", lambda: Path("/"))
    assert diagnostics._scrub("运行 /usr/bin/x 与 a/b") == "运行 x 与 a/b"  # 主目录为 / 时不乱换 ~


def test_symlinked_work_dir_is_skipped(env, tmp_path):
    pdir, out = env
    import shutil
    elsewhere = tmp_path / "elsewhere_work"
    shutil.move(str(pdir / "work"), elsewhere)
    (pdir / "work").symlink_to(elsewhere)
    names = set(_zip(diagnostics.build_bundle(out, pdir)))
    assert not any(n.startswith("project/work/") or n == "project/files.txt" for n in names)
