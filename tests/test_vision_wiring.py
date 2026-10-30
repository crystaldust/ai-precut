"""画面理解第 3 阶段：接入命令行 / 就绪检查 / 磁盘预检 / 剪辑台就绪。"""
import json

import pytest

import aicut
from pipeline import diskspace, readiness, vision_run
from test_aicut_cli import STAGES, _project, _record_stages, cli_env, new  # noqa: F401

ON = {"enabled": True, "tier": "balanced"}


def _with_vision(pdir, setting=ON):
    path = pdir / "project.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**cfg, "vision": setting}), encoding="utf-8")
    return {**cfg, "vision": setting}


# ---------------------------------------------------------------- 就绪
def test_needed_keys_transcribed_without_vision_skips_mediakit(tmp_path):
    (tmp_path / "transcript_raw.json").write_text("{}", encoding="utf-8")
    assert readiness.needed_keys(tmp_path) == ["deepseek"]
    assert readiness.needed_keys(tmp_path, {"vision": {"enabled": False}}) == ["deepseek"]


def test_needed_keys_vision_pending_needs_mediakit(tmp_path, monkeypatch):
    (tmp_path / "transcript_raw.json").write_text("{}", encoding="utf-8")
    cfg = {"vision": ON}
    assert readiness.needed_keys(tmp_path, cfg) == ["mediakit", "deepseek"]
    monkeypatch.setattr(readiness.vision_run, "timeline_current", lambda w, c: True)
    assert readiness.needed_keys(tmp_path, cfg) == ["deepseek"]


def test_prepare_with_vision_on_needs_mediakit_even_if_transcribed(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _with_vision(_project(projects, transcript=True))
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    assert calls == [] and "MEDIAKIT_API_KEY" in capsys.readouterr().out


def test_gui_prepare_ready_reads_vision_switch(consented, tmp_path):
    from gui import settings
    settings.secrets.set("deepseek", "sk-abcdefghijkl")
    (tmp_path / "work").mkdir()
    (tmp_path / "work/transcript_raw.json").write_text("{}", encoding="utf-8")
    (tmp_path / "project.json").write_text(json.dumps({"vision": ON}), encoding="utf-8")
    with pytest.raises(settings.PrepareBlocked) as ei:
        settings.check_prepare_ready(tmp_path)
    assert ei.value.need == "keys" and "mediakit" in ei.value.missing


def test_gui_prepare_ready_corrupt_project_counts_as_off(consented, tmp_path, monkeypatch):
    from gui import settings
    settings.secrets.set("deepseek", "sk-abcdefghijkl")
    monkeypatch.setattr(settings.encode, "preflight", lambda: None)
    (tmp_path / "work").mkdir()
    (tmp_path / "work/transcript_raw.json").write_text("{}", encoding="utf-8")
    (tmp_path / "project.json").write_text("{bad", encoding="utf-8")
    settings.check_prepare_ready(tmp_path)  # 不抛


# ---------------------------------------------------------------- 磁盘
def test_disk_need_counts_vision_chunks():
    base = diskspace.need_for_prepare(3600, wav=False, proxy=False)
    with_vision = diskspace.need_for_prepare(3600, wav=False, proxy=False, vision=True)
    assert base == 0
    assert with_vision == diskspace.MARGIN_BYTES + int(3600 * 300_000 / 8)


# ---------------------------------------------------------------- 命令
@pytest.mark.parametrize("choice,expected", [(None, {"enabled": False, "tier": "economy"}),
                                             ("off", {"enabled": False, "tier": "economy"}),
                                             ("quality", {"enabled": True, "tier": "quality"})])
def test_new_vision_flag(cli_env, choice, expected):
    projects, material = cli_env
    new(material, "--no-input", *([f"--vision={choice}"] if choice else []))
    cfg = json.loads((projects / "p1/project.json").read_text(encoding="utf-8"))
    assert cfg["vision"] == expected


def test_new_rejects_unknown_vision_tier(cli_env):
    _, material = cli_env
    with pytest.raises(SystemExit):
        new(material, "--no-input", "--vision=max")


def test_cmd_vision_off_returns_without_cloud(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _project(projects)
    monkeypatch.setattr(aicut.vision_run, "run", lambda *a, **k: pytest.fail("不应调用"))
    aicut.main(["vision", "p1"])
    assert "画面理解没开" in capsys.readouterr().out


def _vision_ready(projects, monkeypatch):
    pdir = _project(projects)
    _with_vision(pdir)
    monkeypatch.setattr(aicut.media_io, "complete_or_adopt", lambda p, **k: True)
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    return pdir


def test_cmd_vision_on_runs_and_reports(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    pdir = _vision_ready(projects, monkeypatch)
    seen = {}

    def fake_run(work, cfg, proxy, **kw):
        seen.update(work=work, tier=cfg["vision"]["tier"], proxy=proxy)
        return {"events": [{}, {}]}

    monkeypatch.setattr(aicut.vision_run, "run", fake_run)
    aicut.main(["vision", "p1"])
    assert seen == {"work": pdir / "work", "tier": "balanced", "proxy": pdir / "work/proxy.mp4"}
    assert "2 个画面事件" in capsys.readouterr().out


@pytest.mark.parametrize("exc", [vision_run.VisionError("第 2 段看不懂"),
                                 aicut.cloud.CloudError("任务失败：x", terminal=True)])
def test_cmd_vision_failure_dies_with_way_out(cli_env, monkeypatch, capsys, exc):
    projects, _ = cli_env
    _vision_ready(projects, monkeypatch)

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(aicut.vision_run, "run", boom)
    with pytest.raises(SystemExit):
        aicut.main(["vision", "p1"])
    out = capsys.readouterr().out
    assert "画面理解失败" in out and str(exc) in out and "关掉画面理解" in out


def test_cmd_vision_without_key_dies_before_upload(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    pdir = _project(projects)
    _with_vision(pdir)
    monkeypatch.setattr(aicut.media_io, "complete_or_adopt", lambda p, **k: True)
    monkeypatch.setattr(aicut.vision_run, "run", lambda *a, **k: pytest.fail("不应调用"))
    with pytest.raises(SystemExit):
        aicut.main(["vision", "p1"])
    assert "MEDIAKIT_API_KEY" in capsys.readouterr().out


def test_cmd_vision_needs_proxy(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _with_vision(_project(projects))
    with pytest.raises(SystemExit):
        aicut.main(["vision", "p1"])
    assert "proxy.mp4" in capsys.readouterr().out


def test_status_lists_visual_timeline():
    assert ("画面时间轴", "work/visual_timeline.json") in readiness.STATUS_ARTIFACTS
