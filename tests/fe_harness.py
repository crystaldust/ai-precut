"""向导前端的 node vm 测试夹具（M13b）：把 gui/static 里的脚本按 index.html 的顺序装进一个带最小 DOM 桩的上下文。

- 元素按选择器记（`el('#stage')`），有 innerHTML / textContent / classList / attrs / dataset / listeners；
- fetch 由测试给的 routes 回答：{"GET /api/config": {...}, "POST /api/job": [409, {...}]}，按「方法 路径」前缀匹配，
  最长的先中；值是 JSON（200）或 [状态码, JSON]；没有匹配的返回 404；所有请求记进 `calls`；
- setTimeout 不真的计时：定时器进 `timers`，测试用 `runTimers()` 手动触发；`tick()` 让出微任务队列。
"""
import json
import shutil
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "gui" / "static"
NODE = shutil.which("node")

# index.html 里的加载顺序，不含最后的 main.js（它只负责启动，测试里手动调用 boot()）
SCRIPTS = ["common.js", "base.js", "jobs.js", "settings.js", "support.js", "sidebar.js", "wizard.js",
           "shortcuts.js", "cliplist.js", "project-form.js", "step-analyze.js", "step-browse.js", "step-criteria.js",
           "criteria-analysis.js", "criteria-pending.js", "reselect.js", "result-table.js", "result-unused.js",
           "step-result.js", "step-export.js", "export-compare.js", "app.js"]

HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const [files, routes, setup, script] = JSON.parse(process.argv[1]);
const els = {}, calls = [], timers = [], intervals = [], docListeners = {}, lists = {};
function mkEl(sel, parent){
  let html = '';
  const e = {sel, parent: parent || null, textContent: '', value: '', checked: false, disabled: false, hidden: false,
    style: {}, dataset: {}, attrs: {}, listeners: {}, children: [], scrollTop: 0, scrollHeight: 0,
    classList: {_s: new Set(),
      add(...c){ c.forEach(x => this._s.add(x)); }, remove(...c){ c.forEach(x => this._s.delete(x)); },
      contains(c){ return this._s.has(c); },
      toggle(c, on){ const want = on === undefined ? !this._s.has(c) : !!on; want ? this._s.add(c) : this._s.delete(c); return want; }},
    setAttribute(k, v){ this.attrs[k] = String(v); }, getAttribute(k){ return k in this.attrs ? this.attrs[k] : null; },
    removeAttribute(k){ delete this.attrs[k]; },
    addEventListener(t, fn){ (this.listeners[t] = this.listeners[t] || []).push(fn); },
    removeEventListener(t, fn){ this.listeners[t] = (this.listeners[t] || []).filter(f => f !== fn); },
    load(){ this.loaded = (this.loaded || 0) + 1; },
    closest(q){  // 只认 [attr] 选择器：沿 parent 往上找带这个属性的元素（事件委托测试用）
      const a = q.replace(/^\[|\]$/g, ''); let n = this;
      while(n){ if(a in n.attrs) return n; n = n.parent; }
      return null;
    },
    contains(){ return false; }, focus(){}, pause(){}, play(){ return Promise.resolve(); },
    querySelector(){ return null; }, querySelectorAll(){ return []; }};
  // innerHTML 的 setter：#stage / #modalBody 整块重画时，里面的 Key 输入框会被清空（和真 DOM 一样）
  Object.defineProperty(e, 'innerHTML', {get(){ return html; }, set(v){
    html = v;
    if(sel === '#stage' || sel === '#modalBody') for(const k of Object.keys(els)) if(k.startsWith('#key_')) els[k].value = '';
  }});
  return e;
}
const el = s => els[s] || (els[s] = mkEl(s));
const respond = (method, path) => {
  const key = method + ' ' + path;
  const hit = Object.keys(routes).filter(k => key.startsWith(k)).sort((a, b) => b.length - a.length)[0];
  if (hit === undefined) return [404, {error: 'no route ' + key}];
  const v = routes[hit];
  return Array.isArray(v) && typeof v[0] === 'number' ? v : [200, v];
};
const ctx = {
  URL, URLSearchParams, Headers, console, Promise, JSON, Math, Date, Set, Map, Object, Array, Number, String, RegExp, Error, encodeURIComponent,
  els, el, calls, timers, lists, respond,
  location: {href: 'http://127.0.0.1:8765/', origin: 'http://127.0.0.1:8765', hash: '', search: ''},
  document: {
    querySelector: s => el(s), getElementById: id => el('#' + id), querySelectorAll: s => lists[s] || [],
    addEventListener(t, fn){ (docListeners[t] = docListeners[t] || []).push(fn); },
    createElement: () => mkEl('created'), body: mkEl('body'), hidden: false,
  },
  fetch: async (path, opt) => {
    const method = (opt && opt.method) || 'GET';
    const body = opt && opt.body ? JSON.parse(opt.body) : null;
    calls.push({path, method, body});
    if (ctx.__fail) throw new Error(ctx.__fail);
    const [status, data] = ctx.__respond ? ctx.__respond(method, path, body) : respond(method, path);
    return {ok: status < 400, status, json: async () => data};
  },
  setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
  clearTimeout: id => { if (id && timers[id - 1]) timers[id - 1].fn = null; },
  setInterval: (fn, ms) => { intervals.push({fn, ms, cleared: false}); return intervals.length; },
  clearInterval: id => { if (id && intervals[id - 1]) intervals[id - 1].cleared = true; },
  intervals,
  // 造一个带属性的节点（可挂 parent），属性里的 data-* 同步进 dataset：node({'data-act': 'go', 'data-step': 'browse'}, parent)
  node: (attrs, parent) => { const n = mkEl('node', parent); n.attrs = Object.assign({}, attrs);
    for (const [k, v] of Object.entries(attrs)) if (k.startsWith('data-')) n.dataset[k.slice(5)] = v; return n; },
  click: target => (docListeners.click || []).forEach(fn => fn({type: 'click', target})),
  tick: () => new Promise(r => setImmediate(r)),
  runTimers: async () => {
    const due = timers.splice(0);
    for (const t of due) if (t.fn) await t.fn();
    await new Promise(r => setImmediate(r));
  },
  docListeners,
  act: (name, dataset = {}, extra = {}) => ctx.ACTIONS[name](
    Object.assign(mkEl('act'), {dataset, getAttribute: k => dataset[k.replace(/^data-/, '')]}, extra), {preventDefault(){}}),
  fire: (sel, type, ev = {}) => (el(sel).listeners[type] || []).forEach(fn => fn(Object.assign({target: el(sel)}, ev))),
  fireDoc: (type, ev = {}) => (docListeners[type] || []).forEach(fn => fn(ev)),
};
ctx.window = ctx;
vm.createContext(ctx);
for (const f of files) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, {filename: f});
if (setup) vm.runInContext(setup, ctx);
Promise.resolve(vm.runInContext(script, ctx)).then(out => {
  process.stdout.write(JSON.stringify(out === undefined ? null : out));
}).catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def run_app(script, routes=None, setup="", files=None):
    paths = [str(STATIC / f) for f in (files if files is not None else SCRIPTS)]
    args = json.dumps([paths, routes or {}, setup, script])
    r = subprocess.run([NODE, "-e", HARNESS, args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def wizard(**status):
    """造一份 wizard 载荷：steps 默认 ①② 完成、其余未到；status 里 {key: (status, hint/banner, action)} 覆盖。"""
    labels = [("new", 1, "新建"), ("analyze", 2, "分析"), ("browse", 3, "看素材"),
              ("criteria", 4, "定标准"), ("result", 5, "看结果"), ("export", 6, "导出")]
    base = {"new": "done", "analyze": "done", "browse": "available", "criteria": "available",
            "result": "locked", "export": "locked"}
    steps = []
    for key, n, label in labels:
        spec = status.get(key, base[key])
        st, text, action = spec if isinstance(spec, tuple) else (spec, None, None)
        steps.append({"key": key, "n": n, "label": label, "status": st,
                      "hint": text if st == "locked" else None,
                      "banner": text if st != "locked" else None,
                      "action": action, "reasons": []})
    return {"steps": steps, "next": "criteria", "legacy": False}
