# Plan: 画面理解 · 第 2 阶段 —— 流程与开关

## Summary
把「创建即分析」改成「创建项目 → 停在 ② → 剪辑师决定要不要开画面理解 → 开始分析」。② 页在非运行状态显示「画面理解（AI 多模态）」开关和档位（省钱 / 均衡 / 精细），运行中锁定只能停止；设置存进 project.json，进入分析输入指纹，改了之后 ② 标「需要更新」。外发告知加第三条数据流并升版本。本阶段**只记录设置**，不生成代理、不调云端（第 3 阶段做）。

## User Story
As a 剪辑师, I want 在开始分析前决定要不要让 AI 看画面, so that 我能按素材是否涉及隐私、是否需要画面信息来选择，并且清楚知道会上传什么。

## Problem → Solution
① 点「创建并开始分析」立刻开跑，没有选择时机；外发告知写死「画面不出本机」 → ① 只创建；② 有开关和档位；设置可追溯、改了会提示重新分析；告知如实说明可选的第三条数据流。

## Metadata
- **Complexity**: Medium（约 14 个文件，后端 + 前端 + 文档）
- **Source PRD**: `.claude/PRPs/prds/multimodal-video-understanding.prd.md`
- **PRD Phase**: Phase 2 流程与开关
- **Estimated Files**: 14

---

## UX Design

### Before
```
① 新建弹窗 ─[创建并开始分析]→ ② 正在分析（立刻开始）
外发告知：两条数据流 · 「原片和画面不会离开这台电脑」
```

### After
```
① 新建弹窗 ─[创建项目]→ ② 准备开始
                         ┌ 画面理解（AI 多模态）[开关] 可选·默认关闭
                         │ 档位：省钱（默认）/ 均衡 / 精细
                         │ ⚠ 开启后上传低清代理视频（不是原片）
                         └ [开始分析]
② 运行中：🔒 画面理解：已开启 · 省钱档（分析中不能修改）  [停止分析]
② 完成 / 停止 / 失败：开关可改 → 和上次分析时不同 → ② 标「需要更新」→ 重新分析
外发告知：三条（第三条注明只在开启画面理解时）· 「原片不出本机」
```
设计图：`designs/aicut.pen` 中「① 新建项目」「② 分析：准备开始（选画面理解）」「② 分析」「首次打开：外发告知 + 填 Key」（commit c916201）。

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| ① 新建弹窗按钮 | 创建并开始分析 → 起 prepare 任务 | 创建项目 → 只 POST /api/new，进入 ② | 不再自动起任务 |
| ② 未开始 | 「还没开始分析…」+ 开始分析 | 同上 + 画面理解卡片（开关、档位、隐私提示） | |
| ② 运行中 | 进度标题 | 进度标题 + 锁定条（显示当前设置） | 开关不可点 |
| ② 完成 / 中断 / 失败 | 原卡片 | 原卡片 + 画面理解卡片（可改） | 改了 → 向导 ② STALE |
| ② 需要更新横幅 | 「剪辑偏好或预设改过了…」 | 原因含 vision 时显示「画面理解设置改过了 · 重新分析…」 | |
| 外发告知 | 2 条，版本 1 | 3 条，版本 2（老用户重新确认一次） | CLI 文案同步 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `gui/static/project-form.js` | 1-30, 95-150 | 文案常量；`createAndAnalyze` 要改名改行为 |
| P0 | `gui/static/step-analyze.js` | 1-200 | ② 页全部状态（`statusCardHtml` / `viewAnalyze` / `startAnalysis`），新增卡片挂在这里 |
| P0 | `gui/project_routes.py` | 90-105, 153-240, 476-495 | `_get_analysis` 返回体；`_post_project_settings` + `_write_settings` 的 JOBS_LOCK 写法；`handle_post` 分发 |
| P0 | `pipeline/fingerprints.py` | 91-101 | `analysis_inputs` / `changed` |
| P0 | `gui/wizard.py` | 15-25, 70-120 | `STALE_ANALYZE`、`collect` 读戳、`_analyze_step` 用整 dict 比较 |
| P1 | `pipeline/schema.py` | 28-60, 72-105 | `DEFAULTS`、`default_project`、`migrate` 的「补齐」 |
| P1 | `pipeline/consent.py` | all | `CONSENT_VERSION`、CLI 文案 |
| P1 | `gui/static/settings.js` | 20-55 | GUI 告知文案与 `consentHtml` |
| P1 | `gui/analysis.py` | 125-150 | `progress()` 返回体 |
| P1 | `gui/jobs.py` | 68, 120-140 | `JOBS_LOCK`、`project_running_locked` |
| P2 | `tests/test_frontend_analysis.py` | 1-60 | node vm 前端测试写法 |
| P2 | `tests/test_frontend_project_form.py` | 1-70 | 新建弹窗测试（要改） |
| P2 | `tests/test_server_wizard.py` | 185-215 | 路由 409 测试写法（`fake_job`、`post`） |
| P2 | `tests/fe_fixtures.py` | 15-90 | `js()`、`NEW_WIZARD`、`progress()` |

## External Documentation
No external research needed — 本阶段只用内部模式；云端接口在第 3 阶段接入。

---

## Patterns to Mirror

### NAMING_CONVENTION（前端文案常量）
// SOURCE: gui/static/step-analyze.js:7-23
```js
const COPY_ANALYZE_START = '开始分析';
const COPY_ANALYZE_CONTINUE = '继续分析';
```
所有界面文字用 `COPY_*` 常量，放文件顶部；动作用 `data-act` + `Object.assign(ACTIONS, {...})` 注册。

### ERROR_HANDLING（路由）
// SOURCE: gui/project_routes.py:153-163, 210-232
```python
def _project_for_write(body: dict, existing: Lookup) -> tuple[int, dict] | tuple[Path, dict]:
    try:
        pdir = existing(body.get("project", ""))
        return pdir, schema.load(pdir / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.SchemaTooNew as exc:
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}
...
        if "target_duration" in changes:
            stack.enter_context(jobs.JOBS_LOCK)
            ...
            elif jobs.project_running_locked(name):
                return 409, {"error": TARGET_BUSY_MSG}
```
校验失败 400、项目不存在 404、正在跑 / 损坏 409；错误信息是中文常量 `*_MSG`。

### STATE_WRITE（project.json）
// SOURCE: gui/project_routes.py:226-233
```python
def mutate(cur: dict) -> dict:
    out = {**cur, **changes, ...}
    return out
cfg = schema.update_project(pdir / "project.json", mutate)
return 200, {"ok": True, "project": cfg, "wizard": wizard.derive(wizard.collect(pdir, cfg, name))}
```
不可变更新；写完把新向导一起返回。

### FRONTEND_ASYNC_GUARD
// SOURCE: gui/static/step-analyze.js:44-58
```js
const req = ++analysisUi.req;
...
if(req !== analysisUi.req || project !== state.project) return null;  // 切了项目 / 有更新的请求
```
异步请求回来前切了项目 / 有新请求，丢弃旧响应。

### TEST_STRUCTURE（前端，node vm）
// SOURCE: tests/test_frontend_analysis.py:1-20
```python
from fe_fixtures import *  # noqa: F401,F403
from fe_harness import NODE, run_app, wizard
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

def test_analyze_page_lists_eleven_human_steps_with_icons_and_times():
    html = run_app(f"viewAnalyze({js(progress(done=3, running=3, seconds=74))})")
```

### TEST_STRUCTURE（路由）
// SOURCE: tests/test_server_wizard.py:201-210
```python
monkeypatch.setitem(project_routes.jobs.JOBS, "j1", fake_job("p1"))
status, data = post(gui_server, "/api/project/settings", {"project": "p1", "target": 120})
assert status == 409 and data["error"] == project_routes.TARGET_BUSY_MSG
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/vision.py` | CREATE | 画面理解设置的唯一来源：档位常量、默认值、`normalize(raw)`、`fingerprint(setting)`、`check(body)`（校验 API 入参） |
| `pipeline/schema.py` | UPDATE | `DEFAULTS["vision"] = {"enabled": False, "tier": "economy"}`（旧项目由 migrate「补齐」） |
| `pipeline/fingerprints.py` | UPDATE | `analysis_inputs` 加 `"vision"`；新增 `ANALYSIS_STAMP_DEFAULTS = {"vision": "off"}` |
| `gui/wizard.py` | UPDATE | 读戳时补默认值（旧戳不能因为多了一项就全部变 STALE）；原因含 vision 时换横幅 |
| `gui/project_routes.py` | UPDATE | `_get_analysis` 返回 `vision` + `vision_locked`；新增 `POST /api/project/vision` |
| `pipeline/consent.py` | UPDATE | `CONSENT_VERSION = 2`；CLI 文案三条 |
| `gui/static/settings.js` | UPDATE | GUI 告知文案三条（与 consent.py 同步） |
| `gui/static/project-form.js` | UPDATE | 按钮「创建项目」；`createAndAnalyze` → `createProject`，不再 `startAnalysis` |
| `gui/static/step-analyze.js` | UPDATE | 画面理解卡片（开关、档位、隐私提示）、运行中锁定条、保存设置 |
| `gui/static/app.css` | UPDATE | 开关、档位分段按钮、锁定条样式 |
| `tests/test_vision_setting.py` | CREATE | vision 模块、schema 默认、指纹、向导、路由 |
| `tests/test_frontend_analysis_vision.py` | CREATE | ② 卡片各状态、锁定、保存、竞态 |
| `tests/test_frontend_project_form.py`、`tests/test_frontend_review.py`、`tests/test_static_pages.py`、`tests/test_consent.py`、`tests/fe_fixtures.py` | UPDATE | 改名 / 新行为 / 新版本号 |
| `docs/GUI.md`、`docs/界面流程-v2.md`、`docs/PRD-AI粗剪工具.md`、`docs/PROGRESS.md` | UPDATE | ①② 流程、API 表、隐私红线（§3.3、§7、FR-2）、决策记录、放行检查 #33 |

## NOT Building
- 代理素材、切段、MediaKit 视频理解调用、`visual_timeline.json`（第 3 阶段）
- ② 进度列表里的画面步骤（第 3 阶段随真实阶段一起加，避免显示永远「等待」的假步骤）
- 画面信息进入标注 / 档位 / ③ 显示（第 4、5 阶段）
- 全局（跨项目）的默认开关；CLI 的开关参数（`aicut new` 不变，CLI 用户在第 3 阶段再加 `--vision`）

---

## Step-by-Step Tasks

### Task 1: `pipeline/vision.py` 设置模型
- **ACTION**: 新建模块。
- **IMPLEMENT**:
  - `TIERS = ("economy", "balanced", "quality")`，`DEFAULT_TIER = "economy"`，`DEFAULT = {"enabled": False, "tier": DEFAULT_TIER}`
  - `normalize(raw: object) -> dict`：非 dict / 字段类型不对 → 回落默认；返回新 dict
  - `fingerprint(setting: dict) -> str`：关闭为 `"off"`，开启为 `"on:<tier>"`
  - `check(body: dict) -> dict`：`enabled` 必须是 bool、`tier` 必须在 TIERS，否则 `ValueError(BAD_SETTING_MSG)`；返回规范化后的新 dict
  - 中文常量 `BAD_SETTING_MSG = "画面理解设置不对：enabled 要是开 / 关，档位只能是省钱 / 均衡 / 精细"`
- **MIRROR**: `pipeline/style.py` 的 `normalize` / 常量风格
- **GOTCHA**: `True` 是 int 的子类，判断 bool 用 `isinstance(x, bool)`
- **VALIDATE**: `uv run pytest tests/test_vision_setting.py -k module`

### Task 2: schema 默认值 + 分析指纹 + 向导
- **ACTION**: `schema.DEFAULTS` 加 `"vision": {"enabled": False, "tier": "economy"}`（直接写字面量，避免 schema 依赖 vision 形成环；在测试里断言两处一致）。`fingerprints.analysis_inputs` 返回 `{..., "vision": vision.fingerprint(vision.normalize(cfg.get("vision")))}`；新增 `ANALYSIS_STAMP_DEFAULTS = {"vision": "off"}`。`wizard.collect` 读到戳是 dict 时用 `{**fingerprints.ANALYSIS_STAMP_DEFAULTS, **stamp}`。`_analyze_step`：`reasons` 含 `"vision"` 时横幅用新常量 `STALE_ANALYZE_VISION = "画面理解设置改过了 · 重新分析（已完成的转写、理解会沿用，只补跑画面相关的环节）"`，否则沿用 `STALE_ANALYZE`。
- **MIRROR**: `gui/wizard.py:108-115`
- **GOTCHA**: `_analyze_step` 是整 dict `stamp != now` 比较 —— 不补默认值，所有旧项目都会变成 STALE 且原因为空。写测试锁住：旧戳（无 vision）+ 当前关闭 → DONE。
- **VALIDATE**: `uv run pytest tests/test_vision_setting.py tests/test_fingerprints.py tests/test_wizard_state.py tests/test_server_wizard.py`

### Task 3: 路由
- **ACTION**: `_get_analysis` 返回 `{**analysis.progress(...), "vision": vision.normalize(cfg.get("vision"))}`。新增 `_post_project_vision(path, body, existing)` 注册到 `POST_ROUTES["/api/project/vision"]`：`vision.check(body)` → 400；`with jobs.JOBS_LOCK:` 内 `_project_for_write` + `project_running_locked(name)` → 409 `VISION_BUSY_MSG = "正在分析这个项目，停止或完成后再改画面理解"`；`schema.update_project(..., lambda cur: {**cur, "vision": setting})`；返回 `{"ok": True, "vision": setting, "wizard": wizard.derive(wizard.collect(pdir, cfg, name))}`（collect 在锁外调用，见 `_write_settings` 注释）。
- **MIRROR**: `_write_settings`（锁顺序 JOBS_LOCK → 项目锁 → 文件锁），错误映射同 `_project_for_write`
- **GOTCHA**: `wizard.collect` 内部会取 JOBS_LOCK，必须在 `with` 外调用，否则死锁（Lock 不可重入）
- **VALIDATE**: 路由测试：200 写盘、400 坏参数、404 不存在、409 正在跑（不写盘）、别的项目在跑不拦

### Task 4: 外发告知 v2
- **ACTION**: `consent.CONSENT_VERSION = 2`；`NOTICE_LINES` 与 `settings.js` 的 `COPY_CONSENT_INTRO` / `COPY_CONSENT_FLOWS` 同步改为：开头「原片不会离开这台电脑。为了完成粗剪，会有以下数据发到云端：」；三条：音轨 → 火山引擎；文字 → DeepSeek；「只在「② 分析」开启画面理解时：降质的低清代理视频（不是原片）→ 火山引擎，用于理解画面内容」。`CLI_REQUIRED_MSG` 同步提到画面理解。
- **GOTCHA**: 升版本会让所有老用户在下次分析前重新确认一次——这是预期（告知内容变了）。`test_docs_consistency.py` 可能比对文案，跑一遍看。
- **VALIDATE**: `uv run pytest tests/test_consent.py tests/test_cli_helpers.py tests/test_docs_consistency.py tests/test_frontend_analysis.py`

### Task 5: ① 只创建
- **ACTION**: `COPY_CREATE = '创建项目'`；函数改名 `createProject`（`data-act` 同步）；去掉 `await startAnalysis()`，改为 `await go('analyze')`；`toast(COPY_CREATED)` 保留。项目设置弹窗里的说明不变。
- **GOTCHA**: `tests/test_static_pages.py` 有三处按函数名切源码（`async function createAndAnalyze`），一起改名；`test_frontend_review.py:111,119` 也调用旧名。
- **VALIDATE**: `uv run pytest tests/test_frontend_project_form.py tests/test_frontend_review.py tests/test_static_pages.py`

### Task 6: ② 画面理解卡片
- **ACTION**: `step-analyze.js`：
  - 常量：`COPY_VISION_TITLE='画面理解（AI 多模态）'`、`COPY_VISION_OPTIONAL='可选 · 默认关闭'`、`COPY_VISION_DESC='除了听对话，再让 AI 看画面：认出人、动作、物品和画面上的文字，补上没人说话的镜头，并结合画面判断片段能不能用。'`、`COPY_VISION_PRIVACY='开启后会把低清代理视频（不是原片）上传到火山引擎。素材涉及隐私时不要开启。'`、`COPY_VISION_TIER='档位'`、`VISION_TIERS=[['economy','省钱（默认）'],['balanced','均衡'],['quality','精细']]`、`COPY_VISION_TIER_HINT='省钱：每秒看 2 帧，每小时素材约 27 万 tokens；均衡 / 精细看得更细、更贵'`、`COPY_VISION_LOCKED='画面理解：{state} · 分析中不能修改；停止或完成后可以改，再重新运行'`、`COPY_VISION_ON='已开启 · {tier}'`、`COPY_VISION_OFF='未开启'`
  - `visionCardHtml(v, locked)`：`locked` 时只渲染一行锁定条；否则开关（`<button role="switch" aria-checked>` + `data-act="toggleVision"`）、档位分段按钮（`data-act="setVisionTier" data-tier`，关闭时置灰 `disabled`）、说明、隐私提示。全部 `esc`。
  - `viewAnalyze`：`statusCardHtml(p)` 之后插入 `visionCardHtml(p.vision, isAnalyzing())`；`state.block` 分支不显示。
  - `saveVision(next)`：`postJson('/api/project/vision', {project, ...next})`；请求序号 + 项目校验（同 `loadAnalysis`），成功后 `analysisUi.data = {...analysisUi.data, vision: res.vision}`，`state.data.wizard = res.wizard`（看 `applyWizard` / 现有写法），重画；失败 toast 原文。进行中禁用重复点击。
  - `ACTIONS` 注册 `toggleVision` / `setVisionTier`。
- **MIRROR**: `FRONTEND_ASYNC_GUARD`；按钮 / 卡片 class 沿用 `card`、`primary`、`ghost`、`hint`
- **GOTCHA**: 运行中即使前端状态没刷新，后端也会 409——前端显示 toast 并刷新进度
- **VALIDATE**: `uv run pytest tests/test_frontend_analysis_vision.py tests/test_frontend_analysis.py`

### Task 7: 样式
- **ACTION**: `app.css` 加 `.vision-card`、`.switch`（40×22 圆角、开时 `--accent`）、`.seg`（分段按钮）、`.vision-lock`，深色主题变量沿用文件里已有的。
- **VALIDATE**: 浏览器版手动看一遍（见 Manual Validation）

### Task 8: 文档
- **ACTION**:
  - `docs/GUI.md`：① 新建（「创建项目」不再自动分析）、② 分析（画面理解开关、档位、锁定、需要更新）、API 表加 `POST /api/project/vision`、首次告知三条
  - `docs/界面流程-v2.md`：①② 流程同步
  - `docs/PRD-AI粗剪工具.md`：§3.3 / §7 / FR-2 隐私红线改为「原片不出本机；只在剪辑师开启画面理解时上传降质代理视频到火山引擎」；决策记录加 2026-10-30
  - `docs/PROGRESS.md`：放行检查 #33「② 画面理解开关」
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py`

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| normalize 默认 | None / "x" / {"enabled": 1} | 默认值 | ✓ |
| check 坏参数 | tier="pro"、enabled="yes" | ValueError | ✓ |
| fingerprint | 关 / 开省钱 | "off" / "on:economy" | |
| schema 补齐 | 无 vision 的旧 project.json | 迁移后有默认 vision | ✓ |
| 向导旧戳 | 戳无 vision、当前关闭 | ② DONE（不变 STALE） | ✓ 回归 |
| 向导切开关 | 戳 off、当前 on:economy | STALE + 画面理解横幅 + reasons=["vision"] | |
| 向导改档位 | 戳 on:economy、当前 on:quality | STALE | |
| 路由 | 正常 / 坏参数 / 不存在 / 本项目在跑 / 别的项目在跑 | 200 / 400 / 404 / 409 不写盘 / 200 | ✓ |
| /api/analysis | 任意项目 | 带 vision | |
| consent | 旧版本记录 | 需要重新确认 | |
| ① 创建 | 填表 → 创建项目 | 只 POST /api/new，view=analyze，不发 /api/job | |
| ② 卡片 | 未开始 / 完成 / 失败 / 中断 | 有开关、档位、隐私提示 | |
| ② 运行中 | isAnalyzing | 只有锁定条，没有可点的开关 | |
| ② 保存 | 点开关 | POST /api/project/vision，重画为开启 | |
| ② 竞态 | 请求回来前切项目 | 不覆盖新项目的显示 | ✓ |
| ② 409 | 后端说正在跑 | toast 原文，开关不变 | ✓ |
| 转义 | 档位名 / 错误信息带 `<script>` | 已转义 | ✓ |

### Edge Cases Checklist
- [x] 旧项目（无 vision 字段、无 vision 戳）
- [x] 非法输入
- [x] 并发：分析运行中改设置
- [x] 切项目时的旧响应
- [ ] Network failure：POST 失败 → toast，状态不变

---

## Validation Commands

### Static Analysis
项目未配置 lint / 类型检查（CLAUDE.md）。JS 语法由 node vm 测试覆盖。

### Unit Tests
```bash
uv run pytest tests/test_vision_setting.py tests/test_frontend_analysis_vision.py tests/test_frontend_analysis.py tests/test_frontend_project_form.py tests/test_server_wizard.py tests/test_consent.py
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest --cov
```
EXPECT: 无回归，覆盖率 ≥ 80%

### Browser Validation
```bash
python3 gui/server.py --open
```
EXPECT: 与设计图一致

### Manual Validation
- [ ] 新建项目 → 停在 ②「准备开始」，没有任务在跑
- [ ] 打开开关 → 档位可选；关闭 → 档位置灰
- [ ] 开始分析 → 卡片变锁定条；点不了
- [ ] 停止 → 开关恢复可改
- [ ] 分析完成后切换开关 → 顶部步骤条 ② 变 ⚠，横幅「画面理解设置改过了」
- [ ] 老项目（改版前分析过）打开 → ② 仍是 ✓
- [ ] 首次告知显示三条；老用户下次分析前重新确认一次

---

## Acceptance Criteria
- [ ] All tasks completed
- [ ] All validation commands pass
- [ ] Tests written and passing
- [ ] Matches UX design（`designs/aicut.pen`）

## Completion Checklist
- [ ] 文案全部是 `COPY_*` / `*_MSG` 常量
- [ ] 错误映射 400 / 404 / 409 与现有路由一致
- [ ] 不可变更新（project.json、前端 state）
- [ ] 测试沿用 node vm / gui_server 写法
- [ ] CLI 与 GUI 告知文案同步
- [ ] 没有超出本阶段范围（无云端调用）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 指纹多一项导致所有旧项目 ② 变「需要更新」 | H（不处理必发生） | H | 读戳补默认值 + 回归测试 |
| 升告知版本打扰老用户 | M | L | 预期行为；文案说明新增的是可选项 |
| 改名 `createAndAnalyze` 漏改测试 / 调用点 | M | L | grep 全仓；静态页测试会兜底 |
| 第 2 阶段上线了开关但第 3 阶段未做，开了没效果 | M | M | 第 2、3 阶段一起发布；第 2 阶段不单独出包（写进 PROGRESS 放行检查说明） |

## Notes
- 开关放 project.json 而不是全局：每条素材隐私情况不同，按项目选。
- 档位名在后端用英文 key，界面映射中文，便于第 3 阶段映射到 MediaKit 的 `manual_option` / `level`（第 1 阶段结论：默认 2 fps 手动抽帧）。
