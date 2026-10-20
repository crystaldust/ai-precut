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

    monkeypatch.setattr(aicut.schema, "create_json_exclusive", boom)  # KI-69：新建改走原子占位
    with pytest.raises(OSError):
        new(material, "--no-input")
    assert not (projects / "p1").exists()
    monkeypatch.undo()


def test_new_save_failure_keeps_preexisting_empty_dir(cli_env, monkeypatch):
    projects, material = cli_env
    (projects / "p1").mkdir()

    def boom(*_a, **_k):
        raise OSError("磁盘满")

    monkeypatch.setattr(aicut.schema, "create_json_exclusive", boom)  # KI-69：新建改走原子占位
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


STAGES = ("cmd_ingest", "cmd_junk", "cmd_transcribe", "cmd_analyze", "cmd_scenes", "cmd_quality",
          "cmd_text", "cmd_score", "cmd_summary", "cmd_questions", "cmd_select", "cmd_brief")


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


def test_prepare_writes_analysis_stamp_on_success(cli_env, monkeypatch):
    from pipeline import fingerprints
    projects, _ = cli_env
    pdir = _project(projects, transcript=True)
    cal = {"tone": "info", "audience": "家长", "must_lines": ""}
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    (pdir / "project.json").write_text(json.dumps({**cfg, "calibration": cal, "preset": "测试预设"}),
                                       encoding="utf-8")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    _record_stages(monkeypatch)
    aicut.main(["prepare", "p1"])
    stamp = json.loads((pdir / "work/analysis_inputs.json").read_text(encoding="utf-8"))
    assert stamp == fingerprints.analysis_inputs({"calibration": cal, "preset": "测试预设"})


def test_prepare_stamp_is_taken_at_start_not_end(cli_env, monkeypatch):
    from pipeline import fingerprints
    projects, _ = cli_env
    pdir = _project(projects, transcript=True)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    start_cal = {"tone": "info", "audience": "", "must_lines": ""}
    (pdir / "project.json").write_text(json.dumps({**cfg, "calibration": start_cal}), encoding="utf-8")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    _record_stages(monkeypatch)

    def edit_midway(args):  # 分析过程中剪辑师改了偏好
        (pdir / "project.json").write_text(json.dumps({**cfg, "calibration": {"tone": "emotion"}}),
                                           encoding="utf-8")

    monkeypatch.setattr(aicut, "cmd_text", edit_midway)
    aicut.main(["prepare", "p1"])
    stamp = json.loads((pdir / "work/analysis_inputs.json").read_text(encoding="utf-8"))
    assert stamp == fingerprints.analysis_inputs({"calibration": start_cal, "preset": "纪实3min"})  # 迁移补上的默认预设


def test_prepare_failure_keeps_old_stamp(cli_env, monkeypatch):
    projects, _ = cli_env
    pdir = _project(projects, transcript=True)
    (pdir / "work/analysis_inputs.json").write_text('{"old": "1"}', encoding="utf-8")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    _record_stages(monkeypatch)
    monkeypatch.setattr(aicut, "cmd_text", lambda a: aicut.die("理解失败"))
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert json.loads((pdir / "work/analysis_inputs.json").read_text(encoding="utf-8")) == {"old": "1"}


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
    monkeypatch.setattr(aicut.media_io, "complete_or_adopt", lambda p, **k: True)
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


# ---------------------------------------------------------------- KI-33：磁盘预检 + aicut clean
def test_prepare_dies_when_disk_low(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _project(projects, transcript=True)
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    monkeypatch.setattr(aicut.diskspace, "shortfall", lambda path, need, **k: "磁盘空间不够：测试")
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert calls == [] and "磁盘空间不够" in capsys.readouterr().out


def test_build_dies_when_disk_low_before_cutting(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    pdir = _project(projects)
    cfg = json.loads((pdir / "project.json").read_text())
    (pdir / "project.json").write_text(json.dumps({**cfg, "preset": "测试预设"}))
    (pdir / "shots.json").write_text(json.dumps({"shots": [{"id": "S1", "in": 0, "out": 5}]}))
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: pytest.fail("不应开始切片"))
    monkeypatch.setattr(aicut.diskspace, "shortfall", lambda path, need, **k: "磁盘空间不够：测试")
    with pytest.raises(SystemExit):
        aicut.main(["build", "p1", "--no-draft"])
    assert "磁盘空间不够" in capsys.readouterr().out


def test_clean_dry_run_deletes_nothing(cli_env, capsys):
    projects, _ = cli_env
    pdir = _project(projects)
    clip = pdir / "work/clips/S1.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x" * 2048)
    aicut.main(["clean", "p1", "--dry-run"])
    assert clip.exists() and "work/clips" in capsys.readouterr().out
    aicut.main(["clean", "p1"])
    assert not clip.exists()


# ---------------------------------------------------------------- 审查修复 M3：任务在跑时命令行 clean 也要拒绝
def test_clean_refused_while_project_task_runs(cli_env, capsys):
    import subprocess
    import sys as _sys
    projects, _ = cli_env
    pdir = _project(projects)
    clip = pdir / "work/clips/S1.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")
    from pipeline import project_lock
    holder = subprocess.Popen([_sys.executable, "-c",
        "import sys,time; sys.path.insert(0, %r); from pipeline import project_lock;"
        "cm = project_lock.busy(%r); cm.__enter__(); print('ok', flush=True); time.sleep(30)"
        % (str(aicut.ROOT), str(pdir))], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ok"
        with pytest.raises(SystemExit):
            aicut.main(["clean", "p1"])
        assert clip.exists() and "正在运行" in capsys.readouterr().out
    finally:
        holder.kill(); holder.wait()
    aicut.main(["clean", "p1"])
    assert not clip.exists()


def test_project_commands_hold_shared_lock(cli_env, monkeypatch):
    projects, _ = cli_env
    _project(projects)
    from pipeline import project_lock
    seen = []

    def fake_status(args):
        with pytest.raises(project_lock.Busy):
            with project_lock.exclusive(projects / "p1"):
                pass
        seen.append(1)

    monkeypatch.setattr(aicut, "cmd_brief", fake_status)
    aicut.main(["brief", "p1"])
    assert seen == [1]
