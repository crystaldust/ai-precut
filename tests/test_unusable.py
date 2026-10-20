"""M13 · KI-93：「不可用」标记端到端（存储 → 选段排除 → 出片剔除 → 旧版本导出拦截 → 接口）。"""
import json
from argparse import Namespace

import pytest
from conftest import call, make_project

import aicut
from pipeline import exclusions, review, select

pytestmark = pytest.mark.usefixtures("consented")


def _seg(i, start, dur, topic="讲合同", *, level=3, must=False, unusable=False, text=""):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur, "topic": topic,
            "level": level, "key_info": False, "must_keep": must, "unusable": unusable,
            "info_type": "", "text": text or f"第{i}句", "signals": {}}


TOPICS = [{"name": "讲合同", "budget": 30, "must": True, "duration": 60, "usable_dur": 40}]


def _scored(*segs):
    return {"segments": [{"id": i, "start": s, "end": e, "level": 3, "text": t, "topic": "讲合同"}
                         for i, s, e, t in segs], "topics": []}


# ---------------------------------------------------------------- review 存储
def test_review_set_unusable_stores_flag_and_anchor(tmp_path):
    (tmp_path / "segments_scored.json").write_text(
        json.dumps(_scored(("S1", 3.0, 8.0, "身份证号"))), encoding="utf-8")
    _, cleared = review.set_unusable(tmp_path, "S1", True)
    item = review.load(tmp_path)["S1"]
    assert item["unusable"] is True and cleared is None
    assert item["anchor"]["start"] == 3.0 and item["anchor"]["text"]


def test_review_unusable_clears_must_keep(tmp_path):
    review.set_must(tmp_path, "S1", True)
    _, cleared = review.set_unusable(tmp_path, "S1", True)
    item = review.load(tmp_path)["S1"]
    assert cleared == "must_keep"
    assert item["unusable"] is True and item["must_keep"] is False


def test_review_must_clears_unusable(tmp_path):
    review.set_unusable(tmp_path, "S1", True)
    _, cleared = review.set_must_reporting(tmp_path, "S1", True)
    item = review.load(tmp_path)["S1"]
    assert cleared == "unusable"
    assert item["must_keep"] is True and item["unusable"] is False


def test_review_set_must_keeps_dict_return(tmp_path):
    data = review.set_must(tmp_path, "S1", True)
    assert data["S1"]["must_keep"] is True


def test_review_unflagging_does_not_touch_other_flag(tmp_path):
    review.set_must(tmp_path, "S1", True)
    _, cleared = review.set_unusable(tmp_path, "S1", False)
    item = review.load(tmp_path)["S1"]
    assert cleared is None and item["must_keep"] is True and item["unusable"] is False


def test_review_apply_outputs_unusable():
    segs = [{"id": "S1", "level": 3}, {"id": "S2", "level": 3}]
    merged = review.apply(segs, {"S1": {"unusable": True}})
    assert merged[0]["unusable"] is True and merged[1]["unusable"] is False


def test_review_unset_level_keeps_flags(tmp_path):
    review.set_level(tmp_path, "S1", 1)
    review.set_unusable(tmp_path, "S1", True)
    review.unset_level(tmp_path, "S1")
    item = review.load(tmp_path)["S1"]
    assert "level" not in item and item["unusable"] is True


def test_review_unset_level_drops_empty_entry(tmp_path):
    review.set_level(tmp_path, "S1", 3)
    review.unset_level(tmp_path, "S1")
    assert "S1" not in review.load(tmp_path)


def test_review_unset_level_without_entry_is_noop(tmp_path):
    assert review.unset_level(tmp_path, "S9") == {}


@pytest.mark.parametrize("op", [
    lambda w: review.set_unusable(w, "S1", True),
    lambda w: review.set_must_reporting(w, "S1", True),
    lambda w: review.unset_level(w, "S1"),
])
def test_review_writers_on_corrupt_keep_file(tmp_path, op):
    path = tmp_path / "overrides.json"
    path.write_text("{坏的", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        op(tmp_path)
    assert path.read_text(encoding="utf-8") == "{坏的"


# ---------------------------------------------------------------- select 排除
def test_select_excludes_unusable_from_shots_unused_and_stats():
    segs = [_seg(1, 0, 6), _seg(2, 10, 6, unusable=True), _seg(3, 20, 6)]
    res = select.select(segs, TOPICS, {}, 60)
    assert "S002" not in [s["segment_id"] for s in res["shots"]]
    assert "S002" not in [u["segment_id"] for u in res["unused"]]
    assert res["stats"]["usable_total"] == 2


def test_select_unusable_with_must_keep_is_dropped_without_error():
    segs = [_seg(1, 0, 6), _seg(2, 10, 6, must=True, unusable=True)]
    res = select.select(segs, TOPICS, {}, 60)
    assert "S002" not in [s["segment_id"] for s in res["shots"]]
    assert "S002" not in res["must_keep_ids"]


def test_select_does_not_force_line_from_unusable_segment():
    segs = [_seg(1, 0, 6), _seg(2, 10, 8, unusable=True, text="我的身份证号是一二三四五六")]
    res = select.select(segs, TOPICS, {"must_lines": ["我的身份证号是一二三四五六"]}, 60)
    assert "S002" not in [s["segment_id"] for s in res["shots"]]
    assert any("身份证号" in w for w in res["warnings"])


def test_missing_must_keep_ignores_unusable_segment(tmp_path):
    (tmp_path / "segments_scored.json").write_text(
        json.dumps(_scored(("S1", 0, 6, "甲"))), encoding="utf-8")
    (tmp_path / "overrides.json").write_text(
        json.dumps({"S1": {"must_keep": True, "unusable": True}}), encoding="utf-8")
    assert select.missing_must_keep(tmp_path, [{"id": "a", "in": 50.0, "out": 60.0}]) == []


# ---------------------------------------------------------------- exclusions 纯函数
def test_spans_lists_unusable_segments(tmp_path):
    (tmp_path / "segments_scored.json").write_text(
        json.dumps(_scored(("S1", 0, 6, "甲"), ("S2", 10, 16, "乙"))), encoding="utf-8")
    review.set_unusable(tmp_path, "S2", True)
    assert exclusions.spans(tmp_path) == [(10.0, 16.0, "S2")]


def test_spans_without_analysis_is_empty(tmp_path):
    assert exclusions.spans(tmp_path) == []


def test_spans_corrupt_overrides_raises(tmp_path):
    (tmp_path / "segments_scored.json").write_text(
        json.dumps(_scored(("S1", 0, 6, "甲"))), encoding="utf-8")
    (tmp_path / "overrides.json").write_text("[", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        exclusions.spans(tmp_path)


def test_drop_overlapping_uses_threshold():
    spans = [(10.0, 16.0, "S2")]
    shots = [{"id": "a", "in": 0, "out": 10.05},      # 只重叠 0.05 秒：保留
             {"id": "b", "in": 9, "out": 12},         # 重叠 2 秒：剔除
             {"id": "c", "in": 16, "out": 20}]        # 紧邻：保留
    kept, dropped = exclusions.drop_overlapping(shots, spans)
    assert [s["id"] for s in kept] == ["a", "c"] and dropped == ["b"]


def test_drop_overlapping_without_spans_returns_same_shots():
    shots = [{"id": "a", "in": 0, "out": 5}]
    kept, dropped = exclusions.drop_overlapping(shots, [])
    assert kept == shots and dropped == []


def test_timeline_hits_counts_snapshot_shots(tmp_path):
    work = tmp_path / "work"
    vdir = tmp_path / "output" / "v1"
    work.mkdir()
    vdir.mkdir(parents=True)
    (work / "segments_scored.json").write_text(
        json.dumps(_scored(("S1", 10, 16, "乙"))), encoding="utf-8")
    review.set_unusable(work, "S1", True)
    (vdir / "shots_snapshot.json").write_text(json.dumps({"shots": [
        {"id": "a", "in": 0.0, "out": 5.0}, {"id": "b", "in": 12.0, "out": 14.0}]}), encoding="utf-8")
    assert exclusions.timeline_hits(work, vdir) == 1


def test_timeline_hits_without_snapshot_fails_closed(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "segments_scored.json").write_text(
        json.dumps(_scored(("S1", 10, 16, "乙"))), encoding="utf-8")
    review.set_unusable(work, "S1", True)
    with pytest.raises(exclusions.ExclusionError, match="没有留存"):
        exclusions.timeline_hits(work, tmp_path / "output" / "v1")


# ---------------------------------------------------------------- aicut build / export
class Reached(Exception):
    pass


def _project(root, name="p", **work):
    pdir = root / name
    (pdir / "work").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "material": "/tmp/a.mp4", "schema_version": 2, "target_duration": 175}),
        encoding="utf-8")
    for rel, obj in work.items():
        (pdir / "work" / rel).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return pdir


def _selected(pdir, *spans):
    shots = [{"id": f"sel{i:02d}", "in": a, "out": b} for i, (a, b) in enumerate(spans, 1)]
    (pdir / "work" / "shots-selected.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")


def test_build_drops_unusable_shots_with_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    seen = []

    def stop(pdir, c, shots):
        seen.append([s["id"] for s in shots])
        raise Reached
    monkeypatch.setattr(aicut, "ensure_clips", stop)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S1", 0, 6, "甲"), ("S2", 10, 16, "乙")),
                                 "overrides.json": {"S2": {"unusable": True}}})
    _selected(pdir, (0, 6), (10, 16))
    with pytest.raises(Reached):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    assert seen == [["sel01"]]
    assert "[!] 已自动剔除 1 个含「不可用」片段的镜头：sel02" in capsys.readouterr().out


def test_build_dies_when_all_shots_dropped(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: pytest.fail("不应切片"))
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S2", 10, 16, "乙")),
                                 "overrides.json": {"S2": {"unusable": True}}})
    _selected(pdir, (10, 16))
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    assert "[x] 分镜表里的镜头都含「不可用」片段" in capsys.readouterr().out


def test_build_without_analysis_skips_unusable_check(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)

    def stop(*_a):
        raise Reached
    monkeypatch.setattr(aicut, "ensure_clips", stop)
    pdir = _project(tmp_path)
    _selected(pdir, (0, 6))
    with pytest.raises(Reached):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))


def test_export_blocks_version_with_unusable_shots(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S2", 10, 16, "乙")),
                                 "overrides.json": {"S2": {"unusable": True}}})
    vdir = pdir / "output" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text("{}", encoding="utf-8")
    (vdir / "shots_snapshot.json").write_text(
        json.dumps({"shots": [{"id": "sel01", "in": 11.0, "out": 13.0}]}), encoding="utf-8")
    monkeypatch.setattr(aicut.clips, "restore_missing", lambda *a, **k: pytest.fail("不应补切"))
    monkeypatch.setattr(aicut.export_draft, "build_windows_package",
                        lambda *a: pytest.fail("不应导出"))
    with pytest.raises(SystemExit):
        aicut.cmd_export(Namespace(name="p", timeline=str(vdir / "timeline.json"),
                                   package_name=None, out=str(tmp_path)))
    assert "[x] 这一版含 1 段已标为不可用的片段，不能再导出；请生成新版本" in capsys.readouterr().out


# ---------------------------------------------------------------- POST /api/browse/unusable
def _api_project(gs, shots=None):
    pdir = make_project(gs.root, shots=shots, **{
        "work/segments_scored.json": json.dumps(
            _scored(("S1", 0, 6, "甲"), ("S2", 10, 16, "乙")), ensure_ascii=False)})
    return pdir


def _mark(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/browse/unusable", {"project": "p1", **body})
    return status, json.loads(raw)


def test_api_unusable_marks_and_reports(gui_server):
    pdir = _api_project(gui_server)
    status, data = _mark(gui_server, id="S2", unusable=True)
    assert status == 200 and data["ok"] is True
    assert data["segment"]["unusable"] is True
    assert data["removed_shots"] == [] and data["cleared"] is None
    assert data["clip_list"]["items"] == []
    assert review.load(pdir / "work")["S2"]["unusable"] is True
    assert not (pdir / "shots.json").exists()  # 没有手动分镜表：不新建


def test_api_unusable_removes_overlapping_manual_shots(gui_server):
    pdir = _api_project(gui_server, shots=[{"id": "a", "in": 0, "out": 5},
                                           {"id": "b", "in": 11, "out": 14}])
    status, data = _mark(gui_server, id="S2", unusable=True)
    assert status == 200 and [x["id"] for x in data["removed_shots"]] == ["b"]
    left = json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["shots"]
    assert [s["id"] for s in left] == ["a"]


def test_api_unusable_leaves_shots_file_when_nothing_overlaps(gui_server):
    pdir = _api_project(gui_server, shots=[{"id": "a", "in": 0, "out": 5}])
    before = (pdir / "shots.json").read_bytes()
    _, data = _mark(gui_server, id="S2", unusable=True)
    assert data["removed_shots"] == [] and (pdir / "shots.json").read_bytes() == before


def test_api_unusable_removes_from_clip_list(gui_server):
    pdir = _api_project(gui_server)
    review.set_must(pdir / "work", "S2", True)
    status, data = _mark(gui_server, id="S2", unusable=True)
    assert status == 200 and data["cleared"] == "must_keep"
    assert data["clip_list"]["items"] == []


def test_api_must_on_unusable_reports_cleared(gui_server):
    pdir = _api_project(gui_server)
    review.set_unusable(pdir / "work", "S2", True)
    status, raw, _ = call(gui_server, "POST", "/api/browse/must",
                          {"project": "p1", "id": "S2", "must": True})
    data = json.loads(raw)
    assert status == 200 and data["ok"] is True and data["cleared"] == "unusable"


def test_api_unusable_corrupt_overrides_409(gui_server):
    pdir = _api_project(gui_server)
    (pdir / "work" / "overrides.json").write_text("{坏", encoding="utf-8")
    status, data = _mark(gui_server, id="S2", unusable=True)
    assert status == 409 and "损坏" in data["error"]


def test_api_unusable_missing_id_400(gui_server):
    _api_project(gui_server)
    status, _ = _mark(gui_server, unusable=True)
    assert status == 400


def test_api_unusable_bad_id_400(gui_server):
    _api_project(gui_server)
    status, data = _mark(gui_server, id="S999", unusable=True)
    assert status == 400 and "S999" in data["error"]


def test_api_unusable_unknown_project_404(gui_server):
    status, raw, _ = call(gui_server, "POST", "/api/browse/unusable",
                          {"project": "nope", "id": "S1", "unusable": True})
    assert status == 404


# ---------------------------------------------------------------- payloads.clip_list（D14）
def test_clip_list_orders_by_marked_time_and_sums():
    from gui import payloads
    segs = [{"id": "S1", "start": 0, "end": 30, "must_keep": True, "must_at": "2026-01-01T00:00:09+00:00",
             "text": "甲", "topic": "t"},
            {"id": "S2", "start": 40, "end": 70, "must_keep": True, "must_at": "2026-01-01T00:00:01+00:00",
             "text": "乙", "topic": "t"},
            {"id": "S3", "start": 80, "end": 90, "must_keep": False, "text": "丙"}]
    out = payloads.clip_list(segs, 100)
    assert [i["id"] for i in out["items"]] == ["S2", "S1"]
    assert out["total"] == 60 and out["target"] == 100
    assert out["over_target"] is False and out["suggested_target"] is None


def test_clip_list_over_target_suggests_rounded_up():
    from gui import payloads
    segs = [{"id": "S1", "start": 0, "end": 63, "must_keep": True, "text": "甲", "topic": "t"}]
    out = payloads.clip_list(segs, 60)
    assert out["over_target"] is True and out["suggested_target"] == 65
    assert out["over_by"] == 3


def test_clip_list_excludes_unusable_even_if_must():
    from gui import payloads
    segs = [{"id": "S1", "start": 0, "end": 5, "must_keep": True, "unusable": True, "text": "甲"}]
    assert payloads.clip_list(segs, 60)["items"] == []


# ---------------------------------------------------------------- 评审修复：HIGH-1 剔除后必留段丢失
def test_build_dies_when_dropping_shot_loses_adjacent_must_keep(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: pytest.fail("不应切片"))
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S1", 0, 6, "甲"), ("S2", 10, 16, "乙")),
                                 "overrides.json": {"S1": {"must_keep": True}, "S2": {"unusable": True}}})
    (pdir / "shots.json").write_text(json.dumps({"shots": [{"id": "sh01", "in": 0, "out": 20}]}),
                                     encoding="utf-8")
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    out = capsys.readouterr().out
    assert "[x]" in out and "S1" in out and "S2" in out and "sh01" in out and "拆" in out


# ---------------------------------------------------------------- HIGH-2 shots.json 共用一把锁
def test_shots_save_and_unusable_share_the_shots_lock(gui_server):
    import threading

    from pipeline import shots_store
    _api_project(gui_server, shots=[{"id": "a", "in": 11, "out": 14}])
    results = []
    calls = [("/api/shots?project=p1", {"project": "p1", "shots": [{"id": "z", "in": 0, "out": 3}]}),
             ("/api/browse/unusable", {"project": "p1", "id": "S2", "unusable": True})]
    with shots_store.thread_lock(gui_server.root / "p1"):
        threads = [threading.Thread(target=lambda c=c: results.append(call(gui_server, "POST", *c)[0]))
                   for c in calls]
        for t in threads:
            t.start()
        for t in threads:
            t.join(0.5)
        assert results == [] and all(t.is_alive() for t in threads), results
    for t in threads:
        t.join(5)
    assert sorted(results) == [200, 200]


# ---------------------------------------------------------------- MEDIUM-3 先校验后写
def test_api_unusable_validates_before_writing(gui_server):
    pdir = _api_project(gui_server)
    (pdir / "shots.json").write_text("{坏", encoding="utf-8")
    status, _ = _mark(gui_server, id="S2", unusable=True)
    assert status == 409
    assert not (pdir / "work" / "overrides.json").exists()


# ---------------------------------------------------------------- MEDIUM-4 must_at
def test_must_at_set_once_and_cleared(tmp_path):
    review.set_must(tmp_path, "S1", True)
    first = review.load(tmp_path)["S1"]["must_at"]
    review.set_must(tmp_path, "S1", True)
    assert review.load(tmp_path)["S1"]["must_at"] == first
    review.set_must(tmp_path, "S1", False)
    assert "must_at" not in review.load(tmp_path)["S1"]


def test_must_at_cleared_when_unusable_takes_over(tmp_path):
    review.set_must(tmp_path, "S1", True)
    review.set_unusable(tmp_path, "S1", True)
    assert "must_at" not in review.load(tmp_path)["S1"]


def test_apply_exposes_must_at_only_for_must_keep():
    segs = [{"id": "S1", "level": 3}, {"id": "S2", "level": 3}]
    merged = review.apply(segs, {"S1": {"must_keep": True, "must_at": "T"}, "S2": {"level": 3, "at": "X"}})
    assert merged[0]["must_at"] == "T" and "must_at" not in merged[1] and "marked_at" not in merged[0]


# ---------------------------------------------------------------- MEDIUM-5 导出失败即关闭
def _marked_version(tmp_path, snapshot):
    work = tmp_path / "work"
    vdir = tmp_path / "output" / "v1"
    work.mkdir()
    vdir.mkdir(parents=True)
    (work / "segments_scored.json").write_text(json.dumps(_scored(("S1", 10, 16, "乙"))), encoding="utf-8")
    review.set_unusable(work, "S1", True)
    if snapshot is not None:
        (vdir / "shots_snapshot.json").write_text(snapshot, encoding="utf-8")
    return work, vdir


def test_timeline_hits_corrupt_snapshot_fails_closed_with_distinct_message(tmp_path):
    work, vdir = _marked_version(tmp_path, "{坏")
    with pytest.raises(exclusions.ExclusionError, match="损坏"):
        exclusions.timeline_hits(work, vdir)


def test_timeline_hits_without_marks_ignores_missing_snapshot(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    assert exclusions.timeline_hits(work, tmp_path / "output" / "v1") == 0


def test_export_blocks_when_snapshot_missing_and_marks_exist(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S2", 10, 16, "乙")),
                                 "overrides.json": {"S2": {"unusable": True}}})
    vdir = pdir / "output" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(aicut.export_draft, "build_windows_package", lambda *a: pytest.fail("不应导出"))
    with pytest.raises(SystemExit):
        aicut.cmd_export(Namespace(name="p", timeline=str(vdir / "timeline.json"),
                                   package_name=None, out=str(tmp_path)))
    out = capsys.readouterr().out
    assert "无法确认这一版是否含已标为不可用的片段" in out and "请生成新版本" in out


# ---------------------------------------------------------------- MEDIUM-6 阈值
def test_drop_overlapping_catches_very_short_unusable_span():
    kept, dropped = exclusions.drop_overlapping([{"id": "a", "in": 0, "out": 10}], [(5.0, 5.08, "S1")])
    assert dropped == ["a"] and kept == []


def test_drop_overlapping_catches_zero_length_span_inside_shot():
    _, dropped = exclusions.drop_overlapping([{"id": "a", "in": 0, "out": 10}], [(5.0, 5.0, "S1")])
    assert dropped == ["a"]


def test_drop_overlapping_zero_length_span_outside_shot_kept():
    _, dropped = exclusions.drop_overlapping([{"id": "a", "in": 0, "out": 10}], [(11.0, 11.0, "S1")])
    assert dropped == []


# ---------------------------------------------------------------- MEDIUM-7 备份 + 完整镜头
def test_api_unusable_backs_up_shots_and_returns_full_objects(gui_server):
    pdir = _api_project(gui_server, shots=[{"id": "a", "in": 0, "out": 5},
                                           {"id": "b", "in": 11, "out": 14}])
    original = json.loads((pdir / "shots.json").read_text(encoding="utf-8"))
    _, data = _mark(gui_server, id="S2", unusable=True)
    assert data["removed_shots"] == [{"id": "b", "in": 11.0, "out": 14.0}] or \
        [x["id"] for x in data["removed_shots"]] == ["b"] and data["removed_shots"][0]["out"] == 14
    backup = json.loads((pdir / "work" / "shots.before-unusable.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in backup["shots"]] == [x["id"] for x in original["shots"]]


def test_api_unusable_no_backup_when_nothing_removed(gui_server):
    pdir = _api_project(gui_server, shots=[{"id": "a", "in": 0, "out": 5}])
    _mark(gui_server, id="S2", unusable=True)
    assert not (pdir / "work" / "shots.before-unusable.json").exists()


# ---------------------------------------------------------------- 安全：入参类型
@pytest.mark.parametrize("path,body", [
    ("/api/browse/unusable", {"id": 5, "unusable": True}),
    ("/api/browse/unusable", {"id": "S2", "unusable": "true"}),
    ("/api/browse/unusable", {"id": "S2"}),
    ("/api/browse/must", {"id": ["S2"], "must": True}),
    ("/api/browse/must", {"id": "S2", "must": "yes"}),
    ("/api/browse/must", {"id": "S2", "must": 1}),
])
def test_api_mark_rejects_wrong_types(gui_server, path, body):
    pdir = _api_project(gui_server)
    status, raw, _ = call(gui_server, "POST", path, {"project": "p1", **body})
    assert status == 400
    assert not (pdir / "work" / "overrides.json").exists()


# ---------------------------------------------------------------- 安全 L6：损坏文件不出 traceback
def test_export_with_corrupt_scored_dies_friendly(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path)
    (pdir / "work" / "segments_scored.json").write_text("{坏", encoding="utf-8")
    vdir = pdir / "output" / "v1"
    vdir.mkdir(parents=True)
    (vdir / "timeline.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        aicut.cmd_export(Namespace(name="p", timeline=str(vdir / "timeline.json"),
                                   package_name=None, out=str(tmp_path)))
    assert "[x]" in capsys.readouterr().out


def test_build_with_malformed_segments_dies_friendly(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: pytest.fail("不应切片"))
    pdir = _project(tmp_path, **{"segments_scored.json": {"segments": [{"id": "S1", "level": 3}]},
                                 "overrides.json": {"S1": {"unusable": True}}})
    _selected(pdir, (0, 6))
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    assert "[x]" in capsys.readouterr().out
