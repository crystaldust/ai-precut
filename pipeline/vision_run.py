# -*- coding: utf-8 -*-
"""画面理解编排：浏览小样 → 分段画面代理 → 上传 → 云端理解 → 解析 → work/visual_timeline.json。

续跑（「停止分析」会直接杀进程，所以每一步的结果先落盘再做下一步）：
  * work/vision/state.json：key（浏览小样指纹 + 档位 + 提示词版本 + 段长）与每段的 file_id / task_id；
    key 变了 → 旧段结果全部作废；
  * work/vision/chunk_NNN.raw.json：云端已返回、还没解析完的原始输出（先落盘再清任务号、再记账）：
    这之后被杀，重跑直接用它，不重新提交、不重复记账（被杀在记账前只会少记一次）；
  * work/vision/chunk_NNN.json：一段的解析结果，有了就不再上传 / 提交；
  * 提交后立即记 task_id，下次直接续查，不重复计费；上传的 file_id 按 cloud.UPLOAD_TTL_S 续用。
已知窗口：提交返回到记下 task_id 之间被杀，或提交响应丢失后重试，会多出一个云端任务（接口是否接受
client_token 去重未验证，先不传）；上传后、记下 file_id 前被杀只是下次重传（上传不计费）。
同一项目同时跑两个分析进程（剪辑台 + 终端）不互斥，可能重复提交。
不碰 ASR 的 asr_task.json / asr_upload.json；失败写 failed.json（只有段号，不带路径和画面内容）；
画面结果不进诊断包（diagnostics.SAFE_WORK_FILES 不收 vision/ 与 visual_timeline.json）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from pipeline import cloud, media_io, schema, usage, vision, vision_proxy, vision_timeline

TOOL = "video-understand-router"
UPLOAD_LABEL = "画面"
VISION_DIR = "vision"
STATE_FILE = "state.json"
RESULT_NAME = "chunk_{index:03d}.json"
RAW_NAME = "chunk_{index:03d}.raw.json"
TIMELINE_FILE = "visual_timeline.json"
PARALLEL = 3                  # 同时处理的段数（429 由 CloudClient 退避）
VISION_TASK_TIMEOUT_S = 900   # 单段等待上限；超时可重试，下次续查同一任务
PARSE_ATTEMPTS = 2            # 看不懂就同一段重新提交一次
STATE_SCHEMA = 1

NO_DURATION = "读不出浏览小样的时长，没法给画面分段：重新生成浏览小样后再试"
ENCODE_FAILED = "第 {n} 段（{span}）的画面代理没生成出来：{exc}"
PARSE_FAILED = "第 {n} 段（{span}）的画面理解结果看不懂（已重新提交过一次）：{exc}"
CHUNK_DONE = "[·] 画面理解：第 {n}/{total} 段完成"
CHUNK_RESUME = "[·] 画面理解：第 {n} 段续查上次的任务"
USAGE_FAILED = "[!] 画面理解用量没记上（{exc}）"
LOCAL_IO_FAILED = "第 {n} 段（{span}）的本地文件读写失败（{kind}）：检查磁盘空间和项目目录权限后重试"
UPLOAD_STALE = "[·] 云端已不认第 {n} 段上次上传的画面，重新上传"


class VisionError(RuntimeError):
    """画面理解失败（不是云端调用本身的错误：时长、代理生成、结果看不懂、本地读写）。"""


class _Aborted(Exception):
    """别的段已遇到鉴权失败，这段不再上传 / 提交（不是独立的错误，不报给用户）。"""


_FAIL_LOCK = threading.Lock()  # failed.json 是读改写，多段同时失败时不能互相覆盖


def _record_failure(work: Path, error: str, index: int) -> None:
    with _FAIL_LOCK:
        cloud.record_failure(work, "vision", error, {"chunk": index})


def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def _span(chunk: dict) -> str:
    return f"{_mmss(chunk['start'])}–{_mmss(chunk['end'])}"


def _proxy(work: Path) -> Path:
    return Path(work) / "proxy.mp4"


def run_key(proxy: Path, setting: dict) -> str | None:
    """浏览小样（只看大小与修改时间：项目目录搬家不算变）+ 档位 + 提示词版本 + 段长。读不到 → None。"""
    try:
        st = Path(proxy).stat()
    except OSError:
        return None
    raw = json.dumps({"size": st.st_size, "mtime_ns": st.st_mtime_ns, "tier": setting["tier"],
                      "prompt": vision.PROMPT_VERSION, "chunk_s": vision.CHUNK_S}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ 给进度 / 就绪用的事实
def timeline_current(work: Path, cfg: dict) -> bool:
    """时间轴可读，且档位、提示词版本、浏览小样都与现在一致。"""
    setting = vision.normalize(cfg.get("vision"))
    if not setting["enabled"]:
        return False
    tl = _read(Path(work) / TIMELINE_FILE)
    key = run_key(_proxy(work), setting)
    return key is not None and tl is not None and isinstance(tl.get("events"), list) \
        and (tl.get("setting") or {}).get("tier") == setting["tier"] \
        and tl.get("prompt_version") == vision.PROMPT_VERSION and tl.get("key") == key


def chunks_ready(work: Path, cfg: dict) -> bool:
    """画面代理都已生成（或时间轴已是当前的，段视频已清理）。"""
    if timeline_current(work, cfg):
        return True
    setting = vision.normalize(cfg.get("vision"))
    vdir = Path(work) / VISION_DIR
    state = _read(vdir / STATE_FILE)
    if not setting["enabled"] or state is None or state.get("key") != run_key(_proxy(work), setting):
        return False
    total = state.get("total")
    return isinstance(total, int) and total > 0 and all(
        (vdir / RESULT_NAME.format(index=i)).exists()
        or media_io.is_complete(vision_proxy.chunk_path(vdir, i)) for i in range(total))


# ------------------------------------------------------------------ 状态
class _State:
    """work/vision/state.json 的线程安全读改写；每次改动立即原子落盘。"""

    def __init__(self, path: Path, key: str, total: int) -> None:
        self.path, self._lock = path, threading.Lock()
        old = _read(path)
        same = old is not None and old.get("key") == key and old.get("schema") == STATE_SCHEMA
        chunks = old.get("chunks") if same and isinstance(old.get("chunks"), dict) else {}
        self._data = {"schema": STATE_SCHEMA, "key": key, "total": total, "chunks": chunks}
        schema.write_json(path, self._data)

    def get(self, index: int) -> dict:
        with self._lock:
            entry = self._data["chunks"].get(str(index))
            return dict(entry) if isinstance(entry, dict) else {}

    def set(self, index: int, **fields) -> None:
        with self._lock:
            entry = {**(self._data["chunks"].get(str(index)) or {}), **fields}
            self._data = {**self._data, "chunks": {**self._data["chunks"], str(index): entry}}
            schema.write_json(self.path, self._data)


def _reset_dir(vdir: Path, key: str) -> None:
    """key 变了：只删本模块自己的文件（段视频、完成标记、段结果、状态）。"""
    state = _read(vdir / STATE_FILE)
    if state is None or state.get("key") == key:
        return
    for pattern in ("chunk_*.mp4", "chunk_*.mp4.done", "chunk_*.json", STATE_FILE):
        for p in vdir.glob(pattern):
            p.unlink(missing_ok=True)


# ------------------------------------------------------------------ 一段
class _Chunk:
    """一段：编码 → 上传 → 提交 → 等结果 → 解析 → 落盘；每一步都可从盘上的状态接着做。"""

    def __init__(self, ctx: "_Run", chunk: dict) -> None:
        self.ctx, self.chunk, self.i = ctx, chunk, chunk["index"]
        self.n = self.i + 1
        self.result_path = ctx.vdir / RESULT_NAME.format(index=self.i)
        self.raw_path = ctx.vdir / RAW_NAME.format(index=self.i)
        self.clip = vision_proxy.chunk_path(ctx.vdir, self.i)

    def cached(self) -> dict | None:
        data = _read(self.result_path)
        if data is None or data.get("key") != self.ctx.key or not isinstance(data.get("events"), list):
            return None
        return data

    def encode(self) -> None:
        if media_io.is_complete(self.clip, source=self.ctx.proxy):
            return
        try:
            vision_proxy.encode_chunk(self.ctx.proxy, self.chunk, self.clip, runner=self.ctx.runner)
        except media_io.MediaError as exc:
            raise VisionError(ENCODE_FAILED.format(n=self.n, span=_span(self.chunk), exc=exc)) from exc

    def _file_id(self) -> tuple[str, bool]:
        """(file_id, 是否续用的旧上传)。"""
        entry, client = self.ctx.state.get(self.i), self.ctx.client()
        expires = entry.get("upload_expires")
        if entry.get("file_id") and entry.get("account") == client.key_id() \
                and isinstance(expires, (int, float)) and time.time() < expires:
            return entry["file_id"], True
        file_id = client.upload(self.clip, tool=TOOL, label=UPLOAD_LABEL)
        self.ctx.state.set(self.i, file_id=file_id, upload_expires=time.time() + cloud.UPLOAD_TTL_S,
                           account=client.key_id())
        return file_id, False

    def _submit(self) -> str:
        file_id, reused = self._file_id()
        payload = {"video_urls": [file_id], "prompt": vision_timeline.PROMPT,
                   **vision.tier_params(self.ctx.setting["tier"])}
        try:
            task_id = self.ctx.client().submit_tool(TOOL, payload)
        except cloud.CloudError as exc:
            # 续用的上传被云端作废（业务拒绝、非鉴权）→ 重传、再提交一次（同 cloud.submit_asr，KI-75）
            if not reused or exc.retryable or exc.status in cloud.AUTH_STATUS:
                raise
            print(UPLOAD_STALE.format(n=self.n))
            self.ctx.state.set(self.i, file_id=None)
            file_id, _ = self._file_id()
            task_id = self.ctx.client().submit_tool(TOOL, {**payload, "video_urls": [file_id]})
        self.ctx.state.set(self.i, task_id=task_id)  # 先落盘再等结果：被杀后续查，不重复计费
        return task_id

    def _pending_raw(self) -> tuple[str, int] | None:
        raw = _read(self.raw_path)
        if raw is None or raw.get("key") != self.ctx.key or not isinstance(raw.get("text"), str):
            return None
        tokens = raw.get("tokens")
        return raw["text"], tokens if isinstance(tokens, int) and tokens >= 0 else 0

    def _ask(self) -> tuple[str, int]:
        """拿一次模型输出，返回 (文本, 这次的 tokens)。顺序：原始输出落盘 → 清任务号 → 记账。"""
        if (pending := self._pending_raw()) is not None:  # 上次拿到结果后被杀：不重新提交、不再记账
            self.ctx.state.set(self.i, task_id=None)
            return pending
        if self.ctx.abort.is_set():
            raise _Aborted
        task_id = self.ctx.state.get(self.i).get("task_id")
        if task_id:
            print(CHUNK_RESUME.format(n=self.n))
        else:
            task_id = self._submit()
        data = self.ctx.client().wait_task(task_id, VISION_TASK_TIMEOUT_S)
        contents = data.get("contents")
        first = contents[0] if isinstance(contents, list) and contents else ""
        text = first if isinstance(first, str) else ""
        tu = data.get("token_usage") if isinstance(data.get("token_usage"), dict) else {}
        tokens = usage.total_of({"total_tokens": tu.get("total_tokens"),
                                 "prompt_tokens": tu.get("input_tokens"),
                                 "completion_tokens": tu.get("output_tokens")})
        schema.write_json(self.raw_path, {"key": self.ctx.key, "text": text, "tokens": tokens})
        self.ctx.state.set(self.i, task_id=None)
        try:
            usage.record_vision(self.ctx.work, tu)
        except OSError as exc:  # 记不了账不能让已经付费的结果作废；说出来
            print(USAGE_FAILED.format(exc=exc))
        return text, tokens

    def _understand(self) -> tuple[list[dict], int]:
        tokens, last = 0, None
        for _ in range(PARSE_ATTEMPTS):
            text, used = self._ask()
            tokens += used
            try:
                return vision_timeline.parse_contents(text), tokens
            except vision_timeline.TimelineParseError as exc:
                self.raw_path.unlink(missing_ok=True)  # 看不懂的输出不留：下一轮重新提交
                last = exc
        raise VisionError(PARSE_FAILED.format(n=self.n, span=_span(self.chunk), exc=last)) from last

    def process(self) -> dict:
        try:
            return self._process()
        except cloud.CloudError as exc:
            if exc.terminal:  # 云端判这段任务终态失败：下次重新上传、重新提交
                self.ctx.state.set(self.i, task_id=None, file_id=None)
            if exc.status in cloud.AUTH_STATUS:  # Key 不对：其它段再试也一样，别再上传
                self.ctx.abort.set()
            _record_failure(self.ctx.work, str(exc), self.i)
            raise
        except VisionError as exc:
            _record_failure(self.ctx.work, str(exc), self.i)
            raise
        except OSError as exc:  # 段视频 / 状态 / 结果读写失败：不带路径
            err = VisionError(LOCAL_IO_FAILED.format(n=self.n, span=_span(self.chunk),
                                                     kind=type(exc).__name__))
            _record_failure(self.ctx.work, str(err), self.i)
            raise err from exc

    def _process(self) -> dict:
        if (done := self.cached()) is not None:
            return done
        if self.ctx.abort.is_set():
            raise _Aborted
        self.encode()
        events, tokens = self._understand()
        result = {"key": self.ctx.key, "chunk": dict(self.chunk), "events": events, "tokens": tokens}
        schema.write_json(self.result_path, result)
        self.raw_path.unlink(missing_ok=True)
        print(CHUNK_DONE.format(n=self.n, total=self.ctx.total))
        return result


# ------------------------------------------------------------------ 整体
class _Run:
    """一次运行共享的东西：状态、懒建的云端客户端、中止标志。"""

    def __init__(self, work: Path, setting: dict, proxy: Path, key: str, total: int,
                 client_factory: Callable, runner) -> None:
        self.work, self.setting, self.proxy, self.key, self.total = Path(work), setting, Path(proxy), \
            key, total
        self.vdir = self.work / VISION_DIR
        self.runner = runner
        self._factory, self._client, self._lock = client_factory, None, threading.Lock()
        self.abort = threading.Event()
        self.vdir.mkdir(parents=True, exist_ok=True)
        _reset_dir(self.vdir, key)
        self.state = _State(self.vdir / STATE_FILE, key, total)

    def client(self):
        with self._lock:  # 第一次真正要上传 / 提交时才建（全部命中缓存时连 Key 都不读）
            if self._client is None:
                self._client = self._factory()
            return self._client


def _collect(futures: list) -> list[dict]:
    """等所有段跑完（成功的段都已落盘），再抛第一个出错段的错误（因中止而没做的段不算错误）。"""
    results, first_error = [], None
    for fut in futures:
        try:
            results.append(fut.result())
        except _Aborted:
            continue
        except Exception as exc:  # noqa: BLE001 — 先收集，最后统一抛
            first_error = first_error or exc
    if first_error is not None:
        raise first_error
    return results


def _cleanup_clips(vdir: Path) -> None:
    for pattern in ("chunk_*.mp4", "chunk_*.mp4.done"):
        for p in vdir.glob(pattern):
            p.unlink(missing_ok=True)


def run(work: Path, cfg: dict, proxy: Path, *, client_factory: Callable = cloud.CloudClient,
        runner=subprocess.run, parallel: int = PARALLEL) -> dict:
    """未开启 → {"skipped": True}；否则返回时间轴（已原子写到 work/visual_timeline.json）。"""
    setting = vision.normalize(cfg.get("vision"))
    if not setting["enabled"]:
        return {"skipped": True}
    work = Path(work)
    if timeline_current(work, cfg):
        return _read(work / TIMELINE_FILE) or {}
    duration = media_io.duration_or_zero(proxy)
    key = run_key(proxy, setting)
    if duration <= 0 or key is None:
        raise VisionError(NO_DURATION)
    chunks = vision_proxy.plan_chunks(duration)
    ctx = _Run(work, setting, proxy, key, len(chunks), client_factory, runner)
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = [pool.submit(_Chunk(ctx, c).process) for c in chunks]
        try:
            wait(futures)
        except BaseException:  # Ctrl-C：没开始的段不再做，正在做的段做完当前一步就停
            ctx.abort.set()
            for fut in futures:
                fut.cancel()
            raise
    results = _collect(futures)
    timeline = {**vision_timeline.build(results, duration, setting), "key": key}
    schema.write_json(work / TIMELINE_FILE, timeline)
    _cleanup_clips(ctx.vdir)
    return timeline
