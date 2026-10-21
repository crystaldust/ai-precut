# Plan: 成片时长随时可改（里程碑 15，KI-104）

## Summary
成片目标时长除了 ⑤ 看结果，还能在 ①（= 更多 → 项目设置，步骤条点 ① 打开的就是它）和 ③ 看素材的剪辑列表面板里改；③ 超出目标时一键采用建议时长。①③ 里改只保存，⑤ 因选段指纹里的 `target` 变化自动标「需要更新 · 目标时长改过了」，不自动重新选段；⑤ 维持改完即重新选段（手动改过分镜表先询问，KI-95）。

## User Story
作为剪辑师，我想在挑段（③）或回看设置（①）时就能改成片时长，这样发现剪辑列表超了目标或想换时长时不用先走到 ⑤。

## Problem → Solution
时长只在 ① 新建时填、⑤ 才能再改；项目设置明确不动时长（KI-92 注释） → ① / 项目设置、③、⑤ 都能改；①③ 改后 ⑤ 标需要更新。

## Metadata
- **Complexity**: Medium（约 9 个文件）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: 里程碑 15 — 时长随时可改
- **Decisions（用户 2026-10-21 已定）**: ①（项目设置）、③、⑤、项目设置都能改；①③ 与设置里改只保存、⑤ 标「需要更新」、不自动重选；⑤ 保持改完即重选；③ 超目标一键采用建议值；范围仍 10 秒–60 分钟；②④⑥ 不加入口。

---

## UX Design

### Before
```
① 新建：成片时长 [ 2 ]分[ 55 ]秒      ← 只有这里
项目设置（= 点 ①）：片名 / 预设 / 剪辑偏好   ← 没有时长
③ 剪辑列表面板：合计 3:40 / 目标 2:55
               ⚠ 已超出目标 0:45，进片时全部保留，建议把目标改为 3:40   ← 只能看
⑤ 顶栏：目标时长 2:55 [改]   ← 唯一能改的地方
```

### After
```
项目设置（= 点 ①）：成片时长 [ 2 ]分[ 55 ]秒（最上面）/ 片名 / 预设 / 剪辑偏好
③ 剪辑列表面板：合计 3:40 / 目标 2:55 [改]
               ⚠ 已超出目标 0:45，进片时全部保留，建议把目标改为 3:40 [改为 3:40]
               点 [改] → 合计 3:40 / 目标 [ 2 ]分[ 55 ]秒 [确定] [取消]
⑤ 顶栏：不变（改完立即重新选段）
保存后（已有选段时）：⑤ 步骤标「需要更新」，横幅「目标时长改过了 · 重新选段」
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 项目设置 / 点 ① | 无时长 | 最上面「成片时长」分 + 秒，回显当前值 | 只在值变了时才发 `target` |
| ③ 面板 | 只显示目标 | 「改」→ 就地分 + 秒 + 确定 / 取消 | 确定 = 保存，面板合计 / 超出 / 建议即时更新 |
| ③ 超目标警告 | 只有文字 | 加按钮「改为 {suggest}」 | 一键保存建议值 |
| ⑤ | 改完即重选 | 不变 | |
| 任务进行中 | — | ③ 的「改」「改为…」随其它启动类按钮一起置灰；服务端对正在跑任务的项目拒绝改时长（409） | 防止与选段任务写 project.json 交错 |
| 改后 ⑤ | — | 已有选段时标「需要更新 · 目标时长改过了」 | 现有指纹机制，无需新逻辑 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `gui/project_routes.py` | 151–203 | `_project_for_write`、`_post_project_settings`（要加 `target`；docstring 里「不动 target_duration（KI-92）」要改） |
| P0 | `gui/static/project-form.js` | 1–50, 140–180 | `durationFields(prefix, sec)` / `readDuration(prefix)` / `markTargetTouched`；`openProjectSettings` / `saveProjectSettings` |
| P0 | `gui/static/cliplist.js` | 1–20, 195–231 | 面板文案常量、`panelHtml` / `renderClipPanel` / `localClip`；ACTIONS 注册 |
| P0 | `gui/static/step-result.js` | 145–212 | ⑤ 顶栏改时长的写法（`targetHtml` 编辑态、`applyTarget`、`applySuggested`）——③ 照这个样子做 |
| P1 | `gui/jobs.py` | 115–140 | `active_job(project)` / `project_job(project)`：判断项目有没有在跑的任务 |
| P1 | `pipeline/schema.py` | 345–360 | `TARGET_MIN/MAX`、`TARGET_ERROR`、`check_target_duration`（返回 int） |
| P1 | `aicut.py` | 450–470 | `select --target` 在选段成功后才写 project.json——这是要防的并发写 |
| P1 | `gui/wizard.py` | 15–30 | 横幅分项文案 `"target": "目标时长改过了"`（已存在） |
| P1 | `gui/static/jobs.js` | 265–285 | `[data-starts-job]` 忙碌守卫：任务进行中自动置灰 |
| P1 | `gui/static/step-browse.js` | `resyncBrowse` | ③ 保存后用它重新读 `/api/browse`（`clip_list.target` 来自 project.json） |
| P2 | `tests/test_server_wizard.py` | 85–140 | `/api/project/settings` 测试写法（`_settings_project`、`post`、`project_json`） |
| P2 | `tests/test_frontend_project_form.py`, `tests/test_frontend_cliplist.py`, `tests/fe_browse.py` | all | 前端 node vm 测试写法与夹具 |

## External Documentation
无需外部资料——全部沿用仓库内既有模式。

---

## Patterns to Mirror

### 路由校验与错误映射
```python
# SOURCE: gui/project_routes.py:170-192
changes, platform = {}, None
try:
    if "title" in body:
        title = body["title"]
        changes["title"] = schema.check_title(title.strip() if isinstance(title, str) else title)
    ...
except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
    return 409, {"error": str(exc)}
except ValueError as exc:
    return 400, {"error": str(exc)}
if not changes and given is None:
    return 400, {"error": NOTHING_TO_CHANGE_MSG}
```
加 `if "target" in body: changes["target_duration"] = schema.check_target_duration(body["target"])`。

### 原子更新 project.json
```python
# SOURCE: gui/project_routes.py:200
cfg = schema.update_project(pdir / "project.json", mutate)
```

### ⑤ 的就地编辑（③ 照抄形态，不复用 res() 状态）
```js
// SOURCE: gui/static/step-result.js:152-157, 195-205
function targetHtml(r, tb){
  if(r.editing) return `${esc(COPY_TOP_TARGET)} ${durationFields('tgt', num(tb.target))}
    <button class="primary" data-act="applyTarget" data-starts-job>${esc(COPY_TARGET_OK)}</button>
    <button class="ghost" data-act="cancelTarget">${esc(COPY_TARGET_CANCEL)}</button>`;
  ...
}
async function applyTarget(){
  const t = readDuration('tgt');
  if(!t){ toast(COPY_TARGET_RANGE); return; }
  ...
}
```
③ 用前缀 `clipTgt`（id 不能和 ⑤ 的 `tgt`、新建的 `np`、设置的 `ps` 撞）。

### 保存后同步向导状态（项目设置已有）
```js
// SOURCE: gui/static/project-form.js:174-178
state.data = {...state.data, project: r.project, wizard: r.wizard};
state.view = resolveView(r.wizard, state.view);
closeModal(); renderChrome(); renderView(); toast(COPY_SETTINGS_SAVED);
```

### 文案常量
`/* 界面文案：产品可直接改这里 */ const COPY_... = '...';`（每个 JS 文件顶部）

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `gui/project_routes.py` | UPDATE | `/api/project/settings` 接受可选 `target`；项目有在跑任务时拒绝改时长（409）；docstring 改掉 KI-92 那句 |
| `gui/static/project-form.js` | UPDATE | 项目设置弹窗最上面加 `durationFields('ps', cfg.target_duration)`；保存时 `readDuration('ps')` 校验，值变了才带 `target` |
| `gui/static/cliplist.js`（或新 `gui/static/clip-target.js`） | UPDATE / CREATE | 面板「改」/ 编辑态 / 「改为 {suggest}」；保存走 `/api/project/settings {project, target}`；成功后更新 `state.data` 并 `resyncBrowse()` |
| `gui/static/app.css` | UPDATE（如需要） | 面板编辑态排版 |
| `tests/test_server_wizard.py`（或新 `tests/test_project_settings_target.py`） | UPDATE / CREATE | 后端测试 |
| `tests/test_frontend_project_form.py` | UPDATE | 设置弹窗时长回显 / 保存 / 校验 |
| `tests/test_frontend_target_browse.py` | CREATE | ③ 面板改时长 |
| `docs/PRD-AI粗剪工具.md` | UPDATE | FR-1（约第 144 行）：「之后可在 ⑤ 看结果随时改」→「之后可在 ①（项目设置）、③ 剪辑列表面板、⑤ 看结果随时改；①③ 里改只保存，⑤ 标需要更新」 |
| `docs/界面流程-v2.md` | UPDATE | ① 段落、③ 剪辑列表面板段落、入口对照表「改目标时长」行（约第 156 行） |
| `docs/known-issues.md` | UPDATE | 新增 KI-104 行（「2026-10-20 界面流程梳理」表末尾，KI-103 之后）；KI-92 行不改历史，在 KI-104 里说明取代「项目设置不动时长」 |
| `docs/GUI.md` | UPDATE | `/api/project/settings` 的说明加 `target` |
| `docs/PROGRESS.md` | UPDATE | 放行检查加 #26 |
| `CHANGELOG.md` | UPDATE | 「未发布」下加一节 |
| `.claude/prds/ai-cut-go-live.prd.md` | UPDATE | 里程碑 15 状态与链接 |

## NOT Building
- ②④⑥ 加改时长入口
- ①③ 改完自动重新选段
- 改时长范围（仍 10 秒–60 分钟）
- ⑤ 的行为变化
- 新建弹窗的变化（已支持分 + 秒自由填写，KI-92）

---

## Step-by-Step Tasks

### Task 1: 后端 `/api/project/settings` 接受 `target`
- **ACTION**: 改 `_post_project_settings`。
- **IMPLEMENT**:
  - `if "target" in body: changes["target_duration"] = schema.check_target_duration(body["target"])`（放在 try 里，非法 → 400 带 `TARGET_ERROR` 文案）。
  - 带 `target` 且 `jobs.active_job(project)` 不为 None → 409 `TARGET_BUSY_MSG`（如「正在处理这个项目，完成后再改时长」）。只拦带 `target` 的请求，不改片名 / 预设 / 偏好的现有行为。
  - docstring 改为「项目设置：片名 / 预设 / 剪辑偏好 / 目标时长（KI-104：①③ 改只保存，⑤ 标需要更新）」。
  - 返回不变（`project` + `wizard`）。
- **MIRROR**: 路由校验与错误映射
- **IMPORTS**: `jobs` 已在 `gui/project_routes.py` 导入。
- **GOTCHA**: 校验在 `update_project` 之前；不带 `target` 时不得改 `target_duration`（现有测试 `assert cfg["target_duration"] == 99` 保留）；确认 `check_target_duration` 拒绝 bool，否则在路由里先拒；`{"target": null}` → 400，不当成「没给」。
- **VALIDATE**: 测试：合法值（10、175、3600）写入并返回；非法（9、3601、"abc"、true、null、列表）→ 400 且 project.json 未变；只改时长成功；已有选段（`work/selection.json` 带 inputs）时改时长后返回的 `wizard` 里 ⑤ 为 stale 且 reasons 含 `target`；项目有在跑任务时带 target → 409、不带 target 仍 200；项目不存在 404。

### Task 2: 项目设置弹窗（= 点 ①）加时长
- **ACTION**: 改 `openProjectSettings` / `saveProjectSettings`。
- **IMPLEMENT**: 弹窗第一项 `<div class="field"><label>${esc(COPY_NEW_TARGET_LABEL)}</label>${durationFields('ps', cfg.target_duration)}</div>`；保存时 `const target = readDuration('ps'); if(!target) return toast(COPY_TARGET_RANGE);`；若 `target !== Math.round(num(cfg.target_duration))` 才把 `target` 放进 body。保存成功后现有逻辑已经更新 `state.data` / `wizard` / 重画；在 ③ 时额外 `resyncBrowse()`。新增文案 `COPY_TARGET_SAVED_STALE = '已保存。⑤ 看结果需要重新选段才会按新时长出分镜表'`：保存了新时长且返回的 ⑤ 为 stale 时用它，否则沿用 `COPY_SETTINGS_SAVED`。
- **MIRROR**: 保存后同步向导状态；⑤ 的就地编辑（readDuration 用法）
- **GOTCHA**: `durationFields` 的输入框带 `data-input="markTargetTouched"`（设 `state.npTouched`），只影响新建弹窗，`openNew` 会重置，无害。项目设置里换预设**不**改时长（与 KI-92 一致）。
- **VALIDATE**: 前端测试：弹窗回显当前时长（175 → 2 分 55 秒）；改成 3 分 → body 带 `target: 180`；没改 → body 不带 `target`；非法（秒填 60、总长 5 秒）→ toast 范围提示、不发请求；服务端 409 → toast 原因、弹窗保留；保存后 ⑤ stale 时用 stale 文案。

### Task 3: ③ 剪辑列表面板改时长
- **ACTION**: 改面板（`cliplist.js`，必要时拆出 `clip-target.js`）。
- **IMPLEMENT**:
  - 状态：`bs().targetEditing`（进 ③ / 切项目时为 false）。
  - `panelHtml`：合计行后加 `<button class="ghost" data-act="editClipTarget" data-starts-job>改</button>`；编辑态把「目标 X」换成 `durationFields('clipTgt', target)` + `[确定] data-act="applyClipTarget" data-starts-job` + `[取消] data-act="cancelClipTarget"`。
  - 超目标警告：有 `suggested_target` 时加 `<button class="primary" data-act="applyClipSuggested" data-starts-job>改为 {fmtLong(suggest)}</button>`。
  - `saveClipTarget(sec)`：`postJson('/api/project/settings', {project: b.project, target: sec})` → `bs() !== b` 就丢弃；成功：`state.data = {...state.data, project: r.project, wizard: r.wizard}`、`renderSteps(); renderBanner(); renderNav();`、`b.targetEditing = false`、`resyncBrowse()`、toast（同 Task 2 的两种文案）；失败：toast 服务端原因，编辑态与输入保留。
  - 在途防重复（模块级 `savingTarget` 标志）。
  - 编辑态时 `renderClipPanel` 被别的标记响应触发重画不能清掉输入：重画前读出 `#clipTgtMin/#clipTgtSec` 的值再写回（测试钉住）。
- **MIRROR**: ⑤ 的就地编辑；文案常量
- **GOTCHA**: 输入框里打字不触发快捷键（`TYPING_TAGS`）。`cliplist.js` 保持 ≤ 400 行（现 241）；若拆出 `clip-target.js`，同时登记 `gui/static_files.py` 白名单、`index.html` 顺序、`tests/fe_harness.py` 的 `SCRIPTS`、`tests/test_static_pages.py` 的 `INDEX_SCRIPT_ORDER`、`docs/GUI.md` 文件地图。
- **VALIDATE**: 前端测试：面板有「改」；点「改」出现分 + 秒且回显当前目标；确定发 `/api/project/settings {project, target}`；成功后退出编辑态、步骤条用返回的 wizard、重新读 `/api/browse`；非法值 toast 不发请求；失败保留编辑态与输入；超目标时出现「改为 3:40」且点击发 `target: 220`；切项目后旧回包不动界面；编辑态下别的段按 S 后输入值不丢。

### Task 4: 文档与登记
- **IMPLEMENT**: 见 Files to Change 的文档行。KI-104 行：问题「成片时长只能在 ① 新建时填、⑤ 看结果才能再改，③ 发现剪辑列表超目标也只能先走到 ⑤；项目设置不动时长（KI-92 当时的约定）」；位置 `gui/project_routes.py`（`_post_project_settings`）、`gui/static/project-form.js`、`cliplist.js`；状态 fixed（提交号待回填）。PROGRESS #26：设置里改时长 → ⑤ 标需要更新、点重新选段后分镜表按新时长；③ 面板「改」与「改为建议值」；任务进行中按钮置灰；手动改过分镜表时重新选段先问。CHANGELOG 一节。
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py tests/test_terms.py` 通过。

---

## Testing Strategy

### Edge Cases Checklist
- [ ] `target` 为 bool / null / 字符串 / 越界
- [ ] 不带 `target` 时时长不变
- [ ] 项目有在跑任务时改时长 → 409；改片名不受影响
- [ ] 没有选段结果时改时长：⑤ 不出现 stale
- [ ] 已有选段时改时长：⑤ stale，reasons 含 target
- [ ] ③ 编辑态下面板被别的响应重画
- [ ] 切项目时保存回包
- [ ] 设置弹窗换预设不改时长

## Validation Commands
```bash
uv run pytest tests/test_server_wizard.py tests/test_frontend_project_form.py tests/test_frontend_target_browse.py tests/test_frontend_cliplist.py
uv run pytest          # 全量（约 2 分钟），不加 -q
node --check gui/static/project-form.js gui/static/cliplist.js
```
项目未配置 lint / typecheck。不跑 App、不做冒烟；绝不碰钥匙串与真实剪映草稿目录。

## Acceptance Criteria
- [ ] 全部任务完成，新增测试先红后绿（报告 RED 数）
- [ ] 全量测试通过，覆盖率不低于 80%（当前 95%）
- [ ] python-reviewer / typescript-reviewer / security-reviewer 无 CRITICAL / HIGH
- [ ] 每个静态 JS 文件 ≤ 400 行
- [ ] 界面不出现「必留」（名词守卫）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 选段任务与改时长并发写 project.json，新时长被覆盖 | M | M | 服务端对有在跑任务的项目拒绝改时长；前端 `data-starts-job` 置灰 |
| ③ 编辑态被标记响应重画清掉输入 | M | L | 测试钉住；编辑态保留输入 |
| 用户以为 ③ 改完就生效 | M | L | 保存后 toast 明确「⑤ 需要重新选段」；⑤ 横幅已有 |

## Notes
- 新建弹窗本身已支持分 + 秒自由填写（KI-92 `c0fbe05`），用户 2026-10-21 反馈「最长 3 分钟」源于预设下拉名字带时长；本里程碑不改新建弹窗。
