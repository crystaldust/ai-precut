import http.client
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


# ---------------------------------------------------------------- M2 审查：坏响应一律 LLMError
def test_truncated_200_body_is_llm_error_and_retried():
    calls = []

    def _t(url, headers, body, timeout):
        calls.append(1)
        return 200, '{"choices": [{"message": '  # 截断
    c = llm.DeepSeekClient(api_key="k", retries=2, sleep=lambda _: None, transport=_t)
    with pytest.raises(llm.LLMError):
        c.chat_json("s", "u")
    assert len(calls) == 3


@pytest.mark.parametrize("payload", ['[]', '{"choices": null}', '{"choices": [{"message": 5}]}',
                                     '{"choices": [{"message": {"content": 7}}]}', '"x"'])
def test_malformed_choices_is_llm_error(payload):
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None,
                           transport=lambda *a: (200, payload))
    with pytest.raises(llm.LLMError):
        c.chat_json("s", "u")


def test_llm_error_exposes_status():
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None,
                           transport=lambda *a: (401, "unauthorized"))
    with pytest.raises(llm.LLMError) as ei:
        c.chat_json("s", "u")
    assert ei.value.status == 401 and ei.value.retryable is False


def test_exhausted_retry_error_is_retryable():
    c = llm.DeepSeekClient(api_key="k", retries=1, sleep=lambda _: None,
                           transport=lambda *a: (503, "busy"))
    with pytest.raises(llm.LLMError) as ei:
        c.chat_json("s", "u")
    assert ei.value.status == 503 and ei.value.retryable is True


def test_missing_key_not_retryable(monkeypatch):
    monkeypatch.setattr(llm.secrets, "get", lambda name: None)
    with pytest.raises(llm.LLMError) as ei:
        llm.DeepSeekClient(api_key=None).chat_json("s", "u")
    assert ei.value.retryable is False


# ---------------------------------------------------------------- M8：KI-25 回归（走真实 default_transport）
class _Resp:
    def __init__(self, body):
        self.status, self._b = 200, body.encode()

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_OK_BODY = json.dumps({"choices": [{"message": {"content": '{"ok": 1}'}}]})


def _sequenced_open(seq):
    def fake_open(req, timeout):
        item = seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    return fake_open


@pytest.mark.parametrize("exc", [http.client.RemoteDisconnected("closed"),
                                 ConnectionResetError(54, "reset"),
                                 http.client.IncompleteRead(b"")])
def test_default_transport_retries_dropped_connection(monkeypatch, exc):
    seq = [exc, _Resp(_OK_BODY)]
    monkeypatch.setattr(llm, "_open", _sequenced_open(seq))
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None, transport=llm.default_transport)
    assert c.chat_json("s", "u") == {"ok": 1}
    assert seq == []


def test_default_transport_200_html_then_json_retries(monkeypatch):
    seq = [_Resp("<html>gateway</html>"), _Resp(_OK_BODY)]
    monkeypatch.setattr(llm, "_open", _sequenced_open(seq))
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None, transport=llm.default_transport)
    assert c.chat_json("s", "u") == {"ok": 1}
    assert seq == []


def test_default_transport_gives_up_after_retries(monkeypatch):
    seq = [http.client.RemoteDisconnected("closed") for _ in range(4)]
    monkeypatch.setattr(llm, "_open", _sequenced_open(seq))
    c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None, transport=llm.default_transport)
    with pytest.raises(llm.LLMError, match="网络错误"):
        c.chat_json("s", "u")
