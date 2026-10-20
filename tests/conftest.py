"""测试脚手架：剪映草稿库 / 凭证隔离（autouse）+ GUI 服务（随机端口、PROJECTS 指向 tmp_path）。"""
import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _isolate_jianying(tmp_path, monkeypatch):
    """任何测试都不许碰真实剪映草稿库：默认把草稿根指向一个不存在的临时目录。"""
    monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(tmp_path / "jy_guard_root"))


@pytest.fixture(autouse=True)
def _isolate_secrets(tmp_path, monkeypatch):
    """任何测试都不许碰真实钥匙串和 ~/.config/ai-cut：凭证与告知记录一律落在 tmp。"""
    from pipeline import secrets
    monkeypatch.setenv("AI_CUT_SECRETS", "file")
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "cfg_guard"))
    # 本机环境变量 / 旧版 key 文件里的真实 Key 不能漏进测试（开发机与 CI 结果要一致）
    for var in secrets.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(secrets, "LEGACY_FILES", {}, raising=False)


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    """任何测试都不许写真实的 ~/Library/Logs/剪辑台；测完卸掉本测试装上的日志 handler 与异常钩子。"""
    monkeypatch.setenv("AI_CUT_LOG_DIR", str(tmp_path / "logs_guard"))
    yield
    from pipeline import applog
    applog.reset_for_tests()


@pytest.fixture(autouse=True)
def _encoder_ok(monkeypatch):
    """默认当作本机能用 VideoToolbox（预检本身在 test_m5_review2 里用假 runner 测）。"""
    from pipeline import encode
    monkeypatch.setattr(encode, "_PREFLIGHT", {"result": None})


@pytest.fixture
def no_keys():
    """显式声明「本测试不带任何 Key」；隔离本身已由 _isolate_secrets 统一完成。"""
    from pipeline import secrets
    return secrets


@pytest.fixture
def consented():
    """已阅读数据外发说明（记录写在本测试的临时配置目录里）。"""
    from pipeline import consent
    consent.accept()
    return consent


def _stop_jobs(jobs, timeout=10.0):
    """收尾：取消还在跑的任务并等它退出，免得串到下一个测试（全局互斥）。"""
    for jid in [j for j, v in list(jobs.JOBS.items()) if v["status"] == "running"]:
        jobs.cancel_job(jid)
    deadline = time.time() + timeout
    while time.time() < deadline and jobs.active_job() is not None:
        time.sleep(0.05)
    for job in list(jobs.JOBS.values()):  # 等任务线程真正收尾，再清表
        thread = job.get("thread")
        if thread is not None and thread.is_alive():
            thread.join(max(0.0, deadline - time.time()))
    with jobs.JOBS_LOCK:
        jobs.JOBS.clear()


@pytest.fixture
def gui_server(tmp_path, monkeypatch):
    from gui import jobs, server
    monkeypatch.setattr(server, "PROJECTS", tmp_path)
    _stop_jobs(jobs)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01},
                     daemon=True).start()
    try:
        yield SimpleNamespace(module=server, port=srv.server_address[1], root=tmp_path)
    finally:
        _stop_jobs(jobs)
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def preset_dir(gui_server, tmp_path_factory, monkeypatch):
    """只有一个「测试预设」的预设目录，测试不依赖仓库里真实的预设名。"""
    d = tmp_path_factory.mktemp("presets")
    (d / "测试预设.json").write_text(json.dumps({"name": "测试"}), encoding="utf-8")
    monkeypatch.setattr(gui_server.module, "PRESETS", d)
    return d


def call(gs, method, path, body=None, *, token=True, headers=None, raw=None):
    """发请求并返回 (status, bytes, headers)。默认带合法 Host/会话 cookie/JSON（token=False 不带凭证）。"""
    from gui import session
    h = {"Host": f"127.0.0.1:{gs.port}"}
    if token:  # KI-88：凭证是 nonce 换来的会话 cookie
        h["Cookie"] = f"{session.cookie_name(gs.port)}={session.SECRET}"
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", gs.port, timeout=10)
    try:
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        return r.status, r.read(), {k.lower(): v for k, v in r.getheaders()}
    finally:
        conn.close()


def make_project(root, name="p1", shots=None, **files):
    """建一个最小项目；files 的键是相对路径，例：make_project(root, **{"work/proxy.mp4": b"..."})。"""
    pdir = root / name
    (pdir / "work").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "material": "/tmp/a.mp4", "title": name, "schema_version": 2},
        ensure_ascii=False), encoding="utf-8")
    if shots is not None:
        (pdir / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
    for rel, content in files.items():
        f = pdir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content if isinstance(content, bytes) else content.encode())
    return pdir


@pytest.fixture(autouse=True)
def _no_real_jianying_version(request, monkeypatch):
    """开发机装的剪映版本不能影响测试（KI-17）；test_jy_version 自己显式传入候选路径，不打桩。"""
    if request.node.module.__name__.endswith("test_jy_version"):
        return
    from pipeline import jy_version
    monkeypatch.setattr(jy_version, "installed_version", lambda *a: None)
    monkeypatch.setattr(jy_version, "find_app", lambda *a, **k: None)  # KI-98：绝不在测试里对真实系统做检测


@pytest.fixture(autouse=True)
def _fresh_jianying_cache():
    """剪辑台进程内缓存了「剪映装没装」60 秒：每个测试开始 / 结束都清掉，免得串测试。"""
    from gui import jianying
    jianying.reset_cache()
    yield
    jianying.reset_cache()


def fake_ensure_preview(vdir, tl_hash, seen=None):
    """替身 aicut.ensure_preview：写一个带完成标记的假预览片和哈希戳（M14 起 build 要晋升它，不能只返回路径）。"""
    from pipeline import media_io
    with media_io.atomic_output(vdir / "preview.mp4") as tmp:
        tmp.write_bytes(b"fake-mp4")
    (vdir / ".timeline.sha").write_text(tl_hash)
    if seen is not None:
        seen.append(tl_hash)
    return vdir / "preview.mp4"
