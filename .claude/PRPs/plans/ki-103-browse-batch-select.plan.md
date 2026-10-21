# Plan: ③ 看素材 · 批量选择与全选（KI-103）

## Summary
③ 看素材的片段列表加勾选框、Shift 连选、「全选（当前筛选）」和底部批量操作栏：放入 / 移出剪辑列表、标为可用 / 废片、标为不可用、取消选择。后端新增一个原子的批量标记接口；一次 Z 撤销整批。

## User Story
作为剪辑师，我想一次勾选多段（或全选当前筛选）再批量放入剪辑列表 / 改标记，这样不用一条一条按 S。

## Problem → Solution
现在只能逐段点「＋ 剪辑列表」或按 S，每段一个请求 → 勾选多段 + 一个批量请求，整批成功或整批不写，整批撤销。

## Metadata
- **Complexity**: Medium（约 8 个文件）
- **Source PRD**: N/A（用户直接提出，登记为 KI-103）
- **Decisions（用户已定，2026-10-21）**: 勾选框 + Shift 连选；全选 = 当前筛选下看得到的段；批量操作 = 放入剪辑列表、移出剪辑列表、标为不可用、改档位（可用 / 废片）；一次 Z 撤销整批。

---

## UX Design

### After
```
[☑ 全选 12]  按时间 按话题 | 全部 待定 可用 废片 剪辑列表 不可用 未用
☑ 00:12 可用 话题A 原文……  ＋剪辑列表 ⊘
☑ 00:18 可用 话题A 原文……  ＋剪辑列表 ⊘
☐ 00:25 待定 话题B 原文……  ＋剪辑列表 ⊘
──────────────────────────────────────────
已选 2 段 [放入剪辑列表] [移出剪辑列表] [标为可用] [标为废片] [标为不可用] [取消选择]
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 行首 | 无 | 勾选框；点勾选框只改勾选，不换当前段、不播放 | 勾选框自带 data-act，委托取最内层，不会触发行的 jumpSeg |
| Shift+点勾选框 | — | 从上次点的勾选框到这一行（按当前列表显示顺序 `b.shown`）全部设成这一行的新状态 | 锚点 = 上次点的段；没有锚点时等同普通点 |
| 全选 | — | 勾上 = 选中当前筛选下所有显示的段；三态（部分选中 indeterminate）；数字为当前显示段数 | 只选看得到的 |
| 操作栏 | — | 有勾选时出现在列表下方；显示「已选 N 段」与 6 个按钮 | 没有勾选时隐藏 |
| 勾选清空时机 | — | 切筛选 / 切视图 / 切项目 / 重新进入 ③ / 批量操作成功后 | 失败时保留勾选，方便重试 |
| 快捷键 S/A/D/X/Z | 作用于当前段 | 不变（S/A/D/X 仍只作用于当前段）；Z 撤销栈里一条批量 = 整批 | 不加 ⌘A |
| 批量放入时已不可用的段 | — | 跟单段 P9 一致：放入 = 取消不可用 | 提示一句「其中 N 段已取消不可用」 |
| 批量不可用 | — | 移出列表 + 从手动分镜表移除重叠镜头（一次备份、一次移除） | 提示「已从分镜表移除 N 镜」 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/review.py` | 89–160 | `_write` / `unset_level`：锁内读改写、`_rekey`、互斥（EXCLUSIVE）、`must_at` 顺序戳、锚点 |
| P0 | `gui/project_routes.py` | 287–451 | `_mark_target`、`_mark_response`、`_saved_response`、`_post_browse_mark`、`_post_browse_unusable`、`_remove_manual_shots`、`_restore_manual_shots`、`_clean_restore`、`POST_ROUTES` |
| P0 | `gui/static/cliplist.js` | all | 乐观更新、每段请求队列（markQueues / epoch）、confirmed 快照、撤销栈（pushUndo / nextUndo / restoreSeg）、refreshSeg / localClip |
| P0 | `gui/static/step-browse.js` | all | 列表骨架、rowHtml、renderList（b.shown 显示顺序）、setFilter / setView、resyncBrowse、paintRow |
| P1 | `gui/static/common.js` | 25–50 | 事件委托：`ACTIONS[name](el, ev)`，取最内层带 data-act 的元素；data-change 同理 |
| P1 | `tests/fe_browse.py`, `tests/fe_harness.py`, `tests/test_frontend_cliplist.py` | all | node vm 前端测试写法、seg() 夹具、路由打桩 |
| P1 | `tests/test_browse_marks.py`, `tests/test_unusable.py` | all | 后端标记接口测试写法 |
| P2 | `docs/GUI.md` | 文件地图 | 有守卫测试比对静态文件清单，新增 JS 必须登记 |

## External Documentation
无需外部资料——全部沿用仓库内既有模式。

---

## Patterns to Mirror

### 文案常量（前端）
```js
// SOURCE: gui/static/cliplist.js:4-12
/* 界面文案：产品可直接改这里 */
const COPY_LIST_TITLE = '剪辑列表';
const COPY_CLEARED_UNUSABLE = '已取消不可用并放入剪辑列表';
```

### 动作注册（前端）
```js
// SOURCE: gui/static/cliplist.js:226-231
Object.assign(ACTIONS, {
  toggleListIdx: el => { const b = bs(); return b && toggleList(b.segs[num(el.dataset.i)]); },
});
```
处理函数签名是 `(el, ev)`，Shift 用 `ev.shiftKey`。

### 锁内读改写（后端）
```python
# SOURCE: pipeline/review.py:89-116
with _LOCK:
    data = load(workdir)
    segments = _scored_segments(workdir)
    if segments:
        data, stale = _rekey(data, segments)
    ...
    _save(workdir, data)
```

### 路由错误映射（后端）
```python
# SOURCE: gui/project_routes.py:337-341
except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
    return 409, {"error": str(exc)}
except (ValueError, TypeError, OSError) as exc:
    return 400, {"error": str(exc)}
return 200, _saved_response(...)
```

### 写成功后响应拼装失败 → 200 + warning
`gui/project_routes.py:313-321`（`_saved_response`）

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/review.py` | UPDATE | 新增 `set_batch(workdir, changes)`：一把锁、一次 load / rekey / save；每条按单段同样的互斥、must_at、锚点、unset level 规则 |
| `gui/project_routes.py` 或新 `gui/browse_batch.py` | UPDATE / CREATE | 新增 `POST /api/browse/batch`；project_routes.py 已 462 行，新增后若超 ~550 行就抽到 `gui/browse_batch.py` 并在 POST_ROUTES 注册 |
| `gui/static/batch-select.js` | CREATE | 勾选状态、Shift 连选、全选、操作栏、批量请求与整批撤销 |
| `gui/static/step-browse.js` | UPDATE | rowHtml 加勾选框；骨架加操作栏容器；renderFilters 加全选；setFilter / setView / resetBrowse / enterBrowse 清空勾选 |
| `gui/static/cliplist.js` | UPDATE | 撤销栈支持批量条目；nextUndo / undoLast 分发到批量恢复 |
| `gui/static/index.html` | UPDATE | 加载 `batch-select.js`（main.js 之前，按依赖放置） |
| `gui/static/app.css` | UPDATE | 勾选列、全选、操作栏样式 |
| `tests/test_browse_batch.py` | CREATE | 后端接口与 `review.set_batch` |
| `tests/test_frontend_batch_select.py` | CREATE | 前端 node vm 行为测试 |
| `docs/界面流程-v2.md`, `docs/GUI.md`, `docs/known-issues.md`, `docs/PROGRESS.md`, `CHANGELOG.md` | UPDATE | ③ 说明、文件地图、KI-103、放行检查 #25、变更记录 |

## NOT Building
- ⑤ 分镜表的批量操作
- 批量相关快捷键（⌘A 全选等）；S/A/D/X 不作用于勾选集合
- 「标为待定」批量按钮（单段也没有）

---

## Step-by-Step Tasks

### Task 1: `review.set_batch`
- **ACTION**: 在 `pipeline/review.py` 加批量写。
- **IMPLEMENT**: `set_batch(workdir, changes: list[dict]) -> tuple[dict, dict[str, str]]`。每个 change：`{"id": str, "must_keep"?: bool, "unusable"?: bool, "level"?: 1|2|3|None}`；`level: None` = 撤销人工档位（同 unset_level 语义）。锁内一次 load + rekey；逐条：按 stale 规则丢掉同 id 失效旧裁决；置 True 的标记触发互斥清除（must_keep↔unusable；同一条里两者都 True → ValueError）；must_at 规则同 `_write`；level 校验 `LEVELS`；条目只剩记账字段就删除；刷新锚点。全部算完再 `_save` 一次；任一条非法 → 抛 ValueError，什么都不写。返回 (新表, {id: 被清掉的标记名})。把 `_write` 的逐条合并逻辑抽成共用函数，不复制。
- **GOTCHA**: 校验必须在 `_save` 之前全部完成（原子性）；id 重复 → ValueError。
- **VALIDATE**: 单元测试：多条一次写入；一条非法整批不写；互斥；level None 撤销；must_at 只在 False→True 记；既有 review 测试不回归。

### Task 2: `POST /api/browse/batch`
- **ACTION**: 新路由。
- **IMPLEMENT**: 请求 `{project, items: [...], restore_shots?: [...]}`。校验：项目（同 `_mark_target` 的项目部分）；`items` 是非空列表且 ≤ `BATCH_ITEMS_MAX = 2000`；每条 `id` 是非空文本、在 segments_scored 里存在（否则 400 `UNKNOWN_SEGMENT_MSG`）、不重复；布尔字段必须是真布尔；level 是 1/2/3 或 null；每条至少一个字段。先做完所有会失败的读与校验（含手动分镜表可读、`_clean_restore`），再 `review.set_batch`；有任一条 `unusable: true` 时调用一次 `_remove_manual_shots(pdir, exclusions.spans(work))`；有 restore_shots 时调用一次 `_restore_manual_shots`。错误映射同 `_post_browse_unusable`（含 `shots_store.Busy` → 409）。响应：`{ok, segments: [这批各段最新状态], cleared: {id: 字段}, clip_list, wizard, removed_shots, restored, not_restored}`；拼装失败 → 200 + `warning`（同 `_saved_response`）。
- **GOTCHA**: 写 overrides 之后不能再有可能 400 的校验。
- **VALIDATE**: 后端测试：成功；参数非法（非列表、空、超上限、重复 id、未知 id、非布尔、非法 level、两个都 True、空字段）全部 400 且 overrides 未变；损坏 overrides → 409；批量不可用移除镜头且只备份一次；带 restore_shots 放回；纯手工项目（无分析结果）→ 400；项目不存在 404；非法项目名 400。

### Task 3: 前端勾选 UI
- **ACTION**: `batch-select.js` + `step-browse.js` 改动。
- **IMPLEMENT**: `b.sel = new Set()`（存 `_i`）、`b.selAnchor = null`。rowHtml 首列 `<input type="checkbox" class="pick" data-act="pickIdx" data-i>`（`checked` 按 sel，aria-label）；行加 `picked` class。`pickIdx(el, ev)`：Shift 且有锚点 → 按 `b.shown` 区间统一设成这一行的新状态；否则切换单条；更新锚点。全选勾选框放在 `#bFilters` 最前：全选 / 部分（indeterminate）/ 无；勾上 = sel 设为 `b.shown` 全部，取消 = 清空。操作栏 `#bBatch` 在 `#bList` 之后：无勾选时隐藏；否则「已选 N 段」+ 6 个按钮。只改勾选时不重画列表（切 class 与 checked）。setFilter / setView / resetBrowse / enterBrowse 清空 sel。
- **GOTCHA**: 勾选框点击不能触发行的 jumpSeg（委托取最内层，测试钉住）；勾选框得焦点时 S/A/D/X 不触发（INPUT 在 TYPING_TAGS 里）——保持此行为，并让点击勾选框后焦点回到列表（`el.blur()`），否则剪辑师接着按 ↓ / S 会失效。
- **VALIDATE**: 前端测试：点勾选框不换当前段；Shift 连选按显示顺序（含按话题视图）；全选只选当前筛选；三态；切筛选清空；操作栏计数与隐藏。

### Task 4: 批量操作与整批撤销
- **ACTION**: `batch-select.js` 的 `applyBatch(kind)` + `cliplist.js` 撤销接入。
- **IMPLEMENT**: kind → 每段目标变更：`add` → `{must_keep: true}`（若 unusable 同时 `unusable: false`，P9）；`remove` → `{must_keep: false}`；`usable` / `waste` → `{level: 3|1}`（本地乐观值同 markLevel：override true + level_reason）；`unusable` → `{unusable: true}`（本地 must_keep false）。跳过已经是目标状态的段；全部跳过时 toast 一句、不发请求。先 `await settleMarks()`，记录每段 before 快照，乐观改本地 → 一次 POST `/api/browse/batch` → 成功：按响应 segments 合并、更新 confirmed、`b.clip`、applyWizard、汇总提示（取消不可用 N 段 / 移出列表 N 段 / 移除 N 镜）、清空勾选、压入撤销条目 `{batch: [{id, before}], removed}`；失败：整批回到 confirmed、toast 服务端原因、保留勾选。切项目后回包丢弃（`bs() !== b`）。批量在途时按钮 disabled。撤销：batch 条目 → 用 before 快照拼 items（must_keep / unusable 显式给，level：override 为 true 给数字，否则 null）+ `restore_shots: removed` 一次 POST；失败重试一次，再失败丢弃并提示（同单段）。镜头有变化后 `resyncBrowse()`。
- **GOTCHA**: 批量与单段队列互斥：批量在途期间单段 S/A/D/X 必须排在批量之后（例如把批量 Promise 接到所涉各段的 `queueOf(id).chain` 上）。批量时不要对每段调用 refreshSeg（会重画面板 N 次）：每段 paintRow / paintDensityCell，然后统一 paintGroups / renderFilters / renderNote / renderClipPanel 一次。
- **VALIDATE**: 前端测试：批量放入只发一个请求且 body 正确；P9 互斥；失败整批回滚且保留勾选；成功清空勾选并用服务端 clip_list；Z 一次撤销整批（一个请求，带 restore_shots）；批量在途时单段 S 排在其后；切项目后旧回包不动界面；全部已是目标状态时不发请求。

### Task 5: 文档与登记
- **IMPLEMENT**: `docs/known-issues.md` 登记 KI-103（来源：用户反馈，③ 只能逐段加入剪辑列表；修复后标 fixed 并回填提交号）；`docs/界面流程-v2.md` ③ 加「批量选择」；`docs/GUI.md` 文件地图加 `batch-select.js` 与 `/api/browse/batch`；`docs/PROGRESS.md` 放行检查加 #25（真机：Shift 连选、全选、批量放入 / 不可用、Z 整批撤销）；`CHANGELOG.md` 一行。
- **VALIDATE**: 文档守卫测试通过（GUI.md 文件地图、名词守卫：界面不出现「必留」）。

---

## Testing Strategy

### Edge Cases Checklist
- [ ] 空选择时操作栏隐藏
- [ ] items 超上限 / 重复 id / 未知 id
- [ ] 同一条里 must_keep 与 unusable 同时为 true
- [ ] 并发：单段在途 + 批量；批量在途 + 单段
- [ ] 切项目时批量回包
- [ ] overrides.json 损坏 → 409 且不写
- [ ] 手动分镜表被锁（Busy）→ 409
- [ ] 无手动分镜表时批量不可用不新建 shots.json
- [ ] 按话题视图下 Shift 连选按显示顺序（跨组）

## Validation Commands
```bash
uv run pytest tests/test_browse_batch.py tests/test_frontend_batch_select.py
uv run pytest            # 全量（约 2 分钟），不加 -q
node --check gui/static/batch-select.js gui/static/step-browse.js gui/static/cliplist.js
```
项目未配置 lint / typecheck。冒烟（如做）：`AI_CUT_SECRETS=file`，`AI_CUT_CONFIG_DIR` / `AI_CUT_PROJECTS` / `AI_CUT_DRAFT_ROOT` / `AI_CUT_LOG_DIR` 指向临时目录；绝不碰真实钥匙串与真实剪映草稿目录。钥匙串里已有用户自己的 `ai-cut`/`deepseek` 条目（创建于 2026-10-20 13:58:31Z），不得读取或改动。

## Acceptance Criteria
- [ ] 全部任务完成，新增测试先红后绿
- [ ] 全量测试通过，覆盖率不低于 80%（当前 94.86%）
- [ ] python-reviewer / typescript-reviewer / security-reviewer 无 CRITICAL / HIGH
- [ ] 每个静态 JS 文件 ≤ 400 行（M13 惯例）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 批量与单段队列交错导致状态错乱 | M | H | 批量前 settleMarks；批量在途时单段排队；confirmed 快照对账 |
| 批量撤销放回镜头只认最近一次备份 | M | M | 一次批量只备份一次；与单段语义一致，测试钉住 |
| cliplist.js 超 400 行 | M | L | 批量逻辑全部放 batch-select.js，cliplist 只加钩子 |
