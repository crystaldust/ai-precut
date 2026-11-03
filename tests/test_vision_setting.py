# -*- coding: utf-8 -*-
"""画面理解第 2 阶段：设置模型（pipeline/vision.py）、schema 默认、分析指纹、向导「需要更新」、POST /api/project/vision。"""
import json
import re
from pathlib import Path

import pytest

from conftest import call, make_project
from gui import project_routes, wizard
from pipeline import fingerprints, schema, vision

OFF = {"enabled": False, "tier": "economy"}


def post(gs, path, body):
    status, raw, _ = call(gs, "POST", path, body)
    return status, json.loads(raw)


def project_json(gs, name="p1"):
    return json.loads((gs.root / name / "project.json").read_text(encoding="utf-8"))


def fake_job(project, task="prepare"):
    return {"status": "running", "log": [], "exit": None, "started": 0.0, "task": task, "project": project,
            "popen": None, "cancel": False, "thread": None, "out_lines": 0}


# ---------------------------------------------------------------- 模块
def test_module_default_matches_schema_default():
    assert vision.DEFAULT == OFF == schema.DEFAULTS["vision"]
    assert vision.TIERS == ("economy", "balanced", "quality") and vision.DEFAULT_TIER == "economy"


@pytest.mark.parametrize("raw", [None, "x", [], {}, {"enabled": 1}, {"enabled": "yes"},
                                 {"enabled": True, "tier": "pro"}, {"enabled": True, "tier": 3}])
def test_module_normalize_falls_back_field_by_field(raw):
    out = vision.normalize(raw)
    assert set(out) == {"enabled", "tier"} and out["tier"] in vision.TIERS
    assert out["enabled"] is (raw.get("enabled") is True if isinstance(raw, dict) else False)
    assert out["tier"] == "economy"


def test_module_normalize_keeps_valid_and_returns_new_dict():
    raw = {"enabled": True, "tier": "quality", "extra": 1}
    out = vision.normalize(raw)
    assert out == {"enabled": True, "tier": "quality"} and out is not raw and "extra" in raw
    assert vision.normalize(None) is not vision.DEFAULT


@pytest.mark.parametrize("setting,expected", [(OFF, "off"), ({"enabled": False, "tier": "quality"}, "off"),
                                              ({"enabled": True, "tier": "economy"}, "on:economy"),
                                              ({"enabled": True, "tier": "balanced"}, "on:balanced")])
def test_module_fingerprint(setting, expected):
    assert vision.fingerprint(setting) == expected


def test_module_check_accepts_valid_body_and_ignores_other_keys():
    assert vision.check({"project": "p1", "enabled": True, "tier": "balanced"}) == {
        "enabled": True, "tier": "balanced"}


@pytest.mark.parametrize("body", [{}, {"enabled": True}, {"tier": "economy"}, {"enabled": 1, "tier": "economy"},
                                  {"enabled": "true", "tier": "economy"}, {"enabled": True, "tier": "pro"},
                                  {"enabled": True, "tier": None}, {"enabled": None, "tier": "economy"}])
def test_module_check_rejects_bad_body(body):
    with pytest.raises(ValueError, match="画面理解设置不对"):
        vision.check(body)


# ---------------------------------------------------------------- schema / 指纹
def test_schema_new_project_and_migration_fill_default_vision():
    cfg = schema.default_project("p", "/a.mp4")
    assert cfg["vision"] == OFF and cfg["vision"] is not schema.DEFAULTS["vision"]
    out, changes = schema.migrate({"name": "p", "material": "/a.mp4", "schema_version": 2})
    assert out["vision"] == OFF and "补齐 vision" in changes


def test_fingerprint_analysis_inputs_includes_vision():
    assert fingerprints.analysis_inputs({})["vision"] == "off"
    assert fingerprints.analysis_inputs({"vision": {"enabled": True, "tier": "quality"}})["vision"] == "on:quality"
    assert fingerprints.analysis_inputs({"vision": "坏"})["vision"] == "off"
    assert fingerprints.ANALYSIS_STAMP_DEFAULTS == {"vision": "off"}


# ---------------------------------------------------------------- 向导
def _f(stamp, now):
    return {"analysis_done": True, "analysis_running": False, "analysis_stamp": stamp, "analysis_inputs": now,
            "answers_confirmed": False, "answers_questions_digest": None, "questions_digest": None,
            "legacy": False, "selection_inputs_saved": None, "selection_inputs_now": None}


def _analyze(stamp, now):
    return next(s for s in wizard.derive(_f(stamp, now))["steps"] if s["key"] == "analyze")


def test_wizard_old_stamp_without_vision_stays_done_when_vision_off():
    """回归：改版前分析过的项目，戳里没有 vision；当前关闭 → 仍是 ✓，不能全部变「需要更新」。"""
    now = fingerprints.analysis_inputs({"preset": "纪实3min"})
    old = {k: v for k, v in now.items() if k != "vision"}
    assert _analyze(old, now)["status"] == wizard.DONE


def test_wizard_old_stamp_with_vision_now_on_is_stale_with_vision_banner():
    now = fingerprints.analysis_inputs({"preset": "纪实3min", "vision": {"enabled": True, "tier": "economy"}})
    old = {k: v for k, v in now.items() if k != "vision"}
    step = _analyze(old, now)
    assert step["status"] == wizard.STALE and step["reasons"] == ["vision"]
    assert step["banner"] == wizard.STALE_ANALYZE_VISION and step["action"] == wizard.ACTION_REANALYZE


def test_wizard_tier_change_is_stale_and_preference_change_keeps_old_banner():
    saved = fingerprints.analysis_inputs({"vision": {"enabled": True, "tier": "economy"}})
    assert _analyze(saved, {**saved, "vision": "on:quality"})["banner"] == wizard.STALE_ANALYZE_VISION
    step = _analyze(saved, {**saved, "directive": "新偏好"})
    assert step["status"] == wizard.STALE and step["banner"] == wizard.STALE_ANALYZE
    assert step["reasons"] == ["directive"]


def test_wizard_collect_keeps_raw_stamp(tmp_path):
    pdir = make_project(tmp_path, **{"work/analysis_inputs.json": json.dumps({"directive": "", "preset": "p"})})
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    f = wizard.collect(pdir, cfg, "p1")
    assert f["analysis_stamp"] == {"directive": "", "preset": "p"} and f["analysis_inputs"]["vision"] == "off"


# ---------------------------------------------------------------- 接口
@pytest.mark.usefixtures("consented")
def test_api_analysis_returns_vision_setting(gui_server):
    make_project(gui_server.root)
    status, raw, _ = call(gui_server, "GET", "/api/analysis?project=p1")
    assert status == 200 and json.loads(raw)["vision"] == OFF


@pytest.mark.usefixtures("consented")
def test_api_post_vision_saves_and_returns_wizard(gui_server):
    make_project(gui_server.root)
    status, data = post(gui_server, "/api/project/vision", {"project": "p1", "enabled": True, "tier": "balanced"})
    assert status == 200 and data["ok"] is True and data["vision"] == {"enabled": True, "tier": "balanced"}
    assert project_json(gui_server)["vision"] == {"enabled": True, "tier": "balanced"}
    assert [s["key"] for s in data["wizard"]["steps"]][1] == "analyze"


@pytest.mark.usefixtures("consented")
@pytest.mark.parametrize("body", [{"enabled": "yes", "tier": "economy"}, {"enabled": True, "tier": "pro"},
                                  {"enabled": True}])
def test_api_post_vision_bad_body_is_400_and_file_untouched(gui_server, body):
    pdir = make_project(gui_server.root)
    before = (pdir / "project.json").read_bytes()
    status, data = post(gui_server, "/api/project/vision", {"project": "p1", **body})
    assert status == 400 and "画面理解设置不对" in data["error"]
    assert (pdir / "project.json").read_bytes() == before


@pytest.mark.usefixtures("consented")
def test_api_post_vision_unknown_project_is_404(gui_server):
    assert post(gui_server, "/api/project/vision", {"project": "nope", "enabled": True, "tier": "economy"})[0] == 404


@pytest.mark.usefixtures("consented")
def test_api_post_vision_while_this_project_runs_is_409_and_untouched(gui_server, monkeypatch):
    pdir = make_project(gui_server.root)
    monkeypatch.setitem(project_routes.jobs.JOBS, "j1", fake_job("p1"))
    before = (pdir / "project.json").read_bytes()
    status, data = post(gui_server, "/api/project/vision", {"project": "p1", "enabled": True, "tier": "economy"})
    assert status == 409 and data["error"] == project_routes.VISION_BUSY_MSG
    assert (pdir / "project.json").read_bytes() == before


@pytest.mark.usefixtures("consented")
def test_api_post_vision_other_projects_job_does_not_block(gui_server, monkeypatch):
    make_project(gui_server.root)
    make_project(gui_server.root, "p2")
    monkeypatch.setitem(project_routes.jobs.JOBS, "j1", fake_job("p2"))
    status, _ = post(gui_server, "/api/project/vision", {"project": "p1", "enabled": True, "tier": "economy"})
    assert status == 200 and project_json(gui_server)["vision"]["enabled"] is True


@pytest.mark.usefixtures("consented")
def test_api_post_vision_change_after_analysis_marks_step_stale(gui_server, monkeypatch):
    from pipeline import media_io
    monkeypatch.setattr(media_io, "is_complete", lambda p, **k: p.exists())
    pdir = make_project(gui_server.root)
    for rel in ("work/proxy.mp4", "work/segments_scored.json", "work/content_summary.json",
                "work/questions.json", "work/selection.json"):
        (pdir / rel).write_text("{}", encoding="utf-8")
    cfg = schema.load(pdir / "project.json")  # 迁移后的配置（分析时用的就是它）
    stamp = {k: v for k, v in fingerprints.analysis_inputs(cfg).items() if k != "vision"}  # 改版前的戳
    (pdir / "work/analysis_inputs.json").write_text(json.dumps(stamp), encoding="utf-8")
    status, data = post(gui_server, "/api/project/vision", {"project": "p1", "enabled": True, "tier": "economy"})
    analyze = next(s for s in data["wizard"]["steps"] if s["key"] == "analyze")
    assert status == 200 and analyze["status"] == wizard.STALE and analyze["reasons"] == ["vision"]


# ---------------------------------------------------------------- 第 3 阶段：接口参数
def test_every_tier_has_params_and_frames_fit_api_limit():
    assert set(vision.TIER_FPS) == set(vision.TIERS)
    longest = vision.CHUNK_S + vision.MIN_TAIL_S
    for tier in vision.TIERS:
        opt = vision.tier_params(tier)["manual_option"]
        assert opt["need_audio"] is False and 0.2 <= opt["fps"] <= 5
        assert opt["fps"] * longest <= vision.MAX_FRAMES


def test_tier_params_returns_fresh_dict():
    a = vision.tier_params("economy")
    a["manual_option"]["fps"] = 99
    assert vision.tier_params("economy")["manual_option"]["fps"] == 2.0


@pytest.mark.parametrize("cfg,on", [({}, False), ({"vision": OFF}, False),
                                    ({"vision": {"enabled": True, "tier": "quality"}}, True),
                                    ({"vision": {"enabled": "yes"}}, False)])
def test_is_on(cfg, on):
    assert vision.is_on(cfg) is on


def test_vision_bitrate():
    from pipeline import encode
    assert "300k" in encode.h264_args("vision", "h264_videotoolbox")


# ---------------------------------------------------------------- 档位提示（真账号验收 2026-10-30）
STEP_ANALYZE_JS = Path(__file__).resolve().parent.parent / "gui" / "static" / "step-analyze.js"
MEASURED_ECONOMY_TOKENS_PER_HOUR = 460_037 / 3258.4 * 3600  # 54 分钟素材、省钱档实测，约 51 万


def _tier_hint() -> str:
    match = re.search(r"const COPY_VISION_TIER_HINT = '([^']*)'", STEP_ANALYZE_JS.read_text(encoding="utf-8"))
    assert match, "step-analyze.js 里找不到 COPY_VISION_TIER_HINT"
    return match.group(1)


def test_tier_hint_states_economy_fps_and_measured_tokens():
    hint = _tier_hint()
    assert f"每秒看 {vision.TIER_FPS['economy']:g} 帧" in hint
    stated = int(re.search(r"约 (\d+) 万 tokens", hint).group(1)) * 10_000
    assert abs(stated - MEASURED_ECONOMY_TOKENS_PER_HOUR) / MEASURED_ECONOMY_TOKENS_PER_HOUR < 0.15
