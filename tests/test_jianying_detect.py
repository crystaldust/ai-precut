"""KI-98：剪映检测（缓存、/api/state 的可用性、/api/open target=jianying 只在检测到时才打开）。

全程打桩 jy_version.find_app：绝不在测试里对真实用户目录 / Spotlight 做检测。
"""
import json
from pathlib import Path

import pytest

from conftest import call, make_project
from gui import jianying
from pipeline import jy_version

APP = Path("/fake/剪映专业版.app")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _counting(monkeypatch, result):
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return result
    monkeypatch.setattr(jy_version, "find_app", fake)
    return calls


def test_find_caches_result_for_the_cache_window(monkeypatch):
    calls, clock = _counting(monkeypatch, APP), Clock()
    assert jianying.find(now=clock) == APP and jianying.find(now=clock) == APP
    assert len(calls) == 1
    clock.t += jianying.JIANYING_CACHE_S + 1
    assert jianying.find(now=clock) == APP
    assert len(calls) == 2


def test_find_refresh_bypasses_cache_and_caches_none_too(monkeypatch):
    calls, clock = _counting(monkeypatch, None), Clock()
    assert jianying.find(now=clock) is None and jianying.find(now=clock) is None
    assert len(calls) == 1
    assert jianying.find(refresh=True, now=clock) is None
    assert len(calls) == 2


def test_installed_refresh_redetects(monkeypatch):
    calls = _counting(monkeypatch, None)
    assert jianying.installed() is False and jianying.installed() is False
    assert len(calls) == 1
    _counting(monkeypatch, APP)
    assert jianying.installed() is False and jianying.installed(refresh=True) is True


def test_installed_is_bool(monkeypatch):
    _counting(monkeypatch, APP)
    assert jianying.installed() is True
    jianying.reset_cache()
    _counting(monkeypatch, None)
    assert jianying.installed() is False


# ---------------------------------------------------------------- 接口
def test_state_reports_jianying_availability_and_uses_cache(gui_server, monkeypatch):
    make_project(gui_server.root)
    calls = _counting(monkeypatch, APP)
    for _ in range(2):
        status, raw, _ = call(gui_server, "GET", "/api/state?project=p1")
        assert status == 200 and json.loads(raw)["jianying"] == {"installed": True}
    assert len(calls) == 1


def test_state_jianying_not_installed(gui_server, monkeypatch):
    make_project(gui_server.root)
    _counting(monkeypatch, None)
    _, raw, _ = call(gui_server, "GET", "/api/state?project=p1")
    assert json.loads(raw)["jianying"] == {"installed": False}


def test_open_jianying_opens_the_detected_path_with_timeout(gui_server, monkeypatch):
    make_project(gui_server.root)
    _counting(monkeypatch, APP)
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run",
                        lambda argv, **kw: ran.append((argv, kw)))
    status, _, _ = call(gui_server, "POST", "/api/open", {"project": "p1", "target": "jianying"})
    assert status == 200
    assert ran[0][0] == ["open", "-a", str(APP)] and ran[0][1]["timeout"] == jianying.OPEN_TIMEOUT_S


def test_open_jianying_404_when_not_detected_and_runs_nothing(gui_server, monkeypatch):
    make_project(gui_server.root)
    _counting(monkeypatch, None)
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: ran.append(argv))
    status, raw, _ = call(gui_server, "POST", "/api/open", {"project": "p1", "target": "jianying"})
    assert status == 404 and json.loads(raw)["error"] == jianying.NOT_FOUND_MSG and ran == []


def test_open_jianying_rechecks_instead_of_trusting_a_stale_cache(gui_server, monkeypatch):
    make_project(gui_server.root)
    _counting(monkeypatch, None)
    call(gui_server, "GET", "/api/state?project=p1")          # 缓存里记下「没装」
    _counting(monkeypatch, APP)                                # 随后装上了
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: None)
    status, _, _ = call(gui_server, "POST", "/api/open", {"project": "p1", "target": "jianying"})
    assert status == 200


@pytest.mark.parametrize("target", ["project"])
def test_open_project_still_works(gui_server, monkeypatch, target):
    pdir = make_project(gui_server.root)
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: ran.append(argv))
    status, _, _ = call(gui_server, "POST", "/api/open", {"project": "p1", "target": target})
    assert status == 200 and ran == [["open", str(pdir)]]
