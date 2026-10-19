import json
import random

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


def test_target_comes_from_scored_result(tmp_path):
    scored = {"target": 30, "topics": TOPICS, "segments": [seg(1, 0, 6, "讲合同")]}
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    ap = tmp_path / "a.json"
    ap.write_text(json.dumps({"answers": {}}), encoding="utf-8")
    res = select.run(sp, ap, tmp_path)
    assert res["target"] == 30


# ---------------------------------------------------------------- GL-08 必留整段进片
def _ids(res):
    return [s["segment_id"] for s in res["shots"]]


def test_must_keep_survives_zero_topic_budget():
    segs = [seg(1, 0, 6, "聊吃饭", level=2, must=True)]  # level=3 会被补齐阶段捞回，测不出
    topics = [{"name": "讲合同", "budget": 20}, {"name": "聊吃饭", "budget": 0}]
    assert "S001" in _ids(select.select(segs, topics, {}, 60))


def test_must_keep_survives_excluded_topic():
    segs = [seg(1, 0, 6, "聊吃饭", must=True)]
    res = select.select(segs, TOPICS, {"exclude_topics": ["聊吃饭"]}, 60)
    assert "S001" in _ids(res)  # 必留优先于「哪些不能出现」


def test_must_keep_survives_budget_exhaustion():
    segs = [seg(i, i * 10, 6, "讲合同", must=True) for i in range(1, 6)]
    res = select.select(segs, [{"name": "讲合同", "budget": 10}], {}, 120)
    assert set(_ids(res)) >= {f"S{i:03d}" for i in range(1, 6)}


def test_must_keep_over_target_never_trimmed_and_reported():
    segs = [seg(i, i * 10, 6, "讲合同", must=True) for i in range(1, 6)]
    res = select.select(segs, [{"name": "讲合同", "budget": 100}], {}, 12)  # 必留 30s > 目标 12s
    assert set(_ids(res)) == {f"S{i:03d}" for i in range(1, 6)}
    assert res["must_keep_total"] == 30.0
    assert res["over_target"] is True
    assert res["suggested_target"] == 30
    assert "必留内容共" in res["over_target_warning"]
    assert res["warnings"] == []  # 超目标提示单独一个字段，不靠下标切片


def test_suggested_target_rounds_up_to_step():
    segs = [seg(1, 0, 31.2, "讲合同", must=True)]
    res = select.select(segs, TOPICS, {}, 12)
    assert res["suggested_target"] == 35  # 向上取整到 TARGET_ROUND_STEP=5


def test_must_keep_kept_whole_not_clipped_by_budget_or_max_shot():
    res = select.select([seg(1, 0, 30, "讲合同", must=True)], [{"name": "讲合同", "budget": 10}],
                        {}, 60)
    shot = next(s for s in res["shots"] if s["segment_id"] == "S001")
    assert (shot["start"], shot["end"]) == (0.0, 30.0)


def test_short_must_keep_not_dropped_by_min_shot():
    res = select.select([seg(1, 0, 1.0, "讲合同", must=True), seg(2, 10, 6, "讲合同")],
                        TOPICS, {}, 60)
    assert "S001" in _ids(res)


def test_must_keep_shot_marked_forced_with_reason():
    res = select.select([seg(1, 0, 6, "讲合同", must=True)], TOPICS, {}, 60)
    shot = next(s for s in res["shots"] if s["segment_id"] == "S001")
    assert shot["forced"] is True and shot["must_keep"] is True
    assert shot["reason"].startswith(select.MUST_KEEP_REASON)
    assert res["must_keep_ids"] == ["S001"] and res["over_target"] is False


def test_no_must_keep_reports_empty():
    res = select.select([seg(1, 0, 6, "讲合同")], TOPICS, {}, 60)
    assert res["must_keep_ids"] == [] and res["must_keep_total"] == 0
    assert res["over_target"] is False and res["suggested_target"] is None
    assert res["stats"]["must_keep"] == 0


def test_within_target_has_no_warning():
    res = select.select([seg(1, 0, 6, "讲合同", must=True), seg(2, 10, 6, "讲合同")],
                        TOPICS, {}, 12)
    assert res["warnings"] == [] and res["over_target_warning"] is None


def test_guard_raises_when_must_keep_lost(monkeypatch):
    monkeypatch.setattr(select, "_ensure_must_keep", lambda segs, shots, w: shots)
    segs = [seg(1, 0, 6, "聊吃饭", level=2, must=True)]
    with pytest.raises(select.SelectionError, match="S001"):
        select.select(segs, [{"name": "聊吃饭", "budget": 0}], {}, 60)


def test_markdown_lists_warnings():
    segs = [seg(i, i * 10, 6, "讲合同", must=True) for i in range(1, 6)]
    res = select.select(segs, [{"name": "讲合同", "budget": 100}], {}, 12)
    assert "## 警告" in select.markdown(res)


def test_fmt_duration():
    assert select.fmt_duration(214) == "3 分 34 秒"
    assert select.fmt_duration(45.4) == "45 秒"


def test_must_keep_invariant_randomized():
    rng = random.Random(20261019)
    names = ["讲合同", "聊吃饭", "谈价格", "未归类"]
    for _ in range(300):
        segs = [seg(i, i * 12.0, round(rng.uniform(0.5, 40), 1), rng.choice(names),
                    level=rng.choice([1, 2, 3]), key=rng.random() < 0.3,
                    must=rng.random() < 0.2) for i in range(1, rng.randint(2, 40))]
        topics = [{"name": n, "budget": rng.choice([0, 5, 10, 30, 80])} for n in names[:3]]
        rules = {"exclude_topics": rng.sample(names[:3], rng.randint(0, 2)),
                 "must_topics": rng.sample(names[:3], rng.randint(0, 1)),
                 "ending": rng.choice([None, "sign", "emotion"])}
        res = select.select(segs, topics, rules, rng.choice([10, 30, 60, 175]))
        must = {s["id"] for s in segs if s["must_keep"]}
        assert must <= set(_ids(res)), "必留进片率必须 100%"
        whole = {s["id"]: (s["start"], s["end"]) for s in segs if s["must_keep"]}
        for shot in res["shots"]:
            if shot["segment_id"] in whole:
                assert (shot["start"], shot["end"]) == tuple(
                    round(x, 2) for x in whole[shot["segment_id"]])


def test_run_reallocates_budget_when_target_changed(tmp_path, monkeypatch):
    topics = [{"name": "讲合同", "must": True, "usable_dur": 120, "budget": 20}]
    scored = {"target": 30, "topics": topics, "segments": [seg(1, 0, 6, "讲合同")]}
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    seen = {}
    real = select.select

    def fake_select(segments, topics, rules, target, weights=None):
        seen["budget"], seen["target"] = topics[0]["budget"], target
        return real(segments, topics, rules, target, weights)

    monkeypatch.setattr(select, "select", fake_select)
    select.run(sp, tmp_path / "a.json", tmp_path, target=300)
    assert seen["target"] == 300 and seen["budget"] > 20  # 按新目标重分，不需要重跑 score
    assert json.loads(sp.read_text(encoding="utf-8"))["topics"][0]["budget"] == 20


def test_uncovered_must_keep_reports_missing_segments():
    segs = [seg(1, 0, 6, "讲合同", must=True), seg(2, 10, 6, "讲合同", must=True),
            seg(3, 20, 6, "讲合同")]
    shots = [{"id": "sh01", "in": 0.0, "out": 6.0}, {"id": "sh02", "in": 10.0, "out": 12.0}]
    missing = select.uncovered_must_keep(segs, shots)
    assert [m["id"] for m in missing] == ["S002"]  # 只覆盖 2/6 秒不算进片


def test_uncovered_must_keep_accepts_split_coverage():
    segs = [seg(1, 0, 10, "讲合同", must=True)]
    shots = [{"id": "a", "in": 0.0, "out": 5.0}, {"id": "b", "in": 5.0, "out": 9.9}]
    assert select.uncovered_must_keep(segs, shots) == []  # 两镜拼起来只差 0.1 秒


@pytest.mark.parametrize("dur, covered, missing", [
    (20.0, 18.0, True),    # 比例阈值会放过 2 秒的缺口，绝对容差不会
    (10.0, 9.5, True),
    (3.0, 2.75, True),
    (3.0, 2.8, False),     # 帧/取整误差以内
    (3.0, 3.0, False),
])
def test_uncovered_must_keep_absolute_tolerance(dur, covered, missing):
    segs = [seg(1, 0, dur, "讲合同", must=True)]
    shots = [{"id": "a", "in": 0.0, "out": covered}]
    assert bool(select.uncovered_must_keep(segs, shots)) is missing


def test_uncovered_must_keep_overlapping_shots_not_double_counted():
    segs = [seg(1, 0, 10, "讲合同", must=True)]
    shots = [{"id": "a", "in": 0.0, "out": 5.0}, {"id": "b", "in": 0.0, "out": 5.0}]
    assert [m["id"] for m in select.uncovered_must_keep(segs, shots)] == ["S001"]


# ---------------------------------------------------------------- M2 审查
def test_over_target_drops_all_non_forced_shots():
    segs = [seg(1, 0, 30, "讲合同", must=True), seg(2, 40, 6, "讲合同", key=True)]
    res = select.select(segs, [{"name": "讲合同", "budget": 100}], {}, 12)
    assert _ids(res) == ["S001"]  # 必留已超目标，非必留镜头一个都不该留


def test_trim_still_keeps_one_shot_without_must_keep():
    segs = [seg(i, i * 10, 8, "讲合同") for i in range(1, 4)]
    res = select.select(segs, [{"name": "讲合同", "budget": 100}], {}, 2)
    assert len(res["shots"]) == 1


def test_zero_length_must_keep_skipped_with_warning():
    segs = [seg(1, 5, 0, "讲合同", must=True), seg(2, 10, 6, "讲合同", must=True)]
    res = select.select(segs, TOPICS, {}, 60)
    assert "S001" not in _ids(res) and "S002" in _ids(res)
    assert all(s["dur"] > 0 for s in res["shots"])
    assert res["must_keep_ids"] == ["S002"] and res["must_keep_skipped"] == ["S001"]
    assert any("S001" in w for w in res["warnings"])


def test_run_warns_when_legacy_topics_cannot_be_reallocated(tmp_path):
    scored = {"target": 30, "topics": [{"name": "讲合同", "budget": 20}],
              "segments": [seg(1, 0, 6, "讲合同")]}
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    res = select.run(sp, tmp_path / "a.json", tmp_path, target=300)
    assert any(select.BUDGET_LEGACY_WARNING in w for w in res["warnings"])


def test_summary_includes_warnings_and_missing_topics():
    sel = {"total": 1, "target": 2, "must_keep_total": 0, "over_target": False,
           "suggested_target": None, "warnings": ["w"], "missing_must_topics": ["讲合同"],
           "over_target_warning": None, "shots": [{"x": 1}]}
    got = select.summary(sel)
    assert got["warnings"] == ["w"] and got["missing_must_topics"] == ["讲合同"]
    assert "shots" not in got


def test_describe_missing_from_selection_says_reselect():
    missing = [seg(1, 70, 6, "讲合同", must=True, text="九千八")]
    assert "在分镜表里加回" in select.describe_missing(missing)
    msg = select.describe_missing(missing, from_selection=True)
    assert "重新选段" in msg and "在分镜表里加回" not in msg and "01:10" in msg


# ---------------------------------------------------------------- M8：KI-23 匹配不上要说出来
def _has(res, *parts):
    return any(all(p in w for p in parts) for w in res["warnings"])


def test_unmatched_must_line_warned():
    res = select.select([seg(1, 0, 6, "讲合同")], TOPICS, {"must_lines": ["不存在的原话"]}, 60)
    assert _has(res, "不存在的原话", "找不到")


def test_too_short_must_line_warned():
    segs = [seg(1, 0, 6, "讲合同"), seg(2, 20, 1.0, "聊吃饭", text="退费", level=1)]
    res = select.select(segs, TOPICS, {"must_lines": ["退费"]}, 60)
    assert _has(res, "退费", "不足")
    assert "S002" not in [s["segment_id"] for s in res["shots"]]


def test_matched_must_line_no_warning():
    segs = [seg(1, 0, 6, "讲合同"), seg(2, 20, 5, "聊吃饭", text="不白学吗", level=1)]
    res = select.select(segs, TOPICS, {"must_lines": ["不白学吗"]}, 60)
    assert not _has(res, "不白学吗")
    assert "S002" in [s["segment_id"] for s in res["shots"]]


def test_must_line_already_selected_not_warned():
    segs = [seg(1, 0, 6, "讲合同", text="合同签了"), seg(2, 20, 6, "聊吃饭")]
    res = select.select(segs, TOPICS, {"must_lines": ["合同签了"]}, 60)
    assert not _has(res, "合同签了")


def test_unmatched_must_topic_warned():
    res = select.select([seg(1, 0, 6, "讲合同")], TOPICS, {"must_topics": ["完全无关的内容"]}, 60)
    assert _has(res, "完全无关的内容")
    ok = select.select([seg(1, 0, 6, "讲合同")], TOPICS, {"must_topics": ["讲合同"]}, 60)
    assert ok["warnings"] == []


QUESTIONS = {"questions": [
    {"id": "q1", "type": "single", "options": [
        {"label": "合同全额", "rule": {"kind": "must_topics", "value": ["讲合同"]}}]},
    {"id": "q2", "type": "multi", "options": [
        {"label": "签字收尾", "rule": {"kind": "ending", "value": "sign"}}]},
]}


def test_unknown_answer_label_reported():
    rules = select._rules({"q1": "旧选项", "q2": ["签字收尾", "旧多选", ""], "q3": None}, QUESTIONS)
    assert rules["ignored_answers"] == ["旧选项", "旧多选"]
    assert rules["ending"] == "sign"


def test_ignored_answers_become_warnings():
    res = select.select([seg(1, 0, 6, "讲合同")], TOPICS, {"ignored_answers": ["旧选项"]}, 60)
    assert _has(res, "旧选项", "不在当前的决策问题里")


def test_run_reports_unmatched_must_line(tmp_path):
    sp = tmp_path / "segments_scored.json"
    sp.write_text(json.dumps({"segments": [seg(1, 0, 6, "讲合同")], "topics": TOPICS, "target": 60},
                             ensure_ascii=False), encoding="utf-8")
    res = select.run(sp, tmp_path / "none.json", tmp_path, calibration={"must_lines": "推费"})
    assert _has(res, "推费", "找不到")
    saved = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert any("推费" in w for w in saved["warnings"])
