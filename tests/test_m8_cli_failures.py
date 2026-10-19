"""里程碑 8「失败可见」：aicut 接线（KI-19 / KI-20 / KI-21 / KI-22 / KI-48 / KI-56 / KI-66）。

全部用打桩，不依赖 ffmpeg / 网络。
"""
import argparse
import io
import json
from pathlib import Path

import pytest

import aicut
from pipeline import media_io, schema
from pipeline import understand_visual as uv

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", str(tmp_path / "src.mov")))
    return pdir


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def _fail(*a, **k):
    raise AssertionError("不应调用")


def _output(capsys) -> str:
    """stdout + stderr：traceback 打在 stderr，断言「没有 traceback」必须两边都看。"""
    captured = capsys.readouterr()
    return captured.out + captured.err


def _complete_proxy(pdir):
    proxy = pdir / "work/proxy.mp4"
    with media_io.atomic_output(proxy) as tmp:
        tmp.write_bytes(b"proxy")
    return proxy


# ---------------------------------------------------------------- KI-19：镜头切分 / 抽帧
class FakePopen:
    def __init__(self, data=b"", code=0, err=b""):
        self.stdout = io.BytesIO(data)
        self._code, self._err, self.killed = code, err, False

    def __call__(self, cmd, stdout=None, stderr=None):
        if hasattr(stderr, "write"):
            stderr.write(self._err)
            stderr.flush()
        return self

    def wait(self, timeout=None):
        return self._code

    def poll(self):
        return self._code

    def kill(self):
        self.killed = True


def test_detect_cuts_raises_when_ffmpeg_fails(monkeypatch):
    monkeypatch.setattr(media_io, "run_analysis",
                        _raise(media_io.MediaError("ffmpeg 失败（退出码 1）：moov atom not found")))
    with pytest.raises(media_io.MediaError, match="moov atom"):
        uv.detect_cuts(Path("x.mp4"))


def test_detect_cuts_parses_analysis_log(monkeypatch):
    log = "[scdet @ 0x1] lavfi.scd.score: 30, lavfi.scd.time: 4.5\n[scdet] lavfi.scd.time: 2.0\n"
    monkeypatch.setattr(media_io, "run_analysis", lambda *a, **k: log)
    assert uv.detect_cuts(Path("x.mp4")) == [2.0, 4.5]


def test_analyze_duration_failure_is_media_error(monkeypatch):
    monkeypatch.setattr(media_io, "probe_duration",
                        _raise(media_io.MediaError("读不到时长：x.mp4（moov atom not found）")))
    with pytest.raises(media_io.MediaError, match="读不到时长"):
        uv.analyze(Path("x.mp4"))


def test_sample_frames_nonzero_exit_raises():
    fake = FakePopen(code=1, err=b"Invalid data found when processing input")
    with pytest.raises(media_io.MediaError, match="Invalid data found") as exc:
        uv.sample_frames(Path("x.mp4"), popen=fake)
    assert "退出码 1" in str(exc.value)


def test_sample_frames_zero_frames_raises():
    with pytest.raises(media_io.MediaError, match="一帧画面也没读到"):
        uv.sample_frames(Path("x.mp4"), popen=FakePopen(code=0))


def test_sample_frames_ok_does_not_kill_finished_process():
    w, h = 4, 4
    fake = FakePopen(data=bytes([100] * (w * h)) * 2, code=0)
    frames = uv.sample_frames(Path("x.mp4"), width=w, height=h, popen=fake)
    assert len(frames) == 2 and frames[0]["bright"] == 100.0
    assert not fake.killed


def test_scenes_dies_with_reason(project, monkeypatch, capsys):
    _complete_proxy(project)
    monkeypatch.setattr(media_io, "probe_duration", lambda *a, **k: 10.0)
    monkeypatch.setattr(media_io, "run_analysis",
                        _raise(media_io.MediaError("ffmpeg 失败（退出码 1）：Invalid data found")))
    with pytest.raises(SystemExit):
        aicut.cmd_scenes(argparse.Namespace(name="p", threshold=8.0))
    out = capsys.readouterr().out
    assert "镜头切分失败" in out and "Invalid data found" in out
    assert not (project / "work/shots_visual.json").exists()


def test_quality_failure_is_visible_warning(project, monkeypatch, capsys):
    # M8 审查 LOW 7：画面质量只是加分项，失败 [!] 警告后继续（分档会注明没用上画面质量）
    _complete_proxy(project)
    (project / "work/segments.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
    monkeypatch.setattr(uv, "sample_frames",
                        _raise(media_io.MediaError("抽帧失败（退出码 1）：Invalid data found")))
    aicut.cmd_quality(argparse.Namespace(name="p"))
    out = capsys.readouterr().out
    assert "[!]" in out and "画面质量分析失败" in out and "Invalid data found" in out
    assert not (project / "work/visual_quality.json").exists()


# ---------------------------------------------------------------- KI-20：残留的 check=True
def test_no_check_true_left_in_pipeline():
    for f in [ROOT / "aicut.py", *sorted((ROOT / "pipeline").glob("*.py"))]:
        assert "check=True" not in f.read_text(encoding="utf-8"), f.name


# ---------------------------------------------------------------- KI-22：LLM 兜底不固化、原因可见
THREE_QUESTIONS = [{"id": f"q{i}", "text": "?", "type": "single",
                    "options": [{"label": "a"}, {"label": "b"}]} for i in (1, 2, 3)]


def _prep_questions(pdir, *, answered):
    work = pdir / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "content_summary.json").write_text("{}", encoding="utf-8")
    (work / "segments_scored.json").write_text('{"segments": []}', encoding="utf-8")
    (work / "questions.json").write_text(json.dumps(
        {"fallback": True, "error": "HTTP 402: Insufficient Balance", "questions": THREE_QUESTIONS}),
        encoding="utf-8")
    if answered:
        (work / "brief_answers.json").write_text('{"answers": {"q1": "a"}}', encoding="utf-8")


def test_questions_regenerates_cached_fallback(project, monkeypatch, consented, capsys):
    _prep_questions(project, answered=False)
    calls = []
    monkeypatch.setattr(aicut.questions, "run", lambda *a, **k: calls.append(a) or
                        {"questions": THREE_QUESTIONS, "fallback": False})
    aicut.cmd_questions(argparse.Namespace(name="p", force=False))
    assert len(calls) == 1


def test_questions_keeps_answered_fallback_and_warns(project, monkeypatch, consented, capsys):
    _prep_questions(project, answered=True)
    monkeypatch.setattr(aicut.questions, "run", _fail)
    aicut.cmd_questions(argparse.Namespace(name="p", force=False))
    out = capsys.readouterr().out
    assert "[!]" in out and "兜底" in out and "HTTP 402" in out


def test_questions_fallback_result_prints_reason(project, monkeypatch, consented, capsys):
    _prep_questions(project, answered=False)
    monkeypatch.setattr(aicut.questions, "run", lambda *a, **k: {
        "questions": THREE_QUESTIONS, "fallback": True, "error": "网络错误：timed out"})
    aicut.cmd_questions(argparse.Namespace(name="p", force=False))
    out = capsys.readouterr().out
    assert "[!]" in out and "网络错误：timed out" in out


def test_summary_fallback_prints_reason(project, monkeypatch, consented, capsys):
    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "segments_text.json").write_text("{}", encoding="utf-8")
    (work / "segments_scored.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(aicut.summarize, "run", lambda *a, **k: {
        "summary": "s", "fallback": True, "error": "HTTP 402: Insufficient Balance"})
    aicut.cmd_summary(argparse.Namespace(name="p"))
    out = capsys.readouterr().out
    assert "[!]" in out and "HTTP 402" in out


# ---------------------------------------------------------------- KI-66 / KI-19：素材台账
def test_ingest_unrecognized_material_dies_without_traceback(project, monkeypatch, capsys):
    (project.parent / "src.mov").write_bytes(b"not a video")
    monkeypatch.setattr(media_io, "probe_material", _raise(media_io.MediaError(
        media_io.MATERIAL_UNREADABLE.format(detail="Invalid data found when processing input"))))
    with pytest.raises(SystemExit):
        aicut.cmd_ingest(argparse.Namespace(name="p"))
    out = capsys.readouterr().out
    assert "素材读不出来" in out and "Invalid data found" in out
    assert "Traceback" not in out and "KeyError" not in out
    assert not (project / "work/materials.json").exists()


def test_ingest_missing_material_dies(project, monkeypatch, capsys):
    monkeypatch.setattr(media_io, "probe_material", _fail)
    with pytest.raises(SystemExit):
        aicut.cmd_ingest(argparse.Namespace(name="p"))
    assert "原片不存在" in capsys.readouterr().out


def test_ingest_records_probe_result(project, monkeypatch):
    (project.parent / "src.mov").write_bytes(b"x" * 10)
    monkeypatch.setattr(media_io, "probe_material", lambda p, **k: {"duration": 60.0, "streams": []})
    aicut.cmd_ingest(argparse.Namespace(name="p"))
    item = json.loads((project / "work/materials.json").read_text(encoding="utf-8"))["items"][0]
    assert item["duration"] == 60.0 and item["size"] == 10 and item["streams"] == []


# ---------------------------------------------------------------- KI-48 / KI-21：出片
@pytest.mark.parametrize("content", ["{}", '{"shots": {}}', '{"shots": [{"id": "sh01", "in": 5, "out": 1}]}',
                                     "{坏", "[]", '{"shots": [{"id": "../x", "in": 0, "out": 1}]}'])
def test_build_rejects_bad_shots_file(project, monkeypatch, capsys, content):
    (project / "shots.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    assert aicut.run_cli(["build", "p", "--no-draft"]) == 1
    out = _output(capsys)
    assert "分镜表" in out or "shots.json" in out
    assert "Traceback" not in out


def test_build_missing_preset_dies(project, monkeypatch, capsys):
    cfg = schema.load(project / "project.json")
    schema.save(project / "project.json", {**cfg, "preset": "不存在的预设"})
    (project / "shots.json").write_text('{"shots": [{"id": "sh01", "in": 0, "out": 1}]}', encoding="utf-8")
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    assert aicut.run_cli(["build", "p", "--no-draft"]) == 1
    assert "找不到预设 不存在的预设" in _output(capsys)


# ---------------------------------------------------------------- KI-56 / KI-21：损坏文件统一给人话
def test_select_corrupt_overrides_dies_with_message(project, capsys):
    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "segments_scored.json").write_text(json.dumps({"segments": [], "topics": [], "target": 60}),
                                               encoding="utf-8")
    (work / "overrides.json").write_text("{坏", encoding="utf-8")
    assert aicut.run_cli(["select", "p"]) == 1
    out = _output(capsys)
    assert "人工裁决文件损坏" in out and "Traceback" not in out


def test_corrupt_project_json_dies_with_file_name(project, capsys):
    (project / "project.json").write_text("{坏", encoding="utf-8")
    assert aicut.run_cli(["status", "p"]) == 1
    out = _output(capsys)
    assert "project.json" in out and "损坏" in out and "Traceback" not in out


def test_list_skips_corrupt_project(project, tmp_path, capsys):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "project.json").write_text("{坏", encoding="utf-8")
    aicut.cmd_list(argparse.Namespace())
    out = _output(capsys)
    assert "p " in out and "bad" in out and "损坏" in out
