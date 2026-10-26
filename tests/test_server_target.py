"""M2：GUI 服务的目标时长（/api/new、/api/job select）与选段摘要、分镜表预填。"""
import json
import time

import pytest

from conftest import call, make_project


@pytest.fixture
def recorder(gui_server, monkeypatch):
    calls = {"start_job": [], "run_aicut": []}

    def fake_start_job(*args):
        calls["start_job"].append(args)
        return "job1"

    def fake_run_aicut(args):
        calls["run_aicut"].append(args)
        return 0, ""

    monkeypatch.setattr(gui_server.module, "start_job", fake_start_job)
    monkeypatch.setattr(gui_server.module, "run_aicut", fake_run_aicut)
    return calls


NEW = {"name": "n1", "material": "/tmp/a.mp4", "preset": "纪实3min"}


# ---------------------------------------------------------------- /api/new
def test_new_passes_target(gui_server, recorder):
    status, _, _ = call(gui_server, "POST", "/api/new", {**NEW, "target": 240})
    assert status == 200
    assert "--target=240" in recorder["run_aicut"][0]


def test_new_without_target_passes_none(gui_server, recorder):
    status, _, _ = call(gui_server, "POST", "/api/new", NEW)
    assert status == 200
    assert not any(a.startswith("--target") for a in recorder["run_aicut"][0])


@pytest.mark.parametrize("bad", ["abc", -5, 99999, True, "1e999"])
def test_new_rejects_bad_target(gui_server, recorder, bad):
    status, body, _ = call(gui_server, "POST", "/api/new", {**NEW, "target": bad})
    assert status == 400 and recorder["run_aicut"] == []
    assert "目标时长" in json.loads(body)["error"]


# ---------------------------------------------------------------- /api/job select
def test_job_select_with_target(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job",
                        {"project": "p1", "task": "select", "target": "300"})
    assert status == 200
    assert recorder["start_job"] == [("p1", "select", ["--target", "300"])]


def test_job_select_without_target(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job", {"project": "p1", "task": "select"})
    assert status == 200
    assert recorder["start_job"] == [("p1", "select", [])]


def test_job_select_bad_target_rejected(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job",
                        {"project": "p1", "task": "select", "target": "0"})
    assert status == 400 and recorder["start_job"] == []


def test_start_job_knows_select(gui_server):
    assert gui_server.module.JOB_COMMANDS["select"] == ["select"]


def test_start_job_unknown_task_leaves_no_ghost_job(gui_server):
    before = dict(gui_server.module.JOBS)
    with pytest.raises(ValueError):
        gui_server.module.start_job("p1", "evil")
    assert gui_server.module.JOBS == before


def test_start_job_select_runs_aicut_select(gui_server, plain_attach, monkeypatch):
    seen = {}

    class FakePopen:
        pid = 0  # 与真 Popen 同形：有 pid / returncode
        returncode = None

        def __init__(self, argv, **kw):
            seen["argv"] = argv
            seen["stdin"] = kw.get("stdin")
            self.stdout = iter(["[✓] 选段 3 镜\n"])

        def wait(self):
            return 0

    srv = gui_server.module
    monkeypatch.setattr(srv.proc, "FROZEN", False)
    monkeypatch.setattr(srv.subprocess, "Popen", FakePopen)
    job = srv.start_job("p1", "select", ["--target", "300"])
    deadline = time.time() + 3
    while srv.JOBS[job]["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
    assert srv.JOBS[job]["status"] == "done"
    assert len(plain_attach) == 1  # 子进程确实被放进了进程树
    assert seen["argv"][2:] == ["select", "p1", "--target", "300"]
    assert seen["stdin"] is srv.subprocess.DEVNULL  # 子进程里 input() 不能卡住任务


# ---------------------------------------------------------------- /api/state
def test_state_includes_selection_summary(gui_server):
    sel = {"total": 214, "target": 175, "must_keep_total": 214, "over_target": True,
           "suggested_target": 215, "shots": [{"segment_id": "S001"}], "warnings": ["w"]}
    make_project(gui_server.root, **{"work/selection.json": json.dumps(sel)})
    status, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    got = json.loads(body)["selection"]
    assert status == 200 and got["over_target"] is True and got["suggested_target"] == 215
    assert "shots" not in got  # 只给摘要


def test_state_selection_null_without_selection(gui_server):
    make_project(gui_server.root)
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(body)
    assert data["selection"] is None and data["shots_from_selection"] is False


def test_state_prefills_storyboard_from_selection(gui_server):
    pre = {"shots": [{"id": "sel01", "in": 0, "out": 6, "sub": "a", "note": "t"}]}
    make_project(gui_server.root, **{"work/shots-selected.json": json.dumps(pre)})
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(body)
    assert data["shots"][0]["id"] == "sel01" and data["shots_from_selection"] is True


def test_state_keeps_manual_storyboard(gui_server):
    pre = {"shots": [{"id": "sel01", "in": 0, "out": 6}]}
    make_project(gui_server.root, shots=[{"id": "sh01", "in": 1, "out": 2}],
                 **{"work/shots-selected.json": json.dumps(pre)})
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(body)
    assert data["shots"][0]["id"] == "sh01" and data["shots_from_selection"] is False


def test_run_aicut_never_inherits_stdin(gui_server, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    srv = gui_server.module
    monkeypatch.setattr(srv.proc, "FROZEN", False)
    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    srv.run_aicut(["list"])
    assert seen["stdin"] is srv.subprocess.DEVNULL


# ---------------------------------------------------------------- M2 审查：警告要让剪辑师看到
def test_state_collects_warnings(gui_server):
    sel = {"total": 214, "target": 175, "over_target": True, "must_keep_total": 214,
           "suggested_target": 215, "over_target_warning": "必留内容共 3 分 34 秒…",
           "warnings": ["选段警告"], "missing_must_topics": ["讲合同"], "shots": []}
    scored = {"segments": [], "topics": [], "warnings": ["待定 50 段超过上限 40 段"]}
    make_project(gui_server.root, **{
        "work/selection.json": json.dumps(sel, ensure_ascii=False),
        "work/segments_scored.json": json.dumps(scored, ensure_ascii=False),
        "work/segments_text.partial.json": "{}"})
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(body)
    text = "\n".join(data["warnings"])
    for frag in ("必留内容共", "选段警告", "讲合同", "待定 50 段", "逐句标注没有完成"):
        assert frag in text
    assert data["selection"]["missing_must_topics"] == ["讲合同"]


def test_state_warnings_empty_for_clean_project(gui_server):
    make_project(gui_server.root)
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    assert json.loads(body)["warnings"] == []


def test_state_survives_corrupt_scored_file(gui_server):
    # KI-21：仍能打开（200），但警告栏必须点名损坏的三档判定，不能当「没有」
    make_project(gui_server.root, **{"work/segments_scored.json": "{坏"})
    status, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    warnings = json.loads(body)["warnings"]
    assert status == 200 and len(warnings) == 1 and "三档判定" in warnings[0]


# ---------------------------------------------------------------- KI-51：/api/calibrate 不覆盖别人刚改的目标时长
def test_server_calibrate_does_not_clobber_target(gui_server, monkeypatch):
    import json as _json
    from conftest import call, make_project
    from pipeline import schema
    pdir = make_project(gui_server.root)
    real = schema.update_project

    def rival_first(path, mutate):
        return real(path, lambda c: mutate({**c, "target_duration": 333}))

    monkeypatch.setattr(schema, "update_project", rival_first)
    status, _, _ = call(gui_server, "POST", "/api/calibrate",
                        {"project": "p1", "calibration": {"tone": "emotion"}})
    assert status == 200
    cfg = _json.loads((pdir / "project.json").read_text())
    assert cfg["target_duration"] == 333 and cfg["calibration"]["tone"] == "emotion"
