"""③ 看素材：当前段 / 编辑起止弹窗显示完整正文、列表按字数截断且只在真截断时加「…」、画面信息折叠。"""
import re
from pathlib import Path

import pytest

from fe_browse import BROWSE, SEGS, in_browse, seg
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"
LONG = "".join(chr(0x4E00 + i) for i in range(100))   # 100 个互不相同的汉字
PIC = {"desc": "两人<b>签</b>合同", "text_on_screen": "9600", "issues": ["晃动"]}


def with_segs(*segs):
    return {"GET /api/browse": {**BROWSE, "segments": [*segs, *SEGS[1:]]}}


def long_seg(**extra):
    return {**seg(1, 0, 6, 2, "话题", LONG), **extra}


def test_now_panel_shows_full_text():
    html = in_browse("act('jumpSeg', {i: '0'}); return el('#bNow').innerHTML;", with_segs(long_seg()))
    assert LONG in html and "…" not in html


def test_edit_modal_shows_full_original_text():
    html = in_browse("act('jumpSeg', {i: '0'}); await press('KeyE'); return el('#modalBody').innerHTML;", with_segs(long_seg()))
    assert LONG in html


def test_preview_constant_is_gone_everywhere():
    for f in STATIC.glob("*.js"):
        assert "NOW_PREVIEW_CHARS" not in f.read_text(encoding="utf-8"), f.name


def test_se_text_scrolls_inside_instead_of_growing():
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    rule = re.search(r"\.se-text\{([^}]*)\}", css).group(1)
    assert "max-height" in rule and "overflow-y:auto" in rule


@pytest.mark.parametrize("n,expect", [(60, False), (61, True), (0, False)])
def test_row_text_adds_ellipsis_only_when_truncated(n, expect):
    text = LONG[:n]
    html = in_browse("return rowHtml(B().segs[0]);", with_segs(long_seg(text=text)))
    assert ("…" in html) is expect
    if n:
        assert (LONG[:60] + "…" in html) if expect else (text in html)
    assert LONG[60:61] not in html


def test_clip_text_helper_contract():
    out = in_browse("return [clipText('abc', 3), clipText('abcd', 3), clipText('', 3), clipText(null, 3), clipText('abcd', 0)];")
    assert out == ["abc", "abc…", "", "", "…"]


def test_picture_line_in_row_clips_with_ellipsis_only_when_long():
    long_pic = {"desc": LONG, "text_on_screen": "短字", "issues": []}
    html = in_browse("return rowHtml(B().segs[0]);", with_segs(long_seg(visual=long_pic)))
    assert "画面：" + LONG[:40] + "…" in html and "画面：" + LONG[:41] not in html
    assert "画面上的字：短字" in html and "短字…" not in html


def test_now_picture_is_collapsed_details_closed_by_default():
    html = in_browse("act('jumpSeg', {i: '0'}); return el('#bNow').innerHTML;", with_segs(long_seg(visual=PIC)))
    assert '<details class="now-vis">' in html and "<summary>画面</summary>" in html
    assert "画面：两人&lt;b&gt;签&lt;/b&gt;合同" in html and "<b>签" not in html
    assert "画面上的字：9600" in html and "晃动" in html and " open" not in html


def test_now_picture_absent_without_picture_lines():
    html = in_browse("act('jumpSeg', {i: '0'}); return el('#bNow').innerHTML;", with_segs(long_seg()))
    assert "now-vis" not in html and "<details" not in html


def test_now_picture_open_state_is_remembered_across_segments():
    out = in_browse("""act('jumpSeg', {i: '0'});
      const fire = open => el('#bNow').listeners.toggle.forEach(f => f({target: {open, classList: {contains: c => c === 'now-vis'}}}));
      fire(true); act('jumpSeg', {i: '1'}); act('jumpSeg', {i: '0'});
      const opened = el('#bNow').innerHTML; fire(false); act('jumpSeg', {i: '0'});
      return [opened.includes('<details class="now-vis" open>'), el('#bNow').innerHTML.includes(' open'), state.nowPictureOpen];""",
                    with_segs(long_seg(visual=PIC), {**seg(2, 6, 9, 2, "话题", "乙"), "visual": PIC}))
    assert out == [True, False, False]
