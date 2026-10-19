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

from pipeline import asr_state, schema, secrets

BACKEND = "mediakit-cli"  # GL-01 换 HTTP 后改成新值，旧的续查状态自动作废
STATE_SAVE_FAILED = "[!] 没能记下云端任务号（{exc}），这次中断后重跑会重新提交"

NETWORK_HINTS = (
    "timeout", "timed out", "connection", "reset by peer", "temporarily",
    "network", "502", "503", "504", "eof", "broken pipe",
)


class CloudError(RuntimeError):
    """云端调用失败。

    retryable=True：超时 / 网络类，重跑可以接着查同一个任务。
    terminal=True：云端明确说这个任务已经失败 / 取消（只有这种才清掉续查状态，GL-16）；
    鉴权失败、找不到 mediakit-cli、返回不是 JSON 都不是任务本身的终态，任务号要留着。
    """

    def __init__(self, message: str, *, retryable: bool = False, terminal: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.terminal = terminal


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
        raise CloudError(f"重试 {self.retries} 次仍失败：{last}", retryable=True)

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

    def wait_task(self, task_id: str, total_timeout: float,
                  interval: float = 10.0) -> dict:
        """单次查询 + 自己轮询。不用 --poll-complete：那是阻塞调用，
        长音频（几十分钟）会被子进程超时误杀，而且没法显示进度。"""
        deadline = time.monotonic() + total_timeout
        last_status = ""
        while True:
            data = self._json(self._run(
                ["shared", "query-task", "--task-id", task_id,
                 "--max-poll-attempts", "0"],
                self.timeout_poll))
            status = (data.get("status") or "").lower()
            last_status = status or last_status
            if status in ("completed", "success", "succeeded"):
                return data
            if status in ("failed", "error", "canceled", "cancelled"):
                raise CloudError(f"任务失败：{data.get('message') or status}", terminal=True)
            if time.monotonic() > deadline:
                raise CloudError(
                    f"任务超时（已等待 {total_timeout / 60:.0f} 分钟，最后状态 {last_status}）："
                    f"{task_id}。任务没有丢，重跑会接着查这个任务，不会重新提交。",
                    retryable=True)
            self.sleep(interval)

    def transcribe(self, audio: Path, workdir: Path,
                   *, duration_s: float = 0.0) -> dict:
        """提交 + 等待，返回字幕 JSON；失败落盘。断点续跑复用同一音频的 task_id（GL-16）。"""
        total_timeout = max(900.0, duration_s * 3 + 600)
        task_id = asr_state.load(workdir, audio, BACKEND)
        try:
            if task_id is None:
                task_id = self.submit_asr(audio)
                _remember_task(workdir, audio, task_id)
            else:
                print(f"[·] 续查上次的子任务：{task_id}")
            data = self.wait_task(task_id, total_timeout)
        except CloudError as exc:
            if exc.terminal:  # 云端判任务终态失败：下次重新提交，而不是 3 天内永远失败
                asr_state.clear(workdir)
            record_failure(workdir, "asr", str(exc), {"audio": str(audio)})
            raise
        # aicut 以"存在"判转写完成，必须原子写（GL-15）
        schema.write_json(Path(workdir) / "transcript_raw.json", data)
        asr_state.clear(workdir)  # 结果已落盘，任务号用完即弃
        return data


def _remember_task(workdir: Path, audio: Path, task_id: str) -> None:
    """记下任务号供中断后续查；记不下来不影响这次转写，只是失去续查能力。"""
    try:
        asr_state.save(workdir, audio, BACKEND, task_id)
    except OSError as exc:
        print(STATE_SAVE_FAILED.format(exc=exc))


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
