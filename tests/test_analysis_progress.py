# -*- coding: utf-8 -*-
"""M13 T6：② 分析的人话进度（纯函数 + 读盘 + 接口）。"""
import json
from datetime import datetime, timezone

from gui import analysis
from conftest import call, make_project

JOB_START = 1_700_000_000.0


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def timing(epoch, seconds=1.0, ok=True, **extra):
    return {"started": iso(epoch), "seconds": seconds, "ok": ok, **extra}


def facts(done=(), timings=None, job=None):
    arts = {k: (k in done) for k in analysis.ARTIFACT_KEYS}
    return {"artifacts": arts, "timings": timings or {}, "job": job}


def running_job(**extra):
    return {"task": "prepare", "status": "running", "started": JOB_START, "last_error": None, **extra}


def statuses(result):
    return {s["key"]: s["status"] for s in result["steps"]}


def test_fresh_project_all_waiting():
    res = analysis.progress(facts())
    assert [s["key"] for s in res["steps"]] == [
        "ingest", "proxy", "audio", "asr", "voice", "visual", "text", "score", "summary",
        "questions", "select"]
    assert set(statuses(res).values()) == {"waiting"}
    assert (res["done"], res["total"], res["complete"]) == (0, 11, False)
    assert res["running"] is None and res["failed"] is None
    assert res["notice"] == analysis.NOTICE


def test_running_splits_transcribe_into_audio_done_and_asr_running():
    res = analysis.progress(facts(
        done={"materials", "proxy", "wav"},
        timings={"ingest": timing(JOB_START + 1), "junk": timing(JOB_START + 2)},
        job=running_job()))
    st = statuses(res)
    assert [st[k] for k in ("ingest", "proxy", "audio")] == ["done"] * 3
    assert st["asr"] == "running" and res["running"] == "asr"
    assert st["voice"] == "waiting" and res["done"] == 3


def test_running_before_wav_is_audio_step():
    res = analysis.progress(facts(
        done={"materials", "proxy"},
        timings={"ingest": timing(JOB_START + 1), "junk": timing(JOB_START + 2)},
        job=running_job()))
    assert res["running"] == "audio"


def test_running_first_stage_without_any_timing_is_ingest():
    res = analysis.progress(facts(job=running_job()))
    assert res["running"] == "ingest"


def test_skipped_steps_from_previous_run_still_count_as_done():
    old = {"ingest": timing(JOB_START - 500), "junk": timing(JOB_START - 400)}
    res = analysis.progress(facts(done={"materials", "proxy"}, timings=old, job=None))
    assert statuses(res)["ingest"] == "done" and statuses(res)["proxy"] == "done"


def test_last_skipped_counts_as_fresh_for_current_stage():
    timings = {"ingest": timing(JOB_START - 500, last_skipped=iso(JOB_START + 1)),
               "junk": timing(JOB_START - 400, last_skipped=iso(JOB_START + 2)),
               "transcribe": timing(JOB_START - 300, last_skipped=iso(JOB_START + 3))}
    res = analysis.progress(facts(
        done={"materials", "proxy", "wav", "segments"}, timings=timings, job=running_job()))
    assert res["running"] == "voice"


def test_failed_stage_reports_label_and_last_error_line():
    done = {"materials", "proxy", "wav", "segments", "audio_json", "visual"}
    timings = {"text": timing(JOB_START + 9, ok=False)}
    job = running_job(status="failed", last_error="AI 理解失败：网络不通")
    res = analysis.progress(facts(done=done, timings=timings, job=job))
    assert statuses(res)["text"] == "failed" and res["running"] is None
    assert res["failed"] == {"key": "text", "label": "AI 理解对话", "reason": "AI 理解失败：网络不通"}
    assert statuses(res)["score"] == "waiting"


def test_failed_without_job_has_no_reason():
    res = analysis.progress(facts(done={"materials"}, timings={"junk": timing(1, ok=False)}))
    assert res["failed"]["key"] == "proxy" and res["failed"]["reason"] is None


def test_failure_is_ignored_while_a_new_run_is_in_progress():
    res = analysis.progress(facts(
        done={"materials", "proxy", "wav", "segments", "audio_json", "visual"},
        timings={"text": timing(JOB_START - 10, ok=False)}, job=running_job()))
    assert res["failed"] is None


def test_failure_is_ignored_when_artifact_exists():
    res = analysis.progress(facts(done={"materials", "proxy"},
                                  timings={"ingest": timing(1, ok=False)}))
    assert res["failed"] is None and statuses(res)["ingest"] == "done"


def test_visual_done_when_quality_skipped_with_ok_true():
    timings = {"scenes": timing(1, 2.0), "quality": timing(2, 3.0)}
    res = analysis.progress(facts(timings=timings))  # 画面质量没产出文件（警告跳过）
    assert statuses(res)["visual"] == "done"


def test_visual_fails_when_scenes_failed():
    timings = {"scenes": timing(1, 2.0, ok=False)}
    res = analysis.progress(facts(timings=timings))
    assert statuses(res)["visual"] == "failed"


def test_seconds_sum_over_merged_stages_and_transcribe_only_on_asr():
    timings = {"scenes": timing(1, 2.0), "quality": timing(2, 3.5), "transcribe": timing(3, 40.0),
               "select": timing(4, 1.0), "brief": timing(5, 0.5)}
    res = analysis.progress(facts(done={"wav", "segments"}, timings=timings))
    by = {s["key"]: s["seconds"] for s in res["steps"]}
    assert by["visual"] == 5.5 and by["asr"] == 40.0 and by["audio"] is None
    assert by["select"] == 1.5 and by["ingest"] is None


def test_complete_matches_wizard_criterion():
    needed = {"proxy", "scored", "summary", "questions", "selection"}
    assert analysis.progress(facts(done=needed))["complete"] is True
    assert analysis.progress(facts(done=needed - {"proxy"}))["complete"] is False
    assert analysis.is_complete({k: k in needed for k in analysis.ARTIFACT_KEYS}) is True


def test_non_prepare_job_does_not_mean_analysis_running():
    res = analysis.progress(facts(job=running_job(task="build")))
    assert res["running"] is None


def test_garbage_timings_are_tolerated():
    timings = {"ingest": "oops", "junk": {"started": "不是时间", "seconds": "x", "ok": True}}
    res = analysis.progress(facts(job=running_job(), timings=timings))
    assert res["total"] == 11


# ---------------------------------------------------------------- 读盘
def test_facts_reads_artifacts_timings_and_job(tmp_path):
    pdir = make_project(tmp_path, **{
        "work/materials.json": "{}", "work/segments_scored.json": "{}",
        "work/timings.json": json.dumps({"ingest": timing(1)}),
        "work/proxy.mp4": b"x"})
    f = analysis.facts(pdir, {"material": "/tmp/a.mp4"}, None)
    assert f["artifacts"]["materials"] and f["artifacts"]["scored"]
    assert not f["artifacts"]["summary"] and not f["artifacts"]["selection"]
    assert f["timings"]["ingest"]["ok"] is True and f["job"] is None


def test_facts_tolerates_corrupt_timings(tmp_path):
    pdir = make_project(tmp_path, **{"work/timings.json": "{坏"})
    assert analysis.facts(pdir, {}, None)["timings"] == {}


# ---------------------------------------------------------------- 接口
def test_api_analysis_ok(gui_server):
    make_project(gui_server.root, **{"work/materials.json": "{}"})
    status, raw, _ = call(gui_server, "GET", "/api/analysis?project=p1")
    data = json.loads(raw)
    assert status == 200 and data["total"] == 11 and data["steps"][0]["status"] == "done"


def test_api_analysis_missing_project_404(gui_server):
    assert call(gui_server, "GET", "/api/analysis?project=nope")[0] == 404


def test_api_analysis_bad_name_400(gui_server):
    assert call(gui_server, "GET", "/api/analysis?project=" + "%2E%2E")[0] == 400


def test_api_analysis_corrupt_project_409(gui_server):
    pdir = make_project(gui_server.root)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    assert call(gui_server, "GET", "/api/analysis?project=p1")[0] == 409


def test_api_analysis_requires_session(gui_server):
    make_project(gui_server.root)
    assert call(gui_server, "GET", "/api/analysis?project=p1", token=False)[0] == 403


# ---------------------------------------------------------------- 评审修复
def test_reanalysis_old_timings_do_not_count_as_done():
    """重新分析：上一轮的计时 / 产物不算本轮完成，当前步骤 = 第一个还没跑到的。"""
    old = {k: timing(JOB_START - 500) for k in ("ingest", "junk", "transcribe", "analyze", "scenes", "quality", "text")}
    done = {"materials", "proxy", "wav", "segments", "audio_json", "visual", "text_json", "scored"}
    res = analysis.progress(facts(done=done, timings=old, job=running_job()))
    st = statuses(res)
    assert res["running"] == "ingest" or st["ingest"] == "running"
    assert st["visual"] != "done" and st["text"] != "done" and st["score"] != "done"


def test_reanalysis_progress_advances_with_fresh_stages():
    done = {"materials", "proxy", "wav", "segments", "audio_json", "visual", "text_json", "scored"}
    old = {k: timing(JOB_START - 500) for k in ("transcribe", "analyze", "scenes", "quality", "text")}
    fresh = {k: timing(JOB_START + 3) for k in ("ingest", "junk")}
    res = analysis.progress(facts(done=done, timings={**old, **fresh}, job=running_job()))
    st = statuses(res)
    assert st["ingest"] == "done" and st["proxy"] == "done"
    assert st["audio"] == "done" and st["asr"] == "running"
    assert st["text"] == "waiting" and st["visual"] == "waiting"


def test_visual_old_timings_not_done_while_running():
    timings = {"scenes": timing(JOB_START - 10), "quality": timing(JOB_START - 9)}
    assert statuses(analysis.progress(facts(timings=timings, job=running_job())))["visual"] != "done"


def test_same_second_timing_counts_as_fresh():
    """timings 的时间截断到秒，任务开始是小数秒：同一秒内记录的阶段不能被当成旧的。"""
    start = 1_700_000_000.7
    timings = {"ingest": timing(1_700_000_000)}  # 实际在 start 之后 0.2 秒，但截断成 .000
    res = analysis.progress(facts(done={"materials"}, timings=timings, job=running_job(started=start)))
    assert statuses(res)["ingest"] == "done" and res["running"] == "proxy"


def test_facts_does_not_adopt_unmarked_proxy_or_write_markers(tmp_path):
    from pipeline import media_io
    pdir = make_project(tmp_path, **{"work/proxy.mp4": b"legacy-bytes"})
    f = analysis.facts(pdir, {"material": "/tmp/a.mp4"}, running_job())
    assert f["artifacts"]["proxy"] is False
    assert not media_io.done_marker(pdir / "work/proxy.mp4").exists()
