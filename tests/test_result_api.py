"""⑤ 看结果相关接口（M14）：/api/shots 的基线与 409。"""
import json
import sys

import pytest

from conftest import call, make_project

pytestmark = pytest.mark.usefixtures("consented")

QUICK_OK = [sys.executable, "-c", "print('[✓] ok', flush=True)"]
AI = [{"id": "sel01", "in": 0, "out": 10, "sub": "甲"}, {"id": "sel02", "in": 20, "out": 30, "sub": "乙"}]


def _shots_post(gs, shots, name="p1"):
    return call(gs, "POST", f"/api/shots?project={name}", body={"shots": shots})


# ---------------------------------------------------------------- /api/shots
def test_first_shots_save_writes_baseline_from_ai_selection(gui_server):
    pdir = make_project(gui_server.root, **{"work/shots-selected.json": json.dumps({"shots": AI})})
    status, _, _ = _shots_post(gui_server, [{"id": "a", "in": 1, "out": 2, "sub": "x"}])
    assert status == 200
    base = json.loads((pdir / "work" / "manual_base.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in base["shots"]] == ["sel01", "sel02"]
    # 第二次保存不改基线
    _shots_post(gui_server, [])
    assert json.loads((pdir / "work" / "manual_base.json").read_text(encoding="utf-8")) == base


def test_shots_save_rejected_with_409_while_select_job_runs(gui_server, monkeypatch):
    pdir = make_project(gui_server.root, shots=AI)
    before = (pdir / "shots.json").read_bytes()
    monkeypatch.setattr(gui_server.module.jobs, "project_job", lambda name: {"id": "j", "task": "select"})
    status, body, _ = _shots_post(gui_server, [])
    assert status == 409
    assert json.loads(body)["error"] == "正在重新选段，完成后再改分镜表"
    assert (pdir / "shots.json").read_bytes() == before


def test_shots_save_allowed_while_other_task_runs(gui_server, monkeypatch):
    make_project(gui_server.root, shots=AI)
    monkeypatch.setattr(gui_server.module.jobs, "project_job", lambda name: {"id": "j", "task": "preview"})
    status, _, _ = _shots_post(gui_server, [])
    assert status == 200


def test_shots_save_waits_for_cross_process_lock(gui_server):
    """另一个进程（aicut select --manual=replace）持有文件锁时，保存要等，而不是写进去被吞掉。"""
    import fcntl
    import os
    import threading
    from pipeline import shots_store
    pdir = make_project(gui_server.root, shots=AI)
    fd = os.open(pdir / shots_store.FILE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    result = []
    t = threading.Thread(target=lambda: result.append(_shots_post(gui_server, [])[0]))
    t.start()
    t.join(0.4)
    assert result == [] and t.is_alive()
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    t.join(5)
    assert result == [200]


# ---------------------------------------------------------------- /api/job：preview / build target / 剪映开着
def _job(gs, **body):
    from test_server_jobs import post_job
    return post_job(gs, **body)


def _fresh_preview(pdir):
    """造一份与当前分镜表一致的暂存预览片（等同 aicut preview 的产物）。"""
    from pipeline import fingerprints, media_io, outputs, schema
    cfg = schema.read_json(pdir / "project.json")
    staging = outputs.staging_dir(pdir)
    staging.mkdir(parents=True)
    for name in ("timeline.json", "shots_snapshot.json", ".timeline.sha"):
        (staging / name).write_text("{}", encoding="utf-8")
    with media_io.atomic_output(staging / "preview.mp4") as tmp:
        tmp.write_bytes(b"x")
    outputs.write_stamp(staging, fingerprints.preview_inputs(pdir, cfg), 2, 20.0)


def test_preview_task_starts_preview_command(gui_server, monkeypatch):
    from gui import jobs
    from test_server_jobs import fake_command, wait_for
    make_project(gui_server.root, shots=AI)
    seen = fake_command(monkeypatch, jobs, QUICK_OK)
    status, data = _job(gui_server, task="preview")
    assert status == 200 and seen == [("preview", "p1", [])]
    assert wait_for(lambda: jobs.active_job() is None)


def test_build_mac_with_jianying_running_is_409_close_jianying(gui_server, monkeypatch):
    from gui import jobs, settings
    from test_server_jobs import fake_command
    pdir = make_project(gui_server.root, shots=AI)
    _fresh_preview(pdir)
    seen = fake_command(monkeypatch, jobs, QUICK_OK)
    monkeypatch.setattr(settings.to_jianying, "jianying_running", lambda: True)
    status, data = _job(gui_server, task="build", target="mac")
    assert status == 409 and data["need"] == "close_jianying" and seen == []


def test_build_target_with_stale_preview_is_400_and_starts_nothing(gui_server, monkeypatch):
    from gui import jobs, settings
    from test_server_jobs import fake_command
    pdir = make_project(gui_server.root, shots=AI)
    _fresh_preview(pdir)
    (pdir / "shots.json").write_text(json.dumps({"shots": AI[:1]}), encoding="utf-8")  # 预览之后改了表
    seen = fake_command(monkeypatch, jobs, QUICK_OK)
    monkeypatch.setattr(settings.to_jianying, "jianying_running", lambda: False)
    status, data = _job(gui_server, task="build", target="windows")
    assert status == 400 and "重新生成预览片" in data["error"] and seen == []


def test_build_windows_with_fresh_preview_passes_flags(gui_server, monkeypatch):
    from gui import jobs
    from test_server_jobs import fake_command, wait_for
    pdir = make_project(gui_server.root, shots=AI)
    _fresh_preview(pdir)
    seen = fake_command(monkeypatch, jobs, QUICK_OK)
    status, _ = _job(gui_server, task="build", target="windows")
    assert status == 200 and seen == [("build", "p1", ["--require-preview", "--windows", "--no-draft"])]
    assert wait_for(lambda: jobs.active_job() is None)


def test_build_with_corrupt_project_json_is_409(gui_server, monkeypatch):
    from gui import jobs
    from test_server_jobs import fake_command
    pdir = make_project(gui_server.root, shots=AI)
    seen = fake_command(monkeypatch, jobs, QUICK_OK)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    status, _ = _job(gui_server, task="build", target="mac")
    assert status == 409 and seen == []


def test_select_job_rejects_bad_manual_with_400(gui_server, monkeypatch):
    from gui import jobs
    from test_server_jobs import fake_command
    make_project(gui_server.root, shots=AI)
    seen = fake_command(monkeypatch, jobs, QUICK_OK)
    status, data = _job(gui_server, task="select", manual="nuke")
    assert status == 400 and "manual" in data["error"] and seen == []


# ---------------------------------------------------------------- MEDIUM-5：选段指纹 / MEDIUM-6：忙
def _sel_digest(pdir):
    from pipeline import fingerprints
    return fingerprints.file_digest(pdir / "work" / "shots-selected.json")


def test_state_returns_selection_digest(gui_server):
    pdir = make_project(gui_server.root, **{"work/shots-selected.json": json.dumps({"shots": AI})})
    status, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    assert status == 200 and json.loads(body)["selection_digest"] == _sel_digest(pdir) != ""


def test_save_after_replace_with_stale_selection_digest_is_409_and_writes_nothing(gui_server):
    pdir = make_project(gui_server.root, **{"work/shots-selected.json": json.dumps({"shots": AI})})
    loaded = _sel_digest(pdir)                                       # 页面读到的 AI 选段
    (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": AI[:1]}), encoding="utf-8")  # 覆盖后选段变了
    status, body, _ = call(gui_server, "POST", "/api/shots?project=p1",
                           body={"shots": [{"id": "a", "in": 1, "out": 2}], "selection_digest": loaded})
    data = json.loads(body)
    assert status == 409 and data["error"] == "分镜表刚被重新选段覆盖了，请刷新" and data["stale"] is True
    assert not (pdir / "shots.json").exists()


def test_save_with_matching_digest_or_existing_manual_table_or_no_digest_is_ok(gui_server):
    pdir = make_project(gui_server.root, **{"work/shots-selected.json": json.dumps({"shots": AI})})
    shots = [{"id": "a", "in": 1, "out": 2}]
    assert _shots_post_digest(gui_server, shots, _sel_digest(pdir))[0] == 200
    (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": AI[:1]}), encoding="utf-8")
    assert _shots_post_digest(gui_server, shots, "old-digest")[0] == 200      # 已有手动表：以手动表为准
    (pdir / "shots.json").unlink()
    assert call(gui_server, "POST", "/api/shots?project=p1", body={"shots": shots})[0] == 200  # 旧客户端不带指纹


def _shots_post_digest(gs, shots, digest):
    return call(gs, "POST", "/api/shots?project=p1", body={"shots": shots, "selection_digest": digest})


def test_save_returns_409_busy_when_another_process_holds_the_lock(gui_server, monkeypatch):
    from pipeline import shots_store
    from test_shots_store import _hold_flock_in_subprocess, _release
    pdir = make_project(gui_server.root, shots=AI)
    before = (pdir / "shots.json").read_bytes()
    monkeypatch.setattr(shots_store, "BUSY_TIMEOUT_S", 0.3)
    holder = _hold_flock_in_subprocess(pdir)
    try:
        status, body, _ = _shots_post(gui_server, [])
    finally:
        _release(holder)
    assert status == 409 and json.loads(body)["error"] == "分镜表正忙，请稍后再试"
    assert (pdir / "shots.json").read_bytes() == before


def test_save_waits_for_a_short_cross_process_hold(gui_server):
    import threading
    from test_shots_store import _hold_flock_in_subprocess, _release
    pdir = make_project(gui_server.root, shots=AI)
    holder = _hold_flock_in_subprocess(pdir)
    out = []
    t = threading.Thread(target=lambda: out.append(_shots_post(gui_server, [])[0]))
    t.start()
    t.join(0.5)
    assert out == []
    _release(holder)
    t.join(5)
    assert out == [200]


def test_unusable_mark_returns_409_when_shots_lock_busy(gui_server, monkeypatch):
    from pipeline import shots_store
    from test_shots_store import _hold_flock_in_subprocess, _release
    pdir = make_project(gui_server.root, shots=AI, **{
        "work/segments_scored.json": json.dumps({"segments": [{"id": "S1", "start": 0, "end": 5, "level": 3}]})})
    monkeypatch.setattr(shots_store, "BUSY_TIMEOUT_S", 0.3)
    holder = _hold_flock_in_subprocess(pdir)
    try:
        status, _, _ = call(gui_server, "POST", "/api/browse/unusable", body={"project": "p1", "id": "S1", "unusable": True})
    finally:
        _release(holder)
    assert status == 409
