# -*- coding: utf-8 -*-
"""输入指纹（M13 T4）：只看会改变结果的内容，忽略 at / anchor 等易变字段。"""
import json

from pipeline import fingerprints, style


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_file_digest_missing_is_empty_and_tracks_content(tmp_path):
    f = tmp_path / "a.json"
    assert fingerprints.file_digest(f) == ""
    f.write_bytes(b"abc")
    first = fingerprints.file_digest(f)
    assert len(first) == fingerprints.DIGEST_LEN
    f.write_bytes(b"abc")
    assert fingerprints.file_digest(f) == first
    f.write_bytes(b"abd")
    assert fingerprints.file_digest(f) != first


def test_file_digest_unreadable_is_corrupt(tmp_path):
    assert fingerprints.file_digest(tmp_path) == fingerprints.CORRUPT  # 目录读不了


def test_overrides_digest_ignores_bookkeeping_fields(tmp_path):
    _write(tmp_path / "overrides.json", {"S1": {"level": 3, "at": "t1", "anchor": {"text": "a"}}})
    base = fingerprints.overrides_digest(tmp_path)
    _write(tmp_path / "overrides.json", {"S1": {"level": 3, "at": "t2", "anchor": {"text": "b"}}})
    assert fingerprints.overrides_digest(tmp_path) == base


def test_overrides_digest_false_flags_equal_never_marked(tmp_path):
    _write(tmp_path / "overrides.json", {"S1": {"must_keep": True, "at": "t"}})
    marked = fingerprints.overrides_digest(tmp_path)
    _write(tmp_path / "overrides.json", {"S1": {"must_keep": False, "unusable": False, "at": "t"}})
    assert fingerprints.overrides_digest(tmp_path) != marked
    assert fingerprints.overrides_digest(tmp_path) == fingerprints.overrides_digest(tmp_path / "none")
    _write(tmp_path / "overrides.json", {})
    assert fingerprints.overrides_digest(tmp_path) == fingerprints.overrides_digest(tmp_path / "none")


def test_overrides_digest_level_and_unusable_matter_and_order_does_not(tmp_path):
    _write(tmp_path / "overrides.json", {"S1": {"level": 3}, "S2": {"unusable": True}})
    a = fingerprints.overrides_digest(tmp_path)
    _write(tmp_path / "overrides.json", {"S2": {"unusable": True}, "S1": {"level": 3}})
    assert fingerprints.overrides_digest(tmp_path) == a
    _write(tmp_path / "overrides.json", {"S1": {"level": 1}, "S2": {"unusable": True}})
    assert fingerprints.overrides_digest(tmp_path) != a
    _write(tmp_path / "overrides.json", {"S1": {"level": 3}, "S2": {"unusable": False}})
    assert fingerprints.overrides_digest(tmp_path) != a


def test_overrides_digest_corrupt_does_not_raise(tmp_path):
    (tmp_path / "overrides.json").write_text("{坏", encoding="utf-8")
    assert fingerprints.overrides_digest(tmp_path) == fingerprints.CORRUPT
    _write(tmp_path / "overrides.json", [1, 2])
    assert fingerprints.overrides_digest(tmp_path) == fingerprints.CORRUPT


def test_answers_digest_is_key_order_independent_and_ignores_other_fields(tmp_path):
    assert fingerprints.answers_digest(tmp_path) == ""
    _write(tmp_path / "brief_answers.json", {"answers": {"q1": "a", "q2": "b"}, "at": "1"})
    a = fingerprints.answers_digest(tmp_path)
    _write(tmp_path / "brief_answers.json", {"at": "2", "confirmed": True, "answers": {"q2": "b", "q1": "a"}})
    assert fingerprints.answers_digest(tmp_path) == a
    _write(tmp_path / "brief_answers.json", {"answers": {"q1": "x", "q2": "b"}})
    assert fingerprints.answers_digest(tmp_path) != a
    (tmp_path / "brief_answers.json").write_text("not json", encoding="utf-8")
    assert fingerprints.answers_digest(tmp_path) == fingerprints.CORRUPT


def test_selection_inputs_has_fixed_keys_and_tracks_each_part(tmp_path):
    cfg = {"target_duration": 120, "calibration": {"tone": "info", "must_lines": "第一句"}}
    now = fingerprints.selection_inputs(tmp_path, cfg)
    assert set(now) == {"scored", "overrides", "answers", "target", "lines"}
    assert now["target"] == "120"
    assert fingerprints.selection_inputs(tmp_path, {**cfg, "target_duration": None})["target"] == "175"
    (tmp_path / "segments_scored.json").write_text("{}", encoding="utf-8")
    after = fingerprints.selection_inputs(tmp_path, cfg)
    assert fingerprints.changed(now, after) == ["scored"]
    now = after
    cfg2 = {**cfg, "calibration": {"tone": "emotion", "must_lines": "第一句"}}
    assert fingerprints.changed(now, fingerprints.selection_inputs(tmp_path, cfg2)) == ["lines"]
    cfg3 = {**cfg, "calibration": {"tone": "info", "audience": "家长", "must_lines": "第一句"}}
    assert fingerprints.selection_inputs(tmp_path, cfg3) == now  # audience 不影响选段输入


def test_selection_inputs_target_is_rounded_to_int(tmp_path):
    assert fingerprints.selection_inputs(tmp_path, {"target_duration": 90.7})["target"] == "90"


def test_analysis_inputs_uses_directive_and_preset():
    cal = {"tone": "info", "audience": "家长"}
    assert fingerprints.analysis_inputs({"calibration": cal, "preset": "纪实3min"}) == {
        "directive": style.directive(cal), "preset": "纪实3min"}
    assert fingerprints.analysis_inputs({}) == {"directive": "", "preset": ""}


def test_changed_lists_differing_parts_in_order_and_tolerates_bad_saved():
    now = {"scored": "a", "overrides": "b", "answers": "c", "target": "1", "lines": "d"}
    assert fingerprints.changed(None, now) == []
    assert fingerprints.changed("x", now) == []
    assert fingerprints.changed({}, now) == []
    assert fingerprints.changed(now, now) == []
    assert fingerprints.changed({**now, "answers": "z", "overrides": "y"}, now) == ["overrides", "answers"]
    assert fingerprints.changed({"scored": "a"}, now) == []  # 缺项当作没有可比较的戳


def test_target_of_tolerates_infinity_and_junk():
    assert fingerprints.target_of({"target_duration": float("inf")}) == 175
    assert fingerprints.target_of({"target_duration": "abc"}) == 175
    assert fingerprints.target_of({"target_duration": float("nan")}) == 175
