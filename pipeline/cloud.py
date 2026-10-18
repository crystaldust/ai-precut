# -*- coding: utf-8 -*-
"""MediaKit 云端调用封装：超时、重试、幂等、失败落盘。

设计要点：
  * 所有外部调用都经过 `CloudClient._run`，禁止在业务代码里裸调 subprocess；
  * 网络类错误重试（指数退避），业务类错误不重试；
  * 同一个逻辑请求的重试链复用同一个 client_token，避免重复计费/重复任务；
  * 失败写 `work/failed.json`，界面据此提供"重试/跳过"。
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline import secrets

NETWORK_HINTS = (
    "timeout", "timed out", "connection", "reset by peer", "temporarily",
    "network", "502", "503", "504", "eof", "broken pipe",
)


class CloudError(RuntimeError):
    """云端调用的终态失败。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CloudClient:
    def __init__(
        self,
        cli: str = "mediakit-cli",
        *,
        retries: int = 3,
        backoff: tuple[float, ...] = (1.0, 3.0, 9.0),
        sleep=time.sleep,
        timeout_submit: float = 30.0,
        timeout_poll: float = 20.0,
        runner=subprocess.run,
        env: dict | None = None,
    ) -> None:
        self.cli = cli
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.timeout_submit = timeout_submit
        self.timeout_poll = timeout_poll
        self.runner = runner
        self.env = env if env is not None else secrets.env_with_secret()

    # ------------------------------------------------------------------ 基础
    def _run(self, args: list[str], timeout: float) -> str:
        """执行 CLI，网络类错误按退避重试；返回 stdout。"""
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                proc = self.runner(
                    [self.cli, *args], capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=timeout, env=self.env,
                )
            except subprocess.TimeoutExpired as exc:
                last = exc
            except FileNotFoundError as exc:
                raise CloudError(f"找不到 {self.cli}，请先安装 mediakit-cli") from exc
            else:
                if proc.returncode == 0:
                    return proc.stdout
                blob = f"{proc.stdout}\n{proc.stderr}".lower()
                last = CloudError(f"{self.cli} 退出码 {proc.returncode}: {blob[:400]}")
                if not any(h in blob for h in NETWORK_HINTS):
                    raise last
            if attempt < self.retries:
                self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise CloudError(f"重试 {self.retries} 次仍失败：{last}")

    @staticmethod
    def _json(stdout: str) -> dict:
        text = stdout.strip()
        start = text.find("{")
        if start < 0:
            raise CloudError(f"返回不是 JSON：{text[:200]}")
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError as exc:
            raise CloudError(f"JSON 解析失败：{text[:200]}") from exc

    # ------------------------------------------------------------------ 业务
    def submit_asr(
        self,
        audio: Path,
        *,
        language: str = "cmn-Hans-CN",
        speaker: bool = True,
        confidence: bool = True,
        client_token: str | None = None,
    ) -> str:
        token = client_token or uuid.uuid4().hex
        args = [
            "video", "asr-subtitles",
            "--audio-url", str(audio),
            "--language", language,
            f"--enable-speaker-info={'true' if speaker else 'false'}",
            f"--enable-confidence={'true' if confidence else 'false'}",
            "--client-token", token,
        ]
        data = self._json(self._run(args, self.timeout_submit))
        task_id = data.get("task_id")
        if not task_id:
            raise CloudError(f"未返回 task_id：{str(data)[:200]}")
        return task_id

    def wait_task(self, task_id: str, total_timeout: float) -> dict:
        deadline = time.monotonic() + total_timeout
        while True:
            data = self._json(self._run(
                ["shared", "query-task", "--task-id", task_id, "--poll-complete"],
                self.timeout_poll))
            status = (data.get("status") or "").lower()
            if status in ("completed", "success", "succeeded"):
                return data
            if status in ("failed", "error", "canceled", "cancelled"):
                raise CloudError(f"任务失败：{data.get('message') or status}")
            if time.monotonic() > deadline:
                raise CloudError(f"任务超时：{task_id}")
            self.sleep(2.0)

    def transcribe(self, audio: Path, workdir: Path,
                   *, duration_s: float = 0.0) -> dict:
        """提交 + 等待，返回字幕 JSON；失败落盘。"""
        total_timeout = max(600.0, duration_s * 3 + 300)
        try:
            task_id = self.submit_asr(audio)
            data = self.wait_task(task_id, total_timeout)
        except CloudError as exc:
            record_failure(workdir, "asr", str(exc), {"audio": str(audio)})
            raise
        raw = Path(workdir) / "transcript_raw.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data


def record_failure(workdir: Path, stage: str, error: str, context: dict) -> None:
    """把失败追加到 work/failed.json，供界面展示与重试。"""
    path = Path(workdir) / "failed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    if path.exists():
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            items = []
    items.append({
        "stage": stage,
        "error": re.sub(r"\s+", " ", error)[:800],
        "context": context,
        "at": _now(),
    })
    path.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=2), encoding="utf-8")
