"""镜头配对与差异（M14 E8）：改动清单（KI-95）与版本对比（KI-94）共用的纯函数。"""
import copy

from pipeline import shot_diff


def _shot(i, a, b, sub="字幕"):
    return {"id": f"s{i}", "in": a, "out": b, "sub": sub}


BASE = [_shot(1, 0, 10), _shot(2, 20, 30), _shot(3, 40, 50), _shot(4, 60, 70)]


def test_identical_tables_have_no_diff():
    d = shot_diff.diff(BASE, copy.deepcopy(BASE))
    assert d["added"] == d["removed"] == d["sub_changed"] == d["retimed"] == []
    assert d["reordered"] is False
    assert shot_diff.count(d) == 0


def test_sub_change_counts_but_surrounding_whitespace_does_not():
    new = copy.deepcopy(BASE)
    new[1]["sub"] = "  字幕  "
    assert shot_diff.count(shot_diff.diff(BASE, new)) == 0
    new[1]["sub"] = "改过的字幕"
    d = shot_diff.diff(BASE, new)
    assert [(x["before"], x["after"]) for x in d["sub_changed"]] == [("字幕", "改过的字幕")]
    assert shot_diff.count(d) == 1


def test_retime_below_tolerance_ignored_above_counted():
    small = copy.deepcopy(BASE)
    small[0]["in"] = 0.04
    assert shot_diff.diff(BASE, small)["retimed"] == []
    big = copy.deepcopy(BASE)
    big[0]["in"] = 0.2
    assert len(shot_diff.diff(BASE, big)["retimed"]) == 1


def test_same_id_without_time_overlap_is_remove_plus_add():
    new = [_shot(1, 100, 110, "完全不同")] + BASE[1:]  # AI 两次选段都叫 s1 却是别的内容
    d = shot_diff.diff(BASE, new)
    assert len(d["added"]) == 1 and len(d["removed"]) == 1
    assert d["sub_changed"] == [] and d["retimed"] == []


def test_different_id_paired_by_iou_threshold():
    paired = [{**BASE[0], "id": "copy"}] + BASE[1:]  # 同样时间、换了 id → 配上
    assert shot_diff.count(shot_diff.diff(BASE, paired)) == 0
    # 交 4 / 并 16 = 0.25 < 0.5 → 一删一增；交 8 / 并 12 ≈ 0.67 → 配上（改入出点）
    low = [{**BASE[0], "id": "x", "in": 6, "out": 16}] + BASE[1:]
    d = shot_diff.diff(BASE, low)
    assert (len(d["added"]), len(d["removed"])) == (1, 1)
    high = [{**BASE[0], "id": "x", "in": 2, "out": 12}] + BASE[1:]
    d = shot_diff.diff(BASE, high)
    assert (len(d["added"]), len(d["removed"]), len(d["retimed"])) == (0, 0, 1)


def test_swapping_two_shots_is_one_reorder():
    new = [BASE[0], BASE[2], BASE[1], BASE[3]]
    d = shot_diff.diff(BASE, new)
    assert d["reordered"] is True
    assert d["added"] == d["removed"] == d["retimed"] == []
    assert shot_diff.count(d) == 1


def test_pairing_prefers_highest_overlap_not_first_come():
    old = [_shot(1, 0, 10), _shot(2, 8, 18)]
    new = [_shot(9, 8, 18), _shot(8, 0, 10)]
    assert sorted(shot_diff.pair(old, new)) == [(0, 1), (1, 0)]


def test_describe_lists_changes_in_plain_words_and_limits():
    new = copy.deepcopy(BASE)
    new[1]["in"] = 21.0                       # 第 2 镜改入出点
    new[3]["sub"] = "这是一段很长很长很长很长的新字幕文字"  # 第 4 镜改字幕
    del new[2]                                # 删除 00:40 那一镜
    new.append(_shot(7, 100, 110, "新增的这一镜字幕有点长长长长长"))
    d = shot_diff.diff(BASE, new)
    lines, more = shot_diff.describe(d, new)
    assert lines == ["新增第 4 镜「新增的这一镜字幕有点长长」", "删除了 00:40 那一镜",
                     "第 3 镜改了字幕", "第 2 镜改了入出点"]
    assert more == 0
    short, more = shot_diff.describe(d, new, limit=2)
    assert len(short) == 2 and more == shot_diff.count(d) - 2


def test_describe_truncates_sub_to_limit_chars():
    new = [*BASE, _shot(9, 100, 110, "一二三四五六七八九十甲乙丙丁")]
    lines, _ = shot_diff.describe(shot_diff.diff(BASE, new), new)
    assert lines == ["新增第 5 镜「一二三四五六七八九十甲乙」"]


def test_describe_reordered_line():
    new = [BASE[1], BASE[0], BASE[2], BASE[3]]
    lines, _ = shot_diff.describe(shot_diff.diff(BASE, new), new)
    assert lines == ["调整了镜头顺序"]


def test_inputs_not_mutated_and_tolerates_odd_values():
    old, new = copy.deepcopy(BASE), copy.deepcopy(BASE)
    new[0]["in"] = 1                          # int
    del new[1]["sub"]                         # 缺 sub
    snap_old, snap_new = copy.deepcopy(old), copy.deepcopy(new)
    d = shot_diff.diff(old, new)
    assert old == snap_old and new == snap_new
    assert len(d["retimed"]) == 1 and len(d["sub_changed"]) == 1


def test_empty_tables():
    assert shot_diff.count(shot_diff.diff([], [])) == 0
    d = shot_diff.diff([], BASE)
    assert len(d["added"]) == 4 and d["removed"] == []
    assert len(shot_diff.diff(BASE, [])["removed"]) == 4
