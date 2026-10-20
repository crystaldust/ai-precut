"""M4 前端行为（node vm 里真正执行）：GL-22 选中行不重绘、任务弹窗按钮、409 分流；GL-02 设置页转义。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

# 最小 DOM 桩：按 id 记元素；结果可以是 Promise（会 await）
HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const [files, extraSrc, script] = JSON.parse(process.argv[1]);
const els = {};
function el(id){
  if(!els[id]) els[id] = {id, innerHTML:'', textContent:'', value:'', scrollTop:0, scrollHeight:0,
    classList:{_s:new Set(), add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
               contains(c){return this._s.has(c)}, toggle(c,on){on?this._s.add(c):this._s.delete(c)}}};
  return els[id];
}
const ctx = {
  URL, Headers, console, Promise, JSON, setTimeout: (fn)=>0, clearTimeout: ()=>{},
  location: {href: 'http://127.0.0.1:8765/', origin: 'http://127.0.0.1:8765'},
  document: {
    querySelector: s => s.startsWith('meta') ? {content:'T'} : el(s.replace(/^#/, '')),
    querySelectorAll: s => (ctx.__rows || []),
    addEventListener: () => {},  // common.js 的事件委托（KI-53）
  },
  fetch: () => Promise.resolve(), els, el,
};
ctx.window = ctx;
vm.createContext(ctx);
for (const f of files) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, {filename: f});
if (extraSrc) vm.runInContext(extraSrc, ctx);
Promise.resolve(vm.runInContext(script, ctx)).then(out => {
  process.stdout.write(JSON.stringify(out === undefined ? null : out));
}).catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

# 内联脚本里 jobs.js / settings.js 依赖的全局，测试里打桩并记录调用
STUBS = r"""
var calls = [];
var $ = s => document.querySelector(s);
var state = {project: 'p1', shots: [{in: 1}], data: {versions: [{name: 'v1'}]}, sel: null};
var api = (path, opt) => { calls.push(['api', path, opt && opt.body]); return window.__api(path, opt); };
var showModal = (t, h) => { calls.push(['showModal', t]); el('modalBody').innerHTML = h; el('mask').classList.add('on'); };
var closeModal = () => { calls.push(['closeModal']); el('mask').classList.remove('on'); };
var logLine = t => calls.push(['log', t]);
var toast = t => calls.push(['toast', t]);
var refresh = () => Promise.resolve();
var openTarget = () => calls.push(['openTarget']);
var renderView = () => calls.push(['renderView']);
var flushPendingSave = () => Promise.resolve(true);
"""


def run_js(script, files=(), extra=""):
    paths = [str(STATIC / "common.js"), *[str(STATIC / f) for f in files]]
    args = json.dumps([paths, STUBS + extra, script])
    r = subprocess.run([NODE, "-e", HARNESS, args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def api_rejects(status, data):
    return ("window.__api = () => Promise.reject(Object.assign(new Error(%s), {status: %d, data: %s}));"
            % (json.dumps(data.get("error", "x")), status, json.dumps(data)))


# ---------------------------------------------------------------- GL-22：字幕框可输入
def _index_fn(name):
    src = (STATIC / "result-table.js").read_text(encoding="utf-8")  # M14：分镜表视图在 result-table.js
    m = re.search(r"^function %s\(.*?\n(?=function |let |const |/\*)" % name, src, re.S | re.M)
    assert m, f"result-table.js 里找不到 {name}"
    return m.group(0)


def test_pick_only_toggles_highlight_not_rerender():
    rows = "__rows = [0,1,2].map(i => ({cls: new Set(), classList: {toggle(c, on){ on ? this._o.add(c) : this._o.delete(c); }}}));" \
           "__rows.forEach(r => r.classList._o = r.cls);"
    out = run_js(rows + "pick(1); [calls.filter(c => c[0]==='renderView').length,"
                 " __rows.map(r => r.cls.has('sel')), state.sel];",
                 extra="function seekNoSwitch(){}\n" + _index_fn("pick"))
    assert out == [0, [False, True, False], 1]


# ---------------------------------------------------------------- 任务弹窗按钮
@pytest.mark.parametrize("kind, has, lacks", [
    ("running", ["取消任务", 'data-act="cancelJob"'], ["重试"]),
    ("ended", ["重试", "关闭", 'data-act="retryJob"', 'data-act="closeModal"'], ["取消任务"]),
    ("conflict", ["查看进行中的任务", 'data-act="attachJob"', "关闭"], ["重试"]),
    ("ack", ["知道了"], ["取消任务"]),
])
def test_job_actions_html(kind, has, lacks):
    html = run_js(f"jobActionsHtml({kind!r})", files=["jobs.js"])
    for text in has:
        assert text in html
    for text in lacks:
        assert text not in html


def test_conflict_409_offers_view_running_job():
    out = run_js("startJob('build').then(() => [jobUi.id, el('jobActions').innerHTML,"
                 " calls.filter(c => c[0]==='log').map(c => c[1])]);",
                 files=["jobs.js"],
                 extra=api_rejects(409, {"error": "已有任务在运行：p2 · 处理素材", "job_id": "abc12345"}))
    job_id, actions, logs = out
    assert job_id == "abc12345" and "查看进行中的任务" in actions
    assert any("已有任务在运行" in l for l in logs)


def test_consent_409_opens_consent_then_retries():
    out = run_js("var seen = []; openConsent = f => { seen.push('consent'); };"
                 "openSettings = f => { seen.push('settings'); };"
                 "startJob('prepare').then(() => [seen, el('mask').classList.contains('on')]);",
                 files=["jobs.js"], extra=api_rejects(409, {"error": "x", "need": "consent"}))
    assert out == [["consent"], False]


def test_keys_409_opens_settings():
    out = run_js("var seen = []; openConsent = f => seen.push('consent');"
                 "openSettings = f => seen.push('settings');"
                 "startJob('prepare').then(() => seen);",
                 files=["jobs.js"],
                 extra=api_rejects(409, {"error": "缺 Key", "need": "keys", "missing": ["deepseek"]}))
    assert out == ["settings"]


def test_bad_request_offers_retry_and_close():
    out = run_js("startJob('build').then(() => el('jobActions').innerHTML);",
                 files=["jobs.js"], extra=api_rejects(400, {"error": "素材不存在"}))
    assert "重试" in out and "关闭" in out


def test_version_export_html_uses_index_not_name():
    html = run_js("versionExportHtml({name: \"v1');alert(1)//\", windows_zip: '<b>x.zip', windows_mb: 3}, 0)",
                  files=["jobs.js", "step-export.js"])
    assert 'data-act="exportVersion" data-i="0"' in html and 'data-act="revealExport" data-i="0"' in html
    assert "alert" not in html and "<b>" not in html and "&lt;b&gt;x.zip" in html


def test_export_version_posts_export_task():
    out = run_js("window.__api = () => new Promise(() => {}); exportVersion(0);"
                 "calls.filter(c => c[0]==='api').map(c => JSON.parse(c[2]));",
                 files=["jobs.js", "step-export.js"])
    assert out == [{"project": "p1", "task": "export", "version": "v1"}]


# ---------------------------------------------------------------- GL-02：设置页 / 告知
def test_settings_rows_escape_and_env_has_no_clear():
    cfg = {"providers": [
        {"key": "mediakit", "label": "<img src=x>", "hint": "h", "configured": True,
         "source": "keyring", "masked": "AKLT****9f2a"},
        {"key": "deepseek", "label": "文本分析", "hint": "h", "configured": True,
         "source": "env", "masked": "sk-d****23"},
        {"key": "bad'key", "label": "x", "hint": "h", "configured": False},
    ]}
    html = run_js(f"settingsRowsHtml({json.dumps(cfg)})", files=["settings.js"])
    assert "<img" not in html and "&lt;img src=x&gt;" in html
    assert "AKLT****9f2a" in html and "来自环境变量" in html
    assert 'data-act="deleteKey" data-provider="mediakit"' in html
    assert 'data-provider="deepseek"' in html and 'data-act="deleteKey" data-provider="deepseek"' not in html
    assert "bad'key" not in html
    assert 'type="password"' in html


def test_consent_html_names_both_data_flows():
    html = run_js("consentHtml()", files=["settings.js"])
    for text in ("16kHz", "火山引擎", "DeepSeek", "不会离开这台电脑", "钥匙串", "我知道了，继续", "暂不使用"):
        assert text in html


def test_save_key_clears_input_and_never_toasts_plaintext():
    out = run_js("el('key_deepseek').value = ' sk-secret-value ';"
                 "window.__api = (p) => Promise.resolve({consent: true, providers: [{key:'deepseek', configured:true}]});"
                 "saveKey('deepseek').then(() => [el('key_deepseek').value,"
                 " JSON.stringify(calls.filter(c => c[0]==='toast'))]);",
                 files=["settings.js"])
    assert out[0] == "" and "sk-secret-value" not in out[1]


def test_static_scripts_load_before_page_script_and_settings_entry_exists():
    src = (STATIC / "index.html").read_text(encoding="utf-8")
    page = src.index('<script src="/static/main.js"></script>')
    for name in ("common.js", "base.js", "jobs.js", "settings.js", "support.js", "app.js"):
        tag = f'<script src="/static/{name}"></script>'
        assert tag in src and src.index(tag) < page
    assert "act: 'openSettings'" in (STATIC / "wizard.js").read_text(encoding="utf-8")  # 入口在「更多」菜单
    assert "checkFirstRun()" in (STATIC / "app.js").read_text(encoding="utf-8")


def test_legacy_key_is_read_only_in_settings():
    cfg = {"providers": [{"key": "mediakit", "label": "l", "hint": "h", "configured": True,
                          "source": "legacy", "masked": "AKLT****iNzE"}]}
    html = run_js(f"settingsRowsHtml({json.dumps(cfg)})", files=["settings.js"])
    assert 'data-act="deleteKey"' not in html  # 清除删不掉旧版文件，按钮不能骗人
    assert "~/.mediakit/api_key" in html


# ---------------------------------------------------------------- 审查修复 2：HIGH-2 设置页死循环
MISSING_DS = ("window.__api = () => Promise.resolve({consent: true, providers: ["
              "{key:'mediakit', configured:true}, {key:'deepseek', configured:false}]});")


def test_settings_done_without_required_keys_closes_and_does_not_retry():
    out = run_js(MISSING_DS +
                 "var retried = 0;"
                 "openSettings(() => { retried++; }, ['deepseek'])"
                 ".then(() => finishSettings())"
                 ".then(() => [el('mask').classList.contains('on'), retried])",
                 files=["settings.js"])
    assert out == [False, 0]


def test_settings_done_with_required_keys_retries_once():
    out = run_js("window.__api = () => Promise.resolve({consent: true, providers: ["
                 "{key:'mediakit', configured:false}, {key:'deepseek', configured:true}]});"
                 "var retried = 0;"
                 "openSettings(() => { retried++; }, ['deepseek'])"
                 ".then(() => finishSettings()).then(() => retried)",
                 files=["settings.js"])
    assert out == 1  # 只缺的那个 Key 补上了就继续；没填的 mediakit 这个项目用不到


def test_settings_has_close_button_that_drops_retry():
    out = run_js(MISSING_DS +
                 "var retried = 0;"
                 "openSettings(() => { retried++; }, ['deepseek'])"
                 ".then(() => { const html = el('modalBody').innerHTML; closeSettings();"
                 " return [html.includes('data-act=\"closeSettings\"'), html.includes('关闭'),"
                 " el('mask').classList.contains('on'), retried, settingsUi.then]; })",
                 files=["settings.js"])
    assert out == [True, True, False, 0, None]


def test_keys_409_passes_missing_list_to_settings():
    out = run_js("var seen = []; openSettings = (f, req) => seen.push(req);"
                 "startJob('prepare').then(() => seen);",
                 files=["jobs.js"],
                 extra=api_rejects(409, {"error": "缺 Key", "need": "keys", "missing": ["deepseek"]}))
    assert out == [["deepseek"]]


def test_modal_closes_on_escape_and_backdrop_unless_job_running():
    src = (STATIC / "base.js").read_text(encoding="utf-8")  # M13：弹窗基础设施在 base.js
    assert "'Escape'" in src and "e.target === mask" in src
    assert "modalDismissable()" in src


def test_modal_dismissable_only_when_no_job_polling():
    out = run_js("state.modalKind = 'job'; [(jobUi.polling = 'x', modalDismissable()), (jobUi.polling = null, modalDismissable())]",
                 files=["jobs.js"])
    assert out == [False, True]


def test_other_modals_stay_dismissable_while_a_background_job_polls():  # M13：胶囊模式下任务常驻后台
    out = run_js("state.modalKind = null; jobUi.polling = 'x'; modalDismissable()", files=["jobs.js"])
    assert out is True


# ---------------------------------------------------------------- MEDIUM-4：查看别人的任务后不能「重试」它
def test_attach_job_disables_retry_of_unseen_job():
    out = run_js("window.__api = () => new Promise(() => {});"
                 "jobUi.last = {task: 'export', extra: {version: 'v1'}}; jobUi.id = 'abc';"
                 "attachJob(); setJobActions('ended'); [jobUi.last, el('jobActions').innerHTML]",
                 files=["jobs.js"])
    last, html = out
    assert last is None and "重试" not in html and "关闭" in html


def test_attach_running_job_disables_retry():
    out = run_js("window.__api = () => new Promise(() => {});"
                 "jobUi.last = {task: 'build', extra: {no_draft: true}};"
                 "attachRunningJob({id: 'j9', task: 'prepare'}); jobUi.last",
                 files=["jobs.js"])
    assert out is None


# ---------------------------------------------------------------- LOW-11 / LOW-13
def test_save_key_failure_keeps_input():
    out = run_js("el('key_deepseek').value = 'sk-keep-me-123';"
                 "window.__api = () => Promise.reject(Object.assign(new Error('保存失败'), {status: 500}));"
                 "saveKey('deepseek').then(() => el('key_deepseek').value)",
                 files=["settings.js"])
    assert out == "sk-keep-me-123"


def test_poll_error_not_reported_as_start_failure():
    out = run_js("window.__api = () => Promise.resolve({job_id: 'j1'});"
                 "pollJob = () => { throw new Error('boom'); };"
                 "startJob('build').then(() => calls.filter(c => c[0]==='log').map(c => c[1]))",
                 files=["jobs.js"])
    assert not any(l.startswith("[错误]") for l in out)
    assert any("boom" in l for l in out)


def test_settings_notes_hidden_legacy_plaintext_file():  # 审查修复 L18
    cfg = {"providers": [{"key": "mediakit", "label": "l", "hint": "h", "configured": False,
                          "source": "", "masked": "", "legacy_file": True}]}
    html = run_js(f"settingsRowsHtml({json.dumps(cfg)})", files=["settings.js"])
    assert "~/.mediakit/api_key" in html and "删除" in html
