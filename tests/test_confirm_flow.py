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


def _stored(pdir):
    return json.loads((pdir / "work/brief_answers.json").read_text(encoding="utf-8"))


def test_save_writes_questions_digest(gui_server):
    from pipeline import fingerprints
    pdir = _project(gui_server)
    _save(gui_server, answers={"q1": "签字"})
    assert _stored(pdir)["questions_digest"] == fingerprints.file_digest(pdir / "work/questions.json")


def test_draft_without_confirmed_key_keeps_stored_confirmed_and_starts_nothing(gui_server, monkeypatch):
    from gui import jobs
    pdir = _project(gui_server)
    (pdir / "work/brief_answers.json").write_text(
        json.dumps({"answers": {"q1": "签字"}, "confirmed": True}), encoding="utf-8")
    seen = fake_command(monkeypatch, jobs, QUICK)
    status, data = _save(gui_server, answers={"q1": "全部"})
    assert status == 200 and data["job_id"] is None
    assert seen == [] and _stored(pdir)["confirmed"] is True
    assert _stored(pdir)["answers"] == {"q1": "全部"}


def test_explicit_confirmed_false_cancels_confirmation(gui_server):
    pdir = _project(gui_server)
    (pdir / "work/brief_answers.json").write_text(
        json.dumps({"answers": {}, "confirmed": True}), encoding="utf-8")
    _save(gui_server, answers={"q1": "全部"}, confirmed=False)
    assert _stored(pdir)["confirmed"] is False


def test_draft_with_corrupt_stored_answers_still_saves(gui_server):
    pdir = _project(gui_server)
    (pdir / "work/brief_answers.json").write_text("{坏", encoding="utf-8")
    status, _ = _save(gui_server, answers={"q1": "全部"})
    assert status == 200 and _stored(pdir)["confirmed"] is False


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


def test_index_has_confirm_entry():  # KI-53：脚本外置到 index.js；KI-36：子页面经 openSubpage 打开
    html = (ROOT / "gui/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "gui/static/index.js").read_text(encoding="utf-8")
    assert 'data-act="openConfirm"' in html and "openSubpage('confirm')" in js
    assert "/static/${page}.html?project=" in js and "COPY_CONFIRM_ENTRY" in js


def test_confirm_page_polls_job():
    html = (ROOT / "gui/static/confirm.js").read_text(encoding="utf-8")  # KI-53：脚本外置
    assert "/api/job/" in html and "job_id" in html and "job_error" in html
    for name in ("COPY_RESELECT_RUNNING", "COPY_RESELECT_DONE", "COPY_RESELECT_FAILED", "COPY_RESELECT_BLOCKED"):
        assert name in html



def test_calibrate_hint_says_one_quote_per_line():  # M6 · KI-03 / D5
    html = (ROOT / "gui/static/calibrate.html").read_text(encoding="utf-8")
    assert "每句一行（也可以用逗号分隔）" in html and "用逗号分隔。" not in html


def test_saved_answers_carry_rules_version(tmp_path):  # KI-84
    import json as _json
    from gui import confirm
    from pipeline import select_rules
    work = tmp_path / "p/work"
    work.mkdir(parents=True)
    (work / "questions.json").write_text(_json.dumps({"questions": []}), encoding="utf-8")
    confirm.save_answers(tmp_path / "p", "p", {"answers": {}, "confirmed": False})
    saved = _json.loads((work / "brief_answers.json").read_text(encoding="utf-8"))
    assert saved["rules_version"] == select_rules.RULES_VERSION


# ---------------------------------------------------------------- KI-86：旧版决策问题（focus 是自由文本）
LEGACY_QS = {"questions": [{"id": "q1", "text": "主角？", "type": "single", "options": [
    {"label": "妈妈", "rule": {"kind": "focus", "value": "妈妈"}},
    {"label": "群像", "rule": {"kind": "focus", "value": "ensemble"}}]}]}


def test_legacy_focus_detected():
    from pipeline import questions
    assert questions.has_legacy_focus(LEGACY_QS)
    assert not questions.has_legacy_focus(QUESTIONS)
    assert not questions.has_legacy_focus({"questions": [{"options": [
        {"rule": {"kind": "focus", "value": "main"}}]}]})
    assert not questions.has_legacy_focus(None)


def test_confirm_payload_flags_stale_questions(gui_server):
    make_project(gui_server.root, **{"work/questions.json": json.dumps(LEGACY_QS, ensure_ascii=False)})
    status, raw, _ = call(gui_server, "GET", "/api/confirm?project=p1")
    data = json.loads(raw)
    assert status == 200 and data["stale_questions"] is True and data["stale_hint"]
    _project_fresh = make_project(gui_server.root, name="p2",
                                  **{"work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})
    status, raw, _ = call(gui_server, "GET", "/api/confirm?project=p2")
    assert json.loads(raw)["stale_questions"] is False


def test_regenerate_questions_job_runs_force(gui_server, monkeypatch, consented):
    from gui import jobs
    from pipeline import secrets
    secrets.set("deepseek", "sk-regeneratekey1234")
    _project(gui_server)
    seen = fake_command(monkeypatch, jobs, QUICK)
    status, data = post_job(gui_server, task="questions")
    assert status == 200 and seen[0][0] == "questions"
    assert jobs.JOB_COMMANDS["questions"] == ["questions", "--force"]
    assert jobs.job_command.__module__  # 真实命令行由 JOB_COMMANDS 拼出
    assert wait_for(lambda: get_job(gui_server, data["job_id"])[1]["status"] == "done")


def test_regenerate_questions_needs_deepseek_key(gui_server, monkeypatch, consented):
    from gui import jobs
    _project(gui_server)
    fake_command(monkeypatch, jobs, QUICK)
    status, data = post_job(gui_server, task="questions")
    assert status == 409 and data["need"] == "keys" and data["missing"] == ["deepseek"]


def test_regenerate_questions_needs_consent(gui_server, monkeypatch):
    from gui import jobs
    _project(gui_server)
    fake_command(monkeypatch, jobs, QUICK)
    status, data = post_job(gui_server, task="questions")
    assert status == 409 and data["need"] == "consent"
