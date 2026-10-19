"""GUI 服务测试脚手架：在随机端口起一个真实的剪辑台服务，PROJECTS 指向 tmp_path。"""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest


@pytest.fixture
def gui_server(tmp_path, monkeypatch):
    from gui import server
    monkeypatch.setattr(server, "PROJECTS", tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01},
                     daemon=True).start()
    try:
        yield SimpleNamespace(module=server, port=srv.server_address[1], root=tmp_path)
    finally:
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
    """发请求并返回 (status, bytes, headers)。默认带合法 Host/token/JSON。"""
    h = {"Host": f"127.0.0.1:{gs.port}"}
    if token:
        h["X-AICUT-Token"] = getattr(gs.module, "API_TOKEN", "")
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
