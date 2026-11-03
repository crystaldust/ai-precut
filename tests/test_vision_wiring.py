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


# ---------------------------------------------------------------- 第 4 阶段：画面与对白整合
def test_cmd_align_off_returns_without_touching_files(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _project(projects)
    monkeypatch.setattr(aicut.vision_align, "run", lambda *a, **k: pytest.fail("不应调用"))
    aicut.main(["align", "p1"])
    assert "画面理解没开" in capsys.readouterr().out


def test_cmd_align_on_reports_counts_and_warnings(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    pdir = _project(projects)
    _with_vision(pdir)
    seen = {}

    def fake_run(work, cfg):
        seen.update(work=work, tier=cfg["vision"]["tier"])
        return {"by_segment": {"S001": {}, "S002": {}}, "visual_segments": [{}], "warnings": ["没有镜头切点"]}

    monkeypatch.setattr(aicut.vision_align, "run", fake_run)
    aicut.main(["align", "p1"])
    out = capsys.readouterr().out
    assert seen == {"work": pdir / "work", "tier": "balanced"}
    assert "挂到 2 句" in out and "画面片段 1 段" in out and "没有镜头切点" in out


def test_cmd_align_stale_timeline_dies(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _with_vision(_project(projects))

    def stale(*a, **k):
        raise aicut.vision_align.AlignError(aicut.vision_align.STALE_TIMELINE)

    monkeypatch.setattr(aicut.vision_align, "run", stale)
    with pytest.raises(SystemExit):
        aicut.main(["align", "p1"])
    assert "画面时间轴不是最新的" in capsys.readouterr().out


def test_status_lists_aligned_file():
    assert ("画面与对白整合", "work/vision_aligned.json") in readiness.STATUS_ARTIFACTS


def _text_ready(projects, monkeypatch, *, vision_on):
    from argparse import Namespace
    pdir = _project(projects)
    if vision_on:
        _with_vision(pdir)
    (pdir / "work/segments.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    aicut.secrets.set("deepseek", "sk-abcdefghij1234")
    seen = {}

    def fake_run(*a, **k):
        seen.update(visual=k.get("visual"))
        return {"topics": [], "segments": [], "failures": []}

    monkeypatch.setattr(aicut.understand_text, "run", fake_run)
    return pdir, seen, Namespace(name="p1", batch=40, model="m")


def test_cmd_text_off_passes_no_visual_even_with_leftover_files(cli_env, monkeypatch):
    projects, _ = cli_env
    pdir, seen, args = _text_ready(projects, monkeypatch, vision_on=False)
    (pdir / "work/vision_aligned.json").write_text(json.dumps({"by_segment": {"S001": {}}}), encoding="utf-8")
    aicut.cmd_text(args)
    assert seen == {"visual": None}


def test_cmd_text_on_with_stale_alignment_dies(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _, seen, args = _text_ready(projects, monkeypatch, vision_on=True)
    monkeypatch.setattr(aicut.vision_align, "current", lambda w, c: False)
    with pytest.raises(SystemExit):
        aicut.cmd_text(args)
    assert "画面整合不是最新的" in capsys.readouterr().out and seen == {}


def test_cmd_text_on_passes_aligned_data(cli_env, monkeypatch):
    projects, _ = cli_env
    pdir, seen, args = _text_ready(projects, monkeypatch, vision_on=True)
    aligned = {"timeline_key": "k", "by_segment": {"S001": {"desc": "签合同"}}, "visual_segments": []}
    (pdir / "work/vision_aligned.json").write_text(json.dumps(aligned, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(aicut.vision_align, "current", lambda w, c: True)
    aicut.cmd_text(args)
    assert seen == {"visual": aligned}


def test_cmd_text_reports_visual_segment_count_only_when_on(cli_env, monkeypatch, capsys):
    projects, _ = cli_env
    _, _, args = _text_ready(projects, monkeypatch, vision_on=False)
    monkeypatch.setattr(aicut.understand_text, "run", lambda *a, **k: {
        "topics": [], "segments": [], "failures": [], "visual_segments": [{}, {}]})
    aicut.cmd_text(args)
    assert "画面片段 2 段" in capsys.readouterr().out


def test_cmd_score_reports_picture_effects(cli_env, monkeypatch, capsys):
    from argparse import Namespace
    projects, _ = cli_env
    pdir = _project(projects)
    (pdir / "work/segments_text.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(aicut.classify, "run", lambda *a, **k: {
        "summary": {"waste": 1, "pending": 2, "usable": 3},
        "segments": [{"vision_demoted": True, "level": 2}, {"level": 3}], "pending": {"demoted": 0}, "warnings": [],
        "visual_segments": [{"level": 3}, {"level": 2}]})
    aicut.cmd_score(Namespace(name="p1"))
    out = capsys.readouterr().out
    assert "因画面降为待定 1" in out and "画面片段 2 段（可用 1）" in out


@pytest.mark.parametrize("on", [False, True])
def test_cmd_score_passes_current_vision_setting(cli_env, monkeypatch, on):
    from argparse import Namespace
    projects, _ = cli_env
    pdir = _project(projects)
    if on:
        _with_vision(pdir)
    (pdir / "work/segments_text.json").write_text("{}", encoding="utf-8")
    seen = {}

    def fake_run(*a, **k):
        seen.update(vision=k.get("vision"))
        return {"summary": {"waste": 0, "pending": 0, "usable": 0}, "segments": [], "warnings": []}

    monkeypatch.setattr(aicut.classify, "run", fake_run)
    monkeypatch.setattr(aicut.vision_align, "current", lambda w, c: True)
    (pdir / "work/vision_aligned.json").write_text(json.dumps({"timeline_key": "k9"}), encoding="utf-8")
    aicut.cmd_score(Namespace(name="p1"))
    assert seen == {"vision": "k9" if on else False}
