"""M8 独立审查修复：损坏项目不能被写入（HIGH）、残留的裸 json.loads、无容器时长的素材、
浏览 / 确认页警告条、过期的已存规则、画面质量软失败、兜底原因进日志。"""
import argparse
import json
import logging
import sys
from pathlib import Path

import pytest

import aicut
from conftest import call, make_project
from gui import payloads
from pipeline import format_transcript, media_io, notices, questions, schema, select, select_rules, summarize
from pipeline import understand_visual as uv


def _j(body):
    return json.loads(body) if body else {}


def _corrupt_project(gs, **files):
    pdir = make_project(gs.root, shots=[{"id": "sh01", "in": 0, "out": 2}], **files)
    (pdir / "project.json").write_text("{坏", encoding="utf-8")
    return pdir


# ---------------------------------------------------------------- HIGH：损坏项目的写接口一律 409
WRITE_CALLS = [
    ("POST", "/api/shots?project=p1", {"shots": [{"id": "x1", "in": 0, "out": 1}]}),
    ("POST", "/api/job", {"project": "p1", "task": "select"}),
    ("POST", "/api/browse/level", {"project": "p1", "id": "S001", "level": 3}),
    ("POST", "/api/browse/must", {"project": "p1", "id": "S001", "must": True}),
    ("POST", "/api/confirm/answers", {"project": "p1", "answers": {}}),
    ("POST", "/api/calibrate", {"project": "p1", "calibration": {}}),
    ("POST", "/api/open", {"project": "p1", "target": "project"}),
    ("POST", "/api/open", {"project": "p1", "target": "export", "version": "v1"}),
    ("GET", "/api/calibrate?project=p1", None),
]


@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_write_endpoints_refuse_corrupt_project(gui_server, monkeypatch, method, path, body):
    monkeypatch.setattr(gui_server.module.subprocess, "run",
                        lambda *a, **k: pytest.fail("不应调用外部命令"))
    pdir = _corrupt_project(gui_server)
    before = (pdir / "shots.json").read_bytes()
    status, resp, _ = call(gui_server, method, path, body)
    assert status == 409
    assert "project.json" in _j(resp)["error"]
    assert (pdir / "shots.json").read_bytes() == before
    assert not (pdir / "work/overrides.json").exists()
    assert not (pdir / "work/brief_answers.json").exists()
    assert (pdir / "project.json").read_text(encoding="utf-8") == "{坏"


def test_diagnostics_still_allowed_for_corrupt_project(gui_server, monkeypatch, tmp_path):
    from gui import support
    seen = []
    monkeypatch.setattr(support.diagnostics, "build_bundle", lambda out, pdir: seen.append(pdir) or tmp_path / "d.zip")
    monkeypatch.setattr(support.diagnostics, "default_out_dir", lambda: tmp_path)
    pdir = _corrupt_project(gui_server)
    status, _, _ = call(gui_server, "POST", "/api/diagnostics", {"project": "p1"})
    assert status != 409 and seen and seen[0].name == pdir.name


def test_healthy_project_shots_still_saved(gui_server):
    pdir = make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/shots?project=p1",
                        {"shots": [{"id": "x1", "in": 0, "out": 1}]})
    assert status == 200
    assert json.loads((pdir / "shots.json").read_text(encoding="utf-8"))["source"] == "/tmp/a.mp4"


# ---------------------------------------------------------------- MEDIUM 2：select / format_transcript 的裸 json.loads
SCORED = {"target": 60, "topics": [{"name": "讲合同", "budget": 20, "count": 0, "duration": 0.0, "usable_dur": 0.0}],
          "segments": [{"id": "S001", "start": 0, "end": 6, "topic": "讲合同", "level": 3, "text": "x"}]}


def _w(path, obj):
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("answers", ["{坏", "[1]", '{"answers": [1]}', '{"answers": {}, "rules": [1]}'])
def test_select_corrupt_answers_is_corrupt_json(tmp_path, answers):
    sp = _w(tmp_path / "segments_scored.json", SCORED)
    ap = _w(tmp_path / "brief_answers.json", answers)
    with pytest.raises(schema.CorruptJSON, match="brief_answers.json"):
        select.run(sp, ap, tmp_path)


@pytest.mark.parametrize("qs", ["{坏", "[1]"])
def test_select_corrupt_questions_is_corrupt_json(tmp_path, qs):
    sp = _w(tmp_path / "segments_scored.json", SCORED)
    with pytest.raises(schema.CorruptJSON, match="questions.json"):
        select.run(sp, tmp_path / "none.json", tmp_path, questions_path=_w(tmp_path / "questions.json", qs))


@pytest.mark.parametrize("raw", ["{坏", "3", '"x"'])
def test_format_transcript_corrupt_raw_exits_with_file_name(tmp_path, monkeypatch, raw):
    p = _w(tmp_path / "transcript_raw.json", raw)
    monkeypatch.setattr(sys, "argv", ["format_transcript", str(p), "-o", str(tmp_path / "o")])
    with pytest.raises(SystemExit) as exc:
        format_transcript.main()
    assert "transcript_raw.json" in str(exc.value.code)


def test_corrupt_answers_notice_says_reanswer(tmp_path):
    work = tmp_path / "p/work"
    work.mkdir(parents=True)
    _w(work / "brief_answers.json", "{坏")
    _w(work / "segments.json", "{坏")
    text = "\n".join(notices.project_warnings(work))
    line = next(w for w in text.splitlines() if "brief_answers.json" in w)
    assert "④ 定标准" in line and "重新作答" in line and "处理素材" not in line
    seg_line = next(w for w in text.splitlines() if "segments.json" in w)
    assert "② 分析" in seg_line


# ---------------------------------------------------------------- MEDIUM 3：容器里没有时长
class FakeOut:
    def __init__(self, out, code=0, err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def _probe(out):
    return lambda cmd, **k: FakeOut(json.dumps(out))


def test_probe_material_falls_back_to_stream_duration():
    res = media_io.probe_material(Path("a.mkv"), runner=_probe(
        {"format": {}, "streams": [{"codec_type": "video", "duration": "12.5"},
                                   {"codec_type": "audio", "duration": "N/A"}]}))
    assert res["duration"] == 12.5 and res["warnings"] == []


def test_probe_material_no_duration_anywhere_warns_not_fails():
    res = media_io.probe_material(Path("a.mkv"), runner=_probe({"format": {"duration": "N/A"},
                                                               "streams": [{"codec_type": "video"}]}))
    assert res["duration"] == 0.0
    assert res["warnings"] and "容器里没有时长信息" in res["warnings"][0]


def test_probe_material_ffprobe_cannot_read_still_fails():
    with pytest.raises(media_io.MediaError, match="ffprobe 认不出"):
        media_io.probe_material(Path("a.mkv"), runner=lambda cmd, **k: FakeOut("", 1, "Invalid data"))


def test_ingest_without_duration_records_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    src = tmp_path / "src.mkv"
    src.write_bytes(b"x")
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", str(src)))
    monkeypatch.setattr(media_io, "_run_probe", lambda cmd, runner: (0, json.dumps({"format": {}, "streams": []}), ""))
    aicut.cmd_ingest(argparse.Namespace(name="p"))
    out = capsys.readouterr().out
    assert "[!]" in out and "容器里没有时长信息" in out
    data = json.loads((pdir / "work/materials.json").read_text(encoding="utf-8"))
    assert data["items"][0]["duration"] == 0.0
    assert any("容器里没有时长信息" in w for w in notices.project_warnings(pdir / "work"))


# ---------------------------------------------------------------- MEDIUM 4：浏览 / 确认页带警告
def test_browse_and_confirm_payloads_include_warnings(tmp_path):
    pdir = tmp_path / "p1"
    work = pdir / "work"
    work.mkdir(parents=True)
    _w(pdir / "project.json", {"name": "p1", "material": "/a"})
    _w(work / "segments_scored.json", SCORED)
    _w(work / "questions.json", {"questions": []})
    _w(work / "junk_report.json", "{坏")
    for data in (payloads.browse(pdir, "p1"), payloads.confirm(pdir)):
        assert any("junk_report.json" in w for w in data["warnings"])


# ---------------------------------------------------------------- LOW 6：过期的已存规则 / 排除话题对不上
QS = {"questions": [{"id": "q1", "type": "single", "options": [
    {"label": "合同全额", "rule": {"kind": "must_topics", "value": ["讲合同"]}}]}]}


def test_stale_stored_rules_recomputed_and_warned(tmp_path):
    sp = _w(tmp_path / "segments_scored.json", SCORED)
    ap = _w(tmp_path / "brief_answers.json", {"answers": {"q1": "旧选项"},
                                              "rules": {"must_topics": ["旧话题"], "exclude_topics": ["讲合同"]}})
    res = select.run(sp, ap, tmp_path, questions_path=_w(tmp_path / "questions.json", QS))
    assert "讲合同" not in res["rules"]["exclude_topics"]  # 旧规则不再生效
    assert any("旧选项" in w for w in res["warnings"])
    assert [s["segment_id"] for s in res["shots"]] == ["S001"]


def test_fresh_stored_rules_still_used(tmp_path):
    sp = _w(tmp_path / "segments_scored.json", SCORED)
    ap = _w(tmp_path / "brief_answers.json", {"answers": {"q1": "合同全额"},
                                              "rules": {"must_topics": ["讲合同"], "ending": "sign"},
                                              "rules_version": select_rules.RULES_VERSION})
    res = select.run(sp, ap, tmp_path, questions_path=_w(tmp_path / "questions.json", QS))
    assert res["rules"]["ending"] == "sign"
    assert not any("不在当前的决策问题里" in w for w in res["warnings"])


def test_unmatched_exclude_topic_warned():
    res = select.select(SCORED["segments"], SCORED["topics"], {"exclude_topics": ["完全无关"]}, 60)
    assert any("完全无关" in w and "排除" in w for w in res["warnings"])


# ---------------------------------------------------------------- LOW 7：画面质量失败只警告
def test_quality_failure_warns_and_continues(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", "/a.mov"))
    with media_io.atomic_output(pdir / "work/proxy.mp4") as tmp:
        tmp.write_bytes(b"proxy")
    _w(pdir / "work/segments.json", {"segments": []})
    stale = _w(pdir / "work/visual_quality.json", {"segments": {}})
    monkeypatch.setattr(uv, "sample_frames", lambda *a, **k: (_ for _ in ()).throw(
        media_io.MediaError("抽帧失败（退出码 1）：Invalid data")))
    aicut.cmd_quality(argparse.Namespace(name="p"))  # 不退出
    out = capsys.readouterr().out
    assert "[!]" in out and "Invalid data" in out
    assert not stale.exists()  # 旧结果不能被分档当成这次的


# ---------------------------------------------------------------- LOW 8：兜底的真实原因进日志
class Boom:
    model = "m"

    def chat_json(self, *a, **k):
        raise RuntimeError("真实原因 xyz")


@pytest.mark.parametrize("mod", ["summarize", "questions"])
def test_fallback_logs_real_error(tmp_path, caplog, monkeypatch, mod):
    from pipeline import applog
    root = logging.getLogger(applog.ROOT_LOGGER)  # 应用日志不往 root 传，直接挂到应用根 logger 上
    root.addHandler(caplog.handler)
    monkeypatch.setattr(root, "level", logging.DEBUG)
    text = _w(tmp_path / "t.json", {"segments": [], "topics": []})
    scored = _w(tmp_path / "s.json", {"segments": [], "topics": []})
    summary = _w(tmp_path / "sum.json", {"summary": "s"})
    with caplog.at_level(logging.ERROR):
        if mod == "summarize":
            res = summarize.run(text, scored, tmp_path / "o.json", client=Boom())
        else:
            res = questions.run(summary, scored, tmp_path / "o.json", client=Boom())
    assert res["fallback"] is True
    root.removeHandler(caplog.handler)
    assert any(r.levelno >= logging.ERROR and r.exc_info and "真实原因 xyz" in str(r.exc_info[1])
               for r in caplog.records)


def test_missing_must_keep_corrupt_scored_is_corrupt_json(tmp_path):
    _w(tmp_path / "segments_scored.json", "{坏")
    with pytest.raises(schema.CorruptJSON, match="segments_scored.json"):
        select.missing_must_keep(tmp_path, [])
    assert select.missing_must_keep(tmp_path / "none", []) == []
