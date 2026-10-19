# -*- coding: utf-8 -*-
"""LLM 用量账本与预算（KI-32）。

  * 账本在 work/llm_usage.json：{"total_tokens", "calls", "by_stage": {stage: {...}}}；坏文件不阻断（当空账本）；
  * 预算按项目累计 tokens，AI_CUT_LLM_BUDGET_TOKENS 调整，0 = 不限；只统计 tokens，不折算金额（D3）；
  * MeteredClient 包住 DeepSeekClient：调用前查预算、调用后按 last_usage 记账（跨进程加锁）。
"""
from __future__ import annotations

import os
from pathlib import Path

from pipeline import applog, schema
from pipeline.llm import LLMError

USAGE_FILE = "llm_usage.json"
BUDGET_ENV = "AI_CUT_LLM_BUDGET_TOKENS"
DEFAULT_BUDGET_TOKENS = 3_000_000
RECORD_FAILED = "[!] LLM 用量没记上（{exc}），本次用量不计入预算"
LOG = applog.get("usage")
TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
BUDGET_EXCEEDED = ("本项目 LLM 用量已达上限（{used} / {budget} tokens），已停止调用模型。"
                   "要继续：设置环境变量 {env} 调高上限，或设为 0 不限")


class BudgetExceeded(LLMError):
    """本项目累计用量已达预算：不可重试（再试还是超）。"""

    def __init__(self, used: int, limit: int) -> None:
        super().__init__(BUDGET_EXCEEDED.format(used=used, budget=limit, env=BUDGET_ENV),
                         retryable=False)
        self.used, self.budget = used, limit


def budget() -> int | None:
    """当前预算（tokens）；0 → None（不限）；env 缺失或非法 → 默认值。"""
    raw = (os.environ.get(BUDGET_ENV) or "").strip()
    if not raw.isdigit():
        return DEFAULT_BUDGET_TOKENS
    value = int(raw)
    return None if value == 0 else value


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _empty() -> dict:
    return {"total_tokens": 0, "calls": 0, "by_stage": {}}


def _sane(data: object) -> dict:
    if not isinstance(data, dict):
        return _empty()
    stages = data.get("by_stage") if isinstance(data.get("by_stage"), dict) else {}
    return {"total_tokens": _int(data.get("total_tokens")), "calls": _int(data.get("calls")),
            "by_stage": {k: v for k, v in stages.items() if isinstance(v, dict)}}


def load(workdir: Path) -> dict:
    try:
        return _sane(schema.read_json(Path(workdir) / USAGE_FILE, default=None, expect=None))
    except schema.CorruptJSON:  # 账本坏了不能挡住剪辑：按空账本继续
        return _empty()


def total_of(used: dict) -> int:
    """total_tokens；接口没给时按 prompt + completion 算。"""
    return _int(used.get("total_tokens")) or (_int(used.get("prompt_tokens"))
                                               + _int(used.get("completion_tokens")))


def record(workdir: Path, stage: str, used: dict | None) -> None:
    """把一次调用的用量累加进账本（跨进程加锁读改写）。"""
    used = used if isinstance(used, dict) else {}
    path = Path(workdir) / USAGE_FILE
    with schema.locked(path):
        led = load(workdir)
        cur = dict(led["by_stage"].get(stage) or {})
        cur = {**cur, **{k: _int(cur.get(k)) + _int(used.get(k)) for k in TOKEN_KEYS[:2]},
               "total_tokens": _int(cur.get("total_tokens")) + total_of(used),
               "calls": _int(cur.get("calls")) + 1}
        schema.write_json(path, {"total_tokens": led["total_tokens"] + total_of(used),
                                 "calls": led["calls"] + 1,
                                 "by_stage": {**led["by_stage"], stage: cur}})


def check(workdir: Path) -> None:
    """已达预算 → BudgetExceeded；不限或未达 → 什么也不做。"""
    limit = budget()
    used = load(workdir)["total_tokens"]
    if limit is not None and used >= limit:
        raise BudgetExceeded(used, limit)


def over_budget_message(workdir: Path) -> str | None:
    try:
        check(workdir)
    except BudgetExceeded as exc:
        return str(exc)
    return None


def summary(workdir: Path) -> dict:
    """给界面 / status：{"total_tokens", "budget"}（budget 为 None 表示不限）。"""
    return {"total_tokens": load(workdir)["total_tokens"], "budget": budget()}


class MeteredClient:
    """chat_json 前查预算、后记 last_usage；其余属性透传给被包的客户端。

    client 可以是客户端，也可以是无参工厂（第一次真正调用时才建，命中缓存时连 Key 都不读）。
    """

    def __init__(self, client, workdir: Path, stage: str, *, model: str | None = None) -> None:
        self._client = client if hasattr(client, "chat_json") else None
        self._factory = None if self._client is not None else client
        self._workdir, self._stage, self._model = Path(workdir), stage, model

    def _inner(self):
        if self._client is None:
            self._client = self._factory()
        return self._client

    @property
    def model(self) -> str:
        return self._model or getattr(self._inner(), "model", "")

    def chat_json(self, system: str, user: str, **kw) -> dict:
        check(self._workdir)  # 每次真正调用前查预算（命中缓存的步骤不会走到这里）
        inner = self._inner()
        if hasattr(inner, "last_usage"):
            inner.last_usage = {}  # 清掉上一次的：失败的调用不能把上次的用量再记一遍
        result = inner.chat_json(system, user, **kw)
        try:
            record(self._workdir, self._stage, getattr(inner, "last_usage", {}) or {})
        except OSError as exc:  # 记不了账不能让已经付费的结果作废；说出来（进日志与任务输出）
            LOG.warning("LLM 用量没记上：%s", exc)
            print(RECORD_FAILED.format(exc=exc))
        return result
