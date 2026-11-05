# -*- coding: utf-8 -*-
"""片段一句话总结（pipeline/segment_summary.py）：分批并发、缓存、失败不外抛、用量记账。"""
import json
import re
import threading
import time

import pytest

from pipeline import segment_summary as ss
from pipeline import schema, usage
from pipeline.llm import LLMError
from pipeline.usage import BudgetExceeded

LINE = re.compile(r"^(S\d+) ", re.M)


def segs(n, prefix="第"):
    return [{"id": f"S{i:03d}", "start": float(i), "end": i + 1.0, "text": f"{prefix}{i}句话",
             "level": 2} for i in range(1, n + 1)]


def write_text_file(work, segments, visual=None):
    path = work / "segments_text.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"topics": [], "segments": segments,
                                **({"visual_segments": visual} if visual else {})},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class Fake:
    """一个客户端实例；calls / threads 记在共享的 hub 上。"""

    def __init__(self, hub):
        self.hub, self.last_usage, self.model = hub, {}, "fake"

    def chat_json(self, system, user, **kw):
        ids = LINE.findall(user)
        thread = threading.get_ident()
        with self.hub.lock:
            self.hub.calls.append(ids)
            self.hub.users.append(user)
            self.hub.owners.setdefault(id(self), set()).add(thread)
            n = len(self.hub.calls)
        if self.hub.barrier:
            self.hub.barrier.wait(timeout=5)
        if self.hub.delay:
            time.sleep(self.hub.delay)
        self.last_usage = {"prompt_tokens": len(ids), "completion_tokens": 1,
                           "total_tokens": len(ids) + 1}
        return self.hub.reply(ids, n)


class Hub:
    def __init__(self, reply=None, barrier=None, delay=0.0):
        self.lock = threading.Lock()
        self.calls, self.users, self.owners, self.made = [], [], {}, 0
        self.reply = reply or (lambda ids, n: {"segments": [{"id": i, "summary": f"总结{i}"} for i in ids]})
        self.barrier, self.delay = barrier, delay

    def factory(self):
        with self.lock:
            self.made += 1
        return Fake(self)


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ss, "_sleep", lambda ev, s: None)
    monkeypatch.setenv(usage.BUDGET_ENV, "0")


def run(tmp_path, hub, segments=None, **kw):
    path = tmp_path / "work" / "segments_text.json"
    if segments is not None:
        write_text_file(tmp_path / "work", segments)
    return ss.run(path, tmp_path / "work" / ss.OUT_FILE, client_factory=hub.factory, **kw)


def items(tmp_path):
    return json.loads((tmp_path / "work" / ss.OUT_FILE).read_text(encoding="utf-8"))["items"]


def test_constants():
    from pipeline import llm
    assert (ss.PROMPT_VERSION, ss.BATCH, ss.PARALLEL, ss.MAX_TOKENS) == (1, 50, 4, 4000)
    assert (ss.SUMMARY_MAX, ss.INPUT_CLIP, ss.OUT_FILE, ss.STAGE) == (
        20, 300, "segment_summaries.json", "segment_summary")
    assert ss.SEGMENT_SUMMARY_MODEL == llm.DEFAULT_MODEL


def test_batching_splits_at_50(tmp_path):
    hub = Hub()
    res = run(tmp_path, hub, segs(120))
    assert sorted(len(c) for c in hub.calls) == [20, 50, 50]
    assert res == {"done": 120, "failed": 0, "error": "", "cached": 0}
    assert len(items(tmp_path)) == 120


def test_concurrent_equals_sequential(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    segments = segs(230)
    run(a, Hub(delay=0.01), segments, parallel=1)
    run(b, Hub(delay=0.01), segments, parallel=4)
    fa, fb = (p / "work" / ss.OUT_FILE for p in (a, b))
    assert fa.read_bytes() == fb.read_bytes()


def test_each_thread_gets_its_own_client(tmp_path):
    hub = Hub(barrier=threading.Barrier(4), )
    run(tmp_path, hub, segs(200))  # 4 批、4 个并发线程
    assert hub.made == 4 and len(hub.owners) == 4
    assert all(len(threads) == 1 for threads in hub.owners.values())
    assert len({next(iter(t)) for t in hub.owners.values()}) == 4


def test_usage_recorded_once_per_call_under_concurrency(tmp_path):
    work = tmp_path / "work"
    hub = Hub(barrier=threading.Barrier(4))
    write_text_file(work, segs(200))
    factory = lambda: usage.MeteredClient(hub.factory, work, ss.STAGE)  # noqa: E731
    res = ss.run(work / "segments_text.json", work / ss.OUT_FILE, client_factory=factory)
    led = usage.load(work)
    assert res["done"] == 200
    assert led["calls"] == 4 and led["by_stage"][ss.STAGE]["calls"] == 4
    assert led["total_tokens"] == 200 + 4 and led["by_stage"][ss.STAGE]["prompt_tokens"] == 200


def test_usage_record_is_thread_safe(tmp_path):
    threads = [threading.Thread(target=lambda: [usage.record(tmp_path, "x", {"total_tokens": 1})
                                                for _ in range(10)]) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert usage.load(tmp_path)["calls"] == 80 and usage.load(tmp_path)["total_tokens"] == 80


def test_normalizes_whitespace_and_clamps(tmp_path):
    long = "一二三四五六七八九十" * 3
    reply = {"segments": [{"id": "S001", "summary": " 讲 合\n同\t条款　x\x07y "},
                          {"id": "S002", "summary": long}]}
    run(tmp_path, Hub(reply=lambda ids, n: reply), segs(2))
    got = items(tmp_path)
    assert got["S001"]["summary"] == "讲合同条款xy"
    assert got["S002"]["summary"] == long[:20] and len(got["S002"]["summary"]) == 20


def test_drops_unknown_nonstr_and_bad_items(tmp_path):
    reply = {"segments": [{"id": "S001", "summary": "好"}, {"id": "S9", "summary": "不存在"},
                          {"id": "S002", "summary": 5}, {"id": "S003", "summary": " \n "},
                          {"id": ["S004"], "summary": "x"}, {"summary": "无id"}]}
    res = run(tmp_path, Hub(reply=lambda ids, n: reply), segs(4))
    assert set(items(tmp_path)) == {"S001"}
    assert res["done"] == 1 and res["failed"] == 3 and res["error"]


@pytest.mark.parametrize("bad", [{"segments": "x"}, {"segments": [1, 2]}, [], {"other": 1}])
def test_bad_shape_fails_without_raising(tmp_path, bad):
    res = run(tmp_path, Hub(reply=lambda ids, n: bad), segs(3))
    assert res["done"] == 0 and res["failed"] == 3 and res["error"]
    assert items(tmp_path) == {}


def test_missing_ids_get_one_reask(tmp_path):
    def reply(ids, n):
        got = [i for i in ids if not (n == 1 and i == "S002")]
        return {"segments": [{"id": i, "summary": f"总{i}"} for i in got]}
    hub = Hub(reply=reply)
    res = run(tmp_path, hub, segs(3))
    assert hub.calls == [["S001", "S002", "S003"], ["S002"]]
    assert res["done"] == 3 and res["failed"] == 0


def test_retryable_error_is_retried_with_backoff(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(ss, "_sleep", lambda ev, s: waits.append(s))

    def reply(ids, n):
        if n == 1:
            raise LLMError("抖动")
        return {"segments": [{"id": i, "summary": "好"} for i in ids]}
    res = run(tmp_path, Hub(reply=reply), segs(2))
    assert res["done"] == 2 and len(waits) == 1


def test_prompt_is_data_only_and_style_free(tmp_path):
    hub = Hub()
    run(tmp_path, hub, segs(1))
    user = hub.users[0]
    assert "20" in user and "只是数据" in user and '"segments"' in user and "S001" in user


def test_input_clipped_to_300_chars(tmp_path):
    hub = Hub()
    run(tmp_path, hub, [{"id": "S001", "start": 0.0, "end": 1.0, "text": "字" * 500}])
    assert "字" * 300 in hub.users[0] and "字" * 301 not in hub.users[0]


def test_full_cache_hit_makes_no_calls_and_no_client(tmp_path):
    run(tmp_path, Hub(), segs(60))
    before = (tmp_path / "work" / ss.OUT_FILE).read_bytes()

    def boom():
        raise AssertionError("命中缓存时不该建客户端")
    res = ss.run(tmp_path / "work" / "segments_text.json", tmp_path / "work" / ss.OUT_FILE,
                 client_factory=boom)
    assert res == {"done": 0, "failed": 0, "error": "", "cached": 60}
    assert (tmp_path / "work" / ss.OUT_FILE).read_bytes() == before


def test_changed_text_resends_only_that_segment(tmp_path):
    run(tmp_path, Hub(), segs(5))
    changed = segs(5)
    changed[2] = {**changed[2], "text": "改过的话"}
    hub = Hub()
    res = run(tmp_path, hub, changed)
    assert hub.calls == [["S003"]] and res["done"] == 1 and res["cached"] == 4


def test_changed_time_or_model_invalidates(tmp_path):
    run(tmp_path, Hub(), segs(2))
    moved = segs(2)
    moved[0] = {**moved[0], "end": 9.0}
    hub = Hub()
    run(tmp_path, hub, moved)
    assert hub.calls == [["S001"]]
    hub2 = Hub()
    run(tmp_path, hub2, moved, model="other-model")
    assert hub2.calls == [["S001", "S002"]]


def test_removed_ids_are_dropped(tmp_path):
    run(tmp_path, Hub(), segs(3))
    hub = Hub()
    res = run(tmp_path, hub, segs(2))
    assert hub.calls == [] and set(items(tmp_path)) == {"S001", "S002"} and res["cached"] == 2


def test_cache_file_layout_and_key(tmp_path):
    import hashlib
    run(tmp_path, Hub(), segs(1))
    data = json.loads((tmp_path / "work" / ss.OUT_FILE).read_text(encoding="utf-8"))
    assert set(data) == {"version", "model", "items", "failures"} and data["failures"] == []
    payload = json.dumps(["第1句话", 1.0, 2.0, ss.SEGMENT_SUMMARY_MODEL, ss.PROMPT_VERSION], ensure_ascii=False)
    assert data["items"]["S001"]["key"] == hashlib.sha1(payload.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("junk", ["{broken", "[]", '{"items": 5}', '{"items": {"S001": 3}}'])
def test_corrupt_cache_is_treated_as_empty(tmp_path, junk):
    write_text_file(tmp_path / "work", segs(2))
    (tmp_path / "work" / ss.OUT_FILE).write_text(junk, encoding="utf-8")
    hub = Hub()
    res = run(tmp_path, hub)
    assert res["done"] == 2 and len(hub.calls) == 1


def test_only_nonempty_text_segments_are_summarized(tmp_path):
    segments = segs(2) + [{"id": "S003", "start": 5.0, "end": 6.0, "text": "  "},
                          {"id": "S004", "start": 6.0, "end": 7.0}]
    visual = [{"id": "V001", "kind": "visual", "start": 8.0, "end": 9.0, "text": "画面字"}]
    write_text_file(tmp_path / "work", segments, visual)
    hub = Hub()
    run(tmp_path, hub)
    assert hub.calls == [["S001", "S002"]]


def test_partial_failure_keeps_successes_and_returns(tmp_path):
    def reply(ids, n):
        if "S051" in ids:
            raise LLMError("网络断了")
        return {"segments": [{"id": i, "summary": "好"} for i in ids]}
    res = run(tmp_path, Hub(reply=reply), segs(100), parallel=1)
    assert res["done"] == 50 and res["failed"] == 50 and "网络断了" in res["error"]
    assert set(items(tmp_path)) == {f"S{i:03d}" for i in range(1, 51)}
    failures = json.loads((tmp_path / "work" / ss.OUT_FILE).read_text(encoding="utf-8"))["failures"]
    assert failures and failures[0]["ids"][0] == "S051"


def test_budget_exceeded_stops_scheduling_and_returns(tmp_path):
    def reply(ids, n):
        raise BudgetExceeded(10, 5)
    hub = Hub(reply=reply)
    res = run(tmp_path, hub, segs(200), parallel=1)
    assert len(hub.calls) == 1 and res["done"] == 0 and res["failed"] == 200 and "上限" in res["error"]


def test_non_retryable_error_stops_remaining_batches(tmp_path):
    def reply(ids, n):
        if n == 1:
            raise LLMError("鉴权失败", status=401)
        return {"segments": [{"id": i, "summary": "好"} for i in ids]}
    hub = Hub(reply=reply)
    res = run(tmp_path, hub, segs(150), parallel=1)
    assert len(hub.calls) == 1 and res["failed"] == 150 and "鉴权失败" in res["error"]


def test_unexpected_exception_never_escapes(tmp_path):
    def factory():
        raise RuntimeError("没有 Key")
    write_text_file(tmp_path / "work", segs(3))
    res = ss.run(tmp_path / "work" / "segments_text.json", tmp_path / "work" / ss.OUT_FILE,
                 client_factory=factory)
    assert res["done"] == 0 and res["failed"] == 3 and "RuntimeError" in res["error"]
    assert "没有 Key" not in res["error"]
    assert "没有 Key" not in (tmp_path / "work" / ss.OUT_FILE).read_text(encoding="utf-8")


def test_unexpected_error_in_run_itself_leaks_only_type(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_run", lambda *a, **k: (_ for _ in ()).throw(ValueError("机密文本")))
    res = ss.run(tmp_path / "a.json", tmp_path / "b.json", client_factory=Hub().factory)
    assert "ValueError" in res["error"] and "机密文本" not in res["error"]


def test_unreadable_input_never_escapes(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "segments_text.json").write_text("{oops", encoding="utf-8")
    res = ss.run(tmp_path / "work" / "segments_text.json", tmp_path / "work" / ss.OUT_FILE,
                 client_factory=Hub().factory)
    assert res["done"] == 0 and res["error"]


def test_source_file_is_byte_identical(tmp_path):
    path = write_text_file(tmp_path / "work", segs(60))
    before = path.read_bytes()
    run(tmp_path, Hub())
    assert path.read_bytes() == before


def test_run_stage_missing_input_is_quiet(tmp_path):
    msgs = []
    out = ss.run_stage(tmp_path / "work", Hub().factory, msgs.append, msgs.append)
    assert out is None and msgs == []


def test_run_stage_reports_in_chinese(tmp_path):
    write_text_file(tmp_path / "work", segs(3))
    infos, warns = [], []
    ss.run_stage(tmp_path / "work", Hub().factory, infos.append, warns.append)
    assert infos and warns == [] and (tmp_path / "work" / ss.OUT_FILE).exists()
    warns.clear()
    bad = Hub(reply=lambda ids, n: (_ for _ in ()).throw(LLMError("坏了", status=400)))
    (tmp_path / "work" / ss.OUT_FILE).unlink()
    ss.run_stage(tmp_path / "work", bad.factory, infos.append, warns.append)
    assert len(warns) == 1 and "坏了" in warns[0]


# ---- 评审补充 ----
@pytest.mark.parametrize("ch", ["\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202e",
                                "\u2066", "\u2069", "\ufeff"])
def test_normalize_strips_zero_width_and_bidi(ch):
    assert ss.normalize(f"讲{ch}合{ch}同") == "讲合同"


def test_stop_halts_retrying_batch_and_wakes_backoff(tmp_path, monkeypatch):
    monkeypatch.undo()  # 用真实的可中断等待
    monkeypatch.setenv(usage.BUDGET_ENV, "0")
    monkeypatch.setattr(ss, "BACKOFF", (3.0,))

    def reply(ids, n):
        if n == 1:
            raise LLMError("抖动")
        raise BudgetExceeded(10, 5)
    hub = Hub(reply=reply)
    started = time.monotonic()
    res = run(tmp_path, hub, segs(100), parallel=2)
    assert len(hub.calls) == 2 and time.monotonic() - started < 2.0
    assert res["done"] == 0 and res["failed"] == 100


def test_each_attempt_checks_stop_before_calling(tmp_path):
    stop = ss._Stop()
    stop.set("预算用完")
    called = []
    out, failure = ss._do_batch(segs(2), lambda: called.append(1), stop, 2)
    assert called == [] and out == {} and failure["ids"] == ["S001", "S002"]
    assert ss.SKIPPED_PREFIX in failure["error"]


def test_keyboard_interrupt_cancels_pending_and_propagates(tmp_path, monkeypatch):
    shutdowns = []

    class Spy(ss.ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            shutdowns.append(cancel_futures)
            return super().shutdown(wait=wait, cancel_futures=cancel_futures)
    monkeypatch.setattr(ss, "ThreadPoolExecutor", Spy)

    def reply(ids, n):
        raise KeyboardInterrupt
    hub = Hub(reply=reply)
    with pytest.raises(KeyboardInterrupt):
        ss._fill(segs(150), hub.factory, 1, 2)
    assert True in shutdowns and len(hub.calls) == 1


def _foreign_writer(tmp_path, seg_id, key_of):
    path = tmp_path / "work" / ss.OUT_FILE
    path.write_text(json.dumps({"version": 1, "items": {seg_id: {"summary": "别人写的", "key": key_of}},
                                "failures": []}, ensure_ascii=False), encoding="utf-8")


def test_concurrent_writer_entry_with_matching_key_is_merged(tmp_path):
    rows = segs(2)
    key2 = ss._key(rows[1], ss.SEGMENT_SUMMARY_MODEL)

    def reply(ids, n):
        _foreign_writer(tmp_path, "S002", key2)  # 网络调用期间，别的进程写入了 S002
        return {"segments": [{"id": "S001", "summary": "我写的"}]}
    res = run(tmp_path, Hub(reply=reply), rows, retries=0)
    got = items(tmp_path)
    assert got["S001"]["summary"] == "我写的" and got["S002"]["summary"] == "别人写的"
    data = json.loads((tmp_path / "work" / ss.OUT_FILE).read_text(encoding="utf-8"))
    assert data["failures"] == [] and res["done"] == 1


def test_concurrent_writer_entry_with_other_key_is_dropped(tmp_path):
    def reply(ids, n):
        _foreign_writer(tmp_path, "S002", "旧key")
        return {"segments": [{"id": "S001", "summary": "我写的"}]}
    run(tmp_path, Hub(reply=reply), segs(2), retries=0)
    assert set(items(tmp_path)) == {"S001"}


# ---- 外发许可 ----
def test_precheck_not_called_on_full_cache_hit(tmp_path):
    run(tmp_path, Hub(), segs(3))
    calls = []
    hub = Hub()
    res = run(tmp_path, hub, precheck=lambda: calls.append(1))
    assert calls == [] and hub.calls == [] and res["cached"] == 3


def test_precheck_called_once_before_first_request(tmp_path):
    order = []
    hub = Hub(reply=lambda ids, n: order.append("call") or {"segments": [{"id": i, "summary": "好"} for i in ids]})
    run(tmp_path, hub, segs(120), precheck=lambda: order.append("check"))
    assert order[0] == "check" and order.count("check") == 1


def test_precheck_refusal_skips_round_without_calls_or_file(tmp_path):
    hub = Hub()
    res = run(tmp_path, hub, segs(3), precheck=lambda: "未确认外发")
    assert hub.calls == [] and hub.made == 0 and res["done"] == 0 and res["error"] == "未确认外发"
    assert res.get("skipped") is True and not (tmp_path / "work" / ss.OUT_FILE).exists()


def test_precheck_raising_never_escapes(tmp_path):
    def boom():
        raise SystemExit(1)
    res = run(tmp_path, Hub(), segs(2), precheck=boom)
    assert res["done"] == 0 and res["error"]


def test_run_stage_warns_when_precheck_refuses(tmp_path):
    write_text_file(tmp_path / "work", segs(3))
    infos, warns = [], []
    hub = Hub()
    res = ss.run_stage(tmp_path / "work", hub.factory, infos.append, warns.append,
                       precheck=lambda: "还没确认外发说明")
    assert hub.calls == [] and infos == [] and len(warns) == 1 and "还没确认外发说明" in warns[0]
    assert "不影响" in warns[0] and res["skipped"] is True


def test_cloud_precheck_messages(tmp_path, monkeypatch):
    from pipeline import consent, secrets
    monkeypatch.setattr(consent, "accepted", lambda: False)
    assert ss.cloud_precheck() == consent.CLI_REQUIRED_MSG
    monkeypatch.setattr(consent, "accepted", lambda: True)
    monkeypatch.setattr(secrets, "get", lambda p: None)
    assert "DEEPSEEK_API_KEY" in ss.cloud_precheck()
    monkeypatch.setattr(secrets, "get", lambda p: "k")
    assert ss.cloud_precheck() is None
