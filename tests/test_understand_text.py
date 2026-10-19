import json
import re

import pytest

from pipeline import understand_text as ut


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(ut, "_sleep", lambda _s: None)


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
            return FakeClient.chat_json(self, system, user, **kw)  # 本测试只验证话题兜底

    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(5)}), encoding="utf-8")
    res = ut.run(sp, tmp_path / "o.json", client=Partial())
    covered = {i for t in res["topics"] for i in t["segment_ids"]}
    assert covered == {f"S{i:03d}" for i in range(1, 6)}


def test_failed_batch_retried_then_succeeds(tmp_path):
    """GL-09：旧断言「失败批次被记录、其余照常」固化了静默丢弃；现在先整批重试。"""
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    client = FakeClient(fail_batches={0})
    res = ut.run(sp, tmp_path / "o.json", client=client, batch=40)
    assert res["failures"] == [] and res["complete"] is True
    assert not any(s["annotation_failed"] for s in res["segments"])
    assert client.annotate_calls == 3  # 第 1 批失败 1 次 + 重试 1 次 + 第 2 批 1 次


class StubbornClient(FakeClient):
    """含指定 id 的批次永远失败 / 永远漏标指定 id，并附带一个编造的 id。"""

    def __init__(self, *, fail_if=(), omit=()):
        super().__init__()
        self.fail_if, self.omit = set(fail_if), set(omit)

    def chat_json(self, system, user, **kw):
        ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
        if "归并成" not in user and self.fail_if & set(ids):
            self.calls += 1
            self.annotate_calls += 1
            from pipeline.llm import LLMError
            raise LLMError("mock persistent failure")
        data = super().chat_json(system, user, **kw)
        if "segments" in data:
            data = {"segments": [x for x in data["segments"] if x["id"] not in self.omit]
                    + [{"id": "S999", "info_type": "金额价格", "key_info": True}]}
        return data


def test_persistent_failure_saves_then_raises(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(ut.AnnotationIncomplete) as exc:
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    assert exc.value.ids[0] == "S001" and len(exc.value.ids) == 40
    assert "只会重跑" in str(exc.value)
    assert not out.exists()  # 未完成的结果不写主文件
    saved = json.loads(ut.partial_path(out).read_text(encoding="utf-8"))  # 先落盘
    assert saved["complete"] is False and saved["input_hash"]
    flags = {s["id"]: s["annotation_failed"] for s in saved["segments"]}
    assert flags["S001"] is True and flags["S041"] is False


def test_rerun_only_reannotates_failed_segments(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(ut.AnnotationIncomplete):
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    first_topics = json.loads(ut.partial_path(out).read_text(encoding="utf-8"))["topics"]
    healthy = FakeClient()
    res = ut.run(sp, out, client=healthy, batch=40)
    assert res["complete"] is True and res["resumed"] is True
    assert healthy.calls == 1  # 不再做话题分段，只补 1 批（S001–S040）
    assert res["topics"] == first_topics  # 沿用上次的话题分段
    assert not any(s["annotation_failed"] for s in res["segments"])
    assert res["segments"][45]["info_type"] == "金额价格"  # 上次成功的标注保留


def test_rerun_with_changed_input_does_full_run(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(ut.AnnotationIncomplete):
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    healthy = FakeClient()
    ut.run(sp, out, client=healthy, batch=40, style="新偏好")  # 输入变了 → 不能复用旧结果
    assert healthy.calls == 1 + 2  # 1 次话题分段 + 2 批标注（全量）


def test_old_result_without_complete_flag_does_full_run(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(5)}), encoding="utf-8")
    out = tmp_path / "o.json"
    out.write_text(json.dumps({"topics": [], "segments": []}), encoding="utf-8")
    healthy = FakeClient()
    res = ut.run(sp, out, client=healthy)
    assert healthy.calls == 2 and res["resumed"] is False


def test_retry_count_bounded():
    client = StubbornClient(fail_if={"S001"})
    _, failures = ut.annotate(client, make_segments(5), batch=40)
    assert client.annotate_calls == ut.ANNOTATE_RETRIES + 1
    assert "mock persistent failure" in failures[0]["error"]


def test_missing_ids_rerequested_only_for_gaps():
    class OnceOmit(FakeClient):
        def __init__(self):
            super().__init__()
            self.listings = []

        def chat_json(self, system, user, **kw):
            self.listings.append(re.findall(r"^(S\d{3}) ", user, flags=re.M))
            data = super().chat_json(system, user, **kw)
            if self.annotate_calls == 1:
                data = {"segments": [x for x in data["segments"] if x["id"] != "S003"]}
            return data

    client = OnceOmit()
    result, failures = ut.annotate(client, make_segments(5), batch=40)
    assert failures == [] and "S003" in result and client.annotate_calls == 2
    assert client.listings[1] == ["S003"]  # 补问只问漏掉的句子


def test_permanently_missing_id_flagged_alone():
    result, failures = ut.annotate(StubbornClient(omit={"S003"}), make_segments(5), batch=40)
    assert [f["ids"] for f in failures] == [["S003"]] and "漏标" in failures[0]["error"]
    assert "S999" not in result  # 模型编造的 id 不进结果


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


def test_style_is_injected_into_annotate_prompt(tmp_path):
    class Recorder(FakeClient):
        def __init__(self):
            super().__init__()
            self.prompts = []

        def chat_json(self, system, user, **kw):
            self.prompts.append(user)
            return super().chat_json(system, user, **kw)

    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(5)}), encoding="utf-8")
    client = Recorder()
    ut.run(sp, tmp_path / "o.json", client=client, style="剪辑偏好：观众是准备报名的家长")
    assert any("准备报名的家长" in p for p in client.prompts)


# ---------------------------------------------------------------- M2 审查
class ShapeClient(FakeClient):
    """第一次标注返回错误形状（entities 是数字 / segments 不是列表），之后正常。"""

    def __init__(self, bad):
        super().__init__()
        self.bad = bad

    def chat_json(self, system, user, **kw):
        data = super().chat_json(system, user, **kw)
        if "segments" in data and self.annotate_calls == 1:
            return self.bad(data)
        return data


@pytest.mark.parametrize("bad", [
    lambda d: {"segments": [{**x, "entities": 5} for x in d["segments"]]},
    lambda d: {"segments": "oops"},
    lambda d: {"segments": [5, None]},
    lambda d: ["not", "a", "dict"],
])
def test_wrong_shape_is_retried_not_crash(bad):
    client = ShapeClient(bad)
    result, failures = ut.annotate(client, make_segments(5), batch=40, sleep=lambda _: None)
    assert failures == [] and len(result) == 5 and client.annotate_calls == 2


def test_fatal_status_not_retried_and_stops_later_batches():
    from pipeline.llm import LLMError

    class Unauthorized(FakeClient):
        def chat_json(self, system, user, **kw):
            self.annotate_calls += 1
            raise LLMError("HTTP 401: unauthorized", status=401)

    client = Unauthorized()
    _, failures = ut.annotate(client, make_segments(90), batch=40, sleep=lambda _: None)
    assert client.annotate_calls == 1  # 鉴权错误重试没用，后面的批次也不用再试
    assert sorted(i for f in failures for i in f["ids"]) == [f"S{i:03d}" for i in range(1, 91)]
    assert "401" in failures[0]["error"]


def test_retry_backoff_uses_injected_sleep():
    slept = []
    ut.annotate(StubbornClient(fail_if={"S001"}), make_segments(5), batch=40,
                sleep=slept.append)
    assert slept == list(ut.ANNOTATE_BACKOFF[:ut.ANNOTATE_RETRIES])


def _paths(tmp_path, n=50):
    sp = tmp_path / "segments_text_src.json"
    sp.write_text(json.dumps({"segments": make_segments(n)}), encoding="utf-8")
    return sp, tmp_path / "segments_text.json"


def test_incomplete_rerun_does_not_clobber_complete_main_file(tmp_path):
    sp, out = _paths(tmp_path)
    good = ut.run(sp, out, client=FakeClient(), batch=40)
    with pytest.raises(ut.AnnotationIncomplete):
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40, style="新偏好")
    assert json.loads(out.read_text(encoding="utf-8"))["segments"] == good["segments"]
    partial = ut.partial_path(out)
    assert json.loads(partial.read_text(encoding="utf-8"))["complete"] is False
    assert ut.is_incomplete(out) is True


def test_resume_uses_partial_then_replaces_main_and_removes_partial(tmp_path):
    sp, out = _paths(tmp_path)
    with pytest.raises(ut.AnnotationIncomplete):
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    assert not out.exists()
    healthy = FakeClient()
    res = ut.run(sp, out, client=healthy, batch=40)
    assert res["resumed"] is True and healthy.calls == 1
    assert json.loads(out.read_text(encoding="utf-8"))["complete"] is True
    assert not ut.partial_path(out).exists() and ut.is_incomplete(out) is False


def test_is_incomplete_detects_legacy_failures(tmp_path):
    out = tmp_path / "segments_text.json"
    out.write_text(json.dumps({"segments": [], "failures": [{"ids": ["S001"]}]}),
                   encoding="utf-8")
    assert ut.is_incomplete(out) is True
    out.write_text(json.dumps({"segments": [], "failures": []}), encoding="utf-8")
    assert ut.is_incomplete(out) is False


# ================================================================ M6 · KI-09 话题分段分窗 + 脏输出
class TopicRecorder(FakeClient):
    def __init__(self, replies=None):
        super().__init__()
        self.topic_kw, self.replies = [], list(replies or [])

    def chat_json(self, system, user, **kw):
        if "归并成" in user:
            self.topic_kw.append(kw)
            if self.replies:
                self.calls += 1
                return self.replies.pop(0)
        return super().chat_json(system, user, **kw)


def test_topic_segmentation_windows_long_input():
    segs = [{"id": f"S{i:03d}", "start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"第{i}句"}
            for i in range(1, 301)]
    client = TopicRecorder()
    topics = ut.segment_topics(client, segs)
    assert len(client.topic_kw) == 3
    assert all(kw["max_tokens"] >= ut.TOPIC_MAX_TOKENS for kw in client.topic_kw)
    flat = [i for t in topics for i in t["segment_ids"]]
    assert sorted(flat) == [s["id"] for s in segs] and len(flat) == len(set(flat))


def test_single_window_prompt_keeps_8_to_15():
    seen = []

    class C(FakeClient):
        def chat_json(self, system, user, **kw):
            seen.append(user)
            return super().chat_json(system, user, **kw)
    ut.segment_topics(C(), make_segments(10))
    assert "8–15" in seen[0]


def test_topic_window_retried_on_bad_shape():
    client = TopicRecorder(replies=[["x"]])
    topics = ut.segment_topics(client, make_segments(10))
    assert len(client.topic_kw) == 2
    assert {i for t in topics for i in t["segment_ids"]} == {s["id"] for s in make_segments(10)}


def test_topic_window_persistent_failure_raises_llmerror(tmp_path):
    from pipeline.llm import LLMError
    client = TopicRecorder(replies=[{"topics": "oops"}] * 5)
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(10)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(LLMError) as exc:
        ut.run(sp, out, client=client)
    assert "话题分段" in str(exc.value) and "1/1" in str(exc.value)
    assert len(client.topic_kw) == ut.TOPIC_RETRIES + 1
    assert not out.exists()


def test_topic_window_fatal_error_not_retried():
    from pipeline.llm import LLMError

    class Fatal(FakeClient):
        def chat_json(self, system, user, **kw):
            self.calls += 1
            raise LLMError("鉴权失败", status=401)
    client = Fatal()
    with pytest.raises(LLMError, match="话题分段"):
        ut.segment_topics(client, make_segments(5))
    assert client.calls == 1


def test_topic_items_non_dict_and_non_list_ids_skipped():
    client = TopicRecorder(replies=[{"topics": [5, {"name": "a", "segment_ids": "S001"},
                                                {"name": "b", "segment_ids": ["S001", 7]}]}])
    topics = ut.segment_topics(client, make_segments(3))
    assert topics[0]["name"] == "b" and topics[0]["segment_ids"][0] == "S001"
    assert {i for t in topics for i in t["segment_ids"]} == {"S001", "S002", "S003"}
    assert len(topics) == 1  # 漏掉的句子兜底并入最后一个话题


@pytest.mark.parametrize("raw,expected", [("false", False), ("False", False), ("否", False), ("", False),
                                          (None, False), (0, False), ("true", True), (True, True),
                                          (1, True), ("是", True)])
def test_key_info_string_false_is_false(raw, expected):
    assert ut._normalize({"info_type": "事实陈述", "key_info": raw})["key_info"] is expected


def test_unknown_info_type_defaults():
    assert ut._normalize({"info_type": "价格"})["info_type"] == "事实陈述"
    assert ut._normalize({"info_type": "金额价格"})["info_type"] == "金额价格"


@pytest.mark.parametrize("data", [["x"], {"groups": "x"}, {"groups": [3]}, {"groups": [{"indexes": "0"}]}])
def test_merge_topics_non_dict_returns_none(data):
    class C:
        def chat_json(self, *a, **k):
            return data
    topics = [{"name": f"t{i}", "segment_ids": [f"S{i:03d}"]} for i in range(3)]
    assert ut._merge_topics_via_llm(C(), topics) is None


# ================================================================ M6 · KI-10 --model 真正传给客户端
def test_model_passed_to_client(tmp_path, monkeypatch):
    made = []

    class Spy(FakeClient):
        def __init__(self, **kw):
            made.append(kw)
            super().__init__()
    monkeypatch.setattr(ut, "DeepSeekClient", Spy)
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(3)}), encoding="utf-8")
    res = ut.run(sp, tmp_path / "o.json", model="deepseek-reasoner")
    assert made == [{"model": "deepseek-reasoner"}] and res["model"] == "deepseek-reasoner"
    ut.run(sp, tmp_path / "o2.json")
    assert made[-1] == {}


# ================================================================ M6 审查修复：尾窗并入 + 跨窗同名合并
def _many(n):
    return [{"id": f"S{i:03d}", "start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"第{i}句"}
            for i in range(1, n + 1)]


def test_tiny_trailing_window_folded_into_previous():
    client = TopicRecorder()
    ut.segment_topics(client, _many(130))
    assert len(client.topic_kw) == 1


def test_same_named_topics_merged_across_window_edge():
    class Same(TopicRecorder):
        def chat_json(self, system, user, **kw):
            if "归并成" in user:
                self.topic_kw.append(kw)
                return {"topics": [{"name": "同一话题", "segment_ids": re.findall(r"^(S\d{3}) ", user, flags=re.M)}]}
            return super().chat_json(system, user, **kw)
    client = Same()
    topics = ut.segment_topics(client, _many(250))
    assert len(client.topic_kw) == 2
    n = len(topics)
    assert all(t["name"].endswith(f"/{n})") for t in topics)


# ---------------------------------------------------------------- KI-32：输入没变就不重新标注
def _seg_file(tmp_path, n=6):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(n)}), encoding="utf-8")
    return sp


def test_complete_unchanged_input_is_not_reannotated(tmp_path):
    sp, out = _seg_file(tmp_path), tmp_path / "text.json"
    first = ut.run(sp, out, client=FakeClient())
    again = FakeClient()
    res = ut.run(sp, out, client=again)
    assert again.calls == 0 and res["cached"] is True
    assert res["segments"] == first["segments"]


def test_cache_hit_does_not_create_client(tmp_path, monkeypatch):
    sp, out = _seg_file(tmp_path), tmp_path / "text.json"
    ut.run(sp, out, client=FakeClient(), model="deepseek-chat")
    monkeypatch.setattr(ut, "DeepSeekClient", lambda **kw: pytest.fail("命中缓存不应读 Key / 建客户端"))
    assert ut.run(sp, out, model="deepseek-chat")["cached"] is True


def test_prompt_version_change_invalidates_cache(tmp_path, monkeypatch):
    sp, out = _seg_file(tmp_path), tmp_path / "text.json"
    ut.run(sp, out, client=FakeClient())
    monkeypatch.setattr(ut, "PROMPT_VERSION", ut.PROMPT_VERSION + 1)
    again = FakeClient()
    ut.run(sp, out, client=again)
    assert again.calls > 0


def test_changed_text_or_model_invalidates_cache(tmp_path):
    sp, out = _seg_file(tmp_path), tmp_path / "text.json"
    ut.run(sp, out, client=FakeClient())
    other = FakeClient()
    other.model = "other-model"
    ut.run(sp, out, client=other)
    assert other.calls > 0


def test_artifact_schema_stamped(tmp_path):  # KI-37
    from pipeline import schema
    sp, out = _seg_file(tmp_path), tmp_path / "text.json"
    ut.run(sp, out, client=FakeClient())
    assert json.loads(out.read_text())["artifact_schema"] == schema.ARTIFACT_SCHEMA


def test_changed_timing_or_speaker_invalidates_cache(tmp_path):  # 审查修复 M7
    sp, out = _seg_file(tmp_path), tmp_path / "text.json"
    ut.run(sp, out, client=FakeClient())
    segs = make_segments(6)
    segs[0] = {**segs[0], "start": 99.0, "speaker": "2"}
    sp.write_text(json.dumps({"segments": segs}), encoding="utf-8")
    again = FakeClient()
    ut.run(sp, out, client=again)
    assert again.calls > 0
