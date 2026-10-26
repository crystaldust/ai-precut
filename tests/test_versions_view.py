"""M14 T6：版本卡片数据（真实导出物、是否当前分镜表、含不可用片段的拦截）与 Windows 包的拦截（KI-100 / KI-102）。"""
import json

import pytest

from conftest import call, make_project
from gui import jobs, settings, views
from pipeline import exclusions, fingerprints, outputs, review, schema

pytestmark = pytest.mark.usefixtures("consented")

SHOTS = [{"id": "a", "in": 10, "out": 20, "sub": "甲"}, {"id": "b", "in": 40, "out": 50, "sub": "乙"}]
TIMELINE = {"video": [{"timeline_in": 0, "in": 0, "out": 10}, {"timeline_in": 10, "in": 0, "out": 10}]}


def _cfg(pdir):
    return json.loads((pdir / "project.json").read_text(encoding="utf-8"))


def _version(pdir, name="v1", *, exports="absent", stamp=None, snapshot=SHOTS):
    """造一个版本目录。exports：'absent' = 改版前的版本（没有 export.json）；None / dict 直接写入。"""
    vdir = pdir / "output" / name
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text(json.dumps(TIMELINE), encoding="utf-8")
    if exports != "absent":
        (vdir / "export.json").write_text(json.dumps(exports or {"mac": None, "windows": None}), encoding="utf-8")
    if stamp is not None:
        (vdir / "preview.json").write_text(json.dumps({"inputs": stamp, "shots": 2, "duration": 20, "at": "t"}),
                                           encoding="utf-8")
    if snapshot is not None:
        (vdir / "shots_snapshot.json").write_text(json.dumps({"shots": snapshot}), encoding="utf-8")
    return vdir


def _mark_unusable(pdir, sid="S1", start=12.0, end=18.0):
    scored = {"segments": [{"id": sid, "start": start, "end": end, "level": 3, "text": "t", "topic": "x"}],
              "topics": []}
    (pdir / "work" / "segments_scored.json").write_text(json.dumps(scored), encoding="utf-8")
    review.set_unusable(pdir / "work", sid, True)


def _card(pdir, name="v1"):
    return next(v for v in views._versions(pdir, _cfg(pdir), "p1") if v["name"] == name)


# ---------------------------------------------------------------- KI-102：只显示真实导出物
def test_draft_shown_when_mac_export_recorded(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir, exports={"mac": {"draft": "p1_v1", "at": "t"}, "windows": None})
    card = _card(pdir)
    assert card["draft"] == "p1_v1" and card["exports"]["mac"]["draft"] == "p1_v1"
    assert card["legacy"] is False


def test_no_draft_version_has_no_draft_name(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir, exports={"mac": None, "windows": None})
    card = _card(pdir)
    assert card["draft"] is None and card["exports"] == {"mac": None, "windows": None}
    assert card["legacy"] is False


def test_legacy_version_keeps_draft_name_and_is_flagged(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir)  # 没有 export.json
    card = _card(pdir)
    assert card["legacy"] is True and card["exports"] is None and card["draft"] == "p1_v1"


def test_corrupt_export_json_is_treated_as_legacy_without_failing(tmp_path):
    pdir = make_project(tmp_path)
    vdir = _version(pdir)
    (vdir / "export.json").write_text("{坏", encoding="utf-8")
    assert _card(pdir)["legacy"] is True


# ---------------------------------------------------------------- 是否当前分镜表 / 快照
def test_current_flag_compares_stamp_with_current_inputs(tmp_path):
    pdir = make_project(tmp_path, shots=SHOTS)
    now = fingerprints.preview_inputs(pdir, _cfg(pdir))
    _version(pdir, "v1", exports=None, stamp=now)
    _version(pdir, "v2", exports=None, stamp={**now, "table": "other"})
    _version(pdir, "v3", exports=None)
    cards = {v["name"]: v for v in views._versions(pdir, _cfg(pdir), "p1")}
    assert [cards[k]["current"] for k in ("v1", "v2", "v3")] == [True, False, False]


def test_has_snapshot(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir, "v1", exports=None)
    _version(pdir, "v2", exports=None, snapshot=None)
    cards = {v["name"]: v for v in views._versions(pdir, _cfg(pdir), "p1")}
    assert cards["v1"]["has_snapshot"] is True and cards["v2"]["has_snapshot"] is False


# ---------------------------------------------------------------- KI-100：含不可用片段
def test_no_unusable_marks_means_zero_hits_and_not_blocked(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir, snapshot=None)
    card = _card(pdir)
    assert card["unusable_hits"] == 0 and card["blocked"] is None


def test_version_with_unusable_hit_is_blocked(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir)
    _mark_unusable(pdir)  # 12–18 秒落在快照第一镜（10–20）里
    card = _card(pdir)
    assert card["unusable_hits"] == 1 and card["blocked"] == exclusions.EXPORT_BLOCKED.format(n=1)


def test_unusable_marks_but_no_snapshot_is_blocked_with_reason(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir, snapshot=None)
    _mark_unusable(pdir)
    card = _card(pdir)
    assert card["unusable_hits"] is None and card["blocked"] == exclusions.EXPORT_NO_SNAPSHOT


def test_corrupt_overrides_do_not_break_the_version_list(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir)
    (pdir / "work" / "overrides.json").write_text("{坏", encoding="utf-8")
    (pdir / "work" / "segments_scored.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    card = _card(pdir)
    assert card["unusable_hits"] is None and card["blocked"]


def test_timeline_hits_is_not_read_when_nothing_is_marked(tmp_path, monkeypatch):
    """/api/state 每次轮询都会算：没有任何不可用标记时不读快照。"""
    pdir = make_project(tmp_path)
    vdir = _version(pdir)
    reads = []
    real = schema.read_shots
    monkeypatch.setattr(schema, "read_shots", lambda p: reads.append(p) or real(p))
    assert _card(pdir)["unusable_hits"] == 0
    assert [p for p in reads if p.parent == vdir] == []


# ---------------------------------------------------------------- 接口
def test_state_versions_carry_new_fields_and_old_ones(gui_server):
    pdir = make_project(gui_server.root)
    _version(pdir, exports={"mac": {"draft": "p1_v1", "at": "t"}, "windows": None})
    _, raw, _ = call(gui_server, "GET", "/api/state?project=p1")
    v = json.loads(raw)["versions"][0]
    assert {"name", "preview", "shots", "duration", "draft", "mtime", "windows_zip", "windows_mb",
            "exports", "legacy", "current", "has_snapshot", "unusable_hits", "blocked"} <= set(v)
    assert v["shots"] == 2 and v["duration"] == 20.0


def test_state_has_manual_and_preview_status(gui_server):
    make_project(gui_server.root, shots=SHOTS,
                 **{"work/shots-selected.json": json.dumps({"shots": SHOTS[:1]})})  # 手动表比 AI 选段多一镜
    _, raw, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(raw)
    assert data["manual"]["edited"] is True and data["manual"]["count"] == 1
    assert data["preview"] == {"status": "none", "at": None} and data["next_version"] == "v1"


def _open_export(gs, version="v1"):
    return call(gs, "POST", "/api/open", {"project": "p1", "target": "export", "version": version})


def test_open_export_blocked_for_version_with_unusable(gui_server, monkeypatch):
    pdir = make_project(gui_server.root)
    vdir = _version(pdir)
    _mark_unusable(pdir)
    zip_path = jobs.windows_zip(pdir, "v1", "p1")
    zip_path.write_bytes(b"zip")  # 旧的 Windows 包还在，也不能定位
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: ran.append(argv))
    status, raw, _ = _open_export(gui_server)
    assert status == 409 and json.loads(raw)["error"] == exclusions.EXPORT_BLOCKED.format(n=1)
    assert ran == [] and vdir.exists()


def test_open_export_blocked_when_cannot_confirm(gui_server, monkeypatch):
    pdir = make_project(gui_server.root)
    _version(pdir, snapshot=None)
    _mark_unusable(pdir)
    jobs.windows_zip(pdir, "v1", "p1").write_bytes(b"zip")
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: ran.append(argv))
    status, raw, _ = _open_export(gui_server)
    assert status == 409 and json.loads(raw)["error"] == exclusions.EXPORT_NO_SNAPSHOT and ran == []


def test_open_export_still_works_for_clean_version(gui_server, mac_platform, monkeypatch):
    pdir = make_project(gui_server.root)
    _version(pdir)
    zip_path = jobs.windows_zip(pdir, "v1", "p1")
    zip_path.write_bytes(b"zip")
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: ran.append(argv))
    status, _, _ = _open_export(gui_server)
    assert status == 200 and ran == [["open", "-R", str(zip_path)]]


def test_export_job_for_version_with_unusable_is_409_and_starts_nothing(gui_server, monkeypatch):
    pdir = make_project(gui_server.root)
    _version(pdir)
    _mark_unusable(pdir)
    started = []
    monkeypatch.setattr(jobs, "job_command", lambda *a: started.append(a) or ["true"])
    status, raw, _ = call(gui_server, "POST", "/api/job", {"project": "p1", "task": "export", "version": "v1"})
    data = json.loads(raw)
    assert status == 409 and data["error"] == exclusions.EXPORT_BLOCKED.format(n=1)
    assert data["need"] == "export_blocked" and started == [] and jobs.JOBS == {}


def test_check_ready_export_passes_clean_version(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir)
    settings.check_ready(pdir, "export", {"version": "v1"})  # 不抛


def test_outputs_export_block_contract(tmp_path):
    pdir = make_project(tmp_path)
    _version(pdir)
    assert outputs.export_block(pdir, "v1") == (0, None)
    _mark_unusable(pdir)
    assert outputs.export_block(pdir, "v1") == (1, exclusions.EXPORT_BLOCKED.format(n=1))
    assert outputs.version_facts(pdir / "output" / "v1") == (2, 20.0)


def test_marked_spans_are_read_once_for_all_versions(tmp_path, monkeypatch):
    """/api/state 每次轮询都会算版本卡片：不能每个版本都重读一遍分析结果和裁决。"""
    pdir = make_project(tmp_path)
    for v in ("v1", "v2", "v3"):
        _version(pdir, v)
    _mark_unusable(pdir)
    reads = []
    real = exclusions.spans
    monkeypatch.setattr(exclusions, "spans", lambda w: reads.append(w) or real(w))
    cards = views._versions(pdir, _cfg(pdir), "p1")
    assert len(reads) == 1 and [c["unusable_hits"] for c in cards] == [1, 1, 1]


def test_state_request_fingerprints_the_preview_inputs_once(tmp_path, monkeypatch):
    pdir = make_project(tmp_path, shots=SHOTS)
    _version(pdir, "v1", exports=None)
    _version(pdir, "v2", exports=None)
    calls = []
    real = fingerprints.preview_inputs
    monkeypatch.setattr(fingerprints, "preview_inputs", lambda *a, **k: calls.append(1) or real(*a, **k))
    state = views.project_state(pdir, "p1")
    assert len(calls) == 1 and state["preview"] == {"status": "none", "at": None} and len(state["versions"]) == 2


def test_project_list_does_not_fingerprint_previews(tmp_path, monkeypatch):
    pdir = make_project(tmp_path, shots=SHOTS)
    _version(pdir, "v1", exports=None)
    calls = []
    monkeypatch.setattr(fingerprints, "preview_inputs", lambda *a, **k: calls.append(1))
    assert views.projects_list(tmp_path)[0]["name"] == "p1" and calls == []
