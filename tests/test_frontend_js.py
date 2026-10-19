"""前端行为测试：在 node 的 vm 里真正执行 common.js 与 index.html 的镜头编号函数。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

# 在一个隔离的 vm 上下文里加载 common.js，并打桩 window / document / location / fetch
HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const [commonPath, extraSrc, script] = JSON.parse(process.argv[1]);
const calls = [];
const ctx = {
  URL, Headers, console,
  location: {href: 'http://127.0.0.1:8765/', origin: 'http://127.0.0.1:8765'},
  document: {querySelector: () => ({content: 'TOKEN123'})},
  fetch: (input, init) => { calls.push({input, init}); return Promise.resolve(); },
  calls,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(commonPath, 'utf8'), ctx);
if (extraSrc) vm.runInContext(extraSrc, ctx);
const out = vm.runInContext(script, ctx);
process.stdout.write(JSON.stringify(out === undefined ? null : out));
"""


def run_js(script: str, extra_src: str = ""):
    args = json.dumps([str(STATIC / "common.js"), extra_src, script])
    r = subprocess.run([NODE, "-e", HARNESS, args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---------------------------------------------------------------- esc / num
@pytest.mark.parametrize("raw,expected", [
    ("<img src=x onerror=alert(1)>", "&lt;img src=x onerror=alert(1)&gt;"),
    ("a\"b'c&d", "a&quot;b&#39;c&amp;d"),
    (None, ""),
    (3, "3"),
])
def test_esc(raw, expected):
    assert run_js(f"esc({json.dumps(raw)})") == expected


def test_esc_undefined_is_empty():
    assert run_js("esc(undefined)") == ""


@pytest.mark.parametrize("raw,expected", [
    ("2.5", 2.5), (7, 7), ("1);alert(1)//", 0), (None, 0), ("Infinity", 0), ([], 0),
])
def test_num(raw, expected):
    assert run_js(f"num({json.dumps(raw)})") == expected


# ---------------------------------------------------------------- fetch 补丁
def test_fetch_adds_token_to_same_origin_api_and_keeps_headers():
    out = run_js("""
      fetch('/api/x', {method:'POST', headers:{'Content-Type':'application/json'}});
      const h = calls[0].init.headers;
      [h.get('X-AICUT-Token'), h.get('Content-Type'), calls[0].init.method];
    """)
    assert out == ["TOKEN123", "application/json", "POST"]


def test_fetch_absolute_same_origin_api_gets_token():
    out = run_js("""
      fetch('http://127.0.0.1:8765/api/state');
      calls[0].init.headers.get('X-AICUT-Token');
    """)
    assert out == "TOKEN123"


@pytest.mark.parametrize("url", ["/media/p/proxy", "/static/browse.html",
                                 "http://evil.example/api/x"])
def test_fetch_does_not_leak_token(url):
    out = run_js(f"fetch({json.dumps(url)}); calls[0].init === undefined;")
    assert out is True


# ---------------------------------------------------------------- renumber / nextShotId
def _shot_id_src() -> str:
    src = (STATIC / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const SHOT_ID_RE[\s\S]*?\nfunction renumber\(\)\{[\s\S]*?\n\}\n", src)
    assert m, "index.html 里找不到 SHOT_ID_RE / nextShotId / renumber"
    return "var state = {shots: []};\n" + m.group(0).replace("const SHOT_ID_RE", "var SHOT_ID_RE")


def _renumber(ids):
    script = (f"state.shots = {json.dumps([{'id': i} for i in ids])};"
              "renumber(); state.shots.map(s => s.id);")
    return run_js(script, _shot_id_src())


def test_renumber_after_delete_uses_max_plus_one():
    assert _renumber(["sh01", "sh03", ""]) == ["sh01", "sh03", "sh04"]


def test_renumber_fixes_duplicates_and_bad_ids():
    assert _renumber(["sh01", "sh03", "sh03", "../x", "sel02", None]) == \
        ["sh01", "sh03", "sh04", "sh05", "sel02", "sh06"]


def test_renumber_empty_list_starts_at_sh01():
    assert _renumber(["", ""]) == ["sh01", "sh02"]


def test_next_shot_id_ignores_sel_ids():
    out = run_js("state.shots = [{id:'sel09'}, {id:'sh02'}]; nextShotId();", _shot_id_src())
    assert out == "sh03"


# ---------------------------------------------------------------- KI-49：asList
@pytest.mark.parametrize("raw,expected", [
    (["a"], ["a"]), ("a", ["a"]), (None, []), ({}, []), (3, []), ("", []),
])
def test_as_list(raw, expected):
    assert run_js(f"asList({json.dumps(raw)})") == expected


# ---------------------------------------------------------------- M8 审查 HIGH：切到坏项目后不能留着旧项目的数据
ASYNC_HARNESS = r"""
const vm = require('vm');
const [src, script] = JSON.parse(process.argv[1]);
const els = {};
const el = id => els[id] || (els[id] = {id, style: {}, textContent: '', innerHTML: '', classList: {add(){}, remove(){}, toggle(){}}});
const ctx = {console, els, posts: [], toasts: [], warnbars: [], stateResp: null, stateErr: null};
ctx.$ = s => el(s);
ctx.document = {querySelectorAll: () => []};
ctx.toast = (m) => ctx.toasts.push(m);
ctx.renderWarnbar = (l) => ctx.warnbars.push(l);
ctx.renderTab = () => {}; ctx.attachRunningJob = () => {}; ctx.renumber = () => {};
ctx.fmtLong = String; ctx.num = Number; ctx.esc = String; ctx.TOAST_ERROR_MS = 6000;
ctx.api = async (path, opt) => {
  if (path.startsWith('/api/state')) { if (ctx.stateErr) throw new Error(ctx.stateErr); return ctx.stateResp; }
  ctx.posts.push(path); return {};
};
ctx.setTimeout = setTimeout; ctx.clearTimeout = clearTimeout;
vm.createContext(ctx);
vm.runInContext(src, ctx);
Promise.resolve(vm.runInContext(script, ctx)).then(out =>
  process.stdout.write(JSON.stringify(out === undefined ? null : out)));
"""


def _project_switch_src() -> str:
    src = (STATIC / "index.html").read_text(encoding="utf-8")
    parts = ["var state = { project:null, data:null, tab:'preview', sel:null, shots:[], dirty:false };",
             "var saveTimer = null;"]
    for name in ("selectProject", "flushPendingSave", "refreshOrWarn", "showProjectError", "refresh",
                 "saveShots", "scheduleSave"):
        m = re.search(r"(async )?function " + name + r"\([^)]*\)\{[\s\S]*?\n\}\n", src)
        assert m, name
        parts.append(m.group(0))
    return "\n".join(parts)


def run_async(script):
    args = json.dumps([_project_switch_src(), script])
    r = subprocess.run([NODE, "-e", ASYNC_HARNESS, args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


GOOD_STATE = "{project:{name:'A', title:'A'}, stages:[], shots:[{id:'sh01'}], warnings:[]}"


def test_switch_to_corrupt_project_clears_previous_project():
    out = run_async(f"""(async () => {{
      stateResp = {GOOD_STATE};
      await selectProject('A');
      stateErr = 'project.json 损坏'; 
      await selectProject('B');
      return [state.project, state.data, state.shots.length, els['#actions'].style.display,
              els['#tabs'].style.display, els['#title'].textContent, toasts, warnbars.at(-1)];
    }})()""")
    assert out == [None, None, 0, "none", "none", "B", ["project.json 损坏"], ["project.json 损坏"]]


def test_pending_shot_save_goes_to_original_project_and_no_save_after_failure():
    out = run_async(f"""(async () => {{
      stateResp = {GOOD_STATE};
      await selectProject('A');
      scheduleSave();                 // A 的分镜表改动还没落盘
      stateErr = 'project.json 损坏';
      await selectProject('B');
      const ok = await saveShots(true);  // 失败后的保存不能发出去
      return [posts, ok];
    }})()""")
    assert out == [["/api/shots?project=A"], False]
