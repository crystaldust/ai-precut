#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剪辑台 · 本地网页服务（给没有技术背景的剪辑师用）。

只监听 127.0.0.1，不联网。前端是 gui/static/index.html。
后端不重复实现业务逻辑，一律调用 aicut.py，保证 GUI 和命令行行为完全一致。

启动：
    python3 gui/server.py            # 默认 http://127.0.0.1:8765
    python3 gui/server.py --port 8800 --open
"""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 让 gui 能 import pipeline

from pipeline import notices, proc, review, schema, select, style  # noqa: E402

proc.ensure_bundled_path()  # 打包后优先用 App 自带的 ffmpeg
PROJECTS = proc.user_data_root()
PRESETS = ROOT / "presets"
STATIC = (proc.resource_path("gui", "static") if proc.FROZEN
          else Path(__file__).resolve().parent / "static")
PICKER = None  # 由桌面壳注入（pywebview 的文件选择框）

# ---- GL-05：本地服务访问控制
API_TOKEN = os.urandom(32).hex()  # 每次启动随机生成；页面加载时由服务端注入
TOKEN_HEADER = "X-AICUT-Token"
TOKEN_PLACEHOLDER = b"__AICUT_TOKEN__"
TOKEN_EXPIRED_MSG = "页面已过期，请刷新"  # 浏览器模式下服务重启后，旧标签页会看到它
ALLOWED_HOSTNAMES = ("127.0.0.1", "localhost")
JSON_CTYPE = "application/json"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# 页面全是内联脚本/样式和内联事件，所以 script-src 需要 'unsafe-inline'；没有任何外部资源
PAGE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'")
MAX_BODY_BYTES = 2 * 1024 * 1024  # 请求体上限：分镜表再大也到不了 2 MB
REQUEST_TIMEOUT_S = 60            # 单次 socket 读写超时，慢速/半开连接不会永久占住线程
INTERNAL_ERROR_MSG = "服务内部错误，请重试；如果反复出现请把终端里的报错发给开发"


def run_aicut(args: list[str]) -> tuple[int, str]:
    """执行一条 aicut 命令；打包后必须同进程，不能再拉起 App 自身。"""
    if proc.FROZEN:
        import contextlib
        import io
        from aicut import run_cli
        buf = io.StringIO()
        old_argv = sys.argv
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = run_cli(args)
        except Exception as exc:  # noqa: BLE001
            code, _ = 1, buf.write(f"[错误] {exc}\n")
        finally:
            sys.argv = old_argv
        return code, buf.getvalue()
    r = subprocess.run([PY, str(AICUT), *args], cwd=str(ROOT), stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def set_picker(fn) -> None:
    global PICKER
    PICKER = fn
AICUT = ROOT / "aicut.py"
PY = sys.executable

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ------------------------------------------------------------------ 工具
def jload(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def jdump(p: Path, obj) -> None:
    schema.write_json(p, obj)


class BadRequest(ValueError):
    """请求体不合法：必须返回 4xx，绝不能当空请求继续写盘（GL-18）。"""

    def __init__(self, msg: str, code: int = 400) -> None:
        super().__init__(msg)
        self.code = code


def project_path(name: str) -> Path:
    schema.check_project_name(name)  # GL-06：白名单在前，下面的包含检查是第二道防线
    p = (PROJECTS / name).resolve()
    if PROJECTS.resolve() not in p.parents:
        raise ValueError("非法项目名")
    return p


def existing_project(name: str) -> Path:
    pdir = project_path(name)
    if not (pdir / "project.json").exists():
        raise FileNotFoundError(f"项目不存在：{name}")
    return pdir


def safe_name(name: str) -> str:
    return schema.check_project_name(name)


def preset_names() -> set[str]:
    return {f.stem for f in PRESETS.glob("*.json")}


def project_state(name: str) -> dict:
    pdir = project_path(name)
    cfg = jload(pdir / "project.json")
    if not cfg:
        raise FileNotFoundError(name)
    schema.ensure_supported(cfg)  # 新版程序建的项目不能让旧界面去改
    work = pdir / "work"
    stages = [
        {"key": "ingest", "label": "素材台账", "done": (work / "materials.json").exists()},
        {"key": "audio", "label": "抽音轨", "done": (work / "audio/asr.wav").exists()},
        {"key": "transcribe", "label": "语音转写", "done": (work / "transcript.md").exists()},
        {"key": "junk", "label": "废片检测", "done": (work / "junk_report.csv").exists()},
        {"key": "brief", "label": "策划分派单", "done": (work / "brief.md").exists()},
        {"key": "shots", "label": "分镜表", "done": (pdir / "shots.json").exists()},
    ]
    versions = []
    for d in sorted((pdir / "output").glob("v*"), key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 0):
        if not d.is_dir():
            continue
        tl = jload(d / "timeline.json", {})
        total = 0.0
        if tl.get("video"):
            total = max((s["timeline_in"] + s["out"] - s["in"]) for s in tl["video"])
        versions.append({
            "name": d.name,
            "preview": (d / "preview.mp4").exists(),
            "shots": len(tl.get("video", [])),
            "duration": round(total, 1),
            "draft": f"{cfg.get('title', name)}_{d.name}",
            "mtime": time.strftime("%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
        })
    manual = jload(pdir / "shots.json", {}).get("shots", [])
    selected = jload(work / "shots-selected.json", {}).get("shots", [])
    return {
        "project": cfg,
        "stages": stages,
        "versions": list(reversed(versions)),
        "segments": jload(work / "segments.json", {}).get("segments", []),
        # 没有手存分镜表时用选段结果预填；有就不覆盖（M2）
        "shots": manual or selected,
        "shots_from_selection": not manual and bool(selected),
        "selection": select.summary(jload(work / "selection.json")),
        "warnings": notices.project_warnings(work),
        "junk": jload(work / "junk_report.json", {}).get("items", []),
        "material_duration": (jload(work / "materials.json", {}).get("items") or [{}])[0].get("duration", 0),
        "has_proxy": (work / "proxy.mp4").exists(),
        "has_transcript": (work / "transcript.md").exists(),
    }


# ------------------------------------------------------------------ 浏览页数据
def browse_payload(name: str) -> dict:
    pdir = project_path(name)
    cfg = jload(pdir / "project.json") or {}
    try:
        cfg = schema.load(pdir / "project.json")
    except Exception:  # noqa: BLE001 - 旧项目读不出来就用原始 json
        pass
    work = pdir / "work"
    scored = jload(work / "segments_scored.json")
    if not scored:
        raise FileNotFoundError("还没有三档判定，先跑 analyze/text/score")

    overrides = review.load(work)
    segments = review.apply(scored["segments"], overrides)

    shots = jload(pdir / "shots.json", {}).get("shots", [])

    def in_cut(s):
        return any(max(0, min(s["end"], sh["in"] + sh["out"] - sh["in"]) -
                       max(s["start"], sh["in"])) > 1.0 for sh in shots)

    topics = {t["name"]: dict(t) for t in scored.get("topics", [])}
    for s in segments:
        t = topics.setdefault(s.get("topic") or "未归类",
                             {"name": s.get("topic") or "未归类", "must": False,
                              "count": 0, "duration": 0.0, "usable_dur": 0.0,
                              "budget": 0})
        t["count"] += 1
        t["duration"] += s["end"] - s["start"]
        if s["level"] == 3:
            t["usable_dur"] += s["end"] - s["start"]

    summary = jload(work / "content_summary.json") or {}
    try:
        material_duration = jload(work / "materials.json")["items"][0]["duration"]
    except Exception:  # noqa: BLE001
        material_duration = 0.0

    for s in segments:
        s["inCut"] = in_cut(s)
        s["dur"] = round(s["end"] - s["start"], 2)

    return {
        "project": {"name": cfg.get("name", name), "title": cfg.get("title", name),
                    "preset": cfg.get("preset"), "platform": cfg.get("platform"),
                    "target_duration": cfg.get("target_duration")},
        "material_duration": material_duration,
        "summary": summary,
        "counts": {k: sum(1 for s in segments if s["level"] == v)
                   for k, v in (("waste", 1), ("pending", 2), ("usable", 3))},
        "topics": sorted(topics.values(), key=lambda t: -t["duration"]),
        "segments": segments,
        "has_overrides": bool(overrides),
    }


def confirm_payload(name: str) -> dict:
    pdir = project_path(name)
    work = pdir / "work"
    q = jload(work / "questions.json")
    summary = jload(work / "content_summary.json") or {}
    answers = jload(work / "brief_answers.json") or {}
    if q is None:
        raise FileNotFoundError("还没有决策问题，先跑 questions")
    return {"questions": q["questions"], "fallback": q.get("fallback", False),
            "summary": summary, "answers": answers.get("answers", {}),
            "confirmed": answers.get("confirmed", False)}


# ------------------------------------------------------------------ 任务
JOB_COMMANDS = {"prepare": ["prepare"], "build": ["build"], "select": ["select"]}


def start_job(name: str, task: str, extra: list[str] | None = None) -> str:
    if task not in JOB_COMMANDS:  # 先校验再登记，未知任务不留幽灵 running
        raise ValueError("未知任务")
    argv = [*JOB_COMMANDS[task], name, *(extra or [])]
    job_id = uuid.uuid4().hex[:8]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "log": [], "exit": None,
                        "started": time.time(), "task": task, "project": name}

    if proc.FROZEN:
        class _JobLog:
            """把 stdout 逐行灌进任务日志，界面才能实时看到进度。"""
            def __init__(self, jid: str) -> None:
                self.jid = jid
                self.buf = ""
                self.encoding = "utf-8"

            def write(self, chunk: str) -> int:
                if not chunk:
                    return 0
                self.buf += chunk
                *lines, self.buf = self.buf.split("\n")
                if lines:
                    with JOBS_LOCK:
                        JOBS[self.jid]["log"].extend(lines)
                return len(chunk)

            def flush(self) -> None:
                if self.buf:
                    with JOBS_LOCK:
                        JOBS[self.jid]["log"].append(self.buf)
                    self.buf = ""

        def worker_frozen():
            import contextlib
            from aicut import run_cli
            sink = _JobLog(job_id)
            old_argv = sys.argv
            try:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    code = run_cli(argv)
            except Exception as exc:  # noqa: BLE001
                code = -1
                sink.write(f"[错误] {exc}\n")
            finally:
                sink.flush()
                sys.argv = old_argv
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "done" if code == 0 else "failed"
                JOBS[job_id]["exit"] = code
                JOBS[job_id]["log"].append(f"[退出码] {code}")

        threading.Thread(target=worker_frozen, daemon=True).start()
        return job_id

    def worker():
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        try:
            proc = subprocess.Popen([PY, str(AICUT), *argv], cwd=str(ROOT),
                                    stdin=subprocess.DEVNULL,  # input() 不能卡住任务
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, env=env)
            for line in proc.stdout:
                with JOBS_LOCK:
                    JOBS[job_id]["log"].append(line.rstrip())
            code = proc.wait()
        except Exception as e:  # noqa: BLE001
            code = -1
            with JOBS_LOCK:
                JOBS[job_id]["log"].append(f"[错误] {e}")
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done" if code == 0 else "failed"
            JOBS[job_id]["exit"] = code
            JOBS[job_id]["log"].append(f"[退出码] {code}")

    threading.Thread(target=worker, daemon=True).start()
    return job_id


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "aicut-gui/1.0"
    timeout = REQUEST_TIMEOUT_S

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    # ---------- 基础响应
    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _security_headers(self) -> None:
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)

    def _send_page(self, f: Path) -> None:
        """HTML 页面：把占位符替换成本次启动的 token。"""
        body = f.read_bytes().replace(TOKEN_PLACEHOLDER, API_TOKEN.encode())
        return self._send(200, body, "text/html; charset=utf-8",
                          {"Content-Security-Policy": PAGE_CSP})

    # ---------- 兜底：任何请求都不能直接断连
    def send_response(self, code, message=None):
        self._started = True
        super().send_response(code, message)

    def _safely(self, route) -> None:
        self._started = False
        try:
            route()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:  # noqa: BLE001 - 未预期的错误：记到终端，给前端 500
            traceback.print_exc(file=sys.stderr)
            if self._started:  # 响应已经开始写，只能断开
                self.close_connection = True
                return
            try:
                self._json({"error": INTERNAL_ERROR_MSG}, 500)
            except OSError:
                self.close_connection = True

    def do_GET(self):  # noqa: N802
        self._safely(self._route_get)

    def do_POST(self):  # noqa: N802
        self._safely(self._route_post)

    # ---------- 访问控制（GL-05）
    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"{h}:{port}" for h in ALLOWED_HOSTNAMES}

    def _deny_reason(self, path: str, post: bool) -> tuple[int, str] | None:
        """返回 (状态码, 原因)；None 表示放行。"""
        hosts = self._allowed_hosts()
        if (self.headers.get("Host") or "").lower() not in hosts:
            return 403, "拒绝：Host 不是本机剪辑台"
        if post:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {f"http://{h}" for h in hosts}:
                return 403, "拒绝：跨站请求"
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != JSON_CTYPE:
                return 415, f"请求必须是 {JSON_CTYPE}"
        if path.startswith("/api/"):
            given = self.headers.get(TOKEN_HEADER) or ""
            if not hmac.compare_digest(given.encode(), API_TOKEN.encode()):
                return 403, TOKEN_EXPIRED_MSG
        return None

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def _read_body(self) -> dict:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise BadRequest("缺少 Content-Length", 411)
        if not re.fullmatch(r"[0-9]{1,12}", raw.strip()):
            raise BadRequest("Content-Length 非法")
        n = int(raw)
        if n > MAX_BODY_BYTES:
            raise BadRequest(f"请求体过大（上限 {MAX_BODY_BYTES // 1024 // 1024} MB）", 413)
        if n == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequest(f"请求体不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise BadRequest("请求体必须是 JSON 对象")
        return data

    # ---------- 视频（支持 Range，浏览器才能拖进度条）
    def _serve_media(self, path: Path, root: Path) -> None:
        """只发项目目录内的普通文件：符号链接逃逸、目录一律 404。"""
        try:
            real = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return self._json({"error": "文件不存在"}, 404)
        if root.resolve() not in real.parents or not real.is_file():
            return self._json({"error": "文件不存在"}, 404)
        path = real
        size = path.stat().st_size
        ctype = "video/mp4"
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            start = int(m.group(1) or 0) if m else 0
            end = int(m.group(2)) if m and m.group(2) else size - 1
            end = min(end, size - 1)
            length = max(0, end - start + 1)
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self._security_headers()
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)
        else:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self._security_headers()
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return

    # ---------- 路由
    def _route_get(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        deny = self._deny_reason(p, post=False)
        if deny:
            return self._json({"error": deny[1]}, deny[0])

        if p in ("/", "/index.html"):
            return self._send_page(STATIC / "index.html")

        if p.startswith("/static/"):
            f = (STATIC / p[len("/static/"):]).resolve()
            if STATIC.resolve() in f.parents and f.exists():
                if f.suffix == ".html":
                    return self._send_page(f)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype)
            return self._json({"error": "not found"}, 404)

        if p == "/api/health":
            import shutil as _shutil
            ff = _shutil.which("ffmpeg")
            ver = ""
            if ff:
                try:
                    ver = subprocess.run([ff, "-version"], capture_output=True, text=True,
                                         timeout=5).stdout.splitlines()[0][:60]
                except Exception:  # noqa: BLE001
                    ver = "?"
            return self._json({
                "frozen": proc.FROZEN,
                "app_root": str(proc.app_root()),
                "projects_root": str(proc.user_data_root()),
                "ffmpeg": ff, "ffmpeg_version": ver,
                "ffprobe": _shutil.which("ffprobe"),
            })

        if p == "/api/projects":
            items = []
            for f in sorted(PROJECTS.glob("*/project.json")):
                c = jload(f, {})
                pdir = f.parent
                vs = sorted([d.name for d in (pdir / "output").glob("v*") if d.is_dir()])
                items.append({"name": c.get("name", pdir.name), "title": c.get("title", ""),
                              "preset": c.get("preset", ""), "versions": vs})
            return self._json({"projects": items})

        if p == "/api/presets":
            out = []
            for f in sorted(PRESETS.glob("*.json")):
                c = jload(f, {})
                out.append({"key": f.stem, "name": c.get("name", f.stem),
                            "platform": c.get("platform"), "duration": c.get("duration")})
            return self._json({"presets": out})

        if p == "/api/browse":
            name = q.get("project", [""])[0]
            try:
                return self._json(browse_payload(name))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except review.OverridesCorrupt as exc:  # 必须在 ValueError 之前
                return self._json({"error": str(exc)}, 409)
            except (ValueError, OSError) as exc:
                return self._json({"error": str(exc)}, 400)

        if p == "/api/calibrate":
            name = q.get("project", [""])[0]
            try:
                cfg = schema.load(existing_project(name) / "project.json")
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except schema.SchemaTooNew as exc:
                return self._json({"error": str(exc)}, 409)
            except (ValueError, OSError) as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"calibration": style.normalize(cfg.get("calibration")),
                               "directive": style.directive(cfg.get("calibration"))})

        if p == "/api/confirm":
            name = q.get("project", [""])[0]
            try:
                return self._json(confirm_payload(name))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)

        if p == "/api/state":
            name = q.get("project", [""])[0]
            try:
                return self._json(project_state(name))
            except FileNotFoundError as e:
                return self._json({"error": f"项目不存在：{e}"}, 404)
            except schema.SchemaTooNew as e:
                return self._json({"error": str(e)}, 409)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)

        if p.startswith("/api/job/"):
            job_id = p.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job:
                    return self._json({"error": "job not found"}, 404)
                return self._json({"status": job["status"], "log": job["log"],
                                   "exit": job["exit"], "task": job["task"]})

        if p.startswith("/media/"):
            # /media/<project>/proxy  |  /media/<project>/preview/v2
            # GL-21：先按 / 切分再逐段解码，%2F 不会制造新的路径层级
            parts = [unquote(x) for x in p[len("/media/"):].split("/")]
            try:
                pdir = project_path(parts[0])
            except ValueError:
                return self._json({"error": "bad project"}, 400)
            if len(parts) == 2 and parts[1] == "proxy":
                return self._serve_media(pdir / "work/proxy.mp4", pdir)
            if len(parts) == 3 and parts[1] == "preview":
                try:
                    version = schema.check_version(parts[2])
                except ValueError as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._serve_media(pdir / "output" / version / "preview.mp4", pdir)
            return self._json({"error": "not found"}, 404)

        return self._json({"error": "not found"}, 404)

    def _route_post(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        deny = self._deny_reason(p, post=True)  # 未授权的请求连 body 都不读
        if deny:
            return self._json({"error": deny[1]}, deny[0])
        try:
            body = self._read_body()
        except BadRequest as exc:
            return self._json({"error": str(exc)}, exc.code)

        if p == "/api/new":
            try:
                name = safe_name(body.get("name", ""))  # 首尾空格直接拒绝，不偷偷 strip
                raw_title = body.get("title") or name
                title = schema.check_title(
                    raw_title.strip() if isinstance(raw_title, str) else raw_title)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            material = body.get("material", "")
            preset = body.get("preset", "纪实3min")
            if not isinstance(material, str) or not material:
                return self._json({"error": "缺少素材路径"}, 400)
            if not isinstance(preset, str) or preset not in preset_names():
                return self._json({"error": f"未知预设：{preset}"}, 400)
            # --x=value 形式：以 - 开头的值不会被 argparse 当成选项
            args = ["new", name, f"--material={material}", f"--preset={preset}",
                    f"--title={title}"]
            if body.get("target") is not None:  # GUI 总是传，CLI 就不会停在 input() 上
                try:
                    args.append(f"--target={schema.check_target_duration(body['target'])}")
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            code, out = run_aicut(args)
            if code != 0:
                return self._json({"error": out[-500:] or "创建失败"}, 400)
            return self._json({"ok": True, "name": name})

        if p == "/api/pick":
            if PICKER is not None:
                try:
                    picked = PICKER()
                except Exception:  # noqa: BLE001
                    picked = []
                path = picked[0] if picked else ""
                return self._json({"path": path})
            script = ('POSIX path of (choose file with prompt "选择一条视频素材" '
                      'of type {"public.movie"})')
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            path = r.stdout.strip()
            return self._json({"path": path if r.returncode == 0 else ""})

        if p == "/api/shots":
            name = q.get("project", [""])[0]
            try:
                pdir = existing_project(name)
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            shots = body.get("shots")
            if not isinstance(shots, list):
                return self._json({"error": "缺少 shots 列表，未保存"}, 400)
            try:
                # GL-23：id 合法且唯一；KI-31：入出点是非负有限数且出点晚于入点
                clean = schema.clean_shots(shots)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            jdump(pdir / "shots.json", {"project": jload(pdir / "project.json", {}).get("title", name),
                                        "source": jload(pdir / "project.json", {}).get("material", ""),
                                        "shots": clean})
            return self._json({"ok": True, "count": len(clean)})

        if p == "/api/job":
            name = body.get("project", "")
            task = body.get("task", "")
            extra = []
            try:
                existing_project(name)
                if task == "build":
                    v = body.get("version")
                    if v:
                        extra += ["--version", schema.check_version(v)]
                    if body.get("no_draft"):
                        extra.append("--no-draft")
                if task == "select" and body.get("target") is not None:
                    extra += ["--target", str(schema.check_target_duration(body["target"]))]
                job_id = start_job(name, task, extra)
            except (ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"job_id": job_id})

        if p == "/api/calibrate":
            try:
                pdir = existing_project(body.get("project", ""))
                cfg = schema.load(pdir / "project.json")
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except schema.SchemaTooNew as exc:
                return self._json({"error": str(exc)}, 409)
            except (ValueError, OSError) as exc:
                return self._json({"error": str(exc)}, 400)
            cfg["calibration"] = style.normalize(body.get("calibration") or {})
            schema.save(pdir / "project.json", cfg)
            return self._json({"ok": True,
                               "directive": style.directive(cfg["calibration"])})

        if p == "/api/confirm/answers":
            try:
                pdir = existing_project(body.get("project", ""))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            work = pdir / "work"
            questions = jload(work / "questions.json")
            answers = body.get("answers") or {}
            from pipeline import select as selector
            rules = selector._rules(answers, questions)
            data = {"answers": answers,
                    "rules": rules,
                    "confirmed": bool(body.get("confirmed", False)),
                    "at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}
            jdump(pdir / "work/brief_answers.json", data)
            return self._json({"ok": True})

        if p in ("/api/browse/level", "/api/browse/must"):
            name = body.get("project", "")
            sid = body.get("id", "")
            try:
                pdir = existing_project(name)
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            if not sid:
                return self._json({"error": "缺少 id"}, 400)
            work = pdir / "work"
            try:
                if p.endswith("level"):
                    review.set_level(work, sid, int(body.get("level")))
                else:
                    review.set_must(work, sid, bool(body.get("must")))
            except review.OverridesCorrupt as exc:  # 必须在 ValueError 之前
                return self._json({"error": str(exc)}, 409)
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True})

        if p == "/api/open":
            name = body.get("project", "")
            target = body.get("target", "project")
            try:
                pdir = existing_project(name)
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            if target == "jianying":
                subprocess.run(["open", "-a", "/Applications/VideoFusion-macOS.app"],
                               capture_output=True)
            else:
                subprocess.run(["open", str(pdir)], capture_output=True)
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


def serve_in_background(start_port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    """给桌面壳用：起服务并返回 (server, url)，不阻塞。"""
    port = start_port
    srv = None
    for _ in range(8):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    if srv is None:
        raise RuntimeError("没有可用端口")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{port}/"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    srv = None
    port = args.port
    for _ in range(6):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    if srv is None:
        print("端口都被占用了，请关掉其他剪辑台窗口再试。")
        sys.exit(1)
    url = f"http://127.0.0.1:{port}/"
    print(f"剪辑台已启动：{url}")
    print("关闭这个窗口即退出。")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
