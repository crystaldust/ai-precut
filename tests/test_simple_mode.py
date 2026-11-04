# -*- coding: utf-8 -*-
"""简单模式：mode 模块、schema 默认、选段指纹、向导、选段、⑤ 载荷、接口、CLI。"""
import json

import pytest

from conftest import call, make_project
from gui import wizard
from pipeline import fingerprints, mode, schema


def post(gs, path, body):
    status, raw, _ = call(gs, "POST", path, body)
    return status, json.loads(raw)


# ---------------------------------------------------------------- 模块 / schema
def test_module_constants_and_schema_default():
    assert mode.MODES == ("full", "simple") and mode.DEFAULT == "full" == schema.DEFAULTS["mode"]


@pytest.mark.parametrize("raw,expected", [("simple", "simple"), ("full", "full"), (None, "full"), ("x", "full"),
                                          (1, "full"), ([], "full"), ("SIMPLE", "full")])
def test_normalize_invalid_reads_as_full(raw, expected):
    assert mode.normalize(raw) == expected


def test_is_simple_reads_cfg_leniently():
    assert mode.is_simple({"mode": "simple"}) and not mode.is_simple({}) and not mode.is_simple(None)
    assert not mode.is_simple({"mode": "weird"})


@pytest.mark.parametrize("bad", [None, "", "Simple", 1, True, ["simple"]])
def test_check_rejects_invalid(bad):
    with pytest.raises(ValueError, match="出片模式"):
        mode.check(bad)


def test_check_accepts_valid():
    assert mode.check("simple") == "simple" and mode.check("full") == "full"


def test_migrate_fills_mode_for_old_projects():
    cfg, changes = schema.migrate({"name": "p", "material": "/m", "schema_version": 2})
    assert cfg["mode"] == "full" and "补齐 mode" in changes


# ---------------------------------------------------------------- 指纹
def test_full_mode_selection_inputs_unchanged(tmp_path):
    assert "mode" not in fingerprints.selection_inputs(tmp_path, {})
    assert "mode" not in fingerprints.selection_inputs(tmp_path, {"mode": "full"})
    assert "mode" not in fingerprints.selection_inputs(tmp_path, {"mode": "junk"})


def test_simple_mode_inputs_are_scored_overrides_mode_only(tmp_path):
    now = fingerprints.selection_inputs(tmp_path, {"mode": "simple"})
    assert list(now) == ["scored", "overrides", "mode"] and now["mode"] == "simple"


def test_changed_detects_mode_switch_both_ways_even_for_old_saved(tmp_path):
    full = fingerprints.selection_inputs(tmp_path, {})
    simple = fingerprints.selection_inputs(tmp_path, {"mode": "simple"})
    assert fingerprints.changed(full, simple) == ["mode"]   # 旧戳没有 mode = full
    assert fingerprints.changed(simple, full) == ["mode"]
    assert fingerprints.changed(simple, simple) == [] and fingerprints.changed(full, full) == []
    assert fingerprints.changed(None, simple) == []         # 没有戳仍不判


def test_full_target_change_then_mode_switch_lists_both_reasons(tmp_path):
    a = fingerprints.selection_inputs(tmp_path, {"target_duration": 100})
    b = fingerprints.selection_inputs(tmp_path, {"target_duration": 90})
    assert fingerprints.changed(a, b) == ["target"]
    assert fingerprints.changed({**a, "mode": "simple"}, b) == ["target", "mode"]


def test_simple_mode_ignores_target_answers_and_preferences(tmp_path):
    (tmp_path / "brief_answers.json").write_text(json.dumps({"answers": {"q1": "a"}}), encoding="utf-8")
    base = {"mode": "simple", "target_duration": 100, "calibration": {"tone": "info"}}
    saved = fingerprints.selection_inputs(tmp_path, base)
    (tmp_path / "brief_answers.json").write_text(json.dumps({"answers": {"q1": "b"}}), encoding="utf-8")
    for cfg in ({**base, "target_duration": 50}, {**base, "calibration": {"tone": "emotion", "must_lines": "x"}}, base):
        assert fingerprints.changed(saved, fingerprints.selection_inputs(tmp_path, cfg)) == []


def test_simple_mode_overrides_and_scored_changes_are_stale(tmp_path):
    cfg = {"mode": "simple"}
    saved = fingerprints.selection_inputs(tmp_path, cfg)
    (tmp_path / "overrides.json").write_text(json.dumps({"S001": {"must_keep": True}}), encoding="utf-8")
    assert fingerprints.changed(saved, fingerprints.selection_inputs(tmp_path, cfg)) == ["overrides"]
    (tmp_path / "segments_scored.json").write_text("{}", encoding="utf-8")
    assert fingerprints.changed(saved, fingerprints.selection_inputs(tmp_path, cfg)) == ["scored", "overrides"]


# ---------------------------------------------------------------- 向导
SAVED = {"scored": "a", "overrides": "b", "answers": "c", "target": "175", "lines": "d"}


def F(**over):
    base = {"mode": "simple", "analysis_done": True, "analysis_running": False, "analysis_stamp": None,
            "analysis_inputs": None, "answers_confirmed": False, "answers_questions_digest": None,
            "questions_digest": None, "legacy": False, "selection_inputs_saved": SAVED,
            "selection_inputs_now": SAVED}
    return {**base, **over}


def step(d, key):
    return next(s for s in d["steps"] if s["key"] == key)


def test_simple_criteria_is_skipped_and_result_open_without_answers():
    d = wizard.derive(F())
    assert step(d, "criteria") == {"key": "criteria", "n": 4, "label": "定标准", "status": "skipped",
                                   "hint": "简单模式不需要定标准", "banner": None, "action": None, "reasons": []}
    assert step(d, "result")["status"] == "available" and d["next"] == "result"
    assert [s["key"] for s in d["steps"]] == [k for k, _, _ in wizard.STEPS]


def test_simple_next_never_criteria_even_when_unconfirmed_and_legacy():
    for over in ({}, {"legacy": True}, {"answers_confirmed": True, "answers_questions_digest": "a",
                                        "questions_digest": "b"}):
        assert wizard.derive(F(**over))["next"] != "criteria"


def test_simple_before_analysis_everything_after_is_locked():
    d = wizard.derive(F(analysis_done=False))
    assert d["next"] == "analyze" and step(d, "criteria")["status"] == "skipped"
    assert step(d, "result")["status"] == step(d, "export")["status"] == "locked"


def test_simple_export_follows_preview_and_next_goes_to_export():
    d = wizard.derive(F(preview_fresh=True))
    assert step(d, "result")["status"] == "done" and step(d, "export")["status"] == "available"
    assert d["next"] == "export"


def test_simple_mode_switch_marks_result_stale_with_reselect():
    d = wizard.derive(F(selection_inputs_now={**SAVED, "mode": "simple"}, selection_inputs_saved=SAVED))
    r = step(d, "result")
    assert r["status"] == "stale" and r["action"] == "reselect" and r["reasons"] == ["mode"]
    assert r["banner"] == "出片模式改了" + wizard.STALE_RESULT_ACTION and d["next"] == "result"


def test_full_mode_unchanged_and_missing_mode_fact_is_full():
    base = F(mode="full")
    assert step(wizard.derive(base), "criteria")["status"] == "available"
    assert step(wizard.derive(base), "result")["status"] == "locked"
    legacy_facts = {k: v for k, v in base.items() if k != "mode"}
    assert wizard.derive(legacy_facts) == wizard.derive(base)


def test_collect_reports_mode(tmp_path):
    pdir = make_project(tmp_path)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert wizard.collect(pdir, cfg, "p1")["mode"] == "full"
    assert wizard.collect(pdir, {**cfg, "mode": "simple"}, "p1")["mode"] == "simple"
    assert wizard.collect(pdir, {**cfg, "mode": "bogus"}, "p1")["mode"] == "full"


# ---------------------------------------------------------------- 选段
from pipeline import select  # noqa: E402
from test_select import TOPICS, seg  # noqa: E402

SIMPLE_RULES = {"must_topics": ["讲合同"], "exclude_topics": [], "ending": "sign"}


def pick(segs, **kw):
    return select.select(segs, TOPICS, kw.pop("rules", {}), kw.pop("target", 10), mode="simple", **kw)


def test_simple_select_only_clip_list_segments_in_time_order():
    segs = [seg(1, 30, 6, "讲合同", must=True), seg(2, 0, 5, "讲合同"), seg(3, 10, 7, "聊吃饭", must=True),
            seg(4, 50, 5, "讲合同", level=2)]
    res = pick(segs)
    assert [s["segment_id"] for s in res["shots"]] == ["S003", "S001"]
    assert [s["id"] for s in res["shots"]] == ["sel01", "sel02"]
    assert [(s["start"], s["end"]) for s in res["shots"]] == [(10, 17), (30, 36)]
    assert all(s["must_keep"] and s["sub"] for s in res["shots"])
    assert res["mode"] == "simple" and res["unused"] == [] and res["stats"]["shots"] == 2


def test_simple_select_ignores_target_budget_fill_and_rules():
    segs = [seg(i, i * 10, 8, "讲合同", must=(i == 1)) for i in range(1, 6)]
    res = pick(segs, target=500, rules={"must_lines": ["第3句"], "ending": "info"})
    assert [s["segment_id"] for s in res["shots"]] == ["S001"]
    assert res["over_target"] is False and res["suggested_target"] is None and res["over_target_warning"] is None
    assert not any("超出" in w for w in res["warnings"])
    # 剪辑列表远超目标也不报超时长
    over = pick([seg(i, i * 10, 8, "讲合同", must=True) for i in range(1, 5)], target=5)
    assert over["over_target"] is False and over["over_target_warning"] is None and len(over["shots"]) == 4


def test_simple_select_keeps_whole_segment_no_trim_no_hook():
    segs = [seg(1, 0, 40, "讲合同", must=True, key=True), seg(2, 50, 6, "讲合同", must=True, key=True),
            seg(3, 60, 6, "讲合同", must=True, key=True)]
    res = pick(segs, target=5)
    assert [(s["start"], s["end"]) for s in res["shots"]] == [(0, 40), (50, 56), (60, 66)]
    assert not any(s.get("role") for s in res["shots"])


def test_simple_select_empty_clip_list_gives_zero_shots_and_warning():
    res = pick([seg(1, 0, 5, "讲合同"), seg(2, 10, 5, "聊吃饭")])
    assert res["shots"] == [] and res["total"] == 0 and res["stats"]["shots"] == 0
    assert select.EMPTY_CLIP_LIST_WARNING in res["warnings"]
    assert select.EMPTY_CLIP_LIST_WARNING == "剪辑列表是空的：先在「③ 看素材」把要用的片段放进剪辑列表"


def test_simple_select_drops_unusable_and_keeps_zero_length_warning():
    segs = [seg(1, 0, 5, "讲合同", must=True), {**seg(2, 10, 5, "讲合同", must=True), "unusable": True},
            seg(3, 20, 0, "讲合同", must=True)]
    res = pick(segs)
    assert [s["segment_id"] for s in res["shots"]] == ["S001"]
    assert any("S003" in w for w in res["warnings"])
    assert select.EMPTY_CLIP_LIST_WARNING not in res["warnings"]


def test_full_mode_default_unchanged_has_no_mode_key_and_still_selects():
    segs = [seg(1, 0, 5, "讲合同"), seg(2, 10, 5, "聊吃饭")]
    res = select.select(segs, TOPICS, {}, 60)
    assert "mode" not in res and res["shots"]


# ---------------------------------------------------------------- select.run / CLI
from argparse import Namespace  # noqa: E402

import aicut  # noqa: E402
from test_aicut_must_keep import _cfg, _fail, _new_args, _project  # noqa: E402


def _scored(tmp_path, segs):
    sp = tmp_path / "scored.json"
    sp.write_text(json.dumps({"target": 60, "topics": TOPICS, "segments": segs}, ensure_ascii=False),
                  encoding="utf-8")
    ap = tmp_path / "answers.json"
    ap.write_text(json.dumps({"answers": {}}), encoding="utf-8")
    return sp, ap


def test_run_simple_records_mode_and_inputs_and_writes_files(tmp_path):
    sp, ap = _scored(tmp_path, [seg(1, 0, 6, "讲合同"), seg(2, 10, 6, "聊吃饭")])
    (tmp_path / "overrides.json").write_text(json.dumps({"S001": {"must_keep": True}}), encoding="utf-8")  # 剪辑列表来自 overrides.json
    res = select.run(sp, ap, tmp_path, title="t", material="/m.mp4", mode="simple", target=500)
    saved = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert saved["mode"] == "simple" and saved["inputs"]["mode"] == "simple" == res["inputs"]["mode"]
    assert [s["segment_id"] for s in saved["shots"]] == ["S001"] and "简单模式" in (tmp_path / "分镜表-选段.md").read_text(encoding="utf-8")
    shots = json.loads((tmp_path / "shots-selected.json").read_text(encoding="utf-8"))
    assert len(shots["shots"] if isinstance(shots, dict) else shots) == 1


def test_run_simple_changed_target_adds_no_budget_warning(tmp_path):
    sp, ap = _scored(tmp_path, [seg(1, 0, 6, "讲合同")])
    res = select.run(sp, ap, tmp_path, mode="simple", target=500)
    assert not any("话题" in w for w in res["warnings"])


def test_run_full_inputs_have_no_mode(tmp_path):
    sp, ap = _scored(tmp_path, [seg(1, 0, 6, "讲合同")])
    assert "mode" not in select.run(sp, ap, tmp_path)["inputs"]


def test_cmd_select_passes_simple_ignores_target_and_skips_custom(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})
    (pdir / "project.json").write_text(json.dumps(
        {"name": "p", "material": "/tmp/a.mp4", "schema_version": 2, "target_duration": 175, "mode": "simple"}),
        encoding="utf-8")
    monkeypatch.setattr(aicut, "_interpret_custom", _fail)
    seen = {}

    def fake_run(*a, **kw):
        seen.update(kw)
        return {"stats": {"shots": 0, "must_keep": 0}, "total": 0, "target": kw["target"], "mode": "simple",
                "missing_must_topics": [], "warnings": []}

    monkeypatch.setattr(aicut.select, "run", fake_run)
    aicut.cmd_select(Namespace(name="p", target="300"))
    assert seen["mode"] == "simple" and seen["target"] == 175 and seen["custom"] is None
    assert _cfg(pdir / "project.json")["target_duration"] == 175  # --target 被忽略，也不保存


def test_cmd_select_full_project_passes_full(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})
    monkeypatch.setattr(aicut, "_interpret_custom", lambda w: {"items": []})
    seen = {}
    monkeypatch.setattr(aicut.select, "run", lambda *a, **kw: seen.update(kw) or {
        "stats": {"shots": 0}, "total": 0, "target": 175, "missing_must_topics": [], "warnings": []})
    aicut.cmd_select(Namespace(name="p", target=None))
    assert seen["mode"] == "full"


def test_new_default_mode_is_full_and_simple_is_stored(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    aicut.cmd_new(_new_args(tmp_path, target="240", no_input=True))
    assert _cfg(tmp_path / "projects/n1/project.json")["mode"] == "full"
    aicut.cmd_new(_new_args(tmp_path, name="n2", target="240", no_input=True, mode="simple"))
    assert _cfg(tmp_path / "projects/n2/project.json")["mode"] == "simple"


def test_new_cli_mode_flag_parses_and_rejects_invalid():
    from collections import defaultdict
    from pipeline import cli_args
    parser = cli_args.build_parser(defaultdict(lambda: (lambda a: None)))
    base = ["new", "p", "--material", "/m.mp4"]
    assert parser.parse_args(base).mode == "full"
    assert parser.parse_args([*base, "--mode", "simple"]).mode == "simple"
    with pytest.raises(SystemExit):
        parser.parse_args([*base, "--mode", "fast"])


# ---------------------------------------------------------------- 接口
from gui import project_routes  # noqa: E402
from test_result_view import _project as result_project  # noqa: E402


@pytest.fixture
def recorder(gui_server, monkeypatch):
    calls = []
    monkeypatch.setattr(gui_server.module, "run_aicut", lambda args: calls.append(args) or (0, ""))
    return calls


def project_json(gs, name="p1"):
    return json.loads((gs.root / name / "project.json").read_text(encoding="utf-8"))


def fake_job(project):
    return {"status": "running", "log": [], "exit": None, "started": 0.0, "task": "prepare", "project": project,
            "popen": None, "cancel": False, "thread": None, "out_lines": 0}


NEW = {"name": "n1", "material": "/tmp/a.mp4", "preset": "纪实3min"}


@pytest.mark.usefixtures("consented")
def test_api_new_mode_simple_passes_flag_and_absent_has_old_args(gui_server, recorder):
    assert post(gui_server, "/api/new", NEW)[0] == 200
    assert recorder[0] == ["new", "n1", "--no-input", "--material=/tmp/a.mp4", "--preset=纪实3min", "--title=n1"]
    assert post(gui_server, "/api/new", {**NEW, "mode": "simple"})[0] == 200
    assert "--mode=simple" in recorder[1]


@pytest.mark.usefixtures("consented")
@pytest.mark.parametrize("bad", ["fast", "", 1, ["simple"], True])
def test_api_new_invalid_mode_is_400_and_nothing_runs(gui_server, recorder, bad):
    status, data = post(gui_server, "/api/new", {**NEW, "mode": bad})
    assert status == 400 and "出片模式" in data["error"] and recorder == []


@pytest.mark.usefixtures("consented")
def test_api_settings_mode_saves_and_returns_wizard(gui_server):
    make_project(gui_server.root)
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "mode": "simple"})
    assert status == 200 and data["project"]["mode"] == "simple" and project_json(gui_server)["mode"] == "simple"
    crit = next(s for s in data["wizard"]["steps"] if s["key"] == "criteria")
    assert crit["status"] == "skipped"
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "mode": "full"})
    assert status == 200 and project_json(gui_server)["mode"] == "full"


@pytest.mark.usefixtures("consented")
@pytest.mark.parametrize("bad", ["fast", None, 3, ""])
def test_api_settings_invalid_mode_is_400_and_untouched(gui_server, bad):
    pdir = make_project(gui_server.root)
    before = (pdir / "project.json").read_bytes()
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "mode": bad})
    assert status == 400 and "出片模式" in data["error"]
    assert (pdir / "project.json").read_bytes() == before


@pytest.mark.usefixtures("consented")
def test_api_settings_mode_while_job_runs_is_409_but_same_value_is_not_blocked(gui_server, monkeypatch):
    pdir = make_project(gui_server.root)
    monkeypatch.setitem(project_routes.jobs.JOBS, "j1", fake_job("p1"))
    before = (pdir / "project.json").read_bytes()
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "mode": "simple"})
    assert status == 409 and data["error"] == project_routes.MODE_BUSY_MSG
    assert (pdir / "project.json").read_bytes() == before
    assert post(gui_server, "/api/project/settings", {"project": "p1", "mode": "full"})[0] == 200  # 没改


@pytest.mark.usefixtures("consented")
def test_api_settings_mode_switch_marks_result_stale_with_reselect(gui_server, monkeypatch):
    from pipeline import media_io
    monkeypatch.setattr(media_io, "is_complete", lambda p, **k: p.exists())
    pdir = make_project(gui_server.root)
    for rel in ("work/proxy.mp4", "work/segments_scored.json", "work/content_summary.json",
                "work/questions.json"):
        (pdir / rel).write_text("{}", encoding="utf-8")
    cfg = schema.load(pdir / "project.json")
    (pdir / "work/analysis_inputs.json").write_text(json.dumps(fingerprints.analysis_inputs(cfg)), encoding="utf-8")
    (pdir / "work/selection.json").write_text(
        json.dumps({"inputs": fingerprints.selection_inputs(pdir / "work", cfg)}), encoding="utf-8")
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "mode": "simple"})
    result = next(s for s in data["wizard"]["steps"] if s["key"] == "result")
    assert status == 200 and result["status"] == "stale" and result["action"] == "reselect"
    assert result["reasons"] == ["mode"] and "出片模式改了" in result["banner"]


@pytest.mark.usefixtures("consented")
def test_result_payload_simple_mode_has_mode_no_unused_and_no_target(gui_server):
    result_project(gui_server.root, cfg_extra={"mode": "simple"})
    status, raw, _ = call(gui_server, "GET", "/api/result?project=p1")
    data = json.loads(raw)
    assert status == 200 and data["mode"] == "simple" and data["unused"] == []
    top = data["topbar"]
    assert top["target"] is None and top["over_target"] is False and top["suggested_target"] is None
    assert top["shots"] == 2 and top["total"] == 20.0 and top["clip"]["count"] == 1


@pytest.mark.usefixtures("consented")
def test_result_payload_full_mode_reports_full_and_keeps_unused(gui_server):
    result_project(gui_server.root)
    data = json.loads(call(gui_server, "GET", "/api/result?project=p1")[1])
    assert data["mode"] == "full" and data["unused"] and data["topbar"]["target"] == 175


# ---------------------------------------------------------------- 空分镜表出片
def test_current_shots_empty_table_dies_with_friendly_message(tmp_path):
    from pipeline import export_flow
    pdir = tmp_path / "p"
    (pdir / "work").mkdir(parents=True)
    (pdir / "shots.json").write_text('{"shots": []}', encoding="utf-8")

    class Ops:
        def info(self, *_a): pass

        def die(self, msg):
            raise SystemExit(msg)

    with pytest.raises(SystemExit) as exc:
        export_flow.current_shots(Ops(), pdir)
    assert str(exc.value) == export_flow.EMPTY_TABLE_MSG and "剪辑列表" in export_flow.EMPTY_TABLE_MSG


@pytest.mark.usefixtures("consented")
@pytest.mark.parametrize("stored,expected", [(None, "full"), ("simple", "simple"), ("bogus", "full")])
def test_browse_payload_project_has_mode(gui_server, stored, expected):
    from test_browse_payload import _project as browse_project
    pdir = browse_project(gui_server)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    (pdir / "project.json").write_text(json.dumps({**cfg, **({"mode": stored} if stored else {})}), encoding="utf-8")
    data = json.loads(call(gui_server, "GET", "/api/browse?project=p1")[1])
    assert data["project"]["mode"] == expected
    state = json.loads(call(gui_server, "GET", "/api/state?project=p1")[1])
    assert state["project"]["mode"] == expected


# ---------------------------------------------------------------- 审查补充
@pytest.mark.usefixtures("consented")
def test_api_new_mode_null_is_400_like_settings(gui_server, recorder):
    status, data = post(gui_server, "/api/new", {**NEW, "mode": None})
    assert status == 400 and "出片模式" in data["error"] and recorder == []


@pytest.mark.usefixtures("consented")
def test_api_settings_response_project_has_normalized_mode_for_legacy_project(gui_server):
    pdir = make_project(gui_server.root)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    (pdir / "project.json").write_text(json.dumps({k: v for k, v in cfg.items() if k != "mode"}), encoding="utf-8")
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "title": "新片名"})
    assert status == 200 and data["project"]["mode"] == "full" and data["project"]["title"] == "新片名"


@pytest.mark.usefixtures("consented")
def test_must_keep_and_unusable_together_count_the_same_in_topbar_and_simple_select(gui_server):
    """手写坏的 overrides 里一段同时 must_keep + unusable：API 写入互斥（后按生效），读取时两边都按不可用处理。"""
    from test_result_view import SEGS
    pdir = result_project(gui_server.root, cfg_extra={"mode": "simple"})
    ov = pdir / "work/overrides.json"
    data = json.loads(ov.read_text(encoding="utf-8"))
    both = {**data, "S3": {"must_keep": True, "unusable": True}}
    ov.write_text(json.dumps(both), encoding="utf-8")
    top = json.loads(call(gui_server, "GET", "/api/result?project=p1")[1])["topbar"]
    assert top["clip"]["count"] == 1  # 只有 S4（S3 不可用不算）
    res = select.select([{**s, "must_keep": s["id"] in ("S3", "S4"), "unusable": s["id"] == "S3",
                          "signals": {}, "key_info": False} for s in SEGS], TOPICS, {}, 10, mode="simple")
    assert [x["segment_id"] for x in res["shots"]] == ["S4"]


def test_review_api_writes_keep_must_keep_and_unusable_exclusive(tmp_path):
    from pipeline import review
    review.set_must(tmp_path, "S1", True)
    review.set_unusable(tmp_path, "S1", True)
    item = review.load(tmp_path)["S1"]
    assert item["unusable"] is True and item["must_keep"] is False


def test_run_simple_edited_bounds_visual_clip_and_stale_override(tmp_path):
    visual = {"id": "V001", "kind": "visual", "start": 20.0, "end": 30.0, "text": "", "level": 2,
              "level_reason": "画面片段", "label": "扫码付款", "visual": {"desc": "一人扫码", "issues": []}}
    sp = tmp_path / "scored.json"
    sp.write_text(json.dumps({"target": 60, "topics": TOPICS, "visual_segments": [visual],
                              "segments": [seg(1, 0, 10, "讲合同"), seg(2, 40, 6, "聊吃饭")]},
                             ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "answers.json"
    ap.write_text(json.dumps({"answers": {}}), encoding="utf-8")
    (tmp_path / "overrides.json").write_text(json.dumps({
        "S001": {"must_keep": True, "start": 2.0, "end": 8.0},
        "V001": {"must_keep": True},
        "S099": {"must_keep": True, "anchor": {"text": "abcabcabcabc", "start": 99.0}}}), encoding="utf-8")
    res = select.run(sp, ap, tmp_path, mode="simple", target=5)
    shots = res["shots"]
    assert [(s["segment_id"], s["start"], s["end"]) for s in shots] == [("S001", 2.0, 8.0), ("V001", 20.0, 30.0)]
    assert shots[1]["note"] == "画面：扫码付款" and shots[0]["id"] == "sel01"
    assert res["unused"] == [] and res["over_target"] is False
    assert any(select.OVERRIDES_STALE_WARNING.split("{")[0] in w or "人工裁决" in w for w in res["warnings"])
