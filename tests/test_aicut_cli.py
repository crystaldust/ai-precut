"""M4 · GL-20（new 不交互、空目录可重试、失败清理）与 GL-02（prepare 缺 Key 前置失败）。"""
import json

import pytest

import aicut


@pytest.fixture
def cli_env(tmp_path, monkeypatch, no_keys, consented):
    projects = tmp_path / "projects"
    projects.mkdir()
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "测试预设.json").write_text(json.dumps({"duration": 120}), encoding="utf-8")
    material = tmp_path / "m.mp4"
    material.write_bytes(b"fake")
    monkeypatch.setattr(aicut, "PROJECTS", projects)
    monkeypatch.setattr(aicut, "PRESETS", presets)
    monkeypatch.setattr(aicut, "ask_calibration", lambda *_: pytest.fail("不应提问"))
    monkeypatch.setattr(aicut, "ask_target", lambda *_: pytest.fail("不应提问"))
    return projects, str(material)


def new(material, *extra):
    aicut.main(["new", "p1", f"--material={material}", "--preset=测试预设", *extra])


# ---------------------------------------------------------------- GL-20
def test_new_no_input_never_prompts(cli_env):
    projects, material = cli_env
    new(material, "--no-input")
    cfg = json.loads((projects / "p1/project.json").read_text(encoding="utf-8"))
    assert cfg["target_duration"] == 120  # 不问就用预设时长


def test_new_reuses_leftover_empty_dir(cli_env):
    projects, material = cli_env
    (projects / "p1").mkdir()  # 上次失败留下的空目录
    new(material, "--no-input")
    assert (projects / "p1/project.json").exists()


def test_new_refuses_non_empty_dir_without_project(cli_env, capsys):
    projects, material = cli_env
    (projects / "p1").mkdir()
    (projects / "p1/别人的文件.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        new(material, "--no-input")
    assert (projects / "p1/别人的文件.txt").exists()
    assert "不是空目录" in capsys.readouterr().out


def test_new_cleans_up_dir_on_save_failure(cli_env, monkeypatch):
    projects, material = cli_env

    def boom(*_a, **_k):
        raise OSError("磁盘满")

    monkeypatch.setattr(aicut.schema, "save", boom)
    with pytest.raises(OSError):
        new(material, "--no-input")
    assert not (projects / "p1").exists()
    monkeypatch.undo()


def test_new_save_failure_keeps_preexisting_empty_dir(cli_env, monkeypatch):
    projects, material = cli_env
    (projects / "p1").mkdir()

    def boom(*_a, **_k):
        raise OSError("磁盘满")

    monkeypatch.setattr(aicut.schema, "save", boom)
    with pytest.raises(OSError):
        new(material, "--no-input")
    assert (projects / "p1").is_dir()  # 不是这次建的，不删


# ---------------------------------------------------------------- GL-02
def _project(projects, transcript=False):
    pdir = projects / "p1"
    (pdir / "work").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": "p1", "material": "/tmp/a.mp4", "schema_version": 2}), encoding="utf-8")
    if transcript:
        (pdir / "work/transcript_raw.json").write_text("{}", encoding="utf-8")
    return pdir


STAGES = ("cmd_ingest", "cmd_transcribe", "cmd_analyze", "cmd_text", "cmd_junk", "cmd_scenes",
          "cmd_quality", "cmd_score", "cmd_summary", "cmd_questions", "cmd_select", "cmd_brief")


def _record_stages(monkeypatch):
    calls = []
    for stage in STAGES:
        monkeypatch.setattr(aicut, stage, lambda a, _s=stage: calls.append(_s))
    return calls


def test_prepare_fails_fast_without_deepseek_key(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _project(projects)
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    calls = _record_stages(monkeypatch)
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert calls == []  # 一步都不能开始
    out = capsys.readouterr().out
    assert "DEEPSEEK_API_KEY" in out and "MEDIAKIT_API_KEY" not in out


def test_prepare_fails_fast_without_mediakit_key_when_not_transcribed(cli_env, monkeypatch,
                                                                       capsys):
    projects, _ = cli_env
    _project(projects)
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert calls == [] and "MEDIAKIT_API_KEY" in capsys.readouterr().out


def test_prepare_without_mediakit_ok_when_already_transcribed(cli_env, monkeypatch):
    projects, _ = cli_env
    _project(projects, transcript=True)
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    aicut.main(["prepare", "p1"])
    assert calls == list(STAGES)


def test_prepare_always_runs_text_when_keys_present(cli_env, monkeypatch):
    projects, _ = cli_env
    _project(projects)
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    aicut.main(["prepare", "p1"])
    assert "cmd_text" in calls and calls == list(STAGES)



# ---------------------------------------------------------------- 审查修复 2：命令行也要先确认外发说明（MEDIUM-5）
@pytest.fixture
def unconsented(cli_env):
    from pipeline import consent, secrets as sec
    (sec.config_dir() / consent.FILENAME).unlink()
    assert not consent.accepted()
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    return cli_env


def _assert_consent_die(capsys):
    out = capsys.readouterr().out
    assert "aicut.py config consent" in out and "外发" in out


def test_prepare_requires_consent(unconsented, monkeypatch, capsys):
    projects, _ = unconsented
    _project(projects)
    calls = _record_stages(monkeypatch)
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert calls == []
    _assert_consent_die(capsys)


def test_transcribe_requires_consent_before_cloud(unconsented, monkeypatch, capsys):
    projects, _ = unconsented
    pdir = _project(projects)
    wav = pdir / "work/audio/asr.wav"
    wav.parent.mkdir(parents=True)
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr(aicut.media_io, "complete_or_adopt", lambda p: True)
    monkeypatch.setattr(aicut.cloud, "CloudClient", lambda *a, **k: pytest.fail("不应调用云端"))
    with pytest.raises(SystemExit):
        aicut.main(["transcribe", "p1"])
    _assert_consent_die(capsys)


@pytest.mark.parametrize("cmd, files", [
    ("text", ["segments.json"]),
    ("summary", ["segments_text.json", "segments_scored.json"]),
    ("questions", ["content_summary.json", "segments_scored.json"]),
])
def test_llm_commands_require_consent(unconsented, monkeypatch, capsys, cmd, files):
    projects, _ = unconsented
    pdir = _project(projects)
    for f in files:
        (pdir / "work" / f).write_text("{}", encoding="utf-8")
    for mod in (aicut.understand_text, aicut.summarize, aicut.questions):
        monkeypatch.setattr(mod, "run", lambda *a, **k: pytest.fail("不应调用 LLM"))
    with pytest.raises(SystemExit):
        aicut.main([cmd, "p1"])
    _assert_consent_die(capsys)


def test_config_consent_prints_notice_and_records(unconsented, capsys):
    from pipeline import consent
    aicut.main(["config", "consent"])
    out = capsys.readouterr().out
    for text in ("16kHz", "火山引擎", "DeepSeek", "不会离开这台电脑"):
        assert text in out
    assert consent.accepted()
