"""M13c Task 17：③ 看素材页面（node vm）：摘要卡、分布条、列表视图与筛选、当前段、播放器、键盘导航。"""
import json
import re
from pathlib import Path

import pytest

from fe_browse import BROWSE, BROWSE_ROUTES, KEYS_SETUP, SEGS, in_browse
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")
STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"


# ---------------------------------------------------------------- 骨架与加载
def test_browse_stage_is_a_stable_skeleton_with_player_and_panel():
    out = in_browse("return el('#stage').innerHTML;")
    for part in ('id="bSummary"', 'id="bDensity"', 'id="bFilters"', 'id="bList"', 'id="bPv"',
                 'id="bNow"', 'id="bPanel"'):
        assert part in out
    assert "打开看素材窗口" not in out and "/api/window" not in out


def test_enter_loads_browse_and_points_player_at_proxy():
    out = in_browse("return [el('#bPv').src, calls.filter(c => c.path.startsWith('/api/browse')).map(c => c.path)];")
    assert out[0] == "/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/proxy"
    assert out[1] == ["/api/browse?project=%E6%96%B0%E9%A1%B9%E7%9B%AE"]


def test_browse_load_failure_shows_escaped_server_error_and_no_window_hint():
    out = in_browse("return el('#bList').innerHTML;", {"GET /api/browse": [404, {"error": "还没有<b>分析</b>结果"}]})
    assert "还没有&lt;b&gt;分析&lt;/b&gt;结果" in out and "<b>分析" not in out


def test_warnings_are_escaped():
    out = in_browse("return el('#bSummary').innerHTML;")
    assert "有个警告&lt;u&gt;" in out and "<u>" not in out


# ---------------------------------------------------------------- 摘要卡
def test_summary_card_escapes_and_makes_key_points_clickable():
    html = in_browse("return el('#bSummary').innerHTML;")
    assert "讲了&lt;i&gt;合同&lt;/i&gt;的事" in html and "<i>合同" not in html
    assert 'data-act="jumpAt" data-t="12"' in html and "00:12.0" in html
    assert "关键&lt;b&gt;点&lt;/b&gt;" in html and "因为&lt;x&gt;" in html
    assert "兜底" in html


def test_summary_lists_speakers_with_duration():
    html = in_browse("return el('#bSummary').innerHTML;")
    assert "老王&lt;b&gt; · 3:20" in html and "小李 · 1:05" in html
    assert html.index("老王") < html.index("小李")


def test_summary_without_content_shows_placeholder():
    data = {**BROWSE, "summary": {}, "speakers": []}
    html = in_browse("return el('#bSummary').innerHTML;", {"GET /api/browse": data})
    assert "暂无摘要" in html


def test_key_point_click_plays_from_timecode_for_a_few_seconds():
    out = in_browse("""let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      act('jumpAt', {t: '12'}); return [el('#bPv').currentTime, played, B().stopAt];""")
    assert out[0] == pytest.approx(11.7) and out[1] == 1 and out[2] > 12


# ---------------------------------------------------------------- 分布条
def test_density_bar_colored_by_level_and_clickable():
    html = in_browse("return el('#bDensity').innerHTML;")
    assert html.count('data-act="jumpSeg"') == len(SEGS)
    assert 'class="d lv3 "' in html or "lv3" in html
    assert 'data-i="0"' in html and "width:10.000%" in html


def test_density_click_selects_and_plays_that_segment():
    out = in_browse("""let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      act('jumpSeg', {i: '2'}); return [B().cur, el('#bPv').currentTime, played];""")
    assert out == [2, pytest.approx(19.7), 1]


# ---------------------------------------------------------------- 筛选
def test_filters_constant_lists_the_seven_prd_labels_in_order():
    out = in_browse("return FILTERS.map(f => f[1]);")
    assert out == ["全部", "待定", "可用", "废片", "剪辑列表", "不可用", "未用"]


@pytest.mark.parametrize("key,expected", [
    ("all", ["S1", "S2", "S3", "S4", "S5"]),
    ("pending", ["S2"]),
    ("usable", ["S1", "S4"]),          # S5 是不可用，不算可用
    ("waste", ["S3"]),
    ("list", ["S4"]),
    ("unusable", ["S5"]),
    ("unused", ["S1", "S2", "S4", "S5"]),
])
def test_filter_results(key, expected):
    out = in_browse(f"act('setFilter', {{v: '{key}'}}); return ids();")
    assert out == expected


def test_unusable_segment_is_excluded_from_level_filters_even_if_level_matches():
    out = in_browse("""B().segs[1].unusable = true; act('setFilter', {v: 'pending'}); return ids();""")
    assert out == []


def test_filter_chips_show_counts_and_mark_the_active_one():
    html = in_browse("act('setFilter', {v: 'usable'}); return el('#bFilters').innerHTML;")
    assert "可用 2" in html and "待定 1" in html and "不可用 1" in html and "全部 5" in html
    active = re.search(r'class="on"[^>]*data-v="usable"|data-v="usable"[^>]*class="on"', html)
    assert active


def test_unknown_filter_key_is_ignored():
    out = in_browse("act('setFilter', {v: 'bogus'}); return [B().filter, ids().length];")
    assert out == ["all", 5]


# ---------------------------------------------------------------- 视图切换
def test_topic_view_groups_with_counts_and_usable_duration():
    html = in_browse("act('setView', {v: 'topic'}); return el('#bList').innerHTML;")
    assert html.index("讲合同") < html.index("聊吃饭")
    assert "可用 1 · 待定 1 · 废片 0 · 可用时长 0:06" in html
    assert "可用 1 · 待定 0 · 废片 1 · 可用时长 0:05" in html  # 聊吃饭：S4 可用 5s；S5 不可用不计
    assert "必留" not in html


def test_topic_view_respects_filter_and_navigation_follows_display_order():
    out = in_browse("""act('setView', {v: 'topic'}); act('setFilter', {v: 'usable'}); return ids();""")
    assert out == ["S1", "S4"]


def test_view_toggle_marks_active_button():
    html = in_browse("act('setView', {v: 'topic'}); return el('#bFilters').innerHTML;")
    assert re.search(r'data-act="setView" data-v="topic"', html) and "按话题" in html and "按时间" in html


# ---------------------------------------------------------------- 行内容
def test_row_has_timecode_level_topic_text_reason_and_visual_tags():
    html = in_browse("return el('#bList').innerHTML;")
    first = html.split('id="r1"')[0]
    assert "00:00.0" in first and "可用" in first and "讲合同" in first
    assert "甲&lt;b&gt;粗体&lt;/b&gt;" in first and "信息密度高" in first
    assert "虚焦" in first and "过暗" in first and "<b>粗体" not in html


@pytest.mark.parametrize("flag,label", [("soft", "虚焦"), ("shaky", "抖动"), ("dark", "过暗"), ("still", "静止")])
def test_visual_flag_labels(flag, label):
    out = in_browse(f"return rowHtml({{...B().segs[1], visual_flags: ['{flag}', 'weird<x>']}});")
    assert label in out and "weird" not in out  # 未知标签不渲染


def test_row_toggle_shows_add_or_added_and_unusable_button():
    html = in_browse("return el('#bList').innerHTML;")
    row1, row4 = html.split('id="r1"')[0], html.split('id="r4"')[0].split('id="r3"')[1]
    assert "＋ 剪辑列表" in row1 and "✓ 剪辑列表" in row4
    assert 'data-act="toggleListIdx"' in row1 and 'data-act="markUnusableIdx"' in row1 and "⊘" in row1


def test_row_state_classes_and_list_tag_can_stack():
    out = in_browse("""act('jumpSeg', {i: '3'}); return rowHtml(B().segs[3]);""")
    assert 'class="row current in-list"' in out and "已在剪辑列表" in out


def test_unusable_row_is_marked_and_used_tag_shown():
    html = in_browse("return el('#bList').innerHTML;")
    row5 = html.split('id="r4"')[1]
    row3 = html.split('id="r2"')[1].split('id="r3"')[0]
    assert "unusable" in row5.split(">")[0] or 'row unusable' in html
    assert "已用" in row3


def test_ui_never_says_must_keep_word():
    out = in_browse("act('setView', {v: 'topic'}); return el('#stage').innerHTML + el('#bList').innerHTML + el('#bPanel').innerHTML;")
    assert "必留" not in out and "★" not in out


# ---------------------------------------------------------------- 当前段、播放器
def test_click_row_sets_current_and_plays_with_padding():
    out = in_browse("""let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      act('jumpSeg', {i: '1'});
      return [B().cur, el('#r1').classList.contains('current'), el('#bPv').currentTime, B().stopAt, played,
              el('#bNow').innerHTML];""")
    assert out[0] == 1 and out[1] is True
    assert out[2] == pytest.approx(9.7) and out[3] == pytest.approx(16.3) and out[4] == 1
    assert "00:10.0" in out[5] and "不确定" in out[5]


def test_current_ring_moves_from_old_row_to_new_row():
    out = in_browse("""act('jumpSeg', {i: '1'}); act('jumpSeg', {i: '2'});
      return [el('#r1').classList.contains('current'), el('#r2').classList.contains('current')];""")
    assert out == [False, True]


def test_player_is_not_driven_by_a_global_interval_until_it_plays():
    out = in_browse("""act('jumpSeg', {i: '1'}); return intervals.filter(i => !i.cleared).length;""")
    assert out == 0


def test_play_rejection_is_swallowed():
    out = in_browse("""el('#bPv').play = () => Promise.reject(new Error('blocked'));
      act('jumpSeg', {i: '0'}); await tick(); return B().cur;""")
    assert out == 0


def test_click_on_row_button_does_not_also_select_row():
    out = in_browse("""const row = node({'data-act': 'jumpSeg', 'data-i': '0'}); const btn = node({'data-act': 'noop'}, row);
      let hit = 0; ACTIONS.noop = () => { hit++; }; click(btn); return [hit, B().cur];""")
    assert out == [1, None]


# ---------------------------------------------------------------- 键盘导航与不整表重绘
def test_down_selects_first_then_next_and_up_goes_back():
    out = in_browse("""await press('ArrowDown'); const a = B().cur; await press('ArrowDown'); const b = B().cur;
      await press('ArrowUp'); return [a, b, B().cur];""")
    assert out == [0, 1, 0]


def test_navigation_clamps_at_both_ends():
    out = in_browse("""await press('ArrowUp'); const top = B().cur;
      for (let i = 0; i < 9; i++) await press('ArrowDown'); return [top, B().cur];""")
    assert out == [0, 4]


def test_navigation_moves_within_current_filter_only():
    out = in_browse("""act('setFilter', {v: 'usable'}); await press('ArrowDown'); const a = B().cur;
      await press('ArrowDown'); return [a, B().cur];""")
    assert out == [0, 3]


def test_navigation_scrolls_row_into_view_nearest():
    out = in_browse("""const got = []; for (const i of [0, 1]) el('#r' + i).scrollIntoView = o => got.push([i, o]);
      await press('ArrowDown'); await press('ArrowDown'); return got;""")
    assert out == [[0, {"block": "nearest"}], [1, {"block": "nearest"}]]


def test_navigation_sets_current_but_does_not_autoplay():
    out = in_browse("""let played = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      await press('ArrowDown'); return [played, el('#bPv').currentTime];""")
    assert out[0] == 0 and out[1] == pytest.approx(0)  # 入点 0 − 0.3 夹到 0


def test_selection_and_filter_change_do_not_redraw_the_whole_list():
    out = in_browse("""el('#bList').innerHTML += '<!--marker-->'; await press('ArrowDown'); act('jumpSeg', {i: '2'});
      return el('#bList').innerHTML.includes('<!--marker-->');""")
    assert out is True


def test_space_toggles_play_pause_and_prevents_scroll():
    out = in_browse("""let played = 0, paused = 0; el('#bPv').play = () => { played++; return Promise.resolve(); };
      el('#bPv').pause = () => { paused++; }; el('#bPv').paused = true;
      await press('ArrowDown'); const e1 = await press('Space');
      el('#bPv').paused = false; await press('Space'); return [played, paused, e1.prevented];""")
    assert out == [1, 1, True]


def test_space_replays_current_segment_when_player_is_outside_it():
    out = in_browse("""el('#bPv').paused = true; await press('ArrowDown'); await press('ArrowDown'); // 当前 S2
      el('#bPv').currentTime = 50; await press('Space'); return [el('#bPv').currentTime, B().stopAt];""")
    assert out[0] == pytest.approx(9.7) and out[1] == pytest.approx(16.3)


# ---------------------------------------------------------------- 切项目与文件规模
def test_leaving_project_resets_browse_state():
    out = in_browse("""await press('ArrowDown'); await selectProject('新项目'); return [state.browse === null || state.browse.cur === null];""")
    assert out == [True]


def test_slow_response_of_previous_project_is_ignored():
    out = run_app("""(async () => {
      await selectProject('新项目'); const orig = window.fetch; let release = null; let held = false;
      window.fetch = (p, o) => {
        if (!String(p).startsWith('/api/browse') || held) return orig(p, o);
        held = true;   // 第一次请求挂起，放出来时是另一份（旧项目的）数据：只有 2 段
        return new Promise(r => { release = () => orig(p, o).then(resp => resp.json().then(d =>
          r({ok: true, status: 200, json: async () => ({...d, segments: d.segments.slice(0, 2)})}))); });
      };
      await go('browse'); await tick();
      await selectProject('新项目'); state.view = 'browse'; enterBrowse(); await tick(); await tick();
      const fresh = B() && B().segs.length;
      release(); await tick(); await tick(); await tick();
      return [fresh, B() && B().segs.length, el('#bList').innerHTML.split('class="row').length - 1];
    })()""", routes=BROWSE_ROUTES, setup=KEYS_SETUP)
    assert out == [5, 5, 5]


def test_browse_scripts_stay_within_size_limit():
    for name in ("step-browse.js", "cliplist.js", "shortcuts.js"):
        assert len((STATIC / name).read_text(encoding="utf-8").splitlines()) <= 400, name


def test_old_browse_window_is_gone_from_main_ui():
    src = (STATIC / "step-browse.js").read_text(encoding="utf-8") + (STATIC / "app.js").read_text(encoding="utf-8")
    assert "openBrowse" not in src and "browse.html" not in src
    assert not (STATIC / "browse.html").exists() and not (STATIC / "browse.js").exists()
