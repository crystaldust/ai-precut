"""画面与对白整合：画面事件挂到对白片段、无对白时段生成画面片段、落盘与「是否当前」。"""
import copy
import json

import pytest

from pipeline import format_transcript, vision_align as va, vision_run

ON = {"vision": {"enabled": True, "tier": "economy"}}
OFF = {"vision": {"enabled": False, "tier": "economy"}}


def seg(i, start, end):
    return {"id": f"S{i:03d}", "start": start, "end": end, "text": f"第{i}句"}


def ev(start, end, *, people="一人", action="说话", text="", objects=(), issues=()):
    return {"start": start, "end": end, "people": people, "action": action,
            "text_on_screen": text, "objects": list(objects), "issues": list(issues)}


# ---------------------------------------------------------------- 挂到对白片段
def test_attach_takes_description_from_event_with_most_overlap():
    out = va.attach([seg(1, 10, 20)], [ev(8, 14, action="走路"), ev(14, 30, action="签合同")])
    assert out["S001"]["desc"].startswith("一人，签合同")
    assert "走路" in out["S001"]["desc"]  # 前两个都进描述，重叠多的在前


def test_attach_skips_segment_without_overlapping_event():
    assert va.attach([seg(1, 0, 5)], [ev(5, 9)]) == {}


@pytest.mark.parametrize("covered, expected", [(4.9, []), (5.0, ["背对镜头"])])
def test_issue_needs_half_of_segment(covered, expected):
    events = [ev(0, covered, issues=["背对镜头"]), ev(covered, 10)]
    assert va.attach([seg(1, 0, 10)], events)["S001"]["issues"] == expected


def test_dark_and_blur_from_cloud_are_left_to_local_quality_check():
    out = va.attach([seg(1, 0, 10)], [ev(0, 10, issues=["过暗", "模糊", "遮挡"])])
    assert out["S001"]["issues"] == ["遮挡"]


def test_attach_truncates_and_dedupes_model_text():
    long = "字" * 500
    events = [ev(0, 5, people=long, text="培训协议书", objects=["合同"] * 3 + [f"物{i}" for i in range(20)]),
              ev(5, 10, text="培训协议书")]
    v = va.attach([seg(1, 0, 10)], events)["S001"]
    assert len(v["desc"]) == va.DESC_MAX and v["text_on_screen"] == "培训协议书"
    assert v["objects"][0] == "合同" and len(v["objects"]) == va.OBJECTS_MAX


def test_attach_does_not_mutate_inputs():
    segs, events = [seg(1, 0, 10)], [ev(0, 10, issues=["遮挡"])]
    before = copy.deepcopy((segs, events))
    va.attach(segs, events)
    va.visual_segments(segs, events, [], 30)
    assert (segs, events) == before


# ---------------------------------------------------------------- 画面片段
def test_visual_segment_fills_gap_between_speech():
    out = va.visual_segments([seg(1, 0, 10), seg(2, 30, 40)], [ev(10, 30, action="坐电梯")], [], 40)
    assert [(v["id"], v["start"], v["end"], v["text"], v["kind"]) for v in out] == [("V001", 10, 30, "", "visual")]
    assert "坐电梯" in out[0]["visual"]["desc"]


def test_gaps_at_head_and_tail_count():
    out = va.visual_segments([seg(1, 10, 20)], [ev(0, 40)], [], 40)
    assert [(v["start"], v["end"]) for v in out] == [(0, 10), (20, 40)]


def test_short_gap_or_gap_without_event_gives_nothing():
    assert va.visual_segments([seg(1, 0, 10), seg(2, 12.5, 20)], [ev(0, 20)], [], 20) == []
    assert va.visual_segments([seg(1, 0, 10), seg(2, 30, 40)], [ev(0, 10), ev(30, 40)], [], 40) == []


def test_long_gap_is_split_to_max_length():
    out = va.visual_segments([], [ev(0, 80)], [], 80)
    assert len(out) == 3 and all(v["duration"] <= va.MAX_SEG_S for v in out)
    assert out[0]["start"] == 0 and out[-1]["end"] == 80


def test_max_length_matches_transcript_segments():
    assert va.MAX_SEG_S == format_transcript.MAX_SEG


def test_boundary_snaps_to_nearby_cut_inside_gap_only():
    speech = [seg(1, 0, 10), seg(2, 30, 40)]
    out = va.visual_segments(speech, [ev(12, 28)], [12.6, 29.5], 40)
    assert (out[0]["start"], out[0]["end"]) == (12.6, 28.0)  # 29.5 离 28 超过 1 秒，不吸附
    tail = va.visual_segments(speech, [ev(12, 29.8)], [30.6], 40)
    assert tail[0]["end"] == 29.8  # 30.6 在对白里（空档 10–30 之外），不吸附过去


def test_overlapping_events_do_not_produce_overlapping_pieces():
    out = va.visual_segments([], [ev(0, 20, action="甲"), ev(10, 30, action="乙")], [], 30)
    assert all(a["end"] <= b["start"] for a, b in zip(out, out[1:]))


def test_visual_segment_keeps_every_cloud_issue():
    out = va.visual_segments([], [ev(0, 10, issues=["过暗", "背对镜头"])], [], 10)
    assert out[0]["visual"]["issues"] == ["背对镜头", "过暗"]


def test_no_events_no_visual_segments():
    assert va.visual_segments([seg(1, 0, 5)], [], [], 60) == []


# ---------------------------------------------------------------- 落盘与「是否当前」
@pytest.fixture
def work(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    (w / "segments.json").write_text(json.dumps({"segments": [seg(1, 0, 10), seg(2, 30, 40)]}), encoding="utf-8")
    (w / vision_run.TIMELINE_FILE).write_text(json.dumps(
        {"key": "k1", "duration": 40, "events": [ev(0, 40, issues=["遮挡"])]}, ensure_ascii=False), encoding="utf-8")
    (w / va.SHOTS_FILE).write_text(json.dumps({"shots": [{"start": 0}, {"start": 10.8}]}), encoding="utf-8")
    monkeypatch.setattr(vision_run, "timeline_current", lambda _w, _c: True)
    return w


def test_run_writes_aligned_file(work):
    res = va.run(work, ON)
    saved = json.loads((work / va.ALIGNED_FILE).read_text(encoding="utf-8"))
    assert saved == res and res["timeline_key"] == "k1" and res["warnings"] == []
    assert set(res["by_segment"]) == {"S001", "S002"} and res["visual_segments"][0]["start"] == 10.8
    assert res["artifact_schema"]


def test_run_without_shots_warns_and_does_not_snap(work):
    (work / va.SHOTS_FILE).unlink()
    res = va.run(work, ON)
    assert res["warnings"] == [va.SHOTS_MISSING] and res["visual_segments"][0]["start"] == 10


def test_run_when_off_skips_and_leaves_old_file(work):
    (work / va.ALIGNED_FILE).write_text("old", encoding="utf-8")
    assert va.run(work, OFF) == {"skipped": True}
    assert (work / va.ALIGNED_FILE).read_text(encoding="utf-8") == "old"


def test_run_with_stale_timeline_raises(work, monkeypatch):
    monkeypatch.setattr(vision_run, "timeline_current", lambda _w, _c: False)
    with pytest.raises(va.AlignError):
        va.run(work, ON)
    assert not (work / va.ALIGNED_FILE).exists()


def test_current_tracks_timeline_key_and_segments(work, monkeypatch):
    assert va.current(work, ON) is False  # 还没整合
    va.run(work, ON)
    assert va.current(work, ON) is True
    assert va.current(work, OFF) is False
    (work / "segments.json").write_text(json.dumps({"segments": [seg(1, 0, 9)]}), encoding="utf-8")
    assert va.current(work, ON) is False  # 对白片段变了
    va.run(work, ON)
    tl = json.loads((work / vision_run.TIMELINE_FILE).read_text(encoding="utf-8"))
    (work / vision_run.TIMELINE_FILE).write_text(json.dumps({**tl, "key": "k2"}), encoding="utf-8")
    assert va.current(work, ON) is False  # 时间轴换了
    monkeypatch.setattr(vision_run, "timeline_current", lambda _w, _c: False)
    assert va.current(work, ON) is False


def test_for_text_off_current_and_stale(work, monkeypatch):
    (work / va.ALIGNED_FILE).write_text(json.dumps({"by_segment": {}}), encoding="utf-8")
    assert va.for_text(work, OFF) is None  # 关着：残留文件不读
    with pytest.raises(va.AlignError):
        va.for_text(work, ON)  # 开着但整合结果对不上
    saved = va.run(work, ON)
    assert va.for_text(work, ON) == saved


def test_snapping_never_makes_piece_longer_than_max():
    """切点在分块边界外 0.9 秒：吸附后会超过 35 秒，就不吸附（审查 M2）。"""
    out = va.visual_segments([], [ev(0, 70)], [0.0, 34.1, 35.9, 70.0], 70)
    assert all(v["duration"] <= va.MAX_SEG_S for v in out)


def test_current_goes_stale_when_shot_cuts_change(work):
    va.run(work, ON)
    assert va.current(work, ON) is True
    (work / va.SHOTS_FILE).write_text(json.dumps({"shots": [{"start": 0}, {"start": 11.0}]}), encoding="utf-8")
    assert va.current(work, ON) is False  # 镜头切点变了，画面片段边界要重算（审查 M4）


def test_non_list_objects_are_ignored():
    out = va.attach([seg(1, 0, 10)], [{**ev(0, 10), "objects": "合同"}])
    assert out["S001"]["objects"] == []


def test_score_key(work, monkeypatch):
    assert va.score_key(work, OFF) is False
    assert va.score_key(work, ON) == ""  # 还没整合
    va.run(work, ON)
    assert va.score_key(work, ON) == "k1"
