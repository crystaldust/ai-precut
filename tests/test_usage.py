"""KI-32：LLM 用量账本与预算（只统计 tokens，不折算金额，D3）。"""
import json

import pytest

from pipeline import usage
from pipeline.llm import LLMError


class Client:
    model = "fake"

    def __init__(self, tokens=100):
        self.calls = 0
        self.tokens = tokens
        self.last_usage = {}

    def chat_json(self, system, user, **kw):
        self.calls += 1
        self.last_usage = {"prompt_tokens": self.tokens - 10, "completion_tokens": 10,
                           "total_tokens": self.tokens}
        return {"ok": True}


def test_record_accumulates_by_stage(tmp_path):
    usage.record(tmp_path, "text", {"total_tokens": 100, "prompt_tokens": 90})
    usage.record(tmp_path, "text", {"total_tokens": 50})
    usage.record(tmp_path, "summary", {"total_tokens": 7})
    led = usage.load(tmp_path)
    assert led["total_tokens"] == 157 and led["calls"] == 3
    assert led["by_stage"]["text"]["total_tokens"] == 150
    assert json.loads((tmp_path / usage.USAGE_FILE).read_text())["total_tokens"] == 157


@pytest.mark.parametrize("raw", ["{bad", "[]", '{"total_tokens": "x"}'])
def test_corrupt_ledger_does_not_block(tmp_path, raw):
    (tmp_path / usage.USAGE_FILE).write_text(raw)
    assert usage.load(tmp_path)["total_tokens"] == 0
    usage.record(tmp_path, "text", {"total_tokens": 5})
    assert usage.load(tmp_path)["total_tokens"] == 5


def test_metered_client_records_usage(tmp_path):
    inner = Client(tokens=120)
    c = usage.MeteredClient(inner, tmp_path, "text")
    assert c.chat_json("s", "u") == {"ok": True}
    assert c.model == "fake" and usage.load(tmp_path)["total_tokens"] == 120


def test_client_without_last_usage_is_fine(tmp_path):
    class Bare:
        model = "m"

        def chat_json(self, *a, **k):
            return {}
    usage.MeteredClient(Bare(), tmp_path, "text").chat_json("s", "u")
    assert usage.load(tmp_path)["calls"] == 1


def test_over_budget_raises_without_calling(tmp_path, monkeypatch):
    monkeypatch.setenv(usage.BUDGET_ENV, "100")
    usage.record(tmp_path, "text", {"total_tokens": 100})
    inner = Client()
    with pytest.raises(usage.BudgetExceeded) as ei:
        usage.MeteredClient(inner, tmp_path, "text").chat_json("s", "u")
    assert inner.calls == 0 and isinstance(ei.value, LLMError) and not ei.value.retryable
    assert "100" in str(ei.value) and usage.BUDGET_ENV in str(ei.value)
    with pytest.raises(usage.BudgetExceeded):
        usage.check(tmp_path)


def test_zero_means_unlimited(tmp_path, monkeypatch):
    monkeypatch.setenv(usage.BUDGET_ENV, "0")
    usage.record(tmp_path, "text", {"total_tokens": 10**9})
    assert usage.budget() is None
    usage.check(tmp_path)
    usage.MeteredClient(Client(), tmp_path, "text").chat_json("s", "u")


@pytest.mark.parametrize("raw", ["abc", "-5", "1.5", ""])
def test_invalid_env_uses_default(monkeypatch, raw):
    monkeypatch.setenv(usage.BUDGET_ENV, raw)
    assert usage.budget() == usage.DEFAULT_BUDGET_TOKENS == 3_000_000


def test_summary_view(tmp_path, monkeypatch):
    monkeypatch.delenv(usage.BUDGET_ENV, raising=False)
    usage.record(tmp_path, "text", {"total_tokens": 42})
    assert usage.summary(tmp_path) == {"total_tokens": 42, "budget": 3_000_000}


def test_factory_client_is_built_lazily(tmp_path):
    made = []
    c = usage.MeteredClient(lambda: made.append(1) or Client(), tmp_path, "summary", model="m")
    assert c.model == "m" and made == []
    c.chat_json("s", "u")
    c.chat_json("s", "u")
    assert made == [1]


def test_ledger_write_failure_does_not_lose_result(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(usage, "record", boom)
    assert usage.MeteredClient(Client(), tmp_path, "text").chat_json("s", "u") == {"ok": True}
    assert "用量没记上" in capsys.readouterr().out


# ---------------------------------------------------------------- 审查修复 H1：失败的调用不能重记上一次的用量
def test_failed_call_does_not_rerecord_previous_usage(tmp_path):
    import json as _json
    from pipeline import llm
    seq = [0]

    def transport(url, headers, body, timeout):
        seq[0] += 1
        if seq[0] == 1:
            return 200, _json.dumps({"choices": [{"message": {"content": "{}"}}],
                                     "usage": {"total_tokens": 1000, "prompt_tokens": 900,
                                               "completion_tokens": 100}})
        return 500, "boom"

    inner = llm.DeepSeekClient("k", transport=transport, sleep=lambda s: None, retries=0)
    m = usage.MeteredClient(inner, tmp_path, "text")
    m.chat_json("s", "u")
    with pytest.raises(LLMError):
        m.chat_json("s", "u")
    assert usage.load(tmp_path)["total_tokens"] == 1000


def test_missing_total_falls_back_to_prompt_plus_completion(tmp_path):
    class Partial(Client):
        def chat_json(self, *a, **k):
            self.last_usage = {"prompt_tokens": 30, "completion_tokens": 12}
            return {}
    usage.MeteredClient(Partial(), tmp_path, "text").chat_json("s", "u")
    assert usage.load(tmp_path)["total_tokens"] == 42
