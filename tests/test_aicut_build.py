"""aicut build 链路回归：退出码（GL-12）、字幕卡（GL-10）、媒体产物原子落盘（GL-15）。"""
import argparse
from pathlib import Path

import pytest

import aicut
from pipeline import media_io, schema


def test_run_cli_keeps_text_of_sys_exit_string(monkeypatch, capsys):
    def boom(argv):
        raise SystemExit("剪映正在运行，请先完全退出（Cmd+Q）再安装")
    monkeypatch.setattr(aicut, "main", boom)
    assert aicut.run_cli(["build", "x"]) == 1
    assert "剪映正在运行" in capsys.readouterr().out


# ---------------------------------------------------------------- GL-10
PRESET_JISHI = {"subtitle": {"max_chars": 14, "size": 6.5}, "card": {"size": 6.8},
                "cards": [{"at": 0.0, "dur": 4.5, "text": "片头"},
                          {"at": 170.0, "dur": 5.5, "text": "片尾"}]}


def test_compose_timeline_has_no_nonpositive_text(tmp_path):
    shots = [{"id": "S01", "in": 0.0, "out": 150.0, "sub": "你好，世界。"}]
    tl = aicut.compose_timeline({"title": "t"}, PRESET_JISHI, shots, tmp_path, {"S01": 150.0})
    assert all(t["end"] > t["start"] for t in tl["text"])
    assert "片尾" not in [t["text"] for t in tl["text"]]
    assert "片头" in [t["text"] for t in tl["text"]]


# ---------------------------------------------------------------- GL-15
@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", str(tmp_path / "src.mov")))
    return pdir


def fake_ffmpeg(calls, fail_on=None, interrupt=False):
    def run(args, **kw):
        calls.append(args)
        out = Path(args[-1])
        out.write_bytes(b"half" if interrupt else b"full")
        if interrupt:
            raise KeyboardInterrupt
        if fail_on and fail_on in str(args):
            raise media_io.MediaError("ffmpeg 失败：boom")
    return run


def test_interrupted_audio_extract_is_not_reused(project, monkeypatch):
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls, interrupt=True))
    monkeypatch.setattr(aicut.secrets, "get", lambda p: None)
    with pytest.raises(KeyboardInterrupt):
        aicut.cmd_transcribe(argparse.Namespace(name="p"))
    wav = project / "work/audio/asr.wav"
    assert not wav.exists()                      # 改前：半截 wav 留在最终路径
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
    with pytest.raises(SystemExit):              # 没配 key → die，但 wav 已完整
        aicut.cmd_transcribe(argparse.Namespace(name="p"))
    assert media_io.is_complete(wav) and len(calls) == 2


def test_legacy_wav_without_marker_is_regenerated(project, monkeypatch):
    wav = project / "work/audio/asr.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"half-from-old-version")
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 0.0)  # ffprobe 读不出 → 不认领
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
    monkeypatch.setattr(aicut.secrets, "get", lambda p: None)
    with pytest.raises(SystemExit):
        aicut.cmd_transcribe(argparse.Namespace(name="p"))
    assert len(calls) == 1 and wav.read_bytes() == b"full"


def test_audio_extract_failure_dies_with_reason(project, monkeypatch, capsys):
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg([], fail_on="pcm_s16le"))
    with pytest.raises(SystemExit):
        aicut.cmd_transcribe(argparse.Namespace(name="p"))
    assert "抽音轨失败" in capsys.readouterr().out
    assert not (project / "work/audio/asr.wav").exists()


def test_analyze_requires_complete_wav(project, monkeypatch):
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 0.0)
    wav = project / "work/audio/asr.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"half")
    (project / "work/segments.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        aicut.cmd_analyze(argparse.Namespace(name="p"))


def test_proxy_failure_leaves_no_proxy(project, monkeypatch):
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg([], fail_on="scale=-2:540"))
    monkeypatch.setattr(aicut, "_run_pipeline", lambda *a: None)
    with pytest.raises(SystemExit):
        aicut.cmd_junk(argparse.Namespace(name="p"))
    assert not (project / "work/proxy.mp4").exists()


@pytest.mark.parametrize("cmd", ["cmd_scenes", "cmd_quality"])
def test_visual_steps_require_complete_proxy(project, cmd, monkeypatch):
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 0.0)
    (project / "work").mkdir(exist_ok=True)
    (project / "work/proxy.mp4").write_bytes(b"half")
    (project / "work/segments.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        getattr(aicut, cmd)(argparse.Namespace(name="p", threshold=8.0))


def test_clips_resume_after_failure(project, monkeypatch):
    shots = [{"id": "S01", "in": 0.0, "out": 1.0}, {"id": "S02", "in": 5.0, "out": 6.0}]
    c = aicut.cfg(project)
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls, fail_on="5.000"))
    with pytest.raises(SystemExit):
        aicut.ensure_clips(project, c, shots)
    clips = project / "work/clips"
    assert media_io.is_complete(clips / "S01.mp4") and not (clips / "S02.mp4").exists()
    calls.clear()
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
    aicut.ensure_clips(project, c, shots)
    assert len(calls) == 1  # 只重切 S02


def test_preview_without_marker_is_rerendered(tmp_path, monkeypatch):
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 0.0)
    vdir = tmp_path / "v1"
    vdir.mkdir()
    (vdir / "preview.mp4").write_bytes(b"half")
    (vdir / ".timeline.sha").write_text("h")
    rendered = []

    def fake_pipeline(module, argv):
        rendered.append(argv[-1])
        Path(argv[-1]).write_bytes(b"full")
    monkeypatch.setattr(aicut, "_run_pipeline", fake_pipeline)
    aicut.ensure_preview(vdir, "h")
    assert rendered and rendered[0] != str(vdir / "preview.mp4")
    assert media_io.is_complete(vdir / "preview.mp4")
    aicut.ensure_preview(vdir, "h")
    assert len(rendered) == 1  # 有标记 + 哈希一致 → 跳过


def test_preview_render_failure_keeps_stamp(tmp_path, monkeypatch):
    vdir = tmp_path / "v1"
    vdir.mkdir()

    def boom(module, argv):
        Path(argv[-1]).write_bytes(b"half")
        aicut.die("render_preview 执行失败")
    monkeypatch.setattr(aicut, "_run_pipeline", boom)
    with pytest.raises(SystemExit):
        aicut.ensure_preview(vdir, "h")
    assert not (vdir / "preview.mp4").exists() and not (vdir / ".timeline.sha").exists()


def test_status_marks_half_media_as_not_done(project, monkeypatch, capsys):
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 0.0)
    (project / "work/audio").mkdir(parents=True)
    (project / "work/audio/asr.wav").write_bytes(b"half")
    with media_io.atomic_output(project / "work/proxy.mp4") as tmp:
        tmp.write_bytes(b"full")
    aicut.cmd_status(argparse.Namespace(name="p"))
    out = capsys.readouterr().out
    assert "[·] 音轨" in out and "[✓] 分析代理" in out


# ---------------------------------------------------------------- 审查修复 7
def test_legacy_wav_readable_by_ffprobe_is_adopted(project, monkeypatch):
    wav = project / "work/audio/asr.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"full-from-old-version")
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 42.0)
    calls = []
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
    monkeypatch.setattr(aicut.secrets, "get", lambda p: None)
    with pytest.raises(SystemExit):
        aicut.cmd_transcribe(argparse.Namespace(name="p"))
    assert calls == [] and media_io.is_complete(wav)


def test_status_adopts_legacy_proxy(project, monkeypatch, capsys):
    (project / "work").mkdir(exist_ok=True)
    (project / "work/proxy.mp4").write_bytes(b"legacy")
    monkeypatch.setattr(media_io, "_probe_duration", lambda *a: 10.0)
    aicut.cmd_status(argparse.Namespace(name="p"))
    assert "[✓] 分析代理" in capsys.readouterr().out


# ---------------------------------------------------------------- 审查修复 1：草稿结果可见
SUCCESS_OUT = """草稿已生成：/stg/T（1.00s，媒体 0.1MB）
[warn] 2 条字幕与前一条重叠，起点已顺延（显示时间变短）
校验通过：OK=60 WARN=0 FAIL=0
已注册；注册表备份：/root/root_meta_info.json.x.bak
完成。打开剪映 → 本地草稿 → T
草稿位置：/root/T
注册表备份：/root/root_meta_info.json.x.bak
[!] 1 条警告
  - 2 条字幕与前一条重叠，起点已顺延（显示时间变短）
"""
FAIL_OUT = "\n".join([f"第 {i} 行日志" for i in range(80)]
                     + ["草稿静态校验未通过，已撤销安装：", "  [FAIL] 人为 FAIL " + "很长" * 400])


def _frozen(monkeypatch, code, out):
    monkeypatch.setattr(aicut.proc, "FROZEN", True)
    monkeypatch.setattr(aicut.proc, "run_inprocess", lambda m, argv: (code, out))


def test_install_draft_reemits_warnings_and_location(tmp_path, monkeypatch, capsys):
    _frozen(monkeypatch, 0, SUCCESS_OUT)
    aicut.install_draft(tmp_path, "T")
    out = capsys.readouterr().out
    assert "[!] 2 条字幕与前一条重叠" in out
    assert "/root/T" in out and "root_meta_info.json.x.bak" in out
    assert "[✓] 剪映草稿：T（已通过静态校验）" in out


def test_install_draft_failure_shows_reason_and_rollback(tmp_path, monkeypatch, capsys):
    _frozen(monkeypatch, 1, FAIL_OUT)
    with pytest.raises(SystemExit):
        aicut.install_draft(tmp_path, "T")
    out = capsys.readouterr().out
    assert "草稿静态校验未通过" in out and "人为 FAIL" in out   # 不再按 600 字符截尾
    assert "草稿未安装（已回滚" in out and "[✓]" not in out


def test_install_draft_dev_mode_merges_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aicut.proc, "FROZEN", False)
    monkeypatch.setattr(aicut, "ensure_jy_python", lambda: "python3")
    monkeypatch.setattr(aicut.subprocess, "run", lambda *a, **k: aicut.subprocess.CompletedProcess(
        a[0], 1, "草稿已生成\n", "剪映正在运行，请先完全退出（Cmd+Q）再安装\n"))
    with pytest.raises(SystemExit):
        aicut.install_draft(tmp_path, "T")
    assert "剪映正在运行" in capsys.readouterr().out


# ---------------------------------------------------------------- KI-15：开发态不以脚本路径跑 pipeline
def _capture_dev_run(monkeypatch, code=0, out=""):
    monkeypatch.setattr(aicut.proc, "FROZEN", False)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return aicut.subprocess.CompletedProcess(cmd, code, out, "")
    monkeypatch.setattr(aicut.subprocess, "run", fake_run)
    return seen


def test_run_pipeline_dev_uses_bootstrap_not_script_path(monkeypatch):
    seen = _capture_dev_run(monkeypatch)
    aicut._run_pipeline("pipeline.render_preview", ["t.json", "-o", "o.mp4"])
    assert seen["cmd"][0] == aicut.sys.executable and seen["cmd"][1] == "-P"
    assert seen["cmd"][-4:] == ["pipeline.render_preview", "t.json", "-o", "o.mp4"]
    assert not any(str(c).endswith("render_preview.py") for c in seen["cmd"])


def test_install_draft_dev_uses_bootstrap_with_jy_python(tmp_path, monkeypatch):
    seen = _capture_dev_run(monkeypatch, out=SUCCESS_OUT)
    monkeypatch.setattr(aicut, "ensure_jy_python", lambda: "py")
    monkeypatch.setattr(aicut.proc.pyver, "supports_safe_path", lambda py: True)
    aicut.install_draft(tmp_path, "T")
    assert seen["cmd"][:2] == ["py", "-P"] and "pipeline.to_jianying" in seen["cmd"]
    assert not any(str(c).endswith("to_jianying.py") for c in seen["cmd"])


# ---------------------------------------------------------------- KI-16：run 带上 build 的参数
def test_run_with_shots_reaches_build_with_build_options(project, monkeypatch):
    (project / "shots.json").write_text('{"shots": []}', encoding="utf-8")
    for step in ("cmd_ingest", "cmd_transcribe", "cmd_junk", "cmd_brief"):
        monkeypatch.setattr(aicut, step, lambda a: None)
    seen = []
    monkeypatch.setattr(aicut, "cmd_build", lambda a: seen.append((a.version, a.no_draft)))
    aicut.main(["run", "p"])
    aicut.main(["run", "p", "--version", "v2", "--no-draft"])
    assert seen == [(None, False), ("v2", True)]


def test_build_still_accepts_its_options(project, monkeypatch):
    seen = []
    monkeypatch.setattr(aicut, "cmd_build", lambda a: seen.append((a.version, a.no_draft)))
    aicut.main(["build", "p", "--version", "v3", "--no-draft"])
    assert seen == [("v3", True)]


# ---------------------------------------------------------------- KI-18：Windows 导出的警告要看得见
def test_cmd_export_shows_to_jianying_warnings(project, tmp_path, monkeypatch, capsys):
    tl = tmp_path / "timeline.json"
    tl.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(aicut.export_draft, "build_windows_package",
                        lambda t, n, out: {"zip": str(out), "size": 1, "warnings": ["字幕顺延"]})
    aicut.cmd_export(argparse.Namespace(name="p", timeline=str(tl), package_name=None,
                                        out=str(tmp_path)))
    out = capsys.readouterr().out
    assert "[!] 字幕顺延" in out and "[✓] 已导出" in out


# ---------------------------------------------------------------- KI-82：剪映 venv 由 jy_env 负责（含旧版重建）
def test_ensure_jy_python_frozen_uses_app_itself(monkeypatch):
    monkeypatch.setattr(aicut.proc, "FROZEN", True)
    monkeypatch.setattr(aicut.jy_env, "ensure", lambda v: pytest.fail("打包版不建 venv"))
    assert aicut.ensure_jy_python() == aicut.sys.executable


def test_ensure_jy_python_dev_delegates_and_dies_on_error(monkeypatch, capsys):
    monkeypatch.setattr(aicut.proc, "FROZEN", False)
    seen = []
    monkeypatch.setattr(aicut.jy_env, "ensure", lambda v: seen.append(v) or "py")
    assert aicut.ensure_jy_python() == "py" and seen == [aicut.JY_VENV]

    def boom(v):
        raise aicut.jy_env.JyEnvError("安装 pyJianYingDraft 失败：x")
    monkeypatch.setattr(aicut.jy_env, "ensure", boom)
    with pytest.raises(SystemExit):
        aicut.ensure_jy_python()
    assert "[x] 安装 pyJianYingDraft 失败" in capsys.readouterr().out
