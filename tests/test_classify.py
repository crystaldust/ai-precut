import json

import pytest

from pipeline import classify


def seg(i, start, dur=6.0, **kw):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur,
            "text": kw.pop("text", "这是一句话"), **kw}


def test_key_info_always_usable():
    res = classify.classify([seg(1, 0, key_info=True, info_type="事实陈述",
                                 entities=["九千八"], topic="讲解合同")])
    s = res["segments"][0]
    assert s["level"] == 3
    assert "关键信息" in s["level_reason"]


def test_hard_info_types_usable():
    for t in ("金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"):
        res = classify.classify([seg(1, 0, info_type=t)])
        assert res["segments"][0]["level"] == 3, t


def test_chitchat_is_waste():
    res = classify.classify([seg(1, 0, info_type="闲聊寒暄")])
    assert res["segments"][0]["level"] == 1


def test_short_silent_segment_is_waste():
    res = classify.classify([seg(1, 0, dur=2.0, info_type="事实陈述")])
    assert res["segments"][0]["level"] == 1


def test_must_topic_becomes_pending():
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述", topic="讲解合同条款")])
    assert res["segments"][0]["level"] == 2
    assert "必留话题" in res["segments"][0]["level_reason"]


def test_loud_emphasis_usable():
    res = classify.classify([seg(1, 0, dur=6, info_type="事实陈述")],
                            {"S001": {"rel_db": 5.2}})
    assert res["segments"][0]["level"] == 3
    assert "音量突出" in res["segments"][0]["level_reason"]


def test_non_must_pending_capped_by_ratio():
    """GL-09：旧版用必留话题「讲解合同」断言降级，固化了缺陷；改用非必留话题。"""
    segs = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="闲聊日常") for i in range(1, 61)]
    res = classify.classify(segs)
    limit = max(10, int(60 * classify.MAX_PENDING_RATIO))
    assert res["summary"]["pending"] == limit
    assert res["pending"] == {"limit": limit, "demoted": 60 - limit}
    assert res["warnings"] == []


def test_must_topic_pending_never_demoted():
    segs = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="讲解合同") for i in range(1, 61)]
    res = classify.classify(segs)
    assert res["summary"]["pending"] == 60
    assert res["pending"]["demoted"] == 0
    assert res["warnings"] and "不自动降级" in res["warnings"][0]


def test_over_limit_demotes_only_non_must():
    must = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="讲解合同") for i in range(1, 31)]
    other = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="闲聊日常") for i in range(31, 61)]
    res = classify.classify(must + other)
    lv = {(s["topic"], s["level"]) for s in res["segments"]}
    assert ("讲解合同", 1) not in lv and ("闲聊日常", 2) not in lv


def test_key_ratio_must_topic_also_protected():
    key = [seg(i, i * 10, key_info=True, topic="建议选养生") for i in range(1, 21)]
    pend = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="建议选养生") for i in range(21, 61)]
    assert classify.classify(key + pend)["summary"]["pending"] == 40


def test_annotation_failed_becomes_pending_with_reason():
    s = classify.classify([seg(1, 0, dur=2.0, annotation_failed=True, info_type="")])["segments"][0]
    assert s["level"] == 2 and "标注失败" in s["level_reason"]


def test_annotation_failed_not_demoted_when_over_limit():
    segs = [seg(i, i * 10, dur=8, annotation_failed=True, topic="闲聊日常") for i in range(1, 61)]
    assert classify.classify(segs)["summary"]["pending"] == 60


def test_loud_annotation_failed_segment_still_usable():
    res = classify.classify([seg(1, 0, dur=6, annotation_failed=True)], {"S001": {"rel_db": 5.0}})
    assert res["segments"][0]["level"] == 3


DARK = {"S001": {"flags": ["dark"]}}


def test_dark_must_topic_pending_stays_pending():  # GL-24
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述", topic="讲解合同")],
                            visual_by_id=DARK)
    s = res["segments"][0]
    assert s["level"] == 2 and "画面过暗" in s["level_reason"]


def test_dark_annotation_failed_stays_pending():  # GL-24
    res = classify.classify([seg(1, 0, dur=8, annotation_failed=True)], visual_by_id=DARK)
    assert res["segments"][0]["level"] == 2


def test_dark_non_must_pending_still_waste():
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述", topic="闲聊日常")],
                            visual_by_id=DARK)
    assert res["segments"][0]["level"] == 1


def test_dark_usable_unchanged():
    res = classify.classify([seg(1, 0, key_info=True, topic="闲聊日常")], visual_by_id=DARK)
    assert res["segments"][0]["level"] == 3


def test_classify_does_not_mutate_input():
    segs = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="闲聊日常") for i in range(1, 61)]
    before = json.dumps(segs, ensure_ascii=False, sort_keys=True)
    classify.classify(segs, visual_by_id=DARK)
    assert json.dumps(segs, ensure_ascii=False, sort_keys=True) == before


def test_topic_stats_and_budget():
    segs = [seg(1, 0, key_info=True, topic="讲解合同"),
            seg(2, 10, key_info=True, topic="讲解合同")]
    res = classify.classify(segs)
    topic = res["topics"][0]
    assert topic["must"] is True
    assert topic["usable_dur"] == 12.0
    assert topic["budget"] >= 12


def test_run_reads_audio_and_writes_json(tmp_path):
    text = {"topics": [{"name": "讲解合同", "segment_ids": ["S001"]}],
            "segments": [seg(1, 0, info_type="事实陈述")]}
    audio = {"segments": [{"id": "S001", "signals": {"rel_db": 9.0}}]}
    tp, ap = tmp_path / "t.json", tmp_path / "a.json"
    tp.write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
    ap.write_text(json.dumps(audio, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "s.json"
    res = classify.run(tp, ap, out)
    assert out.exists() and res["segments"][0]["level"] == 3


def test_budget_allocated_within_total_and_capped():
    topics = [
        {"name": "讲解合同", "must": True, "usable_dur": 60, "budget": 0},
        {"name": "谈价格", "must": True, "usable_dur": 20, "budget": 0},
        {"name": "聊吃饭", "must": False, "usable_dur": 40, "budget": 0},
    ]
    out = classify.allocate_budget(topics, total=300, cap_ratio=0.3)
    total_budget = sum(t["budget"] for t in out)
    assert total_budget <= 300 * 1.05
    assert all(t["budget"] <= 300 * 0.3 for t in out)
    assert out[0]["budget"] > out[1]["budget"]  # 可用时长更多的分到更多
    assert out[2]["budget"] > 0


def test_zero_usable_topic_gets_zero_budget():
    topics = [{"name": "闲聊", "must": False, "usable_dur": 0, "budget": 0}]
    out = classify.allocate_budget(topics, total=175)
    assert out[0]["budget"] == 0


def test_topic_with_high_key_info_ratio_is_must():
    segs = [seg(1, 0, key_info=True, topic="建议选养生"),
            seg(2, 10, key_info=True, topic="建议选养生"),
            seg(3, 20, key_info=False, topic="建议选养生"),
            seg(4, 30, key_info=False, topic="建议选养生")]
    res = classify.classify(segs)
    topic = next(t for t in res["topics"] if t["name"] == "建议选养生")
    assert topic["must"] is True  # 50% 句子是关键信息，按内容判定为必留


def test_dark_does_not_promote_waste_in_must_topic():
    """保护只防「降级」：本来就是废片的句子，画面过暗也不能被抬成待定。"""
    segs = [seg(1, 0, key_info=True, topic="建议选养生"),
            seg(2, 10, dur=8, info_type="闲聊寒暄", topic="建议选养生")]
    res = classify.classify(segs, visual_by_id={"S002": {"flags": ["dark"]}})
    assert res["segments"][1]["level"] == 1


# ---------------------------------------------------------------- M2 审查：未完成的标注
def _write_text(tmp_path, **extra):
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps({"segments": [seg(1, 0, dur=8, info_type="事实陈述", topic="闲聊日常"),
                                           seg(2, 10, dur=8, info_type="", topic="闲聊日常")],
                              **extra}, ensure_ascii=False), encoding="utf-8")
    return tp


def test_run_refuses_incomplete_text(tmp_path):
    tp = _write_text(tmp_path, complete=False)
    with pytest.raises(classify.TextIncomplete, match="标注未完成"):
        classify.run(tp, None, tmp_path / "s.json")
    assert not (tmp_path / "s.json").exists()


def test_run_marks_legacy_failures_as_annotation_failed(tmp_path):
    tp = _write_text(tmp_path, failures=[{"ids": ["S002"], "error": "x"}])
    res = classify.run(tp, None, tmp_path / "s.json")
    s2 = res["segments"][1]
    assert s2["annotation_failed"] is True and s2["level"] == 2
    assert any("1 句" in w and "标注失败" in w for w in res["warnings"])


# ---------------------------------------------------------------- M8：KI-21 可选输入缺失 / 损坏
def test_run_warns_when_audio_file_missing(tmp_path):
    tp = _write_text(tmp_path)
    res = classify.run(tp, tmp_path / "none.json", tmp_path / "s.json")
    assert any("声音特征" in w for w in res["warnings"])


def test_run_warns_when_visual_file_missing(tmp_path):
    tp = _write_text(tmp_path)
    res = classify.run(tp, None, tmp_path / "s.json", visual_path=tmp_path / "none.json")
    assert any("画面质量" in w for w in res["warnings"])


def test_run_without_optional_paths_has_no_missing_warning(tmp_path):
    res = classify.run(_write_text(tmp_path), None, tmp_path / "s.json")
    assert not any("声音特征" in w or "画面质量" in w for w in res["warnings"])


def test_run_corrupt_audio_raises_corrupt_json(tmp_path):
    from pipeline import schema
    ap = tmp_path / "segments_audio.json"
    ap.write_text("{坏", encoding="utf-8")
    with pytest.raises(schema.CorruptJSON, match="segments_audio.json"):
        classify.run(_write_text(tmp_path), ap, tmp_path / "s.json")
    assert not (tmp_path / "s.json").exists()


# ================================================================ M6 · 成片质量
def test_scored_segments_carry_audio_signals():  # KI-06
    res = classify.classify([seg(1, 0)], {"S001": {"rel_db": 3.0}})
    assert res["segments"][0]["signals"]["rel_db"] == 3.0
    assert classify.classify([seg(1, 0)])["segments"][0]["signals"] == {}


def test_attach_signals_backfills_without_mutation():  # KI-06
    segs = [seg(1, 0)]
    out = classify.attach_signals(segs, {"S001": {"rel_db": 2.0}})
    assert out[0]["signals"] == {"rel_db": 2.0} and "signals" not in segs[0]


def test_load_audio_signals(tmp_path):
    assert classify.load_audio_signals(tmp_path / "none.json") == {}
    ap = tmp_path / "a.json"
    ap.write_text(json.dumps({"segments": [{"id": "S001", "signals": {"rel_db": 1}}]}), encoding="utf-8")
    assert classify.load_audio_signals(ap) == {"S001": {"rel_db": 1}}


def test_ratio_must_topic_protects_short_plain_segment():  # KI-58
    segs = [seg(i, i * 10, key_info=True, topic="安排宿舍") for i in range(1, 5)]
    segs.append(seg(9, 90, dur=4, info_type="事实陈述", topic="安排宿舍"))
    res = classify.classify(segs)
    s = res["segments"][-1]
    assert s["level"] == 2 and "必留话题" in s["level_reason"]
    assert next(t for t in res["topics"] if t["name"] == "安排宿舍")["must"] is True


def test_must_topic_words_from_config():  # KI-07
    one = [seg(1, 0, dur=8, info_type="事实陈述", topic="安排宿舍")]
    assert classify.classify(one, must_topic={"words": ["宿舍"]})["topics"][0]["must"] is True
    assert classify.classify(one)["topics"][0]["must"] is False
    course = [seg(1, 0, key_info=True, topic="建议选养生美体课程")] + [
        seg(i, i * 10, dur=8, info_type="事实陈述", topic="建议选养生美体课程") for i in range(2, 6)]
    assert classify.classify(course)["topics"][0]["must"] is False  # 「课程」不再是必留词


def test_min_key_hits_required_for_ratio_rule():  # KI-07
    res = classify.classify([seg(1, 0, key_info=True, topic="闲聊日常")])
    assert res["topics"][0]["must"] is False


def test_must_topic_config_tolerates_bad_values():
    cfg = classify.must_topic_config({"words": "宿舍", "key_ratio": "x", "min_key_hits": None})
    assert cfg == classify.must_topic_config(None)
    assert classify.must_topic_config({"words": ["宿舍", 3, ""]})["words"] == ("宿舍",)


def test_run_passes_must_topic_config(tmp_path):  # KI-07
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps({"segments": [seg(1, 0, dur=8, info_type="事实陈述", topic="安排宿舍"),
                                           seg(2, 10, key_info=True, topic="闲聊日常")]},
                             ensure_ascii=False), encoding="utf-8")
    res = classify.run(tp, None, tmp_path / "s.json",
                       must_topic={"words": ["宿舍"], "key_ratio": 0.9, "min_key_hits": 1})
    must = {t["name"]: t["must"] for t in res["topics"]}
    assert must == {"安排宿舍": True, "闲聊日常": True}


def test_interrupt_proxy_on_long_split_segment_not_usable():  # KI-08
    res = classify.classify([seg(1, 0, dur=34.5, info_type="事实陈述")],
                            {"S001": {"interrupt": True, "duration": 34.5, "rel_db": 0.5}})
    assert res["segments"][0]["level"] != 3


def test_interrupt_proxy_with_raised_voice_usable():  # KI-08
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述")],
                            {"S001": {"interrupt": True, "duration": 8, "rel_db": 1.5}})
    s = res["segments"][0]
    assert s["level"] == 3 and s["level_reason"] == "出现抢话/被打断"


def test_real_overlap_usable():  # KI-08
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述")], {"S001": {"overlap": True}})
    assert res["segments"][0]["level"] == 3


def test_artifact_schema_stamped(tmp_path):  # KI-37
    tp = _write_text(tmp_path)
    classify.run(tp, None, tmp_path / "s.json")
    from pipeline import schema
    assert json.loads((tmp_path / "s.json").read_text())["artifact_schema"] == schema.ARTIFACT_SCHEMA


# ---------------------------------------------------------------- 画面理解开启（第 4 阶段）
def vis(issues=(), match="一致", key=False, why="合同特写"):
    return {"visual": {"desc": "两人", "text_on_screen": "", "objects": [], "issues": list(issues)},
            "visual_match": match, "visual_key": key, "visual_reason": why}


def one(s, **kw):
    return classify.classify([s], **kw)["segments"][0]


def test_visual_key_lifts_pending_to_usable():
    s = one(seg(1, 0, dur=8, info_type="事实陈述", **vis(key=True)))
    assert s["level"] == 3 and s["level_reason"] == "画面可见关键信息：合同特写"


def test_visual_key_does_not_lift_when_frame_has_issue_or_is_dark():
    assert one(seg(1, 0, dur=8, info_type="事实陈述", **vis(["遮挡"], key=True)))["level"] == 2
    assert one(seg(1, 0, dur=8, info_type="事实陈述", **vis(key=True)), visual_by_id=DARK)["level"] != 3


def test_visual_key_does_not_lift_failed_annotation():
    s = one(seg(1, 0, dur=8, annotation_failed=True, **vis(key=True)))
    assert s["level"] == 2 and s["level_reason"] == classify.ANNOTATION_FAILED_REASON


@pytest.mark.parametrize("extra, said", [({"issues": ["背对镜头"]}, "画面：背对镜头；"),
                                         ({"match": "不一致"}, "画面：画面与对白不符；"),
                                         ({"issues": ["人物出画", "画面晃动"], "match": "不一致"},
                                          "画面：人物出画、画面晃动、画面与对白不符；")])
def test_visual_problem_drops_usable_to_pending_once(extra, said):
    s = one(seg(1, 0, dur=8, info_type="条款期限", **vis(**extra)))
    assert s["level"] == 2 and s["level_reason"] == said + "信息类型为条款期限"
    assert s["vision_demoted"] is True


def test_key_info_is_never_dropped_by_picture():
    s = one(seg(1, 0, key_info=True, entities=["九千八"], **vis(["背对镜头"], match="不一致")))
    assert s["level"] == 3 and "vision_demoted" not in s


def test_picture_never_drops_pending_or_waste():
    assert one(seg(1, 0, dur=8, info_type="事实陈述", **vis(["背对镜头"])))["level"] == 2
    assert one(seg(1, 0, info_type="闲聊寒暄", **vis(["背对镜头"])))["level"] == 1


def test_vision_demoted_pending_is_not_capped_to_waste():
    segs = [seg(i, i * 10, dur=8, info_type="条款期限", topic="闲聊日常", **vis(["背对镜头"])) for i in range(1, 61)]
    res = classify.classify(segs)
    assert res["summary"] == {"waste": 0, "pending": 60, "usable": 0} and res["pending"]["demoted"] == 0
    assert "因画面降为待定" in res["warnings"][0]


def test_vision_off_segments_get_no_vision_keys():
    s = one(seg(1, 0, dur=8, info_type="条款期限"))
    assert not {"vision_demoted", "visual_match"} & set(s)
    assert "visual_segments" not in classify.classify([seg(1, 0)])


def vseg(n, *, key=False, issues=(), failed=False):
    return {"id": f"V{n:03d}", "kind": "visual", "start": n * 100.0, "end": n * 100.0 + 12, "text": "",
            "label": "坐电梯下楼", "visual": {"desc": "", "text_on_screen": "", "objects": [], "issues": list(issues)},
            "visual_key": key, "visual_reason": "楼层显示", "annotation_failed": failed}


def test_visual_segments_judged_separately_from_counts():
    segs = [vseg(1), vseg(2, key=True), vseg(3, key=True, issues=["过暗"]), vseg(4, failed=True)]
    res = classify.classify([seg(1, 0, info_type="闲聊寒暄")], visual_segments=segs)
    got = [(v["id"], v["level"], v["level_reason"]) for v in res["visual_segments"]]
    assert got == [("V001", 2, classify.VISUAL_SEGMENT_REASON),
                   ("V002", 3, "画面可见关键信息：楼层显示"),
                   ("V003", 2, "画面片段：过暗"),
                   ("V004", 2, classify.VISUAL_SEGMENT_FAILED_REASON)]
    assert res["summary"] == {"waste": 1, "pending": 0, "usable": 0}
    assert [t["name"] for t in res["topics"]] == ["未归类"] and res["topics"][0]["count"] == 1


def test_classify_with_vision_does_not_mutate_input():
    segs = [seg(i, i * 10, dur=8, info_type="条款期限", **vis(["背对镜头"])) for i in range(1, 5)]
    vsegs = [vseg(1, key=True)]
    before = json.dumps([segs, vsegs], ensure_ascii=False, sort_keys=True)
    classify.classify(segs, visual_segments=vsegs)
    assert json.dumps([segs, vsegs], ensure_ascii=False, sort_keys=True) == before


def test_run_reads_visual_segments_from_text(tmp_path):
    text = {"complete": True, "topics": [], "segments": [seg(1, 0, info_type="条款期限", **vis(["遮挡"]))],
            "visual_segments": [vseg(1, key=True)]}
    (tmp_path / "t.json").write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
    res = classify.run(tmp_path / "t.json", None, tmp_path / "s.json")
    assert res["segments"][0]["level"] == 2 and res["visual_segments"][0]["level"] == 3
    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert saved["visual_segments"][0]["id"] == "V001"


def test_vision_demoted_dark_segment_stays_pending():
    """画面问题把可用降成待定后，本机「过暗」也不能再把它打成废片（审查 H1）。"""
    s = one(seg(1, 0, dur=8, info_type="金额价格", **vis(["遮挡"])), visual_by_id=DARK)
    assert s["level"] == 2 and s["level_reason"].startswith("画面过暗；画面：遮挡；")
    res = classify.classify([seg(1, 0, dur=8, info_type="金额价格", **vis(["遮挡"]))], visual_by_id=DARK)
    assert classify.picture_note(res) == " · 因画面降为待定 1"


@pytest.mark.parametrize("vision_on", [False, True])
def test_run_respects_current_vision_setting(tmp_path, vision_on):
    text = {"complete": True, "topics": [], "vision": {"timeline_key": "k"},
            "segments": [seg(1, 0, info_type="条款期限", **vis(["遮挡"]))], "visual_segments": [vseg(1)]}
    (tmp_path / "t.json").write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
    res = classify.run(tmp_path / "t.json", None, tmp_path / "s.json", vision="k" if vision_on else False)
    if vision_on:
        assert res["segments"][0]["level"] == 2 and "visual_segments" in res
    else:  # 关掉画面理解后单独跑 score：上次开启时留下的画面字段不能起作用
        assert res["segments"][0]["level"] == 3 and "visual_segments" not in res
        assert not {"visual", "visual_match", "visual_key", "visual_reason"} & set(res["segments"][0])


@pytest.mark.parametrize("made_with, now", [(None, "k"),        # 标注是关闭时做的
                                           ("old", "k"),       # 画面时间轴后来重做过
                                           ("k", "")])         # 整合结果不是最新的
def test_run_with_vision_on_but_text_not_for_current_timeline_raises(tmp_path, made_with, now):
    text = {"complete": True, "topics": [], "segments": [seg(1, 0, info_type="条款期限")]}
    if made_with:
        text = {**text, "vision": {"timeline_key": made_with}}
    (tmp_path / "t.json").write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(classify.TextIncomplete, match="画面理解"):
        classify.run(tmp_path / "t.json", None, tmp_path / "s.json", vision=now)
