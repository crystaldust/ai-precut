# -*- coding: utf-8 -*-
"""DeepSeek API 客户端（OpenAI 兼容），只做 JSON 输出。

约束：
  * 只用标准库 urllib，不引入 requests；
  * 统一超时与重试（429/5xx/网络错误），业务错误立即失败；
  * 永远不把 API Key 写进异常或日志。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from pipeline import secrets

DEFAULT_BASE = "https://api.deepseek.com"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """LLM 调用的终态失败。"""


def default_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"网络错误：{exc}") from exc


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "deepseek-chat",
        base_url: str = DEFAULT_BASE,
        timeout: float = 120.0,
        retries: int = 3,
        backoff: tuple[float, ...] = (1.0, 3.0, 9.0),
        sleep=time.sleep,
        transport=default_transport,
    ) -> None:
        self.api_key = api_key or secrets.get("deepseek")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.transport = transport
        self.last_usage: dict = {}

    def _post(self, payload: dict) -> dict:
        if not self.api_key:
            raise LLMError("未配置 DEEPSEEK_API_KEY：运行 `aicut config set deepseek`")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        url = f"{self.base_url}/chat/completions"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                status, text = self.transport(url, headers, body, self.timeout)
            except LLMError as exc:
                last = exc
            else:
                if status == 200:
                    return json.loads(text)
                last = LLMError(f"HTTP {status}: {text[:300]}")
                if status not in RETRY_STATUS:
                    raise last
            if attempt < self.retries:
                self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise LLMError(f"重试 {self.retries} 次仍失败：{last}")

    def chat_json(self, system: str, user: str, *,
                  temperature: float = 0.2, max_tokens: int = 4096) -> dict:
        data = self._post({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        })
        self.last_usage = data.get("usage") or {}
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"返回结构异常：{str(data)[:300]}") from exc
        return _parse_json(content)


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError(f"模型没有返回 JSON：{content[:200]}")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 解析失败：{content[:200]}") from exc
