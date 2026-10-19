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
import re
import signal
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 让 gui 能 import pipeline

from pipeline.pyver import require_supported_python  # noqa: E402
require_supported_python()  # 旧解释器在这里就给出中文说明
from pipeline import applog, proc, review, schema, style  # noqa: E402
from gui import (  # noqa: E402
    confirm, desktop, jobs, maintenance, media, payloads, session, settings, support, views,
)
from gui.static_files import STATIC_FILES  # noqa: E402
from gui.jobs import (  # noqa: E402,F401 - 路由与测试都按 server.<名字> 引用
    JOB_COMMANDS, JOBS, JOBS_LOCK, JobConflict, run_aicut, start_job,
)

proc.ensure_bundled_path()  # 打包后优先用 App 自带的 ffmpeg
PROJECTS = proc.user_data_root()
PRESETS = ROOT / "presets"
STATIC = (proc.resource_path("gui", "static") if proc.FROZEN
          else Path(__file__).resolve().parent / "static")
PICKER = None  # 由桌面壳注入（pywebview 的文件选择框）

# ---- GL-05 / KI-88：本地服务访问控制。页面里不放任何秘密：入口地址带一次性 nonce，
# 兑换成 HttpOnly 会话 cookie；页面、/api/、/media/ 都只认 cookie（见 gui/session.py）
entry_url = session.entry_url  # 桌面壳与浏览器启动器用
AUTH_PREFIXES = ("/api/", "/media/")
TOKEN_EXPIRED_MSG = "页面已过期：请关掉这个页面，从剪辑台重新打开"  # 服务重启后旧标签页会看到它
GATE_PAGE = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>剪辑台</title>'
             '</head><body style="font-family:-apple-system,sans-serif;padding:48px;color:#333">'
             '<h2>请从剪辑台 App 打开</h2><p>这个页面需要从「AI 粗剪」App 里打开。'
             '浏览器模式：请重新双击「启动剪辑台」。</p></body></html>').encode()
ALLOWED_HOSTNAMES = ("127.0.0.1", "localhost")
JSON_CTYPE = "application/json"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# KI-53：脚本全部外置、事件走委托，script-src 只认同源文件；内联 style 属性很多、风险低，style-src 保留 inline（D9）
PAGE_CSP = ("default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'")
MAX_BODY_BYTES = 2 * 1024 * 1024  # 请求体上限：分镜表再大也到不了 2 MB
REQUEST_TIMEOUT_S = 60            # 单次 socket 读写超时，慢速/半开连接不会永久占住线程
NO_EXPORT_MSG = "这一版还没有导出 Windows 剪映包"
INTERNAL_ERROR_MSG = "服务内部错误，请重试；如果反复出现请点左下角「导出诊断包」发给开发"
LOG = applog.get("gui")


set_window_opener = desktop.set_window_opener  # 桌面壳注入（KI-36）


def set_picker(fn) -> None:
    global PICKER
    PICKER = fn


# ------------------------------------------------------------------ 工具
jload = views.jload


def jdump(p: Path, obj) -> None:
    schema.write_json(p, obj)


class ProjectCorrupt(Exception):
    """project.json 损坏：任何写操作都必须 409 拒绝（不是 ValueError，免得被各路由当 400 吞掉）。"""


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


def existing_project(name: str, *, strict: bool = True) -> Path:
    """项目存在才返回；strict（默认，所有写接口）时 project.json 必须读得懂，否则 ProjectCorrupt → 409。

    只有导出诊断包用 strict=False：项目坏了正是要导出诊断包的时候。
    """
    pdir = project_path(name)
    if not (pdir / "project.json").exists():
        raise FileNotFoundError(f"项目不存在：{name}")
    if strict:
        try:
            schema.read_json(pdir / "project.json")
        except schema.CorruptJSON as exc:
            raise ProjectCorrupt(str(exc)) from exc
    return pdir


def diagnostics_project(name: str) -> Path:
    return existing_project(name, strict=False)


def safe_name(name: str) -> str:
    return schema.check_project_name(name)


def preset_names() -> set[str]:
    return {f.stem for f in PRESETS.glob("*.json")}


def project_state(name: str) -> dict:
    return views.project_state(project_path(name), name)


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "aicut-gui/1.0"
    timeout = REQUEST_TIMEOUT_S

    def log_message(self, fmt, *args):  # 访问日志只到 debug（默认不落盘），不刷屏
        LOG.debug("%s %s", self.address_string(), fmt % args)

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
        if self.command == "HEAD":  # 审查修复 L11：HEAD 只回头
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _security_headers(self) -> None:
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)

    def _send_page(self, f: Path) -> None:
        return self._send(200, f.read_bytes(), "text/html; charset=utf-8",
                          {"Content-Security-Policy": PAGE_CSP})

    def _authed(self) -> bool:
        return session.has_valid_cookie(self.headers.get("Cookie"), self.server.server_address[1])

    def _page(self, f: Path, path: str, q: dict) -> None:
        """KI-88：页面只发给持会话 cookie 的；入口地址的 nonce 兑换成 cookie 后跳回去掉 nonce 的地址。"""
        if session.NONCE_PARAM in q:
            fresh = session.redeem(q[session.NONCE_PARAM][0])
            if fresh or self._authed():
                rest = {k: v for k, v in q.items() if k != session.NONCE_PARAM}
                extra = {"Location": path + ("?" + urlencode(rest, doseq=True, quote_via=quote)
                                             if rest else "")}
                if fresh:
                    extra["Set-Cookie"] = session.cookie_header(self.server.server_address[1])
                return self._send(302, b"", "text/plain; charset=utf-8", extra)
        elif self._authed():
            return self._send_page(f)
        return self._send(403, GATE_PAGE, "text/html; charset=utf-8",
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
        except ProjectCorrupt as exc:  # 损坏的项目：所有写接口统一 409，不能写进去
            if self._started:
                self.close_connection = True
                return
            self._json({"error": str(exc)}, 409)
        except Exception:  # noqa: BLE001 - 未预期的错误：记到终端，给前端 500
            traceback.print_exc(file=sys.stderr)
            LOG.exception("请求处理异常：%s %s", self.command, urlparse(self.path).path)
            if self._started:  # 响应已经开始写，只能断开
                self.close_connection = True
                return
            try:
                self._json({"error": INTERNAL_ERROR_MSG}, 500)
            except OSError:
                self.close_connection = True

    def do_GET(self):  # noqa: N802
        self._safely(self._route_get)

    def do_HEAD(self):  # noqa: N802 - 与 GET 同一套路由与校验，只是不发响应体
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
        if path.startswith(AUTH_PREFIXES) and not self._authed():
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

    def _serve_media(self, path: Path, root: Path) -> None:
        media.serve_file(self, path, root)

    # ---------- 任务（GL-17：互斥 / 取消；GL-02：处理素材前置检查）
    def _start_job(self, body: dict) -> None:
        name, task = body.get("project", ""), body.get("task", "")
        try:
            pdir = existing_project(name)
            title = (jload(pdir / "project.json", {}) or {}).get("title")
            extra = jobs.job_extra(pdir, task, body, title)
            settings.check_ready(pdir, task)  # prepare / questions 的告知与 Key（GL-02、KI-86）
            job_id = start_job(name, task, extra)
        except JobConflict as e:  # 含 StaleJob（job_id 为 None：上次留下的进程，界面无法接管）
            return self._json({"error": str(e), "job_id": e.job_id, "task": e.task,
                               "project": e.project}, 409)
        except settings.PrepareBlocked as e:
            return self._json({"error": str(e), "need": e.need, "missing": e.missing}, 409)
        except (ValueError, FileNotFoundError) as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"job_id": job_id})

    # ---------- 路由
    def _route_get(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        deny = self._deny_reason(p, post=False)
        if deny:
            return self._json({"error": deny[1]}, deny[0])

        if p in ("/", "/index.html"):
            return self._page(STATIC / "index.html", p, q)

        if p.startswith("/static/"):  # KI-52：只发白名单里的单段文件名
            name = p[len("/static/"):]
            f = STATIC / name
            if name in STATIC_FILES and f.is_file():
                if f.suffix == ".html":
                    return self._page(f, p, q)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype)
            return self._json({"error": "not found"}, 404)

        if p == "/api/health":
            return self._json(views.health_payload())

        if (hit := settings.handle_get(p) or support.handle_get(p)
                or maintenance.handle_get(p, q, existing_project)) is not None:
            return self._json(hit[1], hit[0])

        if p == "/api/projects":
            return self._json({"projects": views.projects_list(PROJECTS),
                               "stale_job": jobs.stale_job_view()})  # KI-71：界面顶部提示条

        if p == "/api/presets":
            return self._json(views.presets_payload(PRESETS))

        if p == "/api/browse":
            name = q.get("project", [""])[0]
            try:
                return self._json(payloads.browse(project_path(name), name))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
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
                return self._json(payloads.confirm(project_path(name)))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
                return self._json({"error": str(exc)}, 409)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)

        if p == "/api/state":
            name = q.get("project", [""])[0]
            try:
                return self._json(project_state(name))
            except FileNotFoundError as e:
                return self._json({"error": f"项目不存在：{e}"}, 404)
            except (schema.SchemaTooNew, schema.CorruptJSON) as e:  # CorruptJSON 必须在 ValueError 之前
                return self._json({"error": str(e)}, 409)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)

        if p.startswith("/api/job/"):
            view = jobs.job_view(p.rsplit("/", 1)[-1])
            if view is None:
                return self._json({"error": "job not found"}, 404)
            return self._json(view)

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

        if (hit := settings.handle_post(p, body)) is not None:
            return self._json(hit[1], hit[0])
        if (hit := support.handle_post(p, body, diagnostics_project)
                or maintenance.handle_post(p, body, existing_project)
                or desktop.handle_post(p, body, existing_project, self.server.server_address[1])) is not None:
            return self._json(hit[1], hit[0])

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
            # GL-20：--no-input，绝不停在 input() 上
            args = ["new", name, "--no-input", f"--material={material}", f"--preset={preset}",
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
            return self._start_job(body)

        if p.startswith("/api/job/") and p.endswith("/cancel"):
            try:
                return self._json({"ok": jobs.cancel_job(p[len("/api/job/"):-len("/cancel")])})
            except KeyError:
                return self._json({"error": "job not found"}, 404)

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
            calibration = style.normalize(body.get("calibration") or {})
            schema.update_project(pdir / "project.json", lambda c: {**c, "calibration": calibration})
            return self._json({"ok": True, "directive": style.directive(calibration)})

        if p == "/api/confirm/answers":
            try:  # KI-05：「保存并确认」后服务端自动起重新选段任务
                return self._json(confirm.save_answers(existing_project(body.get("project", "")),
                                                       body.get("project", ""), body))
            except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
                return self._json({"error": str(exc)}, 409)
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)

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
            if target == "export":  # GL-14：在访达中选中这一版的 Windows 包
                try:
                    version = schema.check_version(body.get("version"))
                except ValueError as exc:
                    return self._json({"error": str(exc)}, 400)
                title = (jload(pdir / "project.json", {}) or {}).get("title")
                zip_path = jobs.windows_zip(pdir, version, title)
                if not zip_path.is_file():
                    return self._json({"error": NO_EXPORT_MSG}, 404)
                subprocess.run(["open", "-R", str(zip_path)], capture_output=True)
            elif target == "jianying":
                subprocess.run(["open", "-a", "/Applications/VideoFusion-macOS.app"],
                               capture_output=True)
            else:
                subprocess.run(["open", str(pdir)], capture_output=True)
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


def report_stale_job() -> None:
    """启动时发现上次留下的任务还在跑：明确告诉用户，而不是悄悄允许再起一个。"""
    stale = jobs.stale_job()
    if stale is not None:
        print("[!] " + jobs.STALE_JOB_MSG.format(
            project=stale.get("project", "?"),
            task=jobs.TASK_LABELS.get(stale.get("task"), stale.get("task", "?")),
            pid=stale["pid"]), file=sys.stderr)


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


def open_browser(url: str) -> None:
    """KI-88：用一次性入口打开默认浏览器（macOS 经 osascript 的 stdin 传地址，ps 看不到）；
    打不开就把链接打印出来，让用户自己粘贴。"""
    link = entry_url(url)
    if not webbrowser.open(link):
        print(f"没能自动打开浏览器，请在浏览器里打开这个一次性链接（{session.NONCE_TTL_S // 60} 分钟内有效）：{link}")


def main() -> None:
    applog.setup("app")
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
    report_stale_job()
    if args.open:
        threading.Timer(0.6, open_browser, args=(url,)).start()
    else:
        print(f"在浏览器里打开这个一次性链接（{session.NONCE_TTL_S // 60} 分钟内有效）：{entry_url(url)}")
    # 终端窗口被关 / kill 时也要走到 finally，停掉后台任务（不留孤儿进程继续计费）
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        jobs.shutdown_all()


if __name__ == "__main__":
    main()
