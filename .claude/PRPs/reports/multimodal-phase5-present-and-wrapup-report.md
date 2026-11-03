# Implementation Report: 画面理解 · 第 5 阶段 —— ③ 呈现与收尾（含旧时间轴认回）

## Summary
③ 显示画面信息：对白句下多一行「画面：…」与画面问题标签，右侧当前片段显示完整画面描述、画面上的字与画面问题；没有对白的画面片段（V001…）按时间插进列表，有画面片段时多一个「画面片段」筛选，按话题看时单独一组放最后。画面片段可以改档、标不可用、放进剪辑列表；放进去的整段成镜一路到 ⑤ 和剪映（原声保留、没有字幕、备注「画面：<标题>」），不放就不会被 AI 选上，也不进档位计数、话题时长、说话人和 ④ 待定裁决。画面片段的人工裁决按起止时间锚定（前后 3 秒内）。另做旧项目迁移：2026-10-31 之前付过费的画面时间轴（旧指纹含浏览小样修改时间）在浏览小样没变时自动认回，不再上传、不要 MediaKit Key。关闭画面理解时 ③ / ④ / ⑤ / 导出与改版前一致（7 个筛选、计数与排序不变，金标准测试通过）。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 一次实现；审查后补了 6 处（见 Review） |
| Files Changed | 约 18 | 25（新模块 1、新测试 3、改代码 14、改测试 5、文档 2；不含报告 / PRD） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | `pipeline/visual_clips.py` | Complete | 另加 `markable()`：读取 + 结构校验，8 处调用点共用 |
| 2 | 旧版时间轴 key 认回 | Complete — 偏离 | 见 Deviations：`current_or_adopt` / `reusable` |
| 3 | 改档锚点认画面片段 | Complete | 审查后锚点加 `end`，起止都要在 3 秒内 |
| 4 | ③ 接口 | Complete | 同时改了 `exclusions.spans`（不可用的画面片段导出时排除） |
| 5 | ④ / ⑤ / 导出 | Complete | ⑤「未采用」只列放进剪辑列表却不在表里的画面片段；画面片段不做冷开场 |
| 6 | ③ 前端 | Complete — 偏离 | 「画面片段」筛选只在有画面片段时出现（PRD 规定 7 个筛选，有测试） |
| 7 | 文档与放行 | Complete | GUI.md ② / ③、PROGRESS #34、spec hiddenimport |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | N/A | 项目未配置 lint / 类型检查 |
| Unit Tests | Pass | 新增约 50 个测试 |
| Build | Pass | spec hiddenimports 加 `pipeline.visual_clips`（`test_structure`） |
| Integration | Pass | 全量 4179 passed, 12 skipped；总覆盖率 95%（payloads 97%、review 99%、select 97%、vision_run 97%、result_payload 99%） |
| Edge Cases | Pass | 关闭画面理解、写坏的 visual_segments（非 dict / 非 V 编号 / 重复 / visual 非对象）、重新分析后编号平移、起点近但长短不同、不可用 + 剪辑列表、修改时间变了不认回、半途的旧结果只补未完成段、segments_scored 不是对象 |
| Manual（本机，不花钱） | Pass | `vision-p4-acceptance`：③ 182 段（对白 138、画面片段 44），计数 废片 31 / 待定 46 / 可用 61（与第 4 阶段验收一致），画面片段 8 可用 36 待定，按时间排序；`vision-acceptance`（未复制过的旧项目）认回成功、无网络调用；`vision-gui-acceptance` 是复制出来的，修改时间已变，认不回（已知限制） |
| Manual（剪辑师） | 待做 | 放行检查 #34；PRD 成功指标的开 / 关对比（3 条素材） |

## Files Changed
- 新建：`pipeline/visual_clips.py`；`tests/test_visual_clips.py`、`tests/test_browse_visual.py`、`tests/test_frontend_browse_visual.py`
- 改代码：`pipeline/review.py`、`pipeline/select.py`、`pipeline/exclusions.py`、`pipeline/vision_run.py`、`pipeline/readiness.py`、`pipeline/classify.py`（注释）、`pipeline/vision_align.py`（注释）、`gui/payloads.py`、`gui/project_routes.py`、`gui/browse_batch.py`、`gui/result_payload.py`、`gui/static/step-browse.js`、`gui/static/cliplist.js`、`gui/static/app.css`、`aicut.py`（两行原地改，仍 800 行）、`packaging/ai-cut.spec`
- 改测试：`test_review`、`test_select`、`test_vision_run`、`test_aicut_build`
- 文档：`docs/GUI.md`、`docs/PROGRESS.md`（#34）

## Deviations from Plan
- **认回放在「真要跑」的写入口**：计划只在 `vision_run.run()` 里认回；实际 `aicut.py cmd_vision` 在调 `run` 之前先用 `timeline_current` 决定要不要外发确认、要不要 MediaKit Key，旧项目会被要 Key。改为 `current_or_adopt()`（会改盘，只在分析时调用）替换那一行；另加只读的 `reusable()` 给 `readiness.needed_keys` 和磁盘余量估算用（审查 MEDIUM），剪辑台轮询仍只读。认回时任务日志打印「沿用改版前已付费的结果」，不用返回值标记。
- **「画面片段」筛选按需出现**：PRD / 现有测试规定 ③ 是 7 个筛选；关闭画面理解的项目保持 7 个，只有存在画面片段时才多第 8 个。
- **⑤ 未采用清单**：计划没提。可用的画面片段不进 AI 选段，若照旧规则会全部出现在「未采用」里且没有正文；改为只列「放进剪辑列表却不在表里」的，正文用画面标题。
- **不可用的画面片段导出时排除**：`exclusions.spans` 也走 `markable`（计划漏列）。

## Issues Encountered
- `test_frontend_browse.py` 固定了 7 个筛选 → 见 Deviations。
- `aicut.py` 正好 800 行：两处都是原地替换一行。

## Review
- `ecc:python-reviewer`：无 CRITICAL / HIGH。已修：M1 旧项目被要 MediaKit Key（`reusable`）；M2 关了画面理解后画面片段上的旧裁决每次选段都报「对不上」（不再提醒）；L1 起点近但长短不同的画面片段会认领裁决（锚点加 end）；L2 必留画面片段触发音频信号回填（补空 signals）；L3 补时长的候选池排除画面片段。未改：M2 前半「关掉开关但还没重新分析时 ③ 仍显示上次的画面片段」——③ 一直显示上次分析的结果（对白档位也一样），② 会提示重新分析；L4 认回逐文件写、不加锁：中断后下次调用接着认回，没有数据损失。
- `ecc:typescript-reviewer`：无 CRITICAL / HIGH，转义全部覆盖。已修：M1 重新读后画面片段没了、筛选停在「画面片段」显示 undefined（退回「全部」）；M2 分组排序按 kind 而不是文案；L4 当前片段描述重复；L5 画面上的字截断；补了转义、7 个筛选、分组排序的测试。
- `ecc:security-reviewer`：无 CRITICAL / HIGH。已修：M1 `segments_scored.json` 不是对象时标不可用接口 500；L2 画面片段编号必须是 V###、去重；L3 `visual` 不是对象时丢弃。确认：没有新增外发；画面文字在 vision_align 已截断、issues 白名单；备注 ≤43 字。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_visual_clips.py` | 8 | 读取、校验、合并、排序、标题 |
| `tests/test_browse_visual.py` | 10 | ③ 接口、计数、标记 / 批量 / 不可用、④ 待定队列、⑤ 未采用与合计 |
| `tests/test_frontend_browse_visual.py` | 13 | 画面行、画面片段行、筛选、分组、当前片段、剪辑列表、转义 |
| `tests/test_review.py` | +7 | 画面片段锚点、平移、不串、起止都要近 |
| `tests/test_select.py` | +7 | 不自动选、必留整段成镜、不可用、核对、冷开场、回填、旧裁决提醒 |
| `tests/test_vision_run.py` | +8 | 认回、不认回、半途续跑、只读判断、Key 需求 |
| `tests/test_aicut_build.py` | +1 | 无字幕镜头是空镜、无文字 |

## Next Steps
- [ ] 剪辑师跑放行检查 #34
- [ ] 开 / 关对比验收（PRD 成功指标，≥3 条素材）后，PRD 第 5 阶段标 complete
