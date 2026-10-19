# Implementation Report: M11 文档一致（KI-40..KI-44）

## Summary
把 PRD、PLAN、产品设计、选段改进方案、PROGRESS、TECH-STACK 对齐到同一套口径，并按上线里程碑 1–9 落地后的代码现状（HEAD `3425296`）校订；`pipeline/understand_visual.py` 只改 docstring。新增只读文本守卫 `tests/test_docs_consistency.py`（22 条），先红后绿。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Medium | Medium |
| Confidence | 计划写于 `963374c` | 计划多处事实已被里程碑 6–9 改变，按代码重核后改写（见 Deviations） |
| Files Changed | 9（CREATE 1 / UPDATE 8） | 8（CREATE 1 / UPDATE 7）；README 无需改 |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | 文档一致性测试（RED） | done | 22 条（计划 20 条 + 新增 2 条，见 Deviations），首跑 22 failed，全部是断言失败，无导入错误 |
| 2 | PRD 头部、§3.3、FR-4/FR-5 | done | v1.2；§3.3 预算表（合计 20，S2+S3 = 11）；筛选 5 项同 GUI；FR-5 上限 = 28%（`MAX_PENDING_RATIO`）、验收「裁决 40 段」 |
| 3 | PRD FR-2 c 路、FR-14、§6 | done | 景别/人脸/OCR/道具降 P2 且须本地实现（用户决策）；FR-14 剪辑偏好；§6 Brief 承载方式与决策答案真实键名 |
| 4 | PRD §7、§10、§11、§12、§13 | done | 成本行用 KI-32 实际预算（每项目 300 万 tokens、`AI_CUT_LLM_BUDGET_TOKENS`）；§10 四列表；§12 四列术语表 |
| 5 | PROGRESS、TECH-STACK | done | PROGRESS 按里程碑 1–9 重核全部状态行 + 待人工放行检查清单 + 上线后指标表；TECH-STACK §2/§4/§10 |
| 6 | PLAN 校订 | done | 头注、§1.1 追溯表、1.3、M1/M2/M3/M4/M5 验收、§3、§4、§5、§7、§8 DoD、§9 |
| 7 | 产品设计文档 | done | 横幅；旧编号 → 档位名；筛选；预算；分类名为示例 |
| 8 | 选段改进方案 | done | 横幅；画面行；三档；§3.4 闸门对齐 PRD §4 |
| 9 | `understand_visual.py` docstring | done | 行为不变 |
| 10 | 全量验证 | done | 1756 passed |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | 未配置 lint/typecheck；`compileall` 通过 |
| Unit Tests | Pass | `tests/test_docs_consistency.py` 22 passed；`tests/test_understand_visual.py` 通过 |
| Build | N/A | 只改文档与 docstring |
| Integration | Pass | 全量 `uv run pytest`：1756 passed（含并行的里程碑 10 新增测试） |
| Edge Cases | Pass | 标题缺失 → `_section` 返回空串断言失败；新增 FR 自动要求 PLAN 追溯；代码改待定比例 / 预算 / 筛选按钮 → 文档用例变红 |

## Files Changed

| File | Action |
|---|---|
| `tests/test_docs_consistency.py` | CREATED |
| `docs/PRD-AI粗剪工具.md` | UPDATED |
| `docs/PLAN-AI粗剪工具.md` | UPDATED |
| `docs/PROGRESS.md` | UPDATED |
| `docs/TECH-STACK.md` | UPDATED |
| `docs/产品设计-AI粗剪工作流.md` | UPDATED |
| `docs/选段与理解-改进方案.md` | UPDATED |
| `pipeline/understand_visual.py` | UPDATED（仅 docstring） |

未改：`docs/known-issues.md`、`docs/go-live-blockers.md`、上线 PRD、README（无陈旧口径）。

## Deviations from Plan

1. **§7「成本」**：计划写「金额上限待 KI-32 落地后回填」。KI-32 已在 `9017287` 落地（`pipeline/usage.py`：每项目默认 300 万 tokens，`AI_CUT_LLM_BUDGET_TOKENS`，0 = 不限，只计 tokens 不折算金额）→ 直接写实际预算；测试从 `usage.DEFAULT_BUDGET_TOKENS` / `usage.BUDGET_ENV` 取值。用量显示在剪辑台项目信息行（`gui/views.py`），诊断包不含用量文件，所以没写「诊断包给出用量」。
2. **PLAN §1.1 追溯表「未关闭登记项」**：计划列的 KI-01/02/03/04/05/06/07/08/09/13/14/17/18/19/22/23/32/35/36/49/58/59/62/66/73/76 全部已修。按登记册现状只列仍 open 的：KI-38、KI-39、KI-80（FR-9）、KI-88（非功能）、KI-89（FR-10）；FR-13 标「已修（GL-19）」。
3. **PROGRESS**：计划只改两行；按任务要求把里程碑 1–9 涉及的状态行全部按 GL/KI 实际状态重核（⚠️/❌ → ✅，附提交号），测试数改为 1756，新增「待人工放行检查」（12 项，汇总自 m1–m9 报告）与 PRD §10 引用的「上线后指标」空表。3.3「一键加回」、4.2 回退/对比、4.3「不可用」、5.6 Windows 安装包仍为 ⚠️/❌。
4. **PRD 补入里程碑 6–9 的事实**：FR-1/FR-7 目标时长由剪辑师定（`new/select --target`、GUI 改目标时长、必留超目标自动弹窗、GL-25 出片前核对）；FR-6 保存确认即重新选段、问题可重新生成且失败不动原题；FR-13 标「已实现」并注明 Windows 日志目录随 Windows 安装包实现（`applog.log_dir` 目前只有 macOS 路径）；§7 隐私写明首次打开外发告知 / `config consent`；§6 决策答案键名按代码改为 `must_topics / exclude_topics / ending / focus / pacing`（计划写的 `must_include / must_exclude` 不存在）。
5. **FR-14 验收**：计划写「指定原话进片（KI-03 修复后）」；KI-03 已修，改为可检验的「每句指定原话恰好多 1 个强制镜头，匹配不到给提示」。
6. **新增测试 2 条、加强 4 条**：`test_visual_module_docstring_matches_scope`（KI-41 docstring）、`test_prd_states_target_duration_is_editor_choice`（`--target` 写入 FR-1/FR-7）；`test_progress_no_pending_prd_backfill` 增加断言 FR-13 不再写「未开始」；`test_nfr_covers_cost_and_outage` 改为钉住预算常量；`test_visual_route_scope_matches_implementation` 额外要求 P2 行写明「本地」；`test_tech_stack_*` 额外要求删掉「MediaKit 视频理解」行。
7. **TECH-STACK** 另改 §2「网络」行（原写「断网降级为本地规则 + 手改」，与 GL-09 后的明确失败冲突）与 §10 mediakit-video 行（视频理解 / OCR 不用）。
8. 计划假定基线 987 用例；实际基线已因里程碑 6–10 增长，全量 1756 passed。

## Issues Encountered
- 并行的里程碑 10 正在改 `pyproject.toml`、`uv.lock`、`.gitignore`、`tests/test_packaging.py`、`tests/test_proc.py` 并新增若干测试文件；本次未触碰，全量测试时它们也全绿。
- 仍残留的历史说法（有意保留）：产品设计 §2.4「她只需要处理那 41 段」（当时实测，已加注）；改进方案 §四/§五 的「必留」实施清单（文首横幅已声明以 PRD §12 为准）。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_docs_consistency.py` | 22 | KI-40 指标/预算/上限、KI-41 c 路范围与 docstring、KI-42 追溯/FR-14/目标时长/陈旧项、KI-43 术语/闸门/分类名/筛选、KI-44 成本/断网/DoD |

## 留给编排方
- 在 `docs/known-issues.md` 把 KI-40..KI-44 填提交号；KI-42 的登记描述「PLAN 漏 FR-10..13」不完全准确（PLAN 原有 4.2/4.3/5.1/5.2 任务行，缺的是验收与追溯），关闭时可备注。
- 上线 PRD 里程碑 11 状态与 Open Questions 中 KI-40/KI-41 两条。
- 人工：在 Markdown 预览里确认 PRD §3.3 / §10 / §12 表格渲染、PLAN 指向上线 PRD 与 PRD §12 锚点的链接可点开。
