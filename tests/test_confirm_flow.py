"""M6 · KI-05：确认页入口，「保存并确认」后自动按答案重新选段。"""
import json
import sys
from pathlib import Path

from conftest import call, make_project
from test_server_jobs import LONG, fake_command, get_job, post_job, wait_for

ROOT = Path(__file__).resolve().parent.parent
QUICK = [sys.executable, "-c", "print('[✓] 选段 3 镜', flush=True)"]
FAIL = [sys.executable, "-c", "import sys; print('[x] 必留段未进片：S001', flush=True); sys.exit(1)"]
QUESTIONS = {"questions": [
    {"id": "q1", "text": "结尾？", "type": "single", "options": [
        {"label": "签字", "rule": {"kind": "ending", "value": "sign"}},
        {"label": "全部", "rule": {"kind": "pacing", "value": "tight"}}]},
    {"id": "q2", "text": "排除？", "type": "single", "options": [
        {"label": "全部", "rule": {"kind": "exclude", "value": ["聊吃饭"]}},
        {"label": "不排除", "rule": {"kind": "must_topics", "value": []}}]}]}


def _project(gs):
    return make_project(gs.root, **{"work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})


def _save(gs, **body):
    status, raw, _ = call(gs, "POST", "/api/confirm/answers", {"project": "p1", **body})
    return status, json.loads(raw)


def test_confirmed_save_starts_select_job(gui_server, monkeypatch):
    from gui import jobs
    pdir = _project(gui_server)
    seen = fake_command(monkeypatch, jobs, QUICK)
    status, data = _save(gui_server, answers={"q1": "全部"}, confirmed=True)
    assert status == 200 and data["job_id"]
    assert seen == [("select", "p1", [])]
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "done")
    saved = json.loads((pdir / "work/brief_answers.json").read_text(encoding="utf-8"))
    assert saved["confirmed"] is True
    assert saved["rules"]["pacing"] == "tight" and saved["rules"]["exclude_topics"] == []  # 按题 id 查


def test_plain_save_does_not_start_job(gui_server, monkeypatch):
    from gui import jobs
    _project(gui_server)
    seen = fake_command(monkeypatch, jobs, QUICK)
    status, data = _save(gui_server, answers={"q1": "签字"}, confirmed=False)
    assert status == 200 and data["job_id"] is None
    assert seen == [] and jobs.JOBS == {}


def test_confirm_save_conflict_keeps_answers(gui_server, monkeypatch):
    from gui import jobs
    pdir = _project(gui_server)
    fake_command(monkeypatch, jobs, LONG)
    status, first = post_job(gui_server, task="build")
    assert status == 200
    status, data = _save(gui_server, answers={"q1": "签字"}, confirmed=True)
    assert status == 200 and data["job_id"] is None
    assert "已有任务在运行" in data["job_error"]
    assert json.loads((pdir / "work/brief_answers.json").read_text(encoding="utf-8"))["answers"] == {"q1": "签字"}


def test_confirm_answers_must_be_object(gui_server):
    pdir = _project(gui_server)
    status, data = _save(gui_server, answers=[], confirmed=True)
    assert status == 400 and "answers" in data["error"]
    assert not (pdir / "work/brief_answers.json").exists()


def test_confirm_answers_missing_project_404(gui_server):
    status, _, _ = call(gui_server, "POST", "/api/confirm/answers", {"project": "nope", "answers": {}})
    assert status == 404


def test_index_has_confirm_entry():
    html = (ROOT / "gui/static/index.html").read_text(encoding="utf-8")
    assert "openConfirm()" in html and "/static/confirm.html?project=" in html
    assert "COPY_CONFIRM_ENTRY" in html


def test_confirm_page_polls_job():
    html = (ROOT / "gui/static/confirm.html").read_text(encoding="utf-8")
    assert "/api/job/" in html and "job_id" in html and "job_error" in html
    for name in ("COPY_RESELECT_RUNNING", "COPY_RESELECT_DONE", "COPY_RESELECT_FAILED", "COPY_RESELECT_BLOCKED"):
        assert name in html



def test_calibrate_hint_says_one_quote_per_line():  # M6 · KI-03 / D5
    html = (ROOT / "gui/static/calibrate.html").read_text(encoding="utf-8")
    assert "每句一行（也可以用逗号分隔）" in html and "用逗号分隔。" not in html
