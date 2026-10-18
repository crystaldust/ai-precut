import json

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


def test_pending_capped_by_ratio():
    segs = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="讲解合同") for i in range(1, 61)]
    res = classify.classify(segs)
    assert res["summary"]["pending"] <= int(60 * classify.MAX_PENDING_RATIO) + 1


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
