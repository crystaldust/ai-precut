# -*- coding: utf-8 -*-
"""M13c 审查：标记接口的写入 / 响应拼装分离（HIGH-2）、撤销 X 时还原被移除的镜头（MEDIUM-3）。"""
import json

import pytest
from conftest import call, make_project

from gui import project_routes
from pipeline import review

pytestmark = pytest.mark.usefixtures("consented")

SCORED = {"topics": [], "segments": [
    {"id": "S1", "start": 0, "end": 6, "level": 3, "text": "甲", "topic": "t"},
    {"id": "S2", "start": 10, "end": 16, "level": 3, "text": "乙", "topic": "t"}]}
SHOTS = [{"id": "a", "in": 0, "out": 5}, {"id": "b", "in": 11, "out": 14}, {"id": "c", "in": 30, "out": 33}]


def _project(gs, shots=None):
    return make_project(gs.root, shots=shots, **{"work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False)})


def _post(gs, path, **body):
    status, raw, _ = call(gs, "POST", path, {"project": "p1", **body})
    return status, json.loads(raw)


def _shots(pdir):
    return json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["shots"]


# ---------------------------------------------------------------- HIGH-2：写成功后拼装失败仍回 200
def test_must_saved_even_if_response_assembly_fails(gui_server, monkeypatch):
    pdir = _project(gui_server)
    monkeypatch.setattr(project_routes.payloads, "clip_list", lambda *a: 1 / 0)
    status, data = _post(gui_server, "/api/browse/must", id="S1", must=True)
    assert status == 200 and data["ok"] is True
    assert data["segment"] is None and data["clip_list"] is None and data["wizard"] is None
    assert data["warning"]
    assert review.load(pdir / "work")["S1"]["must_keep"] is True


def test_level_saved_even_if_wizard_assembly_fails(gui_server, monkeypatch):
    pdir = _project(gui_server)
    monkeypatch.setattr(project_routes.wizard, "collect", lambda *a, **k: 1 / 0)
    status, data = _post(gui_server, "/api/browse/level", id="S1", level=1)
    assert status == 200 and data["ok"] is True and data["warning"] and data["wizard"] is None
    assert review.load(pdir / "work")["S1"]["level"] == 1


def test_unusable_saved_and_shots_report_kept_if_assembly_fails(gui_server, monkeypatch):
    pdir = _project(gui_server, shots=SHOTS)
    monkeypatch.setattr(project_routes.wizard, "collect", lambda *a, **k: 1 / 0)
    status, data = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    assert status == 200 and data["warning"] and [s["id"] for s in data["removed_shots"]] == ["b"]
    assert review.load(pdir / "work")["S2"]["unusable"] is True
    assert [s["id"] for s in _shots(pdir)] == ["a", "c"]


def test_mark_responses_do_not_read_media_or_proxy(gui_server, monkeypatch):
    """每次按键都会拼 wizard：只能读小 JSON，不能碰素材 / 代理片。"""
    from pathlib import Path
    pdir = _project(gui_server)
    (pdir / "work" / "proxy.mp4").write_bytes(b"x" * 10)
    seen = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (seen.append(self.name), real(self))[1])
    assert _post(gui_server, "/api/browse/must", id="S1", must=True)[0] == 200
    assert not [n for n in seen if n.endswith((".mp4", ".wav", ".mov"))]


# ---------------------------------------------------------------- MEDIUM-3：撤销 X 还原镜头
def test_unmark_with_restore_puts_shots_back_in_time_order(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    status, data = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False,
                         restore_shots=x["removed_shots"])
    assert status == 200 and data["restored"] == 1 and data["not_restored"] == 0
    assert [s["id"] for s in _shots(pdir)] == ["a", "b", "c"]
    assert review.load(pdir / "work")["S2"]["unusable"] is False


def test_restore_skips_ids_that_already_exist(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    # 手动又加回了同 id 的镜头：不重复插入
    data = json.loads((pdir / "shots.json").read_text(encoding="utf-8"))
    data["shots"].append(x["removed_shots"][0])
    (pdir / "shots.json").write_text(json.dumps(data), encoding="utf-8")
    status, out = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False, restore_shots=x["removed_shots"])
    assert status == 200 and out["restored"] == 0 and out["not_restored"] == 1
    assert [s["id"] for s in _shots(pdir)].count("b") == 1


def test_restore_ignores_shot_not_in_backup(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    forged = [*x["removed_shots"], {"id": "n1", "in": 20, "out": 22, "sub": "", "note": ""}]
    status, out = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False, restore_shots=forged)
    assert status == 200 and out["restored"] == 1 and out["not_restored"] == 1
    assert [s["id"] for s in _shots(pdir)] == ["a", "b", "c"]


@pytest.mark.parametrize("field,value", [("in", 12), ("out", 15), ("sub", "改过的字幕")])
def test_restore_ignores_shot_whose_values_differ_from_backup(gui_server, field, value):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    tampered = [{**x["removed_shots"][0], field: value}]
    status, out = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False, restore_shots=tampered)
    assert status == 200 and out["restored"] == 0 and out["not_restored"] == 1
    assert [s["id"] for s in _shots(pdir)] == ["a", "c"]


def test_restore_without_backup_restores_nothing(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    status, out = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False,
                        restore_shots=[{"id": "n1", "in": 20, "out": 22}])
    assert status == 200 and out["restored"] == 0 and out["not_restored"] == 1
    assert [s["id"] for s in _shots(pdir)] == ["a", "b", "c"]


def test_restore_without_manual_table_creates_nothing(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False,
                         restore_shots=[{"id": "n1", "in": 20, "out": 22}])
    assert status == 200 and data["restored"] == 0 and data["not_restored"] == 1
    assert not (pdir / "shots.json").exists()


def test_restore_refuses_to_exceed_total_shot_cap(gui_server, monkeypatch):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, "/api/browse/unusable", id="S2", unusable=True)
    monkeypatch.setattr(project_routes.schema, "SHOTS_MAX", 2)
    status, out = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False, restore_shots=x["removed_shots"])
    assert status == 200 and out["restored"] == 0 and out["not_restored"] == 1
    assert [s["id"] for s in _shots(pdir)] == ["a", "c"]


@pytest.mark.parametrize("bad", [
    "x", {"id": "a"}, [{"id": "../x", "in": 0, "out": 1}], [{"id": "z1", "in": "a", "out": 1}],
    [{"id": "z1", "in": 5, "out": 1}], [{"id": "z1", "in": -1, "out": 1}],
    [{"id": "z1", "in": 0, "out": float("inf")}], [{"id": "z1", "in": 0, "out": 1}, {"id": "z1", "in": 2, "out": 3}],
    [{"id": "z%d" % i, "in": 0, "out": 1} for i in range(2000)],
])
def test_restore_rejects_invalid_shot_payload_without_changes(gui_server, bad):
    pdir = _project(gui_server, shots=SHOTS)
    review.set_unusable(pdir / "work", "S2", True)
    before = (pdir / "shots.json").read_bytes()
    status, data = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False, restore_shots=bad)
    assert status == 400 and "error" in data
    assert (pdir / "shots.json").read_bytes() == before
    assert review.load(pdir / "work")["S2"]["unusable"] is True  # 校验在写 overrides 之前


def test_restore_shots_ignored_when_marking_unusable(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    status, data = _post(gui_server, "/api/browse/unusable", id="S1", unusable=True,
                         restore_shots=[{"id": "n1", "in": 1, "out": 2}])
    assert status == 200 and "n1" not in [s["id"] for s in _shots(pdir)]


def test_restore_with_corrupt_manual_table_is_409(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    status, _ = _post(gui_server, "/api/browse/unusable", id="S2", unusable=False,
                      restore_shots=[{"id": "n1", "in": 1, "out": 2}])
    assert status == 409


# ---------------------------------------------------------------- MEDIUM-2：字幕 / 备注 / 总数上限（/api/shots 与 clean_shots 共用）
def test_clean_shots_caps_sub_note_and_count():
    from pipeline import schema
    ok = {"id": "a", "in": 0, "out": 1, "sub": "字" * schema.SHOT_SUB_MAX, "note": "n" * schema.SHOT_NOTE_MAX}
    assert schema.clean_shots([ok])
    for field, cap in (("sub", schema.SHOT_SUB_MAX), ("note", schema.SHOT_NOTE_MAX)):
        with pytest.raises(ValueError, match=field):
            schema.clean_shots([{**ok, field: "x" * (cap + 1)}])
    many = [{"id": f"sh{i:04d}", "in": i, "out": i + 1} for i in range(schema.SHOTS_MAX + 1)]
    with pytest.raises(ValueError):
        schema.clean_shots(many)


def test_api_shots_rejects_oversize_subtitle(gui_server):
    from pipeline import schema
    make_project(gui_server.root)
    status, raw, _ = call(gui_server, "POST", "/api/shots?project=p1",
                          {"shots": [{"id": "a", "in": 0, "out": 1, "sub": "x" * (schema.SHOT_SUB_MAX + 1)}]})
    assert status == 400
