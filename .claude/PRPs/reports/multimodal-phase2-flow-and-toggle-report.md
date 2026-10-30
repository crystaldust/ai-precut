# Implementation Report: 画面理解 · 第 2 阶段 —— 流程与开关

## Summary
「创建项目」不再自动分析，停在 ②；② 在非运行状态显示「画面理解（AI 多模态）」开关、档位（省钱 / 均衡 / 精细）与隐私提示，运行中只显示锁定条（后端 409 兜底）。设置按项目存进 `project.json` 的 `vision`，进入分析输入指纹，分析完成后改了 ② 标「需要更新」（专用横幅）；改版前分析过的项目不受影响。外发告知升到第 2 版，加第三条数据流，CLI 与剪辑台文案同步。本阶段只保存设置，不调用云端。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Medium | Medium |
| Confidence | 8/10 | 一次实现到位；几处计划外的小修（见偏差） |
| Files Changed | 14 | 26（代码 13、测试 8、文档 5；含 packaging spec、TECH-STACK 等计划外同步） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | `pipeline/vision.py` 设置模型 | Complete | |
| 2 | schema 默认 + 分析指纹 + 向导 | Complete | 偏差：补默认值放在 `_analyze_step`，不放 `collect` |
| 3 | 路由 `POST /api/project/vision`、`/api/analysis` 带 vision | Complete | 额外拿项目独占锁（挡终端里的 `aicut run`），同 `_write_settings` |
| 4 | 外发告知 v2 | Complete | 偏差：界面术语用「原始视频」而不是「原片」（`test_terms` 禁用词） |
| 5 | ① 只创建 | Complete | 偏差：不另调 `go('analyze')`，`selectProject` 按 `wizard.next` 已落在 ② |
| 6 | ② 画面理解卡片 | Complete | 偏差：卡片在「开始 / 继续 / 重试」上面（先选再点，对齐设计 DNA6f），完成 / 运行中在状态卡下面 |
| 7 | 样式 | Complete | 隔离环境（临时配置、假项目、假 Key）里用无头 Chrome 截图核对 |
| 8 | 文档 | Complete | 另同步 TECH-STACK、`understand_visual.py` 模块说明、放行检查 #14 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | N/A | 项目未配置 lint / 类型检查；JS 语法由 node vm 测试覆盖 |
| Unit Tests | Pass | 新增 31 个测试函数（参数化展开后 53 个用例）+ consent 2 个 |
| Build | Pass | `packaging/ai-cut.spec` 补 `pipeline.vision`（`test_structure` 守住） |
| Integration | Pass | 全量 `uv run pytest`：3925 passed, 12 skipped；覆盖率 94.92% |
| Edge Cases | Pass | 旧戳、非法入参、运行中改设置、切项目旧响应、重复点击、转义均有测试；真实页面截图核对未开 / 已开两态 |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `pipeline/vision.py` | CREATED | +34 |
| `pipeline/schema.py` | UPDATED | +1 |
| `pipeline/fingerprints.py` | UPDATED | +6 / -3 |
| `pipeline/consent.py` | UPDATED | +5 / -3 |
| `pipeline/understand_visual.py` | UPDATED | +1 / -1（说明文字） |
| `gui/wizard.py` | UPDATED | +6 / -2 |
| `gui/project_routes.py` | UPDATED | +28 / -1 |
| `gui/static/step-analyze.js` | UPDATED | +66 / -1 |
| `gui/static/project-form.js` | UPDATED | +9 / -8 |
| `gui/static/settings.js` | UPDATED | +2 / -1 |
| `gui/static/app.css` | UPDATED | +17 |
| `packaging/ai-cut.spec` | UPDATED | +1 / -1 |
| `tests/test_vision_setting.py` | CREATED | +191 |
| `tests/test_frontend_analysis_vision.py` | CREATED | +113 |
| `tests/fe_fixtures.py`、`test_consent.py`、`test_fingerprints.py`、`test_frontend_project_form.py`、`test_frontend_review.py`、`test_static_pages.py` | UPDATED | 改名 / 新行为 / 新版本号 |
| `docs/GUI.md`、`docs/界面流程-v2.md`、`docs/PRD-AI粗剪工具.md`、`docs/PROGRESS.md`、`docs/TECH-STACK.md` | UPDATED | 流程、API、隐私红线、决策记录、放行检查 #33 |

## Deviations from Plan
- **旧戳补默认值的位置**：计划写在 `wizard.collect`；实际放在 `_analyze_step`，戳和当前值两边都补。原因：`collect` 返回读盘原始事实（已有测试断言原样）；两边都补，只带部分键的夹具 / 旧数据也不会误判。
- **术语**：告知与卡片里用「原始视频」，不用「原片」——`tests/test_terms.py` 把「原片」列为界面禁用旧叫法；文档里引用界面文字处同步。
- **① 创建后不调 `go('analyze')`**：`selectProject` 已按向导的 `next`（新项目为 ②）落页。
- **卡片顺序**：未开始 / 中断 / 失败时卡片放在操作按钮上方（先选再点），与设计图一致；计划原写「状态卡之后」。
- **409 文案**改为「正在处理这个项目…」：审查指出选段等非分析任务也会被拦。

## Issues Encountered
- Chrome DevTools MCP 被另一个浏览器实例占用 → 改用无头 Chrome + 隔离配置目录截图；没有替用户确认真实配置里的外发告知（真实环境下次会看到 v2 告知，这是预期）。
- 全量测试暴露 `test_structure`（spec hiddenimports）和 `test_terms`（禁用词）两处，已修。

## Review
`ecc:code-reviewer`：无 CRITICAL / HIGH。LOW 已修 2 条（409 文案、GUI.md 锁定条引用）；未修 2 条：`visionUi.saving` 是全局的（切项目期间，另一项目的点击会被忽略到前一个响应回来）；更早发出的 `/api/analysis` 响应可能短暂把刚保存的设置画回旧值（下次轮询自愈）。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_vision_setting.py` | 19 个测试函数（参数化展开更多） | vision 模块、schema 默认 / 迁移、指纹、向导旧戳回归与横幅、路由 200/400/404/409 |
| `tests/test_frontend_analysis_vision.py` | 12 个测试函数 | 各状态卡片、顺序、档位置灰、锁定条、保存、409、竞态、防重复点击、block 页 |
| `tests/test_consent.py` | +2 | v1 记录需重新确认；CLI 与剪辑台三条文案一致 |

## Next Steps
- [ ] 第 3 阶段：代理素材与云端理解（第 2、3 阶段一起发版）
- [ ] 提交：按项目约定，由用户确认后提交
