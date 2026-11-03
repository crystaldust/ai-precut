"""KI-01：成片字幕按镜头区间生成（整句；截短只留镜头内的分句）。"""
from pipeline import shot_sub


def _seg(start, end, text, lines=None):
    s = {"id": "S001", "start": start, "end": end, "text": text}
    return {**s, "lines": lines} if lines is not None else s


LINES = [{"start": 0, "end": 3, "text": "第一句"}, {"start": 3, "end": 6, "text": "第二句"},
         {"start": 6, "end": 9, "text": "第三句"}]


def test_full_text_when_shot_covers_segment():
    text = "这是一句超过二十八个字的完整句子" * 3
    assert shot_sub.sub_for(_seg(0, 10, text), 0, 10) == text


def test_lines_inside_shot_only():
    assert shot_sub.sub_for(_seg(0, 9, "第一句第二句第三句", LINES), 0, 6) == "第一句第二句"


def test_line_counted_when_mostly_inside():
    assert shot_sub.sub_for(_seg(0, 9, "x", LINES), 0, 4.4) == "第一句"
    lines = [LINES[0], {"start": 3, "end": 4.8, "text": "第二句"}, LINES[2]]
    assert shot_sub.sub_for(_seg(0, 9, "x", lines), 0, 4.4) == "第一句第二句"


def test_proportional_cut_without_lines():
    text = "一二三四五六七八九十" * 2
    assert shot_sub.sub_for(_seg(0, 10, text), 0, 5) == text[:10]
    assert shot_sub.sub_for(_seg(0, 10, text), 5, 10) == text[10:]


def test_empty_or_zero_length_segment():
    assert shot_sub.sub_for(_seg(0, 10, ""), 0, 5) == ""
    assert shot_sub.sub_for(_seg(5, 5, "原文"), 5, 5) == "原文"


def test_no_line_inside_falls_back_to_proportional():
    """分句全都大半落在镜头外时，不能给空字幕：按时长比例截。"""
    lines = [{"start": 0, "end": 10, "text": "很长的一句话"}]
    assert shot_sub.sub_for(_seg(0, 10, "很长的一句话", lines), 0, 4) == "很长"


def test_bad_line_items_ignored():
    lines = ["坏", {"start": "x", "end": 3, "text": "坏"}, {"start": 0, "end": 3, "text": "好"}]
    assert shot_sub.sub_for(_seg(0, 9, "好别的", lines), 0, 3) == "好"


# ================================================================ M6 审查修复
def test_whole_sentence_tolerates_two_decimal_rounding():
    lines = [{"start": 1.004, "end": 3, "text": "你好。"}, {"start": 3, "end": 5.99, "text": "再见。"},
             {"start": 5.99, "end": 5.996, "text": "哦"}]
    seg = _seg(1.004, 5.996, "你好。再见。哦", lines)
    assert shot_sub.sub_for(seg, 1.0, 6.0) == "你好。再见。哦"
    assert shot_sub.sub_for(seg, 1.0, 5.99) == "你好。再见。哦"


def test_proportional_takes_middle_for_mid_sentence_window():
    text = "一二三四五六七八九十" * 3
    assert shot_sub.sub_for(_seg(0, 30, text), 10, 14) == text[10:14]
    assert shot_sub.sub_for(_seg(0, 30, text), 0, 1.5) == text[:2]


def test_truncated_english_lines_keep_spaces():  # KI-87：截短镜头的分句拼接同样补空格
    from pipeline import shot_sub
    seg = {"text": "One two. Three four. Five", "start": 0.0, "end": 3.0,
           "lines": [{"start": 0.0, "end": 1.0, "text": "One two."},
                     {"start": 1.0, "end": 2.0, "text": "Three four."},
                     {"start": 2.0, "end": 3.0, "text": "Five"}]}
    assert shot_sub.sub_for(seg, 0.0, 2.0) == "One two. Three four."


# ---------------------------------------------------------------- 手改起止：字幕按整份转写的分句重取
ALL = [{"start": 0, "end": 3, "text": "上一句。"}, {"start": 3, "end": 6, "text": "第一句。"},
       {"start": 6, "end": 9, "text": "第二句。"}, {"start": 9, "end": 12, "text": "下一句。"}]


def _edited(start, end, base=(3, 9), text="第一句。第二句。"):
    return {**_seg(start, end, text), "base_start": base[0], "base_end": base[1], "bounds_edited": True}


def test_edited_trim_drops_words():
    assert shot_sub.sub_for(_edited(3, 6), 3, 6, ALL) == "第一句。"


def test_edited_extend_into_neighbour_picks_up_its_words():
    assert shot_sub.sub_for(_edited(0, 12), 0, 12, ALL) == "上一句。第一句。第二句。下一句。"
    assert shot_sub.sub_for(_edited(3, 12), 3, 12, ALL) == "第一句。第二句。下一句。"


def test_edited_lines_unordered_and_duplicated_are_sorted_and_deduped():
    shuffled = [ALL[2], ALL[1], ALL[1], ALL[0]]
    assert shot_sub.sub_for(_edited(0, 9), 0, 9, shuffled) == "上一句。第一句。第二句。"


def test_edited_shot_on_base_bounds_returns_whole_text():
    assert shot_sub.sub_for(_edited(2, 10), 3, 9, ALL) == "第一句。第二句。"


def test_whole_shortcut_ignores_edited_bounds():
    seg = _edited(3, 6)   # 编辑后范围是 3~6；镜头 3~6 覆盖编辑范围但没盖住原句 3~9
    assert shot_sub.sub_for(seg, 3, 6, ALL) != seg["text"]


def test_edited_without_any_lines_falls_back_to_base_behaviour():
    seg = _edited(3, 6)
    assert shot_sub.sub_for(seg, 3, 6) == "第一句。"   # 按原句 3~9 比例截（8 字取前 4）
    assert shot_sub.sub_for(seg, 3, 6, []) == "第一句。"


def test_edited_visual_has_no_subtitle():
    seg = {"id": "V001", "kind": "visual", "start": 1, "end": 9, "text": "", "base_start": 2, "base_end": 8,
           "bounds_edited": True}
    assert shot_sub.sub_for(seg, 1, 9, ALL) == ""


def test_unedited_segment_ignores_all_lines_argument():
    assert shot_sub.sub_for(_seg(0, 9, "x", LINES), 0, 4.4, ALL) == "第一句"


def test_flatten_lines_reads_every_sentence_and_skips_junk():
    raw = [{"id": "S1", "lines": [ALL[0], "bad", {"start": "x"}]}, {"id": "S2", "lines": None}, "x",
           {"id": "S3", "lines": [ALL[1]]}]
    assert shot_sub.flatten_lines(raw) == [ALL[0], ALL[1]]
    assert shot_sub.flatten_lines(None) == []
