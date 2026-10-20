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
  document: {querySelector: () => ({content: 'TOKEN123'}), addEventListener: () => {}},
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
def test_fetch_api_sends_same_origin_credentials_not_token():
    out = run_js("""
      fetch('/api/x', {method:'POST', headers:{'Content-Type':'application/json'}});
      const i = calls[0].init;
      [i.credentials, i.headers['Content-Type'], i.method, JSON.stringify(i).includes('AICUT')];
    """)
    assert out == ["same-origin", "application/json", "POST", False]


def test_fetch_absolute_same_origin_api_gets_credentials():
    out = run_js("""
      fetch('http://127.0.0.1:8765/api/state');
      calls[0].init.credentials;
    """)
    assert out == "same-origin"


@pytest.mark.parametrize("url", ["/media/p/proxy", "/static/browse.html",
                                 "http://evil.example/api/x"])
def test_fetch_non_api_untouched(url):
    out = run_js(f"fetch({json.dumps(url)}); calls[0].init === undefined;")
    assert out is True


# ---------------------------------------------------------------- renumber / nextShotId
def _shot_id_src() -> str:
    src = (STATIC / "index.js").read_text(encoding="utf-8")  # KI-53：脚本外置
    m = re.search(r"const SHOT_ID_RE[\s\S]*?\nfunction renumber\(\)\{[\s\S]*?\n\}\n", src)
    assert m, "index.js 里找不到 SHOT_ID_RE / nextShotId / renumber"
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
    src = (STATIC / "index.js").read_text(encoding="utf-8")  # KI-53：脚本外置
    parts = ["var state = { project:null, data:null, tab:'preview', sel:null, shots:[], dirty:false };",
             "var saveTimer = null; var stateSeq = 0; var usageText = () => '';",
             "var COPY_SAVE_FAILED = '保存失败：';",
             "var saveQ = {chain: Promise.resolve(true), queued: null};"]
    for name in ("selectProject", "flushPendingSave", "refreshOrWarn", "showProjectError", "refresh",
                 "saveShots", "postShots", "scheduleSave"):
        m = re.search(r"(async )?function " + name + r"\([^)]*\)\{[\s\S]*?\n\}\n", src)
        assert m, name
        parts.append(m.group(0))
    return "\n".join(parts)


def run_async(script, extra_src=""):
    args = json.dumps([_project_switch_src() + "\n" + extra_src, script])
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


# ---------------------------------------------------------------- KI-50 / KI-35：保存串行、切项目竞态、生成前先存
TICK = "await new Promise(r => setTimeout(r, 0));"


def test_saves_are_serialized_and_last_state_wins():
    out = run_async(f"""(async () => {{
      stateResp = {GOOD_STATE};
      await selectProject('A');
      let inflight = 0, maxInflight = 0; const bodies = [], done = [];
      api = (path, opt) => {{
        inflight++; maxInflight = Math.max(maxInflight, inflight);
        bodies.push(JSON.parse(opt.body).shots.map(s => s.sub));
        return new Promise(res => done.push(() => {{ inflight--; res({{}}); }}));
      }};
      state.shots[0].sub = 'v1'; saveShots(true);
      {TICK}
      state.shots[0].sub = 'v2'; saveShots(true);
      state.shots[0].sub = 'v3'; const last = saveShots(true);
      {TICK}
      const during = bodies.length;
      done.shift()(); {TICK} {TICK}
      done.shift()(); const ok = await last;
      return [maxInflight, during, bodies, ok];
    }})()""")
    assert out == [1, 1, [["v1"], ["v3"]], True]


def test_stale_state_response_is_dropped():
    out = run_async("""(async () => {
      let releaseA;
      api = (path) => path.includes('project=A')
        ? new Promise(r => { releaseA = () => r({project:{name:'A', title:'A'}, stages:[], shots:[], warnings:[]}); })
        : Promise.resolve({project:{name:'B', title:'B'}, stages:[], shots:[], warnings:[]});
      const a = selectProject('A');
      const b = selectProject('B');
      await b;
      releaseA(); const aResult = await a;
      return [state.project, state.data.project.name, els['#title'].textContent, aResult === undefined];
    })()""")
    assert out == ["B", "B", "B", True]


def test_stale_state_error_is_not_reported():
    out = run_async("""(async () => {
      let failA;
      api = (path) => path.includes('project=A')
        ? new Promise((_, rej) => { failA = () => rej(new Error('A 损坏')); })
        : Promise.resolve({project:{name:'B', title:'B'}, stages:[], shots:[], warnings:[]});
      const a = selectProject('A');
      await selectProject('B');
      failA(); await a;
      return [state.project, toasts];
    })()""")
    assert out == ["B", []]


def _build_src():
    jobs = (STATIC / "jobs.js").read_text(encoding="utf-8")
    m = re.search(r"async function startJob\([^)]*\)\{[\s\S]*?\n\}\n", jobs)
    assert m, "jobs.js 里找不到 startJob"
    stubs = ("var jobUi = {last: null, id: null, polling: null}; var COPY_JOB_SAVE_FIRST = 'save first';"
             "var jobModal = () => {}; var setJobActions = () => {}; var pollJob = () => {};"
             "var onJobStartError = () => {};")
    return stubs + "\n" + m.group(0)


def test_build_flushes_pending_save_first():
    out = run_async(f"""(async () => {{
      stateResp = {GOOD_STATE};
      await selectProject('A');
      vm_eval(BUILD_SRC);
      state.shots[0].sub = '改过的字幕'; scheduleSave();   // 防抖中的保存还没发
      await startJob('build');
      return posts;
    }})()""".replace("vm_eval(BUILD_SRC);", ""), extra_src=_build_src())
    assert out == ["/api/shots?project=A", "/api/job"]


def test_build_stops_when_save_fails():
    out = run_async(f"""(async () => {{
      stateResp = {GOOD_STATE};
      await selectProject('A');
      api = async (path) => {{ posts.push(path); if (path.startsWith('/api/shots')) throw new Error('409'); return {{}}; }};
      scheduleSave();
      await startJob('build');
      return [posts, toasts.at(-1)];
    }})()""", extra_src=_build_src())
    assert out == [["/api/shots?project=A"], "save first"]


# ---------------------------------------------------------------- KI-53：事件委托只认最内层
def test_action_dispatch_uses_innermost_target():
    out = run_js("""
      const hits = [];
      ACTIONS.pick = el => hits.push('pick:' + el.getAttribute('data-i'));
      ACTIONS.move = (el, ev) => hits.push('move:' + el.getAttribute('data-i') + ':' + ev.type);
      const mk = (attrs, parent) => ({attrs, parent, getAttribute(a){ return this.attrs[a]; },
        closest(sel){ const a = sel.slice(1, -1); let n = this; while (n && !(a in n.attrs)) n = n.parent; return n || null; }});
      const row = mk({'data-act': 'pick', 'data-i': '2'}, null);
      const btn = mk({'data-act': 'move', 'data-i': '2'}, row);
      const text = mk({}, row);
      dispatchAction('data-act', {type: 'click', target: btn});
      dispatchAction('data-act', {type: 'click', target: text});
      dispatchAction('data-act', {type: 'click', target: mk({'data-act': 'constructor'}, null)});
      dispatchAction('data-act', {type: 'click', target: mk({}, null)});
      dispatchAction('data-act', {type: 'click', target: null});
      hits;
    """)
    assert out == ["move:2:click", "pick:2"]


# ---------------------------------------------------------------- 目标时长：分 + 秒自由填写，不受预设限制
DURATION_HARNESS = r"""
const vm = require('vm');
const [src, script] = JSON.parse(process.argv[1]);
const els = {};
const ctx = {console, els, state: {presets: []}};
ctx.$ = s => els[s] || null;
ctx.num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
ctx.esc = String;
vm.createContext(ctx);
vm.runInContext(src, ctx);
process.stdout.write(JSON.stringify(vm.runInContext(script, ctx)));
"""


def _duration_src() -> str:
    src = (STATIC / "index.js").read_text(encoding="utf-8")
    parts = [m.group(0) for m in re.finditer(r"const (TARGET_MIN_SEC|TARGET_MAX_SEC)\b.*\n", src)]
    for name in ("durationFields", "readDuration", "syncTarget", "markTargetTouched"):
        m = re.search(r"function " + name + r"\([^)]*\)\{[\s\S]*?\n\}\n", src)
        assert m, name
        parts.append(m.group(0))
    return "\n".join(parts).replace("const ", "var ")


def run_duration(script: str):
    args = json.dumps([_duration_src(), script])
    r = subprocess.run([NODE, "-e", DURATION_HARNESS, args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("mins,secs,expected", [
    ("5", "30", 330), ("10", "", 600), ("", "45", 45), ("60", "0", 3600), ("3", "0", 180),
    ("60", "1", 0), ("0", "5", 0), ("1", "60", 0), ("-1", "30", 0), ("1.5", "0", 0), ("", "", 0), ("abc", "0", 0),
])
def test_read_duration_accepts_any_minutes_and_seconds(mins, secs, expected):
    out = run_duration(f"els['#tMin'] = {{value: {json.dumps(mins)}}}; els['#tSec'] = {{value: {json.dumps(secs)}}};"
                       "readDuration('t')")
    assert out == expected


def test_duration_fields_split_seconds_into_minutes_and_seconds():
    html = run_duration("durationFields('np', 330)")
    assert 'id="npMin"' in html and 'value="5"' in html
    assert 'id="npSec"' in html and 'value="30"' in html


def test_switching_preset_keeps_hand_typed_duration():
    out = run_duration("""
      state.presets = [{key:'a', duration:175}, {key:'b', duration:45}];
      els['#npPreset'] = {value:'a'}; els['#npMin'] = {value:''}; els['#npSec'] = {value:''};
      syncTarget();
      const first = [els['#npMin'].value, els['#npSec'].value];
      els['#npMin'].value = '8'; els['#npSec'].value = '0'; markTargetTouched();
      els['#npPreset'].value = 'b'; syncTarget();
      [first, [els['#npMin'].value, els['#npSec'].value]];
    """)
    assert out == [["2", "55"], ["8", "0"]]
