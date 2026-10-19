"""GL-05 / GL-07 / GL-23 前端静态守卫：纯文本检查页面源码。"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"
PAGES = ["index.html", "browse.html", "confirm.html", "calibrate.html"]
XSS_PAGES = ["index.html", "browse.html", "confirm.html"]
TOKEN_META = '<meta name="aicut-token" content="__AICUT_TOKEN__">'
COMMON_JS = '<script src="/static/common.js"></script>'


def _read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def _first_inline_script(src):
    m = re.search(r"<script>", src)
    assert m, "页面应该有内联脚本"
    return m.start()


# ---------------------------------------------------------------- GL-05
@pytest.mark.parametrize("page", PAGES)
def test_pages_have_token_meta_and_common_js(page):
    src = _read(page)
    assert TOKEN_META in src
    assert COMMON_JS in src
    first = _first_inline_script(src)
    assert src.index(TOKEN_META) < src.index(COMMON_JS) < first


def test_common_js_escapes_quote():
    js = _read("common.js")
    assert "window.esc" in js
    assert "&#39;" in js
    assert "X-AICUT-Token" in js


def test_pick_sends_json():
    assert "api('/api/pick', {method:'POST'})" not in _read("index.html")


# ---------------------------------------------------------------- GL-07
@pytest.mark.parametrize("page", XSS_PAGES)
def test_no_string_interpolation_in_inline_handlers(page):
    hits = re.findall(r"""on\w+="[^"]*'\$\{""", _read(page))
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
    assert raw not in _read("browse.html")


def test_summary_escaped_in_browse():
    assert re.findall(r"(?<!esc)\(s\.summary \|\|", _read("browse.html")) == []


@pytest.mark.parametrize("raw", ["${p.text}", "${fmt(p.at)}"])
def test_llm_fields_escaped_in_confirm(raw):
    assert raw not in _read("confirm.html")


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
    assert 'id="npTarget"' in src
    create = src[src.index("async function createProject"):]
    assert "target" in create[:create.index("\n}")]


def test_target_copy_in_named_constants():
    src = _read("index.html")
    for const in ("COPY_MUST_KEEP_OVER", "COPY_TARGET_ASK", "COPY_TARGET_BUTTON",
                  "COPY_TARGET_LATER", "COPY_TARGET_MANUAL_NOTE"):
        assert f"const {const}" in src
    assert "startJob('select'" in src
    assert 'onclick="openTarget(false)"' in src


def test_target_modal_uses_num_for_numbers():
    src = _read("index.html")
    body = src[src.index("function openTarget"):src.index("function saveTarget")]
    assert "num(" in body and "${sel." not in body


def _job_poll_src():
    """任务轮询与收尾在 jobs.js（M4 从 index.html 搬出）。"""
    src = _read("jobs.js")
    return src[src.index("function pollJob"):src.index("/* ---------------- 版本卡片")]


def test_over_target_modal_opened_after_job():
    poll = _job_poll_src()
    assert "over_target" in poll and "openTarget(true)" in poll


# ---------------------------------------------------------------- M2 审查：警告条
def test_index_has_persistent_warning_bar():
    src = _read("index.html")
    assert 'id="warnbar"' in src
    body = src[src.index("async function refresh"):src.index("/* ---------------- Tab")]
    assert "warnbar" in body and "esc(" in body


def test_job_modal_stays_open_when_job_warned():
    src = _read("index.html") + _read("jobs.js")
    poll = _job_poll_src()
    assert "'[!]'" in poll and "COPY_JOB_DONE_WITH_WARNINGS" in poll
    for const in ("COPY_JOB_DONE_WITH_WARNINGS", "COPY_JOB_ACK", "COPY_WARNBAR_TITLE"):
        assert f"const {const}" in src
