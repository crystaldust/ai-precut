"""gui/views：剪辑台只读视图——项目列表、版本排序、健康检查（KI-38 补覆盖）。"""
import json
import subprocess
from types import SimpleNamespace

from gui import views
from pipeline import proc


def _project(root, name, versions=(), title="", extra_files=()):
    pdir = root / name
    (pdir / "output").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "title": title, "preset": "纪实3min", "material": "/v/a.mov",
         "schema_version": 2}, ensure_ascii=False), encoding="utf-8")
    for v in versions:  # 已完成的版本目录一定有时间线（晋升是整体改名，M14）
        (pdir / "output" / v).mkdir()
        (pdir / "output" / v / "timeline.json").write_text("{}", encoding="utf-8")
    for f in extra_files:
        (pdir / "output" / f).write_text("x")
    return pdir


def test_projects_list_reports_versions_and_ignores_stray_files(tmp_path):
    _project(tmp_path, "a", versions=("v1", "v2"), title="甲", extra_files=("v3",))
    (tmp_path / "not_a_project").mkdir()
    items = views.projects_list(tmp_path)
    assert items == [{"name": "a", "title": "甲", "preset": "纪实3min", "versions": ["v1", "v2"],
                      "step": {"n": 2, "label": "分析"}}]


def test_projects_list_tolerates_corrupt_project_json(tmp_path):
    pdir = tmp_path / "bad"
    pdir.mkdir()
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    assert views.projects_list(tmp_path) == [{"name": "bad", "title": "", "preset": "",
                                              "versions": [], "step": None}]


def test_versions_sorted_numerically_newest_first(tmp_path):
    pdir = _project(tmp_path, "p", versions=("v2", "v10", "v1", "vx"), title="T",
                    extra_files=("v99",))
    (pdir / "output" / "v5").mkdir()                    # 没有时间线的残目录不列出
    (pdir / "output" / ".v6.tmp").mkdir()               # 晋升的组装目录不列出
    names = [v["name"] for v in views._versions(pdir, {"title": "T"}, "p")]
    assert names == ["v10", "v2", "v1"]  # 按数字排（v10 比 v2 新）；非数字目录、同名文件、残目录都被跳过
    assert views._versions(pdir, {}, "p")[0]["draft"] == "p_v10"  # 没有标题用项目名


def test_health_payload_reports_ffmpeg_version(monkeypatch):
    monkeypatch.setattr(views.shutil, "which", lambda name: f"/opt/bin/{name}")
    long_line = "ffmpeg version 7.1 " + "x" * 200
    monkeypatch.setattr(views.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=long_line + "\nmore"))
    h = views.health_payload()
    assert h["ffmpeg"] == "/opt/bin/ffmpeg" and h["ffprobe"] == "/opt/bin/ffprobe"
    assert h["ffmpeg_version"] == long_line[:views.FFMPEG_VERSION_MAX]
    assert h["frozen"] is proc.FROZEN and h["app_root"] == str(proc.app_root())


def test_health_payload_version_unknown_when_ffmpeg_hangs(monkeypatch):
    monkeypatch.setattr(views.shutil, "which", lambda name: "/opt/bin/ffmpeg")

    def hang(*a, **k):
        raise subprocess.TimeoutExpired("ffmpeg", k.get("timeout"))
    monkeypatch.setattr(views.subprocess, "run", hang)
    assert views.health_payload()["ffmpeg_version"] == "?"


def test_health_payload_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(views.shutil, "which", lambda name: None)
    monkeypatch.setattr(views.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("没有 ffmpeg 时不能去跑它")))
    h = views.health_payload()
    assert h["ffmpeg"] is None and h["ffmpeg_version"] == ""


def test_projects_list_step_survives_corrupt_data_exceptions(tmp_path, monkeypatch):
    from gui import wizard
    _project(tmp_path, "a", title="甲")
    for exc in (TypeError("x"), KeyError("k"), ValueError("v"), AttributeError("a"), OSError("o")):
        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(wizard, "collect", boom)
        assert views.projects_list(tmp_path)[0]["step"] is None


def test_wizard_collect_has_no_side_effects_on_unmarked_files(tmp_path):
    from gui import wizard
    from pipeline import media_io
    pdir = _project(tmp_path, "a", title="甲")
    (pdir / "work").mkdir()
    (pdir / "work/proxy.mp4").write_bytes(b"legacy")
    wizard.collect(pdir, {"material": "/v/a.mov"}, "a")
    assert not media_io.done_marker(pdir / "work/proxy.mp4").exists()
