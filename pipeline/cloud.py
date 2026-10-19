# -*- coding: utf-8 -*-
"""火山引擎 MediaKit 云端 ASR 客户端（直连 HTTPS，不依赖 mediakit-cli / Node，GL-01）。

协议与 @volcengine/mediakit-cli 0.2.1 一致（internal/cloud/*.go）：
  1. POST /api/v1/tools-sync/request-media-upload-url → 预签名地址，PUT 上传本地音轨，得到 mediakit:// file_id；
  2. POST /api/v1/tools/asr-subtitles → task_id（同一逻辑请求的重试复用 client_token，避免重复计费）；
  3. GET  /api/v1/tasks/{task_id} → running|queued|completed|failed|canceled。
约束：只用 urllib；429/5xx/网络错误按退避重试，业务错误立即失败；
永不把 API Key、预签名 URL 写进异常、日志或 failed.json；失败写 `work/failed.json`。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline import applog, asr_state, safe_http, schema, secrets

BACKEND = "mediakit-http-v1"  # 换实现就换值：旧 mediakit-cli 的续查状态自动作废（GL-16）
STATE_SAVE_FAILED = "[!] 没能记下云端任务号（{exc}），这次中断后重跑会重新提交"

DEFAULT_ENDPOINT = "https://mediakit.cn-beijing.volces.com"
ASR_TOOL = "asr-subtitles"
UPLOAD_PATH = "/api/v1/tools-sync/request-media-upload-url"
SUBMIT_PATH = f"/api/v1/tools/{ASR_TOOL}"
TASK_PATH = "/api/v1/tasks/{task_id}"
DEFAULT_LANGUAGE = "cmn-Hans-CN"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
AUTH_STATUS = {401, 403}
UPLOAD_RETRY_STATUS = RETRY_STATUS | {403}  # 预签名过期 → 重新申请地址再传
DONE = {"completed", "success", "succeeded"}
FAILED = {"failed", "error", "canceled", "cancelled"}
UPLOAD_TTL_S = 12 * 3600          # 与 mediakit-cli upload_cache.go 一致
UPLOAD_CACHE = "asr_upload.json"  # work/ 下，只存 file_id 与指纹，不存 Key / 上传地址
UPLOAD_CACHE_SCHEMA = 1
SUBMIT_TOKEN_FILE = "asr_submit.json"  # 提交前先落盘 client_token：响应丢了重跑也用同一个，云端去重
NOT_FOUND = 404
ERROR_SNIPPET = 300
# 统计头（mediakit-cli 会发 X-Amk-*）；取值见 M5 计划 Notes「需用户决策 6」
CLIENT_RUNTIME = "aicut"
CLIENT_TASK_SOURCE = "cli/aicut"
CLIENT_HEADERS = {"X-Amk-Cli-Runtime": CLIENT_RUNTIME, "X-Amk-Task-Source": CLIENT_TASK_SOURCE}
MISSING_KEY = "未配置 MEDIAKIT_API_KEY：运行 `aicut config set mediakit`，或在剪辑台「⚙ 设置」里填写"
AUTH_FAILED = "MediaKit API Key 无效或无权限（HTTP {status}）：{msg}"
BAD_KEY = "MediaKit API Key 含空白或控制字符：请在剪辑台「⚙ 设置」里重新填写"
TASK_GONE = "云端找不到这个任务（{msg}），下次会重新提交"
_URL_QUERY = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]*")


class CloudError(RuntimeError):
    """云端调用失败。

    retryable=True：超时 / 网络类，重跑可以接着查同一个任务。
    terminal=True：云端明确说这个任务已经失败 / 取消（只有这种才清掉续查状态，GL-16）；
    鉴权失败、参数错误、返回不是 JSON 都不是任务本身的终态，任务号要留着。
    """

    def __init__(self, message: str, *, retryable: bool = False, terminal: bool = False,
                 status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.terminal = terminal
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(text: str, key: str | None) -> str:
    """去掉 URL 查询串（预签名）并把 Key 换成掩码，再截断。"""
    text = _URL_QUERY.sub(r"\1?…", str(text))
    if key:
        text = text.replace(key, secrets.mask(key))
    return text[:ERROR_SNIPPET]


_OPENER = safe_http.OPENER          # 不跟随重定向（否则 Bearer 会被带去新地址），3xx 当错误
MAX_RESPONSE_BYTES = safe_http.MAX_RESPONSE_BYTES
BAD_URL = "请求地址无效（{what}）"
RESPONSE_TOO_LARGE = "云端响应过大（超过 {mb} MB），已放弃"


def _open(req: urllib.request.Request, timeout: float):
    return safe_http.open_url(req, timeout)


def _http_call(req: urllib.request.Request, timeout: float, label: str) -> tuple[int, str]:
    try:
        with _open(req, timeout) as resp:
            return resp.status, safe_http.read_capped(resp)
    except safe_http.ResponseTooLarge as exc:
        raise CloudError(RESPONSE_TOO_LARGE.format(mb=MAX_RESPONSE_BYTES // 1024 // 1024)) from exc
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, safe_http.read_capped(exc)
        except (OSError, http.client.HTTPException, ValueError):
            return exc.code, ""
    except (OSError, http.client.HTTPException) as exc:  # 含 URLError / 超时 / 断流 IncompleteRead
        raise CloudError(f"{label}：{_redact(str(exc), None)}", retryable=True) from exc


def _build_request(url: str, **kw) -> urllib.request.Request:
    """构造失败（非 http/https 等）不透传 ValueError：它的消息里带完整 URL（可能含签名）。"""
    try:
        return urllib.request.Request(url, **kw)
    except ValueError as exc:
        raise CloudError(BAD_URL.format(what=type(exc).__name__)) from None


def default_transport(method: str, url: str, headers: dict, body: bytes | None,
                      timeout: float) -> tuple[int, str]:
    req = _build_request(url, data=body, headers=headers, method=method)
    return _http_call(req, timeout, "网络错误")


def default_upload(method: str, url: str, headers: dict, path: Path,
                   timeout: float) -> tuple[int, str]:
    """PUT 原始字节到预签名地址。不带 Authorization；必须显式给 Content-Length（否则走 chunked）。"""
    size = Path(path).stat().st_size
    # 不给 Content-Type 时 urllib 会自作主张补 x-www-form-urlencoded
    base = {"Content-Type": "application/octet-stream"}
    if any(k.lower() == "content-type" for k in headers):
        base = {}
    with open(path, "rb") as fh:
        req = _build_request(url, data=fh, method=method,
                             headers={**base, **headers, "Content-Length": str(size)})
        return _http_call(req, timeout, "上传网络错误")


def _error_message(payload: object) -> str:
    """按 mediakit-cli response.go 的顺序取错误文案。"""
    if not isinstance(payload, dict):
        return ""
    err = payload.get("error")
    if isinstance(err, dict):
        for k in ("message", "error", "msg"):
            if isinstance(err.get(k), str) and err[k]:
                return err[k]
    for k in ("message", "msg"):
        if isinstance(payload.get(k), str) and payload[k]:
            return payload[k]
    return err if isinstance(err, str) else ""


UPLOAD_FAILED = "上传音轨失败（HTTP {status}{code}）"
_STORAGE_CODE = re.compile(r"<Code>([A-Za-z0-9_.\-]{1,64})</Code>")


def _storage_code(text: str) -> str:
    """对象存储错误只取 <Code>，正文可能带签名 / 请求细节，不记。"""
    m = _STORAGE_CODE.search(text or "")
    return f"，{m.group(1)}" if m else ""


def _parse_upload_headers(raw: object) -> dict[str, str]:
    """upload_headers 兼容 [{"key","value"}] 与 ["K: V"] 两种写法。"""
    out: dict[str, str] = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("key"):
            out[str(item["key"])] = str(item.get("value", ""))
        elif isinstance(item, str) and ":" in item:
            k, v = item.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _key_id(key: str) -> str:
    """Key 的不可逆短指纹：上传缓存按账号隔离，但文件里不出现 Key。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class CloudClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        retries: int = 3,
        backoff: tuple[float, ...] = (1.0, 3.0, 9.0),
        sleep=time.sleep,
        timeout_submit: float = 30.0,
        timeout_poll: float = 20.0,
        timeout_upload: float = 600.0,
        transport=default_transport,
        uploader=default_upload,
    ) -> None:
        self.api_key = api_key or secrets.get("mediakit")  # 只读一次：钥匙串可能弹授权
        applog.register_secret(self.api_key)  # 之后任何日志里出现原文都打码（GL-19）
        self.endpoint = endpoint.rstrip("/")
        self.retries = retries
        self.backoff = backoff
        self.sleep = sleep
        self.timeout_submit = timeout_submit
        self.timeout_poll = timeout_poll
        self.timeout_upload = timeout_upload
        self.transport = transport
        self.uploader = uploader

    def __repr__(self) -> str:
        return f"CloudClient(endpoint={self.endpoint!r}, key={secrets.mask(self.api_key)!r})"

    # ------------------------------------------------------------------ 基础
    def _headers(self) -> dict:
        if not self.api_key:
            raise CloudError(MISSING_KEY)
        if not self.api_key.isascii() or any(ord(ch) < 33 or ord(ch) == 127 for ch in self.api_key):
            raise CloudError(BAD_KEY)  # 否则 http.client 抛 ValueError，消息里带 Key 原文
        return {"Accept": "application/json", "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}", **CLIENT_HEADERS}

    def _backoff(self, attempt: int) -> None:
        if attempt < self.retries:
            self.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])

    def _parse(self, status: int, text: str) -> dict:
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError as exc:
            # 网关偶发的 HTML / 截断：可重试（提交阶段沿用同一 client_token，不会重复计费）
            raise CloudError(f"返回不是 JSON：{_redact(text, self.api_key)}", retryable=True) from exc
        if not isinstance(data, dict):
            raise CloudError(f"返回不是 JSON 对象：{_redact(text, self.api_key)}")
        if data.get("success") is False:
            msg = _error_message(data) or "业务失败"
            raise CloudError(f"云端拒绝：{_redact(msg, self.api_key)}")
        return data

    def _request(self, method: str, path: str, payload: dict | None, timeout: float) -> dict:
        """一次 API 调用：网络 / 429 / 5xx 退避重试（同一 body，client_token 不变），其余立即失败。"""
        headers = self._headers()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None \
            else None
        url = self.endpoint + path
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                status, text = self.transport(method, url, headers, body, timeout)
            except CloudError as exc:
                if not exc.retryable:  # 响应过大 / 地址无效等：重试也没用，原样抛出
                    raise
                last = exc
            else:
                if status < 300:
                    try:
                        return self._parse(status, text)
                    except CloudError as exc:
                        if not exc.retryable:
                            raise
                        last = exc
                        self._backoff(attempt)
                        continue
                msg = _redact(self._body_message(text), self.api_key)
                if status in AUTH_STATUS:
                    raise CloudError(AUTH_FAILED.format(status=status, msg=msg), status=status)
                last = CloudError(f"HTTP {status}: {msg}", status=status)
                if status not in RETRY_STATUS:
                    raise last
            self._backoff(attempt)
        raise CloudError(f"重试 {self.retries} 次仍失败：{last}", retryable=True)

    @staticmethod
    def _body_message(text: str) -> str:
        try:
            return _error_message(json.loads(text)) or text
        except ValueError:
            return text

    # ------------------------------------------------------------------ 上传
    def _cache_matches(self, data: object, audio: Path) -> bool:
        if not isinstance(data, dict) or data.get("schema") != UPLOAD_CACHE_SCHEMA:
            return False
        if (data.get("backend"), data.get("endpoint"), data.get("key")) != \
                (BACKEND, self.endpoint, _key_id(self.api_key or "")):
            return False
        expires = data.get("expires_at")
        if not isinstance(expires, (int, float)) or time.time() >= expires:
            return False
        return isinstance(data.get("file_id"), str) and \
            data.get("audio") == asr_state.fingerprint(audio)

    def _cached_file_id(self, audio: Path, workdir: Path | None) -> str | None:
        if workdir is None:
            return None
        try:
            data = json.loads((Path(workdir) / UPLOAD_CACHE).read_text(encoding="utf-8"))
            return data["file_id"] if self._cache_matches(data, audio) else None
        except (OSError, ValueError, UnicodeDecodeError):
            return None

    def _remember_upload(self, audio: Path, workdir: Path | None, file_id: str) -> None:
        if workdir is None:
            return
        try:
            schema.write_json(Path(workdir) / UPLOAD_CACHE, {
                "schema": UPLOAD_CACHE_SCHEMA, "backend": BACKEND, "endpoint": self.endpoint,
                "key": _key_id(self.api_key or ""), "audio": asr_state.fingerprint(audio),
                "file_id": file_id, "expires_at": time.time() + UPLOAD_TTL_S})
        except OSError:
            pass  # 记不下只是下次要重传，不影响这次

    def _upload_target(self) -> tuple[str, str, str, dict]:
        data = self._request("POST", UPLOAD_PATH, {"tool_name": ASR_TOOL}, self.timeout_submit)
        res = data.get("result") if isinstance(data.get("result"), dict) else data
        file_id, url = res.get("file_id"), res.get("upload_url")
        if not file_id or not url:
            raise CloudError("云端没有返回上传地址（file_id / upload_url）")
        parts = urllib.parse.urlsplit(str(url))
        if parts.scheme != "https" or not parts.hostname:
            raise CloudError("云端返回的上传地址不是 https 地址，已拒绝上传")
        method = str(res.get("method") or "PUT").upper()
        return file_id, url, method, _parse_upload_headers(res.get("upload_headers"))

    def _upload(self, audio: Path, workdir: Path | None) -> str:
        if cached := self._cached_file_id(audio, workdir):
            print("[·] 续用已上传的音轨")
            return cached
        size = Path(audio).stat().st_size
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            file_id, url, method, headers = self._upload_target()
            print(f"[·] 上传音轨（{size / 1e6:.0f} MB）…")
            try:
                status, text = self.uploader(method, url, headers, Path(audio), self.timeout_upload)
            except CloudError as exc:
                if not exc.retryable:  # 响应过大 / 地址无效等：重试也没用，原样抛出
                    raise
                last = exc
            else:
                if status < 300:
                    self._remember_upload(audio, workdir, file_id)
                    return file_id
                last = CloudError(UPLOAD_FAILED.format(status=status, code=_storage_code(text)))
                if status not in UPLOAD_RETRY_STATUS:
                    raise last
            self._backoff(attempt)
        raise CloudError(f"上传重试 {self.retries} 次仍失败：{last}", retryable=True)

    # ------------------------------------------------------------------ 业务
    def submit_asr(
        self,
        audio: Path | str,
        *,
        language: str = DEFAULT_LANGUAGE,
        speaker: bool = True,
        confidence: bool = True,
        client_token: str | None = None,
        workdir: Path | None = None,
    ) -> str:
        self._headers()  # 没 Key 先失败，不去读 / 传文件
        remote = str(audio).startswith(("mediakit://", "http://", "https://"))
        file_id = str(audio) if remote else self._upload(Path(audio), workdir)
        data = self._request("POST", SUBMIT_PATH, {
            "audio_url": file_id, "language": language,
            "enable_speaker_info": bool(speaker), "enable_confidence": bool(confidence),
            "client_token": client_token or uuid.uuid4().hex,
        }, self.timeout_submit)
        task_id = data.get("task_id") or (data.get("result") or {}).get("task_id")
        if not task_id:
            raise CloudError(f"未返回 task_id：{_redact(json.dumps(data, ensure_ascii=False), self.api_key)}")
        return str(task_id)

    def wait_task(self, task_id: str, total_timeout: float,
                  interval: float = 10.0) -> dict:
        """单次查询 + 自己轮询，便于显示进度、长音频不被单次请求超时误杀。
        返回把 result 拍平到顶层的 dict（与旧 mediakit-cli 输出同形，format_transcript 直接认）。"""
        deadline = time.monotonic() + total_timeout
        path = TASK_PATH.format(task_id=urllib.parse.quote(task_id, safe=""))
        last_status = ""
        while True:
            try:
                data = self._request("GET", path, None, self.timeout_poll)
            except CloudError as exc:
                if exc.status == NOT_FOUND:  # 任务已过期 / 不存在：当终态处理，下次重新提交
                    raise CloudError(TASK_GONE.format(msg=exc), terminal=True) from exc
                raise
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            # 状态可能在顶层，也可能在 result 里（真实形状未经真账号确认，两种都认）
            status = str(data.get("status") or result.get("status") or "").lower()
            last_status = status or last_status
            if status in DONE:
                meta = {k: v for k, v in data.items() if k != "result"}
                return {**meta, **result, "task_id": data.get("task_id") or task_id,
                        "status": status}
            if status in FAILED:
                msg = _redact(_error_message(data) or _error_message(result) or status, self.api_key)
                raise CloudError(f"任务失败：{msg}", terminal=True)
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
                token = _submit_token(workdir, audio)
                task_id = self.submit_asr(audio, workdir=workdir, client_token=token)
                _remember_task(workdir, audio, task_id)
                _clear_submit_token(workdir)
            else:
                print(f"[·] 续查上次的子任务：{task_id}")
            data = self.wait_task(task_id, total_timeout)
        except CloudError as exc:
            if not exc.retryable:  # 不是"响应丢了"一类：下次换新 token，避免拿回同一个失败结果
                _clear_submit_token(workdir)
            if exc.terminal:  # 云端判任务终态失败：下次重新提交，而不是 3 天内永远失败
                asr_state.clear(workdir)
            record_failure(workdir, "asr", str(exc), {"audio": Path(audio).name})
            raise
        # aicut 以"存在"判转写完成，必须原子写（GL-15）
        schema.write_json(Path(workdir) / "transcript_raw.json", data)
        asr_state.clear(workdir)  # 结果已落盘，任务号用完即弃
        (Path(workdir) / UPLOAD_CACHE).unlink(missing_ok=True)
        return data


def _submit_token(workdir: Path, audio: Path) -> str:
    """同一音频、未完成的提交复用同一个 client_token；记不下也照样提交（只是失去去重）。"""
    path = Path(workdir) / SUBMIT_TOKEN_FILE
    try:
        fp = asr_state.fingerprint(audio)
    except OSError:
        return uuid.uuid4().hex
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("backend") == BACKEND and data.get("audio") == fp \
                and isinstance(data.get("token"), str) and data["token"]:
            return data["token"]
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    token = uuid.uuid4().hex
    try:
        schema.write_json(path, {"backend": BACKEND, "audio": fp, "token": token})
    except OSError as exc:
        print(STATE_SAVE_FAILED.format(exc=exc))
    return token


def _clear_submit_token(workdir: Path) -> None:
    (Path(workdir) / SUBMIT_TOKEN_FILE).unlink(missing_ok=True)


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
        "context": {k: (Path(v).name if isinstance(v, str) and os.path.isabs(v) else v)
                    for k, v in context.items()},  # 绝对路径只留文件名（诊断包会带上）
        "at": _now(),
    })
    path.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=2), encoding="utf-8")
