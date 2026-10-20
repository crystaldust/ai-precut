# -*- coding: utf-8 -*-
"""M13 T8：步骤状态判定（derive 纯函数表驱动 + collect 读盘 + /api/state 集成）。"""
import json

import pytest

from conftest import call, make_project
from gui import wizard
from pipeline import fingerprints

SAVED = {"scored": "a", "overrides": "b", "answers": "c", "target": "175", "lines": "d"}


def F(**over):
    base = {"analysis_done": False, "analysis_running": False,
            "analysis_stamp": None, "analysis_inputs": None, "answers_confirmed": False,
            "answers_questions_digest": None, "questions_digest": None, "legacy": False,
            "selection_inputs_saved": None, "selection_inputs_now": None}
    return {**base, **over}


def statuses(derived):
    return [s["status"] for s in derived["steps"]]


def by_key(derived, key):
    return next(s for s in derived["steps"] if s["key"] == key)


def test_step_table_shape():
    d = wizard.derive(F())
    assert [(s["key"], s["n"], s["label"]) for s in d["steps"]] == [
        ("new", 1, "新建"), ("analyze", 2, "分析"), ("browse", 3, "看素材"),
        ("criteria", 4, "定标准"), ("result", 5, "看结果"), ("export", 6, "导出")]
    assert all({"key", "n", "label", "status", "hint", "banner", "action", "reasons"} == set(s)
               for s in d["steps"])


def test_new_project_only_analyze_is_open():
    d = wizard.derive(F())
    assert statuses(d) == ["done", "available", "locked", "locked", "locked", "locked"]
    assert "② 分析" in by_key(d, "browse")["hint"]
    assert "② 分析" in by_key(d, "criteria")["hint"]
    assert "④ 定标准" in by_key(d, "result")["hint"] and "④ 定标准" in by_key(d, "export")["hint"]
    assert d["next"] == "analyze" and d["legacy"] is False


def test_running_analysis_keeps_everything_after_locked():
    d = wizard.derive(F(analysis_running=True))
    assert statuses(d) == ["done", "available", "locked", "locked", "locked", "locked"]
    assert d["next"] == "analyze"


def test_analysis_done_opens_browse_and_criteria():
    d = wizard.derive(F(analysis_done=True))
    assert statuses(d) == ["done", "done", "done", "available", "locked", "locked"]
    assert d["next"] == "criteria"


def test_preferences_changed_marks_analysis_stale():
    d = wizard.derive(F(analysis_done=True, analysis_stamp={"directive": "x", "preset": "p"},
                        analysis_inputs={"directive": "y", "preset": "p"}))
    step = by_key(d, "analyze")
    assert step["status"] == "stale" and step["action"] == "reanalyze"
    assert step["banner"] == wizard.STALE_ANALYZE and step["reasons"] == ["directive"]
    assert by_key(d, "browse")["status"] == "done"  # D4：下游不连锁


def test_old_project_without_stamp_is_not_stale():
    d = wizard.derive(F(analysis_done=True, analysis_stamp=None,
                        analysis_inputs={"directive": "y", "preset": "p"}))
    assert by_key(d, "analyze")["status"] == "done"


def test_matching_stamp_is_done():
    cur = {"directive": "y", "preset": "p"}
    assert by_key(wizard.derive(F(analysis_done=True, analysis_stamp=dict(cur),
                                  analysis_inputs=cur)), "analyze")["status"] == "done"


def test_confirmed_answers_open_result_and_export():
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True))
    assert statuses(d) == ["done"] * 4 + ["available"] * 2
    assert d["next"] == "result"


def test_regenerated_questions_make_criteria_stale():
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True,
                        answers_questions_digest="old", questions_digest="new"))
    step = by_key(d, "criteria")
    assert step["status"] == "stale" and step["banner"] == wizard.STALE_CRITERIA
    assert step["action"] is None
    assert by_key(d, "result")["status"] == "available"  # stale 的 ④ 不挡 ⑤⑥
    assert d["next"] == "criteria"


@pytest.mark.parametrize("saved,now", [(None, "new"), ("old", None), ("", "new"), ("old", "")])
def test_criteria_not_stale_when_either_digest_missing(saved, now):
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True,
                        answers_questions_digest=saved, questions_digest=now))
    assert by_key(d, "criteria")["status"] == "done"


def test_legacy_project_counts_as_criteria_done():
    d = wizard.derive(F(analysis_done=True, legacy=True))
    assert d["legacy"] is True
    assert statuses(d) == ["done"] * 4 + ["available"] * 2
    assert by_key(d, "criteria")["banner"] == wizard.LEGACY_NOTE


def test_selection_inputs_changed_marks_result_stale():
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True,
                        selection_inputs_saved=SAVED,
                        selection_inputs_now={**SAVED, "overrides": "changed"}))
    step = by_key(d, "result")
    assert step["status"] == "stale" and step["action"] == "reselect"
    assert step["reasons"] == ["overrides"]
    assert "素材标记改过了" in step["banner"] and step["banner"].endswith(wizard.STALE_RESULT_ACTION)
    assert by_key(d, "export")["status"] == "available"
    assert d["next"] == "result"


def test_multiple_reasons_follow_selection_key_order():
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True, selection_inputs_saved=SAVED,
                        selection_inputs_now={**SAVED, "answers": "x", "overrides": "y",
                                              "target": "90", "lines": "z", "scored": "w"}))
    step = by_key(d, "result")
    assert step["reasons"] == ["scored", "overrides", "answers", "target", "lines"]
    assert step["banner"] == ("分析结果更新了、素材标记改过了、答案改过了、目标时长改过了、"
                              "剪辑偏好里的指定原话改过了" + wizard.STALE_RESULT_ACTION)


def test_selection_without_saved_inputs_is_not_stale():
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True, selection_inputs_saved=None,
                        selection_inputs_now=SAVED))
    assert by_key(d, "result")["status"] == "available"


def test_unchanged_selection_inputs_not_stale():
    d = wizard.derive(F(analysis_done=True, answers_confirmed=True, selection_inputs_saved=SAVED,
                        selection_inputs_now=dict(SAVED)))
    assert by_key(d, "result")["status"] == "available"


def test_step_label_of_next_step():
    assert wizard.step_label(wizard.derive(F(analysis_done=True))) == {"n": 4, "label": "定标准"}
    assert wizard.step_label(wizard.derive(F())) == {"n": 2, "label": "分析"}


# ---------------------------------------------------------------- collect
def _full_analysis(extra=None):
    files = {"work/proxy.mp4": b"x", "work/segments_scored.json": "{}",
             "work/content_summary.json": "{}", "work/questions.json": '{"questions": []}',
             "work/selection.json": "{}"}
    return {**files, **(extra or {})}


@pytest.fixture
def adopt_all(monkeypatch):
    from pipeline import media_io
    monkeypatch.setattr(media_io, "is_complete", lambda p, **k: p.exists())


def _cfg(pdir):
    return json.loads((pdir / "project.json").read_text(encoding="utf-8"))


def test_collect_empty_project(tmp_path):
    pdir = make_project(tmp_path)
    f = wizard.collect(pdir, _cfg(pdir), "p1")
    assert f["analysis_done"] is False and f["analysis_running"] is False
    assert "analysis_failed" not in f and f["answers_confirmed"] is False
    assert f["analysis_stamp"] is None and f["selection_inputs_saved"] is None
    assert f["legacy"] is False and f["answers_questions_digest"] is None


def test_collect_analysis_done_needs_every_artifact(tmp_path, adopt_all):
    pdir = make_project(tmp_path, **_full_analysis())
    assert wizard.collect(pdir, _cfg(pdir), "p1")["analysis_done"] is True
    (pdir / "work/selection.json").unlink()
    assert wizard.collect(pdir, _cfg(pdir), "p1")["analysis_done"] is False


def test_collect_reads_stamps_and_digests(tmp_path, adopt_all):
    cfg_extra = {"calibration": {"tone": "info"}, "preset": "纪实3min"}
    pdir = make_project(tmp_path, **_full_analysis({
        "work/analysis_inputs.json": json.dumps({"directive": "旧", "preset": "纪实3min"}),
        "work/brief_answers.json": json.dumps({"answers": {"q1": "a"}, "confirmed": True,
                                               "questions_digest": "abc"}),
        "work/selection.json": json.dumps({"inputs": SAVED})}))
    cfg = {**_cfg(pdir), **cfg_extra}
    f = wizard.collect(pdir, cfg, "p1")
    assert f["analysis_stamp"] == {"directive": "旧", "preset": "纪实3min"}
    assert f["analysis_inputs"] == fingerprints.analysis_inputs(cfg)
    assert f["answers_confirmed"] is True and f["answers_questions_digest"] == "abc"
    assert f["questions_digest"] == fingerprints.file_digest(pdir / "work/questions.json")
    assert f["selection_inputs_saved"] == SAVED
    assert f["selection_inputs_now"] == fingerprints.selection_inputs(pdir / "work", cfg)


def test_collect_light_mode_skips_digests(tmp_path, adopt_all):
    pdir = make_project(tmp_path, **_full_analysis({"work/selection.json": json.dumps({"inputs": SAVED})}))
    f = wizard.collect(pdir, _cfg(pdir), "p1", digests=False)
    assert f["analysis_inputs"] is None and f["questions_digest"] is None
    assert f["selection_inputs_now"] is None and f["analysis_done"] is True
    assert wizard.derive(f)["steps"][4]["status"] == "locked"  # 未确认 ④


def test_collect_legacy_needs_unconfirmed_plus_version_or_manual_shots(tmp_path):
    pdir = make_project(tmp_path)
    (pdir / "output/v1").mkdir(parents=True)
    assert wizard.collect(pdir, _cfg(pdir), "p1")["legacy"] is True
    pdir2 = make_project(tmp_path, "p2", shots=[{"id": "s1", "in": 0, "out": 1}])
    assert wizard.collect(pdir2, _cfg(pdir2), "p2")["legacy"] is True
    (pdir / "work/brief_answers.json").write_text(json.dumps({"confirmed": True}), encoding="utf-8")
    assert wizard.collect(pdir, _cfg(pdir), "p1")["legacy"] is False


def test_collect_tolerates_corrupt_files(tmp_path):
    pdir = make_project(tmp_path, **{
        "work/brief_answers.json": "{坏", "work/selection.json": "[1]", "work/timings.json": "{坏",
        "work/analysis_inputs.json": "oops", "work/overrides.json": "{坏"})
    f = wizard.collect(pdir, _cfg(pdir), "p1")
    assert f["answers_confirmed"] is False and f["selection_inputs_saved"] is None
    assert f["analysis_stamp"] is None
    wizard.derive(f)  # 不抛


def test_collect_reports_running_prepare_job(tmp_path, monkeypatch):
    from gui import jobs
    pdir = make_project(tmp_path)
    monkeypatch.setattr(jobs, "project_job", lambda name: {"id": "x", "task": "prepare"})
    assert wizard.collect(pdir, _cfg(pdir), "p1")["analysis_running"] is True
    monkeypatch.setattr(jobs, "project_job", lambda name: {"id": "x", "task": "build"})
    assert wizard.collect(pdir, _cfg(pdir), "p1")["analysis_running"] is False


# ---------------------------------------------------------------- 接口
def test_state_has_wizard_and_busy(gui_server):
    make_project(gui_server.root)
    status, raw, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(raw)
    assert status == 200 and data["busy"] is None
    assert data["wizard"]["next"] == "analyze" and len(data["wizard"]["steps"]) == 6
    assert "stages" not in data and "junk" not in data  # D18：M13b 起旧阶段条、废片 tab 的数据不再下发


def test_state_busy_reports_running_job(gui_server, monkeypatch):
    from gui import jobs
    import sys
    make_project(gui_server.root)
    monkeypatch.setattr(jobs, "job_command", lambda t, n, e: [sys.executable, "-c", "import time; time.sleep(30)"])
    jobs.start_job("p1", "select")
    data = json.loads(call(gui_server, "GET", "/api/state?project=p1")[1])
    assert data["busy"]["task"] == "select" and data["busy"]["project"] == "p1"


def test_projects_list_items_have_step(gui_server):
    make_project(gui_server.root)
    bad = gui_server.root / "bad"
    bad.mkdir()
    (bad / "project.json").write_text("{坏", encoding="utf-8")
    data = json.loads(call(gui_server, "GET", "/api/projects")[1])
    steps = {p["name"]: p["step"] for p in data["projects"]}
    assert steps["p1"] == {"n": 2, "label": "分析"} and steps["bad"] is None
