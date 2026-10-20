"""M14c · ⑥ 导出（node vm）：本次导出、两个导出按钮的状态、历史版本卡片、KI-98 / KI-100 / KI-102。"""
import re

import pytest

from fe_export import EXPORT_STATE, in_export, js, mac_export, text_of, ver
from fe_harness import NODE

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

STAGE = "el('#stage').innerHTML"
JOB_POSTS = "calls.filter(c => c.method === 'POST' && c.path === '/api/job').map(c => c.body)"


# ---------------------------------------------------------------- 本次导出
def test_current_card_shows_table_size_duration_and_preview_time():
    html = in_export(f"return {STAGE};")
    assert "本次导出" in html
    assert "当前分镜表 2 镜 · 2:58 · 预览片 14:02" in text_of(html)
    assert "会导出为 v4" in text_of(html)
    assert 'data-act="exportMac"' in html and "导出到 Mac 剪映" in html
    assert 'data-act="exportWindows"' in html and "生成 Windows 剪映包" in html


def test_new_version_number_comes_from_the_server_and_reuse_is_explained():
    reuse = in_export(f"return {STAGE};", state={"versions": [ver("v3", current=True, exports=mac_export("v3"), draft="片名_v3")]})
    assert "会导出为 v4" not in text_of(reuse)
    assert "当前分镜表已经是 v3" in text_of(reuse)


def test_both_buttons_are_disabled_with_the_reason_when_the_preview_is_not_fresh():
    html = in_export(f"return {STAGE};", state={"preview": {"status": "outdated", "at": "2026-10-20T14:02:00"},
                                                "versions": [ver("v1")]})
    for act in ("exportMac", "exportWindows"):
        tag = re.search(rf'<button[^>]*data-act="{act}"[^>]*>', html).group(0)
        assert " disabled" in tag and 'title="先在「⑤ 看结果」生成当前分镜表的预览片"' in tag
    assert "先在「⑤ 看结果」生成当前分镜表的预览片" in text_of(html)


def test_buttons_are_enabled_when_the_preview_is_fresh_and_start_jobs():
    html = in_export(f"return {STAGE};")
    for act in ("exportMac", "exportWindows"):
        tag = re.search(rf'<button[^>]*data-act="{act}"[^>]*>', html).group(0)
        assert " disabled" not in tag and "data-starts-job" in tag


def test_clicking_a_disabled_button_posts_nothing():
    out = in_export(f"""await act('exportMac'); await act('exportWindows'); return [{JOB_POSTS}, state.view];""",
                    state={"preview": {"status": "none", "at": None}, "versions": [ver("v1")]})
    assert out == [[], "export"]


# ---------------------------------------------------------------- 导出到 Mac 剪映
def test_export_mac_posts_build_target_mac_in_the_log_modal():
    out = in_export(f"""await act('exportMac'); return [{JOB_POSTS}, el('#modalTitle').textContent,
      el('#mask').classList.contains('on')];""")
    assert out == [[{"project": "新项目", "task": "build", "target": "mac"}], "正在导出", True]


def test_jianying_running_prompts_close_and_continue_resends_the_same_request():
    out = in_export(f"""
      let n = 0;
      __respond = (method, path, body) => {{
        if(method === 'POST' && path === '/api/job'){{
          n += 1;
          return n === 1 ? [409, {{error: '剪映正在运行', need: 'close_jianying', missing: []}}] : [200, {{job_id: 'j2'}}];
        }}
        return respond(method, path);
      }};
      await act('exportMac'); await until(() => el('#modalTitle').textContent === '剪映正在运行');
      const prompt = [el('#modalTitle').textContent, el('#modalBody').innerHTML];
      await act('jianyingClosedGo'); await until(() => n === 2);
      return [prompt, {JOB_POSTS}];""")
    (title, body), posts = out
    assert title == "剪映正在运行" and "这台 Mac 暂时不能分析" not in body
    assert "我已关掉，继续" in body and "取消" in body and "⌘Q" in body
    assert posts == [{"project": "新项目", "task": "build", "target": "mac"}] * 2


def test_jianying_prompt_cancel_starts_nothing_more():
    out = in_export(f"""
      __respond = (method, path) => method === 'POST' && path === '/api/job'
        ? [409, {{error: '剪映正在运行', need: 'close_jianying', missing: []}}] : respond(method, path);
      await act('exportMac'); await until(() => el('#modalTitle').textContent === '剪映正在运行'); await act('jianyingCancel');
      return [{JOB_POSTS}.length, el('#mask').classList.contains('on')];""")
    assert out == [1, False]


# ---------------------------------------------------------------- 生成 Windows 剪映包
def test_export_windows_posts_build_target_windows():
    out = in_export(f"""await act('exportWindows'); return {JOB_POSTS};""")
    assert out == [{"project": "新项目", "task": "build", "target": "windows"}]


def test_windows_zip_state_of_the_current_version_shows_name_size_reveal_and_usage():
    cur = ver("v4", current=True, windows_zip="片名_v4_Windows.zip", windows_mb=312,
              exports={"mac": None, "windows": {"zip": "片名_v4_Windows.zip", "at": "t"}})
    html = in_export(f"return {STAGE};", state={"versions": [cur]})
    top = html.split("历史版本")[0]
    assert "已生成 片名_v4_Windows.zip（312 MB）" in text_of(top)
    assert 'data-act="revealExport"' in top and "在访达中显示" in top
    assert "拷到 Windows 解压，双击 INSTALL.bat" in text_of(top)
    assert 'data-act="exportWindows"' not in top


def test_job_done_while_viewing_export_repaints_the_cards():
    after = {"versions": [ver("v4", current=True, windows_zip="片名_v4_Windows.zip", windows_mb=312,
                              exports={"mac": None, "windows": {"zip": "z", "at": "t"}})]}
    out = in_export(f"""
      let posted = false;
      __respond = (method, path, body) => {{
        if(method === 'POST' && path === '/api/job'){{ posted = true; return [200, {{job_id: 'j2'}}]; }}
        if(path.startsWith('/api/job/')) return [200, {{status: 'done', task: 'build', log: [], elapsed_s: 3, project: '新项目'}}];
        if(path.startsWith('/api/state') && posted) return [200, {js({**EXPORT_STATE, **after})}];
        return respond(method, path);
      }};
      const before = {STAGE};
      await act('exportWindows');
      for(let i = 0; i < 4; i++) await runTimers();
      return [before, {STAGE}];""")
    assert "已生成" not in out[0] and "已生成 片名_v4_Windows.zip（312 MB）" in text_of(out[1])


# ---------------------------------------------------------------- 已经在 Mac 剪映里（Q1）与 KI-98
def _mac_cur():
    return ver("v4", current=True, exports=mac_export("v4"), draft="片名_v4")


def test_mac_button_turns_into_in_jianying_state_with_open_button_when_detected():
    html = in_export(f"return {STAGE};", state={"versions": [_mac_cur()]})
    top = html.split("历史版本")[0]
    assert "已在 Mac 剪映里：片名_v4" in text_of(top)
    assert 'data-act="exportMac"' not in top and 'data-act="openJianying"' in top and "打开剪映" in top
    assert 'data-act="exportWindows"' in top  # 同一张表还能补 Windows 包


def test_open_jianying_is_hidden_and_explained_when_not_detected():
    html = in_export(f"return {STAGE};", state={"versions": [_mac_cur()], "jianying": {"installed": False}})
    assert 'data-act="openJianying"' not in html
    assert "没检测到剪映专业版，装好后在剪映的本地草稿里找「片名_v4」" in text_of(html)


def test_open_jianying_posts_open_and_surfaces_wrapper_errors():
    out = in_export(f"""await act('openJianying');
      const ok = calls.filter(c => c.path === '/api/open').map(c => c.body);
      __respond = (m, p) => p === '/api/open' ? [500, {{error: '没能打开剪映：超时'}}] : respond(m, p);
      await act('openJianying');
      return [ok, el('#toast').textContent];""", state={"versions": [_mac_cur()]})
    assert out == [[{"project": "新项目", "target": "jianying"}], "没能打开剪映：超时"]


def test_no_toolbar_open_jianying_without_a_mac_export():
    html = in_export(f"return {STAGE};", state={"versions": [ver("v1")]})
    assert 'data-act="openJianying"' not in html


# ---------------------------------------------------------------- 历史版本卡片
def test_history_cards_show_facts_current_tag_and_mac_draft_only_when_exported():
    vs = [ver("v3", current=True, mtime="10-20 14:00", shots=18, duration=178, exports=mac_export("v3"), draft="片名_v3"),
          ver("v2", mtime="10-20 12:00", shots=16, duration=150)]
    html = in_export(f"return {STAGE};", state={"versions": vs})
    hist = text_of(html.split("历史版本")[1])
    assert "v3" in hist and "10-20 14:00" in hist and "18 镜" in hist and "2:58" in hist and "当前" in hist
    assert "Mac 剪映：片名_v3" in hist
    v2 = next(c for c in html.split('<div class="ver') if "10-20 12:00" in c)
    assert "Mac 剪映" not in text_of(v2)  # KI-102：没装进过剪映的版本不显示草稿名


def test_legacy_version_keeps_its_draft_name_with_a_note():
    html = in_export(f"return {STAGE};", state={"versions": [
        ver("v1", legacy=True, exports=None, draft="老片名_v1", has_snapshot=False, preview=False)]})
    assert "Mac 剪映草稿名：老片名_v1（改版前生成，未记录是否导入过）" in text_of(html)
    assert "这一版只有工程，没有预览片" in html


def test_history_windows_zip_and_generate_buttons():
    vs = [ver("v2", windows_zip="片名_v2_Windows.zip", windows_mb=12, exports={"mac": None, "windows": {"zip": "z", "at": "t"}}),
          ver("v1")]
    html = in_export(f"return {STAGE};", state={"versions": vs})
    hist = html.split("历史版本")[1]
    assert "已生成 片名_v2_Windows.zip（12 MB）" in text_of(hist)
    assert hist.count('data-act="revealExport"') == 1 and hist.count('data-act="exportVersion"') == 1
    assert 'data-act="exportVersion" data-i="1"' in hist and "data-starts-job" in hist


def test_export_version_posts_export_task_and_reveal_posts_open():
    out = in_export("""await act('exportVersion', {i: '0'}); await act('revealExport', {i: '0'});
      return [calls.filter(c => c.method === 'POST' && c.path === '/api/job').map(c => c.body),
              calls.filter(c => c.path === '/api/open').map(c => c.body)];""",
                    {"POST /api/open": {"ok": True}}, state={"versions": [ver("v2"), ver("v1")]})
    assert out == [[{"project": "新项目", "task": "export", "version": "v2"}],
                   [{"project": "新项目", "target": "export", "version": "v2"}]]


def test_history_preview_video_uses_the_version_preview_route():
    html = in_export(f"return {STAGE};", state={"versions": [ver("v2")]})
    assert '<video src="/media/%E6%96%B0%E9%A1%B9%E7%9B%AE/preview/v2" controls' in html


def test_blocked_version_is_flagged_and_has_no_windows_actions_but_keeps_preview():
    msg = "这一版含 2 段已标为不可用的片段，不能生成 Windows 剪映包"
    vs = [ver("v2", unusable_hits=2, blocked=msg, windows_zip="x_Windows.zip", windows_mb=5), ver("v1")]
    html = in_export(f"return {STAGE};", state={"versions": vs})
    hist = html.split("历史版本")[1]
    first = hist.split('<div class="ver')[1]
    assert "blocked" in first.split(">")[0] and msg in text_of(hist)
    assert 'data-act="exportVersion" data-i="0"' not in hist and 'data-act="revealExport" data-i="0"' not in hist
    assert "<video" in first
    assert 'data-act="exportVersion" data-i="1"' in hist  # 其它版本不受影响


def test_unconfirmable_version_shows_the_server_reason():
    vs = [ver("v1", unusable_hits=None, blocked="这一版没有留存分镜表，没法确认是否含不可用片段")]
    html = in_export(f"return {STAGE};", state={"versions": vs})
    assert "没法确认是否含不可用片段" in text_of(html) and 'data-act="exportVersion"' not in html


def test_dynamic_fields_are_escaped_and_indexes_are_numeric():
    vs = [ver("v2", draft="<i>片</i>_v2", exports={"mac": {"draft": "<i>片</i>_v2", "at": "t"}, "windows": None},
              mtime="<b>x", windows_zip="<b>z.zip", windows_mb=3, blocked=None)]
    html = in_export(f"return {STAGE};", state={"versions": vs})
    assert "<i>" not in html and "<b>" not in html
    assert "&lt;i&gt;片&lt;/i&gt;_v2" in html and "&lt;b&gt;z.zip" in html
    assert re.search(r'data-i="\d+"', html)


def test_empty_history_says_nothing_exported_yet():
    out = in_export(f"return {STAGE};")
    assert "还没有导出过" in out and "历史版本" in out


def test_no_old_temporary_flow_remains():
    out = in_export(f"return [{STAGE}, typeof openBuild, typeof doBuild, document.querySelector('#noDraft').checked];")
    assert "生成新版本" not in out[0] and "只出预览" not in out[0] and "这次只生成预览片" not in out[0]
    assert out[1:3] == ["undefined", "undefined"]


def test_export_blocked_409_is_a_plain_toast_not_the_cannot_analyse_dialog():
    out = in_export("""await act('exportVersion', {i: '0'}); await until(() => el('#toast').textContent);
      return [el('#toast').textContent, el('#modalTitle').textContent, el('#mask').classList.contains('on')];""",
                    {"POST /api/job": [409, {"error": "这一版含 2 段已标为不可用的片段", "need": "export_blocked", "missing": []}]},
                    state={"versions": [ver("v1")]})
    assert out[0] == "这一版含 2 段已标为不可用的片段" and out[1] != "这台 Mac 暂时不能分析" and out[2] is False


def test_blocked_current_version_replaces_the_windows_button_with_the_red_notice():
    msg = "这一版含 2 段已标为不可用的片段，不能生成 Windows 剪映包"
    html = in_export(f"return {STAGE};", state={"versions": [ver("v4", current=True, unusable_hits=2, blocked=msg)]})
    top = html.split("历史版本")[0]
    assert 'data-act="exportWindows"' not in top and msg in text_of(top) and "blocked-note" in top


def test_jianying_continue_after_the_preview_went_stale_does_not_resend():
    out = in_export(f"""
      __respond = (m, p) => m === 'POST' && p === '/api/job'
        ? [409, {{error: '剪映正在运行', need: 'close_jianying', missing: []}}] : respond(m, p);
      await act('exportMac'); await until(() => el('#modalTitle').textContent === '剪映正在运行');
      state.data = {{...state.data, preview: {{status: 'outdated', at: null}}}};
      await act('jianyingClosedGo');
      return [{JOB_POSTS}.length, el('#toast').textContent, el('#mask').classList.contains('on')];""")
    assert out == [1, "先在「⑤ 看结果」生成当前分镜表的预览片", False]


def test_jianying_cancel_forgets_the_pending_request():
    out = in_export("""
      __respond = (m, p) => m === 'POST' && p === '/api/job'
        ? [409, {error: '剪映正在运行', need: 'close_jianying', missing: []}] : respond(m, p);
      await act('exportMac'); await until(() => el('#modalTitle').textContent === '剪映正在运行');
      await act('jianyingCancel');
      return [jianyingUi.again, el('#mask').classList.contains('on')];""")
    assert out == [None, False]
