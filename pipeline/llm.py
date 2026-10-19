# -*- coding: utf-8 -*-
"""DeepSeek API 客户端（OpenAI 兼容），只做 JSON 输出。

约束：
  * 只用标准库 urllib，不引入 requests；
  * 统一超时与重试（429/5xx/网络错误），业务错误立即失败；
  * 永远不把 API Key 写进异常或日志。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request

from pipeline import applog, safe_http, secrets

DEFAULT_BASE = "https://api.deepseek.com"
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
ERROR_SNIPPET = 200


class LLMError(RuntimeError):
    """LLM 调用的终态失败。

    status：HTTP 状态码（网络错误/解析错误为 None）；
    retryable：调用方再试一次有没有意义（鉴权、参数错误、余额不足再试也没用）。
    """

    def __init__(self, msg: str, *, status: int | None = None,
                 retryable: bool | None = None) -> None:
        super().__init__(msg)
        self.status = status
        self.retryable = (status is None or status in RETRY_STATUS) if retryable is None \
            else retryable


def describe(text: str) -> str:
    """模型 / 接口返回的正文可能是转写、分镜原文：错误信息里只给长度和短摘要，不回显内容。"""
    text = str(text)
    return f"{len(text)} 字，摘要 {hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"


def _api_error(text: str) -> str:
    """HTTP 错误：只取接口自己的 error.message（不含用户内容），否则只给长度摘要。"""
    try:
        err = json.loads(text).get("error")
        msg = err.get("message") if isinstance(err, dict) else None
        if isinstance(msg, str) and msg:
            return msg[:ERROR_SNIPPET]
    except (ValueError, AttributeError):
        pass
    return describe(text)


def _open(req: urllib.request.Request, timeout: float):
    return safe_http.open_url(req, timeout)  # 不跟随重定向：Authorization 不会被带去别处


def default_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    except ValueError as exc:
        raise LLMError("请求地址无效", retryable=False) from None
    try:
        with _open(req, timeout) as resp:
            return resp.status, safe_http.read_capped(resp)
    except safe_http.ResponseTooLarge as exc:
        raise LLMError("模型响应过大，已放弃", retryable=False) from exc
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, safe_http.read_capped(exc)
        except (OSError, http.client.HTTPException, ValueError):
            return exc.code, ""
    except (OSError, http.client.HTTPException) as exc:
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
        applog.register_secret(self.api_key)  # 之后任何日志里出现原文都打码（GL-19）
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
            raise LLMError("未配置 DEEPSEEK_API_KEY：运行 `aicut config set deepseek`",
                           retryable=False)
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
                    try:
                        return json.loads(text)
                    except ValueError:  # 200 但响应体被截断 / 不是 JSON：按网络抖动重试
                        last = LLMError(f"响应不是合法 JSON（{describe(text)}）")
                else:
                    last = LLMError(f"HTTP {status}: {_api_error(text)}", status=status)
                    if not last.retryable:
                        raise last
            if attempt < self.retries:
                self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise LLMError(f"重试 {self.retries} 次仍失败：{last}",
                       status=getattr(last, "status", None))

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
        try:
            self.last_usage = data.get("usage") or {}
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content 不是文本")
        except (AttributeError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"返回结构异常（{describe(json.dumps(data, ensure_ascii=False))}）") from exc
        return _parse_json(content)


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError(f"模型没有返回 JSON（{describe(content)}）")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 解析失败（{describe(content)}）") from exc
