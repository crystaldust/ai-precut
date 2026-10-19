import json

from pipeline import summarize


def segs():
    return [
        {"id": "S001", "start": 10.0, "end": 20.0, "text": "一位母亲带女儿来报名",
         "key_info": False, "reason": ""},
        {"id": "S002", "start": 30.0, "end": 40.0, "text": "三门课程总共九千八",
         "key_info": True, "reason": "含金额"},
        {"id": "S003", "start": 50.0, "end": 60.0, "text": "找不到工作退学费",
         "key_info": True, "reason": "退费条款"},
    ]


class Fake:
    model = "fake"

    def __init__(self, payload=None, boom=False):
        self.payload, self.boom = payload, boom

    def chat_json(self, system, user, **kw):
        if self.boom:
            raise RuntimeError("boom")
        return self.payload


def write_inputs(tmp_path):
    text = {"topics": [{"name": "讲解合同", "duration": 60, "usable_dur": 30}],
            "segments": segs()}
    scored = {"summary": {}, "topics": text["topics"], "segments": segs()}
    tp, sp = tmp_path / "t.json", tmp_path / "s.json"
    tp.write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    return tp, sp


def test_normalizes_and_snaps_timestamps(tmp_path):
    payload = {"summary": "一位母亲带女儿到美业学校报名并签下九千八的合同",
               "key_points": [{"text": "总价九千八", "at": 33.7, "why": "核心金额"},
                              {"text": "退费承诺", "at": 48.0, "why": "风险保障"}],
               "cast": [{"name": "老师", "desc": "做美业十四年"}]}
    tp, sp = write_inputs(tmp_path)
    out = tmp_path / "o.json"
    res = summarize.run(tp, sp, out, client=Fake(payload))
    assert out.exists()
    assert res["fallback"] is False
    assert [p["at"] for p in res["key_points"]] == [30.0, 50.0]  # 吸附到最近关键句
    assert res["cast"][0]["name"] == "老师"


def test_summary_truncated_to_80(tmp_path):
    payload = {"summary": "很长的摘要" * 40, "key_points": [], "cast": []}
    tp, sp = write_inputs(tmp_path)
    res = summarize.run(tp, sp, tmp_path / "o.json", client=Fake(payload))
    assert len(res["summary"]) <= 80


def test_failure_falls_back(tmp_path):
    tp, sp = write_inputs(tmp_path)
    res = summarize.run(tp, sp, tmp_path / "o.json", client=Fake(boom=True))
    assert res["fallback"] is True
    assert res["summary"]
    assert len(res["key_points"]) == 2  # 来自 key_info 兜底


def test_empty_summary_triggers_fallback(tmp_path):
    tp, sp = write_inputs(tmp_path)
    res = summarize.run(tp, sp, tmp_path / "o.json",
                        client=Fake({"summary": "", "key_points": []}))
    assert res["fallback"] is True


def test_style_injected(tmp_path):
    class Rec(Fake):
        def __init__(self):
            super().__init__({"summary": "x", "key_points": [], "cast": []})
            self.users = []

        def chat_json(self, system, user, **kw):
            self.users.append(user)
            return super().chat_json(system, user, **kw)

    tp, sp = write_inputs(tmp_path)
    c = Rec()
    summarize.run(tp, sp, tmp_path / "o.json", client=c, style="剪辑偏好：情绪优先")
    assert "情绪优先" in c.users[0]


def test_model_passed_to_client(tmp_path, monkeypatch):  # M6 · KI-10
    made = []

    class Spy(Fake):
        def __init__(self, **kw):
            made.append(kw)
            super().__init__(payload={"summary": "一位母亲带女儿来报名", "key_points": [], "cast": []})
    monkeypatch.setattr(summarize, "DeepSeekClient", Spy)
    tp, sp = write_inputs(tmp_path)
    res = summarize.run(tp, sp, tmp_path / "o.json", model="deepseek-reasoner")
    assert made == [{"model": "deepseek-reasoner"}] and res["model"] == "deepseek-reasoner"
    summarize.run(tp, sp, tmp_path / "o2.json")
    assert made[-1] == {}
