import json

from pipeline import questions


TOPICS = [{"name": "讲解合同退费条款"}, {"name": "建议选养生美体"}, {"name": "指导签合同与缴费"}]


class Fake:
    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, **kw):
        return self.payload


def good_payload():
    return {"questions": [
        {"id": "q1", "text": "主角是谁？", "type": "single", "options": [
            {"label": "老师", "effect": "老师镜头占比更高",
             "rule": {"kind": "focus", "value": "老师"}},
            {"label": "妈妈", "effect": "家长视角为主",
             "rule": {"kind": "focus", "value": "妈妈"}}]},
        {"id": "q2", "text": "必须覆盖哪些？", "type": "multi", "options": [
            {"label": "合同条款", "effect": "强制覆盖",
             "rule": {"kind": "must_topics", "value": ["讲解合同退费条款"]}},
            {"label": "课程价格", "effect": "强制覆盖",
             "rule": {"kind": "must_topics", "value": ["不存在的名"]}},
            {"label": "签约缴费", "effect": "强制覆盖",
             "rule": {"kind": "must_topics", "value": ["指导签合同与缴费"]}}]},
        {"id": "q3", "text": "结尾？", "type": "single", "options": [
            {"label": "签字", "effect": "动作收尾", "rule": {"kind": "ending", "value": "sign"}},
            {"label": "出门", "effect": "离开收尾", "rule": {"kind": "ending", "value": "leave"}}]},
    ]}


def test_normalize_drops_invalid_topic_refs():
    res = questions._normalize(good_payload(), TOPICS)
    q2 = res["questions"][1]
    labels = [o["label"] for o in q2["options"]]
    assert labels == ["合同条款", "签约缴费"]  # 引用了不存在话题的选项被丢弃
    assert res["fallback"] is False


def test_normalize_requires_three_questions():
    payload = {"questions": good_payload()["questions"][:2]}
    try:
        questions._normalize(payload, TOPICS)
    except ValueError as exc:
        assert "不足 3 个" in str(exc)
    else:
        raise AssertionError("应当抛错")


def test_fallback_has_three_questions_and_valid_rules():
    fb = questions.fallback(TOPICS, [{"text": "九千八", "key_info": True}])
    assert fb["fallback"] is True
    assert len(fb["questions"]) == 3
    for q in fb["questions"]:
        assert 2 <= len(q["options"]) <= 4
        for o in q["options"]:
            assert o["rule"]["kind"] in questions.KINDS


def test_run_falls_back_on_error(tmp_path):
    summary = {"summary": "x", "key_points": []}
    scored = {"topics": TOPICS, "segments": [{"id": "S001", "key_info": True,
                                              "text": "九千八", "start": 1}]}
    sp, cp = tmp_path / "s.json", tmp_path / "c.json"
    sp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    cp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")

    class Boom:
        def chat_json(self, *a, **k):
            raise RuntimeError("down")

    out = tmp_path / "q.json"
    res = questions.run(sp, cp, out, client=Boom())
    assert res["fallback"] is True and out.exists()


def test_run_writes_questions(tmp_path):
    summary = {"summary": "x", "key_points": [{"text": "九千八"}]}
    scored = {"topics": TOPICS, "segments": []}
    sp, cp = tmp_path / "s.json", tmp_path / "c.json"
    sp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    cp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "q.json"
    res = questions.run(sp, cp, out, client=Fake(good_payload()))
    assert len(res["questions"]) == 3 and out.exists()
