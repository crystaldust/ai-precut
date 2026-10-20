# -*- coding: utf-8 -*-
"""M13 T9b：新建带偏好、项目设置、话题显示名（P3）。"""
import json

import pytest

from conftest import call, make_project
from gui import wizard
from pipeline import fingerprints, topic_names

NEW = {"name": "n1", "material": "/tmp/a.mp4", "preset": "纪实3min"}
SCORED = {"target": 60, "topics": [{"name": "讲合同", "budget": 20}, {"name": "聊吃饭", "budget": 10}],
          "segments": [{"id": "S001", "start": 0, "end": 6, "topic": "讲合同", "level": 3, "text": "a"},
                       {"id": "S002", "start": 10, "end": 16, "topic": "聊吃饭", "level": 2, "text": "b"}]}
QUESTIONS = {"questions": [{"id": "q1", "text": "结尾？", "type": "single", "options": [
    {"label": "讲合同", "rule": {"kind": "must_topics", "value": ["讲合同"]}}]}]}


@pytest.fixture
def recorder(gui_server, monkeypatch):
    calls = []

    def fake_run_aicut(args):
        calls.append(args)
        return 0, ""

    monkeypatch.setattr(gui_server.module, "run_aicut", fake_run_aicut)
    return calls


def post(gs, path, body):
    status, raw, _ = call(gs, "POST", path, body)
    return status, json.loads(raw)


def project_json(gs, name="p1"):
    return json.loads((gs.root / name / "project.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- /api/new + calibration
def test_new_with_calibration_passes_all_three_flags(gui_server, recorder):
    cal = {"tone": "info", "audience": "家长", "must_lines": "第一句\n第二句"}
    status, _ = post(gui_server, "/api/new", {**NEW, "calibration": cal})
    assert status == 200
    args = recorder[0]
    assert "--tone=info" in args and "--audience=家长" in args
    assert "--must-lines=第一句\n第二句" in args


def test_new_without_calibration_has_exactly_the_old_args(gui_server, recorder):
    post(gui_server, "/api/new", NEW)
    assert recorder[0] == ["new", "n1", "--no-input", "--material=/tmp/a.mp4",
                           "--preset=纪实3min", "--title=n1"]


def test_new_dash_prefixed_values_stay_inside_flag(gui_server, recorder):
    post(gui_server, "/api/new", {**NEW, "calibration": {"audience": "--evil", "must_lines": "-x"}})
    assert "--audience=--evil" in recorder[0] and "--must-lines=-x" in recorder[0]


def test_new_rejects_four_must_lines(gui_server, recorder):
    status, data = post(gui_server, "/api/new", {**NEW, "calibration": {"must_lines": "a\nb\nc\nd"}})
    assert status == 400 and "最多 3 句" in data["error"] and recorder == []


def test_new_three_must_lines_with_blank_lines_ok(gui_server, recorder):
    status, _ = post(gui_server, "/api/new", {**NEW, "calibration": {"must_lines": "a\n\nb\n  \nc"}})
    assert status == 200


@pytest.mark.parametrize("cal", [{"tone": "loud"}, {"tone": 3}, {"audience": 5}, {"must_lines": ["a"]},
                                 "info", ["info"], {"audience": "a\x00b"}, {"audience": "a\u202eb"},
                                 {"must_lines": "a\u200bb"}, {"audience": "字" * 61},
                                 {"must_lines": "字" * 201}])
def test_new_rejects_bad_calibration(gui_server, recorder, cal):
    status, data = post(gui_server, "/api/new", {**NEW, "calibration": cal})
    assert status == 400 and data["error"] and recorder == []


def test_new_null_calibration_is_same_as_missing(gui_server, recorder):
    assert post(gui_server, "/api/new", {**NEW, "calibration": None})[0] == 200
    assert len(recorder[0]) == 6


# ---------------------------------------------------------------- /api/project/settings
@pytest.fixture
def presets(preset_dir):
    (preset_dir / "另一个.json").write_text(json.dumps({"name": "另", "platform": "kuaishou"}),
                                           encoding="utf-8")
    return preset_dir


def _settings_project(gs, **extra):
    pdir = make_project(gs.root)
    cfg = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    (pdir / "project.json").write_text(json.dumps(
        {**cfg, "preset": "测试预设", "platform": "douyin", "target_duration": 99,
         "calibration": {"tone": "balanced", "audience": "", "must_lines": ""}, **extra},
        ensure_ascii=False), encoding="utf-8")
    return pdir


def test_settings_updates_title_preset_platform_and_keeps_target(gui_server, presets):
    _settings_project(gui_server)
    status, data = post(gui_server, "/api/project/settings", {
        "project": "p1", "title": "新片名", "preset": "另一个",
        "calibration": {"tone": "emotion", "audience": "学生", "must_lines": "好"}})
    assert status == 200 and data["ok"] is True
    cfg = project_json(gui_server)
    assert cfg["title"] == "新片名" and cfg["preset"] == "另一个" and cfg["platform"] == "kuaishou"
    assert cfg["target_duration"] == 99  # KI-92：不动目标时长
    assert cfg["calibration"] == {"tone": "emotion", "audience": "学生", "must_lines": "好"}
    assert data["project"]["title"] == "新片名" and len(data["wizard"]["steps"]) == 6


def test_settings_partial_update_leaves_other_fields(gui_server, presets):
    _settings_project(gui_server)
    post(gui_server, "/api/project/settings", {"project": "p1", "title": "只改片名"})
    cfg = project_json(gui_server)
    assert cfg["title"] == "只改片名" and cfg["preset"] == "测试预设" and cfg["platform"] == "douyin"


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "a/b"}, {"title": 5},
                                  {"preset": "没有这个"}, {"preset": 3},
                                  {"calibration": {"tone": "x"}}, {"calibration": {"must_lines": "a\nb\nc\nd"}},
                                  {"calibration": "info"}, {}])
def test_settings_rejects_bad_input_without_writing(gui_server, presets, body):
    _settings_project(gui_server)
    before = (gui_server.root / "p1/project.json").read_bytes()
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", **body})
    assert status == 400 and data["error"]
    assert (gui_server.root / "p1/project.json").read_bytes() == before


def test_settings_missing_project_404_bad_name_400_corrupt_409(gui_server, presets):
    assert post(gui_server, "/api/project/settings", {"project": "nope", "title": "x"})[0] == 404
    assert post(gui_server, "/api/project/settings", {"project": "../x", "title": "x"})[0] == 400
    pdir = _settings_project(gui_server)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    assert post(gui_server, "/api/project/settings", {"project": "p1", "title": "x"})[0] == 409


def test_settings_changing_tone_makes_finished_analysis_stale(gui_server, presets, monkeypatch):
    from pipeline import media_io
    monkeypatch.setattr(media_io, "is_complete", lambda p, **k: p.exists())
    pdir = _settings_project(gui_server)
    for rel, content in {"work/proxy.mp4": b"x", "work/segments_scored.json": "{}",
                         "work/content_summary.json": "{}", "work/questions.json": "{}",
                         "work/selection.json": "{}"}.items():
        (pdir / rel).write_bytes(content if isinstance(content, bytes) else content.encode())
    cfg = project_json(gui_server)
    (pdir / "work/analysis_inputs.json").write_text(
        json.dumps(fingerprints.analysis_inputs(cfg)), encoding="utf-8")
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "calibration": {"tone": "info"}})
    analyze = next(s for s in data["wizard"]["steps"] if s["key"] == "analyze")
    assert status == 200 and analyze["status"] == wizard.STALE


def test_settings_requires_session(gui_server, presets):
    _settings_project(gui_server)
    status, _, _ = call(gui_server, "POST", "/api/project/settings", {"project": "p1", "title": "x"}, token=False)
    assert status == 403


# ---------------------------------------------------------------- 话题显示名（P3）
def _topic_project(gs):
    return make_project(gs.root, **{"work/segments_scored.json": json.dumps(SCORED, ensure_ascii=False),
                                    "work/questions.json": json.dumps(QUESTIONS, ensure_ascii=False)})


def test_rename_writes_mapping_and_returns_it(gui_server):
    pdir = _topic_project(gui_server)
    status, data = post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": " 谈合同 "})
    assert status == 200 and data["topic_names"] == {"讲合同": "谈合同"}
    assert json.loads((pdir / "work/topic_names.json").read_text(encoding="utf-8")) == {"讲合同": "谈合同"}


def test_rename_empty_display_restores_original(gui_server):
    pdir = _topic_project(gui_server)
    post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "谈合同"})
    status, data = post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": ""})
    assert status == 200 and data["topic_names"] == {}
    assert json.loads((pdir / "work/topic_names.json").read_text(encoding="utf-8")) == {}


@pytest.mark.parametrize("body", [{"display": "字" * 21}, {"name": "没有这个话题", "display": "x"},
                                  {"display": 5}, {"name": 5, "display": "x"}, {"display": "聊吃饭"},
                                  {"display": "a\nb"}])
def test_rename_rejects_bad_input(gui_server, body):
    pdir = _topic_project(gui_server)
    status, data = post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", **body})
    assert status == 400 and data["error"]
    assert not (pdir / "work/topic_names.json").exists()


def test_rename_twenty_chars_ok(gui_server):
    _topic_project(gui_server)
    assert post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "字" * 20})[0] == 200


def test_rename_without_analysis_is_400_and_missing_project_404(gui_server):
    make_project(gui_server.root)
    assert post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "x"})[0] == 400
    assert post(gui_server, "/api/topics/rename", {"project": "nope", "name": "a", "display": "x"})[0] == 404


def test_rename_corrupt_names_file_409(gui_server):
    pdir = _topic_project(gui_server)
    (pdir / "work/topic_names.json").write_text("{坏", encoding="utf-8")
    assert post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "x"})[0] == 409


def test_browse_shows_display_names_with_raw(gui_server):
    _topic_project(gui_server)
    post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "谈合同"})
    data = json.loads(call(gui_server, "GET", "/api/browse?project=p1")[1])
    seg = next(s for s in data["segments"] if s["id"] == "S001")
    assert seg["topic"] == "谈合同" and seg["topic_raw"] == "讲合同"
    other = next(s for s in data["segments"] if s["id"] == "S002")
    assert other["topic"] == "聊吃饭" and other["topic_raw"] == "聊吃饭"
    topics = {t["topic_raw"]: t["name"] for t in data["topics"]}
    assert topics["讲合同"] == "谈合同" and topics["聊吃饭"] == "聊吃饭"


def test_confirm_lists_topics_with_display_and_raw(gui_server):
    _topic_project(gui_server)
    post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "谈合同"})
    data = json.loads(call(gui_server, "GET", "/api/confirm?project=p1")[1])
    assert {"topic": "谈合同", "topic_raw": "讲合同"} in data["topics"]
    assert {"topic": "聊吃饭", "topic_raw": "聊吃饭"} in data["topics"]


def test_selection_still_matches_raw_names(gui_server):
    """显示名不进算法：sele 的话题匹配键仍是原名，segments_scored.json 不被改写。"""
    pdir = _topic_project(gui_server)
    before = (pdir / "work/segments_scored.json").read_bytes()
    post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "谈合同"})
    assert (pdir / "work/segments_scored.json").read_bytes() == before


def test_topic_names_module_helpers(tmp_path):
    assert topic_names.load(tmp_path) == {}
    mapping = topic_names.rename(tmp_path, "a", "甲")
    assert mapping == {"a": "甲"} and topic_names.display("a", mapping) == "甲"
    assert topic_names.display("b", mapping) == "b"
    assert topic_names.rename(tmp_path, "a", "") == {}


# ---------------------------------------------------------------- 评审修复
@pytest.mark.parametrize("preset", ["../x", "a/b", "..\\x", "..", "测试预设/../另一个", ""])
def test_settings_preset_is_whitelisted_by_stem(gui_server, presets, preset, tmp_path):
    _settings_project(gui_server)
    (gui_server.root / "x.json").write_text(json.dumps({"platform": "evil"}), encoding="utf-8")
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "preset": preset})
    assert status == 400 and "未知预设" in data["error"]
    assert project_json(gui_server)["preset"] == "测试预设"


def test_settings_preset_json_not_object_is_rejected(gui_server, presets):
    _settings_project(gui_server)
    (presets / "坏的.json").write_text("[1, 2]", encoding="utf-8")
    status, _ = post(gui_server, "/api/project/settings", {"project": "p1", "preset": "坏的"})
    assert status in (400, 409)
    assert project_json(gui_server)["preset"] == "测试预设"


@pytest.mark.parametrize("platform", [5, ["a"], None, {"a": 1}])
def test_settings_preset_platform_must_be_text(gui_server, presets, platform):
    _settings_project(gui_server)
    (presets / "怪的.json").write_text(json.dumps({"platform": platform}), encoding="utf-8")
    status, data = post(gui_server, "/api/project/settings", {"project": "p1", "preset": "怪的"})
    if platform is None:  # 缺省平台 = douyin（与 aicut new 一致）；显式 null 同样视为没写
        assert status == 200 and project_json(gui_server)["platform"] == "douyin"
    else:
        assert status == 400 and "platform" in data["error"]
        assert project_json(gui_server)["platform"] == "douyin"


def test_calibration_null_fields_are_not_given(gui_server, recorder):
    status, _ = post(gui_server, "/api/new", {**NEW, "calibration": {"tone": None, "audience": None,
                                                                    "must_lines": None}})
    assert status == 200 and len(recorder[0]) == 6


def test_settings_calibration_null_keeps_current(gui_server, presets):
    _settings_project(gui_server, calibration={"tone": "info", "audience": "家长", "must_lines": ""})
    post(gui_server, "/api/project/settings", {"project": "p1", "calibration": {"tone": None, "audience": "学生"}})
    assert project_json(gui_server)["calibration"]["tone"] == "info"
    assert project_json(gui_server)["calibration"]["audience"] == "学生"


@pytest.mark.parametrize("cal,msg", [({"audience": "字" * 61}, "60"), ({"must_lines": "字" * 201}, "200")])
def test_calibration_length_limits_have_clear_message(gui_server, recorder, cal, msg):
    status, data = post(gui_server, "/api/new", {**NEW, "calibration": cal})
    assert status == 400 and msg in data["error"] and recorder == []


def test_calibration_at_limits_ok(gui_server, recorder):
    cal = {"audience": "字" * 60, "must_lines": "字" * 200}
    assert post(gui_server, "/api/new", {**NEW, "calibration": cal})[0] == 200


@pytest.mark.parametrize("bad", ["a\u0085b", "a​b", "a b", "a‮b", "a⁦b", "a﻿b", "a\u009fb"])
def test_rename_rejects_invisible_and_bidi_characters(gui_server, bad):
    _topic_project(gui_server)
    assert post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": bad})[0] == 400


def test_rename_duplicate_check_uses_nfkc(gui_server):
    _topic_project(gui_server)
    post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "ABC"})
    status, data = post(gui_server, "/api/topics/rename", {"project": "p1", "name": "聊吃饭", "display": "ＡＢＣ"})
    assert status == 400 and "已经有" in data["error"]


def test_rename_duplicate_checked_inside_lock(gui_server, monkeypatch):
    """检查与写入之间别人先改成同名：重名检查必须在 update 的回调里（锁内）做。"""
    pdir = _topic_project(gui_server)
    real = topic_names.schema.update

    def racing(path, mutate):
        (pdir / "work/topic_names.json").write_text(json.dumps({"聊吃饭": "撞名"}), encoding="utf-8")
        return real(path, mutate)

    monkeypatch.setattr(topic_names.schema, "update", racing)
    status, data = post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "撞名"})
    assert status == 400 and "已经有" in data["error"]
    assert json.loads((pdir / "work/topic_names.json").read_text(encoding="utf-8")) == {"聊吃饭": "撞名"}


@pytest.mark.parametrize("topics", ["讲合同", 5, {"name": "x"}, [5, None]])
def test_rename_tolerates_malformed_topics_field(gui_server, topics):
    make_project(gui_server.root, **{"work/segments_scored.json": json.dumps({"topics": topics})})
    status, _ = post(gui_server, "/api/topics/rename", {"project": "p1", "name": "讲合同", "display": "x"})
    assert status == 400
