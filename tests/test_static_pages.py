"""GL-05 / GL-07 / GL-23 前端静态守卫：纯文本检查页面源码。"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"
PAGES = ["index.html"]
XSS_PAGES = ["index.html"]
COMMON_JS = '<script src="/static/common.js"></script>'


def _scripts(page):
    """页面按顺序加载的 /static/*.js 文件名。"""
    return re.findall(r'<script[^>]*\ssrc="/static/([^"]+\.js)"', (STATIC / page).read_text(encoding="utf-8"))


def _read(name):
    """页面源码 + 它加载的全部脚本（KI-53 脚本外置；M13 主页拆成多个文件，守卫照样看得到）。"""
    text = (STATIC / name).read_text(encoding="utf-8")
    if name.endswith(".html"):
        for js in _scripts(name):
            text += "\n" + (STATIC / js).read_text(encoding="utf-8")
    return text


def _html(name):
    return (STATIC / name).read_text(encoding="utf-8")


ALL_SOURCES = sorted(p.name for p in STATIC.glob("*.html") if p.name != "prototype.html") + \
    sorted(p.name for p in STATIC.glob("*.js"))
JS_FILES = sorted(p.name for p in STATIC.glob("*.js"))
MAX_JS_LINES = 400          # M13：每个前端脚本聚焦一件事
INDEX_ENTRY = "main.js"     # 主页最后加载的启动脚本（所有 ACTIONS 注册都在它之前）
INDEX_SCRIPT_ORDER = ["common.js", "base.js", "jobs.js", "settings.js", "support.js", "sidebar.js",
                      "wizard.js", "shortcuts.js", "cliplist.js", "project-form.js", "step-analyze.js", "step-browse.js",
                      "step-criteria.js", "criteria-analysis.js", "criteria-pending.js", "step-result.js", "step-export.js", "app.js", INDEX_ENTRY]


# ---------------------------------------------------------------- GL-05 / KI-88
@pytest.mark.parametrize("page", PAGES)
def test_pages_load_common_js_first_and_hold_no_token(page):
    src = _html(page)
    own = f'<script src="/static/{INDEX_ENTRY if page == "index.html" else page.replace(".html", ".js")}"></script>'
    assert COMMON_JS in src and own in src
    assert src.index(COMMON_JS) < src.index(own)
    assert "aicut-token" not in src and "__AICUT_TOKEN__" not in src  # 凭证只在 HttpOnly cookie 里


def test_common_js_escapes_quote():
    js = _read("common.js")
    assert "window.esc" in js
    assert "&#39;" in js
    assert "X-AICUT-Token" not in js and "credentials" in js


def test_pick_sends_json():
    assert "api('/api/pick', {method:'POST'})" not in _read("index.html")


# ---------------------------------------------------------------- GL-07 / KI-53
@pytest.mark.parametrize("name", ALL_SOURCES)
def test_no_inline_event_handlers(name):
    """CSP 不允许内联事件：页面和脚本模板里都不能再有 on* 属性（更强地替代了原来的「不拼字符串」守卫）。"""
    hits = re.findall(r"<[a-zA-Z][^>]*?\son[a-z]+\s*=", _html(name))
    assert hits == []


@pytest.mark.parametrize("page", PAGES)
def test_no_inline_script_blocks(page):
    assert re.findall(r"<script(?![^>]*\ssrc=)[^>]*>", _html(page)) == []


@pytest.mark.parametrize("name", ALL_SOURCES)
def test_data_attributes_never_take_raw_interpolation(name):
    """data-* 里的动态值必须过 num() / esc()（GL-07）。"""
    hits = re.findall(r'data-[a-z]+="\$\{(?!num\(|esc\()', _html(name))
    assert hits == []


@pytest.mark.parametrize("page", XSS_PAGES)
def test_no_local_escape_helpers(page):
    src = _read(page)
    assert "function escapeHtml" not in src
    assert "function escapeAttr" not in src
    assert "escapeHtml(" not in src


@pytest.mark.parametrize("raw", ["${p.text}", "${p.why", "${c.name}", "${c.desc}",
                                 "${s.topic||", "${name}"])
def test_llm_fields_escaped_in_browse(raw):
    assert raw not in _read("index.html")  # ③ 已并入主页：step-browse.js / cliplist.js 随 index.html 一起读


def test_summary_escaped_in_browse():
    assert re.findall(r"(?<!esc)\(s\.summary \|\|", _read("index.html")) == []
    assert "esc(sum.summary" in _read("step-browse.js")


@pytest.mark.parametrize("raw", ["${p.text}", "${fmt(p.at)}", "${q.text}", "${o.label}", "${o.effect", "${s.text}",
                                 "${t.topic}", "${c.name}", "${s.name}", "${s.level_reason", "${r.job_error"])
def test_llm_fields_escaped_in_criteria(raw):
    assert raw not in _criteria_src()


@pytest.mark.parametrize("raw", ["${j.start_tc}", "${j.suggest}", "${v.name}",
                                 "${p.key}", "${s.label}", "${p.title||p.name}"])
def test_dynamic_fields_escaped_in_index(raw):
    assert raw not in _read("index.html")


# ---------------------------------------------------------------- GL-23
def test_renumber_not_position_based():
    src = _read("index.html")
    assert "'sh'+String(i+1)" not in src
    assert "function nextShotId" in src


# ---------------------------------------------------------------- M2 目标时长
def test_new_project_asks_target():
    src = _read("index.html")
    assert "durationFields('np'" in src
    create = src[src.index("async function createAndAnalyze"):]
    assert "target" in create[:create.index("\n}")]


def test_target_copy_in_named_constants():
    src = _read("index.html")
    for const in ("COPY_MUST_KEEP_OVER", "COPY_TARGET_ASK", "COPY_TARGET_BUTTON",
                  "COPY_TARGET_LATER", "COPY_TARGET_MANUAL_NOTE"):
        assert f"const {const}" in src
    assert "startJob('select'" in src
    assert 'data-act="openTarget"' in src and "openTarget: ()=>openTarget(false)" in src


def test_target_modal_uses_num_for_numbers():
    src = _read("index.html")
    body = src[src.index("function openTarget"):src.index("function saveTarget")]
    assert "num(" in body and "${sel." not in body


def _job_poll_src():
    """任务轮询与收尾在 jobs.js（M4 从 index.html 搬出）。"""
    src = _read("jobs.js")
    return src[src.index("function pollJob"):src.index("/* ---------------- 任务胶囊")]


def test_over_target_modal_opened_after_job():
    poll = _job_poll_src()
    assert "over_target" in poll and "openTarget(true)" in poll


# ---------------------------------------------------------------- M2 审查：警告条
def test_index_has_persistent_warning_bar():
    src = _read("index.html")
    assert 'id="warnbar"' in src
    refresh = src[src.index("async function refresh("):]
    assert re.search(r"renderWarnbar\(\w+\.warnings\)", refresh[:refresh.index("\n}\n")])
    bar = src[src.index("function renderWarnbar"):]
    assert "#warnbar" in bar[:bar.index("\n}\n")] and "esc(" in bar[:bar.index("\n}\n")]


def test_job_modal_stays_open_when_job_warned():
    src = _read("index.html") + _read("jobs.js")
    poll = _job_poll_src()
    assert "'[!]'" in poll and "COPY_JOB_DONE_WITH_WARNINGS" in poll
    for const in ("COPY_JOB_DONE_WITH_WARNINGS", "COPY_JOB_ACK", "COPY_WARNBAR_TITLE"):
        assert f"const {const}" in src


# ---------------------------------------------------------------- M8：KI-49 / KI-21
def _criteria_src():
    """④ 定标准由三个脚本组成（M13d）：守卫一起看。"""
    return "".join(_html(n) for n in ("step-criteria.js", "criteria-analysis.js", "criteria-pending.js"))


def test_criteria_uses_as_list_and_immutable_pick():
    src = _criteria_src()
    assert "asList(" in src and "(chosen||[]).includes" not in src
    assert ".splice(" not in src and ".push(" not in src   # KI-49：不原地改磁盘读来的数组
    assert "answers_unreadable" in src and "COPY_ANSWERS_UNREADABLE" in src
    submit = src[src.index("async function submitGate"):]
    assert "setStatus(c, e.message" in submit[:submit.index("\n}\n")]  # 409 / 404 的原因要显示出来，不只是「保存失败」


def test_index_shows_state_load_error():
    src = _read("index.html")
    body = src[src.index("async function selectProject"):]
    body = body[:body.index("\n}\n")]
    assert "refreshOrWarn(name)" in body  # 失败处理（警告栏 + toast）在 refreshOrWarn 里统一做
    assert "state.project = name" not in body  # 刷新成功后才切项目（在 refresh 里）


# ---------------------------------------------------------------- M8 补充：刷新失败 / 预设警告 / 错误 toast
def test_every_refresh_caller_reports_state_failure():
    """除了 refreshOrWarn 本身，任何地方都不直接 await refresh() / refresh().catch 吞掉错误。"""
    src = _read("index.html") + _read("jobs.js")
    assert len(re.findall(r"(?<![\w.])refresh\(", src)) == 2  # 定义 + refreshOrWarn 里唯一一次调用
    assert "refresh().catch(()=>{})" not in src
    body = src[src.index("async function refreshOrWarn"):]
    body = body[:body.index("\n}\n")]
    assert "showProjectError(" in body
    err = src[src.index("function showProjectError"):]
    err = err[:err.index("\n}\n")]
    assert "renderWarnbar(" in err and "toast(" in err and "state.project = null" in err


def test_new_project_modal_shows_preset_warnings():
    src = _read("index.html")
    body = src[src.index("async function openNew"):]
    body = body[:body.index("\n}\n")]
    assert "warnings" in body and "esc(" in body


def test_criteria_error_toast_stays_longer():
    src = _html("step-criteria.js")
    status = src[src.index("function setStatus"):]
    status = status[:status.index("\n}\n")]
    assert "TOAST_ERROR_MS" in status and "TOAST_MS_PER_CHAR" in status and "toast(" in status


# ---------------------------------------------------------------- M8 审查：浏览 / 确认页警告条，浏览页写失败回滚
def test_browse_step_shows_warnings_escaped():
    src = _read("step-browse.js")
    assert "esc(w)" in src and "b.data.warnings" in src


def test_browse_writes_roll_back_and_say_why():
    src = _read("cliplist.js")
    body = src[src.index("async function applyMark"):]
    body = body[:body.index("\n}\n")]
    assert "failMark(" in body and "err.message" in body
    fail = src[src.index("function failMark"):]
    fail = fail[:fail.index("\n}\n")]
    assert "b.confirmed.get(seg.id)" in fail and "toast(" in fail


# ---------------------------------------------------------------- KI-71 / KI-57 / KI-36
def test_index_shows_stale_job_bar():
    src = _read("index.html")
    assert 'id="stalebar"' in src and "stale_job" in src
    body = src[src.index("function renderStalebar"):]
    body = body[:body.index("\n}\n")]
    assert "esc(" in body and "COPY_STALE_TITLE" in body


def test_create_project_has_no_hash_navigation():
    src = _read("index.html")
    body = src[src.index("async function createAndAnalyze"):]
    body = body[:body.index("\n}\n")]
    assert "location.hash" not in body and "await selectProject(name)" in body


def test_no_sub_window_mechanism_in_main_page():
    src = _read("index.html")
    assert "/api/window" not in src and "window.open(" not in src and "openSubpage" not in src
    assert "onWindowFocus" not in src and "FOCUS_REFRESH" not in src


def test_criteria_page_offers_regenerate_for_stale_questions():  # KI-86
    src = _criteria_src()
    assert 'data-act="critRegen"' in src and "stale_questions" in src and "startJob('questions'" in src


@pytest.mark.parametrize("name", [n for n in JS_FILES if n != "common.js"])  # common.js 里就是那个安全包装 playQuietly
def test_video_play_rejections_are_handled(name):  # 审查修复 L10
    assert re.findall(r"\.play\(\)(?!\.catch)", _html(name)) == []


def test_new_project_duration_is_free_input_above_preset():
    src = _read("index.html")
    body = src[src.index("async function openNew"):src.index("function syncTarget")]
    assert "durationFields('np'" in body and 'id="npTarget"' not in body
    assert body.index("durationFields('np'") < body.index('id="npPreset"')  # 时长在预设上面
    assert "esc(p.duration)" not in body                                     # 下拉里不再写死时长
    create = src[src.index("async function createAndAnalyze"):]
    assert "readDuration('np')" in create[:create.index("\n}")]


def test_retarget_modal_uses_minutes_and_seconds():
    src = _read("index.html")
    body = src[src.index("function openTarget"):src.index("function saveTarget")]
    assert "durationFields('tgt'" in body and 'id="tgtInput"' not in body
    save = src[src.index("function saveTarget"):]
    assert "readDuration('tgt')" in save[:save.index("\n}")]


# ---------------------------------------------------------------- M13 Task 11：拆分后的守卫
@pytest.mark.parametrize("name", JS_FILES)
def test_static_js_files_are_focused(name):
    lines = len((STATIC / name).read_text(encoding="utf-8").splitlines())
    assert lines <= MAX_JS_LINES, f"{name} {lines} 行，超过 {MAX_JS_LINES}"


def test_static_whitelist_is_exactly_the_files_on_disk():
    from gui.static_files import STATIC_FILES
    on_disk = {p.name for p in STATIC.iterdir()
               if p.suffix in {".html", ".js", ".css"} and p.name != "prototype.html"}
    assert set(STATIC_FILES) == on_disk


def test_index_has_no_style_block_and_links_app_css():
    html = _html("index.html")
    assert "<style" not in html and 'href="/static/app.css"' in html
    assert "calibrate" not in html


def test_index_loads_scripts_in_order_with_entry_last():
    assert _scripts("index.html") == INDEX_SCRIPT_ORDER
    assert not (STATIC / "index.js").exists() and not (STATIC / "calibrate.html").exists()


def test_every_index_script_is_loaded_by_some_page():
    assert set(JS_FILES) == set(_scripts("index.html"))


def test_no_script_uses_local_storage():
    """M12 的承诺：要持久的偏好都走 /api/prefs，前端不碰 localStorage / sessionStorage。"""
    for name in JS_FILES:
        src = (STATIC / name).read_text(encoding="utf-8")
        assert "localStorage" not in src and "sessionStorage" not in src, name


def test_app_css_served_and_removed_pages_gone(gui_server):
    from conftest import call
    status, _, headers = call(gui_server, "GET", "/static/app.css", token=False)
    assert status == 200 and headers["content-type"].startswith("text/css")
    assert call(gui_server, "GET", "/static/calibrate.html", token=False)[0] == 404
    assert call(gui_server, "GET", "/static/index.js", token=False)[0] == 404


def test_criteria_gate_wrapper_does_not_reuse_the_first_run_gate_class():
    """真浏览器里发现的：.gate 是首次打开告知卡片的样式（margin: 60px auto），借用会把底部导航撑高到 179px。"""
    js, css = _html("step-criteria.js"), _html("app.css")
    assert 'class="gate"' not in js and 'class="gate-wrap"' in js
    assert re.search(r"^\.gate\{[^}]*margin:60px", css, re.M)          # 首次打开卡片确实占用着这个名字
    assert ".nav .gate-wrap{" in css
