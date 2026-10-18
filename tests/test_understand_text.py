import json
import re

from pipeline import understand_text as ut


class FakeClient:
    model = "fake"

    def __init__(self, *, fail_batches=(), topic_name="讲解合同"):
        self.calls = 0
        self.annotate_calls = 0
        self.fail_batches = set(fail_batches)
        self.topic_name = topic_name

    def chat_json(self, system, user, **kw):
        self.calls += 1
        ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
        if "归并成" in user:  # 话题分段
            half = len(ids) // 2
            return {"topics": [
                {"name": "开场寒暄", "segment_ids": ids[:half]},
                {"name": self.topic_name, "segment_ids": ids[half:]},
            ]}
        # 逐句标注
        idx = self.annotate_calls
        self.annotate_calls += 1
        if idx in self.fail_batches:
            from pipeline.llm import LLMError
            raise LLMError("mock failure")
        return {"segments": [
            {"id": i, "info_type": "金额价格", "key_info": i.endswith("1"),
             "entities": ["九千八"], "reason": "含金额"}
            for i in ids
        ]}


def make_segments(n=10):
    return [{"id": f"S{i:03d}", "start": i * 2.0, "end": i * 2.0 + 1.5,
             "text": f"第{i}句内容", "speaker": "1"} for i in range(1, n + 1)]


def test_run_merges_topics_and_annotations(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(6)}), encoding="utf-8")
    out = tmp_path / "text.json"
    res = ut.run(sp, out, client=FakeClient())
    assert out.exists()
    assert [t["name"] for t in res["topics"]] == ["开场寒暄", "讲解合同"]
    assert res["segments"][0]["topic"] == "开场寒暄"
    assert res["segments"][0]["info_type"] == "金额价格"
    assert any(s["key_info"] for s in res["segments"])


def test_batching_splits_calls(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(90)}), encoding="utf-8")
    client = FakeClient()
    ut.run(sp, tmp_path / "o.json", client=client, batch=40)
    assert client.calls == 1 + 3  # 1 次话题 + 3 批标注


def test_missing_segments_fall_back_to_last_topic(tmp_path):
    class Partial(FakeClient):
        def chat_json(self, system, user, **kw):
            ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
            if "归并成" in user:
                return {"topics": [{"name": "只有前半", "segment_ids": ids[:2]}]}
            return {"segments": []}

    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(5)}), encoding="utf-8")
    res = ut.run(sp, tmp_path / "o.json", client=Partial())
    covered = {i for t in res["topics"] for i in t["segment_ids"]}
    assert covered == {f"S{i:03d}" for i in range(1, 6)}


def test_failed_batch_recorded_but_others_kept(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    res = ut.run(sp, tmp_path / "o.json", client=FakeClient(fail_batches={0}), batch=40)
    assert res["failures"], "失败批次应被记录"
    assert any(s["info_type"] == "金额价格" for s in res["segments"])


class MergeClient(FakeClient):
    def chat_json(self, system, user, **kw):
        if "合并成不超过" in user:
            self.calls += 1
            return {"groups": [{"name": "合并后A", "indexes": [0, 1, 2]},
                               {"name": "合并后B", "indexes": [3]}]}
        return super().chat_json(system, user, **kw)


def test_topics_merged_via_llm_when_over_limit(tmp_path):
    class ManyTopics(MergeClient):
        def chat_json(self, system, user, **kw):
            if "归并成" in user:
                ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
                return {"topics": [{"name": f"t{i}", "segment_ids": [sid]}
                                   for i, sid in enumerate(ids)]}
            return super().chat_json(system, user, **kw)

    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(8)}), encoding="utf-8")
    res = ut.run(sp, tmp_path / "o.json", client=ManyTopics())
    assert len(res["topics"]) <= 15
    assert {i for t in res["topics"] for i in t["segment_ids"]} == {
        f"S{i:03d}" for i in range(1, 9)}


def test_topics_capped_to_15():
    topics = [{"name": f"t{i}", "segment_ids": [f"S{i:03d}"]} for i in range(1, 26)]
    capped = ut._cap_topics(topics, max_n=15)
    assert len(capped) == 15
    assert sum(len(t["segment_ids"]) for t in capped) == 25


def test_large_topic_split_by_time():
    topics = [{"name": "大话题", "segment_ids": [f"S{i:03d}" for i in range(1, 31)]}]
    parts = ut._split_large(topics, max_segments=10)
    assert len(parts) == 3
    assert parts[0]["name"].endswith("(1/3)")
    flat = [i for p in parts for i in p["segment_ids"]]
    assert flat == [f"S{i:03d}" for i in range(1, 31)]
