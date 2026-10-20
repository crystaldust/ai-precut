# Implementation Report: 向导：从新建到定标准（里程碑 13）

## Summary

界面改为六步项目向导的前半段：外壳（自动收起的项目栏、步骤条、任务胶囊、更多菜单、底部导航）、首次打开告知与内联填 Key、① 新建（含剪辑偏好，创建即分析）、② 分析（人话进度、失败重试、中断续跑）、③ 看素材（剪辑列表 S / 不可用 X / 档位 A D / 撤销 Z、自定义快捷键）、④ 定标准（分析确认、逐段裁决待定、决策问题、闸门）。⑤⑥ 暂住旧分镜表与版本视图，留给 M14。删除了子窗口机制（browse / confirm / calibrate 页面、`/api/window`、`gui/desktop.py`）。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | XL（4 个子切片） | XL；按 M13a–d 交付，6 个代码提交 + 1 个文档提交 |
| Confidence | 7/10 | 每个子切片的审查都查出 HIGH（共 11 个），全部修复后才提交 |
| Files Changed | ~50 | ~110（含测试拆分与新增） |
| Tests | — | 1811 → 2637 passed，覆盖率 94.4%（门槛 80%） |

## Commits

| 切片 | 提交 | 内容 |
|---|---|---|
| A1 | `9a705c3` | 路由搬出 `gui/server.py`；FR-4 文档守卫先标 xfail |
| A2 | `f815ddc` | KI-93 不可用标记：存储、选段排除、出片剔除与必留复核、旧版本导出拦截 |
| A3 | `b2f4c69` | 输入指纹与戳、步骤状态、分析进度、偏好 / 项目设置 / 话题显示名接口、后端文案 |
| B1 | `5d25267` | 前端拆分与新外壳、首次打开、① 新建、② 分析、KI-97 |
| C1 | `d65c994` | ③ 看素材、剪辑列表、快捷键、KI-99 |
| D1 | `efeb92b` | ④ 定标准与闸门、删除子窗口、名词守卫、GUI.md 重写 |
| D2 | `a1df2bd` | KI-96 回填提交号 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | 未配置 | 项目无 lint / typecheck；`node --check` 全部静态 JS 通过 |
| Unit Tests | Pass | 2637 passed；前端行为测试走 node vm（`tests/fe_harness.py`） |
| Build | 未跑 | 打包 `build_app.sh` 未在本里程碑执行（放行检查 #12） |
| Integration | Pass | 无头 Chrome + 本地真服务器冒烟 43/43（③→④→闸门→⑤→⑥） |
| Edge Cases | Pass | 跨项目任务完成、快速切项目、在途请求离开页面、乐观更新失败回滚、未保存编辑不被刷新覆盖等均有回归测试 |

## Review Findings Fixed Before Commit（HIGH 级）

- A2：出片剔除不可用镜头后未复核必留覆盖；`shots.json` 读改写与保存分镜表无锁。
- A3：项目设置的预设可路径穿越；步骤状态判定有写盘和 ffprobe 副作用。
- B1：别的项目任务完成会把当前页带走；刷新会覆盖未保存的字幕；异步动作失败无提示。
- C1：乐观队列失败回滚写坏状态；写入成功后响应拼装失败被报成失败。
- D1：离开 ④ 后在途回包抛错；闸门不等档位队列就确认。

## Deviations from Plan

- 新增 `base.js` / `main.js`、`criteria-analysis.js` / `criteria-pending.js` 以守住每文件 ≤ 400 行。
- `timeline_hits` 改读版本目录的 `shots_snapshot.json`（timeline 的 in/out 是切片内时间）；有不可用标记但快照缺失 / 损坏时拦截导出（失败即关闭）。
- browse 页面在 C1 删除（按计划 Task 17），confirm 与子窗口机制在 D1 删除。
- `/api/confirm` 精简为 `pending` 只带 id 与时间，删除未使用的 `blocks` / `legacy` 字段。
- CHANGELOG 在仓库根目录（计划写的是 `packaging/`）。
- 一直在 `main` 上开发（与里程碑 1–12 一致；切分支需用户确认）；计划文件未移入 `completed/`，与前 12 个里程碑一致，PRD 里的链接保持有效。

## Issues Encountered

- **冒烟测试误写钥匙串**：一次冒烟未设 `AI_CUT_SECRETS=file`，把两个假 Key 写进了用户登录钥匙串（`ai-cut` / `mediakit`、`deepseek`），核对为假值后已删除，现无 `ai-cut` 条目。之后的冒烟都用临时配置目录。
- 部分前端测试是实现后补写，未逐条观察到红灯；D1 修复轮要求先红后绿，并报告了实际观察到的红灯数。

## Newly Registered

- KI-99（`/api/browse` 已用 / 未用只看手动分镜表）— 已在 `d65c994` 修复。
- KI-100（事后标不可用不会让已导出产物失效）— 留给 M14 ⑥。

## Next Steps

- [ ] 真机走查：`docs/PROGRESS.md`「待人工放行检查」#13–#19
- [ ] 里程碑 14：⑤ 看结果与 ⑥ 导出（GL-26 剩余部分、GL-27、KI-94、KI-95、KI-98、KI-100）
