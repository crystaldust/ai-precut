# Plan: 里程碑 1 · 本地服务安全，编辑不丢

## Summary
加固剪辑台本地服务 `gui/server.py` 与它调用的 `aicut.py`：所有请求校验 Host，`/api/*` 要求每次启动随机生成、注入到页面里的 token，POST 另外校验 Origin 和 Content-Type（GL-05）；对 project / version / 镜头 id / preset 做白名单校验（GL-06）；前端所有动态内容统一转义，内联事件只传数字下标（GL-07）；JSON 改为唯一临时文件的原子写，坏请求体和损坏的 `overrides.json` 不再覆盖已有数据（GL-18）；`/media/` 路由先 percent-decode 再取项目名（GL-21）；镜头 id 前后端都保证唯一（GL-23）。全程 TDD：先写会失败的回归测试，再改代码。

## User Story
作为在 Mac 上用剪辑台的剪辑师，我希望随便打开的网页都调不动、读不到我的剪辑台，我的分镜和人工裁决也不会因为并发保存或坏请求被清空，同时中文名的项目能正常播放，这样我可以放心把真实素材交给它。

## Problem → Solution
- 现状：服务只靠「监听 127.0.0.1」防护；任何网页都能 POST `/api/job` 启动任务，DNS rebinding 能读出全部数据；`version`、镜头 `id` 可以做路径穿越；LLM 和转写文本直接进 `innerHTML`；`.tmp` 文件名固定导致并发保存失败；请求体解析失败被当成 `{}`，分镜被清空；`overrides.json` 一损坏就被当空，下一次裁决把它永久覆盖；中文项目名的视频全部 404；删一个镜头再加一个会出现重复 id，切片互相覆盖。
- 目标：Host 白名单 + token + Origin + Content-Type 四道校验；路径参数全部走白名单正则；前端统一用 `esc()` 转义；原子写使用唯一临时文件，读改写加锁；坏请求返回 400 且不落盘；损坏的裁决文件直接报错，不覆盖；媒体路由先解码；镜头 id 唯一，前后端都校验。

## Metadata
- **Complexity**: Large（文件数 10 个以上，但都沿用现有模式，新增代码约 400–500 行，其中一半是测试）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 1「本地服务安全，编辑不丢」(GL-05 GL-06 GL-07 GL-18 GL-21 GL-23)
- **Estimated Files**: 16（UPDATE 10，CREATE 6）

---

## UX Design

### Before
```
┌──────────────────────────────────────────────────────────┐
│ 剪辑台（pywebview / 浏览器，http://127.0.0.1:8765/）       │
│ · 恶意网页 fetch('http://127.0.0.1:8765/api/job',…) → 成功  │
│ · 项目「九月 一号」→ 预览/版本视频黑屏（/media 404）         │
│ · 删镜头 sh02 后再加一镜 → 新镜头也叫 sh03 → 成片重复        │
│ · LLM 摘要里含 <img onerror> → 在剪辑台里执行               │
│ · 两个页面同时保存 → 「保存失败」toast / 分镜被清空           │
└──────────────────────────────────────────────────────────┘
```

### After
```
┌──────────────────────────────────────────────────────────┐
│ 剪辑台（同一个 URL，用户无感）                               │
│ · 页面带 <meta name="aicut-token">，common.js 自动加请求头   │
│ · 外部网页 / 外部 Host → 403；不是 JSON 的 POST → 415        │
│ · 中文/空格项目名视频正常播放、能拖进度条                     │
│ · 镜头 id 永远唯一；服务端拒绝重复 id（400，给出原因）         │
│ · 所有 AI/转写文本以纯文本显示                               │
│ · 并发保存全部成功；坏请求 → 400，已有文件不动                 │
│ · overrides.json 损坏 → 明确报错（带文件路径），不覆盖         │
│ · 浏览器模式下服务重启后，旧标签页提示「页面已过期，请刷新」     │
└──────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 打开剪辑台（pywebview / `--open`） | 静态 HTML | HTML 由服务端注入 token | 用户无感 |
| 浏览器模式的旧标签页（服务已重启） | 照常可用 | API 返回 403「页面已过期，请刷新」 | 文案需确认，见 Notes |
| 新建项目时项目名以 `-`/`.` 开头、含控制字符、超过 100 字 | 能创建（或让 argparse 出错） | 400 + 原因 | 中文和空格仍然允许 |
| 浏览素材页（overrides 损坏） | 静默当空 | 页面显示错误和文件路径 | 见 Notes 决策 1 |
| 分镜表删除后新增 | id 可能重复 | 取现有最大编号 +1 | 已有重复 id 的旧项目，打开后保存会自动修正 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `gui/server.py` | 74-98, 298-331, 379-486, 488-622, 625-638 | 本次主要修改对象：工具函数、Handler、全部路由、启动 |
| P0 | `pipeline/review.py` | 1-67 | GL-18：load 吞掉损坏，读改写没有加锁 |
| P0 | `gui/static/index.html` | 162-167, 180-191, 375-409, 412-432, 487-508 | api() 封装、XSS 点、镜头 id 重排 |
| P0 | `gui/static/browse.html` | 96-213 | XSS 点最多的页面 |
| P0 | `gui/static/confirm.html` | 62-120 | 内联 JS 拼接 `escapeAttr` |
| P1 | `aicut.py` | 48-86, 423-455, 527-546, 725-736 | die/save_json/project_dir、ensure_clips、cmd_build、run_cli |
| P1 | `pipeline/schema.py` | 1-101 | 新增 write_json 和校验函数的位置；save 的原子写 |
| P1 | `app/main.py` | 21-38 | 桌面壳如何加载 URL，token 方案必须兼容 |
| P1 | `gui/static/calibrate.html` | 62-104 | 页面里有 fetch，需要 token |
| P2 | `pipeline/select.py` | 375-392 | 调用 `review.load`，损坏时改为抛错 |
| P2 | `tests/test_review.py`, `tests/test_proc.py`, `tests/test_schema.py` | all | 测试写法 |
| P2 | `docs/go-live-blockers.md` | 13-31 | 关闭条目时把状态改为提交号 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| http.client 自定义 Host | Python 文档 `http.client.HTTPConnection.request` | headers 里带了 `Host`，就不会再自动加，所以能伪造外部 Host 来测 DNS rebinding |
| CORP | MDN `Cross-Origin-Resource-Policy` | `same-origin` 会阻止跨站 `<video src>` 这类 no-cors 加载；它对顶层导航无效，不影响 pywebview 打开页面 |
| Origin 头 | Fetch 规范 | 同源 GET 一般不带 Origin，同源 POST 会带（WebKit/Chromium 都是）；Origin 缺失时只能放行（靠 token 兜底），值为 `"null"` 时拒绝 |
| DNS rebinding | 通用知识 | 被 rebind 的请求，Host 头是攻击者的域名，所以只要用 Host 白名单就能挡住 |

KEY_INSIGHT: 浏览器跨源 POST 能发出去，只是读不到响应。所以必须用 token（自定义请求头会触发 CORS 预检，本服务不实现 OPTIONS，预检自然失败）。
APPLIES_TO: Task 5
GOTCHA: `<video src>` 没法带自定义请求头，所以 `/media/*` 不要求 token，只校验 Host，并加上 CORP 头。

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: gui/server.py:66-70
AICUT = ROOT / "aicut.py"
PY = sys.executable

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
```
模块级常量用大写，锁命名为 `<名>_LOCK`，函数用 snake_case，给用户看的消息一律中文。

### ERROR_HANDLING（server：统一 `{"error": msg}` + 状态码）
```python
# SOURCE: gui/server.py:432-439
        if p == "/api/browse":
            name = q.get("project", [""])[0]
            try:
                return self._json(browse_payload(name))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except (ValueError, OSError) as exc:
                return self._json({"error": str(exc)}, 400)
```
```python
# SOURCE: gui/server.py:95-98 —— 校验函数抛 ValueError，由路由转成 400
def safe_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("项目名不能用斜杠或点")
    return name
```

### ERROR_HANDLING（aicut：die 打印后 exit 1）
```python
# SOURCE: aicut.py:48-50
def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)
```

### LOGGING_PATTERN
```python
# SOURCE: gui/server.py:302-303 —— 服务端没有 logging，访问日志被静音
    def log_message(self, fmt, *args):  # 静音访问日志
        pass
# SOURCE: aicut.py:53-58 —— CLI 用 info()/ok() 打印
```
本里程碑**不加** logging（日志落盘属于 GL-19）。错误只通过 `{"error": ...}` 返回给前端。

### REPOSITORY_PATTERN（原子写，现状，有 bug）
```python
# SOURCE: gui/server.py:81-85（aicut.py:71-75、pipeline/schema.py:96-100 是同一写法；review.py:32-37 更糟，用 .tmp 替换后缀）
def jdump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
```

### SERVICE_PATTERN（读改写，现状，没有锁）
```python
# SOURCE: pipeline/review.py:23-48
def load(workdir: Path) -> dict:
    path = _path(workdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
...
def set_level(workdir: Path, segment_id: str, level: int) -> dict:
    if level not in LEVELS:
        raise ValueError(f"非法档位：{level}")
    data = load(workdir)
    item = data.setdefault(segment_id, {})
    ...
    _save(workdir, data)
```

### 前端 API 调用（token 注入的落点）
```js
// SOURCE: gui/static/index.html:162-167 —— index 页的所有 API 调用都走 api()
async function api(path, opt){
  const r = await fetch(path, opt);
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(j.error || ('请求失败 '+r.status));
  return j;
}
// SOURCE: gui/static/browse.html:105, 203, 210；confirm.html:67, 112；calibrate.html:65, 83 —— 其它页面直接用 fetch
await fetch('/api/browse/level', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({project:PROJECT, id, level})});
// SOURCE: gui/static/index.html:504 —— 唯一不带 Content-Type 的 POST
  const {path} = await api('/api/pick', {method:'POST'});
// SOURCE: gui/static/index.html:230, 262, 430；browse.html:110 —— <video src> 没法带请求头
  const src = `/media/${encodeURIComponent(state.project)}/proxy`;
```

### 前端 XSS 现状（要改的写法）
```js
// SOURCE: gui/static/browse.html:151-158 —— 字符串拼进内联 JS，topic/level_reason 拼进属性
  return `<div class="row" data-id="${s.id}" onclick="jump(${s.start},'${s.id}',${s.end})">
    <div class="cat" title="${s.topic||''}">${s.topic||'—'}</div>
    <div class="lv lv${s.level}" title="${(s.level_reason||'').replace(/"/g,'')}">${LV[s.level]}</div>
    ...
    <button class="star ${s.must_keep?'on':''}" onclick="event.stopPropagation();toggleMust('${s.id}')">★</button>
// SOURCE: gui/static/browse.html:118-125 —— LLM 摘要/要点/角色直接 innerHTML；p.at 来自 LLM，可能是字符串
  document.getElementById('summary').innerHTML = (s.summary || '（暂无摘要）') + ...
    `<div class="kp" onclick="jump(${p.at}, null, ${p.at+4})"><b>${fmt(p.at)}</b>${p.text}
// SOURCE: gui/static/confirm.html:92, 99 —— escapeAttr 不处理 \ 和 &，HTML 实体会先解码再进 JS
  onclick="pick('${q.id}','${q.type}','${escapeAttr(o.label)}')"
function escapeAttr(t){ return String(t||'').replace(/'/g,"\\'").replace(/"/g,'&quot;'); }
// SOURCE: gui/static/index.html:325（browse:161、confirm:83 各有一份副本）—— 不转义 '，非字符串会抛错
function escapeHtml(t){ return (t||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
```

### GL-23 现状
```js
// SOURCE: gui/static/index.html:388 —— 按位置编号；删 sh02 后剩 sh01 sh03，新加的第 3 个也叫 sh03
function renumber(){ state.shots.forEach((s,i)=>{ if(!s.id) s.id = 'sh'+String(i+1).padStart(2,'0'); }); }
// SOURCE: aicut.py:437-438 —— 切片文件名就是 id，所以 id 重复会互相覆盖，id 含 ../ 会写到目录外
        key = clip_key(sh, src)
        dst = clips_dir / f"{sh['id']}.mp4"
```

### TEST_STRUCTURE
```python
# SOURCE: tests/test_review.py:1-16 —— 纯函数 + tmp_path，测试内 import pytest，不用 class
import json

from pipeline import review


def test_set_level_and_load(tmp_path):
    review.set_level(tmp_path, "S001", 3)
    data = review.load(tmp_path)
    assert data["S001"]["level"] == 3
    assert "at" in data["S001"]


def test_invalid_level_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        review.set_level(tmp_path, "S001", 9)
```
```python
# SOURCE: tests/test_proc.py:11-13 —— 用 monkeypatch 改环境/模块属性
def test_user_data_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_CUT_PROJECTS", str(tmp_path))
    assert proc.user_data_root() == tmp_path
```
pytest 配置在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 里：`pythonpath=["."]`、`testpaths=["tests"]`、`addopts="-q"`。`gui/` 没有 `__init__.py`，但作为 namespace package 可以 `from gui import server`（`app/main.py:18` 就是这么写的）。目前还没有 `tests/conftest.py`。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/schema.py` | UPDATE | 新增 `write_json`（唯一临时文件的原子写），以及 `check_project_name` / `check_version` / `check_shot_ids`；`save` 改用 `write_json`（GL-18、GL-06） |
| `pipeline/review.py` | UPDATE | `OverridesCorrupt`；load 区分「文件不存在」和「文件损坏」；读改写加 `_LOCK`；`_save` 改用 `schema.write_json`（GL-18） |
| `aicut.py` | UPDATE | `save_json` 改用 `schema.write_json`；`project_dir` 校验项目名；`ensure_clips` 校验镜头 id；`cmd_build` 校验 version（GL-06、GL-18、GL-23） |
| `gui/server.py` | UPDATE | token 与请求守卫、HTML 注入、安全响应头、`_read_body` 报错、路由参数校验、`/media` 解码、shots 校验、overrides 损坏返回 409（GL-05/06/18/21/23） |
| `gui/static/common.js` | CREATE | 读取 token、给 fetch 自动加请求头、`esc()`、`num()`（GL-05、GL-07） |
| `gui/static/index.html` | UPDATE | 引入 common.js 和 meta；改用 esc；`/api/pick` 加 Content-Type；`renumber` 保证唯一（GL-05/07/23） |
| `gui/static/browse.html` | UPDATE | 引入 common.js 和 meta；改用 esc；内联事件只传下标（GL-05/07） |
| `gui/static/confirm.html` | UPDATE | 引入 common.js 和 meta；`pick(qi, oi)`；删除 escapeAttr（GL-05/07） |
| `gui/static/calibrate.html` | UPDATE | 引入 common.js 和 meta（GL-05） |
| `tests/conftest.py` | CREATE | `gui_server` fixture、`call()`、`make_project()` |
| `tests/test_server_security.py` | CREATE | GL-05、GL-06（服务端） |
| `tests/test_server_save.py` | CREATE | GL-18、GL-23（服务端） |
| `tests/test_server_media.py` | CREATE | GL-21 |
| `tests/test_static_pages.py` | CREATE | GL-05/07 静态守卫（每个页面有 meta 和 common.js；没有字符串插值进内联事件；不再有本地 escapeHtml） |
| `tests/test_aicut_guards.py` | CREATE | GL-06/23 aicut 侧：version、镜头 id、项目名 |
| `tests/test_review.py`, `tests/test_schema.py` | UPDATE | GL-18：损坏、并发、原子写 |
| `docs/go-live-blockers.md` | UPDATE | 每个 GL 修完提交后，把状态从 `open` 改为提交号（登记册的约定） |

## NOT Building

- KI-21（`jload` 把损坏的 JSON 当默认值）：本次只改 `overrides.json`（GL-18 点名的那个），`jload` 其它调用点不动。
- KI-31：shots 入出点的数值校验（负数、nan、out≤in），以及 `float()` 抛异常导致断连。本次只校验 id，以及 body 是不是合法 JSON 对象。
- KI-30：Range 解析（后缀范围、416）。
- KI-35：前端竞态和乐观更新；KI-36：`window.open` 在 pywebview 里的问题。
- 完整 CSP（页面全是内联脚本，要改成 nonce 是另一项工作）。
- 请求体大小上限、限流、OPTIONS/CORS 支持。
- 日志落盘（GL-19）、任务互斥（GL-20）。
- `pipeline/secrets.py:71`、`pipeline/to_jianying.py:41` 的 `.tmp` 写法：不在 GL-18 点名范围内，也没有 GUI 并发写入路径。
- `/api/new` 的 `material` 路径存在性校验（aicut 的 `cmd_new` 已经做了）。
- `prototype.html`：没有 fetch，不处理。

---

## Step-by-Step Tasks

> 每个 Task 都按 RED → GREEN 推进：先写测试，跑 `uv run pytest <file> -q` 确认**失败**，然后实现，再跑确认**通过**，最后跑全量 `uv run pytest`。基线：当前全量测试全绿（112 个左右）。
> 建议按 GL 分提交（`fix(gui): ... (GL-05)` 等），每次提交后在 `docs/go-live-blockers.md` 里把对应行的状态改为提交号。**Task 5 和 Task 9 必须放在同一个提交里**：服务端开始要求 token 之后，前端必须同时开始发送 token，否则 GUI 不可用。

### Task 1：schema 新增原子写与校验函数（GL-18、GL-06 基础）
- **ACTION**：先在 `tests/test_schema.py` 里追加测试（RED），再修改 `pipeline/schema.py`。
- **测试先行**：
  - `test_write_json_concurrent_same_path`：8 个线程各对同一路径调 25 次 `schema.write_json(p, {"i": n})`，收集异常。断言没有异常，最终文件是合法 JSON，`list(tmp_path.glob("*.tmp"))` 为空。RED 的方法：先用 `monkeypatch` 让现有写法跑同一个用例（或者直接测 `gui.server.jdump`，见 Task 7），固定 `.tmp` 名必然出现 `FileNotFoundError`。
  - `test_check_project_name_accepts_chinese_and_space`：`"九月 一号"`、`"2026-09-15_探店"` 都能通过。
  - `test_check_project_name_rejects`：用 parametrize 覆盖 `""`、`"-h"`、`"--help"`、`".hidden"`、`".."`、`"a/b"`、`"a\\b"`、`"a\x00b"`、`"a\nb"`、`"x"*101`，都应抛 `ValueError`。
  - `test_check_version`：`"v1"`、`"v12"` 通过；`"../x"`、`"v1/../.."`、`"1"`、`"v"`、`"--no-draft"`、`""` 抛 `ValueError`。
  - `test_check_shot_ids`：`[{"id":"sh01"},{"id":"sel02"}]` 通过；重复 id 抛错，消息里要有该 id；`"../x"`、`""`、`None`、`"a"*33`、非 dict 元素都抛错。
- **IMPLEMENT**（放在 `pipeline/schema.py`，紧跟 `save` 之前；新增 `import re`、`import uuid`）：
  ```python
  PROJECT_NAME_MAX = 100
  _VERSION_RE = re.compile(r"v\d{1,4}")
  _SHOT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")

  def write_json(path: Path, obj: Any) -> None:
      """原子写：每次用唯一临时文件，并发写同一路径不会互相踩。"""
      path = Path(path)
      path.parent.mkdir(parents=True, exist_ok=True)
      tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
      try:
          tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
          os.replace(tmp, path)
      except BaseException:
          tmp.unlink(missing_ok=True)
          raise

  def check_project_name(name: Any) -> str:
      if not isinstance(name, str) or not name.strip():
          raise ValueError("项目名不能为空")
      if (name.startswith(("-", ".")) or "/" in name or "\\" in name
              or any(ord(c) < 32 for c in name) or len(name) > PROJECT_NAME_MAX):
          raise ValueError(f"项目名不能以 - 或 . 开头，不能含斜杠或控制字符，最长 {PROJECT_NAME_MAX} 字")
      return name

  def check_version(version: Any) -> str:
      if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
          raise ValueError(f"版本号格式应为 v+数字（如 v3），收到 {version!r}")
      return version

  def check_shot_ids(shots: Any) -> None:
      if not isinstance(shots, list):
          raise ValueError("shots 必须是列表")
      seen: set[str] = set()
      for s in shots:
          sid = s.get("id") if isinstance(s, dict) else None
          if not isinstance(sid, str) or not _SHOT_ID_RE.fullmatch(sid):
              raise ValueError(f"镜头 id 只能用字母、数字、_、-（≤32 位），收到 {sid!r}")
          if sid in seen:
              raise ValueError(f"镜头 id 重复：{sid}")
          seen.add(sid)
  ```
  `save()` 改为：迁移之后调用 `write_json(path, cfg)`，删除原来自己写临时文件的三行（schema.py:96-100）。
- **MIRROR**：REPOSITORY_PATTERN（同样是原子替换，只是临时文件名唯一）；ERROR_HANDLING（抛 ValueError，中文消息）。
- **IMPORTS**：`import re`、`import uuid`（schema.py 已有 `json`、`os`、`Path`、`Any`）。
- **GOTCHA**：不要用 `tempfile.mkstemp`，它会把权限设成 0600，和原来按 umask 得到的权限不一样。临时文件以 `.` 开头，`glob("v*")`、`glob("*/project.json")` 不会扫到它。`check_project_name` 必须允许中文和空格（GL-21）。
- **VALIDATE**：`uv run pytest tests/test_schema.py -q` 全绿；`tests/test_schema.py` 原有的 save 相关用例仍然通过。

### Task 2：review 区分损坏、加锁（GL-18）
- **ACTION**：先在 `tests/test_review.py` 追加测试（RED），再修改 `pipeline/review.py`。
- **测试先行**：
  - `test_load_missing_returns_empty`：目录里没有文件时返回 `{}`（行为不变）。
  - `test_load_corrupt_raises`：写入 `"{bad"`，`review.load` 应抛 `review.OverridesCorrupt`，消息里有 `overrides.json`。
  - `test_load_non_dict_raises`：写入 `"[1,2]"`，应抛 `OverridesCorrupt`。
  - `test_set_level_on_corrupt_keeps_file`：写入 `"{bad"`，`set_level` 抛 `OverridesCorrupt`，文件内容仍是 `"{bad"`（以前会被覆盖成 `{"S001":…}`）。
  - `test_set_must_on_corrupt_keeps_file`：同上。
  - `test_concurrent_set_level_no_lost_update`：50 个线程分别对 `S000…S049` 调 `set_level(…, 3)`，结束后 `load()` 里应有 50 个键。现状会丢更新，还可能因为 `.tmp` 冲突抛错。
  - `test_overrides_corrupt_is_value_error`：`issubclass(review.OverridesCorrupt, ValueError)`，确保 server 现有的 `except ValueError` 能兜住。
- **IMPLEMENT**：
  ```python
  import threading
  from pipeline import schema

  _LOCK = threading.Lock()  # GUI 是多线程服务，读-改-写必须串行

  class OverridesCorrupt(ValueError):
      """overrides.json 读不出来：不能当空，否则下一次裁决会把人工结果全部覆盖。"""

  def load(workdir: Path) -> dict:
      path = _path(workdir)
      if not path.exists():
          return {}
      try:
          data = json.loads(path.read_text(encoding="utf-8"))
      except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
          raise OverridesCorrupt(f"人工裁决文件损坏，未做任何修改：{path}（{exc}）") from exc
      if not isinstance(data, dict):
          raise OverridesCorrupt(f"人工裁决文件格式不对（应为对象）：{path}")
      return data

  def _save(workdir: Path, data: dict) -> None:
      schema.write_json(_path(workdir), data)
  ```
  `set_level`、`set_must`、`clear(segment_id)` 的「load → 修改 → _save」整段放进 `with _LOCK:`。`set_level` 的档位校验放在锁外、load 之前。`clear(None)` 是显式重置，保持不读旧文件直接写 `{}`，但同样放进锁里。
- **MIRROR**：SERVICE_PATTERN；锁的命名参照 `JOBS_LOCK`。
- **IMPORTS**：`import threading`；`from pipeline import schema`（schema 不 import review，不会循环导入）。
- **GOTCHA**：`pipeline/select.py:391` 调用的 `review.load` 在文件损坏时会改为抛错，导致 `prepare/select` 失败。这是预期行为（不能静默丢掉人工必留），select.py 本身不用改。`apply()` 不变。
- **VALIDATE**：`uv run pytest tests/test_review.py tests/test_select.py -q` 全绿。

### Task 3：aicut 侧路径与 id 守卫（GL-06、GL-18、GL-23）
- **ACTION**：先新建 `tests/test_aicut_guards.py`（RED），再修改 `aicut.py`。
- **测试先行**（`import aicut`、`from argparse import Namespace`；用 `monkeypatch.setattr(aicut, "PROJECTS", tmp_path)`）：
  - `test_project_dir_rejects_option_like_name`：`aicut.project_dir("-h")` 抛 `SystemExit`。
  - `test_build_rejects_traversal_version`：建 `tmp_path/"p"/project.json`（`{"name":"p","material":"/tmp/a.mp4","schema_version":2}`）和 `shots.json`（一镜 `sh01`）。`monkeypatch.setattr(aicut, "ensure_clips", fail)`，其中 `fail` 被调用就抛 AssertionError。调用 `aicut.cmd_build(Namespace(name="p", version="../../evil", no_draft=True))`，断言抛 `SystemExit`，且 `not (tmp_path/"evil").exists()`。
  - `test_ensure_clips_rejects_traversal_id`：`monkeypatch.setattr(aicut, "run", fail)`，`aicut.ensure_clips(pdir, {"material": "/tmp/a.mp4"}, [{"id": "../../x", "in": 0, "out": 1}])` 抛 `SystemExit`，ffmpeg 没有被调用。
  - `test_ensure_clips_rejects_duplicate_ids`：两镜 id 都是 `sh03`，抛 `SystemExit`，消息里有「重复」（用 `capsys` 看输出）。
  - `test_save_json_uses_atomic_helper`：并发 8×25 次 `aicut.save_json` 写同一个路径，不抛异常。
- **IMPLEMENT**：
  - `save_json`（aicut.py:71-75）函数体改为 `schema.write_json(p, obj)`。
  - `project_dir`（aicut.py:78-82）开头加：
    ```python
    try:
        schema.check_project_name(name)
    except ValueError as exc:
        die(str(exc))
    ```
  - `ensure_clips`（aicut.py:429）开头，在 `clips_dir.mkdir` 之前加 `try: schema.check_shot_ids(shots) except ValueError as exc: die(str(exc))`。
  - `cmd_build`（aicut.py:540-543）：在 `shots = spec["shots"]` 之后、`ensure_clips` 之前加
    ```python
    if args.version:
        try:
            schema.check_version(args.version)
        except ValueError as exc:
            die(str(exc))
    ```
- **MIRROR**：ERROR_HANDLING（aicut 一律 `die`）。
- **IMPORTS**：`schema` 已在 aicut.py:36-38 导入，不需要新增。
- **GOTCHA**：`select.py:284` 生成的 id 是 `sel01` 这类，符合正则。`ensure_clips` 必须在 `clips_dir.mkdir` 和 ffmpeg 之前就失败。`run_cli`（aicut.py:725-735）会把 `SystemExit` 转成退出码，GUI 任务日志里会显示 `[x] 镜头 id 重复：…`。
- **VALIDATE**：`uv run pytest tests/test_aicut_guards.py -q` 全绿。

### Task 4：GUI 服务测试脚手架
- **ACTION**：新建 `tests/conftest.py`。这一步只写脚手架，用一个冒烟用例确认能起服务。
- **IMPLEMENT**：
  ```python
  import http.client
  import json
  import threading
  from http.server import ThreadingHTTPServer
  from types import SimpleNamespace

  import pytest


  @pytest.fixture
  def gui_server(tmp_path, monkeypatch):
      from gui import server
      monkeypatch.setattr(server, "PROJECTS", tmp_path)
      srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
      threading.Thread(target=srv.serve_forever, daemon=True).start()
      try:
          yield SimpleNamespace(module=server, port=srv.server_address[1], root=tmp_path)
      finally:
          srv.shutdown()
          srv.server_close()


  def call(gs, method, path, body=None, *, token=True, headers=None, raw=None):
      """发请求并返回 (status, bytes, headers)。默认带合法 Host/token/JSON。"""
      h = {"Host": f"127.0.0.1:{gs.port}"}
      if token:
          h["X-AICUT-Token"] = getattr(gs.module, "API_TOKEN", "")
      data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
      if data is not None:
          h["Content-Type"] = "application/json"
      h.update(headers or {})
      conn = http.client.HTTPConnection("127.0.0.1", gs.port, timeout=10)
      try:
          conn.request(method, path, body=data, headers=h)
          r = conn.getresponse()
          return r.status, r.read(), {k.lower(): v for k, v in r.getheaders()}
      finally:
          conn.close()


  def make_project(root, name="p1", shots=None, **files):
      pdir = root / name
      (pdir / "work").mkdir(parents=True)
      (pdir / "project.json").write_text(json.dumps(
          {"name": name, "material": "/tmp/a.mp4", "title": name, "schema_version": 2},
          ensure_ascii=False), encoding="utf-8")
      if shots is not None:
          (pdir / "shots.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
      for rel, content in files.items():   # 例：make_project(root, **{"work/proxy.mp4": b"..."})
          f = pdir / rel
          f.parent.mkdir(parents=True, exist_ok=True)
          f.write_bytes(content if isinstance(content, bytes) else content.encode())
      return pdir
  ```
  测试文件里写 `from conftest import call, make_project`（`pythonpath=["."]` 加上 pytest 的 rootdir/tests 插入机制，tests 目录在 sys.path 上；如果导入失败，就把 helper 挪到 `tests/_helpers.py`，用 `from tests._helpers import …`，因为 `pythonpath` 包含仓库根）。`make_project` 的 `**files` 用了 `"work/proxy.mp4"` 这种带斜杠的键，只能通过 `**{…}` 传入。
- **MIRROR**：TEST_STRUCTURE（函数式 fixture，monkeypatch 改模块属性）。
- **GOTCHA**：`server.PROJECTS` 是 import 时算出来的（server.py:35），所以必须 `setattr` 模块属性，设置环境变量没用。端口传 0，让系统分配。服务端子任务（`start_job`、`run_aicut`）在测试里一律 monkeypatch 掉，**不要**真的拉起 aicut。`call()` 用 `getattr(..., "API_TOKEN", "")`，这样 Task 5 之前也能先写 RED 测试。
- **VALIDATE**：冒烟用例 `test_server_smoke`（放在 `tests/test_server_security.py` 顶部）：`call(gs, "GET", "/api/projects", token=False)` 返回 200，用来证明脚手架可用。Task 5 之后改为带 token。

### Task 5：请求守卫、token 注入、安全头（GL-05，服务端）
- **ACTION**：先在 `tests/test_server_security.py` 写 GL-05 用例（RED），再修改 `gui/server.py`。
- **测试先行**：
  - `test_api_get_without_token_forbidden`：`GET /api/projects` 不带 token → 403。
  - `test_api_get_wrong_token_forbidden`：带 `X-AICUT-Token: x` → 403。
  - `test_api_get_with_token_ok`：→ 200。
  - `test_api_post_without_token_forbidden_and_no_write`：项目里已有 shots `[{"id":"sh01",...}]`。`POST /api/shots?project=p1`，body `{"shots": []}`，不带 token → 403，shots.json 不变。
  - `test_foreign_host_rejected_for_page_and_api`：`Host: evil.example:{port}`，`GET /` 和 `GET /api/projects` 都是 403（防 DNS rebinding）。
  - `test_localhost_host_allowed`：`Host: localhost:{port}`，`GET /` → 200。
  - `test_host_with_wrong_port_rejected`：`Host: 127.0.0.1:1` → 403。
  - `test_cross_origin_post_rejected`：token 正确，`Origin: http://evil.example` → 403。
  - `test_null_origin_post_rejected`：`Origin: null` → 403。
  - `test_same_origin_post_allowed`：`Origin: http://127.0.0.1:{port}`，`POST /api/browse/must` 对已有项目 → 200 或者业务层的 400（不是 403）。
  - `test_post_requires_json_content_type`：token 正确，`Content-Type: text/plain` → 415。
  - `test_pick_post_with_empty_json_ok`：monkeypatch `server.PICKER = lambda: ["/x.mp4"]`，`POST /api/pick` 带 `raw=b"{}"` → 200，返回 `{"path": "/x.mp4"}`。
  - `test_index_has_token_injected`：`GET /` 的正文包含 `server.API_TOKEN`，不包含 `__AICUT_TOKEN__`。`GET /static/browse.html`、`/static/confirm.html`、`/static/calibrate.html` 也一样。
  - `test_static_js_served_without_token`：`GET /static/common.js` → 200（Task 9 建好这个文件之后才能通过；也可以先用 index 断言，等 Task 9 再补这一条）。
  - `test_security_headers`：任意响应都有 `x-content-type-options: nosniff`、`x-frame-options: DENY`、`cross-origin-resource-policy: same-origin`。
  - `test_media_needs_host_not_token`：不带 token，`GET /media/p1/proxy`（项目里有 proxy.mp4）→ 200；同一请求用外部 Host → 403。
  - `test_token_is_random_per_process`：`len(server.API_TOKEN) >= 32`。
- **IMPLEMENT**（`gui/server.py`）：
  ```python
  import hmac  # 和其它 stdlib import 放在一起

  API_TOKEN = os.urandom(32).hex()   # 每次启动随机生成；页面加载时由服务端注入
  TOKEN_HEADER = "X-AICUT-Token"
  TOKEN_PLACEHOLDER = b"__AICUT_TOKEN__"
  SECURITY_HEADERS = {
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "Cross-Origin-Resource-Policy": "same-origin",
  }
  ```
  Handler 新增方法：
  ```python
  def _allowed_hosts(self) -> set[str]:
      port = self.server.server_address[1]
      return {f"127.0.0.1:{port}", f"localhost:{port}"}

  def _deny_reason(self, path: str, post: bool) -> tuple[int, str] | None:
      """返回 (状态码, 原因)；None 表示放行。"""
      hosts = self._allowed_hosts()
      if self.headers.get("Host", "") not in hosts:
          return 403, "拒绝：Host 不是本机剪辑台"
      if post:
          origin = self.headers.get("Origin")
          if origin is not None and origin not in {f"http://{h}" for h in hosts}:
              return 403, "拒绝：跨站请求"
          ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
          if ctype != "application/json":
              return 415, "请求必须是 application/json"
      if path.startswith("/api/"):
          given = self.headers.get(TOKEN_HEADER) or ""
          if not hmac.compare_digest(given.encode(), API_TOKEN.encode()):
              return 403, "页面已过期，请刷新"
      return None

  def _send_page(self, f: Path) -> None:
      body = f.read_bytes().replace(TOKEN_PLACEHOLDER, API_TOKEN.encode())
      return self._send(200, body, "text/html; charset=utf-8")
  ```
  - `_send`（server.py:306-318）：在 `Cache-Control` 之后循环写入 `SECURITY_HEADERS`。`_serve_media` 的 206 和 200 两个分支（server.py:345-349、364-367）在 `end_headers()` 之前也写入同一组头。可以抽一个 `_security_headers()` 小方法，三处共用。
  - `do_GET`（server.py:380）：解析出 `p` 之后，第一件事是 `deny = self._deny_reason(p, post=False)`，如果有就 `return self._json({"error": deny[1]}, deny[0])`。
  - `do_POST`（server.py:488-492）：守卫要在 `_read_body()` 之前执行（未授权的请求连 body 都不读）。
  - `/` 路由（server.py:385-387）改为 `return self._send_page(STATIC / "index.html")`。`/static/` 路由（server.py:389-394）：命中文件后，`.html` 走 `_send_page`，其它类型维持原样。
- **MIRROR**：ERROR_HANDLING（`self._json({"error": …}, code)`）；NAMING_CONVENTION（大写常量）。
- **IMPORTS**：`import hmac`。**不要** `import secrets`：仓库里有 `pipeline/secrets.py`，虽然路径不会冲突，但容易让人误读，`os.urandom` 就够用。
- **GOTCHA**：
  - pywebview 和 `--open` 浏览器模式都通过 `http://127.0.0.1:<port>/` 加载，Host 一定是 `127.0.0.1:<port>`，所以白名单能覆盖。端口从 `self.server.server_address[1]` 取，`serve_in_background`/`main` 的端口回退逻辑不受影响。
  - 同源 GET 不带 Origin，只有 POST 校验 Origin，而且 Origin 缺失时放行（非浏览器客户端仍然要 token）。
  - `/media/*` 和 `/static/*` 不要求 token（`<video src>`、`<script src>` 没法带请求头）。
  - 未实现 `do_OPTIONS`，跨域预检会得到 501，这正好起到阻断作用，**不要**加 CORS。
  - 这一步做完、Task 9 做完之前，GUI 不可用，所以两者必须放在同一个提交里。
- **VALIDATE**：`uv run pytest tests/test_server_security.py -q` 中 GL-05 相关用例全绿（`common.js` 那一条在 Task 9 之后转绿）。

### Task 6：路由参数校验（GL-06，服务端）
- **ACTION**：在 `tests/test_server_security.py` 追加 GL-06 用例（RED），再修改路由。
- **测试先行**（`monkeypatch.setattr(server, "start_job", rec)` 和 `monkeypatch.setattr(server, "run_aicut", rec)`，`rec` 记录参数；`run_aicut` 返回 `(0, "")`）：
  - `test_job_rejects_traversal_version`：`{"project":"p1","task":"build","version":"../../evil"}` → 400，`start_job` 未被调用。
  - `test_job_rejects_bad_project`：用 parametrize 覆盖 `"-h"`、`"../x"`、`""`、`"nope"`（不存在）→ 400，`start_job` 未被调用。
  - `test_job_accepts_valid`：`{"project":"p1","task":"build","version":"v2"}` → 200，`start_job` 收到 `("p1","build",["--version","v2"])`。
  - `test_shots_rejects_traversal_id`：`{"shots":[{"id":"../../x","in":0,"out":1}]}` → 400，shots.json 不变。
  - `test_new_rejects_option_like_name`：`{"name":"--help","material":"/x.mp4"}` → 400，`run_aicut` 未被调用。
  - `test_new_rejects_unknown_preset`：`{"name":"ok","material":"/x.mp4","preset":"../../etc/x"}` → 400。
  - `test_new_uses_equals_form`：合法请求 → `run_aicut` 收到的参数是 `["new","ok","--material=/x.mp4","--preset=纪实3min","--title=ok"]`。
  - `test_media_preview_rejects_bad_version`：`GET /media/p1/preview/..` → 400。
  - `test_confirm_bad_project_is_400_not_crash`：`GET /api/confirm?project=-h` → 400（现在会抛未捕获的 ValueError，连接直接断开）。
- **IMPLEMENT**：
  - `safe_name`（server.py:95-98）改为 `return schema.check_project_name(name)`。`project_path`（server.py:88-92）开头加 `schema.check_project_name(name)`，之后原有的 resolve 与包含检查保留，作为第二道防线。这样所有用到 `project_path` 的路由（state/browse/calibrate/confirm/shots/media/open/…）一次性都被覆盖。
  - 新增：
    ```python
    def existing_project(name: str) -> Path:
        pdir = project_path(name)
        if not (pdir / "project.json").exists():
            raise FileNotFoundError(f"项目不存在：{name}")
        return pdir
    ```
  - `/api/job`（server.py:545-559）：先 `existing_project(name)`；`task == "build"` 且传了 `v` 时 `schema.check_version(v)`；`except (ValueError, FileNotFoundError)` → 400（保持现有写法）。
  - `/api/new`（server.py:494-508）：`preset not in {f.stem for f in PRESETS.glob("*.json")}` → 400「未知预设」。命令参数改为 `["new", name, f"--material={material}", f"--preset={preset}", f"--title={title}"]`，这样以 `-` 开头的值不会被 argparse 当成选项。
  - `/media/`（server.py:482-483）：preview 分支先 `schema.check_version(parts[2])`，`ValueError` → 400（解码见 Task 8）。
  - `/api/confirm` GET（server.py:450-455）：增加 `except ValueError as exc: return self._json({"error": str(exc)}, 400)`。
- **MIRROR**：ERROR_HANDLING（server.py:432-439）。
- **IMPORTS**：`schema` 已经导入（server.py:32）。
- **GOTCHA**：项目名的规则必须和 Task 1 的 `check_project_name` 是同一个函数，不要在 server 里再写一份。`run_aicut` 在 FROZEN 模式下走 `run_cli(args)`，`--x=value` 的形式在两种模式下都有效。
- **VALIDATE**：`uv run pytest tests/test_server_security.py -q` 全绿。

### Task 7：保存不丢（GL-18 服务端，GL-23 服务端）
- **ACTION**：新建 `tests/test_server_save.py`（RED），再修改 `gui/server.py`。
- **测试先行**：
  - `test_jdump_concurrent_same_path`：直接 8×25 线程调用 `server.jdump`，不抛异常，没有残留 `*.tmp`。在当前代码上必然 RED。
  - `test_shots_invalid_json_does_not_overwrite`：已有 1 镜，`raw=b"{bad"` → 400，shots.json 字节不变（现状：返回 200，分镜被清空）。
  - `test_shots_non_object_body_rejected`：`raw=b"[1]"` → 400。
  - `test_shots_missing_key_does_not_overwrite`：`body={}` → 400，文件不变。
  - `test_shots_explicit_empty_list_allowed`：`{"shots": []}` → 200，`count == 0`（前端删掉最后一镜是合法操作）。
  - `test_shots_duplicate_ids_rejected`（GL-23）：`[{"id":"sh03",…},{"id":"sh03",…}]` → 400，`error` 里有 `sh03`，文件不变。
  - `test_shots_missing_id_rejected`：`[{"in":0,"out":1}]` → 400（不再由服务端兜底生成可能重复的 `sh{i:02d}`）。
  - `test_concurrent_shots_saves_all_ok`：20 个线程并发 `POST /api/shots`（各自合法）→ 全部 200，最终文件是合法 JSON。
  - `test_browse_level_on_corrupt_overrides_409`：`work/overrides.json` 写入 `"{bad"`，`POST /api/browse/level` → 409，文件不变。
  - `test_browse_get_on_corrupt_overrides_409`：同样的损坏，再准备一个 `work/segments_scored.json`（`{"segments":[{"id":"S001","start":0,"end":1,"level":2,"text":"x"}],"topics":[]}`），`GET /api/browse?project=p1` → 409，`error` 里有 `overrides.json`。
- **IMPLEMENT**：
  - `jdump`（server.py:81-85）函数体改为 `schema.write_json(p, obj)`。
  - 新增 `class BadRequest(ValueError): """请求体不合法：必须返回 400，绝不能当空请求继续写盘。"""`
  - `_read_body`（server.py:323-330）：
    ```python
    def _read_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise BadRequest("Content-Length 非法") from exc
        if n <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadRequest(f"请求体不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise BadRequest("请求体必须是 JSON 对象")
        return data
    ```
    `do_POST` 在守卫之后：`try: body = self._read_body() except BadRequest as exc: return self._json({"error": str(exc)}, 400)`。
  - `/api/shots`（server.py:530-539）：
    ```python
    shots = body.get("shots")
    if not isinstance(shots, list):
        return self._json({"error": "缺少 shots 列表，未保存"}, 400)
    try:
        schema.check_shot_ids(shots)
    except ValueError as exc:
        return self._json({"error": str(exc)}, 400)
    clean = [{"id": s["id"], "in": …, "out": …, "sub": …, "note": …} for s in shots]
    ```
    （`in/out` 的 `round(float(...), 3)` 保持原样，数值校验属于 KI-31。）
  - `browse_payload`、`/api/browse/level|must`：在现有 `except` 之前加 `except review.OverridesCorrupt as exc: return self._json({"error": str(exc)}, 409)`。GET `/api/browse` 的现有 `except (ValueError, OSError)` 在它后面（server.py:438）。POST 的在 server.py:604。
- **MIRROR**：ERROR_HANDLING；REPOSITORY_PATTERN（改用 `schema.write_json`）。
- **IMPORTS**：无新增（`review`、`schema` 已导入）。
- **GOTCHA**：`OverridesCorrupt` 是 `ValueError` 的子类，必须写在 `except ValueError` **之前**，否则会被当成 400。`/api/pick` 不带 body 时 `n == 0` 返回 `{}`，属于合法情况。`/api/calibrate` POST 用的 `schema.save` 已在 Task 1 改为唯一临时文件。
- **VALIDATE**：`uv run pytest tests/test_server_save.py tests/test_review.py -q` 全绿。

### Task 8：媒体路由 percent-decode（GL-21）
- **ACTION**：新建 `tests/test_server_media.py`（RED），再修改 `/media/` 路由。
- **测试先行**：
  - `test_proxy_chinese_space_project_200`：`make_project(root, "九月 一号", **{"work/proxy.mp4": b"\x00" * 1000})`，`GET "/media/" + quote("九月 一号") + "/proxy"` → 200，正文长度 1000（现状 404）。
  - `test_proxy_range_chinese_project_206`：`Range: bytes=10-19` → 206，长度 10，`content-range: bytes 10-19/1000`。
  - `test_preview_chinese_project_200`：`output/v1/preview.mp4` 存在时，`GET /media/<quoted>/preview/v1` → 200。
  - `test_encoded_slash_in_project_rejected`：`GET /media/a%2F..%2Fb/proxy` → 400（解码后含 `/`，被 `check_project_name` 拒绝）。
- **IMPLEMENT**（server.py:475）：
  ```python
  parts = [unquote(x) for x in p[len("/media/"):].split("/")]
  ```
  先按 `/` 切分再逐段解码，这样 `%2F` 不会制造出新的路径层级。`project_path(parts[0])` 会负责校验。
- **MIRROR**：现有 `/media/` 路由结构不变。
- **IMPORTS**：`from urllib.parse import parse_qs, unquote, urlparse`。
- **GOTCHA**：不要对整个 `u.path` 先解码再切分。查询参数里的 `project`（`/api/state?project=…`）已经由 `parse_qs` 解码过，不用改。前端 index.html:204/230/262/430 已经用了 `encodeURIComponent`，问题只在服务端。
- **VALIDATE**：`uv run pytest tests/test_server_media.py -q` 全绿。

### Task 9：前端 common.js 与 token（GL-05，前端；与 Task 5 同一提交）
- **ACTION**：新建 `gui/static/common.js`，四个页面引入它。在 `tests/test_static_pages.py` 写守卫测试（RED）。
- **测试先行**（`tests/test_static_pages.py`，纯文本检查）：
  - `PAGES = ["index.html", "browse.html", "confirm.html", "calibrate.html"]`
  - `test_pages_have_token_meta_and_common_js`：每个页面都包含 `<meta name="aicut-token" content="__AICUT_TOKEN__">` 和 `<script src="/static/common.js"></script>`，并且两者都出现在第一个内联 `<script>`（不带 src 的那个）之前。
  - `test_common_js_escapes_quote`：`common.js` 里有 `esc` 定义，并包含 `&#39;`（单引号也会转义）。
  - `test_pick_sends_json`：index.html 里不再有 `api('/api/pick', {method:'POST'})`。
- **IMPLEMENT** `gui/static/common.js`：
  ```js
  // 剪辑台各页面共用：API token 与转义。必须在页面内联脚本之前加载。
  (function(){
    const meta = document.querySelector('meta[name="aicut-token"]');
    const TOKEN = meta ? meta.content : '';
    const nativeFetch = window.fetch.bind(window);
    // 所有 /api/ 请求自动带 token；<video src> 走 /media/，不需要
    window.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (!url.startsWith('/api/')) return nativeFetch(input, init);
      const opt = {...(init || {})};
      const headers = new Headers(opt.headers || {});
      headers.set('X-AICUT-Token', TOKEN);
      opt.headers = headers;
      return nativeFetch(input, opt);
    };
    window.esc = t => String(t ?? '').replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    window.num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
  })();
  ```
  四个页面的 `<head>` 中，`<title>` 后面插入：
  ```html
  <meta name="aicut-token" content="__AICUT_TOKEN__">
  <script src="/static/common.js"></script>
  ```
  index.html:504 改为 `api('/api/pick', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})`。
- **MIRROR**：「前端 API 调用」一节；现有 `api()` 的错误处理会把 403 的 `j.error`（「页面已过期，请刷新」）用 toast 显示出来，不用另写逻辑。
- **GOTCHA**：所有调用点传的都是字符串 URL 并且以 `/api/` 开头（已核对 index/browse/confirm/calibrate），不存在绝对 URL 或 Request 对象。`common.js` 是同步脚本，必须放在 meta 之后、内联脚本之前。`window.open('/static/browse.html?…')` 打开的新窗口会再次从服务端拿到注入了 token 的 HTML，不需要额外处理。
- **VALIDATE**：`uv run pytest tests/test_static_pages.py tests/test_server_security.py -q` 全绿；手动验证见下文「Browser Validation」。

### Task 10：前端 XSS（GL-07）
- **ACTION**：在 `tests/test_static_pages.py` 追加守卫（RED），再改三个页面。
- **测试先行**：
  - `test_no_string_interpolation_in_inline_handlers`：index/browse/confirm 中，正则 `on\w+="[^"]*'\$\{` 零命中（内联事件里不再出现 `'${…}'` 这种字符串插值）。
  - `test_no_local_escape_helpers`：三个页面都不再包含 `function escapeHtml`、`function escapeAttr`（统一用 common.js 的 `esc`）。
  - `test_llm_fields_escaped_in_browse`：browse.html 里 `${p.text}`、`${c.name}`、`${c.desc}`、`(s.summary ||` 的未转义写法零命中。
- **IMPLEMENT**（逐点修改，行号是当前版本的）：
  - **browse.html**
    - 107-108：`${esc(e.error || '还没有分析结果')}`
    - 112 之后（`DATA = await r.json()` 之后）：`DATA.segments.forEach((s, i) => { s._i = i; });`
    - 118-119：`esc(s.summary || '（暂无摘要）')`
    - 121-123：`onclick="jump(${num(p.at)}, null, ${num(p.at)+4})"`、`${fmt(num(p.at))}`、`${esc(p.text)}`、`${esc(p.why||'')}`
    - 125：`${esc(c.name)}`、`${esc(c.desc)}`
    - 151-158 `row(s)`：`data-id="${esc(s.id)}"`，`onclick="jumpSeg(${s._i})"`，`title="${esc(s.topic||'')}">${esc(s.topic||'—')}`，`title="${esc(s.level_reason||'')}"`，`s.visual_flags.map(esc).join('/')`，星标 `onclick="event.stopPropagation();toggleMustIdx(${s._i})"`；`escapeHtml(` 全部换成 `esc(`。
    - 新增 `function jumpSeg(i){ const s = DATA.segments[i]; jump(s.start, s.id, s.end); }` 和 `function toggleMustIdx(i){ toggleMust(DATA.segments[i].id); }`
    - 173-175：分组标题 `${esc(name)}`，`${num(t.usable_dur).toFixed(0)}`，`${num(t.budget)}`
    - 194-195：`escapeHtml` → `esc`
    - 删除 161 行的 `escapeHtml` 定义
  - **index.html**
    - 186：`<b>${esc(p.title||p.name)}</b><span>${p.versions.length ? '已出片 '+p.versions.map(esc).join(' / ') : '未出片'}</span>`
    - 209：`${esc(s.label)}`
    - 321、350、418：`escapeHtml(` → `esc(`
    - 417-419：`${esc(j.start_tc)}`、`${esc(j.end_tc)}`、`${esc(j.duration)}`、`${esc(j.suggest)}`
    - 428-430：`${esc(v.name)}`、`${esc(v.mtime)}`、`${esc(v.draft)}`，预览地址 `/preview/${encodeURIComponent(v.name)}`
    - 498：`value="${esc(p.key)}">${esc(p.name)}（${esc(p.duration)}s·${esc(p.platform)}）`
    - 删除 325 行的 `escapeHtml` 定义
  - **confirm.html**
    - 76-77、89、95：`escapeHtml(` → `esc(`；`${fmt(num(p.at))}`
    - 92：`onclick="pick(${qi},${oi})"`
    - `pick` 改为：
      ```js
      function pick(qi, oi){
        const q = DATA.questions[qi], label = q.options[oi].label;
        if(q.type==='multi'){
          const arr = ANSWERS[q.id] || [];
          const i = arr.indexOf(label);
          i>=0 ? arr.splice(i,1) : arr.push(label);
          ANSWERS[q.id] = arr;
        } else { ANSWERS[q.id] = label; }
        renderQuestions();
      }
      ```
    - 删除 83 行的 `escapeHtml` 和 99 行的 `escapeAttr`
- **MIRROR**：index.html:206、208 已经用 `textContent` 渲染纯文本，这是安全写法；凡是能改成 `textContent` 的地方优先用它。
- **GOTCHA**：模板里有些数字其实来自 LLM 或磁盘（`p.at`、`t.budget`、`t.usable_dur`），一律先过 `num()`。只能通过 `esc()` 进入属性的值，属性必须用双引号包住（现有模板都是双引号）。`s.id` 不再进入 JS 字符串，只进 `data-id`，所以 `jump()` 里 `r.dataset.id===cur` 的比较不受影响。
- **VALIDATE**：`uv run pytest tests/test_static_pages.py -q` 全绿；做下文的 XSS 手动验证。

### Task 11：前端镜头 id 唯一（GL-23）
- **ACTION**：修改 index.html:388 的 `renumber`（Task 7 已经有服务端测试兜底）。
- **IMPLEMENT**：
  ```js
  const SHOT_ID_RE = /^[A-Za-z0-9_-]{1,32}$/;
  function nextShotId(){
    const nums = state.shots.map(s=>/^sh(\d+)$/.exec(s.id||'')).filter(Boolean).map(m=>+m[1]);
    return 'sh'+String((nums.length ? Math.max(...nums) : 0)+1).padStart(2,'0');
  }
  // 补齐缺失 id、修正重复/非法 id（也能修好历史上已经存进 shots.json 的重复 id）
  function renumber(){
    const seen = new Set();
    state.shots.forEach(s=>{
      if(!s.id || seen.has(s.id) || !SHOT_ID_RE.test(s.id)) s.id = nextShotId();
      seen.add(s.id);
    });
  }
  ```
  `saveShots`（index.html:375-376）已经在保存前调用 `renumber()`，`dup`（395）会把 id 置空，`addFromSeg`/`addBlank` 新建时 id 也为空，这些都不用改。
- **测试先行**：在 `tests/test_static_pages.py` 加 `test_renumber_not_position_based`，断言 index.html 里不再有 `'sh'+String(i+1)`。行为由 Task 7 的服务端用例 `test_shots_duplicate_ids_rejected` 兜底，再加上手动验证。
- **GOTCHA**：选段生成的 `sel01` 不匹配 `^sh\d+$`，所以不参与取最大值，两套编号互不冲突。修改某镜的 id 会让它的切片缓存失效并重新切（manifest 按 id 记录），这是可以接受的。
- **VALIDATE**：手动：删除 sh02 后新加一镜 → 新 id 为 `sh04`（原有 sh01、sh03）；构建后 `work/clips/` 每个 id 一个文件。

### Task 12：登记册状态
- **ACTION**：每个 GL 修完提交后，在 `docs/go-live-blockers.md` 把对应行的状态从 `open` 改为提交短哈希（登记册顶部的约定）。PRD 的里程碑状态由编排方维护，不在这里改。
- **VALIDATE**：`git diff docs/go-live-blockers.md` 只改了 6 行的状态列。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_write_json_concurrent_same_path` | 8 线程 × 25 次写同一路径 | 无异常，合法 JSON，无残留 tmp | 并发 |
| `test_check_project_name_*` | 中文空格 / `-h` / `.x` / `a/b` / `\x00` / 101 字 | 通过 / ValueError | 是 |
| `test_check_version` | `v12` / `../x` / `--no-draft` | 通过 / ValueError | 是 |
| `test_check_shot_ids` | 重复、`../x`、None、非 dict | ValueError | 是 |
| `test_load_corrupt_raises` | `{bad` | OverridesCorrupt | 损坏文件 |
| `test_set_level_on_corrupt_keeps_file` | `{bad` + set_level | 抛错，文件不变 | 是 |
| `test_concurrent_set_level_no_lost_update` | 50 线程不同 id | 50 键 | 并发 |
| `test_build_rejects_traversal_version` | `version=../../evil` | SystemExit，没有建目录 | 是 |
| `test_ensure_clips_rejects_*` | `../x` / 重复 id | SystemExit，没有调用 ffmpeg | 是 |
| `test_api_*_token_*` | 无 / 错 / 对 token | 403 / 403 / 200 | 权限 |
| `test_foreign_host_rejected_*` | `Host: evil.example` | 403 | DNS rebinding |
| `test_cross_origin_post_rejected` | `Origin: http://evil.example` | 403 | CSRF |
| `test_post_requires_json_content_type` | text/plain | 415 | 是 |
| `test_index_has_token_injected` | GET / | 包含 token，没有占位符 | — |
| `test_job_rejects_*` | 穿越 version / `-h` 项目 | 400，没有启动任务 | 是 |
| `test_new_uses_equals_form` | 合法新建 | `--material=…` 形式 | — |
| `test_shots_invalid_json_does_not_overwrite` | `{bad` | 400，文件不变 | 坏请求 |
| `test_shots_missing_key_does_not_overwrite` | `{}` | 400，文件不变 | 空请求 |
| `test_shots_explicit_empty_list_allowed` | `{"shots":[]}` | 200 | 是 |
| `test_shots_duplicate_ids_rejected` | 两个 sh03 | 400 | GL-23 |
| `test_concurrent_shots_saves_all_ok` | 20 并发 POST | 全部 200 | 并发 |
| `test_browse_*_corrupt_overrides_409` | 损坏的 overrides | 409，文件不变 | 是 |
| `test_proxy_chinese_space_project_200` | `/media/%E4…%20…/proxy` | 200 | GL-21 |
| `test_encoded_slash_in_project_rejected` | `a%2F..%2Fb` | 400 | 是 |
| `test_pages_have_token_meta_and_common_js` | 4 个页面 | 都有 meta 和 common.js，而且顺序正确 | — |
| `test_no_string_interpolation_in_inline_handlers` | 3 个页面 | 零命中 | XSS |

### Edge Cases Checklist
- [x] 空输入（空 body、`{}`、`shots: []`、空项目名）
- [ ] 超大输入：不做（不在范围内）
- [x] 类型不对（body 是数组、shots 不是列表、id 为 None 或数字、`p.at` 是字符串）
- [x] 并发（jdump、review 读改写、并发 POST /api/shots）
- [ ] 网络故障：不适用
- [x] 无权限（没有 token、外部 Host、跨站 Origin、`Origin: null`）

---

## Validation Commands

### Static Analysis
```bash
# 项目未配置 lint / typecheck（见 CLAUDE.md）。只做语法冒烟：
uv run python -c "import ast,sys;[ast.parse(open(f,encoding='utf-8').read()) for f in ['gui/server.py','aicut.py','pipeline/schema.py','pipeline/review.py']]"
```
EXPECT：无输出、退出码 0

### Unit Tests
```bash
uv run pytest tests/test_schema.py tests/test_review.py tests/test_aicut_guards.py \
  tests/test_server_security.py tests/test_server_save.py tests/test_server_media.py \
  tests/test_static_pages.py -q
```
EXPECT：全部通过

### Full Test Suite
```bash
uv run pytest
```
EXPECT：无回归（基线约 112 个，加上本次新增的约 60 个，全部绿）

### Database Validation
N/A（无数据库）

### Browser Validation
```bash
# 1) 准备一个带恶意内容、中文名的项目（不放在仓库目录下）
export AI_CUT_PROJECTS="$(mktemp -d)"
uv run python - <<'PY'
import json, os, pathlib
root = pathlib.Path(os.environ["AI_CUT_PROJECTS"]); p = root / "九月 一号"; w = p / "work"; w.mkdir(parents=True)
bad = "<img src=x onerror=alert('xss')>'\");alert(1)//"
(p/"project.json").write_text(json.dumps({"name":"九月 一号","material":"/tmp/a.mp4","title":bad,"schema_version":2}), "utf-8")
(w/"segments_scored.json").write_text(json.dumps({"segments":[{"id":"S001","start":0,"end":2,"level":2,"text":bad,"topic":bad,"level_reason":bad}],"topics":[]}), "utf-8")
(w/"content_summary.json").write_text(json.dumps({"summary":bad,"key_points":[{"at":"1);alert(2)//","text":bad,"why":bad}],"cast":[{"name":bad,"desc":bad}]}), "utf-8")
(w/"questions.json").write_text(json.dumps({"questions":[{"id":"q1","type":"single","text":bad,"options":[{"label":bad,"effect":bad}]}]}), "utf-8")
PY
cp <任意一段 mp4> "$AI_CUT_PROJECTS/九月 一号/work/proxy.mp4"
# 2) 浏览器模式
python3 gui/server.py --open
# 3) 桌面壳
uv run python app/main.py
```
EXPECT：两种模式下都没有任何 alert；恶意文本按原样显示；「九月 一号」的代理视频能播放、能拖动；确认页点选项后能正常勾选；浏览页按 A/D/S 键能改档位和星标，刷新后仍在。

### Manual Validation
- [ ] pywebview（`uv run python app/main.py`）：新建项目 → 处理素材 → 分镜表增删改 → 生成成片，整个流程没有 403。
- [ ] 浏览器模式（`python3 gui/server.py --open`）：同上；「浏览素材」「剪辑偏好」新窗口的 API 正常。
- [ ] 浏览器模式下重启服务，不刷新旧标签页直接操作 → toast「页面已过期，请刷新」；刷新后恢复正常。
- [ ] 在另一个端口打开一个本地 HTML，执行 `fetch('http://127.0.0.1:8765/api/job',{method:'POST',body:'{"project":"x","task":"prepare"}'})` → 被拒（预检失败或 403），没有启动任务。
- [ ] `curl -s -H 'Host: evil.example:8765' http://127.0.0.1:8765/` → 403。
- [ ] 分镜表：有 sh01–sh03 → 删除 sh02 → 新加一镜 → 新 id 为 sh04；生成成片后，`work/clips/` 里没有被覆盖的切片，成片中没有重复内容。
- [ ] 手动把 `work/overrides.json` 改坏 → 浏览页显示含文件路径的错误，文件没有被改写。

---

## Acceptance Criteria
- [ ] Task 1–12 全部完成
- [ ] 上面的验证命令全部通过
- [ ] 每个 GL 至少有一个先 RED、后 GREEN 的回归测试
- [ ] 无 lint/typecheck（项目未配置）；语法冒烟通过
- [ ] pywebview 和浏览器两种模式的手动验证通过（UX 与上面的 After 一致）
- [ ] `docs/go-live-blockers.md` 中 GL-05/06/07/18/21/23 的状态都填了提交号

## Completion Checklist
- [ ] 校验函数只有一份（`pipeline/schema.py`），server 和 aicut 共用
- [ ] 原子写只有一份（`schema.write_json`），jdump、review、schema.save、aicut.save_json 都调用它
- [ ] 错误统一返回 `{"error": 中文消息}` 加正确的状态码（400/403/404/409/415）
- [ ] 没有新增 logging（GL-19 再做）
- [ ] 测试沿用 tests/ 的函数式写法和 tmp_path/monkeypatch
- [ ] token、Host 白名单、长度上限、正则都定义成命名常量
- [ ] 没有越出 NOT Building 的范围
- [ ] 计划是自包含的，实现时不需要再翻代码找上下文

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| pywebview（WKWebView）同源 POST 带的 Origin 和预期不同（比如 `null`） | 低 | 高（GUI 全部 403） | 手动验证第 1 条必须在桌面壳里跑；如果实测是 `null`，把 `"null"` 加入白名单的前提是 token 校验通过（token 已经足以防 CSRF），并在 PR 里记录 |
| 打补丁的 `fetch` 漏掉某个调用点（比如以后用 `new Request`） | 低 | 中 | `common.js` 同时处理字符串和 Request；`test_pages_have_token_meta_and_common_js` 保证每个页面都加载了它 |
| 旧项目的 shots.json 里已经有重复 id | 中 | 中（build 直接失败） | 前端打开后的第一次保存，`renumber` 会自动修正；CLI 用户会看到 `die` 的明确消息 |
| `overrides.json` 损坏后，prepare/select 也会失败 | 低 | 中 | 这是预期行为（不能静默丢掉人工必留）；错误消息带文件路径；处理方式见 Notes 决策 1 |
| 测试里起真实 HTTP 服务导致偶发失败 | 低 | 低 | 端口传 0，用 daemon 线程，`shutdown()` + `server_close()`，http.client 设 timeout |
| 浏览器模式的旧标签页大量 403 | 中 | 低 | 错误文案引导刷新，见 Notes 决策 2 |

## Notes

**设计取舍**
- 为什么用 token 请求头，不用 Cookie：`SameSite` 把 `127.0.0.1` 上的其它端口视为同站，本机任何其它服务的页面都能带上 Cookie；自定义请求头会强制触发 CORS 预检，本服务不响应 OPTIONS，跨站请求就发不出去。
- 为什么用 meta 注入，不提供 `/api/token` 接口：接口一旦存在，被 rebind 的页面就能读到它（Host 校验虽然能挡，但多一层依赖）；HTML 由服务端在读文件时替换占位符，跨站页面读不到同源 HTML。
- 为什么打补丁 `window.fetch`，而不是逐个改调用点：四个页面一共约 12 个 fetch/api 调用点，打补丁一处改完，后面新加的 API 调用也会自动带上 token；`test_static_pages` 守住每个页面都加载了 common.js。
- 为什么 `/media` 不要求 token：`<video src>` 带不了请求头；用 Host 白名单挡 DNS rebinding，用 CORP `same-origin` 挡跨站 `<video>` 嵌入。

**需用户决策**（以下都给了推荐默认值，按默认值实现，不会阻塞开工）
1. **`overrides.json` 损坏时怎么办**。推荐默认：拒绝任何写入，浏览页和选段都报错，消息里带文件路径（409），不自动处理，由人来决定。备选：自动改名备份为 `overrides.json.corrupt-<时间戳>`，从空开始并提示「已备份损坏文件」。默认方案最保守，不会丢数据，但剪辑师需要找人修文件。
2. **token 失效时的文案**。推荐默认：「页面已过期，请刷新」（只有浏览器模式在服务重启后才会遇到；桌面壳每次都重新加载页面）。
3. **项目名规则收紧后的文案**。推荐默认：「项目名不能以 - 或 . 开头，不能含斜杠或控制字符，最长 100 字」，中文和空格照常允许。100 字的上限也需要确认。
