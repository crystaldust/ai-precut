# Implementation Report: 画面理解 · 第 4 阶段 —— 整合与判定

## Summary
开启画面理解时，分析在「云端画面理解」之后多跑本机步骤 `align`（② 第 14 项「整合画面与对白」）：按时间重叠把画面事件挂到每句对白（`by_segment`），并为没有对白、长度 ≥3 秒的空档生成画面片段（`V001`…，≤35 秒，边界吸附 1 秒内的镜头切点），写 `work/vision_aligned.json`。逐句标注照旧做一轮（与关闭时完全相同），另外两轮单独问画面：对白句的「画面与对白是否一致 / 画面上能否看到关键信息」，画面片段的标题。档位判定：待定段画面可见关键信息且无画面问题 → 可用；可用段有画面问题（背对镜头、人物出画、遮挡、晃动）或画面与对白不符 → 待定，说到关键信息的不降，被画面降下来的不会再被「待定过多」或「过暗」打成废片。画面片段单独判档，存在 `visual_segments`，不进 ③、自动选段和汇总。关闭画面理解时，标注、判定产物和发给模型的提示词逐字节不变（金标准测试）。外发告知加第四条「画面文字描述 → DeepSeek」，版本升到 3。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | 7/10 | 计划内一次实现；审查后改了两处结构（画面判断单独调用、score 按开关取用） |
| Files Changed | 约 16 | 23（新模块 1、新测试 2、改代码 10、改测试 7、文档 3） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | 关闭时不变的金标准测试 | Complete | 改代码前录下 text / score 产物与提示词的 sha256，夹具覆盖废片 / 待定 / 可用 / 过暗 |
| 2 | 事件挂到对白片段 | Complete | 另加：`objects` 不是列表时忽略（安全 L3） |
| 3 | 画面片段与落盘 | Complete | 另加：吸附后超过 35 秒就不吸附（审查 M2）；对齐文件记 `cuts_hash`，镜头切点变了算过期（审查 M4） |
| 4 | 流程接入 `align` | Complete | `vision_align.for_text()` 放进模块，`aicut.py` 保持 800 行以内（结构守卫） |
| 5 | ② 进度「整合画面与对白」 | Complete | 开启 14 项、关闭 11 项 |
| 6 | 逐句标注带画面 | Complete — 偏离 | 见 Deviations：画面三项单独一次调用 |
| 7 | 画面片段标注 | Complete | 不可重试的错误后不再调用（审查 M3） |
| 8 | `cmd_text` 传入画面数据 | Complete | 开着但整合不是最新 → 停下说原因 |
| 9 | `classify` 画面规则 | Complete | 另加：`run(vision=)` 按现在的画面结果取用标注（审查 M1）；画面降档 + 过暗仍是待定（审查 H1） |
| 10 | 文档与 PRD | Complete | GUI.md、PRD 隐私行、PROGRESS #33；外发告知 v3 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | N/A | 项目未配置 lint / 类型检查 |
| Unit Tests | Pass | 新增 / 修改约 70 个测试 |
| Build | Pass | spec hiddenimports 加 `pipeline.vision_align`（`test_structure`） |
| Integration | Pass | 全量 4116 passed, 12 skipped；覆盖率 95%（vision_align 98%、classify 98%、understand_text 95%） |
| Edge Cases | Pass | 空时间轴、全程有对白、事件重叠 / 有空档、长空档切分、吸附越界、开启后关闭的残留文件、时间轴 / 整合过期、模型返回枚举外的值、注入文本、不可重试错误 |
| Manual（真账号） | Pending | 需要你确认后再花 DeepSeek tokens，见 Next Steps |

## Files Changed
- 新建：`pipeline/vision_align.py`；`tests/test_vision_align.py`、`tests/test_vision_off_golden.py`
- 改代码：`aicut.py`（`cmd_align`、`cmd_text` / `cmd_score` 接入）、`pipeline/understand_text.py`、`pipeline/classify.py`、`pipeline/readiness.py`、`pipeline/cli_args.py`、`pipeline/consent.py`、`gui/analysis.py`、`gui/static/settings.js`（告知第四条）、`gui/static/step-analyze.js`（注释）、`packaging/ai-cut.spec`
- 改测试：`test_understand_text`、`test_classify`、`test_vision_wiring`、`test_analysis_progress`、`test_consent`、`test_aicut_cli`、`test_stamps`
- 文档：`docs/GUI.md`、`docs/PRD-AI粗剪工具.md`（隐私行）、`docs/PROGRESS.md`（#33）

## Deviations from Plan
- **画面判断单独一次调用**（安全审查 M1）：计划是在原标注提示词里加画面规则、一次调用拿全部字段。画面文字（含画面上读到的字，可被拍摄内容影响）如果和 `info_type` / `key_info` 同一次调用，夹带的指令可能改动整批 30 句的对白标注，档位影响不止一档。改为：对白标注那轮与关闭时完全相同、看不到画面；画面三项另问一轮（`ANNOTATE_VISION_USER`），只能影响画面三项 → 档位最多动一档。代价：开启时多一轮 DeepSeek 调用（对白文本会再发一次）。附带好处：开 / 关画面理解时对白标注（key_info）不会漂移。
- **外发告知升到 v3**（安全审查 M2）：计划没提。开启画面理解时 DeepSeek 会收到画面文字描述，是新的外发内容，告知加第四条，已确认过的用户下次分析前重新确认一次。
- **`classify.run(vision=)`**（审查 M1 与复审 MEDIUM）：单独跑 `aicut score` 时按现在的画面理解取用标注（`vision_align.score_key`）：关着就去掉上次开启时留下的画面字段；开着但标注不是按当前画面时间轴做的（关闭时做的、时间轴重做过、整合不是最新）→ 停下说原因。
- PRD 写「DeepSeek 给出画面可用性」：按计划改为程序按云端 `issues` 判定（第 1 阶段结论：模型自评不可靠）。

## Issues Encountered
- `aicut.py` 超过 800 行结构守卫：把画面相关的判断与汇总文字挪进 `vision_align.for_text()`、`classify.picture_note()`，现在正好 800 行。下次再往 `aicut.py` 加东西前需要先拆。

## Review
- `ecc:python-reviewer`：H1（画面降为待定后又被「过暗」打成废片）已修；M1（score 不看开关）、M2（吸附超长）、M3（致命错误后还调画面轮）、M4（镜头切点不进新鲜度）已修。复审：无 CRITICAL / HIGH，新 MEDIUM（画面时间轴重做后单独跑 score 用旧画面标注）已修，LOW「对白标注失败的句子仍问画面」已修。未改：L4 必留话题的待定段可因画面关键信息升为可用（按设计）；L6 由几段 <3 秒短事件组成的空档不出画面片段（粗剪可接受）；只有画面轮失败的句子也记为标注失败，续跑时两轮都重问（多花一点，结果正确）；`understand_text.run` 仍略超 50 行。
- `ecc:security-reviewer`：无 CRITICAL / HIGH。M1（注入影响整批标注）、M2（告知缺第四条）已修；L3 类型保护已加。确认：画面文字只在 JSON 值里、输出 id 白名单、诊断包不收新文件（`SAFE_WORK_FILES` 是白名单）。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_vision_off_golden.py` | 1 | 关闭时 text / score / 提示词逐字节不变 |
| `tests/test_vision_align.py` | 25 | 挂接、问题覆盖阈值、画面片段、切分、吸附、落盘、新鲜度、`for_text` |
| `tests/test_understand_text.py` | +14 | 画面轮提示词、注入、字段规范化、缓存、续跑、批大小、致命错误 |
| `tests/test_classify.py` | +18 | 升 / 降档、key_info 不降、待定上限、过暗、画面片段、按开关取用 |
| `tests/test_vision_wiring.py` 等 | +10 | `aicut align` / `text` / `score` 接入、② 14 项、告知 v3 |

## Next Steps
- [ ] 真账号验收（需你确认，只花 DeepSeek tokens，不重新上传画面）：在 `projects/vision-acceptance` 跑 `align` → `text` → `score`；抽查画面片段与原片；开 / 关两次 `segments_scored.json` 档位变化逐条看理由；记录开启时 DeepSeek 的增量用量
- [ ] 验收通过后 PRD 第 4 阶段标 complete
- [ ] 第 5 阶段：③ 显示画面描述与画面片段、放入剪辑列表（空文本片段的手动改档锚点要另设）
