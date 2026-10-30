# Implementation Report: 画面理解 · 第 3 阶段 —— 代理素材与云端理解

## Summary
开启画面理解时，分析在「画面检查」之后多跑 `vision` 阶段：浏览小样切成 5 分钟一段、5 fps、300 kbps、无音轨、去掉元数据的画面代理，逐段上传 MediaKit `video-understand-router`（手动 2 / 2.5 / 3 fps 三档），解析模型 JSON、换算成全片时间，合并成 `work/visual_timeline.json`。按段续跑（被杀后不重提、不重复记账），用量另记 `work/vision_usage.json`（不计入 LLM 上限，`aicut status` 显示）。② 开启时 13 项进度；关闭时与原来完全一致。CLI：`aicut new --vision`、`aicut vision <名>`。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | 7/10 | 一次实现到位；审查后补了被杀窗口与元数据两处 |
| Files Changed | 约 20 | 37（新模块 3、新测试 4、改代码 15、改测试 10、文档 5） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | 实测档位参数 | Skipped（不花 tokens） | 偏差：第 1 阶段的 `eco_audio` 已证明 `level` + `manual_option` 同传会被接受，但看不出哪个生效 → 直接用计划里的退化方案：只传 `manual_option`（2 / 2.5 / 3 fps），不传 `level`、不传 `client_token` |
| 2 | cloud.py 通用上传 / 提交 | Complete | 另加 `CloudClient.key_id()`（审查 L2/L3） |
| 3 | 档位参数、码率 | Complete | `TIER_FPS` + `tier_params()` 代替 `TIER_PARAMS` 字典；`MIN_TAIL_S` 放在 `vision.py` |
| 4 | `vision_proxy.py` | Complete | 审查后加 `-map_metadata -1 -map_chapters -1`（真 ffmpeg 验证 GPS / 机型 / 拍摄时间已去掉） |
| 5 | `vision_timeline.py` | Complete | 审查后加 `RecursionError`、输出长度上限、每段事件数上限 |
| 6 | `vision_run.py` | Complete | 审查 H1/H2 后加 `chunk_NNN.raw.json`；鉴权失败中止其它段；failed.json 加锁；本地读写错转 VisionError |
| 7 | 账本 | Complete | `summary` 没加 `file=`，改为 `vision_tokens()`（更小） |
| 8 | 流程接入 | Complete | `needed_keys(work, cfg)` 收 project.json 而不是布尔（要判断时间轴是否已是当前的） |
| 9 | ② 进度 | Complete | 前端已按返回的 `total` 显示，不用改逻辑 |
| 10 | 打包与文档 | Complete | 另改 SOP；PRD 第 3 阶段保持 in-progress，等真账号验收 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | N/A | 项目未配置 lint / 类型检查 |
| Unit Tests | Pass | 新增 / 修改测试见下 |
| Build | Pass | spec hiddenimports 加 3 个模块（`test_structure`） |
| Integration | Pass | 全量 4021 passed, 12 skipped；覆盖率 95%（vision_run 97%、vision_timeline 96%、vision_proxy 100%） |
| Edge Cases | Pass | 极短 / 3 小时素材、尾段并入、乱码重提、终态失败、续查、key 变化、上传过期 / 被作废、被杀在各写盘点之间、鉴权失败中止、超深嵌套 JSON |
| Manual（真账号） | 待做 | PROGRESS #33：60 分钟素材、停止后重跑、账本、关开关回 11 项（需用户确认后上传） |

## Files Changed
- 新建：`pipeline/vision_proxy.py`、`pipeline/vision_timeline.py`、`pipeline/vision_run.py`；`tests/test_vision_proxy.py`、`test_vision_timeline.py`、`test_vision_run.py`、`test_vision_wiring.py`
- 改代码：`aicut.py`、`pipeline/{cloud,vision,encode,usage,readiness,diskspace,cli_args,project_cli}.py`、`gui/{analysis,settings}.py`、`gui/static/step-analyze.js`（注释）、`packaging/ai-cut.spec`
- 改测试：`test_cloud`、`test_vision_setting`、`test_encode`、`test_usage`、`test_aicut_must_keep`、`test_aicut_cli`、`test_stamps`、`test_clips_restore`、`test_analysis_progress`
- 文档：`docs/GUI.md`、`docs/PRD-AI粗剪工具.md`（FR-2）、`docs/TECH-STACK.md`、`docs/PROGRESS.md`（#33）、`docs/SOP.md`；多模态 PRD 状态

## Deviations from Plan
- Task 1 没调真接口（见上表）。
- 每段多一个 `chunk_NNN.raw.json`：计划里「解析失败清 task_id」的顺序会在被杀时丢掉已付费的结果、并重复记账（审查 H1/H2）。现在：原始输出落盘 → 清任务号 → 记账；用量最多少记一次，不会多记。
- 画面段去掉元数据（安全审查 MEDIUM）：浏览小样会带着原始视频的 GPS / 机型 / 拍摄时间。浏览小样本身只在本机，没改。
- `needed_keys` 第二个参数是 project.json（计划写 `vision_on` 布尔）。

## Issues Encountered
- `tests/test_encode_lazy.py` 单独跑会失败（把平台改成 win32 后 ssl 导入报错），改动前也一样；全量跑通过。与本阶段无关，没处理。

## Review
- `ecc:python-reviewer`：H1、H2（被杀窗口）已修，复审通过；M2（鉴权失败后其它段继续上传）、M3（failed.json 并发写）、L1（缺 key 时误判当前）、L2/L3（私有函数）已修。未改、写进模块说明：M1（不传 `client_token`，提交响应丢失可能多一个任务）、M4（续用上传被拒就重传一次，同 ASR）、M5（上传后记 file_id 前被杀只是重传）、同一项目两个进程同时分析不互斥。
- `ecc:security-reviewer`：无 CRITICAL / HIGH。MEDIUM 元数据、超深嵌套 / 超长输出、本地读写错误不进 failed.json 已修。未改：上传地址没有域名白名单（已有 https 限制、不跟随重定向、不带 Authorization）；第 4 阶段把画面文字喂给 DeepSeek 时要当数据包起来（提示词注入）。

## Next Steps
- [ ] 真账号验收（PROGRESS #33 第 3 阶段项），通过后 PRD 第 3 阶段标 complete
- [ ] 提交：按项目约定，由用户确认后提交
- [ ] 第 4 阶段：整合与判定
