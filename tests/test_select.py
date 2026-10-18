import json

import pytest

from pipeline import select


def seg(i, start, dur, topic, *, level=3, key=False, must=False, text="", info=""):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur, "topic": topic,
            "level": level, "key_info": key, "must_keep": must,
            "info_type": info, "text": text or f"第{i}句", "signals": {}}


TOPICS = [
    {"name": "讲合同", "budget": 20, "must": True, "duration": 60, "usable_dur": 40},
    {"name": "聊吃饭", "budget": 10, "must": False, "duration": 60, "usable_dur": 30},
]


def test_must_keep_always_selected():
    segs = [seg(1, 0, 5, "讲合同", must=True),
            seg(2, 10, 5, "聊吃饭")]
    res = select.select(segs, TOPICS, {"must_topics": [], "exclude_topics": []}, 60)
    ids = [s["segment_id"] for s in res["shots"]]
    assert "S001" in ids


def test_excluded_topic_not_selected():
    segs = [seg(1, 0, 5, "讲合同"), seg(2, 10, 5, "聊吃饭")]
    res = select.select(segs, TOPICS, {"exclude_topics": ["聊吃饭"]}, 60)
    assert all(s["topic"] != "聊吃饭" for s in res["shots"])


def test_topic_budget_respected():
    segs = [seg(i, i * 10, 6, "讲合同") for i in range(1, 6)]  # 5 × 6s
    res = select.select(segs, TOPICS, {}, 120)
    total = sum(s["dur"] for s in res["shots"] if s["topic"] == "讲合同")
    assert total <= 20 * 1.1 + 0.01  # 话题预算允许多出 10%


def test_total_not_over_target():
    segs = [seg(i, i * 10, 8, "讲合同") for i in range(1, 6)]
    res = select.select(segs, TOPICS, {}, 20)  # 目标比素材还小
    assert res["total"] <= 20 * 1.10 + 0.01


def test_ending_moves_matching_shot_last():
    segs = [seg(1, 0, 6, "讲合同", text="看一下合同"),
            seg(2, 10, 6, "聊吃饭", text="现在去签字缴费")]
    res = select.select(segs, TOPICS, {"ending": "sign"}, 60)
    assert res["shots"][-1]["segment_id"] == "S002"


def test_unused_records_reason():
    segs = [seg(i, i * 10, 6, "讲合同") for i in range(1, 6)]
    res = select.select(segs, TOPICS, {}, 60)
    assert res["unused"]
    assert all(u["reason"] for u in res["unused"])


def test_rules_from_question_answers():
    questions = {"questions": [
        {"id": "q1", "options": [{"label": "合同全额", "rule": {"kind": "must_topics",
                                                               "value": ["讲合同"]}}]},
        {"id": "q2", "options": [{"label": "签字收尾", "rule": {"kind": "ending",
                                                               "value": "sign"}}]},
    ]}
    rules = select._rules({"q1": "合同全额", "q2": "签字收尾"}, questions)
    assert rules["must_topics"] == ["讲合同"]
    assert rules["ending"] == "sign"


def test_to_shot_list_shape():
    segs = [seg(1, 0, 6, "讲合同")]
    res = select.select(segs, TOPICS, {}, 60)
    tl = select.to_shot_list(res, "片名", "/tmp/a.mp4")
    assert tl["shots"][0]["in"] == 0.0 and tl["shots"][0]["out"] == 6.0
    assert tl["project"] == "片名"


def test_markdown_contains_table():
    segs = [seg(1, 0, 6, "讲合同")]
    res = select.select(segs, TOPICS, {}, 60)
    md = select.markdown(res)
    assert "选段表" in md and "| sel01 |" in md


def test_run_writes_files(tmp_path):
    scored = {"target": 60, "topics": TOPICS,
              "segments": [seg(1, 0, 6, "讲合同", key=True)]}
    sp = tmp_path / "scored.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "answers.json"
    ap.write_text(json.dumps({"answers": {}}), encoding="utf-8")
    res = select.run(sp, ap, tmp_path, title="片名", material="/tmp/a.mp4")
    assert (tmp_path / "selection.json").exists()
    assert (tmp_path / "shots-selected.json").exists()
    assert res["shots"]


def test_hook_moves_best_informative_shot_to_front():
    segs = [seg(1, 0, 6, "讲合同", text="开头普通一句"),
            seg(2, 10, 6, "讲合同", text="九千八", key=True, info="金额价格"),
            seg(3, 20, 6, "聊吃饭", text="吃饭"),
            seg(4, 30, 6, "聊吃饭", text="再聊")]
    topics = [{"name": "讲合同", "budget": 30, "must": True},
              {"name": "聊吃饭", "budget": 10, "must": False}]
    res = select.select(segs, topics, {}, 60)
    assert res["shots"][0]["role"] == "hook"
    assert "九千八" in res["shots"][0]["sub"]


def test_stored_rules_win_over_answers(tmp_path):
    scored = {"target": 60, "topics": TOPICS,
              "segments": [seg(1, 0, 6, "讲合同"), seg(2, 10, 6, "聊吃饭")]}
    sp = tmp_path / "scored.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "answers.json"
    ap.write_text(json.dumps({"answers": {}, "rules": {"exclude_topics": ["聊吃饭"]}}),
                  encoding="utf-8")
    res = select.run(sp, ap, tmp_path)
    assert all(s["topic"] != "聊吃饭" for s in res["shots"])


def test_ending_value_normalized_from_label():
    assert select._norm_ending("微信缴费完成") == "sign"
    assert select._norm_ending("学员离校背影") == "leave"
    assert select._norm_ending("随便看看") is None


def test_exclude_label_matches_topic_by_similarity():
    names = ["询问学员籍贯年龄", "讲解合同退费条款"]
    assert select._match_topics(["学员具体籍贯年龄"], names) == ["询问学员籍贯年龄"]
    assert select._match_topics(["完全无关的内容"], names) == []


def test_must_lines_force_segment_into_cut(tmp_path):
    segs = [seg(1, 0, 6, "讲合同", text="普通一句"),
            seg(2, 10, 6, "聊吃饭", text="找不到工作不白学吗", level=1),
            seg(3, 20, 6, "讲合同", text="另一句")]
    scored = {"target": 30, "topics": TOPICS, "segments": segs}
    sp = tmp_path / "scored.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "answers.json"
    ap.write_text(json.dumps({"answers": {}}), encoding="utf-8")
    res = select.run(sp, ap, tmp_path, calibration={"must_lines": "不白学吗"})
    ids = [s["segment_id"] for s in res["shots"]]
    assert "S002" in ids  # 档位是废片、话题也未入选，仍被强制保留
    forced = next(s for s in res["shots"] if s["segment_id"] == "S002")
    assert forced["reason"] == "剪辑员指定必须保留"


def test_over_target_drops_whole_shots_not_shrink():
    segs = [seg(i, i * 10, 6, "讲合同") for i in range(1, 9)]  # 8 × 6s = 48s
    topics = [{"name": "讲合同", "budget": 100, "must": True}]
    res = select.select(segs, topics, {}, 24)
    assert res["total"] <= 24 * 1.05 + 0.01
    assert all(abs(s["dur"] - 6.0) < 0.01 for s in res["shots"])  # 没有碎镜


def test_forced_shot_survives_trim():
    segs = [seg(i, i * 10, 6, "讲合同") for i in range(1, 9)]
    segs.append(seg(20, 200, 6, "聊吃饭", text="不白学吗", level=1))
    topics = [{"name": "讲合同", "budget": 100, "must": True}]
    res = select.select(segs, topics, {"must_lines": ["不白学吗"]}, 30)
    assert any(s.get("forced") for s in res["shots"])
    assert res["total"] <= 30 * 1.10 + 0.01
