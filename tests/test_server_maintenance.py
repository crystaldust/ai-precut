"""KI-33：/api/cache、/api/cache/clean（剪辑台「清理缓存」）。"""
import json
import sys

import pytest

from conftest import call, make_project


def _get(gs, project="p1", **kw):
    status, body, _ = call(gs, "GET", f"/api/cache?project={project}", **kw)
    return status, json.loads(body)


def _clean(gs, project="p1", **kw):
    status, body, _ = call(gs, "POST", "/api/cache/clean", {"project": project}, **kw)
    return status, json.loads(body)


def _with_clips(root):
    return make_project(root, **{"work/clips/S1.mp4": b"x" * 4000, "work/proxy.mp4": b"p" * 10})


def test_cache_listing(gui_server):
    _with_clips(gui_server.root)
    status, data = _get(gui_server)
    assert status == 200 and data["total"] == 4000
    assert data["items"][0]["path"] == "work/clips" and data["items"][0]["label"]


def test_cache_clean_frees_and_keeps_proxy(gui_server):
    pdir = _with_clips(gui_server.root)
    status, data = _clean(gui_server)
    assert status == 200 and data["freed"] == 4000
    assert not (pdir / "work/clips").exists() and (pdir / "work/proxy.mp4").exists()


def test_cache_clean_refused_while_job_runs(gui_server, monkeypatch):
    from gui import jobs
    pdir = _with_clips(gui_server.root)
    monkeypatch.setattr(jobs, "job_command",
                        lambda *a: [sys.executable, "-c", "import time; time.sleep(30)"])
    jobs.start_job("p1", "select", [])
    status, data = _clean(gui_server)
    assert status == 409 and data["error"]
    assert (pdir / "work/clips/S1.mp4").exists()


@pytest.mark.parametrize("fn", [_get, _clean])
def test_bad_or_missing_project(gui_server, fn):
    assert fn(gui_server, project="-h")[0] == 400
    assert fn(gui_server, project="nope")[0] == 404


@pytest.mark.parametrize("fn", [_get, _clean])
def test_requires_token(gui_server, fn):
    _with_clips(gui_server.root)
    assert fn(gui_server, token=False)[0] == 403


def test_cache_clean_refused_while_cli_task_holds_project(gui_server):
    import subprocess
    pdir = _with_clips(gui_server.root)
    root = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    holder = subprocess.Popen([sys.executable, "-c",
        "import sys,time; sys.path.insert(0, %r); from pipeline import project_lock;"
        "cm = project_lock.busy(%r); cm.__enter__(); print('ok', flush=True); time.sleep(30)"
        % (root, str(pdir))], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ok"
        status, data = _clean(gui_server)
        assert status == 409 and (pdir / "work/clips/S1.mp4").exists()
    finally:
        holder.kill(); holder.wait()
