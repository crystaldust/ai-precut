"""剪辑台：损坏文件不能当「没有」（KI-21）、LLM 兜底进警告栏（KI-22）、答案类型容错（KI-49）。"""
import json

from conftest import call, make_project


def _get(gs, path):
    status, body, _ = call(gs, "GET", path)
    return status, json.loads(body)


def test_state_warns_summary_and_questions_fallback(gui_server):
    make_project(gui_server.root, **{
        "work/content_summary.json": json.dumps({"fallback": True, "error": "超时"}),
        "work/questions.json": json.dumps({"fallback": True, "questions": []})})
    status, data = _get(gui_server, "/api/state?project=p1")
    assert status == 200
    text = "\n".join(data["warnings"])
    assert "内容摘要" in text and "决策问题" in text and "超时" in text
    assert "原因未记录" in text  # questions.json 没记 error


def test_state_no_fallback_no_notice(gui_server):
    make_project(gui_server.root, **{
        "work/content_summary.json": json.dumps({"fallback": False, "summary": "s"})})
    status, data = _get(gui_server, "/api/state?project=p1")
    assert status == 200 and data["warnings"] == []


# ---------------------------------------------------------------- KI-21：损坏不能当「没有」
def test_state_corrupt_project_json_is_409_not_404(gui_server):
    pdir = make_project(gui_server.root)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    status, data = _get(gui_server, "/api/state?project=p1")
    assert status == 409
    assert "project.json" in data["error"] and "损坏" in data["error"]
    assert "项目不存在" not in data["error"]


def test_state_missing_project_still_404(gui_server):
    status, _ = _get(gui_server, "/api/state?project=nope")
    assert status == 404


def test_state_lists_corrupt_files_in_warnings(gui_server):
    make_project(gui_server.root, **{
        "shots.json": "{坏", "work/segments.json": "[]",
        "work/shots-selected.json": json.dumps({"shots": [{"id": "sel01", "in": 0, "out": 2}]})})
    status, data = _get(gui_server, "/api/state?project=p1")
    assert status == 200
    text = "\n".join(data["warnings"])
    assert "分镜表（shots.json）" in text and "分段文稿" in text
    assert data["shots"] == [{"id": "sel01", "in": 0, "out": 2}]
    assert data["segments"] == []


def test_state_lists_corrupt_timeline(gui_server):
    make_project(gui_server.root, **{"output/v1/timeline.json": "{坏"})
    status, data = _get(gui_server, "/api/state?project=p1")
    assert status == 200
    assert any("v1" in w and "timeline.json" in w for w in data["warnings"])
    assert data["versions"][0]["shots"] == 0


def test_browse_corrupt_scored_is_409(gui_server):
    make_project(gui_server.root, **{"work/segments_scored.json": "{坏"})
    status, data = _get(gui_server, "/api/browse?project=p1")
    assert status == 409
    assert "segments_scored.json" in data["error"] and "还没有三档判定" not in data["error"]


def test_browse_missing_scored_still_404(gui_server):
    make_project(gui_server.root)
    status, data = _get(gui_server, "/api/browse?project=p1")
    assert status == 404 and "还没有三档判定" in data["error"]


QUESTIONS = {"fallback": False, "questions": [
    {"id": "q1", "text": "主角？", "type": "single",
     "options": [{"label": "a", "rule": {"kind": "focus", "value": "a"}},
                 {"label": "b", "rule": {"kind": "focus", "value": "b"}}]},
    {"id": "q2", "text": "必留？", "type": "multi",
     "options": [{"label": "合同条款", "rule": {"kind": "must_topics", "value": ["讲合同"]}},
                 {"label": "吃饭", "rule": {"kind": "must_topics", "value": ["聊吃饭"]}}]}]}


def _confirm_project(gs, **files):
    return make_project(gs.root, **{"work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False),
                                    **files})


def test_confirm_corrupt_questions_is_409(gui_server):
    make_project(gui_server.root, **{"work/questions.json": "{坏"})
    status, data = _get(gui_server, "/api/confirm?project=p1")
    assert status == 409 and "questions.json" in data["error"]


def test_confirm_missing_questions_still_404(gui_server):
    make_project(gui_server.root)
    status, _ = _get(gui_server, "/api/confirm?project=p1")
    assert status == 404


def test_confirm_corrupt_answers_reported(gui_server):
    _confirm_project(gui_server, **{"work/brief_answers.json": "[1]"})
    status, data = _get(gui_server, "/api/confirm?project=p1")
    assert status == 200
    assert data["answers"] == {} and data["answers_unreadable"] is True


def test_confirm_corrupt_summary_does_not_block_page(gui_server):
    _confirm_project(gui_server, **{"work/content_summary.json": "{坏"})
    status, data = _get(gui_server, "/api/confirm?project=p1")
    assert status == 200 and data["summary"] == {}


# ---------------------------------------------------------------- KI-49：答案类型容错
def test_confirm_multi_answer_coerced_to_list(gui_server):
    _confirm_project(gui_server, **{"work/brief_answers.json": json.dumps(
        {"answers": {"q2": "合同条款", "q1": ["a"]}}, ensure_ascii=False)})
    status, data = _get(gui_server, "/api/confirm?project=p1")
    assert status == 200
    assert data["answers"] == {"q2": ["合同条款"]}
    assert data["answers_unreadable"] is False


def test_confirm_answers_post_normalized(gui_server):
    pdir = _confirm_project(gui_server)
    status, _, _ = call(gui_server, "POST", "/api/confirm/answers",
                        {"project": "p1", "answers": {"q2": "合同条款", "q1": 3}, "confirmed": True})
    assert status == 200
    saved = json.loads((pdir / "work/brief_answers.json").read_text(encoding="utf-8"))
    assert saved["answers"] == {"q2": ["合同条款"]}
    assert saved["rules"]["must_topics"] == ["讲合同"]


def test_confirm_answers_post_corrupt_questions_is_409(gui_server):
    pdir = make_project(gui_server.root, **{"work/questions.json": "{坏"})
    status, _, _ = call(gui_server, "POST", "/api/confirm/answers",
                        {"project": "p1", "answers": {"q1": "a"}})
    assert status == 409
    assert not (pdir / "work/brief_answers.json").exists()


# ---------------------------------------------------------------- M8 补充：损坏的预设
def test_presets_skips_corrupt_and_warns(gui_server, monkeypatch, tmp_path_factory):
    d = tmp_path_factory.mktemp("presets")
    (d / "好.json").write_text(json.dumps({"name": "好", "duration": 60}), encoding="utf-8")
    (d / "坏.json").write_text("{坏", encoding="utf-8")
    (d / "列表.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(gui_server.module, "PRESETS", d)
    status, data = _get(gui_server, "/api/presets")
    assert status == 200
    assert [p["key"] for p in data["presets"]] == ["好"]
    text = "\n".join(data["warnings"])
    assert "坏.json" in text and "列表.json" in text


def test_presets_clean_has_empty_warnings(gui_server, preset_dir):
    status, data = _get(gui_server, "/api/presets")
    assert status == 200 and data["warnings"] == [] and len(data["presets"]) == 1
