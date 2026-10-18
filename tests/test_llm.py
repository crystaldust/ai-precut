import json

import pytest

from pipeline import llm


def transport_ok(content: str, status: int = 200):
    def _t(url, headers, body, timeout):
        return status, json.dumps({"choices": [{"message": {"content": content}}],
                                   "usage": {"total_tokens": 42}})
    return _t


def test_chat_json_parses_content():
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None,
                           transport=transport_ok('{"a": 1}'))
    assert c.chat_json("s", "u") == {"a": 1}
    assert c.last_usage["total_tokens"] == 42


def test_fenced_json_is_stripped():
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None,
                           transport=transport_ok('```json\n{"b": 2}\n```'))
    assert c.chat_json("s", "u") == {"b": 2}


def test_retry_on_429_then_success():
    calls = []

    def _t(url, headers, body, timeout):
        calls.append(1)
        if len(calls) == 1:
            return 429, "rate limited"
        return 200, json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]})

    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None, transport=_t)
    assert c.chat_json("s", "u") == {"ok": True}
    assert len(calls) == 2


def test_400_not_retried():
    calls = []

    def _t(url, headers, body, timeout):
        calls.append(1)
        return 400, "bad request"

    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None, transport=_t)
    with pytest.raises(llm.LLMError):
        c.chat_json("s", "u")
    assert len(calls) == 1


def test_missing_key_raises_helpful_error(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(llm.secrets, "get", lambda name: None)
    c = llm.DeepSeekClient(api_key=None)
    with pytest.raises(llm.LLMError) as ei:
        c.chat_json("s", "u")
    assert "config set deepseek" in str(ei.value)


def test_non_json_content_raises():
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None,
                           transport=transport_ok("抱歉，我无法回答"))
    with pytest.raises(llm.LLMError):
        c.chat_json("s", "u")


def test_api_key_not_in_error_message():
    def _t(url, headers, body, timeout):
        return 401, "unauthorized"

    c = llm.DeepSeekClient(api_key="sk-secret-value", sleep=lambda _: None, transport=_t)
    with pytest.raises(llm.LLMError) as ei:
        c.chat_json("s", "u")
    assert "sk-secret-value" not in str(ei.value)
