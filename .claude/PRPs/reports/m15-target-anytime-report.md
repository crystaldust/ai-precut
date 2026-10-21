# Implementation Report: 成片时长随时可改（里程碑 15，KI-104）

## Summary

成片时长除了 ⑤ 看结果，现在还能在 ①（= 更多 → 项目设置）和 ③ 剪辑列表面板里改；③ 超出目标时一键「改为」建议值。①③ 里改只保存，已有选段时 ⑤ 标「需要更新 · 目标时长改过了」，不自动重新选段；⑤ 维持改完即重选。`/api/project/settings` 接受 `target`，项目有任务在跑（本进程任务或另一进程占着项目锁）时拒绝改时长。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Medium（约 9 个文件） | Medium；17 个已跟踪文件修改 + 1 个新测试文件（含文档） |
| Tests | — | 3370 → 3447 passed，覆盖率 95%（门槛 80%） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | 后端 `target` | done | 红灯 22；审查后改为在 `JOBS_LOCK` 内检查并写入，另用 `project_lock.exclusive` 非阻塞挡住终端 `aicut` / 遗留子进程（红灯 4） |
| 2 | 项目设置弹窗时长 | done | 红灯 12；只在值变了时发 `target` |
| 3 | ③ 面板改时长 | done | 红灯 19 + 审查修复 9 + 1；未拆新文件（`cliplist.js` 320 行） |
| 4 | 文档与登记 | done | PRD FR-1、界面流程 ①③ 与入口表、KI-104、GUI.md、PROGRESS #26、CHANGELOG |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | 未配置 | 全部 `gui/static/*.js` 过 `node --check` |
| Unit Tests | Pass | 3447 passed |
| Build | 未跑 | 无新模块，spec 无需改动 |
| Integration | N/A | 未做真机冒烟；放行检查 #26 待人工 |
| Edge Cases | Pass | 计划清单全部有测试 |

## Review Findings Fixed（无 CRITICAL / HIGH）

- 后端 / 安全 MEDIUM：「有无任务」检查与写 `project.json` 之间有窗口，⑤ 带 `--target` 的选段任务结束时会静默覆盖 ①③ 刚存的时长 → 检查与写入放在 `JOBS_LOCK` 内（锁顺序 `JOBS_LOCK` → 项目锁 → project.json 文件锁，已核对无反转）。
- 后端 MEDIUM：守卫看不到终端里的 `aicut select` / 遗留子进程 → 非阻塞取 `.aicut-busy.lock` 独占锁；已核对剪辑台进程自身从不持有该锁的共享锁，无误报。
- 后端 LOW：任务在跑时提交与当前相同的时长 → 当作没改，不回 409。
- 前端 MEDIUM：保存标志不分项目；保存后面板显示旧目标直到重读（重读失败则一直旧）；重画时输入框丢焦点导致后续按键触发快捷键。
- 前端 LOW：有标记在途时「改为 X」用的是旧建议值 → 在途时隐藏；XSS 测试空转 → 换成能检出未转义文本的测试；③ 保存提示「项目设置已保存」→ 改为「成片时长已保存」。

## Deviations from Plan

- 未拆出 `clip-target.js`：`cliplist.js` 320 行，在上限内。
- 新增 `gui/jobs.py` 的 `project_running_locked`（锁内判断用，`JOBS_LOCK` 不可重入）。
- ③ 的保存提示用独立文案 `COPY_CLIP_TARGET_SAVED`。
- 一直在 `main` 上开发；计划文件未移入 `completed/`，与前例一致。

## Issues Encountered

- 现有设置弹窗测试的 DOM 桩不解析 HTML，加了时长校验后需要在两处旧测试里显式填分 / 秒。
- 钥匙串只读核对：`ai-cut` 下只有用户自己的 `deepseek` 条目（2026-10-20 13:58:31Z），未新增、未改动。

## Next Steps

- [ ] 真机走查：`docs/PROGRESS.md`「待人工放行检查」#26
