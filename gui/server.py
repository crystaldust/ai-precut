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
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 让 gui 能 import pipeline

from pipeline import review, schema  # noqa: E402
PROJECTS = ROOT / "projects"
PRESETS = ROOT / "presets"
STATIC = Path(__file__).resolve().parent / "static"
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
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def project_path(name: str) -> Path:
    p = (PROJECTS / name).resolve()
    if PROJECTS.resolve() not in p.parents:
        raise ValueError("非法项目名")
    return p


def safe_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("项目名不能用斜杠或点")
    return name


def project_state(name: str) -> dict:
    pdir = project_path(name)
    cfg = jload(pdir / "project.json")
    if not cfg:
        raise FileNotFoundError(name)
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
    return {
        "project": cfg,
        "stages": stages,
        "versions": list(reversed(versions)),
        "segments": jload(work / "segments.json", {}).get("segments", []),
        "shots": jload(pdir / "shots.json", {}).get("shots", []),
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


# ------------------------------------------------------------------ 任务
def start_job(name: str, task: str, extra: list[str] | None = None) -> str:
    job_id = uuid.uuid4().hex[:8]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "log": [], "exit": None,
                        "started": time.time(), "task": task, "project": name}
    cmds = {
        "prepare": [PY, str(AICUT), "prepare", name],
        "build": [PY, str(AICUT), "build", name] + (extra or []),
    }
    if task not in cmds:
        raise ValueError("未知任务")

    def worker():
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        try:
            proc = subprocess.Popen(cmds[task], cwd=str(ROOT), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
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

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    # ---------- 基础响应
    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def _read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------- 视频（支持 Range，浏览器才能拖进度条）
    def _serve_media(self, path: Path) -> None:
        if not path.exists():
            return self._json({"error": "文件不存在"}, 404)
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
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path

        if p in ("/", "/index.html"):
            f = STATIC / "index.html"
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")

        if p.startswith("/static/"):
            f = (STATIC / p[len("/static/"):]).resolve()
            if STATIC.resolve() in f.parents and f.exists():
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype)
            return self._json({"error": "not found"}, 404)

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
            except (ValueError, OSError) as exc:
                return self._json({"error": str(exc)}, 400)

        if p == "/api/state":
            name = q.get("project", [""])[0]
            try:
                return self._json(project_state(name))
            except (FileNotFoundError, ValueError) as e:
                return self._json({"error": str(e)}, 404)

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
            parts = p[len("/media/"):].split("/")
            try:
                pdir = project_path(parts[0])
            except ValueError:
                return self._json({"error": "bad project"}, 400)
            if len(parts) == 2 and parts[1] == "proxy":
                return self._serve_media(pdir / "work/proxy.mp4")
            if len(parts) == 3 and parts[1] == "preview":
                return self._serve_media(pdir / "output" / parts[2] / "preview.mp4")
            return self._json({"error": "not found"}, 404)

        return self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        body = self._read_body()

        if p == "/api/new":
            try:
                name = safe_name(body.get("name", "").strip())
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            material = body.get("material", "")
            preset = body.get("preset", "纪实3min")
            title = (body.get("title") or name).strip()
            if not material:
                return self._json({"error": "缺少素材路径"}, 400)
            args = [PY, str(AICUT), "new", name, "--material", material,
                    "--preset", preset, "--title", title]
            r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True)
            if r.returncode != 0:
                return self._json({"error": (r.stdout + r.stderr)[-500:]}, 400)
            return self._json({"ok": True, "name": name})

        if p == "/api/pick":
            script = ('POSIX path of (choose file with prompt "选择一条视频素材" '
                      'of type {"public.movie"})')
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            path = r.stdout.strip()
            return self._json({"path": path if r.returncode == 0 else ""})

        if p == "/api/shots":
            name = q.get("project", [""])[0]
            try:
                pdir = project_path(name)
            except ValueError:
                return self._json({"error": "bad project"}, 400)
            shots = body.get("shots", [])
            clean = []
            for i, s in enumerate(shots, 1):
                clean.append({
                    "id": s.get("id") or f"sh{i:02d}",
                    "in": round(float(s.get("in", 0)), 3),
                    "out": round(float(s.get("out", 0)), 3),
                    "sub": s.get("sub", ""),
                    "note": s.get("note", ""),
                })
            jdump(pdir / "shots.json", {"project": jload(pdir / "project.json", {}).get("title", name),
                                        "source": jload(pdir / "project.json", {}).get("material", ""),
                                        "shots": clean})
            return self._json({"ok": True, "count": len(clean)})

        if p == "/api/job":
            name = body.get("project", "")
            task = body.get("task", "")
            extra = []
            if task == "build":
                v = body.get("version")
                if v:
                    extra += ["--version", v]
                if body.get("no_draft"):
                    extra.append("--no-draft")
            try:
                job_id = start_job(name, task, extra)
            except (ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"job_id": job_id})

        if p in ("/api/browse/level", "/api/browse/must"):
            name = body.get("project", "")
            sid = body.get("id", "")
            try:
                pdir = project_path(name)
            except ValueError:
                return self._json({"error": "bad project"}, 400)
            if not sid:
                return self._json({"error": "缺少 id"}, 400)
            work = pdir / "work"
            try:
                if p.endswith("level"):
                    review.set_level(work, sid, int(body.get("level")))
                else:
                    review.set_must(work, sid, bool(body.get("must")))
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True})

        if p == "/api/open":
            name = body.get("project", "")
            target = body.get("target", "project")
            try:
                pdir = project_path(name)
            except ValueError:
                return self._json({"error": "bad project"}, 400)
            if target == "jianying":
                subprocess.run(["open", "-a", "/Applications/VideoFusion-macOS.app"],
                               capture_output=True)
            else:
                subprocess.run(["open", str(pdir)], capture_output=True)
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


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
