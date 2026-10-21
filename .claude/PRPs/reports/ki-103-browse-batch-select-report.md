# Implementation Report: ③ 看素材 · 批量选择与全选（KI-103）

## Summary

③ 片段列表加勾选框、Shift 连选、「全选」当前筛选、底部批量操作栏（放入 / 移出剪辑列表、标为可用 / 废片 / 不可用、取消选择）。后端新增原子的 `POST /api/browse/batch`（`gui/browse_batch.py` + `review.set_batch`）；一次 Z 撤销整批。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Medium（约 8 个文件） | Medium；16 个已跟踪文件修改 + 4 个新文件（含测试与文档） |
| Tests | — | 3153 → 3370 passed，覆盖率 95%（门槛 80%） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | `review.set_batch` | done | `_write` 的逐条合并抽成 `_merge_item` 共用；公开 `check_batch` 供路由复用 |
| 2 | `POST /api/browse/batch` | done | 偏离：放在新模块 `gui/browse_batch.py`，在 `gui/server.py` 分发链里注册（放进 `POST_ROUTES` 会循环导入） |
| 3 | 勾选 UI | done | |
| 4 | 批量操作与整批撤销 | done | Z 改为串行（连按两次 Z 不会并发） |
| 5 | 文档与登记 | done | KI-103、界面流程 ③、GUI.md、PROGRESS #25、CHANGELOG |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | 未配置 | `node --check` 三个 JS 文件通过 |
| Unit Tests | Pass | 后端 `tests/test_browse_batch.py`；前端 `tests/test_frontend_batch_select.py` 70 个 |
| Build | 未跑 | 打包脚本本日已跑过一次（改动前）；spec 已登记 `gui.browse_batch` |
| Integration | N/A | 未做真机冒烟；放行检查 #25 待人工 |
| Edge Cases | Pass | 计划中的边界清单全部有测试 |

## Review Findings Fixed（无 CRITICAL / HIGH）

- 后端 M1：批量 `level: null` 会连带删掉失效条目上的剪辑列表标记（与单段 `unset_level` 不一致）。
- 后端 M2 / 安全 MEDIUM：标记写盘后同步手动分镜表失败仍回 4xx，前端回滚但服务端已保存 → 改为 200 + `warning`，前端重新读取。
- 后端 M3：路由与 review 两套校验 → 统一用 `review.check_batch`；`level` 拒绝浮点 / 不可哈希值。
- 前端：批量请求缺 epoch 作废检查；连按两次 Z 可乱序；失败后不与服务端对账；键盘 Space 勾选后焦点丢失、每行 aria-label 误用「全选」；成功后误清在途期间新勾的行。

## Deviations from Plan

- 批量路由放在 `gui/browse_batch.py`（见上），`gui/static_files.py` 白名单与 `packaging/ai-cut.spec` 一并登记。
- 一直在 `main` 上开发（与前 14 个里程碑一致；切分支需用户确认）；计划文件未移入 `completed/`，与前例一致。

## Issues Encountered

- 前后端两个 agent 并行，各自全量测试时会看到对方在建的失败，最终合并后全绿。
- 钥匙串：只读核对，`ai-cut` 下只有用户自己的 `deepseek` 条目（2026-10-20 13:58:31Z 创建），本次未新增、未改动。

## Next Steps

- [ ] 真机走查：`docs/PROGRESS.md`「待人工放行检查」#25
- [ ] 提交后回填 KI-103 提交号
