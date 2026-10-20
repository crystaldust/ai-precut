# Plan: M13 · 向导：从新建到定标准（GL-26 框架与 ①–④ / KI-93 / KI-96 / KI-97）

## 产品决定（2026-10-20 用户确认：P1–P9 全部按推荐默认；标 ⚑ 处即受影响位置）

| # | 问题 | 推荐默认（本计划按此实现） | 备选 | 影响 |
|---|---|---|---|---|
| P1 | ④「剩下的按 AI 建议」/ 闸门询问「按 AI 建议处理？」里的「AI 建议」是什么？代码里**待定段没有任何「建议档位」字段**（`pipeline/classify.py:93-124` 只给 level=2 + 理由），选段只用 level=3（`pipeline/select.py:326-333`） | **不写任何裁决**：剩下的待定保持「待定」，选段照旧不用它们（= 现状，不改算法）。文案如实说：「剩下 N 段按 AI 建议：先不进片（之后仍可在 ③ 看素材里改）」 | 把剩下的批量写成废片（overrides 里多 N 条人工裁决，③ 里会显示「人工改为废片」） | T19（④ 文案与闸门） |
| P2 | 改版前的旧项目（已经出过版本 vN、或手动存过 `shots.json`，但从没「确认」过决策答案）进新界面时，⑤⑥ 是否要先过 ④ 才能点？ | **视为已过 ④**（`legacy=true`）：⑤⑥ 可直接进；④ 页顶部一行提示「这个项目在改版前已出过片，没经过定标准；需要时可以在这里确认一次」 | 严格按闸门：旧项目也必须先在 ④ 确认一次才能看自己的旧版本 | T8 `derive()`、T19 |
| P3 | ④「可改话题名」改的是什么？话题名同时是决策问题选项、`must_topics` / `exclude_topics` 规则的匹配键（`pipeline/select.py:320-325` 模糊匹配） | **只改显示名**：存 `work/topic_names.json {原名: 新名}`，③④⑤ 显示新名；选段、答案、规则仍按原名匹配，不影响剪法。单段「改到别的话题」不做 | 真改话题（要同步改 questions / answers / rules，等于改算法输入） | T9b、T15、T18 |
| P4 | 旧项目的剪辑偏好 `tone=balanced`（均衡，现有默认，`pipeline/style.py:16,27-29`），新界面规格只有「信息 / 情绪」两个选项 | **新建默认「信息」**；「项目设置」里当前值是均衡时额外显示第三个选项「均衡（改版前的设置）」，选了别的就不再出现 | 旧项目打开即显示为「信息」（会让 ② 标「需要更新」） | T13 |
| P5 | 分析被中断（关窗口 / 强退 / 取消）后回到项目：要不要自动接着跑？（FR-12「回来接着跑」） | **不自动重跑**（会外发、计费）：② 显示「上次分析没跑完（已完成 6/11）」+「继续分析」按钮，已完成的步骤会跳过 | 打开项目时自动续跑 | T14 |
| P6 | 旧版本 vN 里含**后来**标成「不可用」的片段：⑥ 里对这一版「生成 Windows 剪映包」怎么办？（FR-11「标记后所有版本均不出现该片段」） | **阻止并说明**：「这一版含 N 段已标为不可用的片段，不能再导出；请生成新版本」；已经进了剪映草稿库的 Mac 草稿不动（程序改不了，剪映会加密工程） | 允许导出，只在日志里 [!] 提示 | T3 |
| P7 | ④ 左侧小目录「每块完成情况」怎么判？规格没说「分析对不对」块有没有必做动作 | ①「分析对不对」无必做动作，显示「可选」；②「裁决待定」待定 = 0 时 ✓；③「决策问题」每题都有答案时 ✓。三块都不是闸门条件（闸门按钮始终可点，待定没裁完先问——§七.2） | 加一个「分析没问题」勾选框作为第 ① 块完成条件 | T18、T19 |
| P8 | Z / ⌘Z 撤销的范围：规格 ③ 写「撤销上一次放入 / 移出」，快捷键表写「Z 撤销」 | **撤销 ③ 里最近一次标记**，S / A / D / X 都算；只在本次打开的 ③ 内有效，最多 50 步；切项目 / 刷新后清空 | 只撤销剪辑列表的放入 / 移出 | T16 |
| P9 | 同一片段既在剪辑列表又被标「不可用」（隐私段）怎么办？ | **互斥，后按的生效**：按 X 会把它移出剪辑列表并提示「已移出剪辑列表并标为不可用」；对不可用段按 S 会取消不可用并放入列表，同样提示 | 不可用优先：对不可用段按 S 拒绝并提示先取消不可用 | T2 |

> 以上任何一条改了，只影响标注的 Task，其它切片照做。

---

## Summary
把剪辑台从「一排按钮 + 5 个标签页 + 3 个子窗口」改成**一个项目一条步骤条的六步向导**，本里程碑交付**框架（项目栏自动隐藏、步骤条、底部导航、更多菜单、任务胶囊、首次打开告知 + 填 Key）和 ①–④ 四步**；⑤⑥ 先用现有的分镜表 / 版本视图「暂住」，保证 M13 结束时全流程照样能走到剪映，M14 再替换。
步骤状态（未到 / 可进入 / 已完成 / 需要更新）全部由**服务端纯函数**从项目产物与输入指纹推导，可单测；「需要更新」靠**输入指纹**（不是 mtime）判断。
同时端到端补上「不可用」标记（KI-93：存储 → 选段排除 → 未采用清单排除 → 出片自动剔除 / 旧版本导出拦截），统一界面名词（KI-96），并处理任务前置检查 `need=encoder`（KI-97）。

## User Story
作为不懂命令行的剪辑师，我想按步骤条一步步走：建项目时就把偏好说清楚、看着人话进度等分析、在素材里用 S 快速挑段、在「定标准」里裁决待定和答题后一键生成分镜表，没走到的步骤点不了、往回改了会提示我哪一步需要更新，这样我不用看说明就能从新建走到出分镜表。

## Problem → Solution
- 选中项目 9 个按钮全亮、未分析就能「生成成片」（GL-26）→ 步骤条 + 服务端 `gui/wizard.py::derive()` 决定每步能否进入；每个动作只有一个入口。
- 偏好 / 浏览 / 确认 3 个子窗口互不联动（GL-26）→ 全部并进主页面（① 新建弹窗 + 更多→项目设置、③ 看素材、④ 定标准），删掉子窗口与 `/api/window`。
- 往回改不知道哪里过期 → 输入指纹：分析输入戳（`work/analysis_inputs.json`）、选段输入指纹（`selection.json.inputs`）、答案对应的题目指纹（`brief_answers.json.questions_digest`）；不一致 → 「需要更新」+ 横幅 + 一个按钮，不自动重跑。
- 「不可用」没有入口、选段也不认（KI-93）→ `overrides.json` 新字段 `unusable` → 选段开头整段剔除（不进候选、不进未采用清单、不被指定原话强拉）→ 手动分镜表里重叠的镜头标记时即移除 → 出片时自动剔除并 [!] 提示 → 旧版本含不可用段拦截 Windows 导出（⚑P6）。
- 名词混乱（KI-96）→ 前端只用 PRD §12 术语；后端会显示到界面的提示文案里指向旧入口的（「浏览素材」「① 处理素材」「改目标时长」「⚙ 设置 · API Key」…）全部改指新位置；`tests/test_terms.py` 守住。
- `need=encoder` 只记一行日志（KI-97）→ 任务前置检查的所有 `need` 都有明确界面：consent / keys 在 ② 页内联，encoder（及未知 need）弹说明 + 「导出诊断包」。
- 顺带修：`/api/browse` 的「未用 / 已用」只看手动 `shots.json`，没有手动分镜表时全部显示未用（`gui/payloads.py:35-39`）→ 登记 **KI-99** 并在 ③ 一起修（③ 的「未用」筛选依赖它）。

## Metadata
- **Complexity**: **XL**（约 50 个文件：新建 ~24、改 ~26；前端几乎重写）→ 拆成 4 个子切片，**每个子切片结束都是可交付、可用的 App**：
  - **M13a 后端地基**（不动界面）：路由拆分腾行数 → KI-93 后端 → 指纹 / 步骤状态 / 分析进度 / 偏好与快捷键接口 / 新建带偏好 / 项目设置 / KI-96 后端文案
  - **M13b 框架 + ① ② + ⑤⑥ 暂住**：新外壳（项目栏、步骤条、更多菜单、任务胶囊、首次打开闸门）、① 新建 / 项目设置、② 分析页、⑤⑥ 承接旧分镜表 / 版本视图；③④ 暂时仍开旧子窗口；KI-97
  - **M13c ③ 看素材**：片段列表、播放器、剪辑列表面板、S / A / D / X / Z、快捷键自定义、不可用入口（KI-93 前端）；删 `browse.*`
  - **M13d ④ 定标准 + 收尾**：三块 + 闸门；删 `confirm.*`、`/api/window`、`gui/desktop.py`；KI-96 名词守卫；文档
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 13「向导：从新建到定标准」（GL-26 ①–④ 与框架、KI-93、KI-96、KI-97）
- **Estimated Files**: ~50（见 Files to Change）
- **Spec**: `docs/界面流程-v2.md`（逐屏规格，§七 评审已定）、`docs/PRD-AI粗剪工具.md` v1.3（§4.1、FR-1/4/5/6/11/12/14、§12）。设计稿 `designs/aicut.pen`（加密，**不要用 Read/Grep 打开**；规格文档已描述）。

### 基线（2026-10-20，HEAD `6579262`）
- `uv run pytest`：**除 1 个外全绿**。`tests/test_docs_consistency.py::test_quick_filters_match_gui` **已经是红的**：PRD v1.3 的 FR-4 快捷筛选已改成「全部 / 待定 / 可用 / 废片 / 剪辑列表 / 不可用 / 未用（界面在 ③ 看素材，KI-96）」，而 `browse.html` 仍是「全部 / 待判断 / 可用 / 废片 / 未用」。本里程碑 T15 把守卫改指新的 ③ 筛选并去掉括注后转绿；在此之前 CI 也是红的——**M13a 第一个提交就先把这条测试标 `xfail(strict=True, reason="M13c 转绿")`**，免得掩盖其它回归。
- 行数红线（`tests/test_structure.py:6-7`）：`aicut.py` ≤ 800（现 750），`gui/server.py` ≤ **650（现 646，只剩 4 行）** → 新接口一律放新模块；T1 先把 ~95 行既有路由搬出去。
- 所有前端源文件 < 800 行（`index.js` 现 604 行，本里程碑拆成 13 个聚焦文件，每个目标 < 350 行）。

---

## 工程决策（按默认执行，均可事后改）

| # | 决策 | 默认 | 理由 |
|---|---|---|---|
| D1 | 步骤状态放哪 | 服务端 `gui/wizard.py`：`collect(pdir, cfg, name) -> Facts`（只读 IO）+ `derive(facts) -> dict`（纯函数）；随 `/api/state` 返回 `wizard`，项目列表用 `derive` 的轻量版给「当前步骤」 | PRD Risks 要求「先把步骤状态判定放到服务端可单测」；前端只渲染 |
| D2 | 状态集合 | 服务端四态 `locked / available / done / stale`；「当前」是**前端正在看的那一步**（覆盖显示）。`available`（可进入、未完成，如在 ③ 时的 ④）显示为白字可点、无图标 | 规格表只画了 4 种外观；「可进入但未完成」不在表里，取最不打扰的外观 |
| D3 | 「需要更新」怎么判 | **输入指纹**（sha1，忽略 `at` / `anchor` 等易变字段），不用 mtime：② 比 `work/analysis_inputs.json`（prepare 成功时写）与当前偏好 + 预设；④ 比答案存盘时的 `questions_digest` 与当前 `questions.json`；⑤ 比 `selection.json.inputs`（选段时写，分项）与当前输入。旧项目没有戳 → 不判过期 | mtime 会被「切换 S 两次 = 原样」、复制项目、时区误报；分项指纹能告诉横幅「是素材标记改了还是答案改了」 |
| D4 | 下游不连锁 | 每步只看自己的输入；② 过期不把 ③–⑥ 一起标过期 | 规格：「往回改会让**下游**变成需要更新」——由各自输入指纹自然体现（重新分析会重跑 select，⑤ 指纹随之更新） |
| D5 | 快捷键与项目栏固定状态存哪 | **服务端** `~/.config/ai-cut/ui_prefs.json`（`secrets.config_dir()`，与 consent.json 同处），新模块 `gui/prefs.py`，`GET/POST /api/prefs`、`POST /api/prefs/reset`；服务端校验冲突 | ① localStorage 按**源**隔离，而剪辑台端口会顺延（8765 被占就 8766…，`gui/server.py:584-597`），换端口 = 设置丢失；② App（WKWebView）与浏览器模式是两份存储；③ M12 风险表已承诺「前端不用 localStorage」；④ 冲突校验能在 pytest 里测。代价：多一个小接口 |
| D6 | 快捷键键位表示 | `KeyboardEvent.code`（`KeyS`、`Space`、`ArrowDown`…，与输入法 / 键盘布局无关）；只允许单键（字母、数字、空格、方向键、常用符号键），不允许 Esc / Tab / Enter / Backspace 和组合键；⌘Z / Ctrl+Z 固定为「撤销」的别名，不可改 | 中文输入法下 `e.key` 不稳定；组合键会和系统 / WebView 冲突 |
| D7 | 子窗口与旧页面 | `browse.*`（M13c）、`calibrate.*`（M13b）、`confirm.*`（M13d）**并入主页面后删除**；`POST /api/window`、`gui/desktop.py`、`app/main.py` 的 `set_window_opener` 在 M13d 一并删（打包清单、结构守卫同步） | 规格 §六 把三个独立窗口都收进步骤；留着没人调用的代码就是隐患（KI-36 的窗口打开器只为它们存在） |
| D8 | ⑤⑥ 在 M13 怎么「暂住」 | ⑤ 看结果 = 现有分镜表视图（表格、选中行设入出点、试听、↑↓ ✕ ⧉ 空镜、按时间排序）+ 「改目标时长」弹窗（现有 `openTarget`）+ 过期横幅「重新选段」；⑥ 导出 = 现有版本卡片 + 「生成新版本（导出到 Mac 剪映）」弹窗（保留「这次只生成预览片，不导出到剪映」勾选，文案按 §12 改）+ Windows 导出 + 打开剪映。⑤⑥ 在 ④ 完成（或 ⚑P2 旧项目）后可进入；M13 不判 ⑤ 的「已完成」（闸门 B 属 M14） | App 在 M13 结束时必须能端到端出片；M14 替换这两个视图时只改 `step-result.js` / `step-export.js` 和 `derive()` 里 ⑤⑥ 两行规则 |
| D9 | ③④ 在 M13b 怎么暂住 | M13b 时 ③④ 的页面只有一张卡片：说明 + 「打开看素材窗口」/「打开定标准窗口」按钮（仍走旧子窗口）；M13c / M13d 分别替换 | 保证每个提交 App 都可用；子窗口流程已有测试 |
| D10 | 分析步骤顺序 | `PREPARE_STEPS` 改成规格顺序：`ingest, junk, transcribe, analyze, scenes, quality, text, score, summary, questions, select, brief`（浏览小样提到转写前） | 依赖成立（junk 只要素材；scenes/quality 要 proxy + segments，转写后跑；text 要 segments）；**总耗时不变**（本来就是串行）；② 的人话列表与执行顺序一致 |
| D11 | ② 的 11 项人话进度怎么来 | 纯函数 `gui/analysis.py::progress(facts)`：完成看**产物**（如浏览小样 = `proxy.mp4` 完整且绑定当前素材），耗时 / 失败看 `work/timings.json`，「正在跑哪一步」= 本次任务开始后**第一个还没有计时记录的 stage**（`timings[key].started` 或 `last_skipped` ≥ 任务开始时刻）。不改 aicut 的输出格式 | `applog.stage` 只在阶段结束时写计时（`pipeline/applog.py:268-279`），据此推当前步骤零侵入；「抽音轨 / 云端转写」同属 transcribe 一个 stage，用 `asr.wav` 完整与否区分 |
| D12 | 「不可用」与手动分镜表 | 标记时：手动 `shots.json` 里与该片段时间重叠 > `UNUSABLE_OVERLAP_S = 0.1` 秒的镜头**整镜移除**，响应带 `removed_shots`，前端 toast「已从分镜表移除 N 镜」；出片时（`cmd_build`）对分镜表再剔除一次（CLI 改过的、AI 选段旧结果），[!] 提示，剔完为空才 die | FR-11「若已在手动分镜表里，标记后从分镜表移除并提示；导出时自动排除」；隐私优先，宁可多删一镜 |
| D13 | 「不可用」与指定原话 / 必留话题 | 选段一开始就把不可用段从 `segments` 里拿掉：不进话题池、不补时长、不被「指定原话」强拉（原话只命中不可用段时报「没找到」类警告）、不进 `unused`；统计里 `usable_total` 也不算它 | 一处过滤，后面所有路径自动成立，最不容易漏 |
| D14 | 剪辑列表顺序与合计 | 剪辑列表 = `must_keep` 段，按 `overrides[id].at` 升序（加入顺序）；合计 / 目标 / 超出 / 建议时长由服务端纯函数 `payloads.clip_list(segments, target)` 算，建议时长与选段同一规则（向上取整到 `select.TARGET_ROUND_STEP` 秒） | 与 FR-7 的「建议时长」同口径，不在前端复制一份取整逻辑 |
| D15 | ③ 点击 / ↑↓ / 空格 | 点一行 = 设为当前段 + 从入点前 0.3 秒开始播到出点后 0.3 秒（保留原来「点即试听」）；↑↓ = 设为当前段 + 定位，不自动播；空格 = 播放 / 暂停（当前段已播完时从当前段入点重播） | 规格节奏「↓ 换段 → 空格听 → S 要」；点击即试听是 FR-4 原有行为 |
| D16 | 任务胶囊 | 全局一个任务（`MAX_ACTIVE_JOBS=1` 不变）；胶囊在步骤条右侧：「正在分析 6/11 · 3 分钟」/「正在重新选段…」；点开 = 现有任务详情弹窗（日志、取消、重试、诊断包）。分析任务不再自动弹窗（② 页就是进度）；其它任务失败时胶囊变红「失败 · 查看」。启动类按钮在有任务时置灰，`title`=「正在 X，完成后再试」 | 规格 §二；复用 `jobs.js` 已测过的轮询 / 取消 / 重试逻辑，只换外壳 |
| D17 | 首次打开 | 主区全屏两段：外发告知 →「我知道了，继续」→ 两行 Key（掩码状态 + 输入 + 保存）→ 两个都 `configured`（含来自环境变量）才进欢迎页；没有「暂不使用」 | 规格 §四「都填好才进欢迎页」 |
| D18 | `/api/state` 字段 | 新增 `wizard`、`busy`（全局任务）；M13b 删 `stages`、`junk`（旧阶段条、废片 tab 不再用；画面提示在 ③ 按片段显示） | KI-96：阶段条内部术语；规格 §五「画面提示」取代「废片」tab |
| D19 | 话题改名存储（⚑P3） | `work/topic_names.json`，`review.py` 旁新增 `pipeline/topic_names.py`（load / rename / display），只在 payload 里映射显示名 | 不碰 `segments_scored.json`，算法输入不变 |
| D20 | 新增 KI | 实现时登记 **KI-99**：`/api/browse` 的已用 / 未用只看手动 `shots.json`（`gui/payloads.py:35-39`），没有手动分镜表时全部显示「未用」；在 T15 修复并钉测试 | 用户硬约定：发现即登记 + 钉住；它直接决定 ③「未用」筛选是否正确，属本里程碑范围 |

---

## 步骤状态判定（服务端纯函数，T8 的规格）

### Facts（`gui/wizard.py::collect` 读盘得到，`derive` 只吃这个 dict）
| 字段 | 来源 | 说明 |
|---|---|---|
| `analysis_done` | `media_io.complete_or_adopt(work/proxy.mp4, source=material)` 且 `work/segments_scored.json`、`content_summary.json`、`questions.json`、`selection.json` 都存在 | 旧项目（无戳）同样适用 |
| `analysis_running` | `jobs.project_job(name)["task"] == "prepare"` | |
| `analysis_failed` | 不在跑、未完成，且 `timings.json` 里某个 `PREPARE_STEPS` 键 `ok == False` | ② 页细节由 `analysis.progress` 给 |
| `analysis_stamp` / `analysis_inputs` | `work/analysis_inputs.json`（prepare 成功末尾写）/ `fingerprints.analysis_inputs(cfg)` = `{"directive": style.directive(calibration), "preset": cfg.preset}` | 无戳 → `None` |
| `answers_confirmed` | `brief_answers.json["confirmed"] is True` | 读不出 → False |
| `answers_questions_digest` / `questions_digest` | `brief_answers.json["questions_digest"]` / `fingerprints.file_digest(work/questions.json)` | 旧答案无字段 → `None` |
| `legacy` | 未确认答案，且（`output/v*/` 至少一个目录 或 手动 `shots.json` 存在）（⚑P2） | |
| `selection_inputs_saved` / `selection_inputs_now` | `selection.json["inputs"]`（分项 dict）/ `fingerprints.selection_inputs(work, cfg)` | 旧选段无字段 → `None` |

### derive(facts) → `{"steps":[{key, n, label, status, hint, banner, action, reasons}], "next": key, "legacy": bool}`
| 步 | key | locked 条件（hint） | done 条件 | stale 条件（banner / action） | 否则 |
|---|---|---|---|---|---|
| ① 新建 | `new` | — | 恒 done | — | — |
| ② 分析 | `analyze` | — | `analysis_done` | `analysis_done` 且戳存在且 `stamp != inputs` →「剪辑偏好或预设改过了 · 重新分析」/ `reanalyze`（只重跑 AI 理解及之后，会重新调用 AI） | available |
| ③ 看素材 | `browse` | `!analysis_done`（「先完成「② 分析」」） | `analysis_done`（无必做动作） | — | — |
| ④ 定标准 | `criteria` | 同 ③ | `answers_confirmed` 或 `legacy` | done 且 `answers_questions_digest` 与 `questions_digest` 都非空且不等 →「决策问题重新生成过 · 请重新作答并确认」/ 无按钮（就地作答） | available |
| ⑤ 看结果 | `result` | ④ 不是 done/stale（「先完成「④ 定标准」」） | M13 不判（M14 加闸门 B） | `saved` 与 `now` 都非空且有分项不同 → 横幅按分项拼：`overrides`「素材标记改过了」、`answers`「答案改过了」、`target`「目标时长改过了」、`lines`「指定原话改过了」、`scored`「分析结果更新了」+「 · 重新选段」/ `reselect` | available |
| ⑥ 导出 | `export` | 同 ⑤ | M13 不判 | — | available |

- `next`：分析在跑或未完成 → `analyze`；否则依次取第一个 `stale` 或 `available` 的 ④ → ⑤ → ⑥；都没有 → `export`。
- 项目栏「当前步骤」= `next` 的「n + label」（如「④ 定标准」）；轻量 `collect(..., digests=False)` 跳过三个指纹，只算 locked/done。
- 指纹（`pipeline/fingerprints.py`）：
  - `selection_inputs(work, cfg)` 分项：`scored` = `segments_scored.json` 字节 sha1；`overrides` = 每段只取 `level` / `must_keep is True` / `unusable is True`（False 与缺省等价，按 id 排序后 sha1）；`answers` = `brief_answers.json["answers"]` 规范化 JSON 的 sha1；`target` = `int(cfg.target_duration or 175)`；`lines` = `style.normalize(calibration)` 的 `tone` + `must_lines`。
  - 所有 sha1 取前 12 位 hex；文件缺失记 `""`；读不出（损坏）记 `"corrupt"`（不抛）。

---

## UX Design

### Before
```
┌────────┬────────────────────────────────────────────────────────────┐
│＋新建  │ 片名 · 素材 54:12 · 预设 · 目标 3:00                       │
│ 项目A  │ ✓素材台账 ✓抽音轨 ✓语音转写 ○废片检测 ○策划分派单 ○分镜表   │
│ 项目B  │ [①处理素材][②生成成片][确认与提问][浏览素材][改目标时长]     │
│        │ [剪辑偏好][打开文件夹][打开剪映][清理缓存]   ← 全亮          │
│⚙设置   │ 预览 | 文稿 | 分镜表 | 废片 | 版本                          │
│诊断包  │ …                                                           │
│关于    │ 浏览素材 / 确认与提问 / 剪辑偏好 = 3 个独立窗口，互不联动     │
└────────┴────────────────────────────────────────────────────────────┘
```

### After
```
首次打开：[全屏] 外发告知 →「我知道了，继续」→ 两行 Key → 欢迎页（大按钮「新建项目」）

┌──┬──────────────────────────────────────────────────────────────────────┐
│☰ │ 项目名 · 片名   ①新建✓ → ②分析✓ → ③看素材 → ④定标准 → ⑤看结果 → ⑥导出  [正在分析 6/11 · 3 分钟] [更多▾] │
│九│──────────────────────────────────────────────────────────────────────│
│  │ (横幅) 素材标记改过了 · [重新选段]                                     │
│48│                    当前步骤的页面                                       │
│px│──────────────────────────────────────────────────────────────────────│
│  │ ← 上一步                                            下一步：去定标准 →  │
└──┴──────────────────────────────────────────────────────────────────────┘
悬停 ☰ → 浮出 240px 项目栏（＋新建项目、项目列表「名称 · ④ 定标准」、📌固定）

③ 看素材：摘要卡（一句话 / 关键信息 / 说话人时长）+ 分布条
  左：[按时间|按话题] [全部|待定|可用|废片|剪辑列表|不可用|未用]
      行：时间码 档位 话题 原文 依据 [过暗][抖动] [＋剪辑列表] [⊘]
  右：播放器（浏览小样，入点-0.3 → 出点+0.3）
      剪辑列表面板：6 段 · 2:40 / 3:00 ▓▓▓▓░ ；超出时「已超出目标 0:40，进片时全部保留，建议把目标改为 3:40」
  键盘：↓换段 → 空格听 → S 要；A 可用 D 废片 X 不可用 Z 撤销（更多→快捷键 可改）

④ 定标准：左小目录（分析对不对·可选 / 裁决待定 ✓ / 决策问题 2/4）
  1 分析对不对：摘要 + 话题 / 关键信息 / 说话人；改话题名、改某段档位
  2 裁决待定：还有 N 段待定 → 一次一段（原文 + 依据 + 播放器）A / D；「剩下的按 AI 建议」
  3 决策问题：每个选项下「选了会怎样」；「重新出题」；兜底题标明
  闸门：[确认，生成分镜表] → 待定没裁完先问 → 保存答案 + 重新选段 → 完成后进入 ⑤
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 首次打开 | 弹告知；Key 只 toast 提示 | 全屏告知 → 内联填两行 Key → 欢迎页 | D17 |
| 新建项目 | 只有素材 / 名称 / 时长 / 预设；建完停在项目里 | 两段（素材与成片 + 可展开的剪辑偏好）；「创建并开始分析」直接进 ② 并开跑 | §七.1；偏好写进 `project.json.calibration` |
| 处理素材 | 3 个入口 | 只有 ②：新建后自动开始；失败 / 中断在 ② 重试 / 继续 | ⚑P5 |
| 分析进度 | 弹窗滚日志 | ② 页 11 项人话进度 + 每项耗时 + 胶囊 | D11 |
| 缺 Key / 告知 / 编码器 | Key 弹设置；encoder 只记一行日志（KI-97） | ② 页内联「去填 Key」；encoder 弹说明 + 导出诊断包 | |
| 浏览素材 | 子窗口，★ 必留，标完不重选 | ③ 页内，S 放入剪辑列表，⊘ 不可用，变化使 ⑤「需要更新」 | KI-93 |
| 确认与提问 | 子窗口；确认后主页不刷新 | ④ 页内；闸门按钮保存并重新选段，完成后自动进入 ⑤ | §七.2 |
| 剪辑偏好 | 子窗口 | ① 新建弹窗 + 更多 → 项目设置；分析后改 → ② 需要更新 | FR-14 |
| 次要操作 | 侧栏 / 操作栏散落 | 更多菜单：项目设置、打开项目文件夹、清理缓存、设置 · API Key、快捷键、导出诊断包、关于 / 第三方许可 | §二 |
| 分镜表 / 版本 | 标签页 | ⑤ / ⑥ 暂住（D8） | M14 替换 |
| 废片 tab、文稿 tab、预览 tab | 有 | 删除；画面提示在 ③ 行内；文稿就是 ③ 列表；播放器在 ③ / ⑤ | §六 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `docs/界面流程-v2.md` | 全部 | 逐屏规格；§七 已定 |
| P0 | `docs/PRD-AI粗剪工具.md` | 110-135, 141-280, 368-395 | 流程、FR、术语 |
| P0 | `gui/server.py` | 49-74, 182-197, 239-253, 280-297, 334-367, 425-451, 497-543, 545-569 | 访问控制、页面门、任务起停、要搬走的路由、/api/new、/api/open |
| P0 | `gui/views.py` | 51-95 | `project_state` / `projects_list`（加 wizard、删 stages/junk） |
| P0 | `gui/payloads.py` | 全部 | ③④ 数据；KI-99 位置 35-39 |
| P0 | `gui/confirm.py` | 全部 | 存答案 + 起 select；要加 questions_digest 与「不改 confirmed」 |
| P0 | `gui/jobs.py` | 29-32, 121-148, 177-203, 429-441 | 任务表、job_view、TASK_LABELS、job_extra |
| P0 | `gui/settings.py` | 24-66 | PrepareBlocked / need |
| P0 | `pipeline/review.py` | 全部 | overrides 读写、锚点、apply |
| P0 | `pipeline/select.py` | 18-56, 310-475, 578-631 | 选段主流程、unused、run 写 selection.json |
| P0 | `aicut.py` | 66-82, 188-231, 485-510, 564-608, 638-651 | 文案常量、new、export、build、prepare |
| P0 | `gui/static/index.js`、`jobs.js`、`settings.js`、`browse.js`、`confirm.js`、`common.js` | 全部 | 要拆 / 迁移的前端 |
| P1 | `pipeline/readiness.py` | 全部 | PREPARE_STEPS（D10 改顺序） |
| P1 | `pipeline/applog.py` | 245-279 | timings.json 写法 |
| P1 | `pipeline/style.py` | 全部 | calibration 规范化 / directive |
| P1 | `pipeline/notices.py` | 1-30 | 指向旧入口的提示文案（KI-96） |
| P1 | `pipeline/classify.py` | 28-45, 93-124 | 文案；待定无建议字段（⚑P1） |
| P1 | `gui/static_files.py`、`packaging/ai-cut.spec:20-50` | 全部 | 白名单 / 打包清单 |
| P1 | `tests/conftest.py` | 64-140 | `gui_server`、`call`、`make_project` |
| P1 | `tests/test_frontend_js.py`、`tests/test_frontend_jobs.py` | 1-80 | node vm 夹具 |
| P1 | `tests/test_static_pages.py`、`tests/test_structure.py`、`tests/test_docs_consistency.py:178-183` | 全部 | 前端静态守卫、行数、快捷筛选守卫 |
| P2 | `gui/desktop.py`、`app/main.py`、`tests/test_server_desktop.py` | 全部 | M13d 删除 |
| P2 | `docs/GUI.md` | 全部 | 「剪辑师怎么用」与接口表要重写 |

## External Documentation

No external research needed — feature uses established internal patterns.（只用到浏览器内置 `KeyboardEvent.code`、`Element.scrollIntoView`、`HTMLMediaElement`；WKWebView / cookie 行为已在 M12 实测记录，见 `.claude/PRPs/plans/m12-wrapup.plan.md` External Documentation。）

KEY_INSIGHT: `KeyboardEvent.code` 表示物理键位，中文输入法 / 不同布局下稳定；`e.key` 在输入法组字时是 `"Process"`。
APPLIES_TO: D6、T16 快捷键。
GOTCHA: 输入法组字期间 `e.isComposing === true`，必须直接忽略；macOS 上 ⌘ 是 `e.metaKey`。

---

## Patterns to Mirror

### NAMING_CONVENTION（中文文案做模块常量；KI 编号进注释）
// SOURCE: gui/settings.py:14-21
```python
KEY_RE = re.compile(r"[\x21-\x7e]{8,512}")  # 可打印 ASCII、无空白

NEED_CONSENT_MSG = "请先阅读并确认数据外发说明"
NEED_KEYS_MSG = "还没有填写 API Key：{names}。请在「⚙ 设置 · API Key」里填写"
UNKNOWN_PROVIDER_MSG = "未知的 Key 类型"
```
// SOURCE: gui/static/jobs.js:6-16（前端同理：`COPY_*` 常量在文件顶部）
```js
/* 界面文案：产品可直接改这里 */
const JOB_TITLES = {prepare:'正在处理素材', build:'正在生成成片', select:'正在重新选段', ...};
const COPY_JOB_CANCEL = '取消任务';
```

### ROUTE_MODULE（新接口一律放子模块：返回 (状态码, JSON) 或 None）
// SOURCE: gui/maintenance.py:19-56
```python
def _resolve(name: str, resolve: Callable[[str], Path]) -> tuple[int, dict] | Path:
    try:
        return resolve(name)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:  # ProjectCorrupt 不是 ValueError：由 server 统一 409
        return 400, {"error": str(exc)}

def handle_get(path: str, query: dict, resolve: Callable[[str], Path]) -> tuple[int, dict] | None:
    if path != "/api/cache":
        return None
```
// SOURCE: gui/server.py:323-325, 418-423（server 里的接线方式）
```python
if (hit := settings.handle_get(p) or support.handle_get(p)
        or maintenance.handle_get(p, q, existing_project)) is not None:
    return self._json(hit[1], hit[0])
```

### ERROR_HANDLING（损坏 → 409，且 CorruptJSON 必须先于 ValueError 捕获）
// SOURCE: gui/server.py:334-343
```python
if p == "/api/browse":
    name = q.get("project", [""])[0]
    try:
        return self._json(payloads.browse(project_path(name), name))
    except FileNotFoundError as exc:
        return self._json({"error": str(exc)}, 404)
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return self._json({"error": str(exc)}, 409)
    except (ValueError, OSError) as exc:
        return self._json({"error": str(exc)}, 400)
```

### REPOSITORY_PATTERN（overrides：锁内读改写、原子落盘、不可变更新、锚点）
// SOURCE: pipeline/review.py:87-112
```python
def _write(workdir: Path, segment_id: str, fields: dict) -> dict:
    with _LOCK:
        data = load(workdir)
        segments = _scored_segments(workdir)
        if segments:
            data, stale = _rekey(data, segments)
            ...
        item = {**(data.get(segment_id) if isinstance(data.get(segment_id), dict) else {}),
                **fields, "at": _now()}
        ...
        data = {**data, segment_id: item}
        _save(workdir, data)
        return data

def set_must(workdir: Path, segment_id: str, flag: bool) -> dict:
    return _write(workdir, segment_id, {"must_keep": bool(flag)})
```

### SERVICE_PATTERN（选段：一次过滤，下游全部生效；结果写 selection.json）
// SOURCE: pipeline/select.py:326-333, 447-453, 619-631
```python
by_topic: dict[str, list[dict]] = {}
for s in segments:
    if s.get("level") != 3 and not s.get("must_keep"):
        continue
...
unused = [{"segment_id": s["id"], "topic": s.get("topic"), "reason": (...)}
          for s in segments
          if s.get("level") == 3 and s["id"] not in used_ids]
...
(out_dir / "selection.json").write_text(
    json.dumps(schema.stamp(result), ensure_ascii=False, indent=2), encoding="utf-8")
```

### GUARD_PATTERN（出片前护栏：切片之前检查，人话 die）
// SOURCE: aicut.py:579-585
```python
try:  # GL-25：切片（耗时）之前确认分镜表覆盖全部必留段
    missing = select.missing_must_keep(pdir / "work", shots)
except review.OverridesCorrupt as exc:
    die(str(exc))
if missing:
    die(select.describe_missing(missing, from_selection=shots_file != pdir / "shots.json"))
```

### CONFIG_FILE_PATTERN（本机配置：config_dir 下的小 JSON，原子写）
// SOURCE: pipeline/consent.py:32-48
```python
def _path() -> Path:
    return secrets.config_dir() / FILENAME

def accepted() -> bool:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("version") == CONSENT_VERSION
```

### LOGGING_PATTERN
// SOURCE: gui/maintenance.py:16, 55；gui/jobs.py:58-60
```python
LOG = applog.get("gui")
LOG.info("清理缓存：释放 %d 字节", freed)
LOG = applog.get("job")  # app.log 只记任务要点（起止、退出码、行数、错误行），不记普通输出（GL-19）
```
→ 新模块用 `applog.get("gui")`；**日志里不写原文 / 片名 / 偏好内容**，只写 id、计数、动作名。

### FRONTEND_PATTERN（CSP：事件委托 + esc()/num()；乐观更新失败回滚）
// SOURCE: gui/static/common.js:28-42；gui/static/browse.js:37-45, 139-145
```js
window.ACTIONS = Object.create(null);
document.addEventListener('click', ev => dispatchAction('data-act', ev));
...
async function toggleMust(id){
  const s = DATA.segments.find(x=>x.id===id); if(!s) return;
  const prev = s.must_keep;
  s.must_keep = !prev;
  render();
  if(!await postOrRollback('/api/browse/must', {project:PROJECT, id, must:s.must_keep}, ()=>{ s.must_keep = prev; })) render();
}
```

### TEST_STRUCTURE（服务端集成 / node vm 行为）
// SOURCE: tests/conftest.py:101-115；tests/test_confirm_flow.py:30-40
```python
def call(gs, method, path, body=None, *, token=True, headers=None, raw=None): ...
def make_project(root, name="p1", shots=None, **files): ...

def test_confirmed_save_starts_select_job(gui_server, monkeypatch):
    from gui import jobs
    pdir = _project(gui_server)
    seen = fake_command(monkeypatch, jobs, QUICK)
    status, data = _save(gui_server, answers={"q1": "全部"}, confirmed=True)
    assert status == 200 and data["job_id"]
```
// SOURCE: tests/test_frontend_jobs.py:16-48（最小 DOM 桩 + 多文件加载 + 返回 Promise）
```python
HARNESS = r"""
const vm = require('vm'); const fs = require('fs');
const [files, extraSrc, script] = JSON.parse(process.argv[1]);
...
for (const f of files) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, {filename: f});
"""
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `gui/project_routes.py` | CREATE | 从 server.py 搬出 /api/browse*、/api/confirm*、/api/calibrate；新增 /api/analysis、/api/browse/unusable、/api/project/settings、/api/topics/rename |
| `gui/wizard.py` | CREATE | `collect()` + 纯函数 `derive()`（步骤状态） |
| `gui/analysis.py` | CREATE | 纯函数 `progress()`（② 的 11 项人话进度） |
| `gui/prefs.py` | CREATE | `ui_prefs.json`：快捷键 + 项目栏固定；校验冲突；/api/prefs* |
| `pipeline/fingerprints.py` | CREATE | 分析输入、选段输入（分项）、文件摘要 |
| `pipeline/exclusions.py` | CREATE | 不可用：区间、分镜表重叠剔除、时间线命中 |
| `pipeline/topic_names.py` | CREATE | 话题显示名映射（⚑P3） |
| `pipeline/review.py` | UPDATE | `set_unusable`（与 must_keep 互斥 ⚑P9）、`unset_level`、`apply` 出 `unusable` |
| `pipeline/select.py` | UPDATE | 开头剔除不可用；`inputs` 指纹写进结果；文案改名（KI-96） |
| `pipeline/readiness.py` | UPDATE | PREPARE_STEPS 改顺序（D10）；`write_analysis_stamp` |
| `pipeline/notices.py`、`pipeline/classify.py`、`pipeline/clips.py`、`pipeline/cache.py`、`pipeline/understand_text.py`、`pipeline/encode.py` | UPDATE | 指向旧入口的提示文案改新位置（KI-96） |
| `aicut.py` | UPDATE | prepare 写分析戳；build 剔除不可用；export 拦截含不可用的旧版本（⚑P6）；文案 |
| `gui/server.py` | UPDATE | 路由委托给新模块；/api/new 收偏好；删搬走的路由 |
| `gui/views.py` | UPDATE | `project_state` 加 wizard / busy、删 stages / junk；`projects_list` 加当前步骤 |
| `gui/payloads.py` | UPDATE | ③：unusable、剪辑列表、说话人时长、显示名、KI-99；④：待定队列、证据 |
| `gui/confirm.py` | UPDATE | `questions_digest`；未传 `confirmed` 时保留原值（④ 草稿自动保存） |
| `gui/jobs.py` | UPDATE | TASK_LABELS 新名词；job_view 加 `elapsed_s`；`busy_view()` |
| `gui/settings.py` | UPDATE | 文案指向「更多 → 设置 · API Key」 |
| `gui/static_files.py` | UPDATE | 新静态文件；删旧页面 |
| `gui/static/index.html` | UPDATE（重写） | 新外壳骨架（CSS 外置） |
| `gui/static/app.css` | CREATE | 全部样式（从 index.html / browse.html 合并） |
| `gui/static/app.js` | CREATE | state、api、toast、modal、refresh、步骤路由、启动 |
| `gui/static/sidebar.js` | CREATE | 项目栏、48px 窄条、浮出、📌固定 |
| `gui/static/wizard.js` | CREATE | 步骤条、底部导航、横幅、更多菜单 |
| `gui/static/project-form.js` | CREATE | ① 新建弹窗、更多 → 项目设置 |
| `gui/static/step-analyze.js` | CREATE | ② 分析 |
| `gui/static/step-browse.js` | CREATE | ③ 摘要卡、分布条、列表、筛选、播放器 |
| `gui/static/cliplist.js` | CREATE | 剪辑列表面板、S/A/D/X 标记、撤销栈 |
| `gui/static/shortcuts.js` | CREATE | 默认键位、键位匹配、录制 / 冲突 / 恢复默认 |
| `gui/static/step-criteria.js` | CREATE | ④ 三块 + 闸门 |
| `gui/static/step-result.js` | CREATE | ⑤ 暂住：分镜表（从 index.js 迁出）+ 改目标时长 |
| `gui/static/step-export.js` | CREATE | ⑥ 暂住：版本卡片、生成新版本、Windows 导出（从 index.js / jobs.js 迁出） |
| `gui/static/jobs.js` | UPDATE | 任务胶囊 + 详情弹窗；KI-97 need 分流 |
| `gui/static/settings.js` | UPDATE | 首次打开全屏闸门；Key 弹窗入口改「更多」 |
| `gui/static/index.js` | DELETE（M13b） | 内容拆进上面各文件 |
| `gui/static/calibrate.{html,js}` | DELETE（M13b） | 并入项目设置 |
| `gui/static/browse.{html,js}` | DELETE（M13c） | 并入 ③ |
| `gui/static/confirm.{html,js}` | DELETE（M13d） | 并入 ④ |
| `gui/desktop.py` | DELETE（M13d） | /api/window 不再需要（D7） |
| `app/main.py` | UPDATE（M13d） | 去掉 set_window_opener |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 增删模块（`tests/test_structure.py` 守卫） |
| `tests/test_wizard_state.py` | CREATE | derive 表驱动、collect 读盘 |
| `tests/test_fingerprints.py` | CREATE | 指纹稳定性 |
| `tests/test_unusable.py` | CREATE | KI-93 端到端（review / select / exclusions / build / export / API） |
| `tests/test_analysis_progress.py` | CREATE | ② 进度纯函数 + /api/analysis |
| `tests/test_prefs.py` | CREATE | 快捷键校验 / 冲突 / 恢复默认 / 固定 |
| `tests/test_server_wizard.py` | CREATE | /api/state wizard、/api/project/settings、/api/new 偏好、/api/topics/rename |
| `tests/test_frontend_wizard.py` | CREATE | node：步骤条渲染与可点性、更多菜单、胶囊、首次闸门、KI-97 |
| `tests/test_frontend_browse.py` | CREATE | node：键位匹配、S 切换 + 回滚、撤销栈、输入框不触发、↑↓ |
| `tests/test_frontend_criteria.py` | CREATE | node：待定队列、闸门询问、自动保存不改 confirmed |
| `tests/test_terms.py` | CREATE | KI-96 名词守卫（前端字符串 + 后端界面文案常量） |
| `tests/test_static_pages.py`、`test_frontend_js.py`、`test_frontend_jobs.py`、`test_docs_consistency.py`、`test_server_media_state.py`、`test_server_desktop.py`（删）、`test_m12_wrapup.py`、`test_aicut_cli.py`、`test_review.py`、`test_select.py`、`test_confirm_flow.py`、`test_server_corrupt.py`、`test_server_hardening.py`、`test_server_security.py`、`test_server_save.py`、`test_views.py` | UPDATE | 跟随文件迁移 / 新名词 / 新字段 |
| `docs/GUI.md`、`docs/known-issues.md`（KI-93/96/97 状态、新增 KI-99）、`docs/go-live-blockers.md`（GL-26 进度）、`CHANGELOG.md`、`.claude/prds/ai-cut-go-live.prd.md` | UPDATE | 文档与登记 |

## NOT Building

- ⑤ 看结果的正式版（顶栏摘要、可改字幕的新分镜表、预览片、未采用清单与加回、恢复为 AI 选段、手动修改冲突询问）→ M14（GL-27、KI-95）。M13 只「暂住」旧视图（D8）。
- ⑥ 导出的正式版（每次导出 = 新版本、对比两版、回到这一版、打开剪映只在可用时出现）→ M14（KI-94、KI-98）。M13 的「打开剪映」原样搬进 ⑥。
- 闸门 B（预览片看过才能导出）→ M14。
- 手动改过分镜表后，④ 重新确认 / 改时长时的「覆盖 / 保留 / 取消」询问 → M14（KI-95）。M13 维持现状：手动分镜表不被覆盖，④ 页闸门旁一行说明。
- 任何选段 / 分析算法改动（含给待定段算「AI 建议档位」，⚑P1）。
- 单段改话题、话题合并 / 拆分（⚑P3）。
- 废片表（`junk_report`）列表视图：不再有「废片」tab，画面问题只以 ③ 行内「画面提示」出现（规格 §五）。
- 快捷键的组合键、按项目区分的快捷键、导入导出键位。
- 浏览器模式与 App 的界面差异处理以外的 Windows 端 App。
- 自动续跑被中断的分析（⚑P5）。

---

## Step-by-Step Tasks

> 每个 Task 先写测试（RED）→ 实现（GREEN）→ 重构。每个 **Commit** 边界都要走用户约定的闭环：`find . -name "*.tsbuildinfo" -delete`（本仓无 TS，可跳过）→ `uv run pytest` → `uv run pytest --cov`（≥80%）→ commit + push → 等 CI 绿。行号均为 HEAD `6579262` 的位置，前面的 Task 合入后会偏移——**按函数名 / 文本锚点定位**。

### ===== M13a 后端地基（界面不变，旧 UI 照常可用）=====

### Task 0: 基线护栏
- **ACTION**: 给 `tests/test_docs_consistency.py::test_quick_filters_match_gui` 加 `@pytest.mark.xfail(strict=True, reason="M13c：③ 快捷筛选落地后转绿（PRD v1.3 先于界面改了 FR-4）")`。
- **IMPLEMENT**: 只加装饰器。T15 去掉。
- **MIRROR**: —
- **GOTCHA**: `strict=True`：一旦意外变绿会报错，提醒去掉。
- **VALIDATE**: `uv run pytest -q` 全绿。

### Task 1: 路由搬家（行为不变，为 server.py 腾行数）
- **ACTION**: 新建 `gui/project_routes.py`，把 `server.py` 里 `/api/browse`（334-343）、`/api/calibrate` GET（345-356）与 POST（497-509）、`/api/confirm`（358-367）、`/api/confirm/answers`（511-520）、`/api/browse/level|must`（522-543）原样搬过去，按 `handle_get(path, q, project_path, existing_project)` / `handle_post(path, body, existing_project)` 返回 `(code, json)`；server 只留一行委托。
- **IMPLEMENT**:
  ```python
  # gui/project_routes.py
  def handle_get(path: str, q: dict, lookup: Callable[[str], Path],
                 existing: Callable[[str], Path]) -> tuple[int, dict] | None:
      route = GET_ROUTES.get(path)
      return route(q, lookup, existing) if route else None
  ```
  每个路由函数内部保持原有的异常顺序（`OverridesCorrupt` / `CorruptJSON` / `SchemaTooNew` 先于 `ValueError`）。`ProjectCorrupt` 不捕获（server `_safely` 统一 409）。
- **MIRROR**: ROUTE_MODULE、ERROR_HANDLING。
- **IMPORTS**: `from gui import confirm, payloads`；`from pipeline import review, schema, style`。
- **GOTCHA**: `tests/test_server_*` 有打桩 `server.<名字>` 的（如 `start_job`、`run_aicut`）——**/api/new 不搬**（`tests/test_server_target.py:11-23` 打桩 server 上的名字）；`confirm.save_answers` 内部用 `jobs.start_job`，测试打桩 `jobs`，不受影响。server.py 要降到 ~560 行。在 `packaging/ai-cut.spec` hiddenimports 加 `gui.project_routes`。
- **VALIDATE**: `uv run pytest tests/test_server_*.py tests/test_confirm_flow.py tests/test_structure.py -q`（全部原样通过，无需改测试）。

**Commit A1**：`refactor: move browse/confirm/calibrate routes out of gui/server.py`

### Task 2: KI-93 存储（review）
- **ACTION**: 先写 `tests/test_unusable.py::test_review_*`：
  1. `set_unusable(work, "S1", True)` → `load()["S1"]["unusable"] is True` 且有锚点；
  2. 对已 `must_keep` 的段 `set_unusable(True)` → `must_keep` 变 False（⚑P9 互斥），返回值告诉调用方 `{"cleared": "must_keep"}`；
  3. 对不可用段 `set_must(True)` → `unusable` 变 False，同样回报；
  4. `apply()` 出 `unusable: bool`；
  5. `unset_level(work, "S1")` 只删 `level` 字段，保留 `must_keep` / `unusable`；条目空了（只剩 `at`/`anchor`）就整条删；
  6. overrides 损坏时三个写函数都抛 `OverridesCorrupt` 且文件不变（同 `test_set_must_on_corrupt_keeps_file`）。
- **IMPLEMENT**（`pipeline/review.py`）：
  ```python
  EXCLUSIVE = {"must_keep": "unusable", "unusable": "must_keep"}  # ⚑P9：后按的生效

  def _set_flag(workdir, segment_id, field, flag) -> tuple[dict, str | None]:
      fields = {field: bool(flag)}
      other = EXCLUSIVE[field]
      cleared = None
      if flag:
          prev = load(workdir).get(segment_id) or {}   # 只读判断；真正的写在 _write 的锁里
          if prev.get(other):
              fields[other] = False
              cleared = other
      return _write(workdir, segment_id, fields), cleared

  def set_must(workdir, segment_id, flag) -> dict:          # 签名不变（现有调用方只要 dict）
      return _set_flag(workdir, segment_id, "must_keep", flag)[0]
  def set_unusable(workdir, segment_id, flag) -> tuple[dict, str | None]: ...
  def set_must_reporting(workdir, segment_id, flag) -> tuple[dict, str | None]: ...
  def unset_level(workdir, segment_id) -> dict: ...  # 锁内：按 _resolve_keys 找到当前 id 对应的键（同 clear 的 KI-85 处理）
  ```
  `apply()` 增加 `item["unusable"] = bool(ov.get("unusable", False))`。
- **MIRROR**: REPOSITORY_PATTERN（不可变更新、锁内读改写）。
- **GOTCHA**: 互斥判断要在 `_LOCK` 内完成才没有竞态 → 把「读 prev」挪进 `_write` 的锁里：给 `_write` 加可选参数 `exclusive: str | None`，在锁内看旧值决定是否顺带写 False。旧裁决 id 可能被重定位：判断 prev 用 `_rekey` 之后的 `data`。
- **VALIDATE**: `uv run pytest tests/test_unusable.py -k review tests/test_review.py -q`

### Task 3: KI-93 选段排除 + 出片剔除 + 旧版本导出拦截
- **ACTION**: 先写测试：
  1. `select.select()`：不可用的可用段不进 `shots`、不进 `unused`、`stats.usable_total` 不算它；不可用段同时 `must_keep`（手改 JSON 造的）→ 不进片且不报「必留未进片」；指定原话只命中不可用段 → 不强拉，出现找不到原话的警告；
  2. `exclusions.spans(work)` → 不可用段的 `(start, end)` 列表（overrides 损坏 → 抛 `OverridesCorrupt`）；
  3. `exclusions.drop_overlapping(shots, spans)` → `(kept, dropped_ids)`，重叠 > `UNUSABLE_OVERLAP_S=0.1` 才算；
  4. `exclusions.timeline_hits(work, timeline)` → 时间线里与不可用段重叠的镜头数（`video[].in/out` 是素材时间）；
  5. `aicut build`：`shots-selected.json` 含不可用段 → 剔除后出片，输出 `[!] 已自动剔除 1 个含「不可用」片段的镜头：S03`；全部被剔除 → `[x]` 退出码 1；
  6. `aicut export --timeline output/v1/timeline.json`：v1 含不可用段 → `[x] 这一版含 1 段已标为不可用的片段，不能再导出；请生成新版本`（⚑P6）；
  7. `POST /api/browse/unusable {project,id,unusable:true}`：200 `{ok, segment, removed_shots, cleared, clip_list}`；手动 `shots.json` 里重叠的镜头被移除（文件被原子重写，其它镜头不动）；没有手动分镜表时 `removed_shots == []`、不新建 `shots.json`；坏 overrides → 409；坏 id → 400。
- **IMPLEMENT**:
  - `pipeline/exclusions.py`：
    ```python
    UNUSABLE_OVERLAP_S = 0.1   # D12：与不可用片段重叠超过这么多秒的镜头整镜剔除（隐私优先）
    DROPPED_WARNING = "已自动剔除 {n} 个含「不可用」片段的镜头：{ids}"
    ALL_DROPPED = "分镜表里的镜头都含「不可用」片段，剔除后没有可出的镜头：回到 ③ 看素材检查标记，或在 ⑤ 看结果重新选段"
    EXPORT_BLOCKED = "这一版含 {n} 段已标为不可用的片段，不能再导出；请生成新版本"
    def spans(workdir: Path) -> list[tuple[float, float, str]]   # 读 scored + overrides（review.apply）
    def drop_overlapping(shots, spans) -> tuple[list[dict], list[str]]
    def timeline_hits(workdir, timeline: dict) -> int
    ```
  - `pipeline/select.py::select()` 第一行：`segments = [s for s in segments if not s.get("unusable")]`（D13）。
  - `aicut.cmd_build`：在 `missing_must_keep` 检查**之后**、磁盘预检之前：
    ```python
    shots, dropped = exclusions.drop_overlapping(shots, exclusions.spans(pdir / "work"))
    if dropped:
        warn(exclusions.DROPPED_WARNING.format(n=len(dropped), ids="、".join(dropped[:5])))
        if not shots:
            die(exclusions.ALL_DROPPED)
    ```
  - `aicut.cmd_export`：`restore_missing` 之前 `if n := exclusions.timeline_hits(pdir / "work", schema.read_json(timeline)): die(EXPORT_BLOCKED.format(n=n))`。
  - `gui/project_routes.py`：`/api/browse/unusable` → `review.set_unusable` → 若 `shots.json` 存在：`schema.read_shots` → `drop_overlapping` → 有变化才 `schema.write_json`（保留 `project` / `source` 字段，同 `server.py:483-485` 的写法）→ 返回。
- **MIRROR**: GUARD_PATTERN；`/api/shots` 的写法（`gui/server.py:467-486`）。
- **IMPORTS**: `from pipeline import exclusions`（aicut.py 的 import 行、spec hiddenimports）。
- **GOTCHA**: `exclusions.spans` 读不到 `segments_scored.json`（纯手工流程）→ 返回 `[]`，不能 die；`missing_must_keep` 在剔除**之前**跑，否则「必留段被剔除」会先触发必留报错——但 ⚑P9 互斥保证正常数据里必留段不会不可用；手改 JSON 的冲突交给 select 已排除。aicut.py 净增 ≤ 10 行（750 → ~760）。
- **VALIDATE**: `uv run pytest tests/test_unusable.py tests/test_select.py tests/test_aicut_build.py tests/test_aicut_must_keep.py tests/test_e2e_draft.py -q`

**Commit A2**：`feat(ki-93): unusable marking end to end in storage, selection, build and export`

### Task 4: 指纹（pipeline/fingerprints.py）
- **ACTION**: 先写 `tests/test_fingerprints.py`：
  1. `file_digest(missing) == ""`，内容相同 → 相同，改一字节 → 不同；
  2. `overrides_digest`：只改 `at` / `anchor` 不变；`must_keep` True→False 与「从没标过」相同；`level` 改了 → 变；损坏 → `"corrupt"`；
  3. `selection_inputs(work, cfg)` 分项 keys = `{"scored","overrides","answers","target","lines"}`；答案顺序不同（dict 键序）结果相同；
  4. `analysis_inputs(cfg)` = `{"directive": style.directive(cal), "preset": ...}`；
  5. `changed(saved, now) -> list[str]`：返回不同的分项名（`saved` 为 None / 非 dict → `[]`）。
- **IMPLEMENT**:
  ```python
  DIGEST_LEN = 12
  CORRUPT = "corrupt"
  SELECTION_KEYS = ("scored", "overrides", "answers", "target", "lines")
  def file_digest(path: Path) -> str
  def overrides_digest(workdir: Path) -> str          # review.load → OverridesCorrupt → CORRUPT
  def answers_digest(workdir: Path) -> str            # brief_answers.json["answers"]，json.dumps(sort_keys=True)
  def selection_inputs(workdir: Path, cfg: dict) -> dict[str, str]
  def analysis_inputs(cfg: dict) -> dict[str, str]
  def changed(saved: object, now: dict) -> list[str]
  ```
- **MIRROR**: `pipeline/understand_text.py:319-323`（`hashlib.sha1(...).hexdigest()` 指纹写法）。
- **GOTCHA**: `selection_inputs` 的 `target` 必须与 `aicut.cmd_select` 传给 `select.run` 的完全同源：`int(cfg.get("target_duration") or 175)`；`--target` 改时长时 cmd_select 先算选段、成功后才写 project.json（`aicut.py:466-468`）→ `select.run` 写指纹时要用**传进来的** target，而不是重读 project.json。
- **VALIDATE**: `uv run pytest tests/test_fingerprints.py -q`

### Task 5: 写戳（select / prepare / confirm）+ PREPARE_STEPS 顺序
- **ACTION**: 先写测试：
  1. `select.run(...)` 结果与 `selection.json` 都含 `inputs`，且等于 `fingerprints.selection_inputs(work, {target_duration: target, calibration: cal})`；
  2. `aicut prepare` 成功末尾写 `work/analysis_inputs.json == fingerprints.analysis_inputs(cfg)`；任何一步失败 → 不写（旧戳保持）；
  3. `confirm.save_answers` 写 `questions_digest`；body 里**没有** `confirmed` 键 → 保留文件里原来的 `confirmed`、不起任务；`confirmed: false` 仍是显式取消（旧测试 `test_plain_save_does_not_start_job` 不变）；
  4. `tests/test_aicut_cli.py::STAGES` 改成新顺序（D10），`test_prepare_*` 全绿。
- **IMPLEMENT**:
  - `select.run(..., calibration, target)`：`result = {**result, "inputs": fingerprints.selection_inputs(out_dir, {"target_duration": target, "calibration": calibration})}` 后再写盘。注意 `select.run` 先写 `selection.json` 再写 `shots-selected.json`，指纹算的是**选段开始前**的输入——在调用 `select()` 之前算好 `inputs`，避免选段过程中有人改 overrides 造成「刚选完就过期」被掩盖。
  - `pipeline/readiness.py`：`PREPARE_STEPS = ("ingest", "junk", "transcribe", "analyze", "scenes", "quality", "text", "score", "summary", "questions", "select", "brief")`；`ANALYSIS_STAMP = "analysis_inputs.json"`；`def write_analysis_stamp(work, cfg) -> None`（`schema.write_json`）。
  - `aicut.cmd_prepare` 循环结束后：`readiness.write_analysis_stamp(pdir / "work", cfg(pdir))`。
  - `gui/confirm.py::save_answers`：`confirmed = bool(body["confirmed"]) if "confirmed" in body else bool(stored.get("confirmed"))`；写入 `"questions_digest": fingerprints.file_digest(work / "questions.json")`；只有 `body.get("confirmed") is True` 才起 select。
- **MIRROR**: `gui/confirm.py:20-39`。
- **GOTCHA**: `stored` 读 `brief_answers.json` 要用 `schema.read_json(..., default={})` 并在 `CorruptJSON` 时当 `{}`（KI-49 同款），否则坏答案文件让草稿保存 409；`cmd_prepare` 要在 for 循环之后、`ok(...)` 之前写戳（失败时 `die` 已经 SystemExit，自然不写）。
- **VALIDATE**: `uv run pytest tests/test_select.py tests/test_aicut_cli.py tests/test_confirm_flow.py tests/test_fingerprints.py -q`

### Task 6: ② 分析进度纯函数（gui/analysis.py）
- **ACTION**: 先写 `tests/test_analysis_progress.py`（只喂 dict，不碰盘）：
  1. 全新项目、无任务 → 11 项全 `waiting`，`done=0, total=11, complete=False`；
  2. 任务在跑、`timings` 里 ingest / junk 的 `started` ≥ 任务开始、`asr.wav` 完整、`transcript_raw` 不在 → ingest/proxy/audio `done`，asr `running`；
  3. 上次跑过（started < 任务开始）但产物在 → 仍是 `done`（跳过的步骤）；
  4. 任务结束（不在跑）、`timings.text.ok == False` → text `failed`，`failed={"key":"text","label":"AI 理解对话","reason":<传入的最后一条 [x] 行或 None>}`；
  5. 画面检查：`scenes` 完成、`quality` 失败但 `ok=True`（warn 跳过）→ `done`；
  6. `seconds` 对合并项求和（transcribe 只记在 asr 上，audio 显示 None）；
  7. `complete` 与 `wizard` 的 `analysis_done` 同一判据。
  再写集成：`GET /api/analysis?project=p1` → 200；不存在 → 404；坏项目名 → 400。
- **IMPLEMENT**:
  ```python
  # (key, 人话, 依赖的 PREPARE_STEPS, 完成判据)；顺序 = D10 执行顺序 = 规格顺序
  ANALYSIS_STEPS = (
      ("ingest", "读取素材", ("ingest",), "materials"),
      ("proxy", "生成浏览小样", ("junk",), "proxy"),
      ("audio", "抽音轨", ("transcribe",), "wav"),
      ("asr", "云端转写", ("transcribe",), "segments"),
      ("voice", "声音分析", ("analyze",), "audio_json"),
      ("visual", "画面检查", ("scenes", "quality"), "visual"),
      ("text", "AI 理解对话", ("text",), "text_json"),
      ("score", "判定档位", ("score",), "scored"),
      ("summary", "写内容摘要", ("summary",), "summary"),
      ("questions", "准备决策问题", ("questions",), "questions"),
      ("select", "初步选段", ("select", "brief"), "selection"),
  )
  NOTICE = "分析大约 10–15 分钟，可以关掉窗口，回来接着跑"
  def facts(pdir: Path, cfg: dict, job: dict | None) -> dict      # 读盘：产物布尔 + timings + job
  def progress(f: dict) -> dict                                    # 纯函数
  ```
  `job` 来自 `jobs.project_job_detail(name)`（新增：`{id, task, started, status, last_error}`，`last_error` = 日志里最后一条 `[x]` 行去前缀）。路由放 `gui/project_routes.py`：`GET /api/analysis`。
- **MIRROR**: `gui/views.py:51-84`（读盘只用于显示：`jload` 宽松读）。
- **GOTCHA**: `timings.json` 的 `started` 是 UTC ISO 字符串（`applog.py:270`），任务 `started` 是 `time.time()` → 统一转 epoch 比较；`junk` 阶段里先生成小样再做废片检测：小样完整但 junk 失败 → proxy 仍 `done`（以产物为准）；`complete_or_adopt(..., source=material)` 绑定素材（KI-62），素材换过要显示未完成。
- **VALIDATE**: `uv run pytest tests/test_analysis_progress.py -q`

### Task 7: 任务表补充（elapsed / busy / 新名词）
- **ACTION**: 先写测试（`tests/test_server_jobs.py` 增补）：`job_view` 含 `elapsed_s`（运行中递增、结束后固定）；`jobs.busy_view()` 无任务 → None，有任务 → `{id, task, project, label}`；`TASK_LABELS` 用新名词。
- **IMPLEMENT**: `PUBLIC_FIELDS` 不变，`job_view` 额外算 `elapsed_s = round((ended or now) - started)`（`_finish_job` 记 `ended`）；`TASK_LABELS = {"prepare": "分析", "build": "生成新版本", "select": "重新选段", "export": "生成 Windows 剪映包", "questions": "重新出题"}`；`project_job_detail()`（T6 用）。
- **MIRROR**: `gui/jobs.py:130-148`（锁内显式挑字段，不序列化 Popen）。
- **GOTCHA**: `JOB_CONFLICT_MSG` 用 `TASK_LABELS` 拼「已有任务在运行：{project} · {task}」，改名后旧断言（grep `处理素材` 的 4 个测试文件）同步改。
- **VALIDATE**: `uv run pytest tests/test_server_jobs.py tests/test_frontend_jobs.py tests/test_server_export.py tests/test_app_main.py -q`

### Task 8: 步骤状态（gui/wizard.py）+ /api/state
- **ACTION**: 先写 `tests/test_wizard_state.py`，**表驱动**覆盖「步骤状态判定」一节每一格：
  | 用例 | facts | 期望 |
  |---|---|---|
  | 新建未分析 | 全 False/None | ② available、③④⑤⑥ locked（hint 含「② 分析」）、next=analyze |
  | 分析中 | running | 同上，next=analyze |
  | 分析完成 | analysis_done | ②③ done、④ available、⑤⑥ locked、next=criteria |
  | 偏好改过 | done + stamp≠inputs | ② stale、action=reanalyze |
  | 无戳旧项目 | done + stamp None | ② done（不判过期） |
  | 已确认 | + confirmed | ④ done、⑤⑥ available、next=result |
  | 题目重出 | confirmed + 两个 digest 不等 | ④ stale |
  | 旧项目 | legacy（未确认 + 有版本）⚑P2 | ④ done、legacy=True |
  | 标记改了 | confirmed + selection saved≠now（overrides） | ⑤ stale、banner 含「素材标记改过了」、action=reselect |
  | 多项改了 | overrides + answers | banner 两个原因按 SELECTION_KEYS 顺序 |
  | 选段无指纹 | saved None | ⑤ available |
  再写 `collect()` 读盘测试（`make_project` + 文件）与 `/api/state` 集成：返回 `wizard`、`busy`；`projects_list` 每项有 `step: {"n": 4, "label": "定标准"}`。
- **IMPLEMENT**:
  ```python
  STEPS = (("new", 1, "新建"), ("analyze", 2, "分析"), ("browse", 3, "看素材"),
           ("criteria", 4, "定标准"), ("result", 5, "看结果"), ("export", 6, "导出"))
  LOCKED_HINT = "先完成「{n} {label}」"
  STALE_ANALYZE = "剪辑偏好或预设改过了 · 重新分析（只重跑 AI 理解及之后的环节，会重新调用 AI）"
  STALE_CRITERIA = "决策问题重新生成过 · 请重新作答并确认"
  STALE_RESULT_REASONS = {"overrides": "素材标记改过了", "answers": "答案改过了", "target": "目标时长改过了",
                          "lines": "剪辑偏好里的指定原话改过了", "scored": "分析结果更新了"}
  STALE_RESULT_ACTION = " · 重新选段"
  LEGACY_NOTE = "这个项目在改版前已出过片，没经过定标准；需要时可以在这里确认一次"
  def collect(pdir: Path, cfg: dict, name: str, *, digests: bool = True) -> dict
  def derive(f: dict) -> dict
  def step_label(name_or_dict) -> dict   # 项目栏用
  ```
  `views.project_state` 加 `"wizard": wizard.derive(wizard.collect(pdir, cfg, name))`、`"busy": jobs.busy_view()`；`views.projects_list` 加 `"step"`（`digests=False`，损坏的 project.json → `step=None`）。
- **MIRROR**: `gui/views.py:51-95`（`jload` 宽松读、损坏不让列表崩）。
- **GOTCHA**: `collect` 里所有读都必须「坏了也不抛」（项目列表不能因一个项目坏掉而 500，`test_projects_list_tolerates_corrupt_project_json`）；`stages` / `junk` 在本 Task **保留**（旧 UI 还在用），M13b T9 再删。
- **VALIDATE**: `uv run pytest tests/test_wizard_state.py tests/test_views.py tests/test_server_media_state.py -q`

### Task 9a: 偏好接口（gui/prefs.py）
- **ACTION**: 先写 `tests/test_prefs.py`：
  1. 没文件 → `GET /api/prefs` 给默认 `{"shortcuts": DEFAULTS, "sidebar_pinned": False, "actions": [...带中文名]}`；
  2. `POST {"shortcuts": {"toggle_list": "KeyK"}}` → 保存后读回；
  3. 冲突：`{"toggle_list": "KeyA"}`（A 是可用）→ 400，`error` 含「S 放入/移出剪辑列表」与「A 标为可用」两个动作名，文件不变；
  4. 非法键（`"Escape"`、`"Meta+KeyS"`、`"<script>"`、`3`）→ 400；未知动作 → 400；
  5. `POST /api/prefs/reset {"what": "shortcuts"}` → 回默认，`sidebar_pinned` 保留；
  6. `{"sidebar_pinned": true}` 单独保存不动快捷键；
  7. 文件损坏 → GET 给默认 + `warning`，POST 覆盖修复（只是界面偏好，不像 overrides 那样不能丢）；
  8. 文件在 `secrets.config_dir()` 下（测试夹具已隔离到 tmp）。
- **IMPLEMENT**:
  ```python
  FILENAME = "ui_prefs.json"
  PREFS_VERSION = 1
  ACTIONS = {"play": "播放 / 暂停", "prev": "上一段", "next": "下一段", "toggle_list": "放入 / 移出剪辑列表",
             "mark_usable": "标为可用", "mark_waste": "标为废片", "mark_unusable": "标为不可用", "undo": "撤销"}
  DEFAULT_SHORTCUTS = {"play": "Space", "prev": "ArrowUp", "next": "ArrowDown", "toggle_list": "KeyS",
                       "mark_usable": "KeyA", "mark_waste": "KeyD", "mark_unusable": "KeyX", "undo": "KeyZ"}
  KEY_CODE_RE = re.compile(r"Key[A-Z]|Digit[0-9]|Space|Arrow(?:Up|Down|Left|Right)|"
                           r"Comma|Period|Slash|Semicolon|Quote|Bracket(?:Left|Right)|Minus|Equal|Backquote|Backslash")
  CONFLICT_MSG = "「{key}」已经用于「{other}」，不能同时用于「{this}」"
  def validate_shortcuts(raw: object) -> dict[str, str]   # 合并默认后整体校验；ValueError(人话)
  def handle_get(path) / handle_post(path, body)
  ```
- **MIRROR**: CONFIG_FILE_PATTERN、`gui/settings.py:108-121`（POST_ROUTES 表）。
- **GOTCHA**: 校验在「合并默认后」做：用户只改一个键时也可能撞上另一个默认键；`json` 里键名只认 `ACTIONS`；写盘用 `schema.write_json`（原子 + 0600 不需要，界面偏好不敏感，但沿用同一写法）。
- **VALIDATE**: `uv run pytest tests/test_prefs.py -q`

### Task 9b: 新建带偏好 + 项目设置 + 话题显示名
- **ACTION**: 先写 `tests/test_server_wizard.py`：
  1. `/api/new` 带 `calibration={"tone":"info","audience":"家长","must_lines":"第一句\n第二句"}` → `run_aicut` 参数含 `--tone=info`、`--audience=家长`、`--must-lines=第一句\n第二句`；`must_lines` 4 行 → 400「最多 3 句」；`tone` 非法 → 400；不带 `calibration` → 参数与现在完全一样（`tests/test_server_target.py` 不改）；
  2. `POST /api/project/settings {project, title, preset, calibration}` → `project.json` 更新（`title` 走 `schema.check_title`；`preset` 必须在 `preset_names()`，同时把 `platform` 换成新预设的；**不动** `target_duration`，KI-92）；返回 `{ok, project, wizard}`；分析完成的项目改 `tone` 后 `wizard` 里 ② 变 `stale`；
  3. `POST /api/topics/rename {project, name, display}` → `work/topic_names.json`；`display` 空串 = 恢复原名；超过 20 字 → 400；`/api/browse` 与 `/api/confirm` 的 topic 字段出显示名、带 `topic_raw`。
- **IMPLEMENT**: server.py `/api/new` 增 ~10 行（`calibration` → `style.normalize` 前先校验 tone ∈ `style.TONES`、`must_lines` 行数 ≤ `MUST_LINES_MAX = 3`）；`/api/project/settings` 与 `/api/topics/rename` 放 `gui/project_routes.py`，写 project.json 用 `schema.update_project`（加锁读改写，KI-51）；`pipeline/topic_names.py`：`load(work) / rename(work, raw, display) / display(name, mapping)`。
- **MIRROR**: `gui/server.py:425-451`（/api/new 的白名单与 `--x=value` 写法）、`gui/server.py:497-509`（calibrate 保存）。
- **GOTCHA**: `--must-lines=` 的值以 `-` 开头也安全（`--x=value` 形式，`server.py:439`）；`preset_names()` 与 `PRESETS` 在 server 上，project_routes 需要它 → 作为参数传入（测试打桩 `server.PRESETS`，`tests/conftest.py:121-127`）；server.py 净行数仍须 ≤ 650。
- **VALIDATE**: `uv run pytest tests/test_server_wizard.py tests/test_server_target.py tests/test_structure.py -q`

### Task 10: KI-96 后端界面文案
- **ACTION**: 先写 `tests/test_terms.py::test_backend_copy_points_to_new_ui`：import 下列常量，断言都不含 `OLD_ENTRY_NAMES = ("「浏览素材」", "「确认与提问」", "「改目标时长」", "① 处理素材", "「处理素材」", "② 生成成片", "「生成成片」", "⚙ 设置 · API Key", "左下角", "★")`，且「必留」只以「必留话题」出现：
  `notices.TEXT_INCOMPLETE_NOTICE / SUMMARY_FALLBACK_NOTICE / QUESTIONS_FALLBACK_NOTICE / REMEDY_*`、`classify.TEXT_INCOMPLETE_ERROR / LEGACY_FAILED_WARNING / AUDIO_MISSING_WARNING`、`select.MUST_KEEP_* / ANSWER_UNMATCHED / OVERRIDES_STALE_WARNING / BUDGET_LEGACY_WARNING`、`settings.NEED_KEYS_MSG`、`server.INTERNAL_ERROR_MSG`、`jobs.NO_TIMELINE_MSG`、`clips` 第 39 行文案、`cache.CLIPS_LABEL`、`understand_text.ANNOTATION_RETRY_HINT`、`encode.ENCODER_UNAVAILABLE`、`aicut.TEXT_PARTIAL_WARNING / PREPARE_KEYS_MISSING / MUST_KEEP_OVER_HINT`。
- **IMPLEMENT**（新文案，界面位置一律用「② 分析」「③ 看素材」「④ 定标准」「⑤ 看结果」「⑥ 导出」「更多 → …」）：
  - 「重新点「① 处理素材」」→「在「② 分析」点「重新分析」」；
  - 「点「改目标时长」重新选段会重建」→「在「⑤ 看结果」改目标时长或重新选段会重建」；
  - 「到「确认与提问」页重新作答」→「到「④ 定标准」重新作答」；
  - 「在「浏览素材」取消★」→「在「③ 看素材」把它移出剪辑列表」；「必留段 / 必留内容」→「剪辑列表里的片段 / 剪辑列表」；
  - 「重新「② 生成成片」会重建这一版」→「在「⑥ 导出」生成新版本」；
  - 「「⚙ 设置 · API Key」」→「「更多 → 设置 · API Key」」；「左下角「导出诊断包」」→「「更多 → 导出诊断包」」。
- **MIRROR**: NAMING_CONVENTION。
- **GOTCHA**: 这些字符串被断言的现有测试（`grep -rn "处理素材\|浏览素材\|确认与提问\|生成成片\|改目标时长" tests` 共 8 个文件）同步改断言；`select.MUST_KEEP_REASON = "剪辑师标记必留"` 会进 selection.json 的 reason → 改「剪辑列表里的片段」。CLI 也显示同样文案，允许（命令行用户同样看得懂位置）。
- **VALIDATE**: `uv run pytest tests/test_terms.py tests/test_m8_review.py tests/test_server_config.py tests/test_clips_restore.py tests/test_e2e_draft.py -q`

**Commit A3**：`feat(gl-26): wizard state, fingerprints, analysis progress, prefs and settings APIs`（M13a 结束：旧界面照常可用，新接口全部有测试）

### ===== M13b 新外壳 + ① ② + ⑤⑥ 暂住 + KI-97 =====

### Task 11: 前端拆分与新外壳
- **ACTION**: 先写 / 改测试：
  - `tests/test_static_pages.py`：`PAGES` 只剩 `index.html`（+ M13c/d 前还在的 `browse.html`、`confirm.html`）；新守卫：`index.html` 依次加载 `common.js` → … → `app.js`（`app.js` 最后，所有 `ACTIONS` 注册都在其前）；`index.html` 不含 `<style>`（全在 `app.css`）；`ALL_SOURCES` 自动覆盖新 `.js`；**每个 `gui/static/*.js` ≤ 400 行**（新守卫 `test_static_js_files_are_focused`）；白名单 = 实际文件集合（新守卫：`STATIC_FILES == {p.name for p in STATIC.iterdir() if p.suffix in {'.html','.js','.css'} and p.name != 'prototype.html'}`）。
  - `tests/test_frontend_js.py`：`_shot_id_src` 改读 `step-result.js`；`_project_switch_src` 改读 `app.js`（`selectProject / flushPendingSave / refreshOrWarn / showProjectError / refresh / saveShots / postShots / scheduleSave`），断言改为「打不开的项目：步骤条清空、主区显示错误卡片」（不再有 `#actions` / `#tabs`）。
  - `tests/test_frontend_wizard.py`（新，HARNESS 同 `test_frontend_jobs.py`）：
    1. `renderSteps(wizard, viewing)`：locked 步骤有 `aria-disabled="true"` 且 `title` = hint、点它不切换；done 有 ✓；stale 有 ⚠ 和 `.stale`；viewing 的那步 `.current`；
    2. `renderBanner(step)`：stale 时出横幅，`action=reselect` 的按钮 `data-act="reselect"`，文字过 `esc()`；
    3. 底部导航：③ 时「下一步：去定标准 →」可点；② 未完成时不可点；
    4. 更多菜单：无项目时只有「设置 · API Key / 快捷键 / 导出诊断包 / 关于」，有项目时 7 项且顺序同规格；
    5. 项目栏：`renderProjects` 每项「名称 · ④ 定标准」；有项目时 `#app.in-project` → 窄条；`pinned` 时不收起。
- **IMPLEMENT**:
  - `index.html`：`<link rel="stylesheet" href="/static/app.css">`；骨架 = `#rail`（项目栏）+ `#topbar`（项目名 / 步骤条 `#steps` / 胶囊 `#chip` / `#more`）+ `#banner` + `#stage`（当前步骤页面）+ `#nav`（上一步 / 下一步）+ 现有 `#mask/#modal/#toast`；脚本顺序：`common.js, jobs.js, settings.js, support.js, shortcuts.js, sidebar.js, wizard.js, project-form.js, step-analyze.js, step-browse.js, cliplist.js, step-criteria.js, step-result.js, step-export.js, app.js`（M13b 时 browse/cliplist/criteria 文件先建成只含暂住卡片的小文件）。
  - `app.js`：从 `index.js` 迁 `$ / state / toast / api / fmt* / refresh / refreshOrWarn / showProjectError / selectProject / saveShots 队列 / showModal / closeModal / logLine`；新增 `state.view`（正在看的步骤）、`go(step)`（locked 拒绝并 toast hint）、`STEP_VIEWS = {analyze: viewAnalyze, browse: viewBrowse, ...}`、`render()`；启动：`checkFirstRun()` 通过后 `loadProjects()`，有 `#project=` hash 时进入并 `go(wizard.next)`。
  - `wizard.js`：`renderSteps / renderBanner / renderNav / openMore / MORE_ITEMS`；横幅动作 `reanalyze`（起 prepare）、`reselect`（起 select）。
  - `sidebar.js`：`renderProjects / setRail / togglePin`（`POST /api/prefs {sidebar_pinned}`），`mouseenter/mouseleave` 在 `#rail` 上（不是内联事件，`addEventListener`）。
  - `app.css`：合并 `index.html` / `browse.html` 的 `:root` 变量与样式；新增 `.rail{width:48px}`、`.rail.open{width:240px;position:absolute}`、`.step.locked/.done/.stale/.current`、`.chip`、`.banner`。
  - 删 `index.js`、`calibrate.html/js`（白名单同步）。
- **MIRROR**: FRONTEND_PATTERN；`gui/static/index.js:105-128`（refresh 序号防乱序，原样搬）。
- **IMPORTS**: 静态文件白名单 `gui/static_files.py`。
- **GOTCHA**: CSP 禁内联事件 → 所有 `onclick=` 改 `data-act`（`index.js:74,159` 仍有 `li.onclick` / `t.onclick` 这种 DOM 属性赋值——不违反 CSP，但新代码统一走 `data-act`）；`test_no_inline_event_handlers` 会扫 `.js` 模板里的 `<… onX=`；每个 data-* 动态值过 `num()` / `esc()`（`test_data_attributes_never_take_raw_interpolation`）；`#project=` 只读一次，**不**做 hash 路由（KI-57：创建后只切到新项目）。
- **VALIDATE**: `uv run pytest tests/test_static_pages.py tests/test_frontend_js.py tests/test_frontend_wizard.py -q`

### Task 12: 首次打开闸门 + 更多菜单里的设置 / 快捷键入口
- **ACTION**: 先写 `tests/test_frontend_wizard.py::test_first_run_*`：`/api/config` 无 consent → 主区渲染告知（`#stage` 含两条外发流、按钮「我知道了，继续」），没有「暂不使用」；点继续 → 渲染两行 Key；一个 Key 未配置时「进入剪辑台」按钮 disabled；两个都 configured（含 `source:'env'`）→ 渲染欢迎页；`/api/config` 失败 → 显示「剪辑台服务没有响应」+ 重试，不进欢迎页。
- **IMPLEMENT**（`settings.js`）：`renderFirstRun(cfg)`（全屏，复用 `consentHtml` 与 `settingsRowsHtml`）、`checkFirstRun()` 返回 Promise<bool>；Key 弹窗 `openSettings` 保留（更多菜单调用）；`COPY_KEYS_MISSING_HINT` 改「更多 → 设置 · API Key」。
- **MIRROR**: `gui/static/settings.js:41-69, 140-146`。
- **GOTCHA**: 明文 Key 只在输入框，保存成功即清空（`settings.js:2` 的约定不能破）；首次闸门里保存 Key 后要重新 `GET /api/config` 判断两个都齐了才放行。
- **VALIDATE**: `uv run pytest tests/test_frontend_wizard.py -k first_run tests/test_frontend_jobs.py -k settings -q`

### Task 13: ① 新建弹窗 + 项目设置
- **ACTION**: 先写 node 测试（`project-form.js`）：
  1. 新建弹窗两段；「剪辑偏好」默认折叠，展开后 tone 单选默认「信息」⚑P4；
  2. `readCalibration()`：must_lines 去空行，> 3 行 → toast「必须保留的原话最多 3 句」并不提交；
  3. `createAndAnalyze()`：先 `POST /api/new`（body 含 `calibration`），成功后 `POST /api/job {task:'prepare'}`，然后 `go('analyze')`；`/api/new` 失败 → 弹窗不关、toast 原因、不起任务；`/api/job` 409 `need=keys` → 仍然 `go('analyze')`（② 页内联去填 Key），**不弹**设置弹窗；
  4. 项目设置弹窗：预填 title / preset / calibration；`tone=balanced` 时出现第三个选项「均衡（改版前的设置）」⚑P4；保存 → `POST /api/project/settings` → 用返回的 `wizard` 重绘步骤条（② 可能变 ⚠）。
- **IMPLEMENT**: 从 `index.js:467-535` 迁 `durationFields / readDuration / syncTarget / pickFile`；新 `openNew / createAndAnalyze / openProjectSettings / saveProjectSettings`；文案常量 `COPY_NEW_SECTION_MATERIAL='素材与成片'`、`COPY_NEW_SECTION_PREFS='剪辑偏好（可跳过）'`、`COPY_TONE_INFO='信息'`、`COPY_TONE_EMOTION='情绪'`、`COPY_TONE_BALANCED_LEGACY='均衡（改版前的设置）'`、`COPY_AUDIENCE='片子给谁看'`、`COPY_MUST_LINES='必须保留的原话（每行一句，最多 3 句）'`、`COPY_CREATE='创建并开始分析'`。
- **MIRROR**: `gui/static/index.js:487-535`（KI-92：换预设不覆盖手填时长 `state.npTouched`）。
- **GOTCHA**: 「① 新建」步骤在项目内点击 = 打开项目设置（已完成的步骤「能回去看、能改」）；`/api/new` 后 `loadProjects()` 再 `selectProject(name)`（KI-57），不要用 hash 跳转。
- **VALIDATE**: `uv run pytest tests/test_frontend_wizard.py -k "new or settings" tests/test_server_wizard.py -q`

### Task 14: ② 分析页 + 任务胶囊 + KI-97
- **ACTION**: 先写 node 测试：
  1. `viewAnalyze(progress)`：11 行，状态图标 / 耗时（`fmtMinSec`）；顶部 `NOTICE`；
  2. 失败：显示「「AI 理解对话」失败：<reason>」+「重试（从这一步接着跑）」+「导出诊断包」；
  3. 未完成也不在跑（⚑P5）：「上次分析没跑完（已完成 6/11）」+「继续分析」；
  4. 起任务 409 `need=consent` → 本页内联告知 + 「我知道了，继续」；`need=keys` → 内联两行 Key + 「去填 Key」直接在本页；`need=encoder` → **弹窗**：标题「这台 Mac 暂时不能分析」、正文 = 服务端 message、按钮「导出诊断包」「知道了」（KI-97）；未知 need → 同 encoder 弹窗；
  5. 胶囊：`renderChip(job, progress)` →「正在分析 6/11 · 3 分钟」；`select` →「正在重新选段…」；失败 →「失败 · 查看」（`.chip.failed`）；无任务 → 隐藏；点胶囊 → `openJobDetail()`（原任务弹窗：日志 / 取消 / 重试 / 诊断包）；
  6. 有任务时所有 `[data-starts-job]` 按钮 disabled + `title`=「正在{label}，完成后再试」；
  7. 分析任务完成且正在看 ② → 自动 `go('browse')`；④ 闸门起的 select 完成 → `go('result')`。
- **IMPLEMENT**:
  - `step-analyze.js`：`viewAnalyze`、`pollAnalysis()`（任务在跑时每 `ANALYSIS_POLL_MS=1500` `GET /api/analysis`，离开 ② 停止）、`startAnalysis()`。
  - `jobs.js`：保留 `startJob / pollJob / cancelJob / retryJob / attachJob`；`jobModal` 改为 `openJobDetail`（不自动弹，除非调用方要求）；新增 `renderChip`、`busyGuard()`；`onJobStartError` 按 `d.need` 分流：`consent`/`keys` 交给调用方回调（② 内联），`encoder` 与其它 → `showNeedModal(e.message)`。`versionExportHtml / exportVersion / revealExport` 迁到 `step-export.js`。
  - `JOB_TITLES / JOB_DONE` 新名词：`{prepare:'正在分析', build:'正在生成新版本', select:'正在重新选段', export:'正在生成 Windows 剪映包', questions:'正在重新出题'}`。
- **MIRROR**: `gui/static/jobs.js:57-143`（轮询、连续失败判中断、取消 / 重试按钮）。
- **GOTCHA**: `onJobDone` 里「剪辑列表合计超过目标就弹改时长」（`jobs.js:137`）保留：select / prepare 完成且 `selection.over_target` → 打开改时长弹窗（⑤ 的「改」M14 再挪）；轮询 `/api/analysis` 与 `/api/job/<id>` 不要同时各跑一套计时器——② 页只轮询 `/api/analysis`（它带 job 状态），胶囊用 `/api/job`；切项目时两者都按序号作废（`stateSeq` 同款）。
- **VALIDATE**: `uv run pytest tests/test_frontend_wizard.py tests/test_frontend_jobs.py tests/test_analysis_progress.py -q`

### Task 14b: ⑤⑥ 暂住 + ③④ 暂住卡片 + 删旧字段
- **ACTION**: 先写 node 测试：⑤ 渲染分镜表（`viewShots` 原测试迁过来：GL-22 选中行不重绘）+「改目标时长」按钮；⑤ stale 时横幅「素材标记改过了 · 重新选段」；有手动分镜表时横幅下加一行「你手动改过分镜表，重新选段只更新建议，不会覆盖它（M14 会提供选择）」；⑥ 渲染版本卡片、「生成新版本（导出到 Mac 剪映）」、Windows 导出、在访达中显示、打开剪映；③④ 显示暂住卡片 + 「打开看素材窗口」/「打开定标准窗口」（走现有 `/api/window`）。服务端：`/api/state` 不再有 `stages`、`junk`（`tests/test_server_media_state.py` 改为断言 `/api/analysis` 的 audio 项）。
- **IMPLEMENT**: `step-result.js` ← `index.js:161-246, 273-384, 443-465`（shotbar、pick、mark、playSel、viewShots、保存队列调用、move/dup/del/addBlank/sortShots、openTarget/saveTarget）；`step-export.js` ← `index.js:398-441` + `jobs.js:145-170`；build 弹窗文案：标题「生成新版本」，勾选项「这次只生成预览片，不导出到剪映（剪映开着时用）」；`views.project_state` 删 `stages`、`junk`。
- **MIRROR**: 原代码原样迁移，只改文案与容器 id。
- **GOTCHA**: 保存队列（`saveQ`）、`flushPendingSave` 在 `app.js`，⑤ 只调用；切步骤离开 ⑤ 时也要 `flushPendingSave()`（原来只在切项目时 flush）。
- **VALIDATE**: `uv run pytest tests/test_frontend_js.py tests/test_frontend_jobs.py tests/test_static_pages.py tests/test_server_media_state.py -q`

**Commit B1**：`feat(gl-26): wizard shell with sidebar, step bar, more menu, task chip, first run, new project and analysis steps`

### ===== M13c ③ 看素材 =====

### Task 15: ③ 数据（payloads）+ KI-99 + 快捷筛选守卫转绿
- **ACTION**: 先写测试：
  1. KI-99：没有 `shots.json`、有 `work/shots-selected.json` → 被选中的段 `inCut=True`；两者都有 → 以手动为准；
  2. `segments[]` 有 `unusable`、`must_keep`、`visual_flags`、`topic`（显示名）与 `topic_raw`；
  3. `clip_list = {ids:[按 at 升序], count, total, target, over, suggested}`：合计 ≤ 目标 → `over=False`；超出 → `suggested` 向上取整到 `select.TARGET_ROUND_STEP`；不可用段不计；
  4. `speakers = [{name, seconds}]` 按时长降序；
  5. 去掉 `tests/test_docs_consistency.py` 的 xfail，守卫改为：`step-browse.js` 里 `FILTERS` 常量的中文标签序列 == FR-4「快捷筛选：」行在「（」之前的部分按「 / 」切分。
- **IMPLEMENT**: `payloads.browse` 改 `shots = manual or selected`（同 `views.py:66-67`）；新增纯函数 `clip_list(segments, overrides, target)`、`speakers(segments)`；`docs/known-issues.md` 登记 KI-99（状态写「M13c 修复」）。
- **MIRROR**: `gui/views.py:66-75`；`select._must_keep_report`（建议时长取整）。
- **GOTCHA**: `in_cut` 的重叠阈值仍是 1.0 秒（`payloads.py:37-39`），不要和 D12 的 0.1 秒混用——前者是「算不算用到了」，后者是隐私剔除。
- **VALIDATE**: `uv run pytest tests/test_server_wizard.py -k browse tests/test_docs_consistency.py tests/test_server_corrupt.py -q`

### Task 16: 快捷键（shortcuts.js）+ 剪辑列表与标记（cliplist.js）
- **ACTION**: 先写 `tests/test_frontend_browse.py`（node）：
  1. `keyAction(ev, map)`：`{code:'KeyS'}` → `toggle_list`；`isComposing` → null；`target` 是 INPUT / TEXTAREA / SELECT / contentEditable → null；`metaKey+KeyZ` → `undo`（别名）；其它带修饰键 → null；
  2. `findConflict(map, action, code)` → 冲突动作名；
  3. 录制弹窗：按下已占用的键 → 提示「「A」已经用于「标为可用」」且不保存；「恢复默认」→ `POST /api/prefs/reset`；服务端 400 → 显示服务端 error；
  4. `toggleList(seg)`：乐观更新 → `POST /api/browse/must`；失败回滚并 toast；成功用返回的 `clip_list` 重绘面板、行内出现「已在剪辑列表」；返回 `cleared:'unusable'` → toast「已取消不可用并放入剪辑列表」⚑P9；
  5. `markUnusable(seg)`：`removed_shots` 非空 → toast「已从分镜表移除 2 镜」；`cleared:'must_keep'` → toast「已移出剪辑列表并标为不可用」；
  6. 撤销栈（⚑P8）：S → Z 恢复原状（再发一次请求）；A（原无人工档位）→ Z 发 `level:null`；栈上限 50；切项目清空；
  7. 面板：超出时文案「已超出目标 0:40，进片时全部保留，建议把目标改为 3:40」（数字过 `fmtLong`）。
- **IMPLEMENT**:
  - `shortcuts.js`：`DEFAULT_SHORTCUTS`（与服务端同值，测试断言两边一致：读 `gui/prefs.py` 常量比对）、`KEY_LABELS = {Space:'空格', ArrowUp:'↑', ArrowDown:'↓', ...}`、`keyAction`、`findConflict`、`loadPrefs()`、`openShortcutEditor()`（逐项「按下新键」录制）；`document.addEventListener('keydown', onKey)` 只在 `state.view==='browse'` 时分发。
  - `cliplist.js`：`toggleList / markLevel / markUnusable / undo / renderClipPanel`；API：`/api/browse/must`、`/api/browse/level`（`level:null` = 撤销人工档位，T2 的 `unset_level`）、`/api/browse/unusable`；每次成功后用响应里的 `wizard` 更新步骤条（⑤ 可能变 ⚠）。
  - `project_routes`：`/api/browse/must`、`/api/browse/level` 响应补 `segment`、`clip_list`、`wizard`、`cleared`（保持 `ok:true`，旧断言不破）；`level: null` → `review.unset_level`。
- **MIRROR**: FRONTEND_PATTERN（`browse.js:37-45,132-145` 的乐观更新与回滚）。
- **GOTCHA**: 空格要 `preventDefault()`（否则滚动页面）；按键自动重复（`ev.repeat`）对 S / A / D / X 忽略，避免长按来回切；`/api/browse/*` 的并发：同一段连续快速按 S，后一次请求要等前一次回来（每段一个 Promise 链，同 `saveQ` 思路）。
- **VALIDATE**: `uv run pytest tests/test_frontend_browse.py tests/test_prefs.py tests/test_unusable.py -q`

### Task 17: ③ 页面（step-browse.js）
- **ACTION**: 先写 node 测试：摘要卡（一句话、关键信息点时间码跳转、说话人「名字 · 3:20」）；分布条按档位上色、点击跳转；视图切换按时间 / 按话题（组头「可用 N · 待定 N · 废片 N · 可用时长 1:20」）；7 个筛选的过滤结果（未用 = `!inCut`、剪辑列表 = `must_keep`、不可用 = `unusable`；待定 / 可用 / 废片 **不含**不可用段）；行内画面提示标签 `{soft:'虚焦', shaky:'抖动', dark:'过暗', still:'静止'}`；当前段 `.current`、已在列表 `.in-list` 可叠加；↑↓ 在**当前筛选结果**里移动并 `scrollIntoView({block:'nearest'})`；点行 = 当前段 + 播放（入点 −0.3 → 出点 +0.3，D15）；所有 LLM / 文稿字段过 `esc()`。
- **IMPLEMENT**: 从 `browse.js` 迁 `renderSummary / density / render / row / jump`，改为渲染进 `#stage`；常量 `FILTERS = [['all','全部'],['pending','待定'],['usable','可用'],['waste','废片'],['list','剪辑列表'],['unusable','不可用'],['unused','未用']]`、`PAD_S = 0.3`；底部导航「下一步：去定标准 →」恒可点；删 `browse.html/js`、③ 暂住卡片。
- **MIRROR**: `gui/static/browse.js:46-131`。
- **GOTCHA**: 140 段要滚得动（FR-4 ≥ 50fps）：筛选 / 切当前段**不重绘整表**，只切 class（GL-22 同理）；播放器停止用 `timeupdate` 监听而不是 `setInterval` 全局变量（`browse.js:129-130` 的 `window._t` 去掉）；`playQuietly` 处理 play() reject（`common.js:25`）。
- **VALIDATE**: `uv run pytest tests/test_frontend_browse.py tests/test_static_pages.py -q`

**Commit C1**：`feat(gl-26,ki-93): step 3 browse with clip list, unusable marking and custom shortcuts`

### ===== M13d ④ 定标准 + 收尾 =====

### Task 18: ④ 数据
- **ACTION**: 先写测试：`/api/confirm` 增加 `pending`（level==2 且非不可用，按时间排序，含 `id/start/end/text/reason/topic`）、`topics`（显示名 + 计数）、`speakers`、`legacy`、`blocks = {analysis:'optional', pending: n==0, questions: 每题有答案}`（⚑P7）；没有 questions.json → 仍是 404（④ 页显示「还没有决策问题」+「重新出题」）。
- **IMPLEMENT**: `payloads.confirm` 复用 T15 的 `speakers()`、`topic_names.display`；`pending` 用 `review.apply`（与 ③ 同一份裁决）。
- **MIRROR**: `gui/payloads.py:79-93`。
- **GOTCHA**: `answers_unreadable`（KI-49）路径保持：答案读不出 → 页面照常打开、清空答案。
- **VALIDATE**: `uv run pytest tests/test_server_wizard.py -k confirm tests/test_confirm_flow.py tests/test_server_corrupt.py -q`

### Task 19: ④ 页面（step-criteria.js）+ 闸门
- **ACTION**: 先写 `tests/test_frontend_criteria.py`（node）：
  1. 左小目录三项状态（⚑P7）；
  2. 「分析对不对」：话题列表可改名（`POST /api/topics/rename`，失败回滚）、关键信息点击跳播、说话人时长；某段改档位（下拉，走 `/api/browse/level`）；
  3. 「裁决待定」：一次一段，A / D（用自定义快捷键表里的 `mark_usable / mark_waste`）后自动下一段；播放器播当前段；「剩下的按 AI 建议」→ 确认框文案 ⚑P1 → 不发任何写请求，只把队列标为已处理（本地）并显示「剩下 N 段先不进片」；
  4. 「决策问题」：多选 / 单选不可变更新（KI-49，`confirm.js:90-99` 原逻辑）；每次点选项 **自动保存草稿**（`POST /api/confirm/answers` 不带 `confirmed` 键，T5）；「重新出题」走 `startJob('questions')`；兜底题标「（兜底模板生成）」；旧题提示（KI-86 `stale_hint`）；
  5. 闸门：待定 > 0 → `confirm()` 式弹窗「还有 N 段待定，按 AI 建议处理？」「按 AI 建议，继续」「回去裁决」；继续 → `POST {confirmed:true}` → 返回 `job_id` → 胶囊跟踪 → 完成后 `go('result')`；返回 `job_error`（有别的任务）→ 横幅「答案已保存，但没能开始重新选段：…」；有手动分镜表 → 闸门按钮下一行说明（D8，KI-95 前的现状）；
  6. 删 `confirm.html/js` 后 `tests/test_static_pages.py` 里 confirm 相关守卫（`test_llm_fields_escaped_in_confirm`、`test_confirm_uses_as_list_and_immutable_pick`、`test_confirm_error_toast_stays_longer`、`test_confirm_page_offers_regenerate_for_stale_questions`）改指 `step-criteria.js`。
- **IMPLEMENT**: 从 `confirm.js` 迁 `renderQuestions / pick / save / regenerate / lastProblem`；轮询改用 `jobs.js` 的胶囊；文案常量 `COPY_GATE='确认，生成分镜表'`、`COPY_GATE_ASK='还有 {n} 段待定，按 AI 建议处理？'`、`COPY_AI_REST='剩下的按 AI 建议'`、`COPY_AI_REST_DONE='剩下 {n} 段按 AI 建议：先不进片（之后仍可在 ③ 看素材里改）'`、`COPY_REGEN='重新出题'`、`COPY_FALLBACK_Q='（兜底模板生成）'`。
- **MIRROR**: `gui/static/confirm.js:75-136`。
- **GOTCHA**: 草稿保存要防抖（`ANSWER_SAVE_DEBOUNCE_MS=500`）并在点闸门前 flush，避免「确认」请求先于最后一次草稿到达；④ 的 A / D 与 ③ 共用 `cliplist.js` 的 `markLevel`（同一份撤销栈只在 ③ 生效，④ 不提供 Z——规格只给 ③ 写了撤销）。
- **VALIDATE**: `uv run pytest tests/test_frontend_criteria.py tests/test_confirm_flow.py tests/test_static_pages.py -q`

### Task 20: 删除子窗口机制
- **ACTION**: 删 `POST /api/window`（`gui/desktop.py` 整个文件）、`server.set_window_opener`、`app/main.py:44-46`；删 `tests/test_server_desktop.py`；`tests/test_app_main.py` 去掉 opener 断言；`tests/test_m12_wrapup.py` 里用 `/static/browse.html?project=p1&nonce=…` 的重定向测试改用 `/index.html?x=1&nonce=…`（验证保留其它查询参数）；`packaging/ai-cut.spec` 去掉 `gui.desktop`；`tests/test_structure.py` 自动校验。
- **IMPLEMENT**: 纯删除 + 测试迁移。
- **MIRROR**: —
- **GOTCHA**: `server.py:422` 的 `desktop.handle_post(...)` 一并删；`gui/server.py` 顶部 import 列表同步；`_page()` 对任意白名单 html 的 nonce 兑换逻辑不变（只剩 index.html）。
- **VALIDATE**: `uv run pytest tests/test_app_main.py tests/test_m12_wrapup.py tests/test_structure.py tests/test_server_security.py -q`

### Task 21: KI-96 前端名词守卫
- **ACTION**: `tests/test_terms.py::test_static_ui_strings_use_prd_terms`：读 `gui/static/*.html|js|css`，去掉 `//…`、`/*…*/`、`<!--…-->` 注释后，断言不出现 `BANNED_UI = ("待判断", "素材台账", "策划分派单", "只出预览", "选段表", "第一版", "已出片", "生成成片", "原片", "代理片", "分析代理", "必留", "★", "浏览素材", "确认与提问", "处理素材")`；并断言步骤名序列 `①新建 ②分析 ③看素材 ④定标准 ⑤看结果 ⑥导出` 出现在 `wizard.js` 的常量里（与服务端 `wizard.STEPS` 一致）。
- **IMPLEMENT**: 按守卫逐个改；「浏览小样」替代「代理」；`step-analyze.js` 的人话标签读服务端 `/api/analysis`，前端不再维护一份。
- **MIRROR**: `tests/test_static_pages.py:13-26`（读页面源码的方式）。
- **GOTCHA**: 「必留话题」是允许的内部概念，但 UI 里本来就不该出现 → 直接禁「必留」整词；CSS 类名、data-act 名是英文，不受影响。
- **VALIDATE**: `uv run pytest tests/test_terms.py -q`

### Task 22: 文档与登记
- **ACTION**: `docs/GUI.md` 重写「一、剪辑师怎么用」（按六步）、接口表（加 /api/analysis、/api/browse/unusable、/api/project/settings、/api/topics/rename、/api/prefs*；删 /api/window）、「界面改哪里」（文件地图）；`docs/known-issues.md`：KI-93 / KI-96 / KI-97 状态「已修复（M13）」+ 提交号留待回填、KI-99 新登记并标修复；`docs/go-live-blockers.md` GL-26 状态「①–④ 与框架已完成（M13），⑤⑥ 随 M14」；`CHANGELOG.md` 一节；PRD 第 13 行加 report 链接（实现报告由 `/prp-implement` 生成）。
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py -q`

### Task 23: 全量验证 + 实机走查
- `uv run pytest -q`、`uv run pytest --cov -q`（≥ 80%）；`wc -l aicut.py gui/server.py gui/static/*.js`（≤ 800 / ≤ 650 / ≤ 400）。
- 按下文 Manual Validation 逐屏走查（App 与浏览器模式各一遍）。

**Commit D1**：`feat(gl-26,ki-96): step 4 criteria gate, remove sub-windows, unify terms`
**Commit D2**：`docs: M13 wizard (GUI.md, known issues, blockers, changelog)`

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| derive 新建 | 全空 facts | ② available，③–⑥ locked，next=analyze | |
| derive 偏好改过 | stamp≠inputs | ② stale + reanalyze | 是 |
| derive 无戳 | stamp None | ② done | 是（旧项目） |
| derive 旧项目 | legacy | ④ done，⑤⑥ available | 是（⚑P2） |
| derive ⑤ 多原因 | overrides+answers 变 | banner 两个原因、固定顺序 | 是 |
| overrides 指纹 | 只改 at / anchor | 不变 | 是 |
| overrides 指纹 | must_keep True→False | 等于从未标过 | 是 |
| progress 跳过的步骤 | started<任务开始，产物在 | done | 是 |
| progress transcribe 拆分 | wav 完整、raw 无、在跑 | audio done / asr running | 是 |
| review 互斥 | must 后 unusable | must_keep=False，cleared | 是（⚑P9） |
| select 不可用 | 可用段标不可用 | 不在 shots / unused | |
| select 不可用 + must_keep（手改） | 两者都 True | 不进片、不报必留缺失 | 是 |
| build 剔除 | selected 含不可用 | [!] 剔除并出片 | |
| build 全剔除 | 全部重叠 | [x] 退出 1 | 是 |
| export 拦截 | 旧版本含不可用 | [x]（⚑P6） | 是 |
| prefs 冲突 | toggle_list=KeyA | 400，两动作名 | 是 |
| prefs 非法键 | Escape / 组合 / 非字符串 | 400 | 是 |
| confirm 草稿 | 无 confirmed 键 | 保留原 confirmed，不起任务 | 是 |
| browse KI-99 | 只有 shots-selected | inCut 正确 | 是 |
| clip_list 超出 | 合计>目标 | suggested 取整到 5 秒 | 是 |
| 前端 keyAction | 输入框 / 组字 / 修饰键 | null | 是 |
| 前端撤销 | A 后 Z（原无人工档位） | 发 level:null | 是 |
| 前端闸门 | 待定>0 | 先问再提交 | |
| 名词守卫 | 全部静态源 | 无禁用词 | |

### Edge Cases Checklist
- [x] 空项目列表（欢迎页）/ 空分镜表 / 没有决策问题 / 没有待定
- [x] 140+ 段列表滚动与 ↑↓（只切 class 不重绘）
- [x] 非法输入：坏项目名、坏 id、非法 level、4 句原话、非法键位、超长话题名
- [x] 并发：同段连续按 S（单通道）；分析进行中标记 ③（overrides 照写，select 在末尾读）；另一项目任务在跑时起任务（胶囊 + 置灰 + 409 兜底）
- [x] 损坏：overrides.json / brief_answers.json / ui_prefs.json / project.json / timings.json
- [x] 服务端无响应（首次闸门、胶囊轮询连续失败判中断）
- [x] 权限 / 安全：新接口全部经 `_deny_reason`（Host / Origin / JSON / cookie），不新增例外；所有动态文本过 `esc()`

---

## Validation Commands

### Static Analysis
```bash
uv run python -m py_compile gui/*.py pipeline/*.py aicut.py
node --check gui/static/*.js
```
EXPECT: 无语法错误（本仓未配置 lint / 类型检查，见 CLAUDE.md）

### Unit Tests
```bash
uv run pytest tests/test_wizard_state.py tests/test_fingerprints.py tests/test_unusable.py tests/test_analysis_progress.py tests/test_prefs.py tests/test_server_wizard.py tests/test_terms.py -q
uv run pytest tests/test_frontend_wizard.py tests/test_frontend_browse.py tests/test_frontend_criteria.py tests/test_frontend_js.py tests/test_frontend_jobs.py tests/test_static_pages.py -q
```
EXPECT: 全部通过（node 缺失时前端测试 skip——CI 有 node）

### Full Test Suite
```bash
uv run pytest -q
uv run pytest --cov -q
wc -l aicut.py gui/server.py gui/static/*.js
```
EXPECT: 无回归；覆盖率 ≥ 80%；aicut.py ≤ 800、server.py ≤ 650、每个前端 JS ≤ 400

### Browser Validation
```bash
AI_CUT_DATA_DIR=<tmp> AI_CUT_CONFIG_DIR=<tmp>/cfg uv run python gui/server.py --port 8899 --open
uv run python app/main.py
```
EXPECT: 下列手工走查全部通过

### Manual Validation（App 与浏览器模式各一遍；用一条 5–10 分钟真实素材 + 一个改版前的旧项目）
**首次打开（§四）**
- [ ] 清空配置目录启动：全屏告知两条外发流 →「我知道了，继续」→ 两行 Key；只填一个时进不去；两个都填好进欢迎页
- [ ] 之后在「更多 → 设置 · API Key」能改；清掉一个 Key 后，② 起分析时本页内联「去填 Key」

**框架（§二）**
- [ ] 没有项目：项目栏不隐藏，主区欢迎页大按钮「新建项目」
- [ ] 进入项目：项目栏收成 48px（☰ + 项目首字）；悬停 / 点 ☰ 浮出 240px；移开收起；📌固定后不再收起，重启 App 仍固定
- [ ] 项目列表每项「名称 · 当前步骤」
- [ ] 步骤条：未到灰字不可点、悬停「先完成 X」；当前主色实底；已完成 ✓ 可回看；需要更新 ⚠ 橙色可点
- [ ] 更多菜单 7 项、顺序同规格；无项目时只有全局项
- [ ] 底部导航「← 上一步」「下一步：X →」；闸门步骤的下一步就是闸门按钮
- [ ] 任务胶囊「正在分析 6/11 · 3 分钟」，点开看日志 / 取消；有任务时其它启动按钮置灰并提示「正在 X，完成后再试」

**① 新建（§三.①）**
- [ ] 两段；偏好可展开、可跳过，tone 默认「信息」；原话第 4 行被拒
- [ ] 「创建并开始分析」后直接到 ② 且已开跑
- [ ] 「更多 → 项目设置」改偏好 → ② 变 ⚠，横幅「重新分析」；改片名不影响任何步骤状态
- [ ] 旧项目 tone=均衡：项目设置里出现「均衡（改版前的设置）」（⚑P4）

**② 分析（§三.②）**
- [ ] 11 项人话进度，顺序 = 读取素材 → 生成浏览小样 → 抽音轨 → 云端转写 → … → 初步选段，每项有状态和耗时
- [ ] 顶部「分析大约 10–15 分钟，可以关掉窗口，回来接着跑」
- [ ] 断网让云端转写失败：显示失败步骤 + 原因 + 「重试（从这一步接着跑）」+「导出诊断包」；重试后已完成的步骤秒过
- [ ] 分析中关 App 再开：② 显示「上次分析没跑完（已完成 N/11）」+「继续分析」（⚑P5）
- [ ] 让 VideoToolbox 预检失败（或打桩）：弹「这台 Mac 暂时不能分析」+ 导出诊断包（KI-97）
- [ ] 完成后自动进入 ③

**③ 看素材（§三.③）**
- [ ] 摘要卡：一句话、关键信息（点时间码跳播）、说话人及时长；分布条按档位上色、点击跳转
- [ ] 按时间 / 按话题；7 个筛选结果正确（未用 = 不在当前分镜表，含没有手动分镜表的情况，KI-99）
- [ ] 行：时间码、档位、话题、原文、依据、画面提示标签、「＋ 剪辑列表」、⊘
- [ ] 点行试听：入点前 0.3 秒到出点后 0.3 秒
- [ ] ↓ 换段 → 空格听 → S 要：行内「已在剪辑列表」+ 面板计数跳动；Z / ⌘Z 撤销；在输入框里打字快捷键不生效
- [ ] 剪辑列表面板：段数、合计 / 目标、进度条、按加入顺序、可跳转、可 ✕；超出时「已超出目标 0:40，进片时全部保留，建议把目标改为 3:40」
- [ ] X 标不可用：手动分镜表里对应镜头被移除并提示；剪辑列表里的段按 X 会移出列表（⚑P9）
- [ ] 标记后 ⑤ 变 ⚠「素材标记改过了 · 重新选段」，不自动重选
- [ ] 「更多 → 快捷键」：逐项录制；与已有键冲突被拒并说明；「恢复默认」；换端口 / 重启后仍生效

**④ 定标准（§三.④）**
- [ ] 左小目录三块完成情况（⚑P7）
- [ ] 分析对不对：改话题名（③④ 显示新名，⚑P3）、改某段档位
- [ ] 裁决待定：一次一段 A / D、播放；「剩下的按 AI 建议」（⚑P1 文案）
- [ ] 决策问题：每个选项下「选了会怎样」；「重新出题」；兜底题标明；选项改了自动保存（刷新后还在）
- [ ] 待定没裁完点「确认，生成分镜表」→ 先问「还有 N 段待定，按 AI 建议处理？」；确认后胶囊显示重新选段，完成后自动进入 ⑤
- [ ] 确认后再回 ④ 改答案 → ⑤ 变 ⚠「答案改过了」

**⑤⑥ 暂住（D8）**
- [ ] ⑤ 分镜表可编辑、设入出点、试听；「改目标时长」；⚠ 横幅「重新选段」可用
- [ ] ⑥ 生成新版本（导出到 Mac 剪映）、Windows 剪映包、在访达中显示、打开剪映；剪映里能打开并播放
- [ ] 含不可用片段的旧版本点 Windows 导出 → 被拦并说明（⚑P6）；新生成的版本里没有不可用片段

**旧项目**
- [ ] 改版前已出过片的项目：直接可进 ⑤⑥，④ 顶部提示（⚑P2）；没有戳的项目 ② 不显示 ⚠

---

## Acceptance Criteria
- [ ] GL-26（①–④ 与框架）：每个可点按钮在当时都能成功或说明原因（PRD 成功指标「点了才发现不能用 = 0 处」，按上表走查）
- [ ] KI-93：不可用段不进候选、不进未采用清单、新版本不出现；手动分镜表标记即移除；旧版本导出被拦（⚑P6）
- [ ] KI-96：`tests/test_terms.py` 绿；步骤名与 PRD §12 一致
- [ ] KI-97：`need=encoder`（及未知 need）有界面说明 + 诊断包入口
- [ ] `test_quick_filters_match_gui` 转绿且去掉 xfail
- [ ] `uv run pytest` 全绿；`--cov` ≥ 80%；行数守卫通过
- [ ] App 在 M13a / M13b / M13c / M13d 每个提交后都能从新建走到剪映打开

## Completion Checklist
- [ ] 新接口都在路由子模块里，返回 (状态码, JSON)；损坏 → 409、CorruptJSON 先于 ValueError
- [ ] 中文文案全部是命名常量（Python 模块常量 / JS 文件顶部 `COPY_*`）
- [ ] 不可变更新（review / prefs / 前端 state 更新都返回新对象）
- [ ] 前端：无内联脚本与 on* 属性；data-* 过 `num()`/`esc()`；新文件进白名单
- [ ] 日志不含原文 / 片名 / 偏好内容
- [ ] 测试沿用 `gui_server` / `call` / `make_project` / node vm 夹具
- [ ] 文档：GUI.md、known-issues（KI-93/96/97 状态、KI-99）、go-live-blockers（GL-26）、CHANGELOG、PRD
- [ ] 没有做 NOT Building 里的任何一项

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 前端重写面大，node vm 只能测函数，测不到布局 / 焦点 / 视频播放 | 高 | 中 | 关键交互全部抽成纯函数测；每个子切片结束做一次真机走查（上表）；GL-22 类「不重绘」规则写进测试 |
| server.py 只剩 4 行余量 | 高 | 低 | T1 先搬路由腾 ~90 行；新接口一律进子模块；结构守卫兜底 |
| 指纹误报「需要更新」（如 overrides 里的锚点被重定位改写） | 中 | 中 | 指纹只取 level / must_keep / unusable；锚点、时间戳排除；fingerprints 单测覆盖 |
| 改 PREPARE_STEPS 顺序（D10）影响断点续跑 | 低 | 中 | 每步本就按产物跳过；`test_aicut_cli` 全部 prepare 用例 + e2e 草稿测试回归 |
| ⑤ 暂住时手动分镜表 + 重新选段的语义仍是旧的（KI-95 在 M14） | 中 | 中 | ⑤ 横幅下明确一行说明；不改现有不覆盖行为 |
| `ui_prefs.json` 写失败（配置目录不可写） | 低 | 低 | POST 返回 500 + 人话，前端保持当前会话的键位（内存），下次启动回默认 |
| 不可用 = 隐私：剔除阈值 0.1 秒可能多删相邻内容 | 中 | 低 | toast 告知删了哪几镜；可在 ⑤ 手动加回非隐私部分 |
| ⚑ 产品决定被推翻 | 中 | 低~中 | 每条只影响标注的 Task；P1/P2/P6 的默认都是「保守、可加不可减」 |

## Notes
- 子切片顺序 M13a → M13b → M13c → M13d 不可调换：M13b 依赖 A 的 `/api/state.wizard`、`/api/analysis`、`/api/prefs`；M13c 依赖 A 的 unusable / clip_list 接口与 B 的外壳；M13d 删除子窗口必须在 ③④ 都落地之后。
- M14 接手点：`gui/wizard.py::derive()` 里 ⑤⑥ 两行（加闸门 B 与导出状态）、`step-result.js` / `step-export.js` 整体替换、KI-95 的冲突询问挂在 `wizard.js` 的 `reselect` 动作上。
- 本计划没有写任何实现代码，也没有提交；`storyboard/`、`work/`、`designs/`、`storyboard-seedream/` 未触碰。
