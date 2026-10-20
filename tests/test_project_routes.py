"""gui/project_routes.py 的分发契约（M13 Task 1：路由搬家，行为不变）。"""
from pathlib import Path

from gui import project_routes


def _unused(_name):  # 不是本模块的路径时，绝不应该去解析项目
    raise AssertionError("不该被调用")


def test_get_returns_none_for_foreign_path():
    assert project_routes.handle_get("/api/projects", {}, _unused, _unused) is None


def test_post_returns_none_for_foreign_path():
    assert project_routes.handle_post("/api/new", {}, _unused) is None


def test_post_level_requires_id(tmp_path):
    code, data = project_routes.handle_post(
        "/api/browse/level", {"project": "p"}, lambda _n: Path(tmp_path))
    assert code == 400 and "id" in data["error"]
