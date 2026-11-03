"""画面理解第 3 阶段：模型输出解析与全片时间轴（pipeline/vision_timeline.py，纯函数）。"""
import json

import pytest

from pipeline import vision, vision_timeline as vt

EV = {"start": 0, "end": 5.5, "shot": "近景", "people": "1 人面向镜头", "action": "说话",
      "objects": ["协议书"], "text_on_screen": "", "issues": []}


def doc(*events):
    return json.dumps({"events": list(events)}, ensure_ascii=False)


def test_prompt_asks_objective_fields_and_no_usable_rating():
    for field in ("start", "end", "shot", "people", "action", "objects", "text_on_screen", "issues"):
        assert f'"{field}"' in vt.PROMPT
    for issue in vt.ISSUES:
        assert issue in vt.PROMPT
    assert "usable" not in vt.PROMPT and "可用" not in vt.PROMPT


def test_parse_plain_json():
    events = vt.parse_contents(doc(EV))
    assert events == [{**EV, "start": 0.0, "end": 5.5}]


@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "好的，结果如下：\n{}\n以上。", "```\n{}```"])
def test_parse_tolerates_fences_and_chatter(wrap):
    assert len(vt.parse_contents(wrap.replace("{}", doc(EV)))) == 1


def test_parse_numeric_strings():
    events = vt.parse_contents(doc({**EV, "start": "1.5", "end": "3"}))
    assert (events[0]["start"], events[0]["end"]) == (1.5, 3.0)


@pytest.mark.parametrize("text", ["not json", "{broken", doc(), json.dumps({"x": []}),
                                  json.dumps({"events": "x"}), json.dumps([1, 2]),
                                  doc({"start": 5, "end": 1}, {"start": "a", "end": 2},
                                      {"start": float("nan"), "end": 2}, "x"), ""])
def test_parse_rejects_unusable_output(text):
    with pytest.raises(vt.TimelineParseError):
        vt.parse_contents(text)


def test_parse_drops_bad_events_keeps_good():
    events = vt.parse_contents(doc({"start": 3, "end": 1}, EV, {"end": 2}))
    assert len(events) == 1


def test_parse_filters_issues_objects_and_truncates_fields():
    raw = {**EV, "issues": ["遮挡", "不可用", 3, "遮挡"], "objects": ["a", 3, None, *"bcdefghijklmn"],
           "action": "长" * 500, "people": None, "shot": 7, "extra": "x"}
    ev = vt.parse_contents(doc(raw))[0]
    assert ev["issues"] == ["遮挡"]
    assert ev["objects"] == ["a", *"bcdefghijkl"] and len(ev["objects"]) == vt.OBJECTS_MAX
    assert len(ev["action"]) == vt.FIELD_MAX
    assert ev["people"] == "" and ev["shot"] == ""
    assert "extra" not in ev


def test_to_global_offsets_clamps_drops_and_sorts():
    chunk = {"index": 1, "start": 300.0, "end": 600.0}
    events = [{**EV, "start": 200, "end": 305}, {**EV, "start": 0, "end": 200},
              {**EV, "start": 299.8, "end": 310}]
    out = vt.to_global(events, chunk)
    assert [(e["start"], e["end"]) for e in out] == [(300.0, 500.0), (500.0, 600.0)]
    assert events[0]["start"] == 200  # 不改输入


def test_build_merges_chunks_and_usage():
    results = [
        {"chunk": {"index": 1, "start": 300.0, "end": 400.0}, "events": [{**EV, "start": 10, "end": 20}],
         "tokens": 50},
        {"chunk": {"index": 0, "start": 0.0, "end": 300.0}, "events": [{**EV, "start": 0, "end": 300}],
         "tokens": 100},
    ]
    tl = vt.build(results, 400.0, {"enabled": True, "tier": "economy"})
    assert tl["artifact_schema"] == 1
    assert tl["setting"] == {"enabled": True, "tier": "economy"}
    assert tl["prompt_version"] == vision.PROMPT_VERSION and tl["duration"] == 400.0
    assert [(e["start"], e["end"]) for e in tl["events"]] == [(0.0, 300.0), (310.0, 320.0)]
    assert [c["index"] for c in tl["chunks"]] == [0, 1] and tl["chunks"][0]["tokens"] == 100
    assert tl["usage"] == {"total_tokens": 150}


@pytest.mark.parametrize("text", ['{"events":' + "[" * 5000 + "]" * 5000 + "}",
                                  doc(EV) + " " * (vt.TEXT_MAX + 1)])
def test_parse_rejects_pathological_output(text):
    with pytest.raises(vt.TimelineParseError):
        vt.parse_contents(text)


def test_parse_caps_event_count():
    many = [{**EV, "start": i, "end": i + 1} for i in range(vt.EVENTS_MAX + 50)]
    assert len(vt.parse_contents(doc(*many))) == vt.EVENTS_MAX
