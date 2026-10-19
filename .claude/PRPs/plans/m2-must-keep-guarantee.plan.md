# Plan: 里程碑 2「必留内容不丢」（GL-08 · GL-09 · GL-24 · GL-25）

> 修订 2（2026-10-19）：按用户对「需用户决策」的答复重写。行号基于**含 M1 未提交改动的工作树**（`aicut.py`、`gui/server.py`、`gui/static/*.html`、`gui/static/common.js`、`pipeline/schema.py`、`pipeline/review.py` 均已被 M1 修改）。基线：`uv run pytest` → 253 passed。

## Summary

必留段在选段里**永远整段进片**；成片时长不再写死——**目标时长由剪辑师决定**（新建项目时问，之后可改，改了只重跑选段）。必留内容超过目标时长时不丢不截，而是把「必留共 X，超过目标 Z」明确告诉剪辑师并让他重新定时长。LLM 逐句标注重试后仍失败 → 任务失败并提示重试，失败句子先落盘，重试只补跑失败的句子。待定超限、画面过暗都不再把必留话题/标注失败的段降成废片。出片前校验分镜表包含全部必留段，缺了就不出片。

## User Story

As a 剪辑师（非技术背景，用剪辑台 GUI 或 CLI），
I want 自己决定成片多长；标了必留的句子一定进片；AI 没处理好的句子不会被悄悄扔掉，
So that 不再出现「重要对话被删了还显示成功」，也不会因为必留太多而被程序偷偷截掉。

## Problem → Solution

**现状**（均已在当前工作树复现，见 Notes）：
- GL-08：`select.select()` 里 must_keep 只是 `_score` +10（`pipeline/select.py:75-76`），会被 exclude（`:173`）、话题预算 0（`:185-187`）、预算用尽（`:198-201`）、`_trim`（`:129-133`）、首镜按预算截断（`:196`）丢掉或截短。
- 目标时长：`cmd_new` 直接取预设 `duration`（`aicut.py:176`），CLI/GUI 都不问；没有任何入口改已有项目的目标；GUI 也没有「只重跑选段」的任务（`gui/server.py:245-248` 只有 prepare/build）。
- GL-09：`annotate()` 批次失败 `continue`、不检测漏 id（`pipeline/understand_text.py:167-180`），`run()` 给缺标注的句子填空（`:200-208`），`cmd_text` 仍 `[✓]`（`aicut.py:259-264`）；待定超限按信息弱降废片，不区分必留话题（`pipeline/classify.py:87-96`）。
- GL-24：画面过暗分支在降级前把一切非可用段改废片（`pipeline/classify.py:82-83`）。
- GL-25：`cmd_build` 优先用手存的 `shots.json`（`aicut.py:538-545`），不检查必留段是否在分镜表里。

**目标**：
1. 选段不变量：`{必留段 id} ⊆ {镜头 segment_id}` 且必留镜头为整段；违反抛 `SelectionError`（守卫）。
2. 结果记录 `must_keep_total`、`over_target`（= 必留合计 > 目标）、`suggested_target`；CLI 打印 `[!]` + 改时长命令；GUI 弹窗「必留内容共 X 分 Y 秒，超过目标 Z」+ 时长输入框，确认后存目标并**只重跑选段**（新 `select` 任务）。
3. 新建项目时问目标时长（预设值仅作默认）；已有项目可改：CLI `select --target`，GUI「目标时长」按钮。
4. 标注：整批重试 + 漏 id 补问；仍失败 → 先落盘（`complete:false` + `annotation_failed`）再报错，任务失败；重跑时若输入未变，只补跑失败的句子。
5. 三档：标注失败段 → 待定；必留话题段与标注失败段不被「待定超限」或「画面过暗」降为废片；超限给警告。
6. 出片前校验：分镜表没覆盖全部必留段 → `die`，列出缺的句子和补救办法，不切片。

## Metadata
- **Complexity**: Large（10+ 文件，跨 pipeline / CLI / GUI 服务 / 前端）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: 里程碑 2「必留内容不丢」（GL-08 GL-09；GL-24 GL-25 由协调方登记后并入）
- **Estimated Files**: 13（`pipeline/select.py`、`pipeline/classify.py`、`pipeline/understand_text.py`、`pipeline/schema.py`、`aicut.py`、`gui/server.py`、`gui/static/index.html`；测试 `tests/test_select.py`、`tests/test_classify.py`、`tests/test_understand_text.py`、`tests/test_schema.py`、新建 `tests/test_aicut_must_keep.py`、新建 `tests/test_server_target.py`；`tests/test_static_pages.py` 追加）+ 完成后更新 `docs/go-live-blockers.md`

---

## UX Design

### Before
```
新建项目：素材 / 项目名 / 片名 / 风格预设（纪实3min = 175s，写死）
① 处理素材 → 日志 …[✓] 话题 12 个 · 2 批失败 → [✓] 选段 14 镜 · 172s/175s → 完成
                    （80 句没标注被当废片）     （标了★的 3 句不在里面）
没有地方改目标时长；② 生成成片 → 手存的分镜表缺必留也照样出片
```

### After
```
新建项目：… 风格预设 [纪实3min ▼]  想剪成多长（秒）[175]  ← 预设只是默认值
① 处理素材
  ├ 标注失败 → [x] 12 句逐句标注失败（每批已重试 2 次）… 结果已保存；
  │            检查网络/额度后重新点「① 处理素材」，只会重跑这 12 句     → 任务失败
  └ 成功 → [✓] 选段 18 镜 · 214s / 目标 175s · 必留 5 段
           [!] 必留内容共 3 分 34 秒，超过目标 2 分 55 秒 …
           任务结束后自动弹窗：
           ┌──────────────────────────────────────────────┐
           │ 必留内容共 3 分 34 秒，超过目标 2 分 55 秒      │
           │ 想剪成多长？ [215] 秒   （默认=必留合计向上取整） │
           │ [按这个时长重新选段]  [先不改]                   │
           └──────────────────────────────────────────────┘
           → 保存目标 → 任务「select」只重跑选段（不转写、不调 LLM）
顶栏：目标 3:35 [改目标时长]（任何时候可改，同样只重跑选段）
② 生成成片：分镜表缺必留段 → [x] 分镜表缺少 2 段必留内容：03:12 "九千八包含…"；
           在分镜表里加回，或在「浏览素材」取消★后再出片        → 不切片
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| GUI 新建项目弹窗 | 只选预设 | 新增「想剪成多长（秒）」，随预设变化预填 | `/api/new` 新增 `target` |
| CLI `new` | 用预设时长 | `--target <秒>`；不给且在终端里 → 询问，回车用预设；非终端 → 预设 | GUI 总是传 `--target`，不会触发 `input()`（避免加重 GL-20） |
| CLI `select` | 用项目目标 | `select <项目> --target <秒>`：保存目标后只重跑选段 | 不碰 ASR/LLM/score |
| GUI 顶栏 | 「目标 175 秒」只读 | 「目标 2:55」+「改目标时长」按钮 | 弹窗同下 |
| GUI 任务结束 | 直接关窗 | prepare/select 完成且 `over_target` → 弹必留超时长窗 | 只在任务结束后自动弹一次；顶栏按钮随时可开 |
| `/api/job` | prepare / build | 新增 `select`（可带 `target`） | KI-05 将来可复用此任务 |
| `/api/state` | 无选段信息；分镜表只读 `shots.json` | 增加 `selection` 摘要；`shots.json` 不存在时用 `work/shots-selected.json` 预填 | 有手存分镜表时不覆盖 |
| `aicut.py text` / prepare | 失败仍 `[✓]` | `[x]` + 退出码 1；重跑只补失败句子 | GUI 失败后关窗依赖 GL-22（M4） |
| `aicut.py score` | 三档计数 | + 「自动降级 N」+ 超限 `[!]` | |
| `aicut.py build` | 不查必留 | 缺必留 → `[x]`，不切片 | GL-25 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/select.py` | 116-160, 163-304, 376-409 | `_clip/_trim/_force_lines`、`select()`、`run()` |
| P0 | `pipeline/classify.py` | 33-98, 101-163 | `_level_of`、暗画面、待定降级、`allocate_budget`、`_assemble` |
| P0 | `pipeline/understand_text.py` | 159-220 | `annotate()`、`run()` |
| P0 | `aicut.py` | 47-80, 156-185, 243-282, 361-378, 534-550, 597-607, 734-780 | 输出助手、`check_or_die`、`cmd_new/text/score/select/build/prepare`、`run_cli`、argparse |
| P0 | `gui/server.py` | 126-167, 240-251, 579-597, 638-653 | `project_state`、`start_job` 任务表、`/api/new`、`/api/job` |
| P0 | `gui/static/index.html` | 119-128, 204-219, 449-475, 501-539 | 顶栏/按钮、`refresh`、`startJob/pollJob`、新建项目弹窗 |
| P0 | `pipeline/schema.py` | 95-143 | M1 的 `check_*` 白名单校验写法（新增 `check_target_duration` 照抄） |
| P1 | `tests/conftest.py` | all | `gui_server` fixture、`call()`、`make_project()` |
| P1 | `tests/test_server_security.py` | 141-180 | `recorder` fixture：替换 `start_job`/`run_aicut` 记录调用 |
| P1 | `tests/test_aicut_guards.py` | 1-60 | 直接调 `aicut.cmd_*(Namespace(...))`，`monkeypatch` `PROJECTS`、`_fail` |
| P1 | `tests/test_static_pages.py` | 1-40, 77-80 | 前端源码文本断言 |
| P1 | `pipeline/review.py` | 23-41, 85-100 | `load()` 损坏抛 `OverridesCorrupt`；`apply()` 写入 `must_keep` |
| P1 | `gui/static/common.js` | 25-29 | `esc()`、`num()`——所有动态值必须过它们 |
| P2 | `docs/PRD-AI粗剪工具.md` | 166-196 | FR-5、FR-7 |

## External Documentation

No external research needed — feature uses established internal patterns（标准库 + pytest，无新依赖）。

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: pipeline/select.py:19-21
HARD_TYPES = {"金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"}
MIN_SHOT = 1.5      # 最短镜头
MAX_SHOT = 25.0     # 最长镜头，超过就截断（访谈镜头可以长一点）
```

### VALIDATION（M1 新模式：schema 白名单 + CLI `check_or_die` + 服务端 400）
```python
# SOURCE: pipeline/schema.py:95-97, 126-129
PROJECT_NAME_MAX = 100
PROJECT_NAME_ERROR = (
    f"项目名不能以 - 或 . 开头，不能含斜杠或控制字符，最长 {PROJECT_NAME_MAX} 字")
...
def check_version(version: Any) -> str:
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ValueError(f"版本号格式应为 v+数字（如 v3），收到 {version!r}")
    return version

# SOURCE: aicut.py:74-79
def check_or_die(check, value) -> None:
    """调用 schema 的白名单校验；不合法就 die（GL-06）。"""
    try:
        check(value)
    except ValueError as exc:
        die(str(exc))

# SOURCE: gui/server.py:643-653
            try:
                existing_project(name)
                if task == "build":
                    v = body.get("version")
                    if v:
                        extra += ["--version", schema.check_version(v)]
                ...
                job_id = start_job(name, task, extra)
            except (ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)
```

### ERROR_HANDLING
```python
# SOURCE: pipeline/llm.py:22-23
class LLMError(RuntimeError):
    """LLM 调用的终态失败。"""

# SOURCE: pipeline/review.py:23-24
class OverridesCorrupt(ValueError):
    """overrides.json 读不出来：不能当空，否则下一次裁决会把人工结果全部覆盖。"""
```
pipeline 抛带中文人话的领域异常；`aicut.py` 捕获后 `die()`。

### LOGGING_PATTERN
```python
# SOURCE: aicut.py:47-57
def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)

def info(msg: str) -> None:
    print(f"[·] {msg}")

def ok(msg: str) -> None:
    print(f"[✓] {msg}")
```
新增同格式 `warn()` → `[!]`。GUI 任务日志就是这些行（`gui/server.py:298-312` 逐行收集）。

### FORCED_SHOT
```python
# SOURCE: pipeline/select.py:152-156
            shots.append({"segment_id": seg["id"], "topic": seg.get("topic") or "未归类",
                          "start": start, "end": end, "dur": round(end - start, 2),
                          "sub": (seg.get("text") or "")[:28],
                          "reason": "剪辑员指定必须保留", "score": _score(seg, weights),
                          "forced": True})
```
`_trim` 已保护 `forced`（`select.py:130-132`）。

### GUI_JOB（任务表 + 前端调用）
```python
# SOURCE: gui/server.py:245-250
    cmds = {
        "prepare": ["prepare", name],
        "build": ["build", name] + (extra or []),
    }
    if task not in cmds:
        raise ValueError("未知任务")
```
```js
// SOURCE: gui/static/index.html:449-457, 464-466
function startJob(task, extra){
  if(!state.project){ toast('先选项目'); return; }
  ...
  const body = {project: state.project, task, ...(extra||{})};
  showModal(task==='prepare'?'正在处理素材':'正在生成成片', '<div class="log" id="log">准备中…</div>');
  api('/api/job', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
...
      if(j.status==='done'){
        logLine('\n[完成]');
        setTimeout(async ()=>{ closeModal(); await refresh(); toast(task==='build'?'新版本已生成':'处理完成'); }, 700);
```
前端动态值一律 `esc()`/`num()`（`common.js:25-29`），内联事件里不许插值（`tests/test_static_pages.py:46-49`）。

### TEST_STRUCTURE
```python
# SOURCE: tests/test_select.py:8-11
def seg(i, start, dur, topic, *, level=3, key=False, must=False, text="", info=""):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur, "topic": topic,
            "level": level, "key_info": key, "must_keep": must,
            "info_type": info, "text": text or f"第{i}句", "signals": {}}

# SOURCE: tests/test_aicut_guards.py:49-55
def test_build_rejects_traversal_version(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    _make_project(tmp_path)
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version="../../evil", no_draft=True))

# SOURCE: tests/test_server_security.py:176-180
def test_job_accepts_valid(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job",
                        {"project": "p1", "task": "build", "version": "v2"})
    assert status == 200
    assert recorder["start_job"] == [("p1", "build", ["--version", "v2"])]
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/select.py` | UPDATE | GL-08 必留整段强制、守卫、`must_keep_total/over_target/suggested_target`；`run()` 按新目标重分话题预算；`uncovered_must_keep()`（GL-25） |
| `pipeline/classify.py` | UPDATE | GL-09b 标注失败→待定、超限不降必留；GL-24 暗画面不降必留 |
| `pipeline/understand_text.py` | UPDATE | GL-09a 重试/补问、`annotation_failed`、`complete/input_hash`、只补跑失败句 |
| `pipeline/schema.py` | UPDATE | `check_target_duration()` + 上下限常量 |
| `aicut.py` | UPDATE | `warn()`；`new --target`+询问；`select --target`；`cmd_text/score/select` 报告；`cmd_build` 必留校验 |
| `gui/server.py` | UPDATE | `/api/new` 收 `target`；`select` 任务；`project_state` 增 `selection`、分镜表预填 |
| `gui/static/index.html` | UPDATE | 新建项目时长输入；「改目标时长」按钮与弹窗；任务结束后必留超时长弹窗 |
| `tests/test_select.py` | UPDATE | GL-08 回归、随机不变量、重分预算、`uncovered_must_keep` |
| `tests/test_classify.py` | UPDATE | GL-09b、GL-24；改写固化 bug 的旧测试 |
| `tests/test_understand_text.py` | UPDATE | GL-09a；修正 2 个依赖旧行为的测试 |
| `tests/test_schema.py` | UPDATE | `check_target_duration` |
| `tests/test_aicut_must_keep.py` | CREATE | CLI：`new/select --target`、`text` 失败、`build` 必留校验 |
| `tests/test_server_target.py` | CREATE | `/api/new` target、`/api/job select`、`/api/state` selection/预填 |
| `tests/test_static_pages.py` | UPDATE | 新 UI 文案常量与转义 |
| `docs/go-live-blockers.md` | UPDATE（完成后） | GL-08/09/24/25 → fixed |

## NOT Building

- KI-05 的确认页部分（确认页入口、答案提交后自动选段、prepare 顺序调整）。本里程碑只新增 `select` 任务类型和改目标时长入口，KI-05 以后可复用。
- 选段结果**覆盖**已手存的 `shots.json`（只在没有 `shots.json` 时预填）；是否加「用新选段替换分镜表」按钮见 Notes。
- KI-01（字幕 28 字）、KI-03（must_lines 碎片）、KI-23（匹配不到不提示）、KI-09/KI-10/KI-25、KI-12。
- GL-22（任务失败模态层关不掉）、GL-17（任务互斥）、GL-20（`ask_calibration` 的 `input()` 卡死）——M4。
- 已完成的 text 再次运行时跳过 LLM（现状：成功后重跑仍全量）；本里程碑只做「上次未完成 → 只补失败句」。
- `--allow-missing-must` 之类绕过 GL-25 的开关（剪辑师可在浏览页取消★）。

---

## Step-by-Step Tasks

> TDD：每个任务先写测试 → `uv run pytest <file> -q` 看到 RED → 实现 → GREEN → 全量 `uv run pytest`。

### Task 1: 目标时长校验（schema）
- **ACTION**: `pipeline/schema.py` 在 `check_version` 之后新增；`tests/test_schema.py` 追加测试。
- **TEST FIRST**:
```python
@pytest.mark.parametrize("raw, expected", [(175, 175), ("240", 240), (59.6, 60), (" 90 ", 90)])
def test_check_target_duration_accepts(raw, expected):
    assert schema.check_target_duration(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 0, -5, 9, 3601, True, float("nan"), [1]])
def test_check_target_duration_rejects(raw):
    with pytest.raises(ValueError, match="目标时长"):
        schema.check_target_duration(raw)
```
- **IMPLEMENT**:
```python
TARGET_MIN, TARGET_MAX = 10, 3600  # 秒；成片时长由剪辑师决定，这里只挡明显的误输入
TARGET_ERROR = f"目标时长应为 {TARGET_MIN}–{TARGET_MAX} 秒之间的数字"


def check_target_duration(value: Any) -> int:
    """剪辑师填写的目标时长（秒）→ 整数秒。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{TARGET_ERROR}，收到 {value!r}")
    try:
        sec = float(value.strip() if isinstance(value, str) else value)
    except ValueError as exc:
        raise ValueError(f"{TARGET_ERROR}，收到 {value!r}") from exc
    if sec != sec or not TARGET_MIN <= round(sec) <= TARGET_MAX:  # sec != sec 即 NaN
        raise ValueError(f"{TARGET_ERROR}，收到 {value!r}")
    return int(round(sec))
```
- **MIRROR**: VALIDATION。
- **GOTCHA**: `bool` 是 `int` 子类，必须先排除；上下限是**护栏**不是产品限制，文案常量化。
- **VALIDATE**: `uv run pytest tests/test_schema.py -q`。

### Task 2: GL-08 选段回归测试（RED）
- **ACTION**: `tests/test_select.py` 顶部加 `import random`，末尾追加。
- **IMPLEMENT**:
```python
def _ids(res):
    return [s["segment_id"] for s in res["shots"]]


def test_must_keep_survives_zero_topic_budget():
    segs = [seg(1, 0, 6, "聊吃饭", level=2, must=True)]
    topics = [{"name": "讲合同", "budget": 20}, {"name": "聊吃饭", "budget": 0}]
    assert "S001" in _ids(select.select(segs, topics, {}, 60))


def test_must_keep_survives_excluded_topic():
    segs = [seg(1, 0, 6, "聊吃饭", must=True)]
    res = select.select(segs, TOPICS, {"exclude_topics": ["聊吃饭"]}, 60)
    assert "S001" in _ids(res)  # 必留优先于「哪些不能出现」


def test_must_keep_survives_budget_exhaustion():
    segs = [seg(i, i * 10, 6, "讲合同", must=True) for i in range(1, 6)]
    res = select.select(segs, [{"name": "讲合同", "budget": 10}], {}, 120)
    assert set(_ids(res)) >= {f"S{i:03d}" for i in range(1, 6)}


def test_must_keep_over_target_never_trimmed_and_reported():
    segs = [seg(i, i * 10, 6, "讲合同", must=True) for i in range(1, 6)]
    res = select.select(segs, [{"name": "讲合同", "budget": 100}], {}, 12)  # 必留 30s > 目标 12s
    assert set(_ids(res)) == {f"S{i:03d}" for i in range(1, 6)}
    assert res["must_keep_total"] == 30.0
    assert res["over_target"] is True
    assert res["suggested_target"] == 30
    assert res["warnings"] and "必留内容共" in res["warnings"][0]


def test_suggested_target_rounds_up_to_step():
    segs = [seg(1, 0, 31.2, "讲合同", must=True)]
    res = select.select(segs, TOPICS, {}, 12)
    assert res["suggested_target"] == 35  # 向上取整到 TARGET_ROUND_STEP=5


def test_must_keep_kept_whole_not_clipped_by_budget_or_max_shot():
    res = select.select([seg(1, 0, 30, "讲合同", must=True)], [{"name": "讲合同", "budget": 10}], {}, 60)
    shot = next(s for s in res["shots"] if s["segment_id"] == "S001")
    assert (shot["start"], shot["end"]) == (0.0, 30.0)


def test_short_must_keep_not_dropped_by_min_shot():
    res = select.select([seg(1, 0, 1.0, "讲合同", must=True), seg(2, 10, 6, "讲合同")], TOPICS, {}, 60)
    assert "S001" in _ids(res)


def test_must_keep_shot_marked_forced_with_reason():
    res = select.select([seg(1, 0, 6, "讲合同", must=True)], TOPICS, {}, 60)
    shot = next(s for s in res["shots"] if s["segment_id"] == "S001")
    assert shot["forced"] is True and shot["must_keep"] is True
    assert shot["reason"].startswith(select.MUST_KEEP_REASON)
    assert res["must_keep_ids"] == ["S001"] and res["over_target"] is False


def test_within_target_has_no_warning():
    res = select.select([seg(1, 0, 6, "讲合同", must=True), seg(2, 10, 6, "讲合同")], TOPICS, {}, 12)
    assert res["warnings"] == []


def test_guard_raises_when_must_keep_lost(monkeypatch):
    monkeypatch.setattr(select, "_ensure_must_keep", lambda segs, shots, w: shots)
    segs = [seg(1, 0, 6, "聊吃饭", level=2, must=True)]
    with pytest.raises(select.SelectionError, match="S001"):
        select.select(segs, [{"name": "聊吃饭", "budget": 0}], {}, 60)


def test_markdown_lists_warnings():
    segs = [seg(i, i * 10, 6, "讲合同", must=True) for i in range(1, 6)]
    res = select.select(segs, [{"name": "讲合同", "budget": 100}], {}, 12)
    assert "## 警告" in select.markdown(res)


def test_must_keep_invariant_randomized():
    rng = random.Random(20261019)
    names = ["讲合同", "聊吃饭", "谈价格", "未归类"]
    for _ in range(300):
        segs = [seg(i, i * 12.0, round(rng.uniform(0.5, 40), 1), rng.choice(names),
                    level=rng.choice([1, 2, 3]), key=rng.random() < 0.3,
                    must=rng.random() < 0.2) for i in range(1, rng.randint(2, 40))]
        topics = [{"name": n, "budget": rng.choice([0, 5, 10, 30, 80])} for n in names[:3]]
        rules = {"exclude_topics": rng.sample(names[:3], rng.randint(0, 2)),
                 "must_topics": rng.sample(names[:3], rng.randint(0, 1))}
        res = select.select(segs, topics, rules, rng.choice([10, 30, 60, 175]))
        must = {s["id"] for s in segs if s["must_keep"]}
        assert must <= set(_ids(res)), "必留进片率必须 100%"
        whole = {s["id"]: (s["start"], s["end"]) for s in segs if s["must_keep"]}
        for shot in res["shots"]:
            if shot["segment_id"] in whole:
                assert (shot["start"], shot["end"]) == tuple(round(x, 2) for x in whole[shot["segment_id"]])


def test_run_reallocates_budget_when_target_changed(tmp_path, monkeypatch):
    topics = [{"name": "讲合同", "must": True, "usable_dur": 120, "budget": 20}]
    scored = {"target": 30, "topics": topics, "segments": [seg(1, 0, 6, "讲合同")]}
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    seen = {}

    def fake_select(segments, topics, rules, target, weights=None):
        seen["budget"], seen["target"] = topics[0]["budget"], target
        return select.select(segments, topics, rules, target, weights)

    monkeypatch.setattr(select, "select", fake_select)
    select.run(sp, tmp_path / "a.json", tmp_path, target=300)
    assert seen["target"] == 300 and seen["budget"] > 20  # 按新目标重分，不需要重跑 score
    assert json.loads(sp.read_text(encoding="utf-8"))["topics"][0]["budget"] == 20  # 不改 scored 文件


def test_uncovered_must_keep_reports_missing_segments():
    segs = [seg(1, 0, 6, "讲合同", must=True), seg(2, 10, 6, "讲合同", must=True),
            seg(3, 20, 6, "讲合同")]
    shots = [{"id": "sh01", "in": 0.0, "out": 6.0}, {"id": "sh02", "in": 10.0, "out": 12.0}]
    missing = select.uncovered_must_keep(segs, shots)
    assert [m["id"] for m in missing] == ["S002"]  # 只覆盖 2/6 秒不算进片


def test_uncovered_must_keep_accepts_split_coverage():
    segs = [seg(1, 0, 10, "讲合同", must=True)]
    shots = [{"id": "a", "in": 0.0, "out": 5.0}, {"id": "b", "in": 5.0, "out": 9.5}]
    assert select.uncovered_must_keep(segs, shots) == []  # 两镜拼起来覆盖 95%
```
- **GOTCHA**: budget=0 用例必须 `level=2`（`level=3` 会被补齐阶段 `select.py:228` 捞回，测试假绿，已实测）。
- **VALIDATE**: `uv run pytest tests/test_select.py -q` → 新测试 RED。

### Task 3: GL-08 实现（GREEN）
- **ACTION**: 修改 `pipeline/select.py`。
- **IMPLEMENT**:
  1. 常量区（`:19-21` 之后）：
```python
MUST_KEEP_REASON = "剪辑师标记必留"
TOTAL_TOLERANCE = 1.10      # PRD FR-7：总时长 ±10%
TARGET_ROUND_STEP = 5       # 建议目标时长向上取整到 5 秒
MUST_KEEP_COVER_RATIO = 0.9  # 分镜表覆盖必留段 ≥90% 才算进片（容忍手动打点误差）
MUST_KEEP_OVER_WARNING = "必留内容共 {must}，超过目标 {target}：已全部保留，请重新设定成片时长"


class SelectionError(RuntimeError):
    """选段结果违反硬约束（必留段丢失）。"""


def fmt_duration(sec: float) -> str:
    """给人看的时长：「3 分 34 秒」/「45 秒」。"""
    sec = int(round(sec))
    return f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"
```
  2. `_force_lines` 之前：
```python
def _must_keep_shot(seg: dict, weights: dict | None) -> dict:
    start, end = round(float(seg["start"]), 2), round(float(seg["end"]), 2)
    why = seg.get("level_reason") or ""
    return {"segment_id": seg["id"], "topic": seg.get("topic") or "未归类",
            "start": start, "end": end, "dur": round(end - start, 2),
            "sub": (seg.get("text") or "")[:28],
            "reason": MUST_KEEP_REASON + (f"；{why}" if why else ""),
            "score": _score(seg, weights), "forced": True, "must_keep": True}


def _ensure_must_keep(segments: list[dict], shots: list[dict],
                      weights: dict | None) -> list[dict]:
    """必留段无视档位/话题/预算/exclude/镜头长度，一律整段进片；已入选但被截短的恢复整段。"""
    must = {s["id"]: s for s in segments if s.get("must_keep")}
    kept = [x for x in shots if x["segment_id"] not in must]
    restored = [_must_keep_shot(seg, weights) for seg in must.values()]
    return sorted(kept + restored, key=lambda x: x["start"])


def uncovered_must_keep(segments: list[dict], shots: list[dict]) -> list[dict]:
    """GL-25：按时间核对分镜表（in/out）是否覆盖每个必留段，返回没覆盖到的段。"""
    spans = sorted((float(s["in"]), float(s["out"])) for s in shots)
    missing = []
    for seg in (s for s in segments if s.get("must_keep")):
        start, end = float(seg["start"]), float(seg["end"])
        covered = sum(max(0.0, min(end, b) - max(start, a)) for a, b in spans)
        if covered < (end - start) * MUST_KEEP_COVER_RATIO:
            missing.append(seg)
    return missing
```
  3. `select()` 第 276-280 行：
```python
    shots.sort(key=lambda x: x["start"])

    shots = _ensure_must_keep(segments, shots, weights)
    shots, total = _trim(shots, target)
    shots = _force_lines(segments, shots, rules.get("must_lines") or [], target, weights)
    total = sum(x["dur"] for x in shots)
```
  4. `used_ids`（`:286`）之后、`return` 之前：
```python
    must_ids = [s["id"] for s in segments if s.get("must_keep")]
    lost = [i for i in must_ids if i not in used_ids]
    if lost:
        raise SelectionError(f"必留段未进片：{', '.join(lost)}")
    must_total = round(sum(x["dur"] for x in shots if x.get("must_keep")), 2)
    for topic in {x["topic"] for x in shots if x.get("must_keep")}:
        if topic not in covered:
            covered.append(topic)
    over = must_total > target
    warnings = []
    if over:
        warnings.append(MUST_KEEP_OVER_WARNING.format(must=fmt_duration(must_total),
                                                      target=fmt_duration(target)))
    elif total > target * TOTAL_TOLERANCE:
        warnings.append(f"成片 {fmt_duration(total)} 超出目标 {fmt_duration(target)} 的 +10%")
    suggested = int(-(-must_total // TARGET_ROUND_STEP) * TARGET_ROUND_STEP) if over else None
```
     返回 dict 追加：`"must_keep_ids": must_ids, "must_keep_total": must_total, "over_target": over, "suggested_target": suggested, "warnings": warnings,`；`stats` 追加 `"must_keep": len(must_ids)`。
  5. `markdown()`（`:366` 之前）：
```python
    if selection.get("warnings"):
        lines += ["", "## 警告", ""]
        lines += [f"- {w}" for w in selection["warnings"]]
```
  6. `run()`（`:393-399`）：目标与 scored 时不同则按新目标重分话题预算（复制，不改文件）：
```python
    target = float(target or scored.get("target") or 175)
    topics = scored.get("topics", [])
    if target != float(scored.get("target") or 0) and all(
            "must" in t and "usable_dur" in t for t in topics):
        topics = classify.allocate_budget([dict(t) for t in topics], target)
    ...
    result = select(segments, topics, rules, target, weights)
```
     顶部 `from pipeline import classify, review`。
- **GOTCHA**:
  - `over_target` 定义为**必留合计 > 目标**（用户要求的触发条件）；必留之外的超时（如 KI-03 must_lines 碎片）只进 `warnings`，不触发改时长弹窗。
  - `_trim` 的 `len(pool) <= 1` 时 break（`:133`），全是必留时 `total` 会超标——期望行为。
  - `_build_hook/_fix_ending` 只重排不删（`:307-345`），不要在它们之后再调 `_ensure_must_keep`。
  - `allocate_budget` 原地改传入的 dict（`classify.py:115-133`），必须传副本。`classify` 不 import `select`，无循环导入。
  - `suggested` 向上取整：`-(-x // step) * step`。
- **VALIDATE**: `uv run pytest tests/test_select.py -q` 全绿。

### Task 4: GL-09a 测试：重试、落盘、只补跑失败句（RED）
- **ACTION**: `tests/test_understand_text.py`；顶部加 `import pytest`。
- **IMPLEMENT**:
  1. 改写 `test_failed_batch_recorded_but_others_kept`（`:78-83`，旧断言固化了静默丢弃）：
```python
def test_failed_batch_retried_then_succeeds(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    client = FakeClient(fail_batches={0})
    res = ut.run(sp, tmp_path / "o.json", client=client, batch=40)
    assert res["failures"] == [] and res["complete"] is True
    assert not any(s["annotation_failed"] for s in res["segments"])
    assert client.annotate_calls == 3  # 第 1 批失败 1 次 + 重试 1 次 + 第 2 批 1 次
```
  2. 修正 `test_missing_segments_fall_back_to_last_topic`（`:63-75`）：`Partial` 标注分支改为 `return FakeClient.chat_json(self, system, user, **kw)`（该测试只验证话题兜底）。
  3. 新增：
```python
class StubbornClient(FakeClient):
    """含指定 id 的批次永远失败 / 永远漏标指定 id，并附带一个编造的 id。"""

    def __init__(self, *, fail_if=(), omit=()):
        super().__init__()
        self.fail_if, self.omit = set(fail_if), set(omit)

    def chat_json(self, system, user, **kw):
        ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
        if "归并成" not in user and self.fail_if & set(ids):
            self.calls += 1
            self.annotate_calls += 1
            from pipeline.llm import LLMError
            raise LLMError("mock persistent failure")
        data = super().chat_json(system, user, **kw)
        if "segments" in data:
            data = {"segments": [x for x in data["segments"] if x["id"] not in self.omit]
                    + [{"id": "S999", "info_type": "金额价格", "key_info": True}]}
        return data


def test_persistent_failure_saves_then_raises(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(ut.AnnotationIncomplete) as exc:
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    assert exc.value.ids[0] == "S001" and len(exc.value.ids) == 40
    assert "只会重跑" in str(exc.value)
    saved = json.loads(out.read_text(encoding="utf-8"))  # 先落盘
    assert saved["complete"] is False and saved["input_hash"]
    flags = {s["id"]: s["annotation_failed"] for s in saved["segments"]}
    assert flags["S001"] is True and flags["S041"] is False


def test_rerun_only_reannotates_failed_segments(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(ut.AnnotationIncomplete):
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    healthy = FakeClient()
    res = ut.run(sp, out, client=healthy, batch=40)
    assert res["complete"] is True and res["resumed"] is True
    assert healthy.calls == 1  # 不再做话题分段，只补 1 批（S001–S040）
    assert [t["name"] for t in res["topics"]] == ["开场寒暄", "讲解合同"]


def test_rerun_with_changed_input_does_full_run(tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": make_segments(50)}), encoding="utf-8")
    out = tmp_path / "o.json"
    with pytest.raises(ut.AnnotationIncomplete):
        ut.run(sp, out, client=StubbornClient(fail_if={"S001"}), batch=40)
    healthy = FakeClient()
    ut.run(sp, out, client=healthy, batch=40, style="新偏好")  # 输入变了 → 不能复用旧结果
    assert healthy.calls == 1 + 2  # 1 次话题分段 + 2 批标注（全量）


def test_retry_count_bounded():
    client = StubbornClient(fail_if={"S001"})
    _, failures = ut.annotate(client, make_segments(5), batch=40)
    assert client.annotate_calls == ut.ANNOTATE_RETRIES + 1
    assert "mock persistent failure" in failures[0]["error"]


def test_missing_ids_rerequested_only_for_gaps():
    class OnceOmit(FakeClient):
        def chat_json(self, system, user, **kw):
            data = super().chat_json(system, user, **kw)
            if self.annotate_calls == 1:
                data = {"segments": [x for x in data["segments"] if x["id"] != "S003"]}
            return data

    client = OnceOmit()
    result, failures = ut.annotate(client, make_segments(5), batch=40)
    assert failures == [] and "S003" in result and client.annotate_calls == 2


def test_permanently_missing_id_flagged_alone():
    result, failures = ut.annotate(StubbornClient(omit={"S003"}), make_segments(5), batch=40)
    assert [f["ids"] for f in failures] == [["S003"]] and "漏标" in failures[0]["error"]
    assert "S999" not in result  # 模型编造的 id 不进结果
```
- **GOTCHA**: `FakeClient.fail_batches` 按**调用序号**，重试会占序号；持久失败用 `StubbornClient` 按 id 判定，并在抛错分支手动累加 `calls/annotate_calls`。
- **VALIDATE**: RED。

### Task 5: GL-09a 实现（GREEN）
- **ACTION**: `pipeline/understand_text.py:159-220`；模块 docstring 第 11 行改为「批处理失败先重试；仍失败的句子标 annotation_failed、结果落盘后报错，重跑只补这些句子」。
- **IMPLEMENT**:
```python
import hashlib

ANNOTATE_RETRIES = 2  # 每批在客户端 HTTP 重试之外，再整批/补漏重试的次数（覆盖 JSON 解析失败、漏 id）
ANNOTATION_RETRY_HINT = "结果已保存；检查网络/额度后重新运行「处理素材」，只会重跑这 {n} 句"
_ANN_KEYS = ("info_type", "key_info", "entities", "reason")


class AnnotationIncomplete(LLMError):
    """逐句标注重试后仍有句子没拿到结果——不能当作「无关键信息」继续往下走。"""

    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        head = ", ".join(ids[:10]) + ("…" if len(ids) > 10 else "")
        super().__init__(f"{len(ids)} 句逐句标注失败（每批已重试 {ANNOTATE_RETRIES} 次）：{head}；"
                         + ANNOTATION_RETRY_HINT.format(n=len(ids)))


def _normalize(item: dict) -> dict:
    return {"info_type": str(item.get("info_type") or "事实陈述")[:12],
            "key_info": bool(item.get("key_info")),
            "entities": [str(e)[:30] for e in (item.get("entities") or [])][:8],
            "reason": str(item.get("reason") or "")[:40]}


def _annotate_once(client, chunk: list[dict], style: str) -> dict[str, dict]:
    prompt = ANNOTATE_USER.format(listing=_listing(chunk))
    if style:
        prompt = f"{prompt}\n\n{style}"
    data = client.chat_json(ANNOTATE_SYSTEM, prompt, temperature=0.1, max_tokens=4000)
    wanted = {s["id"] for s in chunk}
    return {item["id"]: _normalize(item) for item in data.get("segments") or []
            if item.get("id") in wanted}


def annotate(client, segments: list[dict], *, batch: int = 40, style: str = "",
             retries: int = ANNOTATE_RETRIES) -> tuple[dict, list[dict]]:
    result: dict[str, dict] = {}
    failures: list[dict] = []
    for chunk in _chunks(segments, batch):
        todo, error = list(chunk), ""
        for _ in range(retries + 1):
            try:
                got = _annotate_once(client, todo, style)
            except LLMError as exc:
                error = str(exc)[:200]
                continue
            result = {**result, **got}
            todo = [s for s in todo if s["id"] not in got]
            if not todo:
                break
            error = f"模型漏标 {len(todo)} 句"
        if todo:
            failures.append({"ids": [s["id"] for s in todo], "error": error})
    return result, failures


def _fingerprint(segments: list[dict], style: str, model: str) -> str:
    payload = json.dumps([[s["id"], s.get("text", "")] for s in segments] + [style, model],
                         ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _resumable(out_path: Path, fingerprint: str) -> dict | None:
    """上次未完成且输入没变 → 可以只补失败句子。"""
    try:
        prev = json.loads(Path(out_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = isinstance(prev, dict) and prev.get("complete") is False \
        and prev.get("input_hash") == fingerprint
    return prev if ok else None
```
  `run()`：
```python
    client = client or DeepSeekClient()
    label = model or getattr(client, "model", "")
    fp = _fingerprint(segments, style, label)
    prev = _resumable(out_path, fp)
    if prev:
        topics = prev["topics"]
        done = {s["id"]: {k: s[k] for k in _ANN_KEYS}
                for s in prev["segments"] if not s.get("annotation_failed")}
        fresh, failures = annotate(client, [s for s in usable if s["id"] not in done],
                                   batch=batch, style=style)
        annotations = {**done, **fresh}
    else:
        topics = segment_topics(client, usable)
        annotations, failures = annotate(client, usable, batch=batch, style=style)
    failed = {sid for f in failures for sid in f["ids"]}
    ... merged 每项追加 "annotation_failed": s["id"] in failed
    result = {"model": label, "topics": topics, "failures": failures,
              "complete": not failed, "input_hash": fp, "resumed": bool(prev),
              "segments": merged}
    （写文件不变）
    if failed:
        raise AnnotationIncomplete(sorted(failed))
    return result
```
- **GOTCHA**:
  - **先写文件再抛**。旧版 `segments_text.json` 没有 `complete` 字段 → 不续跑，全量重跑（兼容）。
  - 续跑时 `done` 里可能有空文本句（从未送模型），字段齐全，无害。
  - 只对 `LLMError` 重试；`RemoteDisconnected` 等（KI-25）照旧冒泡，本来就不静默。
- **VALIDATE**: `uv run pytest tests/test_understand_text.py -q` 全绿；`test_batching_splits_calls` 仍 `1 + 3`。

### Task 6: GL-09b + GL-24 测试（RED）
- **ACTION**: `tests/test_classify.py`。
- **IMPLEMENT**:
  1. 改写 `test_pending_capped_by_ratio`（`:48-51`，话题「讲解合同」是必留话题，旧断言固化 bug）：
```python
def test_non_must_pending_capped_by_ratio():
    segs = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="闲聊日常") for i in range(1, 61)]
    res = classify.classify(segs)
    limit = max(10, int(60 * classify.MAX_PENDING_RATIO))
    assert res["summary"]["pending"] == limit
    assert res["pending"] == {"limit": limit, "demoted": 60 - limit}
    assert res["warnings"] == []
```
  2. 新增：
```python
def test_must_topic_pending_never_demoted():
    segs = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="讲解合同") for i in range(1, 61)]
    res = classify.classify(segs)
    assert res["summary"]["pending"] == 60
    assert res["warnings"] and "不自动降级" in res["warnings"][0]


def test_over_limit_demotes_only_non_must():
    must = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="讲解合同") for i in range(1, 31)]
    other = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="闲聊日常") for i in range(31, 61)]
    res = classify.classify(must + other)
    lv = {(s["topic"], s["level"]) for s in res["segments"]}
    assert ("讲解合同", 1) not in lv and ("闲聊日常", 2) not in lv


def test_key_ratio_must_topic_also_protected():
    key = [seg(i, i * 10, key_info=True, topic="建议选养生") for i in range(1, 21)]
    pend = [seg(i, i * 10, dur=8, info_type="事实陈述", topic="建议选养生") for i in range(21, 61)]
    assert classify.classify(key + pend)["summary"]["pending"] == 40


def test_annotation_failed_becomes_pending_with_reason():
    s = classify.classify([seg(1, 0, dur=2.0, annotation_failed=True, info_type="")])["segments"][0]
    assert s["level"] == 2 and "标注失败" in s["level_reason"]


def test_annotation_failed_not_demoted_when_over_limit():
    segs = [seg(i, i * 10, dur=8, annotation_failed=True, topic="闲聊日常") for i in range(1, 61)]
    assert classify.classify(segs)["summary"]["pending"] == 60


def test_loud_annotation_failed_segment_still_usable():
    res = classify.classify([seg(1, 0, dur=6, annotation_failed=True)], {"S001": {"rel_db": 5.0}})
    assert res["segments"][0]["level"] == 3


DARK = {"S001": {"flags": ["dark"]}}


def test_dark_must_topic_pending_stays_pending():  # GL-24
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述", topic="讲解合同")],
                            visual_by_id=DARK)
    s = res["segments"][0]
    assert s["level"] == 2 and "画面过暗" in s["level_reason"]


def test_dark_annotation_failed_stays_pending():  # GL-24
    res = classify.classify([seg(1, 0, dur=8, annotation_failed=True)], visual_by_id=DARK)
    assert res["segments"][0]["level"] == 2


def test_dark_non_must_pending_still_waste():
    res = classify.classify([seg(1, 0, dur=8, info_type="事实陈述", topic="闲聊日常")],
                            visual_by_id=DARK)
    assert res["segments"][0]["level"] == 1


def test_dark_usable_unchanged():
    res = classify.classify([seg(1, 0, key_info=True, topic="闲聊日常")], visual_by_id=DARK)
    assert res["segments"][0]["level"] == 3
```
- **GOTCHA**: 非必留话题名避开 `MUST_TOPIC_WORDS`（`classify.py:22-23`）；「闲聊日常」安全。`classify()` 的 `visual_by_id` 是第 5 个参数（`classify.py:65-68`），用关键字传。
- **VALIDATE**: RED。

### Task 7: GL-09b + GL-24 实现（GREEN）
- **ACTION**: `pipeline/classify.py`。
- **IMPLEMENT**:
```python
KEY_RATIO_MUST = 0.30  # 话题内关键信息句占比 ≥30% 也算必留话题
ANNOTATION_FAILED_REASON = "AI 标注失败，需要你判断"
PENDING_DEMOTED_REASON = "待定队列超限，按信息量判定为废片"
DARK_REASON = "画面过暗，不可用"
PENDING_OVER_WARNING = ("待定 {left} 段超过上限 {limit} 段：其中 {kept} 段属于必留话题或 AI 标注失败，"
                        "不自动降级，需要你逐条裁决")
```
  - `_level_of`：在 `if must_topic:`（`:52`）之前插入 `if seg.get("annotation_failed"): return 2, ANNOTATION_FAILED_REASON`。
  - 抽出共用判定（替换 `_assemble` `:153-155` 的内联逻辑，`_assemble` 改为 `item["must"] = item["name"] in must_names`）：
```python
def _must_topic_names(scored: list[dict]) -> set[str]:
    """必留话题 = 名称命中关键词，或话题内关键信息句占比 ≥ KEY_RATIO_MUST。"""
    count: dict[str, int] = {}
    keys: dict[str, int] = {}
    for s in scored:
        name = s.get("topic") or "未归类"
        count[name] = count.get(name, 0) + 1
        keys[name] = keys.get(name, 0) + (1 if s.get("key_info") else 0)
    return {n for n in count if _topic_must(n) or keys[n] / count[n] >= KEY_RATIO_MUST}


def _protected(s: dict, must_names: set[str]) -> bool:
    """必留话题段、标注失败段：只能人来判废片。"""
    return (s.get("topic") or "未归类") in must_names or bool(s.get("annotation_failed"))


def _apply_dark(s: dict, must_names: set[str]) -> dict:
    if "dark" not in s["visual_flags"] or s["level"] == 3:
        return s
    if _protected(s, must_names):
        return {**s, "level": 2, "level_reason": f"画面过暗；{s['level_reason']}"}
    return {**s, "level": 1, "level_reason": DARK_REASON}
```
  - `classify()` 主体（替换 `:76-98`）：
```python
    base = []
    for seg in segments:
        topic = seg.get("topic") or topic_of.get(seg["id"], "")
        lv, why = _level_of(seg, audio_by_id.get(seg["id"]), _topic_must(topic))
        flags = visual_by_id.get(seg["id"], {}).get("flags") or []
        base.append({**seg, "topic": topic, "level": lv, "level_reason": why,
                     "visual_flags": flags})
    must_names = _must_topic_names(base)
    scored = [_apply_dark(s, must_names) for s in base]

    limit = max(10, int(len(scored) * MAX_PENDING_RATIO))

    def weakness(s: dict) -> tuple:
        a = audio_by_id.get(s["id"], {})
        return (a.get("rel_db", 0), len(s.get("text", "")))

    pending = [s for s in scored if s["level"] == 2]
    excess = max(0, len(pending) - limit)
    demotable = sorted((s for s in pending if not _protected(s, must_names)), key=weakness)
    demote = {s["id"] for s in demotable[:excess]}
    scored = [{**s, "level": 1, "level_reason": PENDING_DEMOTED_REASON}
              if s["id"] in demote else s for s in scored]

    left = sum(1 for s in scored if s["level"] == 2)
    kept = sum(1 for s in scored if s["level"] == 2 and _protected(s, must_names))
    warnings = ([PENDING_OVER_WARNING.format(left=left, limit=limit, kept=kept)]
                if left > limit else [])
    result = _assemble(scored, total_target)
    return {**result, "pending": {"limit": limit, "demoted": len(demote)}, "warnings": warnings}
```
- **GOTCHA**: 不可变：用新 dict 替换，不原地改 `s["level"]`。`test_topic_with_high_key_info_ratio_is_must`（`tests/test_classify.py:96-103`）守住抽取后的阈值语义。
- **VALIDATE**: `uv run pytest tests/test_classify.py -q` 全绿。

### Task 8: CLI 测试（RED）——新建 `tests/test_aicut_must_keep.py`
- **ACTION**: 仿 `tests/test_aicut_guards.py` 的写法。
- **IMPLEMENT**（要点，均用 `monkeypatch.setattr(aicut, "PROJECTS", tmp_path)`）：
```python
import json
from argparse import Namespace

import pytest

import aicut
from pipeline import select, understand_text


def _fail(*_a, **_k):
    raise AssertionError("不应该被调用")


def _project(root, name="p", target=175, **work):
    pdir = root / name
    (pdir / "work").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "material": "/tmp/a.mp4", "schema_version": 2,
         "target_duration": target}), encoding="utf-8")
    for rel, obj in work.items():
        (pdir / "work" / rel).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return pdir


def _new_args(tmp_path, **kw):
    mat = tmp_path / "a.mp4"
    mat.write_bytes(b"x")
    base = dict(name="n1", material=str(mat), preset="纪实3min", title=None,
                tone="balanced", audience=None, must_lines=None, target=None)
    return Namespace(**{**base, **kw})


def test_new_stores_given_target(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    aicut.cmd_new(_new_args(tmp_path, target="240"))
    cfg = json.loads((tmp_path / "projects/n1/project.json").read_text(encoding="utf-8"))
    assert cfg["target_duration"] == 240


def test_new_without_target_noninteractive_uses_preset(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", _fail)
    aicut.cmd_new(_new_args(tmp_path))
    cfg = json.loads((tmp_path / "projects/n1/project.json").read_text(encoding="utf-8"))
    assert cfg["target_duration"] == 175  # 纪实3min 预设


def test_new_asks_target_in_terminal(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["abc", "300"])  # 先输错，再输对
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    aicut.cmd_new(_new_args(tmp_path))
    cfg = json.loads((tmp_path / "projects/n1/project.json").read_text(encoding="utf-8"))
    assert cfg["target_duration"] == 300


def test_new_rejects_bad_target(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
    with pytest.raises(SystemExit):
        aicut.cmd_new(_new_args(tmp_path, target="-5"))
    assert not (tmp_path / "projects/n1").exists()


def test_select_target_saves_and_only_reselects(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = _project(tmp_path, **{"segments_scored.json": {"segments": [], "topics": []}})
    for name in ("cmd_transcribe", "cmd_text", "cmd_score"):
        monkeypatch.setattr(aicut, name, _fail)
    monkeypatch.setattr(aicut.understand_text, "run", _fail)
    monkeypatch.setattr(aicut.classify, "run", _fail)
    seen = {}

    def fake_run(*a, target=None, **kw):
        seen["target"] = target
        return {"stats": {"shots": 3, "must_keep": 2}, "total": 300, "target": target,
                "missing_must_topics": [], "warnings": [], "over_target": False,
                "must_keep_total": 40, "suggested_target": None}

    monkeypatch.setattr(aicut.select, "run", fake_run)
    aicut.cmd_select(Namespace(name="p", target="300"))
    assert seen["target"] == 300
    assert json.loads((pdir / "project.json").read_text(encoding="utf-8"))["target_duration"] == 300


def test_select_over_target_prints_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, target=60, **{"segments_scored.json": {"segments": [], "topics": []}})
    monkeypatch.setattr(aicut.select, "run", lambda *a, **k: {
        "stats": {"shots": 5, "must_keep": 5}, "total": 214, "target": 60,
        "missing_must_topics": [], "warnings": ["必留内容共 3 分 34 秒，超过目标 1 分 0 秒：…"],
        "over_target": True, "must_keep_total": 214, "suggested_target": 215})
    aicut.cmd_select(Namespace(name="p", target=None))
    out = capsys.readouterr().out
    assert "[!]" in out and "--target 215" in out


def test_text_incomplete_dies(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    _project(tmp_path, **{"segments.json": {"segments": []}})
    monkeypatch.setattr(aicut.secrets, "get", lambda *_: "k")

    def boom(*a, **k):
        raise understand_text.AnnotationIncomplete(["S001", "S002"])

    monkeypatch.setattr(aicut.understand_text, "run", boom)
    with pytest.raises(SystemExit) as exc:
        aicut.cmd_text(Namespace(name="p", batch=40, model="m"))
    assert exc.value.code == 1
    assert "[x]" in capsys.readouterr().out


def _scored(*segs):
    return {"segments": [{"id": i, "start": s, "end": e, "level": 3, "text": t}
                         for i, s, e, t in segs], "topics": []}


def test_build_blocks_when_storyboard_misses_must_keep(monkeypatch, tmp_path, capsys):  # GL-25
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "ensure_clips", _fail)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S001", 0, 6, "开场"),
                                                                 ("S002", 10, 16, "九千八包含耗材")),
                                 "overrides.json": {"S002": {"must_keep": True}}})
    (pdir / "shots.json").write_text(json.dumps({"shots": [{"id": "sh01", "in": 0, "out": 6}]}),
                                     encoding="utf-8")
    with pytest.raises(SystemExit):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))
    out = capsys.readouterr().out
    assert "九千八包含耗材" in out and "00:10" in out


def test_build_proceeds_when_must_keep_covered(monkeypatch, tmp_path):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)

    class Reached(Exception):
        pass

    def stop(*_a, **_k):
        raise Reached

    monkeypatch.setattr(aicut, "ensure_clips", stop)
    pdir = _project(tmp_path, **{"segments_scored.json": _scored(("S002", 10, 16, "九千八")),
                                 "overrides.json": {"S002": {"must_keep": True}}})
    (pdir / "shots.json").write_text(json.dumps({"shots": [{"id": "sh01", "in": 10, "out": 16}]}),
                                     encoding="utf-8")
    with pytest.raises(Reached):
        aicut.cmd_build(Namespace(name="p", version=None, no_draft=True))


def test_build_without_analysis_skips_must_check(monkeypatch, tmp_path):
    """纯手工流程（没有 segments_scored.json）不应被拦。"""
    ...  # 同上，不写 segments_scored.json，断言走到 ensure_clips
```
- **GOTCHA**: `cmd_new` 没给 tone/audience/must_lines 时会调 `ask_calibration`（`aicut.py:166-168`），测试里给 `tone="balanced"` 绕开；`monkeypatch.setattr("sys.stdin.isatty", ...)` 要在 pytest 捕获下生效，实现中统一用 `sys.stdin.isatty()`。
- **VALIDATE**: RED。

### Task 9: CLI 实现（GREEN）
- **ACTION**: `aicut.py`。
- **IMPLEMENT**:
  1. 导入（`:33-35`）加 `review`；`ok()` 后加：
```python
def warn(msg: str) -> None:
    print(f"[!] {msg}")


TARGET_PROMPT = "想剪成多长的片子？（秒，回车用预设 {default} 秒）"
MUST_KEEP_OVER_HINT = ("必留内容共 {must}，超过目标 {target}。想剪成多长？"
                       "运行：aicut.py select {name} --target <秒>（建议 --target {suggest}）")
MUST_KEEP_MISSING = ("分镜表缺少 {n} 段必留内容：{items}；"
                     "在分镜表里加回，或在「浏览素材」取消★后再出片")
```
  2. `ask_target(default) -> int`（放在 `ask_calibration` 旁）：
```python
def ask_target(default: int) -> int:
    """在终端里问成片时长；非交互环境直接用预设值。"""
    if not sys.stdin.isatty():
        return default
    while True:
        raw = input(TARGET_PROMPT.format(default=default) + "\n  > ").strip()
        if not raw:
            return default
        try:
            return schema.check_target_duration(raw)
        except ValueError as exc:
            print(f"  {exc}")
```
  3. `cmd_new`（`:156-185`）：在 `pdir.mkdir` **之前**算目标（校验失败不留空目录）：
```python
    default_target = schema.check_target_duration(preset.get("duration") or 175)
    if args.target is not None:
        check_or_die(schema.check_target_duration, args.target)
        target = schema.check_target_duration(args.target)
    else:
        target = ask_target(default_target)
    ...
        target_duration=target,
```
     argparse（`:751-757`）：`p.add_argument("--target", default=None, help="成片目标时长（秒），默认用预设")`。
  4. `cmd_select`（`:361-378`）：
```python
    c = cfg(pdir)
    if getattr(args, "target", None) is not None:
        check_or_die(schema.check_target_duration, args.target)
        c["target_duration"] = schema.check_target_duration(args.target)
        schema.save(pdir / "project.json", c)
        info(f"目标时长已改为 {select.fmt_duration(c['target_duration'])}，只重跑选段")
    try:
        res = select.run(...同前..., target=float(c.get("target_duration") or 175))
    except select.SelectionError as exc:
        die(str(exc))
    msg = ...（同前）+ (f" · 必留 {res['stats']['must_keep']} 段" if res["stats"]["must_keep"] else "")
    ok(msg)
    if res["over_target"]:
        warn(MUST_KEEP_OVER_HINT.format(must=select.fmt_duration(res["must_keep_total"]),
                                        target=select.fmt_duration(res["target"]),
                                        name=args.name, suggest=res["suggested_target"]))
    for w in res["warnings"][1 if res["over_target"] else 0:]:
        warn(w)
```
     argparse（`:779-780`）：`p.add_argument("--target", default=None)`。`cmd_prepare` 透传同一个 `args`，prepare 的 Namespace 无 `target` 属性 → `getattr` 兜底。
  5. `cmd_text`（`:258-264`）：
```python
    try:
        res = understand_text.run(segs, work / "segments_text.json",
                                  batch=batch, model=model, style=pref)
    except understand_text.AnnotationIncomplete as exc:
        die(str(exc))
    key = sum(1 for x in res["segments"] if x["key_info"])
    ok(f"话题 {len(res['topics'])} 个 · 关键信息 {key} 句"
       + (" · 已补齐上次失败的句子" if res.get("resumed") else ""))
```
  6. `cmd_score`（`:279-282`）：追加 `· 自动降级 N`（`res["pending"]["demoted"]` 非 0 时），`for w in res["warnings"]: warn(w)`。
  7. `cmd_build`（`:546` `shots = spec["shots"]` 之后、`ensure_clips` 之前）：
```python
    _check_must_keep(pdir, shots)
```
     新函数：
```python
def _check_must_keep(pdir: Path, shots: list[dict]) -> None:
    """GL-25：出片前确认分镜表覆盖全部必留段；没有分析结果（纯手工流程）就不查。"""
    work = pdir / "work"
    scored = load_json(work / "segments_scored.json")
    if not scored:
        return
    try:
        segments = review.apply(scored["segments"], review.load(work))
    except review.OverridesCorrupt as exc:
        die(str(exc))
    missing = select.uncovered_must_keep(segments, shots)
    if missing:
        items = "；".join(f'{int(s["start"] // 60):02d}:{int(s["start"] % 60):02d} '
                         f'"{(s.get("text") or "")[:20]}"' for s in missing[:5])
        die(MUST_KEEP_MISSING.format(n=len(missing), items=items))
```
- **MIRROR**: LOGGING_PATTERN、VALIDATION。
- **GOTCHA**:
  - GUI 的 `/api/new` 总会传 `--target`，所以不会走到 `input()`；不要让这条路径加重 GL-20。
  - `run_cli` 把 `SystemExit(1)` 转成退出码 1（`aicut.py:734-744`），GUI 任务状态变 failed。
  - `cmd_build` 校验要在 `ensure_clips`（切片，耗时）之前。
- **VALIDATE**: `uv run pytest tests/test_aicut_must_keep.py tests/test_aicut_guards.py -q`。

### Task 10: GUI 服务测试（RED）——新建 `tests/test_server_target.py`
- **ACTION**: 复用 `tests/conftest.py` 的 `gui_server/call/make_project`，`recorder` fixture 照抄 `tests/test_server_security.py:142-155`。
- **IMPLEMENT**:
```python
def test_new_passes_target(gui_server, recorder):
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": "n1", "material": "/tmp/a.mp4", "preset": "纪实3min", "target": 240})
    assert status == 200
    assert "--target=240" in recorder["run_aicut"][0]


@pytest.mark.parametrize("bad", ["abc", -5, 99999, True])
def test_new_rejects_bad_target(gui_server, recorder, bad):
    status, _, _ = call(gui_server, "POST", "/api/new",
                        {"name": "n1", "material": "/tmp/a.mp4", "preset": "纪实3min", "target": bad})
    assert status == 400 and recorder["run_aicut"] == []


def test_job_select_with_target(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job", {"project": "p1", "task": "select", "target": "300"})
    assert status == 200
    assert recorder["start_job"] == [("p1", "select", ["--target", "300"])]


def test_job_select_bad_target_rejected(gui_server, recorder):
    make_project(gui_server.root)
    status, _, _ = call(gui_server, "POST", "/api/job", {"project": "p1", "task": "select", "target": "0"})
    assert status == 400 and recorder["start_job"] == []


def test_start_job_knows_select(gui_server):
    assert gui_server.module.JOB_COMMANDS["select"] == ["select"]


def test_state_includes_selection_summary(gui_server):
    sel = {"total": 214, "target": 175, "must_keep_total": 214, "over_target": True,
           "suggested_target": 215, "shots": [], "warnings": []}
    make_project(gui_server.root, **{"work/selection.json": json.dumps(sel)})
    status, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    got = json.loads(body)["selection"]
    assert status == 200 and got["over_target"] is True and got["suggested_target"] == 215


def test_state_prefills_storyboard_from_selection(gui_server):
    pre = {"shots": [{"id": "sel01", "in": 0, "out": 6, "sub": "a", "note": "t"}]}
    make_project(gui_server.root, **{"work/shots-selected.json": json.dumps(pre)})
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(body)
    assert data["shots"][0]["id"] == "sel01" and data["shots_from_selection"] is True


def test_state_keeps_manual_storyboard(gui_server):
    pre = {"shots": [{"id": "sel01", "in": 0, "out": 6}]}
    make_project(gui_server.root, shots=[{"id": "sh01", "in": 1, "out": 2}],
                 **{"work/shots-selected.json": json.dumps(pre)})
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    assert json.loads(body)["shots"][0]["id"] == "sh01"
```
- **GOTCHA**: `make_project` 的 `project.json` 没有 `target_duration`；`project_state` 用 `jload` 读原始 JSON，不经 schema 迁移，前端要容忍缺省。
- **VALIDATE**: RED。

### Task 11: GUI 服务实现（GREEN）
- **ACTION**: `gui/server.py`。
- **IMPLEMENT**:
  1. 任务表提到模块级（`start_job` `:245-250` 改用它）：
```python
JOB_COMMANDS = {"prepare": ["prepare"], "build": ["build"], "select": ["select"]}
...
    if task not in JOB_COMMANDS:
        raise ValueError("未知任务")
    argv = [*JOB_COMMANDS[task], name, *(extra or [])]
```
     冻结分支 `run_cli([task, name, *(extra or [])])`（`:283`）与子进程分支 `[PY, str(AICUT), *cmds[task]]`（`:303`）都改用 `argv`。**注意**：先校验任务再登记 `JOBS[job_id]`（现在 `:242-244` 先登记后校验，未知任务会留幽灵 running——GL-17 的一部分；这里顺手把校验挪到登记前，仅因为本任务改了这几行）。
  2. `/api/job`（`:643-650`）：
```python
                if task == "select" and body.get("target") is not None:
                    extra += ["--target", str(schema.check_target_duration(body["target"]))]
```
  3. `/api/new`（`:586-595`）：
```python
            target = body.get("target")
            ...
            args = ["new", name, f"--material={material}", f"--preset={preset}", f"--title={title}"]
            if target is not None:
                try:
                    args.append(f"--target={schema.check_target_duration(target)}")
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            code, out = run_aicut(args)
```
  4. `project_state`（`:156-167`）：
```python
    manual = jload(pdir / "shots.json", {}).get("shots", [])
    selected = jload(work / "shots-selected.json", {}).get("shots", [])
    sel = jload(work / "selection.json") or {}
    return {
        ...
        "shots": manual or selected,
        "shots_from_selection": not manual and bool(selected),
        "selection": ({k: sel.get(k) for k in ("total", "target", "must_keep_total",
                                               "over_target", "suggested_target", "warnings")}
                      if sel else None),
        ...
    }
```
- **MIRROR**: GUI_JOB、VALIDATION。
- **GOTCHA**:
  - `jload` 读坏文件的行为属 KI-21，不处理。
  - 预填的分镜表一旦被前端保存就成了 `shots.json`；之后再改目标重跑选段**不会覆盖**它（见 Notes 第 1 条）。前端要提示。
- **VALIDATE**: `uv run pytest tests/test_server_target.py tests/test_server_security.py -q`。

### Task 12: 前端（`gui/static/index.html`）+ 静态测试
- **ACTION**: `tests/test_static_pages.py` 追加测试 → 改 `index.html`。
- **TEST FIRST**:
```python
def test_new_project_asks_target():
    src = _read("index.html")
    assert 'id="npTarget"' in src and "target" in src[src.index("async function createProject"):]


def test_target_copy_in_named_constants():
    src = _read("index.html")
    for const in ("COPY_MUST_KEEP_OVER", "COPY_TARGET_ASK", "COPY_TARGET_BUTTON"):
        assert f"const {const}" in src
    assert "startJob('select'" in src


def test_target_modal_uses_num_for_numbers():
    src = _read("index.html")
    body = src[src.index("function openTarget"):src.index("function saveTarget")]
    assert "num(" in body and "${sel." not in body
```
- **IMPLEMENT**:
  1. 常量（脚本顶部，`state` 定义之后；**以下文案为推荐默认，可由产品改**）：
```js
const COPY_MUST_KEEP_OVER = '必留内容共 {must}，超过目标 {target}';
const COPY_TARGET_ASK = '想剪成多长？';
const COPY_TARGET_BUTTON = '按这个时长重新选段';
const COPY_TARGET_LATER = '先不改';
const COPY_TARGET_MANUAL_NOTE = '你已经手动编辑过分镜表，重新选段的结果不会覆盖它，只会更新「浏览素材」里的建议';
function fmtMinSec(sec){ sec = Math.round(num(sec)); return sec>=60 ? `${Math.floor(sec/60)} 分 ${sec%60} 秒` : `${sec} 秒`; }
```
  2. 顶栏按钮（`:122-128` 的 `#actions` 里加）：`<button class="ghost" onclick="openTarget(false)">改目标时长</button>`；`refresh()`（`:210`）的 meta 用 `fmtLong(num(c.target_duration))`。
  3. 弹窗：
```js
function openTarget(fromOverrun){
  const sel = state.data?.selection || {};
  const cur = num(state.data?.project?.target_duration);
  const over = fromOverrun && sel.over_target;
  const value = over ? num(sel.suggested_target) : cur;
  const head = over ? COPY_MUST_KEEP_OVER.replace('{must}', fmtMinSec(sel.must_keep_total))
                                         .replace('{target}', fmtMinSec(cur)) : '';
  showModal(over ? '必留内容超过目标时长' : '目标时长', `
    ${head ? `<p>${esc(head)}</p>` : ''}
    <div class="field"><label>${esc(COPY_TARGET_ASK)}（秒）</label>
      <input id="tgtInput" type="number" min="10" max="3600" value="${num(value)}"></div>
    ${state.data?.shots_from_selection === false && state.shots.length ? `<p class="hint">${esc(COPY_TARGET_MANUAL_NOTE)}</p>` : ''}
    <button class="primary" onclick="saveTarget()">${esc(COPY_TARGET_BUTTON)}</button>
    <button class="ghost" onclick="closeModal()">${esc(COPY_TARGET_LATER)}</button>`);
}
function saveTarget(){
  const t = num($('#tgtInput')?.value);
  closeModal();
  startJob('select', {target: t});
}
```
  4. `startJob` 标题：`{prepare:'正在处理素材', build:'正在生成成片', select:'正在重新选段'}[task]`；`pollJob` 完成分支：`refresh()` 之后若 `task!=='build' && state.data?.selection?.over_target` → `openTarget(true)`，否则 toast。
  5. 新建项目弹窗（`:511-513`）：预设下拉加 `onchange="syncTarget()"`，其后加
```html
    <div class="field"><label>想剪成多长（秒）· 预设只是默认值</label>
      <input id="npTarget" type="number" min="10" max="3600"></div>
```
     `openNew` 末尾 `syncTarget()`：`$('#npTarget').value = num(presets.find(p=>p.key===$('#npPreset').value)?.duration)`（`presets` 存到 `state.presets`）；`createProject`（`:525-530`）body 加 `target: num($('#npTarget').value)`。
- **GOTCHA**:
  - 内联事件不许插值（`test_no_string_interpolation_in_inline_handlers`）：`openTarget(false)`/`saveTarget()` 都不带模板变量。
  - 数值一律 `num()`，文本一律 `esc()`；`selection.warnings` 若显示也要 `esc()`。
  - 失败任务的模态层关不掉是 GL-22（M4）；本任务不改 `pollJob` 失败分支。
- **VALIDATE**: `uv run pytest tests/test_static_pages.py -q`；手动走 Manual Validation 的 GUI 步骤。

### Task 13: 登记册状态
- **ACTION**: 全绿且审查无 CRITICAL/HIGH 后，`docs/go-live-blockers.md` 中 GL-08、GL-09、GL-24、GL-25 状态 `open` → `fixed`。PRD 里程碑状态由用户/编排方更新。
- **VALIDATE**: `git diff docs/go-live-blockers.md` 只改这四行。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_check_target_duration_*` | 175 / "240" / 59.6 / 非法值 | 整数秒 / ValueError | 是 |
| GL-08 系列（Task 2） | 预算 0、exclude、预算用尽、超目标、30s 段、1s 段 | 全部整段进片；`over_target`、`suggested_target` | 是 |
| `test_must_keep_invariant_randomized` | 300 组随机 | 必留 ⊆ 进片且整段 | 是（性质测试） |
| `test_run_reallocates_budget_when_target_changed` | 目标 30→300 | 话题预算重分，scored 文件不变 | 是 |
| `test_uncovered_must_keep_*` | 部分覆盖 / 两镜拼覆盖 | 只报覆盖不足 90% 的 | 是 |
| GL-09a 系列（Task 4） | 首次失败 / 持久失败 / 漏 id / 编造 id / 重跑 | 重试、落盘后抛错、只补失败句、输入变了全量 | 是 |
| GL-09b + GL-24 系列（Task 6） | 必留话题超限、标注失败、暗画面 | 不降废片；非必留照旧 | 是 |
| CLI 系列（Task 8） | `new --target`、终端询问、`select --target`、text 失败、build 缺必留 | 存目标、只重跑选段、`[!]`/`[x]`、不切片 | 是 |
| 服务系列（Task 10） | `/api/new` target、`/api/job select`、`/api/state` | 透传/400、selection 摘要、分镜表预填但不覆盖手存 | 是 |
| 静态页（Task 12） | index.html 源码 | 有时长输入、文案常量、`num()` | 否 |

### Edge Cases Checklist
- [x] Empty input — 无必留：`must_keep_ids == []`、`over_target False`；无 `segments_scored.json` 时 build 不查
- [x] Maximum size input — 必留远超目标；必留段 > `MAX_SHOT`；目标上限 3600
- [x] Invalid types — 目标 `True`/NaN/字符串/负数；模型编造/漏 id
- [ ] Concurrent access — 任务互斥属 GL-17（M4）
- [x] Network failure — `LLMError` 批次重试、持久失败、续跑
- [x] 损坏数据 — `overrides.json` 损坏 → build `die`（沿用 M1 的 `OverridesCorrupt`）
- [x] 旧数据兼容 — 旧 `segments_text.json` 无 `complete`/`annotation_failed`；旧 `selection.json` 无新字段（前端 `num()` 兜底为 0）

---

## Validation Commands

### Static Analysis
```bash
# 未配置 lint / typecheck（CLAUDE.md）；至少保证可导入
uv run python -c 'import aicut, gui.server, pipeline.select, pipeline.classify, pipeline.understand_text'
```
EXPECT: 无报错

### Unit Tests
```bash
uv run pytest tests/test_select.py tests/test_classify.py tests/test_understand_text.py \
  tests/test_schema.py tests/test_aicut_must_keep.py tests/test_server_target.py tests/test_static_pages.py
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 无回归（基线 253 passed）

### Browser Validation
```bash
uv run python gui/server.py --open   # 或 python3 gui/server.py --open
```
EXPECT: 见 Manual Validation 的 GUI 步骤

### Manual Validation
- [ ] CLI：`uv run python aicut.py new t1 --material <视频>`（在终端里）→ 被问时长，回车得到预设值；`--target 240` 不问。
- [ ] 已有项目在 `work/overrides.json` 标 3 句必留（一句在 exclude 话题、一句 > 25s），把目标设成比必留合计还短：`aicut.py select <项目> --target 30` → `[!] 必留内容共 …，超过目标 30 秒 … 建议 --target N`；`selection.json` 里 3 个必留段整段在 `shots`。确认没有重新转写或调 LLM（日志里没有转写/标注的行）。
- [ ] 把 DeepSeek Key 设成无效值跑 `aicut.py text <项目>` → `[x] N 句逐句标注失败 … 只会重跑这 N 句`，退出码 1，`segments_text.json` 有 `"complete": false`；恢复 Key 再跑 → `[✓] … · 已补齐上次失败的句子`。
- [ ] 手存一个漏掉必留段的 `shots.json` → `aicut.py build <项目> --no-draft` → `[x] 分镜表缺少 1 段必留内容：mm:ss "…"`，`work/clips` 没有新增切片。
- [ ] GUI：新建项目弹窗有时长输入框，切换预设时自动更新；创建后顶栏显示该目标。
- [ ] GUI：①处理素材完成且必留超时长 → 自动弹窗，文案为「必留内容共 X 分 Y 秒，超过目标 Z」，输入框默认值 = 建议值；确认后任务标题「正在重新选段」，日志只有选段相关行，完成后顶栏目标已更新。
- [ ] GUI：顶栏「改目标时长」随时可用；已有手存分镜表时弹窗显示「不会覆盖」提示。

---

## Acceptance Criteria
- [ ] All tasks completed
- [ ] `uv run pytest` 全绿，无回归
- [ ] 必留进片率：单测 + 300 组随机不变量测试 100%，且必留镜头为整段
- [ ] 目标时长：新建时由剪辑师决定（预设仅默认）；CLI/GUI 都能改；改后只重跑选段
- [ ] 必留超目标：不丢不截；CLI `[!]` 给出必留合计与改时长命令；GUI 弹窗含时长输入、默认建议值
- [ ] LLM 标注失败：任务失败并提示重试；失败句子先落盘；重跑只补失败句
- [ ] 待定超限、画面过暗都不把必留话题段/标注失败段判废片；自动降级数量可见
- [ ] 出片前分镜表缺必留段 → 不出片并列出缺失
- [ ] No lint/type errors — N/A（未配置）

## Completion Checklist
- [ ] Code follows discovered patterns（常量 + 中文注释、`_private`、`check_*` 校验、领域异常 + `die`）
- [ ] Error handling matches codebase style
- [ ] Logging follows codebase conventions（`[·] [✓] [!] [x]`）
- [ ] Tests follow test patterns（平铺函数、`seg()`、`FakeClient` 子类、`gui_server`/`recorder`、`Namespace`）
- [ ] No hardcoded values（文案、阈值、重试次数均为命名常量；GUI 文案集中在 `COPY_*`）
- [ ] Documentation updated（`go-live-blockers.md`；`understand_text.py` docstring）
- [ ] No unnecessary scope additions（KI 项与 KI-05 确认页部分均未实现）
- [ ] Self-contained

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 手存分镜表后改目标，选段结果不进分镜表，剪辑师以为没生效 | 中 | 中 | 弹窗提示「不会覆盖」；GL-25 出片前兜底；是否加「替换分镜表」见 Notes |
| 标注失败就停整条 prepare，DeepSeek 抖动时体验差 | 中 | 中 | 每批额外 2 次 + 客户端 3 次 HTTP 重试；重跑只补失败句，成本低 |
| 失败后 GUI 模态层关不掉（GL-22 未修） | 高 | 中 | M4 修；在此之前需重启 App。实现顺序上建议 M4 的 GL-22 不要拖太久 |
| GL-25 的 90% 覆盖阈值误判手动打点 | 低 | 中 | 常量 `MUST_KEEP_COVER_RATIO`，报错列出时间码与原话便于核对 |
| 待定不再强制 ≤40（必留话题放行） | 中 | 中 | 超限警告；KI-07（必留话题词过宽）修好后数量会降 |
| 改 3 个旧测试被误解为「改测试迁就实现」 | 低 | 低 | 计划逐条说明旧断言固化了 GL-09 缺陷本身 |

## Notes

### 用户决策（2026-10-19，已落实到计划）
1. **时长由剪辑师决定**（原话：「时长不是限定死的，问用户想剪成多长的片子」）：新建项目时询问（预设为默认），可随时改，改后只重跑选段；必留超出目标时不丢不截，记录 `must_keep_total/over_target`，CLI `[!]` + 改时长命令，GUI 弹窗「必留内容共 X 分 Y 秒，超过目标 Z」+ 输入框（默认 = 必留合计向上取整到 5 秒）。**文案为推荐默认**，集中在 `MUST_KEEP_OVER_WARNING`、`MUST_KEEP_OVER_HINT`、`TARGET_PROMPT`、`MUST_KEEP_MISSING`、`ANNOTATION_RETRY_HINT`、`PENDING_OVER_WARNING` 与前端 `COPY_*` 常量里。
2. **LLM 标注重试后仍失败**：任务失败、提示重试；失败句子先落盘；重跑（输入未变时）只补跑失败句子。
3. **待定超限**（未答，沿用推荐默认）：必留话题段与标注失败段永不自动降级；其他待定按信息弱降废片，数量在 CLI 显示。
4. **GL-24 / GL-25** 并入本里程碑（协调方登记）。

### 仍待用户决策（不阻塞实现，已给默认）
- **手存分镜表与重新选段的关系**：默认不覆盖手存的 `shots.json`，只提示；备选是在弹窗里加「用新选段替换分镜表」按钮。
- **GL-25 是拦截还是警告**：默认拦截（`die`，不切片），理由是「必留 100%」；剪辑师确实不要某句时去浏览页取消★即可。
- **目标时长上下限** 10–3600 秒只作误输入护栏，可调。

### 复现记录（当前工作树，含 M1 改动）
- 待定+必留、预算 0 → 不进片；exclude → 不进片；5×6s 必留、预算 10、目标 120 → 只进 1 段；目标 12 → `_trim` 删到 2 段；30s 必留、预算 10 → 截成 0–11s。
- `tests/test_classify.py::test_pending_capped_by_ratio` 用必留话题断言降级，固化了 GL-09。

### 与其他里程碑的交互
- **KI-05（M6）**：本里程碑新增 `select` 任务和「改目标时长」入口；确认页答案 → 选段、prepare 顺序等仍归 KI-05，届时复用 `select` 任务。
- **GL-22 / GL-17 / GL-20（M4）**：失败后模态层关不掉；任务无互斥（同时点 prepare 与改时长会互踩）；`ask_calibration` 的 `input()` 卡死。本计划只把 `start_job` 的「先校验再登记」顺手修正（因为本任务改动了这几行），其余不动。
- **KI-12**：must_keep 按 id 存，重新分段后可能落到别的句子——不变量成立但保的是错句。
- **KI-03 / KI-23**：must_lines 碎片导致的超时只进 `warnings`，不触发改时长弹窗；匹配不到的提示以后可写进同一 `warnings`。
- **KI-09 / KI-25**：话题分段失败、非 `LLMError` 网络异常直接崩，不走本里程碑的重试，但也不静默。
- **KI-21**：`jload` 把坏 JSON 当默认值，`/api/state` 的 `selection` 可能因此为 `null`。
