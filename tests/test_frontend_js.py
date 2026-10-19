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
