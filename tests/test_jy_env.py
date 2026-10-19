"""pipeline/jy_env：剪映草稿用的专用 venv；旧版 Python 建的 venv 要重建（KI-82）。"""
import pytest

from pipeline import jy_env


class FakeProc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def _venv(tmp_path, exists=True):
    venv = tmp_path / "venv"
    if exists:
        (venv / "bin").mkdir(parents=True)
        (venv / "bin/python").write_text("")
    return venv


def _runner(calls, pip_code=0, installed=jy_env.JY_VERSION):
    def run(cmd, **kw):
        calls.append(cmd)
        if "-c" in cmd:  # 查 venv 里装的版本（KI-34）
            return FakeProc(0, out=f"{installed}\n")
        return FakeProc(pip_code if "pip" in cmd else 0, err="pip boom")
    return run


def test_existing_supported_venv_is_reused(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(jy_env.pyver, "supports_safe_path", lambda py: True)
    venv = _venv(tmp_path)
    assert jy_env.ensure(venv, runner=_runner(calls)) == str(venv / "bin/python")
    assert len(calls) == 1 and "-c" in calls[0]  # 只核对版本，不重装


def test_venv_with_other_version_is_reinstalled_pinned(tmp_path, monkeypatch):  # KI-34
    calls = []
    monkeypatch.setattr(jy_env.pyver, "supports_safe_path", lambda py: True)
    venv = _venv(tmp_path)
    jy_env.ensure(venv, runner=_runner(calls, installed="0.2.9"))
    pip = [c for c in calls if "pip" in c]
    assert pip and jy_env.JY_PIN in pip[0] and jy_env.JY_PIN == "pyJianYingDraft==0.3.1"


def test_fresh_install_is_pinned(tmp_path):
    calls = []
    jy_env.ensure(_venv(tmp_path, exists=False), runner=_runner(calls), base_python="/new/py")
    assert any(jy_env.JY_PIN in c for c in calls)


def test_pin_matches_uv_lock():
    import re
    from pathlib import Path
    lock = (Path(__file__).resolve().parent.parent / "uv.lock").read_text(encoding="utf-8")
    m = re.search(r'name = "pyjianyingdraft"\nversion = "([^"]+)"', lock)
    assert m and m.group(1) == jy_env.JY_VERSION


def test_available_here_reflects_current_interpreter(monkeypatch):
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert jy_env.available_here()
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert not jy_env.available_here()


def test_old_venv_is_rebuilt_in_place(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(jy_env.pyver, "supports_safe_path", lambda py: False)
    venv = _venv(tmp_path)
    assert jy_env.ensure(venv, runner=_runner(calls), base_python="/new/py") == str(venv / "bin/python")
    assert calls[0] == ["/new/py", "-m", "venv", "--clear", str(venv)]
    assert calls[1][:4] == [str(venv / "bin/python"), "-m", "pip", "install"]
    assert "3.11" in capsys.readouterr().out


def test_missing_venv_is_created(tmp_path):
    calls = []
    venv = _venv(tmp_path, exists=False)
    jy_env.ensure(venv, runner=_runner(calls), base_python="/new/py")
    assert calls[0] == ["/new/py", "-m", "venv", "--clear", str(venv)]
    assert any("pyJianYingDraft" in str(x) for x in calls[1])


def test_pip_failure_is_reported(tmp_path):
    with pytest.raises(jy_env.JyEnvError, match="pip boom"):
        jy_env.ensure(_venv(tmp_path, exists=False), runner=_runner([], pip_code=1))


def test_venv_creation_failure_is_reported(tmp_path):
    def run(cmd, **kw):
        return FakeProc(1, err="venv boom")
    with pytest.raises(jy_env.JyEnvError, match="venv boom"):
        jy_env.ensure(_venv(tmp_path, exists=False), runner=run)
