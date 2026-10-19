# Implementation Report: 里程碑 2「必留内容不丢」（GL-08 · GL-09 · GL-24 · GL-25）

## Summary

- **GL-08**：选段里必留段一律整段进片（无视档位 / 话题预算 0 / exclude / 预算用尽 / `_trim` / `MAX_SHOT` / `MIN_SHOT`），并有守卫：丢失即抛 `SelectionError`。结果新增 `must_keep_ids / must_keep_total / over_target / suggested_target / warnings`，`stats.must_keep`；选段表 markdown 增「## 警告」。
- **目标时长由剪辑师决定**：`new --target`（不给且在终端里 → 询问，回车用预设；非终端 → 预设）；`select --target` 保存目标后只重跑选段，`select.run` 按新目标重分话题预算（副本，不改 `segments_scored.json`）。GUI 新建弹窗有时长输入（随预设预填）、顶栏「改目标时长」、`/api/job` 新任务 `select`；①处理素材 / 重新选段完成后若必留合计超目标自动弹窗（默认值 = 必留合计向上取整到 5 秒）。
- **GL-09a**：逐句标注每批额外重试 2 次，漏标 id 单独补问，模型编造的 id 丢弃；仍失败 → 先落盘（`complete:false`、`input_hash`、逐句 `annotation_failed`）再抛 `AnnotationIncomplete`，`cmd_text` `[x]` 退出码 1（prepare 任务失败）；输入未变时重跑只补失败句子（沿用上次话题分段），旧版结果文件无 `complete` 字段 → 全量重跑。
- **GL-09b / GL-24**：标注失败段 → 待定（「AI 标注失败，需要你判断」）；必留话题段与标注失败段不被「待定超限」或「画面过暗」降为废片；超限给 `[!]` 警告；`score` 显示「自动降级 N」。
- **GL-25**：`build` 在切片前核对分镜表（`shots.json` 或 `work/shots-selected.json`）是否覆盖每个必留段（按时间合并区间、覆盖 ≥90%），缺了就 `die` 并列出 `mm:ss "原话"` 与补救办法；没有 `segments_scored.json`（纯手工流程）不查；`overrides.json` 损坏 → `die`。
- `/api/state` 新增 `selection` 摘要、`shots_from_selection`；没有手存 `shots.json` 时用 `work/shots-selected.json` 预填分镜表，有手存的不覆盖（弹窗里提示）。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 高：单测 + 300 组随机不变量 + 进程内 E2E + 服务 curl 冒烟 |
| Files Changed | 13 + docs | 14 修改 + 2 新建（含 README / SOP） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | 目标时长校验 `check_target_duration` | done | 另拒 `inf`/`"inf"`（用 `math.isfinite`，计划版 `round(inf)` 会抛 OverflowError） |
| 2 | GL-08 选段回归测试（RED） | done | 额外加：无必留时字段为空、`fmt_duration`、随机不变量里加入 `ending` 规则、`uncovered_must_keep` 重叠镜头不重复计数 |
| 3 | GL-08 实现 | done | 守卫与汇总抽成 `_must_keep_report()`；`uncovered_must_keep` 先合并区间（偏差，见下） |
| 4 | GL-09a 测试（RED） | done | 修正计划里一条断言（见偏差）；额外加旧版结果不续跑、补问只问漏掉的句子 |
| 5 | GL-09a 实现 | done | 合并逻辑抽成 `_merge()` |
| 6 | GL-09b + GL-24 测试（RED） | done | 额外加 `classify()` 不改输入、暗画面不把废片抬成待定 |
| 7 | GL-09b + GL-24 实现 | done | 降级逻辑抽成 `_cap_pending()`；`_assemble` 复用 `_must_topic_names` |
| 8 | CLI 测试（RED） | done | 新建 `tests/test_aicut_must_keep.py`（19 条） |
| 9 | CLI 实现 | done | GL-25 的读盘 + 文案放进 `pipeline/select.py`（偏差，见下） |
| 10 | GUI 服务测试（RED） | done | 新建 `tests/test_server_target.py`（17 条） |
| 11 | GUI 服务实现 | done | `JOB_COMMANDS` 模块级；`start_job` 先校验再登记；摘要用 `select.summary()` |
| 12 | 前端 + 静态测试 | done | 文案全部在 `COPY_*` / `JOB_TITLES` 常量 |
| 13 | 登记册状态 | 未做（按约定） | `docs/go-live-blockers.md` 由编排方更新 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | lint/typecheck 未配置；`import aicut, gui.server, pipeline.*` 通过；`index.html` 内联脚本 `node --check` 通过 |
| Unit Tests | Pass | `uv run pytest`：373 → **468 passed**（+95） |
| Build | N/A | 未打包 App |
| Integration | Pass | ① 本地起 `gui/server.py --port 18931`：页面含新 UI、`/api/presets` 正常、`/api/new target=abc` → 400「目标时长应为 10–3600 秒…」、`/api/job` select/未知任务对不存在项目 → 400，已停服务；② 进程内 E2E（临时 PROJECTS）：必留 3 段（含 exclude 话题、30s > MAX_SHOT）+ `select --target 30` → 3 段整段进片、`[!] 必留内容共 46 秒，超过目标 30 秒…建议 --target 50`、project.json 目标改为 30；手存分镜表缺 2 段 → `build` `[x] 分镜表缺少 2 段必留内容：01:00 "第3句"；01:40 "第5句"…` 退出码 1、未切片 |
| Edge Cases | Pass | 计划 Edge Cases 清单除「并发」（GL-17，M4）外均有测试 |

## Files Changed

| File | Action |
|---|---|
| `pipeline/schema.py` | UPDATED（`TARGET_MIN/MAX`、`TARGET_ERROR`、`check_target_duration`） |
| `pipeline/select.py` | UPDATED（GL-08、`fmt_duration`、`SelectionError`、`uncovered_must_keep`、`missing_must_keep`、`describe_missing`、`summary`、`run()` 重分预算） |
| `pipeline/classify.py` | UPDATED（GL-09b、GL-24、`pending`/`warnings` 字段） |
| `pipeline/understand_text.py` | UPDATED（GL-09a、docstring） |
| `aicut.py` | UPDATED（`warn`、`ask_target`、`new/select --target`、`text/score/select` 报告、`build` 必留校验、模块 docstring） |
| `gui/server.py` | UPDATED（834 → 847 行：`JOB_COMMANDS`、`select` 任务、`/api/new` target、`project_state` 摘要与预填） |
| `gui/static/index.html` | UPDATED（新建时长输入、改目标时长按钮与弹窗、任务结束后超时长弹窗） |
| `README.md`、`docs/SOP.md` | UPDATED（`--target` 用法） |
| `tests/test_schema.py`、`tests/test_select.py`、`tests/test_classify.py`、`tests/test_understand_text.py`、`tests/test_static_pages.py` | UPDATED |
| `tests/test_aicut_must_keep.py`、`tests/test_server_target.py` | CREATED |

## Deviations from Plan

1. **`uncovered_must_keep` 先合并区间再算覆盖**：计划版直接累加各镜头与必留段的交集，两镜重叠（同一段打了两遍点）会重复计数而误判「已覆盖」。加了回归测试。
2. **GL-25 的读盘与文案放在 `pipeline/select.py`**（`missing_must_keep()`、`describe_missing()`、常量 `MUST_KEEP_MISSING`），`aicut.py` 只做捕获 + `die`；原因是 `aicut.py` 已 820 行。同理选段摘要用 `select.summary()`，让 `gui/server.py` 只增 13 行。
3. **`check_target_duration` 用 `math.isfinite`**：计划版对 `inf` 会在 `round()` 抛 `OverflowError`（不是 ValueError，服务端会 500）。
4. **修正计划中的一条测试断言**：`test_rerun_only_reannotates_failed_segments` 原断言话题名 `== ["开场寒暄", "讲解合同"]`，但 50 句时 `_split_large` 会拆成「(1/3)」等，断言本身错误；改为「续跑沿用上次落盘的话题分段」（`res["topics"] == 第一次落盘的 topics`），验证的仍是同一意图。
5. **`_apply_dark` 只保护待定**：计划版对「保护段」一律设为待定，会把关键信息占比 ≥30% 的必留话题里的「闲聊寒暄」等废片抬成待定。改为只在原本是待定时保留待定，加回归测试。
6. **前端额外常量**：`COPY_MUST_KEEP_OVER_TITLE`、`COPY_TARGET_TITLE`、`COPY_NEW_TARGET_LABEL`、`COPY_RESELECT_DONE`、`JOB_TITLES`，让所有新文案都是命名常量；新建项目时长为空 → toast 提示，不提交。
7. 未改 `docs/go-live-blockers.md`（按编排约定）。

### 改写的既有测试（旧断言固化了缺陷）

| 测试 | 原断言 | 新断言 | 理由 |
|---|---|---|---|
| `test_classify.py::test_pending_capped_by_ratio` → `test_non_must_pending_capped_by_ratio` | 必留话题「讲解合同」的 60 段待定被降到 ≤ 上限 | 话题换成非必留「闲聊日常」，并断言 `pending == {"limit", "demoted"}`、无警告 | 原断言要求「必留话题被降为废片」，正是 GL-09 缺陷；必留话题场景由新测试 `test_must_topic_pending_never_demoted` 覆盖 |
| `test_understand_text.py::test_failed_batch_recorded_but_others_kept` → `test_failed_batch_retried_then_succeeds` | 第 1 批失败被记录、其余照常 | 失败批次被重试后成功，`failures == []`、`complete` | 原断言把「静默丢弃一批」当正确行为（GL-09） |
| `test_understand_text.py::test_missing_segments_fall_back_to_last_topic` | 标注返回空 | 标注走正常 FakeClient | 该测试只验证话题兜底；返回空在新逻辑下会（正确地）报 `AnnotationIncomplete` |

## 新发现缺陷（未修，建议登记）

| 位置 | 描述 |
|---|---|
| `aicut.py`（881 行） | 超过 800 行软上限（本次前已 820），同 KI-54 性质；建议按命令拆模块 |
| `aicut.py:396`（`cmd_select` → `pipeline/select.py:518` `review.load`） | `overrides.json` 损坏时 `select`/`prepare` 抛未捕获的 `OverridesCorrupt`，GUI 日志里是 traceback 而非人话（`build` 已在本次处理） |
| `gui/static/index.html:587`（`createProject`） | 创建成功后的 `loadProjects().then(...)` 内嵌了页面启动时的 hash 导航代码（复制残留），会按旧 URL hash 再选一次项目，与随后的 `selectProject(name)` 竞争 |
| `pipeline/classify.py:133` | `_level_of` 只按话题名判必留（`_topic_must`），按关键信息占比判出的必留话题里的句子拿不到「属于必留话题，需要你判断」的待定理由，会按短句等规则直接判废片；与 `topics[].must` 口径不一致 |

## Pending manual checks（需要人工 / 浏览器 / 真实素材）

- [ ] CLI：真实终端里 `aicut.py new t1 --material <视频>` → 被问时长，回车得预设；`--target 240` 不问。
- [ ] 无效 DeepSeek Key 跑 `aicut.py text <项目>` → `[x] N 句逐句标注失败 … 只会重跑这 N 句`、退出码 1、`segments_text.json` 有 `"complete": false`；恢复 Key 再跑 → `[✓] … · 已补齐上次失败的句子`。（真实 HTTP 重试耗时未测）
- [ ] GUI：新建项目弹窗时长输入随预设变化；创建后顶栏显示目标。
- [ ] GUI：①处理素材完成且必留超时长 → 自动弹窗，文案「必留内容共 X 分 Y 秒，超过目标 Z」、默认值 = 建议值；确认后标题「正在重新选段」，日志只有选段行，完成后顶栏目标更新。
- [ ] GUI：顶栏「改目标时长」随时可用；有手存分镜表时弹窗显示「不会覆盖」提示；无手存时分镜表 Tab 显示预填的选段结果。
- [ ] GUI：任务失败（标注失败 / GL-25）后模态层关不掉仍是 GL-22（M4）。
- [ ] 打包版（`dist/AI粗剪.app`，FROZEN 分支 `run_cli(argv)`）跑一次 `select` 任务。

## 审查修复（两份审查，无 CRITICAL）

TDD：每项先写失败测试并确认 RED，再实现。`uv run pytest`：468 → **510 passed**（+42）。服务 curl 冒烟复跑通过；`index.html` 内联脚本 `node --check` 通过。

| # | 级别 | 修复 | 测试 |
|---|---|---|---|
| 1 | HIGH | `pipeline/llm.py`：200 但响应体截断/非 JSON → `LLMError`（按抖动重试）；`chat_json` 对 `choices` 结构异常（非 dict、null、message 非 dict、content 非文本）→ `LLMError`。`understand_text._annotate_once/_normalize`：`segments` 不是对象列表、`entities` 不是列表、id 不是字符串 → 该批 `LLMError`（重试 → failures → 落盘），不再崩。`cmd_text` 改为捕获所有 `LLMError`（话题分段阶段的失败也 `[x]`，不再 traceback） | `test_llm.py` +5（含参数化）、`test_understand_text.py::test_wrong_shape_is_retried_not_crash`（4 种形状）、`test_aicut_must_keep.py::test_text_llm_error_in_topic_stage_dies` |
| 2 | MEDIUM | 未完成结果写 `segments_text.partial.json`（续跑也从它读），只有完整时才原子替换主文件并删 partial；所有写入走 `schema.write_json`。主文件不会被不完整结果覆盖；分档时若存在 partial → `[!]` 提示「本次分档用的是上一次完整结果」 | `test_incomplete_rerun_does_not_clobber_complete_main_file`、`test_resume_uses_partial_then_replaces_main_and_removes_partial`、`test_score_warns_when_partial_pending` |
| 3 | MEDIUM | `classify.run`：`complete is False` → 抛 `TextIncomplete`，`cmd_score` 拒绝并给人话（选「拒绝」：新代码永远不会把不完整结果写进主文件，prepare 在 text 就已失败停下，所以拒绝不会打断 prepare 流程；只有旧开发版/手改文件会触发）。旧版文件 `failures[].ids` → 标 `annotation_failed`（进待定、受保护）并警告数量。`cmd_status` 对标注未完成（partial 存在 / `complete:false` / 旧版 failures 非空）显示 `[!] 文本标注 (b)：未完成` | `test_run_refuses_incomplete_text`、`test_run_marks_legacy_failures_as_annotation_failed`、`test_score_refuses_incomplete_text`、`test_status_shows_text_incomplete`、`test_is_incomplete_detects_legacy_failures` |
| 4 | MEDIUM | 新建 `pipeline/notices.py::project_warnings()`：汇总标注未完成、分档警告、选段的超目标提示/其他警告/未覆盖必留话题；`/api/state` 返回 `warnings`（坏文件当无警告，不让界面打不开）。`select.summary` 增 `warnings`、`missing_must_topics`、`over_target_warning`。`index.html`：项目页常驻警告条 `#warnbar`（全部 `esc()`）；任务日志里出现 `[!]` 时不自动关弹窗，追加提示并给「知道了」按钮。文案常量 `COPY_WARNBAR_TITLE`、`COPY_JOB_DONE_WITH_WARNINGS`、`COPY_JOB_ACK`、`TEXT_INCOMPLETE_NOTICE`、`MISSING_TOPICS_NOTICE` | `test_server_target.py` +3、`test_static_pages.py` +2、`test_select.py::test_summary_includes_warnings_and_missing_topics` |
| 5 | MEDIUM | GL-25 改为绝对容差 `MUST_KEEP_EDGE_TOLERANCE`：未覆盖总时长超过容差才算缺失（去掉 90% 比例）。**偏差**：审查写的是 0.3 s，但同时要求「3 s 覆盖 2.75 s 必须报、2.8 s 以上放行」——0.25 s 缺口在 0.3 s 容差内会放行，两者矛盾；按具体用例取 **0.2 s**（另加 1e-6 浮点余量），常量可调 | `test_uncovered_must_keep_absolute_tolerance`（20/18、10/9.5、3/2.75 报；3/2.8、3/3 放行）；原「两镜拼 9.5/10」用例改成 9.9/10 |
| 6 | LOW | `run_aicut` 的 `subprocess.run` 与 `start_job` 的 `Popen` 都加 `stdin=subprocess.DEVNULL` | `test_run_aicut_never_inherits_stdin`、`test_start_job_select_runs_aicut_select` 断言 stdin |
| 7 | LOW | `select.run`：旧版话题缺 `must/usable_dur` 无法按新目标重分预算 → 追加 `BUDGET_LEGACY_WARNING`（提示重跑 score） | `test_run_warns_when_legacy_topics_cannot_be_reallocated` |
| 8 | LOW | `cmd_select`：选段成功后才把新目标写进 project.json | `test_select_failure_does_not_persist_target` |
| 9 | LOW | `describe_missing(missing, from_selection=)`：分镜表来自 `shots-selected.json` 时提示「重新选段」而不是「在分镜表里加回」（`MUST_KEEP_REMEDY_SELECTED / _MANUAL`） | `test_describe_missing_from_selection_says_reselect`、`test_build_checks_selected_storyboard_too` 加断言 |
| 10 | LOW | `LLMError` 增 `status`、`retryable`（默认由状态码推出：无状态码或 408/409/425/429/5xx 才可重试；缺 Key 不可重试）。`annotate`：不可重试错误不再重试，后面批次也不再调用、全部记失败；批次重试前按 `ANNOTATE_BACKOFF=(2.0, 5.0)` 退避，`sleep` 可注入（测试用 autouse fixture 置空） | `test_llm_error_exposes_status`、`test_exhausted_retry_error_is_retryable`、`test_missing_key_not_retryable`、`test_fatal_status_not_retried_and_stops_later_batches`、`test_retry_backoff_uses_injected_sleep` |
| 11 | LOW | `_trim`：有强制/必留镜头时非强制镜头可以全部丢掉（`if not pool or len(shots) <= 1`）；没有必留时仍至少留一镜 | `test_over_target_drops_all_non_forced_shots`、`test_trim_still_keeps_one_shot_without_must_keep` |
| 12 | LOW | 时长为 0 / 负的必留段不生成 dur=0 镜头，记 `must_keep_skipped` 并警告（`MUST_KEEP_EMPTY_WARNING`），守卫不再因它误报 | `test_zero_length_must_keep_skipped_with_warning` |
| 13 | LOW | 超目标提示改为独立字段 `over_target_warning`，`warnings` 不再含它；CLI 去掉 `warnings[1 if over_target else 0:]` 切片；markdown「## 警告」两者都列 | 更新 `test_must_keep_over_target_never_trimmed_and_reported`、`test_within_target_has_no_warning`、`test_select_over_target_prints_hint`（超目标只提示一次） |

### 审查修复涉及的文件
- 修改：`pipeline/llm.py`、`pipeline/understand_text.py`、`pipeline/classify.py`、`pipeline/select.py`、`aicut.py`、`gui/server.py`、`gui/static/index.html`、`tests/test_llm.py`、`tests/test_understand_text.py`、`tests/test_classify.py`、`tests/test_select.py`、`tests/test_aicut_must_keep.py`、`tests/test_server_target.py`、`tests/test_static_pages.py`
- 新建：`pipeline/notices.py`

### 审查修复后的补充说明
- 行数：`aicut.py` 897（仍超 800，见「新发现缺陷」）、`gui/server.py` 849（较 M2 前 +15）。
- 打包版（FROZEN）`run_aicut`/`start_job` 是同进程调用，没有子进程 stdin 可关；App 里 `sys.stdin` 不是终端，`ask_target/ask_calibration` 会直接返回默认值。打包版仍需人工确认。
- 补充人工验证项：GUI 警告条显示（待定超限、必留超时长、标注未完成）；任务带 `[!]` 时弹窗不自动关、「知道了」可关闭；无效 Key 时只调用 1 次就停（不再每批重试）。
