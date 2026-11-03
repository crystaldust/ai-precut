"""画面理解第 5 阶段 · ③ 前端（node vm）：对白句的画面行、画面片段插入列表、筛选、话题分组、当前段、剪辑列表。"""
import pytest

from fe_browse import BROWSE, CLIP, SEGS, in_browse, seg
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")


def vseg(i, start, end, level, label, *, desc="一人扫码", on_screen="", issues=(), must=False):
    return {"id": f"V{i:03d}", "kind": "visual", "start": start, "end": end, "dur": end - start, "level": level,
            "level_reason": "画面片段", "text": "", "topic": "画面片段", "topic_raw": "画面片段", "label": label,
            "visual": {"desc": desc, "text_on_screen": on_screen, "issues": list(issues)},
            "visual_flags": [], "must_keep": must, "unusable": False, "inCut": False, "override": False}


PICTURED = {**seg(1, 0, 6, 3, "讲合同", "甲"), "visual": {"desc": "两人<b>签</b>合同", "issues": ["画面晃动"]}}
V1 = vseg(1, 6, 10, 3, "扫码<i>付款</i>", on_screen="9600", must=True)
DATA = {**BROWSE, "segments": [PICTURED, V1, *SEGS[1:]],
        "clip_list": {**CLIP, "items": [{"id": "V001", "start": 6, "end": 10, "dur": 4, "topic": "画面片段",
                                         "text": "", "kind": "visual", "title": "扫码<i>付款</i>"}, *CLIP["items"]]}}
ROUTES = {"GET /api/browse": DATA}


def test_speech_row_shows_escaped_picture_line_and_issue_chip():
    html = in_browse("return rowHtml(B().segs[0]);", ROUTES)
    assert "画面：两人&lt;b&gt;签&lt;/b&gt;合同" in html and "<b>签" not in html
    assert '<span class="vt">画面晃动</span>' in html


def test_visual_segment_row_shows_title_and_on_screen_text():
    html = in_browse("return rowHtml(B().segs[1]);", ROUTES)
    assert "▣ 扫码&lt;i&gt;付款&lt;/i&gt;" in html and "<i>付款" not in html
    assert "画面上的字：9600" in html and "画面：一人扫码" not in html   # 描述已在标题位置，不重复


def test_row_without_picture_fields_is_unchanged():
    html = in_browse("return rowHtml(B().segs[2]);", ROUTES)
    assert 'class="vis"' not in html


def test_visual_filter_counts_and_lists_only_visual_segments():
    out = in_browse("act('setFilter', {v: 'visual'}); return [ids(), el('#bFilters').innerHTML];", ROUTES)
    assert out[0] == ["V001"] and "画面片段 1" in out[1]


def test_topic_view_puts_visual_group_last():
    out = in_browse("act('setView', {v: 'topic'}); return [B().groups, ids()];", ROUTES)
    assert out[0][-1] == "画面片段" and out[1][-1] == "V001"


def test_current_visual_segment_shows_full_picture_detail():
    html = in_browse("act('jumpSeg', {i: '1'}); return el('#bNow').innerHTML;", ROUTES)
    assert "▣ 扫码&lt;i&gt;付款&lt;/i&gt;" in html
    assert "画面：一人扫码" in html and "画面上的字：9600" in html


def test_clip_panel_names_visual_item_by_title():
    html = in_browse("return el('#bPanel').innerHTML;", ROUTES)
    assert "▣ 扫码&lt;i&gt;付款" in html and "<i>付款" not in html


def test_visual_filter_only_appears_when_there_are_visual_segments():
    assert "画面片段" not in in_browse("return el('#bFilters').innerHTML;")


def test_without_visual_segments_filters_are_exactly_the_original_seven():
    html = in_browse("return el('#bFilters').innerHTML;")
    assert html.count('data-act="setFilter"') == 7


def test_on_screen_text_and_issues_are_escaped_in_row_and_now():
    pic = {**seg(1, 0, 6, 3, "讲合同", "甲"),
           "visual": {"desc": "d", "text_on_screen": "<img src=x>", "issues": ["<script>"]}}
    html = in_browse("act('jumpSeg', {i: '0'}); return [rowHtml(B().segs[0]), el('#bNow').innerHTML];",
                     {"GET /api/browse": {**BROWSE, "segments": [pic, *SEGS[1:]]}})
    for part in html:
        assert "<img" not in part and "<script>" not in part
        assert "&lt;img src=x&gt;" in part and "&lt;script&gt;" in part


def test_visual_filter_falls_back_to_all_when_visual_segments_disappear():
    out = in_browse("""act('setFilter', {v: 'visual'});
      B().segs = B().segs.filter(s => s.kind !== 'visual').map((s, i) => ({...s, _i: i}));
      renderList(); renderFilters(); renderNote();
      return [B().filter, el('#bNote').textContent];""", ROUTES)
    assert out[0] == "all" and "undefined" not in out[1]


def test_visual_group_sorts_last_even_if_a_speech_topic_has_a_later_name():
    data = {**DATA, "segments": [V1, {**seg(9, 20, 26, 3, "其他", "己"), "topic_raw": "其他"}]}
    out = in_browse("act('setView', {v: 'topic'}); return B().groups;", {"GET /api/browse": data})
    assert out == ["其他", "画面片段"]


def test_now_panel_does_not_repeat_description_when_title_is_the_description():
    v = vseg(2, 6, 10, 2, "", desc="走廊")
    html = in_browse("act('jumpSeg', {i: '0'}); return el('#bNow').innerHTML;",
                     {"GET /api/browse": {**BROWSE, "segments": [v, *SEGS[1:]]}})
    assert html.count("走廊") == 1
