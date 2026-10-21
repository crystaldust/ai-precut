# -*- coding: utf-8 -*-
"""KI-103：③ 批量标记——review.set_batch（原子、一把锁、一次写盘）与 POST /api/browse/batch。"""
import json

import pytest
from conftest import call, make_project

from gui import browse_batch
from pipeline import review, shots_store

pytestmark = pytest.mark.usefixtures("consented")

SCORED = {"topics": [], "segments": [
    {"id": "S1", "start": 0, "end": 6, "level": 2, "text": "甲", "topic": "t"},
    {"id": "S2", "start": 10, "end": 16, "level": 2, "text": "乙", "topic": "t"},
    {"id": "S3", "start": 20, "end": 26, "level": 3, "text": "丙", "topic": "t"},
    {"id": "S4", "start": 40, "end": 46, "level": 1, "text": "丁", "topic": "t"}]}
SHOTS = [{"id": "a", "in": 0, "out": 5}, {"id": "b", "in": 11, "out": 14}, {"id": "c", "in": 21, "out": 24},
         {"id": "d", "in": 60, "out": 63}]


def _project(gs, shots=None, scored=SCORED):
    files = {} if scored is None else {"work/segments_scored.json": json.dumps(scored, ensure_ascii=False)}
    return make_project(gs.root, shots=shots, **files)


def _post(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/browse/batch", {"project": "p1", **body})
    return status, json.loads(raw)


def _shot_ids(pdir):
    return [s["id"] for s in json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["shots"]]


@pytest.fixture
def work(tmp_path):
    (tmp_path / "segments_scored.json").write_text(json.dumps(SCORED, ensure_ascii=False), encoding="utf-8")
    return tmp_path


# ================================================================ review.set_batch
def test_set_batch_writes_many_items_with_one_save(work, monkeypatch):
    saves = []
    real = review._save
    monkeypatch.setattr(review, "_save", lambda w, d: (saves.append(1), real(w, d))[1])
    data, cleared = review.set_batch(work, [
        {"id": "S1", "must_keep": True}, {"id": "S2", "level": 3}, {"id": "S3", "unusable": True}])
    assert len(saves) == 1 and cleared == {}
    assert data == review.load(work)
    assert data["S1"]["must_keep"] is True and data["S1"]["must_at"] and data["S1"]["anchor"]["start"] == 0
    assert data["S2"]["level"] == 3 and data["S3"]["unusable"] is True


def test_set_batch_invalid_item_writes_nothing(work, monkeypatch):
    review.set_level(work, "S4", 3)
    before = (work / "overrides.json").read_bytes()
    for bad in ({"id": "S2", "level": 9}, {"id": "S2", "must_keep": "yes"}, {"id": "S2"},
                {"id": ""}, {"id": 5, "must_keep": True}, {"id": "S2", "foo": 1},
                {"id": "S2", "must_keep": True, "unusable": True}, "S2", {"id": "S2", "level": True}):
        with pytest.raises(ValueError):
            review.set_batch(work, [{"id": "S1", "must_keep": True}, bad])
        assert (work / "overrides.json").read_bytes() == before


@pytest.mark.parametrize("changes", [[], None, "S1", {"id": "S1", "must_keep": True},
                                     [{"id": "S1", "must_keep": True}, {"id": "S1", "level": 1}]])
def test_set_batch_rejects_bad_list_or_duplicate_ids(work, changes):
    with pytest.raises(ValueError):
        review.set_batch(work, changes)
    assert not (work / "overrides.json").exists()


def test_set_batch_exclusive_flags_reported_per_id(work):
    review.set_unusable(work, "S1", True)
    review.set_must(work, "S2", True)
    data, cleared = review.set_batch(work, [
        {"id": "S1", "must_keep": True}, {"id": "S2", "unusable": True}, {"id": "S3", "must_keep": True}])
    assert cleared == {"S1": "unusable", "S2": "must_keep"}
    assert data["S1"]["must_keep"] is True and data["S1"]["unusable"] is False
    assert data["S2"]["unusable"] is True and data["S2"]["must_keep"] is False
    assert "must_at" not in data["S2"]


def test_set_batch_explicit_false_on_other_flag_still_reports_cleared(work):
    review.set_unusable(work, "S1", True)
    _, cleared = review.set_batch(work, [{"id": "S1", "must_keep": True, "unusable": False}])
    assert cleared == {"S1": "unusable"}
    assert review.load(work)["S1"]["unusable"] is False


def test_set_batch_must_at_only_on_false_to_true(work):
    review.set_batch(work, [{"id": "S1", "must_keep": True}])
    first = review.load(work)["S1"]["must_at"]
    review.set_batch(work, [{"id": "S1", "must_keep": True}, {"id": "S2", "must_keep": True}])
    data = review.load(work)
    assert data["S1"]["must_at"] == first and data["S2"]["must_at"] >= first
    review.set_batch(work, [{"id": "S1", "must_keep": False}])
    assert "must_at" not in review.load(work)["S1"]


def test_set_batch_level_none_unsets_level_but_keeps_flags(work):
    review.set_level(work, "S1", 1)
    review.set_must(work, "S1", True)
    review.set_level(work, "S2", 3)
    data, _ = review.set_batch(work, [{"id": "S1", "level": None}, {"id": "S2", "level": None}])
    assert "level" not in data["S1"] and data["S1"]["must_keep"] is True
    assert "S2" not in data  # 只剩记账字段 → 整条删


def test_set_batch_level_none_without_override_creates_nothing(work):
    data, cleared = review.set_batch(work, [{"id": "S1", "level": None}])
    assert data == {} and cleared == {}


def test_set_batch_level_none_with_flag_in_same_item(work):
    review.set_level(work, "S1", 1)
    data, _ = review.set_batch(work, [{"id": "S1", "level": None, "must_keep": True}])
    assert "level" not in data["S1"] and data["S1"]["must_keep"] is True


def test_set_batch_does_not_inherit_stale_entry_of_same_id(work):
    (work / "overrides.json").write_text(json.dumps(
        {"S1": {"level": 1, "unusable": True, "anchor": {"text": "不存在的原文", "start": 0}}}), encoding="utf-8")
    data, cleared = review.set_batch(work, [{"id": "S1", "must_keep": True}])
    assert "level" not in data["S1"] and not data["S1"].get("unusable") and cleared == {}


def test_set_batch_without_scored_segments_still_writes_without_anchor(tmp_path):
    data, _ = review.set_batch(tmp_path, [{"id": "S1", "must_keep": True}])
    assert data["S1"]["must_keep"] is True and "anchor" not in data["S1"]


def test_set_batch_corrupt_overrides_raises_and_keeps_file(work):
    (work / "overrides.json").write_text("{坏", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.set_batch(work, [{"id": "S1", "must_keep": True}])
    assert (work / "overrides.json").read_text(encoding="utf-8") == "{坏"


def _strip(d, *, anchors=True):
    drop = {"at", "must_at"} | (set() if anchors else {"anchor"})
    return {k: {f: v for f, v in e.items() if f not in drop} for k, e in d.items()}


ANCHOR_S1 = {"text": review.text_key("甲"), "start": 0.0}
PRE_STATES = {
    "none": {},
    "must_anchored": {"S1": {"must_keep": True, "must_at": "2026-01-01", "anchor": ANCHOR_S1}},
    "must_legacy": {"S1": {"must_keep": True, "must_at": "2026-01-01"}},
    "unusable_anchored": {"S1": {"unusable": True, "anchor": ANCHOR_S1}},
    "unusable_legacy": {"S1": {"unusable": True}},
    "level_anchored": {"S1": {"level": 1, "anchor": ANCHOR_S1}},
    "level_legacy": {"S1": {"level": 1}},
    "stale_must": {"S1": {"must_keep": True, "level": 1, "anchor": {"text": "不存在", "start": 0}}},
    "stale_level_only": {"S1": {"level": 1, "anchor": {"text": "不存在", "start": 0}}},
}
OPS = {  # 名称 → (批量里的 change, 单段写法)
    "must_true": ({"must_keep": True}, lambda w: review.set_must_reporting(w, "S1", True)),
    "must_false": ({"must_keep": False}, lambda w: review.set_must_reporting(w, "S1", False)),
    "unusable_true": ({"unusable": True}, lambda w: review.set_unusable(w, "S1", True)),
    "unusable_false": ({"unusable": False}, lambda w: review.set_unusable(w, "S1", False)),
    "level_1": ({"level": 1}, lambda w: (review.set_level(w, "S1", 1), None)),
    "level_2": ({"level": 2}, lambda w: (review.set_level(w, "S1", 2), None)),
    "level_3": ({"level": 3}, lambda w: (review.set_level(w, "S1", 3), None)),
    "level_none": ({"level": None}, lambda w: (review.unset_level(w, "S1"), None)),
}


@pytest.mark.parametrize("pre", PRE_STATES)
@pytest.mark.parametrize("op", OPS)
def test_set_batch_single_item_matches_single_writers(pre, op, tmp_path_factory):
    change, single = OPS[op]
    dirs = []
    for name in ("batch", "single"):
        d = tmp_path_factory.mktemp(name)
        (d / "segments_scored.json").write_text(json.dumps(SCORED, ensure_ascii=False), encoding="utf-8")
        if PRE_STATES[pre]:
            (d / "overrides.json").write_text(json.dumps(PRE_STATES[pre]), encoding="utf-8")
        dirs.append(d)
    data, cleared = review.set_batch(dirs[0], [{"id": "S1", **change}])
    _, hit = single(dirs[1])
    # unset_level 不 rekey，旧裁决没有锚点时不会补锚点；其余写法都会补
    anchors = op != "level_none"
    assert _strip(review.load(dirs[0]), anchors=anchors) == _strip(review.load(dirs[1]), anchors=anchors)
    assert cleared == ({"S1": hit} if hit else {})


def test_set_batch_level_none_alone_keeps_stale_entry_fields(work):
    (work / "overrides.json").write_text(json.dumps(
        {"S1": {"level": 1, "must_keep": True, "anchor": {"text": "不存在", "start": 0}}}), encoding="utf-8")
    data, _ = review.set_batch(work, [{"id": "S1", "level": None}])
    assert data["S1"]["must_keep"] is True and "level" not in data["S1"]


# ================================================================ POST /api/browse/batch
def test_batch_success_contract(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, items=[{"id": "S1", "must_keep": True}, {"id": "S2", "level": 3}])
    assert status == 200 and data["ok"] is True and "warning" not in data
    assert [s["id"] for s in data["segments"]] == ["S1", "S2"]
    s1, s2 = data["segments"]
    assert s1["must_keep"] is True and s2["level"] == 3 and s2["override"] is True
    assert data["cleared"] == {} and data["removed_shots"] == []
    assert data["restored"] == 0 and data["not_restored"] == 0
    assert data["clip_list"] and data["wizard"]
    assert review.load(pdir / "work")["S1"]["must_keep"] is True


def test_batch_reports_cleared_marks(gui_server):
    pdir = _project(gui_server)
    review.set_unusable(pdir / "work", "S1", True)
    status, data = _post(gui_server, items=[{"id": "S1", "must_keep": True, "unusable": False}])
    assert status == 200 and data["cleared"] == {"S1": "unusable"}
    assert data["segments"][0]["unusable"] is False


def test_batch_level_null_unsets_override(gui_server):
    pdir = _project(gui_server)
    review.set_level(pdir / "work", "S1", 1)
    status, data = _post(gui_server, items=[{"id": "S1", "level": None}])
    assert status == 200 and data["segments"][0]["override"] is False and data["segments"][0]["level"] == 2


def test_batch_unusable_removes_overlapping_shots_with_single_backup(gui_server, monkeypatch):
    pdir = _project(gui_server, shots=SHOTS)
    backups = []
    real = browse_batch.project_routes._remove_manual_shots
    monkeypatch.setattr(browse_batch.project_routes, "_remove_manual_shots",
                        lambda *a: (backups.append(1), real(*a))[1])
    status, data = _post(gui_server, items=[{"id": "S2", "unusable": True}, {"id": "S3", "unusable": True}])
    assert status == 200 and len(backups) == 1
    assert sorted(s["id"] for s in data["removed_shots"]) == ["b", "c"]
    assert _shot_ids(pdir) == ["a", "d"]
    assert (pdir / "work" / "shots.before-unusable.json").exists()


def test_batch_unusable_without_manual_table_creates_none(gui_server):
    pdir = _project(gui_server)
    status, data = _post(gui_server, items=[{"id": "S2", "unusable": True}])
    assert status == 200 and data["removed_shots"] == [] and not (pdir / "shots.json").exists()


def test_batch_restore_shots_puts_back_in_time_order(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, items=[{"id": "S2", "unusable": True}, {"id": "S3", "unusable": True}])
    status, out = _post(gui_server, items=[{"id": "S2", "unusable": False}, {"id": "S3", "unusable": False}],
                        restore_shots=x["removed_shots"])
    assert status == 200 and out["restored"] == 2 and out["not_restored"] == 0
    assert _shot_ids(pdir) == ["a", "b", "c", "d"]


def test_batch_restore_ignores_shot_not_in_backup(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, items=[{"id": "S2", "unusable": True}])
    forged = [*x["removed_shots"], {"id": "n1", "in": 30, "out": 32}]
    status, out = _post(gui_server, items=[{"id": "S2", "unusable": False}], restore_shots=forged)
    assert status == 200 and out["restored"] == 1 and out["not_restored"] == 1
    assert _shot_ids(pdir) == ["a", "b", "c", "d"]


@pytest.mark.parametrize("body", [
    {"items": "x"}, {"items": {"id": "S1", "must_keep": True}}, {"items": []}, {},
    {"items": [{"id": "S1", "must_keep": True}, {"id": "S1", "level": 1}]},
    {"items": [{"id": "NOPE", "must_keep": True}]},
    {"items": [{"id": "S1", "must_keep": True}, {"id": "NOPE", "level": 1}]},
    {"items": [{"id": "", "must_keep": True}]}, {"items": [{"id": 3, "must_keep": True}]},
    {"items": [{"must_keep": True}]}, {"items": ["S1"]}, {"items": [None]},
    {"items": [{"id": "S1", "must_keep": 1}]}, {"items": [{"id": "S1", "must_keep": "true"}]},
    {"items": [{"id": "S1", "unusable": None}]},
    {"items": [{"id": "S1", "level": 4}]}, {"items": [{"id": "S1", "level": "3"}]},
    {"items": [{"id": "S1", "level": True}]}, {"items": [{"id": "S1", "level": 2.5}]},
    {"items": [{"id": "S1", "level": []}]}, {"items": [{"id": "S1", "level": {}}]},
    {"items": [{"id": "S1", "level": 1.0}]}, {"items": [{"id": "S1", "level": {"a": 1}}]},
    {"items": [{"id": "S1", "must_keep": True, "unusable": True}]},
    {"items": [{"id": "S1"}]}, {"items": [{"id": "S1", "bogus": 1}]},
    {"items": [{"id": "S1", "must_keep": True}], "restore_shots": "x"},
    {"items": [{"id": "S1", "must_keep": True}], "restore_shots": [{"id": "../x", "in": 0, "out": 1}]},
    {"items": [{"id": "S1", "must_keep": True}], "restore_shots": {"id": "a"}},
])
def test_batch_rejects_invalid_params_without_any_change(gui_server, body):
    pdir = _project(gui_server, shots=SHOTS)
    before = (pdir / "shots.json").read_bytes()
    status, data = _post(gui_server, **body)
    assert status == 400 and data["error"]
    assert not (pdir / "work" / "overrides.json").exists()
    assert (pdir / "shots.json").read_bytes() == before


def test_batch_rejects_more_than_items_max(gui_server, monkeypatch):
    pdir = _project(gui_server)
    assert browse_batch.BATCH_ITEMS_MAX == 2000
    monkeypatch.setattr(browse_batch, "BATCH_ITEMS_MAX", 2)
    status, data = _post(gui_server, items=[{"id": f"S{i}", "must_keep": True} for i in (1, 2, 3)])
    assert status == 400 and "2" in data["error"]
    assert not (pdir / "work" / "overrides.json").exists()
    assert _post(gui_server, items=[{"id": "S1", "must_keep": True}, {"id": "S2", "must_keep": True}])[0] == 200


def test_batch_unknown_segment_message_names_id(gui_server):
    _project(gui_server)
    _, data = _post(gui_server, items=[{"id": "NOPE", "must_keep": True}])
    assert "NOPE" in data["error"]


def test_batch_corrupt_overrides_is_409_and_not_overwritten(gui_server):
    pdir = _project(gui_server)
    (pdir / "work" / "overrides.json").write_text("{坏", encoding="utf-8")
    status, _ = _post(gui_server, items=[{"id": "S1", "must_keep": True}])
    assert status == 409
    assert (pdir / "work" / "overrides.json").read_text(encoding="utf-8") == "{坏"


def test_batch_corrupt_manual_table_is_409_and_overrides_untouched(gui_server):
    pdir = _project(gui_server, shots=SHOTS)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    status, _ = _post(gui_server, items=[{"id": "S2", "unusable": True}])
    assert status == 409 and not (pdir / "work" / "overrides.json").exists()


def test_batch_without_analysis_result_is_400(gui_server):
    pdir = _project(gui_server, scored=None)
    status, data = _post(gui_server, items=[{"id": "S1", "must_keep": True}])
    assert status == 400 and data["error"]
    assert not (pdir / "work" / "overrides.json").exists()


def test_batch_unknown_project_is_404_and_bad_name_is_400(gui_server):
    assert _post(gui_server, project="nope", items=[{"id": "S1", "must_keep": True}])[0] == 404
    assert _post(gui_server, project="../x", items=[{"id": "S1", "must_keep": True}])[0] == 400


def test_batch_saved_even_if_response_assembly_fails(gui_server, monkeypatch):
    pdir = _project(gui_server)
    monkeypatch.setattr(browse_batch.project_routes.wizard, "collect", lambda *a, **k: 1 / 0)
    status, data = _post(gui_server, items=[{"id": "S1", "must_keep": True}])
    assert status == 200 and data["ok"] is True
    assert data["warning"] == browse_batch.project_routes.SAVED_BUT_STALE_MSG
    assert data["segments"] is None and data["clip_list"] is None and data["wizard"] is None
    assert data["cleared"] == {} and data["removed_shots"] == []
    assert review.load(pdir / "work")["S1"]["must_keep"] is True


def test_batch_large_request_within_limit(gui_server):
    big = {"topics": [], "segments": [{"id": f"X{i}", "start": i, "end": i + 1, "level": 2, "text": f"句{i}",
                                       "topic": "t"} for i in range(2000)]}
    pdir = _project(gui_server, scored=big)
    status, data = _post(gui_server, items=[{"id": f"X{i}", "must_keep": True} for i in range(2000)])
    assert status == 200 and len(data["segments"]) == 2000
    assert len(review.load(pdir / "work")) == 2000


# ---------------------------------------------------------------- 写 overrides 之后的失败不能回 4xx
def _boom(exc):
    def raiser(*a, **k):
        raise exc
    return raiser


@pytest.mark.parametrize("exc", [shots_store.Busy(shots_store.BUSY_MSG), OSError("磁盘坏了"),
                                 ValueError("坏值"), TypeError("坏类型")])
def test_batch_remove_shots_failure_after_write_is_200_with_warning(gui_server, monkeypatch, exc):
    pdir = _project(gui_server, shots=SHOTS)
    monkeypatch.setattr(browse_batch.project_routes, "_remove_manual_shots", _boom(exc))
    status, data = _post(gui_server, items=[{"id": "S2", "unusable": True}])
    assert status == 200 and data["ok"] is True and data["warning"]
    assert data["removed_shots"] == [] and data["restored"] == 0 and data["not_restored"] == 0
    assert data["segments"][0]["unusable"] is True and data["clip_list"] and data["wizard"]
    assert review.load(pdir / "work")["S2"]["unusable"] is True
    assert _shot_ids(pdir) == ["a", "b", "c", "d"]


def test_batch_busy_warning_reuses_busy_wording(gui_server, monkeypatch):
    _project(gui_server, shots=SHOTS)
    monkeypatch.setattr(browse_batch.project_routes, "_remove_manual_shots", _boom(shots_store.Busy("x")))
    _, data = _post(gui_server, items=[{"id": "S2", "unusable": True}])
    assert data["warning"] == browse_batch.project_routes.UNUSABLE_SHOTS_BUSY_MSG


@pytest.mark.parametrize("exc", [shots_store.Busy("x"), OSError("磁盘坏了")])
def test_batch_restore_shots_failure_after_write_is_200_with_warning(gui_server, monkeypatch, exc):
    pdir = _project(gui_server, shots=SHOTS)
    _, x = _post(gui_server, items=[{"id": "S2", "unusable": True}])
    monkeypatch.setattr(browse_batch.project_routes, "_restore_manual_shots", _boom(exc))
    status, data = _post(gui_server, items=[{"id": "S2", "unusable": False}], restore_shots=x["removed_shots"])
    assert status == 200 and data["warning"] and data["restored"] == 0 and data["segments"]
    assert review.load(pdir / "work")["S2"]["unusable"] is False


def test_batch_keeps_removed_shots_when_only_restore_fails(gui_server, monkeypatch):
    pdir = _project(gui_server, shots=SHOTS)
    monkeypatch.setattr(browse_batch.project_routes, "_restore_manual_shots", _boom(OSError("x")))
    status, data = _post(gui_server, items=[{"id": "S2", "unusable": True}, {"id": "S1", "unusable": False}],
                         restore_shots=[{"id": "n1", "in": 1, "out": 2}])
    assert status == 200 and [s["id"] for s in data["removed_shots"]] == ["b"] and data["warning"]
    assert _shot_ids(pdir) == ["a", "c", "d"]
