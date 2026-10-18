from pipeline import style


def test_empty_calibration_has_no_directive():
    assert style.directive({}) == ""
    assert style.is_empty({}) is True


def test_directive_includes_audience_tone_and_lines():
    d = style.directive({"tone": "emotion", "audience": "准备报名的家长",
                         "must_lines": "不白学吗"})
    assert "准备报名的家长" in d
    assert "情绪" in d
    assert "不白学吗" in d


def test_invalid_tone_falls_back_to_balanced():
    assert style.normalize({"tone": "乱写"})["tone"] == "balanced"


def test_weights_shift_with_tone():
    assert style.weights({"tone": "info"})["info"] > style.weights({})["info"]
    assert style.weights({"tone": "emotion"})["emotion"] > style.weights({})["emotion"]


def test_apply_to_prompt_appends_only_when_present():
    base = "原始提示词"
    assert style.apply_to_prompt(base, {}) == base
    out = style.apply_to_prompt(base, {"audience": "家长"})
    assert out.startswith(base) and "家长" in out


def test_normalize_truncates_long_fields():
    c = style.normalize({"audience": "x" * 200, "must_lines": "y" * 500})
    assert len(c["audience"]) <= 60 and len(c["must_lines"]) <= 200
