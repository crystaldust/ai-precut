# Plan: 画面理解 · 第 5 阶段 —— ③ 呈现与收尾（含旧时间轴认回）

## Summary
③ 片段浏览里显示画面信息：对白句显示画面描述 / 画面问题，画面片段（`V001`…）按时间插进列表，可手动改档、放进剪辑列表，并一路带到 ④ 选段、⑤ 分镜表和剪映导出（保留原声，没有字幕）。画面片段不进档位统计、话题预算、待定决策队列和 AI 自动选段。另做一次性迁移：`43bc555` 之前付过费的 `visual_timeline.json`（key 含浏览小样 mtime）在浏览小样没变时认回为当前，重新分析不再上传。最后补文档、放行检查 #34，并给出开 / 关对比验收清单。

## User Story
As 剪辑师, I want 在 ③ 里看到每句话的画面情况和没有对白的画面片段，并能把画面片段放进剪辑列表, so that 粗剪里不漏掉无人声的关键画面，也少删画面有问题的镜头。

## Problem → Solution
第 4 阶段产出的画面字段只进了档位理由，画面片段只存在 `segments_scored.json["visual_segments"]` 里没人看得到；旧项目的已付费时间轴被判过期 → ③ 能看到、能用；旧时间轴在浏览小样没变时直接认回。

## Metadata
- **Complexity**: Large
- **Source PRD**: `.claude/PRPs/prds/multimodal-video-understanding.prd.md`
- **PRD Phase**: 5 · ③ 呈现与收尾
- **Estimated Files**: 约 18（新模块 1、改代码 9、改测试 / 新测试 6、文档 3）

---

## UX Design

### Before
```
③ 列表（按时间）
 00:12 可用 合同  「我们今天签合同…」   画面：…（只在理由里）   6s  ＋ ⊘
 00:40 待定 寒暄  「对」                                   1s  ＋ ⊘
 （00:41–01:02 没有对白：什么都不显示）
```

### After
```
③ 列表（按时间）
 00:12 可用 合同    「我们今天签合同…」 画面：两人，签合同 · 晃动        6s  ＋ ⊘
 00:40 待定 寒暄    「对」                                              1s  ＋ ⊘
 00:41 可用 画面片段 ▣ 扫码付款 9600 元（画面上的字：9600）            21s  ＋ ⊘
筛选：全部 / 可用 / 待定 / 废片 / … / 画面片段（新）
右侧当前片段：画面描述、画面上的字、画面问题
剪辑列表：▣ 00:41 扫码付款 9600 元（没有对白时显示画面标题）
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| ③ 对白行 | 理由里带「画面：…」 | 另起一小行：画面描述（截 40 字）+ 画面问题标签 | 关着画面理解时没有这一行 |
| ③ 画面片段 | 不显示 | 按时间插入，主题列显示「画面片段」，正文显示画面标题 | 话题视图里单独一组「画面片段」放最后 |
| ③ 计数 / 话题时长 | — | 不含画面片段；筛选「画面片段」单独计数 | 待定上限、预算不变 |
| ③ 改档 / 不可用 / 剪辑列表 | 只对对白句 | 画面片段同样可以 | 改档锚点按时间（见 Task 3） |
| ④ 待定决策队列 | 待定对白句 | 不含画面片段 | 画面片段只能手动放入 |
| ⑤ / 剪映 | — | 放进剪辑列表的画面片段整段成镜，原声保留、无字幕，备注「画面：<标题>」 | 与现在 B-roll 镜头相同处理 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/review.py` | 59-110, 265-340 | 锚点 `_anchor_of` / `_resolve_keys` / `apply` / `_scored_segments` |
| P0 | `gui/payloads.py` | 42-110, 144-228 | `/api/browse` 组装、计数、话题、待定队列、`clip_list` |
| P0 | `pipeline/select.py` | 143-195, 316-345, 595-640 | 必留段成镜、话题池、`missing_must_keep`、`run` |
| P0 | `gui/static/step-browse.js` | 28-34, 72-160, 163-260 | 行、筛选、列表、当前片段 |
| P0 | `pipeline/vision_run.py` | 83-140, 355-383 | `run_key`、`timeline_current`、`_State`、`run` |
| P1 | `gui/static/cliplist.js` | 33, 92-150, 206-224 | 标记、剪辑列表项 |
| P1 | `gui/project_routes.py` | 353-370, 470-490 | `_mark_response`、不可用的 id 校验 |
| P1 | `gui/result_payload.py` | 97-130 | ⑤ 镜头理由按重叠找片段 |
| P1 | `pipeline/classify.py` | 194-215, 249-270 | `classify_visual` 输出字段（level / level_reason / label / visual） |
| P2 | `tests/fe_browse.py`、`tests/test_frontend_browse.py` | all | 前端测试夹具（node 跑 JS） |
| P2 | `tests/test_review.py`、`tests/test_browse_payload.py`、`tests/test_select.py`、`tests/test_vision_run.py` | — | 测试风格 |

## External Documentation
No external research needed — feature uses established internal patterns.

---

## Patterns to Mirror

### NAMING / 模块文档
// SOURCE: pipeline/vision_align.py:1-20（中文模块 docstring、常量全大写、私有函数下划线）

### 锚点
// SOURCE: pipeline/review.py:59-65
```python
def text_key(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", "", text or "").encode("utf-8")).hexdigest()[:12]

def _anchor_of(seg: dict) -> dict:
    return {"text": text_key(seg.get("text") or ""), "start": round(float(seg.get("start") or 0), 2)}
```

### 必留段成镜
// SOURCE: pipeline/select.py:143-158
```python
def _must_keep_shot(seg: dict, weights: dict | None) -> dict:
    ...
    return {"segment_id": seg["id"], "topic": seg.get("topic") or "未归类", ...}
```

### 错误处理（文件坏了 → 409，不当「没有」）
// SOURCE: gui/payloads.py:49-51
```python
scored = schema.read_json(work / "segments_scored.json", default=None)  # 损坏 → 409，不是「还没有」
if not scored:
    raise FileNotFoundError(NO_SCORED_MSG)
```

### 前端行渲染（全部经 esc / num）
// SOURCE: gui/static/cliplist.js:217-224

### 测试
// SOURCE: tests/test_review.py — `review.set_must(tmp_path, "S002", True); assert review.load(tmp_path)["S002"]["must_keep"] is True`
// SOURCE: tests/fe_browse.py — `seg(1, 0, 6, 3, "讲合同", "甲<b>粗体</b>", reason=..., flags=[...])`，`in_browse(script, routes=None)`

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/visual_clips.py` | CREATE | 画面片段的读取 / 校验 / 合并 / 判断（`is_visual`、`from_scored`、`with_visual`），供 review / payloads / select / routes 共用 |
| `pipeline/review.py` | UPDATE | 画面片段的按时间锚点；`_scored_segments` 带上画面片段 |
| `gui/payloads.py` | UPDATE | ③ 合并画面片段；计数 / 话题 / 待定队列排除；`counts.visual` |
| `gui/project_routes.py` | UPDATE | 不可用 id 校验与 `_mark_response` 认画面片段 |
| `gui/browse_batch.py` | UPDATE | 批量标记同样认画面片段（如有 id 校验 / 查找） |
| `gui/result_payload.py` | UPDATE | ⑤ 理由与 `applied_segments` 带画面片段 |
| `pipeline/select.py` | UPDATE | 必留的画面片段成镜；话题池排除画面片段；`missing_must_keep` 核对画面片段 |
| `pipeline/vision_run.py` | UPDATE | 旧版 key 认回（时间轴、state、段结果） |
| `gui/static/step-browse.js` | UPDATE | 画面行 / 画面片段行、筛选、话题视图分组、当前片段详情 |
| `gui/static/cliplist.js` | UPDATE | 剪辑列表项无对白时用画面标题 |
| `gui/static/*.css`（③ 所在样式表） | UPDATE | 画面行的小字样式（复用现有 `<small>` / chip） |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 加 `pipeline.visual_clips`（`test_structure`） |
| `tests/test_visual_clips.py` | CREATE | 新模块 |
| `tests/test_review.py`、`test_browse_payload.py`、`test_browse_marks.py`、`test_select.py`、`test_vision_run.py`、`test_frontend_browse.py`、`test_frontend_cliplist.py` | UPDATE | 见各 Task |
| `docs/GUI.md`、`docs/PROGRESS.md`（放行检查 #34）、PRD | UPDATE | 文档 |

## NOT Building
- 画面片段进 AI 自动选段 / 话题预算 / 待定上限（PRD：只手动放入）
- 画面片段静音或单独处理音轨（保留原声，与现有 B-roll 镜头一致；要静音由剪辑师在剪映里关）
- 画面片段的字幕（没有对白就没有字幕）
- 改 ⑤ 的手动加镜头交互（画面片段从 ③ 进剪辑列表即可）
- 复制过、修改时间已丢的旧项目的认回（旧 key 依赖修改时间，无法核对，见 Risks）
- ② 上的「可沿用旧结果」提示（迁移在分析时自动发生，任务日志写一行）
- 开 / 关对比验收本身（需要剪辑师用 3 条真实素材手工完成，计划只给清单）

---

## Step-by-Step Tasks

### Task 1: `pipeline/visual_clips.py`
- **ACTION**: 新模块，集中「画面片段」的读取与判断。
- **IMPLEMENT**:
  - `KIND = "visual"`、`TOPIC = "画面片段"`。
  - `is_visual(seg) -> bool`：`seg.get("kind") == KIND`。
  - `from_scored(scored: dict) -> list[dict]`：取 `scored.get("visual_segments")`，不是列表 → `[]`；逐项校验（dict、`id` 为字符串、`start`/`end` 数值且 end>start、`level` ∈ {1,2,3}），不合格的丢掉；每项返回新 dict：`{**v, "topic": TOPIC, "text": ""}`（`text` 保持空，标题在 `label`）。
  - `with_visual(scored) -> list[dict]`：`segments`（原样）+ `from_scored(scored)`，按 `start` 稳定排序。供需要「全部可标记片段」的地方用。
  - `title(seg) -> str`：`label` → `visual.desc` → `TOPIC`，截 40 字。
- **MIRROR**: vision_align 的模块风格；不改入参（返回新 dict）。
- **GOTCHA**: 关闭画面理解时 `classify.run(vision=False)` 不写 `visual_segments` → 自然为空，开关关闭时所有下游行为不变（金标准测试 `test_vision_off_golden.py` 必须仍过）。
- **VALIDATE**: `tests/test_visual_clips.py`：坏项被丢、排序、不改入参、标题回退。

### Task 2: 旧版时间轴 key 认回（`vision_run`）
- **ACTION**: 在 `run()` 判断 `timeline_current` 之前，若磁盘上的结果是旧版 key 且浏览小样没变，把它们改写成新 key。
- **IMPLEMENT**:
  - `_legacy_key(proxy, setting) -> str | None`：复刻 `43bc555` 之前的公式：`json.dumps({"size": st.st_size, "mtime_ns": st.st_mtime_ns, "tier": ..., "prompt": vision.PROMPT_VERSION, "chunk_s": vision.CHUNK_S}, sort_keys=True)` → sha256[:16]（见 `git show 43bc555 -- pipeline/vision_run.py`）。
  - `_adopt_legacy(work, proxy, setting, key) -> bool`：`legacy = _legacy_key(...)`；`legacy is None or legacy == key` → False。依次处理：`visual_timeline.json`、`vision/state.json`、`vision/chunk_*.json`、`vision/chunk_*.raw.json` —— 只改 `key == legacy` 的文件，`{**data, "key": key}` 用 `schema.write_json` 原子写。改了任意一个 → True。
  - `run()`：先算 `key = run_key(...)`；非 None 时调 `_adopt_legacy`，再做 `timeline_current` 判断。认回时返回的时间轴带 `"adopted": True`（不写进文件）。不改 `aicut.py`（已 800 行）：任务日志里的说明由 `aicut.py` 现有的时间轴打印带出则顺带显示，带不出就只在 GUI.md 说明。
- **MIRROR**: `_reset_dir` / `_State` 的读写方式；`_read` 宽松读。
- **GOTCHA**:
  - 旧 key 已含 tier / prompt / chunk_s，匹配即说明这三项也一致。
  - 只读不写的 `timeline_current`（剪辑台轮询）不做迁移，避免轮询写盘；所以 ② 会先显示「需要更新」，点开始分析后云端这步秒过、无上传。下游 `align`（本机）和 DeepSeek 画面两轮会因时间轴 key 变化重跑（约 3 万 token / 小时素材）——写进 GUI.md。
  - 复制后丢了修改时间的项目认不回（旧 key 本身依赖修改时间）。
- **VALIDATE**: `tests/test_vision_run.py`：(a) 旧 key 时间轴 + 原浏览小样 → `run` 返回时间轴、`FakeClient.uploads == []`、文件 key 变为新 key；(b) 修改时间变了 → 不认回（会走正常流程）；(c) 半途的 state + 段结果是旧 key → 认回后只补未完成段；(d) 非旧 key 的文件不被改写。

### Task 3: 改档锚点认画面片段（`review`）
- **ACTION**: 画面片段的裁决按时间锚定，不按文字（空文字哈希全相同）。
- **IMPLEMENT**:
  - `_anchor_of(seg)`：`is_visual` → `{"text": VISUAL_ANCHOR, "start": round(start, 2)}`，`VISUAL_ANCHOR = "visual"`（不会与 12 位十六进制哈希撞）。
  - `_resolve_keys`：`keys[sid]` 对画面片段取 `VISUAL_ANCHOR`；距离上限按种类：画面片段 `VISUAL_RELOCATE_MAX_SECONDS = 3.0`，对白仍 `RELOCATE_MAX_SECONDS`。
  - `_scored_segments`：改用 `visual_clips.with_visual(scored)`（这样写裁决时画面片段有锚点、`_rekey` 认得它们）。
  - `apply()` 不改（画面片段带 `level`，同样套裁决）。
- **GOTCHA**: 对白句的锚点、迁移行为逐字节不变（现有 `test_review.py` 全过）。重新分析后 V 编号可能整体平移，按起点 ±3 秒找回；对不上 → 照旧算失效并在 ④ 警告。
- **VALIDATE**: 新测试：V003 改为可用 → 重新分析后同一时间的片段变成 V004 → 裁决跟到 V004；两个画面片段起点相差 > 3 秒不串；对白句同文同起点不会被画面片段抢走。

### Task 4: ③ 接口（`payloads` / routes）
- **ACTION**: `/api/browse` 返回画面片段，并让标记接口认它们。
- **IMPLEMENT**:
  - `payloads.browse`：`segments = review.apply(visual_clips.with_visual(scored), overrides)`；话题统计循环与 `counts` 只算 `not is_visual(s)`；`counts["visual"] = 画面片段数`；`speakers` 只用对白句；`clip_list` 用全部（剪辑列表可含画面片段）。
  - `_pending_items`：排除画面片段。
  - `applied_segments`（`result_payload._topbar` 用）带画面片段，使剪辑列表总时长一致。
  - `project_routes._post_browse_unusable` 的 `known` 与 `_mark_response` 的查找改用 `with_visual`；`browse_batch` 同理（先读代码确认有无同类查找）。
  - `clip_list` 每项加 `"kind"` 与 `"title"`（画面片段 → `visual_clips.title`）。
- **GOTCHA**: `payloads.py` 里 `s["level"] == 3` 等计算不能把画面片段算进 `usable_dur`（会影响话题预算显示）。
- **VALIDATE**: `test_browse_payload.py`：带 `visual_segments` 的 scored → 列表按时间交错、`counts` 不含、`counts.visual == n`、话题里没有「画面片段」时长；关闭（无 `visual_segments`）响应与现在相同。`test_browse_marks.py`：对 `V001` 设不可用 / 加入剪辑列表 / 改档返回 200 且 `segment` 非空。

### Task 5: ④ / ⑤ / 导出（`select`、`result_payload`）
- **ACTION**: 放进剪辑列表的画面片段成为整段镜头。
- **IMPLEMENT**:
  - `select.run`：`segments = with_lines(review.apply(visual_clips.with_visual(scored), overrides), ...)`；`stale = review.stale_ids(with_visual(scored), overrides)`。
  - `select.select` 话题池循环：`if visual_clips.is_visual(s): continue`（画面片段不进自动选段）；`_ensure_must_keep` 原样把必留的画面片段整段成镜（topic 已是「画面片段」）。
  - 镜头 `sub`：`shot_sub.sub_for` 对空文字返回 `""` → 时间轴里是 B-roll、无字幕；`to_shot_list` 的 `note` 用 topic → 「画面片段」；改为画面片段时 `note = f"画面：{title}"`。
  - `select.missing_must_keep`：用 `with_visual`，导出前同样核对画面片段是否在分镜表里。
  - `result_payload._note`：重叠查找的 `segments` 带画面片段。
- **GOTCHA**: `select.py` 已 659 行，只加几行，逻辑放 `visual_clips`。`signals` 缺失由 `.get` 处理（`run` 里的回填只对缺 `signals` 的段补空 dict，画面片段同样补空即可）。
- **VALIDATE**: `test_select.py`：画面片段可用但未必留 → 不入选；必留 → 整段成镜、`sub == ""`、note 以「画面：」开头；不可用的画面片段不入选；`missing_must_keep` 报出未覆盖的画面片段。导出链不改（`timeline.compose_timeline` 已把空字幕镜头当 B-roll、原声保留），加一个 `compose_timeline` 空字幕用例确认。

### Task 6: ③ 前端（`step-browse.js`、`cliplist.js`）
- **ACTION**: 显示画面信息与画面片段。
- **IMPLEMENT**:
  - `rowHtml`：对白句有 `seg.visual?.desc` 时，`.sum` 下加一行 `<small class="vis">画面：${esc(desc.slice(0,40))}</small>` + `visual.issues` 每项一个 chip（复用 `VISUAL_TAGS` 的 chip 样式）；画面片段：主题列「画面片段」，正文用 `▣ ` + `esc(label || desc)`，有 `visual.text_on_screen` 时追加「（画面上的字：…）」。
  - `FILTERS` / `FILTER_TESTS` 加 `visual: s => s.kind === 'visual'`，标签「画面片段」；其余档位筛选默认仍包含画面片段（按档位筛）——计数在 `renderFilters` 里照用 `b.segs`。
  - 话题视图：`kind==='visual'` 的放进最后一组「画面片段」；`groupStats` 不受影响。
  - `renderNow`：当前片段有 `visual` 时显示画面描述、画面上的字、画面问题；画面片段正文为空时用标题。
  - `cliplist.js clipItemHtml`：`it.text` 为空时用 `it.title`，前缀 `▣ `。
- **GOTCHA**: 一切来自模型的字段都经 `esc`；数值经 `num`（XSS 测试已有模式：夹具里放 `<b>`）。密度条 `renderDensity` 自然包含画面片段（时长按素材），无需改。
- **VALIDATE**: `test_frontend_browse.py`：交错显示、筛选「画面片段」、画面描述与 issue chip、`<b>` 被转义、关闭时（无 visual 字段）DOM 与现在相同；`test_frontend_cliplist.py`：空文字项显示标题。

### Task 7: 文档与放行
- **ACTION**: 
  - `docs/GUI.md` ③ 节：画面行、画面片段、筛选、剪辑列表与导出（原声、无字幕）、旧结果认回与它会重跑的本机整合 / DeepSeek 画面两轮。
  - `docs/PROGRESS.md` 放行检查 #34：③ 画面显示与画面片段进剪辑列表、⑤ 有该镜头、剪映工程里有原声无字幕、改档后重新分析仍在、旧项目重新分析无上传（`work/vision_usage.json` 不增加）。
  - PRD 第 5 阶段状态说明；验收清单（开 / 关对比两项指标的做法）写进报告。
  - `packaging/ai-cut.spec` 加 hiddenimport。
- **VALIDATE**: `tests/test_structure.py` 通过。

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| visual_clips 坏项 | `visual_segments` 含非 dict、缺 level、end<=start | 丢弃 | Yes |
| 关闭时不变 | scored 无 `visual_segments` | browse / select / 金标准与现在相同 | Yes |
| 锚点平移 | V003 裁决，重分析后同起点为 V004 | 裁决跟到 V004 | Yes |
| 锚点不串 | 两片段起点差 4 秒 | 不互相认领 | Yes |
| 必留成镜 | V001 must_keep | 整段镜头、无字幕、note「画面：…」 | |
| 不进自动选段 | V001 level 3 未必留 | 不入选 | |
| 待定队列 | V002 level 2 | 不在 ④ 待定队列 | |
| 认回旧时间轴 | 旧 key、修改时间未变 | 无上传、key 改新 | |
| 不认回 | 修改时间变了 | 正常流程 | Yes |
| 前端转义 | label 含 `<b>` | 原样文本 | Yes |

### Edge Cases Checklist
- [x] 空：没有画面片段 / 关闭画面理解
- [x] 非法类型：模型写坏的 `visual_segments`
- [x] 重新分析后编号变化
- [ ] 并发：标记接口沿用 `review._LOCK`，不新增

---

## Validation Commands

### Unit Tests
```bash
uv run pytest tests/test_visual_clips.py tests/test_review.py tests/test_browse_payload.py tests/test_browse_marks.py tests/test_select.py tests/test_vision_run.py tests/test_frontend_browse.py tests/test_frontend_cliplist.py tests/test_vision_off_golden.py -q
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest -q -p no:warnings -o addopts=""
uv run pytest --cov
```
EXPECT: No regressions；覆盖率 ≥80%

### Browser Validation
```bash
python3 gui/server.py --open
```
用 `projects/vision-p4-acceptance` 看 ③（本机，不花钱）。

### Manual Validation
- [ ] ③ 画面行与画面片段显示正确，筛选计数正确
- [ ] 画面片段放进剪辑列表 → ④ 确认 → ⑤ 有该镜头 → 导出剪映，有原声无字幕
- [ ] 旧项目（未复制过的原项目，如 `projects/vision-gui-acceptance`）重新分析：云端步骤无上传、`vision_usage.json` 不增加
- [ ] 开 / 关对比验收（剪辑师，3 条素材）：⑤ 因画面删除减少 ≥50%；事先标注的无人声关键画面 ≥80% 在画面片段里

## Acceptance Criteria
- [ ] 全部任务完成，测试通过，金标准不变
- [ ] 审查无 CRITICAL / HIGH
- [ ] 文档与放行检查 #34 更新

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 画面片段混进计数 / 预算，改变关闭画面理解或现有项目的数字 | M | H | 所有统计显式排除 `is_visual`；关闭时金标准与现有测试兜底 |
| 画面片段重分析后边界变化大，裁决失效 | M | L | ±3 秒找回；失效照旧在 ④ 警告 |
| 认回误判（换素材但大小、修改时间都相同） | 极低 | M | 旧 key 含纳秒级修改时间 + 大小 |
| 复制过的旧项目认不回 | M | M | 明说限制；用户手动处理 / 重新付费 |
| `select.py`、`to_jianying.py` 继续变长 | M | L | 逻辑放 `visual_clips`，导出链不改 |

## Notes
- 声音：画面片段导出时保留原声（现有 `clips.ensure` 统一带 aac 音轨，`to_jianying` 音量 1.0）。这是计划默认，Gate 1 确认。
- `aicut.py` 正好 800 行，本阶段不改它。
