"""剪辑列表提示：只提示，不改变入选镜头。"""
from pipeline import select
from test_select import TOPICS, seg

PREFIX = "剪辑列表里有"


def run(segs, exclude, **kw):
    return select.select(segs, TOPICS, {"exclude_topics": exclude}, 60, **kw)


def notices(res):
    return [w for w in res["warnings"] if w.startswith(PREFIX)]


def test_one_excluded_topic_hit_is_named():
    res = run([seg(1, 0, 5, "讲合同", must=True), seg(2, 10, 5, "聊吃饭", must=True)], ["聊吃饭"])
    assert notices(res) == ["剪辑列表里有 1 段属于已排除的话题「聊吃饭」：照样进片"]


def test_two_topics_hit_listed_in_time_order():
    segs = [seg(1, 30, 5, "讲合同", must=True), seg(2, 10, 5, "聊吃饭", must=True),
            seg(3, 50, 5, "聊吃饭", must=True)]
    res = run(segs, ["讲合同", "聊吃饭"])
    assert notices(res) == ["剪辑列表里有 3 段属于已排除的话题「聊吃饭、讲合同」：照样进片"]


def test_no_hit_no_warning():
    res = run([seg(1, 0, 5, "讲合同", must=True), seg(2, 10, 5, "聊吃饭")], ["聊吃饭"])
    assert notices(res) == []


def test_visual_clip_and_zero_length_not_counted():
    visual = {**seg(1, 0, 5, "聊吃饭", must=True), "kind": "visual"}
    zero = seg(2, 9, 0, "聊吃饭", must=True)
    assert notices(run([visual, zero, seg(3, 20, 5, "讲合同", must=True)], ["聊吃饭"])) == []


def test_simple_mode_has_no_notice():
    res = run([seg(1, 0, 5, "聊吃饭", must=True)], ["聊吃饭"], mode="simple")
    assert notices(res) == []


def test_notice_does_not_change_selected_shots():
    segs = [seg(1, 0, 5, "讲合同", must=True), seg(2, 10, 5, "聊吃饭", must=True)]
    with_ex, without = run(segs, ["聊吃饭"]), run(segs, [])
    assert notices(with_ex) and not notices(without)
    assert with_ex["shots"] == without["shots"]


def test_untitled_topic_counts_as_uncategorized():
    topics = [*TOPICS, {"name": "未归类", "budget": 5, "must": False, "duration": 10, "usable_dur": 5}]
    res = select.select([seg(1, 0, 5, None, must=True)], topics, {"exclude_topics": ["未归类"]}, 60)
    assert notices(res) == ["剪辑列表里有 1 段属于已排除的话题「未归类」：照样进片"]


def test_not_in_clip_list_not_counted():
    assert notices(run([seg(1, 0, 5, "聊吃饭")], ["聊吃饭"])) == []


def test_over_target_warning_says_ai_adds_no_shots():
    res = select.select([seg(1, 0, 50, "讲合同", must=True)], TOPICS, {}, 10)
    assert "AI 不再补镜头，成片会比目标长；请重新设定成片时长" in res["over_target_warning"]
