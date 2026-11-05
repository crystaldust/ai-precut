"""③ 看素材：对白段的一句话总结（summary）显示在列表 / 当前段 / 编辑起止弹窗；不可信文本要转义；起止改过后标「可能过时」。"""
import json
import re
from pathlib import Path

import pytest

from fe_browse import BROWSE, SEGS, in_browse, mark_ok, seg
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

EVIL = "<img src=x onerror=alert(1)>"
ESC = "&lt;img src=x onerror=a"   # 载荷 28 字，客户端截到 20 字后的转义结果
SHORT = "<b onclick=a()>"
LONG = "".join(chr(0x4E00 + i) for i in range(30))
OPEN = "act('jumpSeg', {i: '0'}); "


def with_segs(*segs):
    return {"GET /api/browse": {**BROWSE, "segments": [*segs, *SEGS[1:]]}}


def first(**extra):
    return {**seg(1, 0, 6, 2, "话题", "原话内容"), **extra}


def row(**extra):
    return in_browse("return rowHtml(B().segs[0]);", with_segs(first(**extra)))


def now(**extra):
    return in_browse(OPEN + "return el('#bNow').innerHTML;", with_segs(first(**extra)))


def modal(**extra):
    return in_browse(OPEN + "await press('KeyE'); return el('#modalBody').innerHTML;", with_segs(first(**extra)))


ALL = [row, now, modal]


@pytest.mark.parametrize("view", ALL)
def test_summary_is_escaped_everywhere(view):
    html = view(summary=EVIL)
    assert ESC in html and EVIL not in html and "<img" not in html
    short = view(summary=SHORT)
    assert "&lt;b onclick=a()&gt;" in short and SHORT not in short


@pytest.mark.parametrize("view", ALL)
@pytest.mark.parametrize("extra", [{}, {"summary": ""}, {"summary": None}, {"summary": 5}, {"summary": ["x"]}])
def test_no_valid_summary_means_no_element(view, extra):
    assert "ssum" not in view(**extra)


@pytest.mark.parametrize("view", ALL)
def test_visual_segment_shows_no_summary(view):
    assert "ssum" not in view(kind="visual", summary="不该出现", label="画面")


@pytest.mark.parametrize("view", ALL)
def test_summary_is_clamped_to_20_chars(view):
    html = view(summary=LONG)
    assert LONG[:20] in html and LONG[:21] not in html


def test_clamp_counts_code_points_not_utf16_units():
    html = row(summary="😀" * 25)
    assert "😀" * 20 in html and "😀" * 21 not in html and "�" not in html


def test_helper_contract():
    out = in_browse("""const b = s => segSummaryHtml(s);
      return [b({}), b({summary: 'a', kind: 'visual'}), b({summary: '甲'}), b({summary: '甲', bounds_edited: true})];""")
    assert out[0] == "" and out[1] == ""
    assert out[2] == '<b class="ssum">甲</b>'
    assert 'class="ssum stale"' in out[3] and 'class="tag-stale"' in out[3]
    assert "可能过时" in out[3] and "起止已改，总结按原来的对白写的，可能过时" in out[3]


@pytest.mark.parametrize("view", ALL)
def test_stale_tag_only_when_bounds_edited(view):
    assert "tag-stale" not in view(summary="总结")
    html = view(summary="总结", bounds_edited=True)
    assert "tag-stale" in html and "可能过时" in html


def test_summary_comes_before_original_text_in_row():
    html = row(summary="一句话总结")
    assert 0 <= html.index("一句话总结") < html.index("原话内容")
    assert 'class="orig"' in html


def test_row_keeps_existing_tags_with_summary():
    html = row(summary="总结")
    for k in ("tag-list", "tag-un", "tag-edit"):
        assert k in html


def test_modal_shows_summary_above_original_text():
    html = modal(summary="弹窗总结")
    assert html.index("弹窗总结") < html.index("原话内容")


def test_now_panel_summary_above_dialogue():
    html = now(summary="当前总结")
    assert html.index("当前总结") < html.index("原话内容")


def test_edit_marks_row_stale_and_undo_clears_it():
    edited = mark_ok({"id": "S2", "start": 11, "end": 17, "dur": 6, "base_start": 10, "base_end": 16, "bounds_edited": True,
                      "level": 2, "level_reason": "不确定", "override": False, "must_keep": False, "unusable": False})
    cleared = mark_ok({**edited["segment"], "start": 10, "end": 16, "bounds_edited": False})
    out = in_browse("""
      let n = 0; window.__respond = (m, p, body) => m === 'POST' && p === '/api/browse/bounds'
        ? [200, ++n === 1 ? EDIT : CLEAR] : respond(m, p);
      act('jumpSeg', {i: '1'}); await press('KeyE');
      act('segEditSlider', {which: 'start'}, {value: '11'}); act('segEditSlider', {which: 'end'}, {value: '17'});
      act('segEditSave'); await tick(); await tick();
      const after = [el('#ss1').innerHTML, el('#bNow').innerHTML];
      await press('KeyZ'); await tick(); await tick();
      return [after, el('#ss1').innerHTML, el('#bNow').innerHTML];""".replace("EDIT", json.dumps(edited, ensure_ascii=False)).replace("CLEAR", json.dumps(cleared, ensure_ascii=False)),
                    with_segs(first(), {**seg(2, 10, 16, 2, "讲合同", "乙"), "summary": "乙的总结"}))
    after, undone, undone_now = out
    assert "tag-stale" in after[0] and "tag-stale" in after[1] and "乙的总结" in after[0]
    assert "ssum" in undone and "tag-stale" not in undone and "乙的总结" in undone
    assert "tag-stale" not in undone_now


def test_repaint_without_summary_leaves_no_element():
    out = in_browse("""const s = B().segs[0]; paintRow(s); return el('#ss0').innerHTML;""", with_segs(first()))
    assert out == ""



STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"


def orig_line(html):
    """取出 <span class="orig"> 的完整内容（按 span 嵌套配平，不是取到第一个 </span>）。"""
    start = html.index('<span class="orig">') + len('<span class="orig">')
    depth, pos = 1, start
    for m in re.finditer(r"<span\b|</span>", html[start:]):
        depth += 1 if m.group() != "</span>" else -1
        if depth == 0:
            return html[start:start + m.start()]
    raise AssertionError("orig span 没有闭合")


@pytest.mark.parametrize("extra", [{"summary": "总结"}, {}])
def test_status_tags_sit_on_the_original_text_line(extra):
    html = row(must_keep=True, unusable=True, inCut=True, **extra)
    line = orig_line(html)
    assert "原话内容" in line
    for k in ("tag-list", "tag-un", "tag-edit", "used"):
        assert f'class="{k}"' in line


def test_row_without_summary_keeps_empty_sline_and_single_line_layout():
    html = row()
    assert '<span class="sline" id="ss0"></span>' in html
    assert html.count('class="orig"') == 1 and html.index('class="sline"') < html.index('class="orig"')


def _rule(css, selector):
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


@pytest.mark.parametrize("selector", [".sline", ".row .sline:not(:empty) + .orig"])
def test_summary_and_original_lines_ellipsize(selector):
    body = _rule((STATIC / "app.css").read_text(encoding="utf-8"), selector)
    for decl in ("overflow:hidden", "text-overflow:ellipsis", "white-space:nowrap"):
        assert decl in body.replace(" ", "")


def test_summary_max_chars_matches_backend():
    js_src = (STATIC / "step-browse.js").read_text(encoding="utf-8")
    front = int(re.search(r"const SUMMARY_MAX_CHARS = (\d+);", js_src).group(1))
    py_src = (STATIC.parent.parent / "pipeline" / "segment_summary.py").read_text(encoding="utf-8")
    back = int(re.search(r"^SUMMARY_MAX = (\d+)", py_src, re.M).group(1))
    assert front == back
    assert "segment_summary.SUMMARY_MAX" in js_src


def test_resync_repaints_summary_and_stale_and_removes_cleared():
    changed = {**seg(1, 0, 6, 2, "话题", "原话内容"), "summary": "新总结", "bounds_edited": True}
    cleared = seg(1, 0, 6, 2, "话题", "原话内容")
    out = in_browse("""
      const before = rowHtml(B().segs[0]);
      window.__respond = (m, p) => m === 'GET' && p.startsWith('/api/browse?') ? [200, DATA1] : respond(m, p);
      await resyncBrowse(); await tick();
      const mid = [rowHtml(B().segs[0]), B().segs[0].summary];
      window.__respond = (m, p) => m === 'GET' && p.startsWith('/api/browse?') ? [200, DATA2] : respond(m, p);
      await resyncBrowse(); await tick();
      return [before, mid, rowHtml(B().segs[0]), B().segs[0].summary === undefined];"""
                    .replace("DATA1", json.dumps({**BROWSE, "segments": [changed, *SEGS[1:]]}, ensure_ascii=False))
                    .replace("DATA2", json.dumps({**BROWSE, "segments": [cleared, *SEGS[1:]]}, ensure_ascii=False)),
                    with_segs(first(summary="旧总结")))
    before, mid, after, gone = out
    assert "旧总结" in before and "tag-stale" not in before
    assert "新总结" in mid[0] and "tag-stale" in mid[0] and mid[1] == "新总结"
    assert "ssum" not in after and "tag-stale" not in after and "新总结" not in after and gone is True
