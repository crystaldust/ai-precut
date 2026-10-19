"""M6：答案 → 选段规则、结尾归一、必留原话解析与命中、focus / pacing（KI-02/03/04）。"""
from pipeline import select_rules as sr


def _q(qid, *options, type_="single"):
    return {"id": qid, "type": type_,
            "options": [{"label": label, "rule": rule} for label, rule in options]}


# ---------------------------------------------------------------- KI-04：按题 id 查规则
def test_same_label_in_two_questions_uses_own_rule():
    qs = {"questions": [_q("q1", ("全部", {"kind": "must_topics", "value": ["讲合同"]})),
                        _q("q2", ("全部", {"kind": "exclude", "value": ["聊吃饭"]}))]}
    rules = sr.rules_from_answers({"q1": "全部"}, qs)
    assert rules["must_topics"] == ["讲合同"]
    assert rules["exclude_topics"] == []


def test_pacing_uses_rule_value_not_label():
    qs = {"questions": [_q("q1", ("慢慢来", {"kind": "pacing", "value": "tight"}),
                           ("紧凑", {"kind": "pacing", "value": "normal"}))]}
    assert sr.rules_from_answers({"q1": "慢慢来"}, qs)["pacing"] == "tight"
    assert sr.rules_from_answers({"q1": "紧凑"}, qs)["pacing"] == "normal"


def test_pacing_free_text_value_normalized():
    assert sr.norm_pacing("紧凑一点") == "tight"
    assert sr.norm_pacing("快节奏") == "tight"
    assert sr.norm_pacing("舒缓") == "normal"
    assert sr.norm_pacing(None) == "normal"


def test_focus_value_kept():
    qs = {"questions": [_q("q1", ("出镜最多的人", {"kind": "focus", "value": "main"}))]}
    assert sr.rules_from_answers({"q1": "出镜最多的人"}, qs)["focus"] == "main"


def test_must_lines_kind_collected():
    qs = {"questions": [_q("q2", ("九千八", {"kind": "must_lines", "value": ["九千八包含所有耗材"]}),
                           ("别的", {"kind": "must_lines", "value": ["", 3]}), type_="multi")]}
    rules = sr.rules_from_answers({"q2": ["九千八", "别的"]}, qs)
    assert rules["must_lines"] == ["九千八包含所有耗材"]


def test_norm_ending_info():
    assert sr.norm_ending("info") == "info"
    assert sr.norm_ending("最后一个关键信息") == "info"
    assert sr.norm_ending("情绪收尾") == "emotion"
    assert sr.norm_ending("微信缴费完成") == "sign"
    assert sr.norm_ending("随便看看") is None


def test_answers_for_unknown_question_not_applied():
    qs = {"questions": [_q("q1", ("合同全额", {"kind": "must_topics", "value": ["讲合同"]}))]}
    rules = sr.rules_from_answers({"q9": "合同全额"}, qs)
    assert rules["must_topics"] == []
    assert rules["ignored_answers"] == ["合同全额"]


def test_non_list_multi_answer_tolerated():
    qs = {"questions": [_q("q1", ("合同全额", {"kind": "must_topics", "value": ["讲合同"]}))]}
    rules = sr.rules_from_answers({"q1": 3, "q2": None}, qs)
    assert rules["must_topics"] == [] and rules["ignored_answers"] == []


def test_rules_from_answers_does_not_mutate_questions():
    opt_rule = {"kind": "must_topics", "value": ["讲合同"]}
    qs = {"questions": [_q("q1", ("A", opt_rule)), _q("q2", ("B", opt_rule))]}
    sr.rules_from_answers({"q1": "A", "q2": "B"}, qs)
    assert opt_rule == {"kind": "must_topics", "value": ["讲合同"]}


# ---------------------------------------------------------------- KI-03：必留原话
def _s(i, text, start=None):
    start = i * 10.0 if start is None else start
    return {"id": f"S{i:03d}", "start": start, "end": start + 6, "text": text}


def _rid(quotes, segs):
    hits, notes = sr.resolve_must_lines(quotes, segs)
    return [h["id"] for h in hits], notes


def test_parse_splits_on_newline_and_semicolon_keeps_commas():
    raw = "嗯，对，就九千八\n找不到工作不白学吗；包吃住"
    assert sr.parse_must_lines(raw) == ["嗯，对，就九千八", "找不到工作不白学吗", "包吃住"]


def test_parse_handles_empty_and_non_string():
    assert sr.parse_must_lines(None) == []
    assert sr.parse_must_lines("") == []
    assert sr.parse_must_lines(["甲乙丙丁", " ", 5]) == ["甲乙丙丁"]


def test_resolve_whole_quote_ignoring_punctuation():
    segs = [_s(i, f"嗯对第{i}句") for i in range(1, 11)] + [_s(20, "嗯对就九千八包含耗材")]
    ids, notes = _rid(["嗯，对，就九千八"], segs)
    assert ids == ["S020"] and notes == []


def test_resolve_falls_back_to_comma_fragments():
    segs = [_s(1, "那找不到工作不白学吗"), _s(2, "九千八包含所有耗材的"), _s(3, "别的")]
    ids, notes = _rid(["找不到工作不白学吗，九千八包含所有耗材"], segs)
    assert ids == ["S001", "S002"] and notes == []


def test_short_fragments_ignored_with_warning():
    segs = [_s(1, "嗯好的"), _s(2, "九千八包含所有耗材")]
    ids, notes = _rid(["嗯，九千八包含所有耗材"], segs)
    assert ids == ["S002"]
    assert any("嗯" in n and str(sr.MUST_LINE_MIN_CHARS) in n for n in notes)


def test_quote_hits_only_first_segment_in_time():
    segs = [_s(2, "包含所有耗材", start=30), _s(1, "包含所有耗材", start=5)]
    ids, _ = _rid(["包含所有耗材"], segs)
    assert ids == ["S001"]


def test_unmatched_quote_warns():
    ids, notes = _rid(["这句话在文稿里根本不存在呢"], [_s(1, "别的")])
    assert ids == []
    assert any("这句话在文稿里根本不存" in n and "找不到" in n for n in notes)


def test_short_whole_quote_still_matches():
    """整句匹配不受最少字数限制（「退费」这样的短原话照样能找）。"""
    ids, notes = _rid(["退费"], [_s(1, "退费")])
    assert ids == ["S001"] and notes == []


# ---------------------------------------------------------------- KI-04：pacing / focus
def test_max_shot_for_pacing():
    assert sr.max_shot_for({"pacing": "tight"}) == sr.PACING_MAX_SHOT["tight"]
    assert sr.max_shot_for({"pacing": "normal"}) == sr.PACING_MAX_SHOT["normal"]
    assert sr.max_shot_for({}) == sr.PACING_MAX_SHOT["normal"]
    assert sr.max_shot_for({"pacing": "奇怪"}) == sr.PACING_MAX_SHOT["normal"]


def _sp(i, start, dur, speaker):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur, "speaker": speaker}


def test_focus_main_maps_to_most_speaking():
    segs = [_sp(1, 0, 10, "1"), _sp(2, 10, 3, "2"), _sp(3, 20, 3, "2")]
    assert sr.focus_speakers(segs, "main") == ({"1"}, [])
    assert sr.focus_speakers(segs, "narrator") == ({"1"}, [])


def test_focus_ensemble_or_none_no_bonus():
    segs = [_sp(1, 0, 10, "1")]
    assert sr.focus_speakers(segs, "ensemble") == (set(), [])
    assert sr.focus_speakers(segs, None) == (set(), [])


def test_focus_unmappable_warns():
    speakers, notes = sr.focus_speakers([_sp(1, 0, 10, "1")], "老师")
    assert speakers == set()
    assert any("老师" in n for n in notes)


def test_focus_main_without_speakers_warns():
    speakers, notes = sr.focus_speakers([{"id": "S001", "start": 0, "end": 5}], "main")
    assert speakers == set() and notes


# ================================================================ M6 审查修复
def test_hit_span_from_lines():
    seg = {"id": "S001", "start": 0, "end": 30, "text": "前面很多铺垫的话。九千八包含所有耗材",
           "lines": [{"start": 0, "end": 20, "text": "前面很多铺垫的话。"},
                     {"start": 20, "end": 30, "text": "九千八包含所有耗材"}]}
    hits, _ = sr.resolve_must_lines(["九千八包含所有耗材"], [seg])
    assert hits == [{"id": "S001", "line": "九千八包含所有耗材", "start": 20.0, "end": 30.0}]


def test_hit_span_proportional_without_lines():
    seg = {"id": "S001", "start": 0, "end": 10, "text": "甲乙丙丁戊己庚辛壬癸"}
    hits, _ = sr.resolve_must_lines(["庚辛壬癸"], [seg])
    assert (hits[0]["start"], hits[0]["end"]) == (6.0, 10.0)


def test_single_char_quote_warns():
    ids, notes = _rid(["对"], [_s(1, "对对对")])
    assert ids == [] and any("对" in n and "太短" in n for n in notes)


def test_partial_fragment_match_warns_unmatched_part():
    ids, notes = _rid(["找不到工作不白学吗，这句根本不存在呢"], [_s(1, "那找不到工作不白学吗")])
    assert ids == ["S001"]
    assert any("这句根本不存在呢" in n and "找不到" in n for n in notes)


def test_pacing_negation_not_tight():
    assert sr.norm_pacing("不要太紧") == "normal"
    assert sr.norm_pacing("别太快") == "normal"
    assert sr.norm_pacing("不紧凑") == "normal"
    assert sr.norm_pacing("快而不乱") == "tight"
