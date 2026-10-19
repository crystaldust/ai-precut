import sys
import textwrap
from pathlib import Path

import pytest

from pipeline import proc


def test_app_root_points_to_repo_in_dev():
    root = proc.app_root()
    assert (root / "pipeline").is_dir()


def test_user_data_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_CUT_PROJECTS", str(tmp_path))
    assert proc.user_data_root() == tmp_path


def test_user_data_root_default_is_writable():
    root = proc.user_data_root()
    assert root.is_absolute()


def test_run_inprocess_captures_system_exit():
    code, out = proc.run_inprocess("pipeline.proc", [])
    assert code == 1  # 该模块没有 main()，应被兜住而不是抛异常
    assert "main" in out


def test_bundled_bin_none_when_missing():
    # 开发环境没有 App 内置目录时不应报错
    assert proc.bundled_bin() is None or isinstance(proc.bundled_bin(), Path)


# ---------------------------------------------------------------- GL-11 / GL-12
def _fake_module(tmp_path, monkeypatch, name, body):
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def test_run_inprocess_keeps_text_of_sys_exit_string(tmp_path, monkeypatch):
    mod = _fake_module(tmp_path, monkeypatch, "fake_exit_text", """
        import sys
        def main():
            print("开始")
            sys.exit("找不到剪映草稿库")
    """)
    code, out = proc.run_inprocess(mod, [])
    assert code == 1
    assert "找不到剪映草稿库" in out  # GL-12：文字不能丢，也不能抛 ValueError
    assert "开始" in out


@pytest.mark.parametrize("ret, expected", [(None, 0), (0, 0), (1, 1), (3, 3)])
def test_run_inprocess_honors_main_return_value(tmp_path, monkeypatch, ret, expected):
    mod = _fake_module(tmp_path, monkeypatch, f"fake_ret_{expected}_{ret}", f"""
        def main():
            return {ret!r}
    """)
    code, _ = proc.run_inprocess(mod, [])
    assert code == expected  # GL-11：validate_draft.main() 返回 1 必须透传


@pytest.mark.parametrize("exit_arg, expected", [(None, 0), (0, 0), (2, 2), (True, 1)])
def test_run_inprocess_int_exit_codes(tmp_path, monkeypatch, exit_arg, expected):
    mod = _fake_module(tmp_path, monkeypatch, f"fake_exit_{expected}_{exit_arg}", f"""
        import sys
        def main():
            sys.exit({exit_arg!r})
    """)
    assert proc.run_inprocess(mod, [])[0] == expected


def test_run_inprocess_restores_argv(tmp_path, monkeypatch):
    before = list(sys.argv)
    mod = _fake_module(tmp_path, monkeypatch, "fake_exit_restore", """
        import sys
        def main():
            sys.exit("x")
    """)
    proc.run_inprocess(mod, ["a"])
    assert sys.argv == before
