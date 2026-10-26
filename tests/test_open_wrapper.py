"""/api/open 的三种目标共用一个 open 包装：超时、异常、退出码都变成 500 + 中文，不回显 stderr。"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import call, make_project
from gui import jobs, opener
from pipeline import jy_version

APP = Path("/fake/剪映专业版.app")

@pytest.fixture(autouse=True)
def _mac_open_semantics(monkeypatch):
    """本文件断言的是 Mac 的 `open` 命令行（open / open -R / open -a）；Windows 的 opener 另有测试（test_opener_platform）。"""
    from pipeline import plat
    monkeypatch.setattr(plat, "IS_WIN", False)


@pytest.fixture
def target_env(gui_server, monkeypatch):
    pdir = make_project(gui_server.root, **{"output/v1/timeline.json": json.dumps({"video": []})})
    zip_path = jobs.windows_zip(pdir, "v1", "p1")
    zip_path.write_bytes(b"zip")
    monkeypatch.setattr(jy_version, "find_app", lambda *a, **k: APP)
    return gui_server, pdir, zip_path


BODIES = {"project": {"target": "project"},
          "export": {"target": "export", "version": "v1"},
          "jianying": {"target": "jianying"}}


def _open(gs, kind):
    status, raw, _ = call(gs, "POST", "/api/open", {"project": "p1", **BODIES[kind]})
    return status, json.loads(raw)


@pytest.mark.parametrize("kind", list(BODIES))
def test_every_open_call_has_a_timeout(target_env, monkeypatch, kind):
    gs = target_env[0]
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: seen.append((argv, kw)) or SimpleNamespace(returncode=0, stderr=b""))
    assert _open(gs, kind)[0] == 200
    assert seen[0][0][0] == "open" and seen[0][1]["timeout"] == opener.OPEN_TIMEOUT_S


@pytest.mark.parametrize("kind", list(BODIES))
@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired("open", 10), FileNotFoundError("open"), PermissionError("x"),
    SimpleNamespace(returncode=1, stderr=b"SECRET /Users/me/path"),
])
def test_open_failure_is_500_chinese_and_does_not_echo_stderr(target_env, monkeypatch, kind, failure):
    gs = target_env[0]

    def run(argv, **kw):
        if isinstance(failure, BaseException):
            raise failure
        return failure
    monkeypatch.setattr(subprocess, "run", run)
    status, data = _open(gs, kind)
    assert status == 500 and data["error"] == opener.OPEN_FAILED_MSG
    assert "SECRET" not in json.dumps(data)


def test_missing_zip_is_404_before_unusable_check(gui_server, monkeypatch):
    """没有 zip 就说「还没导出」，不用先去查不可用标记。"""
    from pipeline import outputs
    make_project(gui_server.root, **{"output/v1/timeline.json": "{}"})
    monkeypatch.setattr(outputs, "export_block", lambda *a, **k: (1, "拦截"))
    status, data = _open(gui_server, "export")
    assert status == 404 and data["error"] == gui_server.module.NO_EXPORT_MSG
