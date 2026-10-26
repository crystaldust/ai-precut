"""M4 · GL-14：版本卡片导出 Windows 剪映包（任务参数、版本校验、已导出状态、在访达中显示）。"""
import json
import sys

import pytest

from conftest import call, make_project


@pytest.fixture
def seen(gui_server, monkeypatch):
    from gui import jobs
    calls = []

    def job_command(task, name, extra):
        calls.append((task, name, list(extra)))
        return [sys.executable, "-c", "print('ok')"]

    monkeypatch.setattr(jobs, "job_command", job_command)
    return calls


def project(gs, title="测试片", versions=("v1",)):
    files = {f"output/{v}/timeline.json": json.dumps({"video": []}) for v in versions}
    pdir = make_project(gs.root, **files)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    (pdir / "project.json").write_text(json.dumps({**cfg, "title": title}, ensure_ascii=False),
                                       encoding="utf-8")
    return pdir


def export(gs, version):
    status, raw, _ = call(gs, "POST", "/api/job", {"project": "p1", "task": "export",
                                                  "version": version})
    return status, json.loads(raw)


def test_export_job_builds_expected_args(gui_server, seen):
    pdir = project(gui_server)
    status, data = export(gui_server, "v1")
    assert status == 200 and data["job_id"]
    task, name, extra = seen[0]
    assert (task, name) == ("export", "p1")
    assert extra == [f"--timeline={pdir / 'output/v1/timeline.json'}",
                     f"--out={pdir / 'output/v1'}", "--package-name=测试片_v1_Windows"]


def test_export_command_is_aicut_export(gui_server):
    from gui import jobs
    assert jobs.JOB_COMMANDS["export"] == ["export"]
    cmd = jobs.job_command("export", "p1", ["--timeline=/x"])
    assert cmd[-3:] == ["export", "p1", "--timeline=/x"]


@pytest.mark.parametrize("version", ["../../x", "v1/../..", "", None, 3, "v1 ", "V1"])
def test_export_rejects_bad_version(gui_server, seen, version):
    project(gui_server)
    status, data = export(gui_server, version)
    assert status == 400 and "版本号" in data["error"]
    assert seen == [] and gui_server.module.JOBS == {}


def test_export_requires_timeline(gui_server, seen):
    project(gui_server)
    status, data = export(gui_server, "v9")
    assert status == 400 and "⑥ 导出" in data["error"] and "生成新版本" not in data["error"]
    assert seen == []


def test_title_with_path_chars_is_sanitized(gui_server, seen):
    project(gui_server, title="a/b:c")
    export(gui_server, "v1")
    pkg = seen[0][2][2]
    assert pkg == "--package-name=a_b_c_v1_Windows"


def test_title_starting_with_dash_or_dot(gui_server, seen):
    project(gui_server, title="-.片名")
    export(gui_server, "v1")
    assert seen[0][2][2] == "--package-name=片名_v1_Windows"


def test_state_reports_windows_zip(gui_server):
    pdir = project(gui_server, versions=("v1", "v2"))
    (pdir / "output/v1/测试片_v1_Windows.zip").write_bytes(b"x" * 2_400_000)
    state = json.loads(call(gui_server, "GET", "/api/state?project=p1")[1])
    by_name = {v["name"]: v for v in state["versions"]}
    assert by_name["v1"]["windows_zip"] == "测试片_v1_Windows.zip"
    assert by_name["v1"]["windows_mb"] == 2
    assert by_name["v2"]["windows_zip"] is None


def test_reveal_export_in_explorer_on_windows(gui_server, win_platform, monkeypatch, tmp_path):
    pdir = project(gui_server)
    zip_path = pdir / "output/v1/测试片_v1_Windows.zip"
    zip_path.write_bytes(b"x")
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Win"))
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run", lambda argv, **kw: ran.append(argv))
    status, _, _ = call(gui_server, "POST", "/api/open",
                        {"project": "p1", "target": "export", "version": "v1"})
    assert status == 200 and ran == [f'"{tmp_path / "Win" / "explorer.exe"}" /select,"{zip_path}"']


def test_reveal_export_in_finder(gui_server, mac_platform, monkeypatch):
    pdir = project(gui_server)
    zip_path = pdir / "output/v1/测试片_v1_Windows.zip"
    zip_path.write_bytes(b"x")
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run",
                        lambda argv, **kw: ran.append(argv))
    status, _, _ = call(gui_server, "POST", "/api/open",
                        {"project": "p1", "target": "export", "version": "v1"})
    assert status == 200 and ran == [["open", "-R", str(zip_path)]]


def test_reveal_export_missing_zip_404(gui_server, monkeypatch):
    project(gui_server)
    ran = []
    monkeypatch.setattr(gui_server.module.subprocess, "run",
                        lambda argv, **kw: ran.append(argv))
    status, _, _ = call(gui_server, "POST", "/api/open",
                        {"project": "p1", "target": "export", "version": "v1"})
    assert status == 404 and ran == []
    status, _, _ = call(gui_server, "POST", "/api/open",
                        {"project": "p1", "target": "export", "version": "../v1"})
    assert status == 400 and ran == []


def test_very_long_title_is_truncated(gui_server, seen):
    project(gui_server, title="长" * 200)
    export(gui_server, "v1")
    stem = seen[0][2][2].split("=", 1)[1]
    assert len(stem.encode("utf-8")) <= 255 - len(".zip") and stem.endswith("_v1_Windows")


# ---------------------------------------------------------------- 审查修复 2：LOW-7
@pytest.mark.parametrize("title", [123, None, ["x"], ""])
def test_non_string_title_never_500(gui_server, title):
    project(gui_server, title=title)
    status, _, _ = call(gui_server, "GET", "/api/state?project=p1")
    assert status == 200


def test_windows_zip_falls_back_to_project_name_for_bad_title(tmp_path):
    from gui import jobs
    from pipeline import outputs
    assert jobs.windows_zip(tmp_path / "p1", "v1", 123).name == "p1_v1_Windows.zip"
    assert outputs.windows_zip(tmp_path / "p1", "v1", 123) == jobs.windows_zip(tmp_path / "p1", "v1", 123)


def test_bidi_and_zero_width_chars_stripped(tmp_path):
    from gui import jobs
    title = "片​名‮gpj.exe⁦‏"
    name = jobs.windows_zip(tmp_path / "p1", "v1", title).name
    from pipeline import outputs
    assert outputs.windows_zip(tmp_path / "p1", "v1", title).name == name
    assert not any(c in name for c in "​‮⁦‏")
    assert name.endswith("_v1_Windows.zip")


def test_gui_build_without_target_is_400_and_starts_nothing(gui_server, seen):
    """M14c：旧的「生成新版本」暂存界面没了，GUI 的 build 必须带 target。"""
    project(gui_server)
    for body in ({}, {"no_draft": True}, {"target": "linux"}):
        status, raw, _ = call(gui_server, "POST", "/api/job", {"project": "p1", "task": "build", **body})
        assert status == 400 and json.loads(raw)["error"], body
    assert seen == [] and gui_server.module.JOBS == {}


def test_build_task_label_is_export_in_conflict_message(gui_server):
    from gui import jobs
    assert jobs.TASK_LABELS["build"] == "导出" and jobs.TASK_LABELS["export"] == "生成 Windows 剪映包"
