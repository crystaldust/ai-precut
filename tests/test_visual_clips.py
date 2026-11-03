"""画面片段在 ③ / 选段 / 导出里的共用读取（pipeline/visual_clips.py）。"""
import copy

from pipeline import visual_clips as vc


def seg(i, start, end, level=3):
    return {"id": f"S{i:03d}", "start": start, "end": end, "text": f"第{i}句", "level": level}


def vseg(n, start, end, level=2, label="扫码付款", desc="一人扫码"):
    return {"id": f"V{n:03d}", "kind": "visual", "start": start, "end": end, "text": "", "level": level,
            "level_reason": "画面片段", "label": label, "visual": {"desc": desc, "issues": []}}


def test_from_scored_drops_malformed_items_and_sets_topic():
    good = vseg(1, 10, 20)
    scored = {"segments": [], "visual_segments": [
        good, "x", {**good, "id": 3}, {**good, "level": 4}, {**good, "end": 10}, {**good, "start": "a"},
        {**good, "kind": "speech"}]}
    out = vc.from_scored(scored)
    assert [v["id"] for v in out] == ["V001"]
    assert out[0]["topic"] == vc.TOPIC and out[0]["text"] == ""


def test_from_scored_without_visual_segments_is_empty():
    assert vc.from_scored({"segments": [seg(1, 0, 5)]}) == []
    assert vc.from_scored({"visual_segments": "坏的"}) == []
    assert vc.from_scored(None) == []


def test_with_visual_interleaves_by_start_and_keeps_speech_untouched():
    speech = [seg(1, 0, 10), seg(2, 30, 40)]
    scored = {"segments": speech, "visual_segments": [vseg(1, 10, 30)]}
    before = copy.deepcopy(scored)
    out = vc.with_visual(scored)
    assert [s["id"] for s in out] == ["S001", "V001", "S002"]
    assert out[0] is speech[0]
    assert scored == before


def test_is_visual():
    assert vc.is_visual(vseg(1, 0, 5)) and not vc.is_visual(seg(1, 0, 5))


def test_title_falls_back_from_label_to_desc_to_topic():
    assert vc.title(vseg(1, 0, 5)) == "扫码付款"
    assert vc.title(vseg(1, 0, 5, label="")) == "一人扫码"
    assert vc.title(vseg(1, 0, 5, label="", desc="")) == vc.TOPIC
    assert len(vc.title(vseg(1, 0, 5, label="字" * 99))) == vc.TITLE_MAX


def test_with_visual_without_visual_segments_keeps_original_order():
    speech = [seg(2, 30, 40), seg(1, 0, 10)]
    assert vc.with_visual({"segments": speech}) == speech


def test_from_scored_rejects_foreign_ids_duplicates_and_bad_visual():
    good = vseg(1, 10, 20)
    scored = {"visual_segments": [good, {**good, "start": 30, "end": 40}, {**vseg(2, 50, 60), "id": "S001"},
                                  {**vseg(3, 70, 80), "visual": "坏的"}]}
    assert [(v["id"], v["start"]) for v in vc.from_scored(scored)] == [("V001", 10)]


def test_with_visual_on_non_dict_is_empty():
    assert vc.with_visual([1, 2]) == []
