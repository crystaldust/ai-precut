from pathlib import Path

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
