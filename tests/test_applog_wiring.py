"""GL-19 接线：CLI / 打包子进程 / GUI 任务 / 客户端密钥登记都进日志，且不改 print 输出。"""
import json
import logging
import sys
from pathlib import Path

import pytest

import aicut
from conftest import fake_ensure_preview
from pipeline import applog, proc

ROOT = Path(__file__).resolve().parent.parent


def _log_text(name: str) -> str:
    for h in logging.getLogger(applog.ROOT_LOGGER).handlers:
        h.flush()
    path = applog.current_log_file()
    assert path is not None and path.name.startswith(name)
    return path.read_text(encoding="utf-8")


def test_die_logs_error_and_keeps_print_prefix(capsys):
    applog.setup("cli")
    with pytest.raises(SystemExit):
        aicut.die("转写失败：boom")
    assert capsys.readouterr().out == "[x] 转写失败：boom\n"
    assert "转写失败：boom" in _log_text("cli")


def test_run_cli_logs_unexpected_exception(monkeypatch):
    applog.setup("cli")

    def boom(argv):
        raise RuntimeError("意外炸了")
    monkeypatch.setattr(aicut, "main", boom)
    assert aicut.run_cli(["status", "p1"]) == 1
    text = _log_text("cli")
    assert "意外炸了" in text and "Traceback" in text and "status" in text


# ---------------------------------------------------------------- 阶段计时
from test_aicut_cli import STAGES, _project, _record_stages, cli_env  # noqa: E402,F401


def test_prepare_records_every_stage_timing(cli_env, monkeypatch):
    projects, _ = cli_env
    pdir = _project(projects)
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    aicut.main(["prepare", "p1"])
    assert calls == list(STAGES)  # 顺序不变
    timings = json.loads((pdir / "work/timings.json").read_text(encoding="utf-8"))
    assert set(timings) == {s[len("cmd_"):] for s in STAGES}
    assert all(v["ok"] for v in timings.values())


def test_prepare_failed_stage_recorded_and_stops(cli_env, monkeypatch):
    projects, _ = cli_env
    pdir = _project(projects)
    aicut.secrets.set("mediakit", "AKLTabcdefghij9f2a")
    aicut.secrets.set("deepseek", "sk-abcdefghijkl")
    calls = _record_stages(monkeypatch)
    monkeypatch.setattr(aicut, "cmd_transcribe", lambda a: aicut.die("转写失败"))
    with pytest.raises(SystemExit):
        aicut.main(["prepare", "p1"])
    timings = json.loads((pdir / "work/timings.json").read_text(encoding="utf-8"))
    assert timings["ingest"]["ok"] is True and timings["transcribe"]["ok"] is False
    assert calls == ["cmd_ingest", "cmd_junk"]  # D10：浏览小样（junk）排在转写前


def test_build_records_clip_preview_draft_timings(cli_env, monkeypatch, tmp_path):
    projects, _ = cli_env
    pdir = _project(projects)
    (pdir / "shots.json").write_text(json.dumps(
        {"shots": [{"id": "s1", "in": 0, "out": 1}]}), encoding="utf-8")
    (aicut.PRESETS / "纪实3min.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(aicut.select, "missing_must_keep", lambda *a: [])
    monkeypatch.setattr(aicut, "ensure_clips", lambda *a: tmp_path)
    monkeypatch.setattr(aicut, "actual_durations", lambda *a: {"s1": 1.0})
    monkeypatch.setattr(aicut, "compose_timeline", lambda *a: {"video": [], "text": []})
    monkeypatch.setattr(aicut, "ensure_preview", fake_ensure_preview)
    monkeypatch.setattr(aicut, "install_draft", lambda *a: None)
    aicut.main(["build", "p1", "--version", "v1"])
    timings = json.loads((pdir / "work/timings.json").read_text(encoding="utf-8"))
    assert {"clips", "preview", "draft"} <= set(timings)


# ---------------------------------------------------------------- 入口装日志
def test_frozen_cli_subprocess_writes_cli_log(monkeypatch):
    monkeypatch.setattr(proc, "_line_buffered_stdio", lambda: None)
    monkeypatch.setattr(proc, "ensure_bundled_path", lambda: None)
    monkeypatch.setattr(proc, "start_parent_watchdog", lambda: None)
    monkeypatch.setattr(aicut, "run_cli", lambda argv: (applog.get("cli").info("跑了 %s", argv), 0)[1])
    assert proc.dispatch(["app", proc.CLI_FLAG, "status", "p1"]) == 0
    assert "跑了 ['status', 'p1']" in _log_text("cli")


def test_entry_points_set_up_logging_first():
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    body = main_src.split("def main() -> None:", 1)[1]
    assert body.strip().startswith('applog.setup("app")')
    server_src = (ROOT / "gui/server.py").read_text(encoding="utf-8")
    assert 'applog.setup("app")' in server_src.split("def main() -> None:", 1)[1]
    aicut_src = (ROOT / "aicut.py").read_text(encoding="utf-8")
    assert 'applog.setup("cli")' in aicut_src.split('if __name__ == "__main__":', 1)[1]


# ---------------------------------------------------------------- 客户端拿到 Key 立刻登记脱敏
def test_clients_register_their_keys():
    from pipeline import cloud, llm
    cloud.CloudClient(api_key="AKLTcloudkey0000abcd")
    llm.DeepSeekClient(api_key="sk-llmkey00001111")
    assert "AKLTcloudkey0000abcd" not in applog.redact("x AKLTcloudkey0000abcd")
    assert "sk-llmkey00001111" not in applog.redact("x sk-llmkey00001111")


# ---------------------------------------------------------------- GUI 任务进 app.log
def test_gui_job_lines_and_exit_are_logged(gui_server, monkeypatch):
    from conftest import make_project
    from gui import jobs
    from test_server_jobs import fake_command, wait_for
    applog.setup("app")
    make_project(gui_server.root)
    fake_command(monkeypatch, jobs, [sys.executable, "-c", "print('[x] 转写失败：网络')"])
    job_id = jobs.start_job("p1", "build")
    assert wait_for(lambda: jobs.JOBS[job_id]["status"] != "running")
    text = _log_text("app")
    assert "任务开始" in text and "转写失败：网络" in text and "任务结束" in text
