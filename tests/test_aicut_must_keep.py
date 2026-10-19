"""M2（GL-08 / GL-09 / GL-25）：CLI 的目标时长、必留超时长提示、标注失败、出片前必留校验。"""
import json
from argparse import Namespace

import pytest

import aicut
from pipeline import select, understand_text


def _fail(*_a, **_k):
    raise AssertionError("不应该被调用")


class Reached(Exception):
    """走到了切片这一步：说明出片前的校验放行了。"""


def _stop(*_a, **_k):
    raise Reached


def _project(root, name="p", target=175, **work):
    pdir = root / name
    (pdir / "work").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "material": "/tmp/a.mp4", "schema_version": 2,
         "target_duration": target}), encoding="utf-8")
    for rel, obj in work.items():
        content = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
        (pdir / "work" / rel).write_text(content, encoding="utf-8")
    return pdir


def _new_args(tmp_path, **kw):
    mat = tmp_path / "a.mp4"
    mat.write_bytes(b"x")
    base = dict(name="n1", material=str(mat), preset="纪实3min", title=None,
                tone="balanced", audience=None, must_lines=None, target=None)
    return Namespace(**{**base, **kw})


def _cfg(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- new --target
def test_new_stores_given_target(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr("builtins.input", _fail)
    aicut.cmd_new(_new_args(tmp_path, target="240"))
    assert _cfg(tmp_path / "projects/n1/project.json")["target_duration"] == 240


def test_new_without_target_noninteractive_uses_preset(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", _fail)
    aicut.cmd_new(_new_args(tmp_path))
    assert _cfg(tmp_path / "projects/n1/project.json")["target_duration"] == 175  # 纪实3min


def test_new_asks_target_in_terminal(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["abc", "300"])  # 先输错，再输对
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    aicut.cmd_new(_new_args(tmp_path))
    assert _cfg(tmp_path / "projects/n1/project.json")["target_duration"] == 300


def test_new_terminal_enter_uses_preset(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    aicut.cmd_new(_new_args(tmp_path))
    assert _cfg(tmp_path / "projects/n1/project.json")["target_duration"] == 175


def test_new_rejects_bad_target(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    with pytest.raises(SystemExit):
        aicut.cmd_new(_new_args(tmp_path, target="-5"))
    assert not (tmp_path / "projects/n1").exists()  # 校验失败不留空目录


def test_new_parser_accepts_target(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(aicut, "cmd_new", lambda a: seen.update(target=a.target))
    aicut.main(["new", "n1", "--material=/tmp/a.mp4", "--target=240"])
    assert seen["target"] == "240"


# ---------------------------------------------------------------- select --target
def _sel_result(**kw):
    base = {"stats": {"shots": 3, "must_keep": 2}, "total": 300, "target": 300,
            "missing_must_topics": [], "warnings": [], "over_target": False,
            "over_target_warning": None, "must_keep_total": 40, "suggested_target": None}
    return {**base, **kw}


def test_select_target_saves_and_only_reselects(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})
    for name in ("cmd_transcribe", "cmd_text", "cmd_score", "cmd_analyze"):
        monkeypatch.setattr(aicut, name, _fail)
    monkeypatch.setattr(aicut.understand_text, "run", _fail)
    monkeypatch.setattr(aicut.classify, "run", _fail)
    seen = {}

    def fake_run(*a, target=None, **kw):
        seen["target"] = target
        return _sel_result(target=target)

    monkeypatch.setattr(aicut.select, "run", fake_run)
    aicut.cmd_select(Namespace(name="p", target="300"))
    assert seen["target"] == 300
    assert _cfg(pdir / "project.json")["target_duration"] == 300
    out = capsys.readouterr().out
    assert "必留 2 段" in out


def test_select_failure_does_not_persist_target(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})

    def boom(*a, **k):
        raise select.SelectionError("必留段未进片：S001")

    monkeypatch.setattr(aicut.select, "run", boom)
    with pytest.raises(SystemExit):
        aicut.cmd_select(Namespace(name="p", target="300"))
    assert _cfg(pdir / "project.json")["target_duration"] == 175  # 失败不改目标


def test_select_rejects_bad_target(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})
    monkeypatch.setattr(aicut.select, "run", _fail)
    with pytest.raises(SystemExit):
        aicut.cmd_select(Namespace(name="p", target="0"))
    assert _cfg(pdir / "project.json")["target_duration"] == 175


def test_select_over_target_prints_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, target=60, **{"segments_scored.json": {"segments": [], "topics": []}})
    monkeypatch.setattr(aicut.select, "run", lambda *a, **k: _sel_result(
        stats={"shots": 5, "must_keep": 5}, total=214, target=60,
        warnings=["其它警告"], over_target_warning="必留内容共 3 分 34 秒，超过目标 1 分 0 秒：…",
        over_target=True, must_keep_total=214, suggested_target=215))
    aicut.cmd_select(Namespace(name="p", target=None))
    out = capsys.readouterr().out
    assert "[!]" in out and "--target 215" in out and "3 分 34 秒" in out
    assert "[!] 其它警告" in out
    assert out.count("必留内容共") == 1  # 超目标只提示一次（带改时长命令的那条）


def test_select_guard_failure_dies(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})

    def boom(*a, **k):
        raise select.SelectionError("必留段未进片：S001")

    monkeypatch.setattr(aicut.select, "run", boom)
    with pytest.raises(SystemExit):
        aicut.cmd_select(Namespace(name="p", target=None))
    assert "[x] 必留段未进片" in capsys.readouterr().out


def test_select_parser_accepts_target(monkeypatch):
    seen = {}
    monkeypatch.setattr(aicut, "cmd_select", lambda a: seen.update(target=a.target))
    aicut.main(["select", "p", "--target", "300"])
    assert seen["target"] == "300"


# ---------------------------------------------------------------- text 失败
def test_text_incomplete_dies(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments.json": {"segments": []}})
    monkeypatch.setattr(aicut.secrets, "get", lambda *_: "k")

    def boom(*a, **k):
        raise understand_text.AnnotationIncomplete(["S001", "S002"])

    monkeypatch.setattr(aicut.understand_text, "run", boom)
    with pytest.raises(SystemExit) as exc:
        aicut.cmd_text(Namespace(name="p", batch=40, model="m"))
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "[x] 2 句逐句标注失败" in out and "只会重跑这 2 句" in out


def test_text_resumed_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments.json": {"segments": []}})
    monkeypatch.setattr(aicut.secrets, "get", lambda *_: "k")
    monkeypatch.setattr(aicut.understand_text, "run", lambda *a, **k: {
        "topics": [], "segments": [], "failures": [], "resumed": True})
    aicut.cmd_text(Namespace(name="p", batch=40, model="m"))
    assert "已补齐上次失败的句子" in capsys.readouterr().out


# ---------------------------------------------------------------- score 报告
def test_score_reports_demoted_and_warnings(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments_text.json": {"segments": []}})
    monkeypatch.setattr(aicut.classify, "run", lambda *a, **k: {
        "summary": {"waste": 1, "pending": 50, "usable": 3}, "segments": [],
        "pending": {"limit": 40, "demoted": 7}, "warnings": ["待定 50 段超过上限 40 段"]})
    aicut.cmd_score(Namespace(name="p"))
    out = capsys.readouterr().out
    assert "自动降级 7" in out and "[!] 待定 50 段超过上限 40 段" in out


# ---------------------------------------------------------------- GL-25 build
def _scored(*segs):
    return {"segments": [{"id": i, "start": s, "end": e, "level": 3, "text": t}
                         for i, s, e, t in segs], "topics": []}


def _shots(pdir, *spans):
    shots = [{"id": f"sh{i:02d}", "in": a, "out": b} for i, (a, b) in enumerate(spans, 1)]
    (pdir / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")


def test_build_blocks_when_storyboard_misses_must_keep(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S001", 0, 6, "开场"),
                                                                 ("S002", 70, 76, "九千八包含耗材")),
                                 "overrides.json": {"S002": {"must_keep": True}}})
    _shots(pdir, (0, 6))
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    out = capsys.readouterr().out
    assert "[x] 分镜表缺少 1 段必留内容" in out
    assert "九千八包含耗材" in out and "01:10" in out
    assert not (pdir / "output").exists()


def test_build_proceeds_when_must_keep_covered(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _stop)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S002", 10, 16, "九千八")),
                                 "overrides.json": {"S002": {"must_keep": True}}})
    _shots(pdir, (10, 16))
    with pytest.raises(Reached):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))


def test_build_without_analysis_skips_must_check(monkeypatch, tmp_path):
    """纯手工流程（没有 segments_scored.json）不应被拦。"""
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _stop)
    pdir = _project(tmp_path)
    _shots(pdir, (0, 6))
    with pytest.raises(Reached):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))


def test_build_checks_selected_storyboard_too(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    _project(tmp_path, **{"segments_scored.json": _scored(("S002", 10, 16, "九千八")),
                          "overrides.json": {"S002": {"must_keep": True}},
                          "shots-selected.json": {"shots": [{"id": "sel01", "in": 0, "out": 6}]}})
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    out = capsys.readouterr().out
    assert "分镜表缺少" in out and "重新选段" in out and "在分镜表里加回" not in out


def test_build_dies_on_corrupt_overrides(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S002", 10, 16, "九千八")),
                                 "overrides.json": "{坏"})
    _shots(pdir, (10, 16))
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    assert "人工裁决文件损坏" in capsys.readouterr().out


# ---------------------------------------------------------------- M2 审查
def test_text_llm_error_in_topic_stage_dies(monkeypatch, tmp_path, capsys):
    from pipeline.llm import LLMError
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments.json": {"segments": []}})
    monkeypatch.setattr(aicut.secrets, "get", lambda *_: "k")

    def boom(*a, **k):
        raise LLMError("HTTP 401: unauthorized", status=401)

    monkeypatch.setattr(aicut.understand_text, "run", boom)
    with pytest.raises(SystemExit):
        aicut.cmd_text(Namespace(name="p", batch=40, model="m"))
    assert "[x]" in capsys.readouterr().out


def test_score_refuses_incomplete_text(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_text.json": {"segments": [], "complete": False}})
    with pytest.raises(SystemExit):
        aicut.cmd_score(Namespace(name="p"))
    assert "标注未完成" in capsys.readouterr().out
    assert not (pdir / "work/segments_scored.json").exists()


def test_score_warns_when_partial_pending(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments_text.json": {"segments": [], "complete": True},
                          "segments_text.partial.json": {"segments": [], "complete": False}})
    aicut.cmd_score(Namespace(name="p"))
    assert "[!] 上次逐句标注没有完成" in capsys.readouterr().out


def test_status_shows_text_incomplete(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments_text.json": {"segments": [], "failures": [{"ids": ["S1"]}]}})
    aicut.cmd_status(Namespace(name="p"))
    out = capsys.readouterr().out
    assert "[!] 文本标注 (b)：未完成" in out
