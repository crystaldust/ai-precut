# Implementation Report: 里程碑 8「失败可见」（KI-19..KI-27 / KI-48 / KI-49 / KI-56 / KI-66 + KI-77）

## Summary
ffmpeg / ffprobe / LLM / JSON 的失败不再伪装成成功：
- 分析类 ffmpeg / ffprobe 一律检查退出码并带回 stderr 末尾（`media_io.run_analysis / probe_duration / probe_material / material_entry`），废片检测、镜头切分、画面质量、素材台账失败时 `[x] <步骤>失败：<原因>`（KI-19 / KI-66）。
- 新增 `schema.read_json` + `schema.CorruptJSON`（缺失 → 默认值，损坏 → 带文件名的人话，不带文件内容）；`aicut.main()` 统一把 `CorruptJSON` / `OverridesCorrupt` 变成 `die()`（KI-21 / KI-56）；`schema.read_shots` 在切片前校验分镜表（KI-48）。
- 剪辑台：project.json / 三档判定 / 决策问题损坏 → 409；其它文件损坏照常打开、常驻警告栏逐个点名；切项目失败进警告栏 + toast（KI-21）。
- LLM 兜底：CLI `[!]` 打出原因，警告栏同步显示；未作答的兜底决策问题下次重新生成（KI-22）。
- 选段把匹配不上的原话 / 必留话题 / 答案写进 `warnings`（KI-23）。
- 转写时间码、包含句、`59.999` 进位（KI-24）；默认值深拷贝（KI-26）；废片检测收尾闭合、负起点、重叠去重、`scenes` 写入报告（KI-27）；冻帧 + 静音基本重叠也给 0.97「无语音 + 画面静止」（KI-77）；确认页答案类型容错（KI-49）。
- KI-25：代码早已修复，补走真实 `default_transport` 的回归测试。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 高（全部自动化测试覆盖；手动清单待做） |
| Files Changed | 30 | 30（源 15 修改 + 1 新建；测试 10 修改 + 4 新建） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | KI-26 + `read_json` / `CorruptJSON` | done | 另加 `read_json_lenient`（显示用，见偏差 6） |
| 2 | KI-25 回归测试 | done | 直接 GREEN（代码已修），另加「重试用尽」用例 |
| 3 | `run_analysis` / `probe_duration` / `probe_material` | done | 另加 `duration_or_zero`、`material_entry`（偏差 2） |
| 4 | understand_visual / render_preview / to_jianying / aicut | done | render_preview、venv 已由 M7 修掉（偏差 1） |
| 5 | 废片检测 KI-19 / KI-27 + KI-77 | done | KI-77 判定见偏差 7 |
| 6 | KI-24 转写时间码 | done | |
| 7 | KI-23 选段警告 | done | |
| 8 | KI-22 兜底不固化、原因可见 | done | |
| 9 | aicut 接线 KI-21/48/56/66 + classify | done | 分镜表校验放进 `schema.read_shots`（偏差 3） |
| 10 | 剪辑台读路径 KI-21 / KI-49 | done | 先纯搬家 `gui/payloads.py` 全量绿，再改行为 |
| 11 | 收尾验证 | done | 手动清单待做 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | pass | 仓库未配 lint / typecheck；`compileall -q aicut.py pipeline gui` 无输出 |
| Unit Tests | pass | `uv run pytest`：1086 → 1226 passed，0 failed / 0 skipped |
| Build | N/A | 未打包（不在本里程碑） |
| Integration | pass | GUI 路由用 `gui_server` 真起服务测；`junk_detect` 用真 ffmpeg + `proc.dev_module_cmd` 冒烟（正常素材 / 不存在 / 垃圾文件三种） |
| Edge Cases | pass | 空 stdout、零帧、超长 stderr、顶层类型错、非 UTF-8、目录当文件、bool 时间码、负静音起点 |

行数：`aicut.py` 924（= 上限 924）、`gui/server.py` 724（< 800）、`gui/payloads.py` 86。

## Files Changed

| File | Action |
|---|---|
| `pipeline/schema.py` | UPDATED（`CorruptJSON` / `read_json` / `read_json_lenient` / `read_shots`；深拷贝默认值） |
| `pipeline/media_io.py` | UPDATED（`run_analysis` / `probe_duration` / `probe_material` / `material_entry` / `duration_or_zero` / `_tail`） |
| `pipeline/junk_detect.py` | UPDATED |
| `pipeline/understand_visual.py` | UPDATED |
| `pipeline/format_transcript.py` | UPDATED |
| `pipeline/select.py` | UPDATED |
| `pipeline/questions.py` | UPDATED（`reusable` / `normalize_answers`） |
| `pipeline/notices.py` | UPDATED（兜底提示、`corrupt_files`） |
| `pipeline/classify.py` | UPDATED |
| `pipeline/to_jianying.py` | UPDATED（删死代码 `run()`） |
| `aicut.py` | UPDATED |
| `gui/payloads.py` | CREATED |
| `gui/server.py` | UPDATED |
| `gui/static/common.js` / `confirm.html` / `index.html` | UPDATED |
| `tests/test_junk_detect.py` / `test_format_transcript.py` / `test_m8_cli_failures.py` / `test_server_corrupt.py` | CREATED |
| `tests/test_schema.py` / `test_llm.py` / `test_media_io.py` / `test_select.py` / `test_questions.py` / `test_classify.py` / `test_frontend_js.py` / `test_static_pages.py` | UPDATED（追加） |
| `tests/test_server_target.py` | UPDATED：`test_state_survives_corrupt_scored_file` 按 KI-21 有意改断言（仍 200，警告栏恰 1 条且含「三档判定」） |
| `tests/test_aicut_guards.py` | UPDATED：两处 `monkeypatch.setattr(aicut, "run", _fail)` 改为打桩 `media_io.run_ffmpeg`（`aicut.run` 已删除，见偏差 4） |

## Deviations from Plan

1. **KI-20 大部分已由 M7 修掉**：`render_preview` 已走 `media_io.run_ffmpeg` + `atomic_output(mark=False)` 并 `sys.exit("预览片渲染失败：…")`（已有 `tests/test_render_preview.py` 覆盖）；venv 创建已搬到 `pipeline/jy_env.py` 并带 stderr。本里程碑只删了 `to_jianying.run()` 死代码，并加静态守卫 `test_no_check_true_left_in_pipeline`。
2. **新增 `media_io.material_entry` 与 `duration_or_zero`**：为把 aicut 压到 924 行，ingest 的「文件不在 / 认不出」整块搬到 `media_io.material_entry`；aicut 自带的 `probe_duration` / `run` 删除，宽松读时长改用 `media_io.duration_or_zero`（行为不变，切片仍按请求时长兜底）。
3. **分镜表校验放进 `schema.read_shots`**（计划是 aicut 内 `clean_shots` + `SHOTS_INVALID`）：结构不合法也抛 `CorruptJSON`（文案「分镜表 shots.json 不能用：…」），由 `main()` 统一 `die`。`clean_shots` 规整入出点 → 手写整数入出点的镜头会重切一次（计划 Risks 已登记）。
4. **`cmd_new` 也改用 `load_preset`**：`PRESET_MISSING` 带上可用预设清单，保留原提示信息并省行。
5. **`cmd_build` 保留自己的 `OverridesCorrupt` 处理**：已有测试直接调 `cmd_build`，`main()` 的统一处理覆盖其它命令。
6. **新增 `schema.read_json_lenient`**：server 的 `jload`、payloads、notices `_read` 共用（只用于显示，损坏由 `notices.corrupt_files` 点名）；顺带修了 `jload` 遇到顶层非对象时 `.get` 500 的问题。
7. **KI-77 判定口径**：冻帧 / 静音行被另一种信号覆盖 ≥ 80%（`STRONG_COVERAGE`）才给 0.97「删」；只擦边（如 1 秒）仍是 0.7 / 0.55；黑场行保持原规则。重叠的两条「删」由 `union_seconds` 只计一次。
8. **`payloads.browse` 读 project.json**：损坏 → 409（按用户决策）；原来的 `except Exception: pass` 收窄为 `(OSError, ValueError, SchemaTooNew)`。
9. **`/api/confirm/answers` 没有 questions.json 时返回 404**（计划未写）：规整后答案会被全部丢弃，不能静默存空。
10. **确认页保存失败显示服务端原因**（`e.error`，`COPY_SAVE_FAILED` 兜底）：新的 409 / 404 不能只显示「保存失败」。
11. **`sample_frames` 读完后 ffmpeg 30 秒不退出**也转成 `MediaError`（`FRAMES_STUCK`），不再冒出裸 `TimeoutExpired`。

## Issues Encountered
- `aicut.py` 行数预算（≤ 924）：通过上面 2 / 3 / 4 把逻辑放进 pipeline，最终刚好 924。
- `run_cli` 的 traceback 打在 stderr：M8 的 CLI 测试用 `_output(capsys)` 同时检查 stdout + stderr，避免「没有 traceback」断言假绿。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_junk_detect.py` | 14 | KI-19 / KI-27 / KI-77 |
| `tests/test_format_transcript.py` | 12 | KI-24 |
| `tests/test_m8_cli_failures.py` | 26 | KI-19 / KI-20 / KI-21 / KI-22 / KI-48 / KI-56 / KI-66 接线 |
| `tests/test_server_corrupt.py` | 15 | KI-21 / KI-22 / KI-49 GUI |
| `tests/test_schema.py` | +10 | KI-21 / KI-26 |
| `tests/test_llm.py` | +5 | KI-25 回归 |
| `tests/test_media_io.py` | +22 | 新原语 |
| `tests/test_select.py` | +8 | KI-23 |
| `tests/test_questions.py` | +15 | KI-22 / KI-49 |
| `tests/test_classify.py` | +4 | KI-21 |
| `tests/test_frontend_js.py` / `test_static_pages.py` | +6 / +2 | KI-49 / KI-21 前端 |

TDD 说明：每个 Task 都先跑出 RED 再实现。例外：Task 2（KI-25，代码已修，按计划预期直接 GREEN）；`test_server_corrupt.py` 里两条兜底警告栏用例写在 `notices` 实现之后（同一改动的 CLI 用例已先 RED）。

## 新发现缺陷（未修，范围外）
- `aicut.py:492` `ensure_clips` 的 `work/clips/manifest.json` 只是缓存，损坏时现在会 `die`（以前是 traceback），更合理的是当空缓存全部重切。
- `gui/server.py:407` `/api/presets` 用宽松读取，损坏的预设文件按文件名列出且不提示。
- `pipeline/understand_visual.py:207` `run_quality` 读 `segments.json` 缺 `segments` 键会 `KeyError` traceback（计划已注明不在本 Task）。
- `pipeline/classify.py:240, 247` 声音特征 / 画面质量文件是合法 JSON 但缺 `segments` 键时 `KeyError` traceback。
- `pipeline/understand_visual.py:79` `sample_frames` 的 `timeout` 参数仍未生效（KI-61，里程碑 9）。
- `pipeline/junk_detect.py:59` `merge()` 原地排序入参（计划已注明，范围外）。
- `gui/static/confirm.html:121` toast 1.6 秒就消失，较长的错误原因（如 409 文案）看不完。
- `gui/static/index.html:244` 除 `selectProject` 外，其它调用 `refresh()` 的地方（任务结束后刷新等）没有接住 `/api/state` 失败。
- KI-24 默认决策 4 的后果：转写跳过 N 句的提示只出现在子进程输出 / CLI 直跑里，GUI 任务成功时看不到。

## 待手动验证
计划 Manual Validation 7 条全部未做（需要真实项目 / 剪辑台界面 / 断网环境）：project.json 改坏后点项目；shots.json 改坏后警告栏 + `build --no-draft`；overrides.json 改坏后 `select`；0 字节 / 改名的 `.mp4` 跑 ingest；截断 proxy 后跑 junk / scenes / quality；断网跑 summary；手改 `brief_answers.json` 多选为字符串后打开确认页。

## Next Steps
- 手动清单；登记册状态与 PRD 里程碑状态由用户 / 提交方更新（本次未改登记册，未提交，计划未归档）。

## 补充修复（协调方追加，同样先 RED 后 GREEN，未提交）

| # | 问题 | 修法 | 测试 |
|---|---|---|---|
| 1 | `work/clips/manifest.json` 损坏会让出片退出 | 新增 `media_io.read_manifest`：损坏时打印 `[!] 切片缓存记录损坏，按空缓存处理，全部镜头重新切：…`，然后当空缓存全部重切；`aicut.ensure_clips` 改调它，aicut 行数不变 | `test_m8_followup.py::test_corrupt_clip_manifest_recut_with_warning` |
| 2 | `/api/presets` 损坏的预设按文件名列出、不提示 | 损坏的跳过，响应带 `warnings`（`PRESET_CORRUPT_MSG`）；新建项目弹窗在预设下拉框下面显示这些警告 | `test_server_corrupt.py::test_presets_*`、`test_static_pages.py::test_new_project_modal_shows_preset_warnings` |
| 3 | JSON 合法但缺 `segments` 或类型不对时 `KeyError` traceback | 新增 `schema.require_key(data, key, path, typ=list)` 和 `schema.read_field(path, key, typ)`，抛 `CorruptJSON`（带文件名，说明缺哪个键 / 应为什么类型）。已覆盖：`understand_visual.run_quality`、`understand_audio.run`、`understand_text.run`、`classify.run`（text / audio 为列表，visual 为对象）、`questions.run`、`summarize.run`、`select.run`、`gui/payloads.browse`；CLI 由 `main()` 统一给人话，GUI 浏览页返回 409 | `test_m8_followup.py`：参数化 9 个读取点 + 浏览页 + CLI `score` 无 traceback |
| 4 | `junk_detect.merge()` 原地排序传入的列表 | 改为遍历 `sorted(...)` 的副本 | `test_merge_does_not_mutate_input` |
| 5 | 确认页 toast 1.6 秒就消失 | 新增 `toastError`：至少 6 秒，按字数加长（每字 120ms，常量 `TOAST_ERROR_MIN_MS` / `TOAST_MS_PER_CHAR`）；保存失败改用它 | `test_confirm_error_toast_stays_longer` |
| 6 | 只有 `selectProject` 接住 `/api/state` 失败 | `index.html` 新增 `refreshOrWarn()`（失败 → 警告栏 + 6 秒 toast）；`selectProject` 和 `jobs.js` 两处（任务失败 / 完成后刷新，原来是 `.catch(()=>{})` 和空 catch 吞掉）都改用它；静态测试保证 `refresh()` 只在 `refreshOrWarn` 里调用一次 | `test_every_refresh_caller_reports_state_failure` |
| 7 | KI-24「跳过 N 句缺时间码」在 GUI 里看不到 | `format_transcript` 把警告写进 `segments.json` 的 `warnings`（没有跳句时为 `[]`），CLI 照常打 `[!]`；`notices.project_warnings` 读取它，剪辑台警告栏常驻显示 | `test_dropped_subs_persisted_and_shown_in_project_warnings` / `test_clean_transcript_has_no_warning` |

- KI-61（`sample_frames` 的 timeout）按要求留给 M9。
- `pipeline/build_documentary.py:94-105` 是独立旧脚本（`spec["shots"]`），aicut 不调用它（出片走 `schema.read_shots`），所以没有改。
- 测试：1226 → **1253 passed**，0 failed / 0 skipped，`uv run pytest` 退出码 0。`compileall` 通过；`node --check` 检查了 `jobs.js` 以及 index / confirm 的内联脚本，均通过。行数：`aicut.py` 924、`gui/server.py` 729。
- 新增测试文件 `tests/test_m8_followup.py`（22 条）；`test_server_corrupt.py` +2；`test_static_pages.py` +3。M8 新加的 `test_index_shows_state_load_error` 改为断言 `selectProject` 调用 `refreshOrWarn()`。
- 待手动验证：新建项目弹窗里的坏预设提示；任务完成后 `/api/state` 失败时警告栏和 toast 的显示；确认页错误 toast 的停留时长。

## 审查修复（独立审查：1 HIGH / 4 MEDIUM / 3 LOW，全部已修，TDD，未提交）

| 级别 | 问题 | 修法 | 测试 |
|---|---|---|---|
| HIGH | 切到 project.json 损坏的项目后，界面还留着上一个项目的数据，`state.project` 却已切过去，「保存分镜表」会把 A 的镜头写进 B | **前端**：`refresh(name)` 成功后才赋值 `state.project` / `state.data`；失败走 `showProjectError`：清掉 project / data / shots、收起操作栏和标签页、标题改成项目名、取消待保存的计时器，`saveShots` 在没有项目时绝不发请求。切项目前先把未落盘的分镜表改动存回原项目（`flushPendingSave`，顺带修了 700ms 自动保存可能写进新项目的竞态）。**服务端**：`existing_project` 默认严格读 project.json，损坏抛 `ProjectCorrupt`（不是 ValueError），由 `_safely` 统一返回 409。覆盖 /api/shots、/api/job、/api/browse/level、/api/browse/must、/api/confirm/answers、/api/calibrate（GET 和 POST）、/api/open（project / export）。只有导出诊断包用宽松版（项目坏了正是要导出诊断包的时候） | `test_m8_review.py::test_write_endpoints_refuse_corrupt_project`（9 个接口：409，磁盘上的文件不变，不调外部命令）、诊断包仍可导出、健康项目照常保存；`test_frontend_js.py` 两条 node 状态测试（切到坏项目后状态被清空；A 的待保存改动只发往 A，失败后不再发请求） |
| MEDIUM 2 | `select.run` 读答案 / 题目、`select.missing_must_keep` 读三档判定、`format_transcript` 读 transcript_raw 仍是裸 `json.loads` | 都改为 `schema.read_json` 加类型检查（answers / rules 必须是对象），抛带文件名的 `CorruptJSON`；`format_transcript` 用 `sys.exit` 给出人话。警告栏的补救提示按文件区分：答案文件写「到「确认与提问」页重新作答」，选段写「点「改目标时长」重新选段会重建」，时间线写「重新「② 生成成片」会重建这一版」，其余仍写「重新点「① 处理素材」会重建」 | `test_select_corrupt_answers/questions_*`、`test_missing_must_keep_corrupt_scored_*`、`test_format_transcript_corrupt_raw_*`、`test_corrupt_answers_notice_says_reanswer` |
| MEDIUM 3 | 容器里没写时长的合法素材（管道写出 / 录制中断的 MKV）被当坏文件拒绝 | `probe_material` 先退回各路流里最长的时长；流也没有 → 时长记 0，加警告「容器里没有时长信息…」，不中断。只有 ffprobe 完全读不了（非零退出 / 没输出 / 没有容器信息）才拒绝。警告同时打印 `[!]`、写进 materials.json，并进入警告栏 | `test_probe_material_falls_back_*`、`*_warns_not_fails`、`*_cannot_read_still_fails`、`test_ingest_without_duration_records_warning`；M8 原测试 `test_probe_material_unrecognized` 去掉了这 3 种如今属于合法的输入 |
| MEDIUM 4 | 浏览 / 确认页看不到损坏文件的提示 | `payloads.browse` / `payloads.confirm` 返回 `warnings`（= `notices.project_warnings`）；两页顶部加警告条，内容经 `esc()` 转义 | `test_browse_and_confirm_payloads_include_warnings`、`test_page_shows_warning_strip_escaped` |
| MEDIUM 5 | 浏览页改档位 / 必留不看返回结果 | 新增 `postOrRollback`：检查 `r.ok`，失败时回滚乐观更新、重绘，并用 `toastError` 显示服务端原因（至少 6 秒，按字数加长；浏览页原来没有 toast，这次补上） | `test_browse_writes_check_ok_and_roll_back` |
| LOW 6 | 题目重新生成后，已存规则还在生效 | `select._current_rules`：答案仍对得上当前题目才用已存规则，否则按当前题目重算，并报 ANSWER_UNMATCHED；排除话题对不上任何话题时也给警告 | `test_stale_stored_rules_*`、`test_fresh_stored_rules_still_used`、`test_unmatched_exclude_topic_warned`；原有的 `test_stored_rules_win_over_answers` 不变 |
| LOW 7 | 处理素材时画面质量失败会让整个任务停下 | `cmd_quality` 失败时 `[!]` 警告后继续（`QUALITY_SKIPPED`）；`run_quality` 失败时删掉旧的 visual_quality.json，分档会给出 VISUAL_MISSING_WARNING。素材台账 / 废片检测 / 镜头切分仍然直接失败 | `test_quality_failure_warns_and_continues`；M8 原测试 `test_quality_dies_with_reason` 改为 `test_quality_failure_is_visible_warning`（行为按审查有意改变） |
| LOW 8 | 摘要 / 决策问题兜底的真实原因只截取 200 字写进文件 | `except Exception` 里加 `applog.get(...).exception(...)`：完整堆栈进诊断日志，由 applog 的 RedactFilter 脱敏 | `test_fallback_logs_real_error[summarize/questions]` |

- 测试：1253 → **1288 passed**，0 failed / 0 skipped，`uv run pytest` 退出码 0；`compileall` 通过；`node --check` 检查了 jobs.js 以及 index / browse / confirm 的内联脚本，均通过。
- 行数：`aicut.py` 924（画面质量那处改为 `return warn(...)`，净增 0 行）、`gui/server.py` 751、`gui/payloads.py` 88。
- 新增测试文件 `tests/test_m8_review.py`（33 条）；`test_frontend_js.py` +2；`test_static_pages.py` +3，并按新结构改了两条 M8 自己写的静态断言。
- 待手动验证：剪辑台在 A、B 两个项目间切换（B 的 project.json 已损坏），确认标题、操作栏、警告栏的表现，且 A 的分镜表不受影响；浏览页在 overrides.json 损坏时改档位，看回滚和提示；浏览 / 确认页顶部的警告条；用一个没有容器时长的 MKV 跑 ingest。
