# 画面理解（AI 多模态，可选）

## Problem Statement

剪辑师用 ai-cut 粗剪 30–90 分钟的访谈 / 讲解 / 门店实拍素材时，AI 只"听"不"看"：片段完全由转写稿切出，没人说话的有效画面（签约手部特写、产品展示、操作演示、空镜）根本不进分析和选段，只能人工拖进度条找；话说得好但画面不对（背对镜头、出画、画面与内容无关）的片段又会被当作「可用」选进片。结果是 20 分钟人工预算里有一大块花在"看画面"上。

## Evidence

- 代码事实：内容单元 = 转写句子合并段（`pipeline/format_transcript.py`，≤35 秒），无人声的时间段不产生任何片段
- 代码事实：本机画面分析只有画质（过暗 / 静止 / 抖动 / 虚焦，`pipeline/understand_visual.py`），三档判定里画面只参与「过暗降档」一条规则（`pipeline/classify.py:149`）
- 产品负责人 2026-10-29 提出需求：多模态理解结果要和 ASR 文字分析结果整合，"完整地分析出视频片段的内容"
- 剪辑师侧的量化痛点（找画面耗时、因画面删镜头的比例）：Assumption - 需要用真实素材做开 / 关对比验证

## Proposed Solution

在 ② 分析页加一个显眼的「画面理解（AI 多模态）」开关，默认关闭。勾选后，分析时从已有的 540p 浏览小样转出低清、低帧率的代理素材，按单视频抽帧上限切段，用现有的 MediaKit 上传流程传上去，调用 MediaKit「视频理解智能策略」（`video-understand-router`，底层是火山方舟视觉大模型），用提示词让它按时间轴输出画面内容。整合分两步：程序按时间重叠把画面时间轴挂到每个片段，并为无人声但有画面内容的时间段生成「画面片段」；再由 DeepSeek 在逐句标注时同时看「说了什么 + 画面上有什么」，给出画面判断，进入档位判定和 ③ 显示。选 MediaKit 而不是直接接方舟，是因为它和现在的转写是同一个服务、同一个 Key、同一套上传和任务轮询，剪辑师不用再配 Key；选云端而不是本机视觉模型，是因为效果好、两平台成本一致、不增加安装包；时间对齐交给程序而不是大模型，是为了时间不被模型改错、结果可检查、成本更低。

## Key Hypothesis

We believe 在分析阶段加入画面理解并与转写分析整合 will 减少剪辑师"找画面"和"删掉画面不对的镜头"的工作 for 拍访谈 / 讲解 / 实拍长素材的剪辑师。
We'll know we're right when 同一批真实素材开 / 关对比：⑤ 中因画面原因被手动删除的镜头减少 ≥50%，且 ③ 能直接找到无人声的关键画面。

## What We're NOT Building

- 本机视觉模型 —— 已决定用火山 MediaKit 云端
- 人脸识别 / 人物身份 —— 隐私风险，与粗剪目标无关
- 上传原片 —— 只传降质代理素材
- 对象存储 TOS / 直接接方舟 —— MediaKit 本地上传（`mediakit://`）已够用，避免多一套密钥
- 画面理解的费用 / token 上限 —— 先不设，但单独记账
- 素材时长上限 —— 素材多长就分析多长（靠切段实现）
- 完全无人声素材（转写失败）的处理 —— 仍按现状报错

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| ⑤ 因画面原因手动删除的镜头 | 比关闭时减少 ≥50% | 同一批 ≥3 条真实素材开 / 关对比，统计 ⑤ 删除操作及原因 |
| 无人声关键画面的召回 | 剪辑师事先标注的关键画面 ≥80% 出现在 ③ 的画面片段里 | 人工标注后对照 |
| 时间轴准确度 | 画面事件起止时间中位误差 ≤1 秒 | 技术验证阶段人工抽样核对 |
| 分析耗时与费用 | 不设上限，记录每小时素材的增量耗时和 tokens | `work/timings.json`、画面理解用量账本 |

## Open Questions

> 2026-10-30 第 1 阶段已验证，结论见 `.claude/PRPs/reports/multimodal-phase1-spike.report.md`：现有 Key 可用；JSON 稳定；默认手动 2 fps、每段 5 分钟；模型自评「可用性」不可靠；语义切片不采用；ASR 暂保留，另做替代验证。

- [ ] 开通条件：现有 MediaKit Key 能否直接调用 `video-understand-router`，还是要在火山方舟另外开通模型服务（文档说模型费用由方舟按 tokens 收取）
- [ ] 抽帧上限：单视频最多 1000 帧、最长 2 小时。实测不同 `fps` / 切段长度下的画面描述质量和 tokens，决定切段长度（一次任务最多 10 个视频，切段可以放进同一个任务）
- [ ] 输出格式：结果 `contents` 是自由文本，提示词要求 JSON 时间轴后能否稳定解析
- [ ] 音轨：`need_audio` 可开启音频分析（使用 `doubao-seed-2-0-lite`）。实测开 / 关音频对画面理解质量和 tokens 的影响，以及带音频时能否给出可替代 MediaKit 转写的逐句时间戳和说话人
- [ ] 档位与价格：Economy（mini 模型，约 30% 帧）/ Balanced（pro，约 60% 帧）/ Quality（pro，1fps）每小时素材的 tokens 和效果
- [ ] 时间轴准确度：没有专门的时间定位字段，靠提示词约定 + 抽帧，精度受帧率限制。实测后决定画面片段的切点是否吸附到本机镜头切点，或改用 MediaKit「智能语义切片」（`semantic-segment`）给出的切点
- [ ] 画面理解失败时：整个分析报错（与现有"不静默降级"一致），还是提供"关闭画面理解后继续"的出口
- [ ] 旧项目：创建后不再自动分析，已有项目在 ② 中如何显示

---

## Users & Context

**Primary User**
- **Who**: 拍访谈、讲解、门店实拍的剪辑师，素材 30–90 分钟，含大量操作演示和产品特写
- **Current behavior**: 在 ③ 按转写片段浏览，没人说话的画面靠拖进度条找；⑤ 里手动删掉画面不能用的镜头
- **Trigger**: 在 ③ 找不到「那段没说话的签约镜头」，或 ⑤ 预览片里出现背影、空画面
- **Success state**: ③ 里每段都有画面描述，无人声的关键画面直接列出来；⑤ 的候选画面基本可用

**Job to Be Done**
When 我拿到一段长素材, I want to 让 AI 同时看懂画面和对白, so I can 不必从头拖进度条找画面，选段也不会选进画面不能用的段。

**Non-Users**
- 纯口播、一镜到底的剪辑师：画面信息少，可以不勾选
- 素材涉及隐私、不能出本机的剪辑师：不应勾选，开关处需提醒画面会上传

---

## Solution Detail

### Core Capabilities (MoSCoW)

| Priority | Capability | Rationale |
|----------|------------|-----------|
| Must | ① 按钮改为「创建项目」，创建后不自动分析；② 进入「准备开始」状态，有显眼的开关和「开始分析」 | 用户要求开关放在 ② |
| Must | 分析中开关置灰、只能停止；完成或停止后可改开关并重新运行（已有结果走缓存，只补跑画面相关步骤） | 用户要求 |
| Must | 代理素材（低清、低帧率、按抽帧上限切段）+ MediaKit 视频理解智能策略 + 画面时间轴（提示词约定 JSON，程序校验、时间换算回全片） | 核心能力 |
| Must | 整合：按时间挂到片段；生成无人声的「画面片段」；DeepSeek 逐句标注时同时判断画面；档位判定用上画面判断 | 用户要求"整合后完整分析片段内容" |
| Must | ③ 显示画面描述和画面片段，画面片段可试听、按 S 放进剪辑列表 | 不显示就无法验证效果 |
| Must | 档位可选（省钱 = Economy 默认 / 均衡 = Balanced / 精细 = Quality）；沿用 MediaKit Key；外发告知升级（第三条数据流，勾选时取得同意） | 用户要求；隐私红线变更 |
| Must | 同步修改设计图 `designs/aicut.pen` 和 `docs/界面流程-v2.md`；PRD 隐私红线改为"仅勾选时外发降质画面" | 用户要求 |
| Should | 选段自动选入画面片段；⑤「＋空镜」从画面片段中挑 | 价值大，但先验证标签质量 |
| Should | 摘要、决策问题参考画面信息 | 顺带受益 |
| Could | ⑤「查看 AI 提示词」弹窗也显示画面理解的提示词 | 便于排查 |
| Could | 用「智能语义切片」（`semantic-segment`，综合画面和语音、不切断句子，只输出起止时间）作为画面片段的切点 | 取决于技术验证结果 |
| Could | 带音频分析时替代 MediaKit 转写 | 取决于技术验证结果 |
| Won't | 本机视觉模型、人脸识别、TOS、直接接方舟、费用上限 | 见上文 |

### MVP Scope

Must 全部：开关和新的创建 / 开始流程、代理素材与 MediaKit 视频理解、时间对齐 + 画面片段 + DeepSeek 画面判断、档位判定、③ 显示、档位选择、外发告知、设计图与 PRD 同步。

### User Flow

① 填信息 →「创建项目」→ ② 准备开始：勾选「画面理解（AI 多模态）」（首次勾选弹出外发告知；可选档位，默认「省钱」）→「开始分析」→ 进度里多出「生成画面代理」「云端画面理解」「整合画面与对白」→ ③ 每段显示画面描述，另有画面片段 → ④ ⑤ ⑥ 照旧。想关掉：停止或等完成后取消勾选 → ② 标「需要更新」→ 重新运行。

---

## Technical Approach

**Feasibility**: HIGH（云端接口现成，项目内已有可复用的代理、上传、重试、缓存、"需要更新"机制）；时间轴准确度和音轨能力为 MEDIUM，需技术验证

**Architecture Notes**
- 代理素材：从已有的 `work/proxy.mp4`（540p30，`aicut.py:343 cmd_junk`）转出，低分辨率、低帧率、低码率；带不带音轨看技术验证。按"抽帧率 × 段长 ≤ 1000 帧"切段，且每段 ≤2 小时
- 服务：MediaKit `POST /api/v1/tools/video-understand-router`（参数 `video_urls`、`prompt`、`level`、`prefer_models`、`manual_option{fps,max_snapshot_number,need_audio}`），`GET /api/v1/tasks/{id}` 轮询；结果 `contents`（每个视频一段文本）+ `token_usage`。上传沿用现有 `mediakit://` 本地上传
- 客户端：扩展 `pipeline/cloud.py`（同一 endpoint、同一 Bearer Key、同一预签名上传、退避重试、脱敏、按素材指纹续传），新增提交和结果解析；不新增 Key
- 输出：`work/visual_timeline.json`（全片时间，事件列表 `{start,end,desc,objects,text_on_screen,shot}`，程序校验后落盘）
- 整合：
  1. 程序按时间重叠把事件挂到 `segments.json` 的片段；无人声且有内容的时间段生成画面片段（id 与句子片段区分），切点可吸附本机 `scenes` 的镜头切点
  2. `understand_text` 的逐句标注在开关打开时把画面描述一起给 DeepSeek，增加字段：画面与话是否一致、画面可见的关键信息、画面可用性；开关状态进入标注指纹
  3. `classify` 使用这些字段（例如画面可见关键信息 → 提档，背对 / 出画 → 降档），理由写成人话
- 流程：`readiness.PREPARE_STEPS` 增加画面相关步骤（开关关闭时跳过）；`gui/analysis.py` 的进度项相应增加；`fingerprints.analysis_inputs` 加入开关和所选模型，切换后 ② 自动标「需要更新」
- 用量：按结果里的 `token_usage` 单独记账，不计入 DeepSeek 300 万预算，不设上限
- 转写替代（Could）：`need_audio` 能做音频分析，但输出是自由文本，文档没说明能否给出逐句时间戳和说话人；现有片段、切点、说话人都依赖 MediaKit 转写的句级时间戳，且关闭开关时仍需转写。v1 保留转写，技术验证后再决定

**Technical Risks**

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| 模型输出的时间轴不准或格式不稳 | M | 提示词约定 JSON 格式并校验、失败重试；切点吸附本机镜头切点；技术验证先量化误差 |
| 长素材多次调用，耗时长 | M | 各段并发上传与理解（注意限流）；按段缓存，停止后重跑只补未完成的段 |
| 抽帧上限与文档不符，或现有 Key 未开通该工具 | M | 技术验证先确认；切段长度做成常量；未开通时给出中文原因和开通指引 |
| 隐私：画面上云 | M | 默认关闭；勾选时外发告知并取得同意；只传降质代理 |
| 创建后不自动分析，影响已有项目和测试 | L | 旧项目按已有分析状态显示；补前端行为测试 |
| Windows 上传与编码差异 | L | 代理转码用现有 `encode` 封装，两平台 CI 都跑 |

---

## Implementation Phases

<!--
  STATUS: pending | in-progress | complete
  PARALLEL: phases that can run concurrently (e.g., "with 3" or "-")
  DEPENDS: phases that must complete first (e.g., "1, 2" or "-")
  PRP: link to generated plan file once created
-->

| # | Phase | Description | Status | Parallel | Depends | PRP Plan |
|---|-------|-------------|--------|----------|---------|----------|
| 1 | 技术验证 | 用真实素材调 MediaKit 视频理解：开通条件、抽帧上限、各档位 tokens 与效果、音频、JSON 稳定性、时间轴误差、语义切片；出结论报告 | complete | with 2 | - | `.claude/PRPs/reports/multimodal-phase1-spike.report.md` |
| 2 | 流程与开关 | 「创建项目」不自动分析；② 准备开始状态 + 开关 + 档位 + 运行中锁定；"需要更新"；外发告知；设计图、界面流程、PRD 红线同步 | complete | with 1 | - | `.claude/PRPs/plans/completed/multimodal-phase2-flow-and-toggle.plan.md`（报告 `.claude/PRPs/reports/multimodal-phase2-flow-and-toggle-report.md`） |
| 3 | 代理素材与云端理解 | 代理转码 + 切段；扩展 MediaKit 客户端（上传、提交、轮询、重试、续跑）；`visual_timeline.json`；档位；单独记账 | complete | - | 1, 2 | `.claude/PRPs/plans/completed/multimodal-phase3-proxy-and-cloud.plan.md`（报告 `.claude/PRPs/reports/multimodal-phase3-proxy-and-cloud-report.md`） |
| 4 | 整合与判定 | 时间对齐、画面片段、DeepSeek 画面判断、档位判定 | complete | - | 3 | `.claude/PRPs/plans/completed/multimodal-phase4-integrate-and-judge.plan.md`（报告 `.claude/PRPs/reports/multimodal-phase4-integrate-and-judge-report.md`） |
| 5 | ③ 呈现与收尾 | ③ 显示画面描述和画面片段（可放入剪辑列表）；GUI 文档、PROGRESS、放行检查；开 / 关对比验收 | in-progress | - | 4 | `.claude/PRPs/plans/completed/multimodal-phase5-present-and-wrapup.plan.md`（报告 `.claude/PRPs/reports/multimodal-phase5-present-and-wrapup-report.md`） |

### Phase Details

**Phase 1: 技术验证**
- **Goal**: 把 Open Questions 里的接口事实变成实测数字
- **Scope**: 一次性脚本（不进产品代码），≥2 条真实素材；三档对比；开 / 关音频；JSON 输出稳定性；抽样核对时间轴误差；试 `semantic-segment`
- **Success signal**: 报告给出开通条件、切段长度、代理参数、默认档位、是否带音轨、切点来源，以及"能否替代转写"的结论

**Phase 2: 流程与开关**
- **Goal**: 交互先到位，开关打开时暂时只记录状态
- **Scope**: `gui/static/project-form.js`、`gui/static/step-analyze.js`、`gui/analysis.py`、`pipeline/fingerprints.py`、`pipeline/consent.py` + `gui/static/settings.js`、`designs/aicut.pen`、`docs/界面流程-v2.md`、`docs/PRD-AI粗剪工具.md`
- **Success signal**: 创建后停在 ② 准备开始；运行中开关不可改；切换后 ② 标「需要更新」；测试通过

**Phase 3: 代理素材与云端理解**
- **Goal**: 稳定拿到全片画面时间轴
- **Scope**: 代理转码与切段、MediaKit 视频理解客户端、时间轴校验与换算、按段缓存续跑、用量账本
- **Success signal**: 60 分钟素材产出完整的 `visual_timeline.json`；中途停止后重跑只补未完成的段
- **状态说明（2026-10-31）**：真账号验收通过（54 分钟素材，省钱档 11 段，460,037 tokens）：时间轴覆盖全片、停止后再开始只续查 / 补提未完成的段、剪辑台 13 / 11 项切换且关闭后无上传。详见报告「真账号验收」一节

**Phase 4: 整合与判定**
- **Goal**: 画面信息进入片段判断
- **Scope**: 对齐模块、画面片段、`understand_text` 标注扩展、`classify` 规则
- **Success signal**: 开关关闭时结果与现在完全一致；打开时片段带画面字段，档位理由能引用画面
- **状态说明（2026-11-01）**：真账号验收通过（54 分钟素材，138 句对白）：对白标注开 / 关逐句一致，开 / 关只差 5 句且都来自画面规则（3 升 2 降），画面片段 44 段（8 段可用）；开启后 DeepSeek 只多画面两轮（7 次调用约 3.2 万 token）。验收中修了对白标注缓存随画面数据失效、收紧了闲聊 / 一两个字的对白靠画面升档。已知局限：模型把闲聊标成「事实陈述」时仍会因画面升档。详见报告「真账号验收」一节

**Phase 5: ③ 呈现与收尾**
- **Goal**: 剪辑师看得到、用得上，并完成验收
- **Scope**: ③ 列表和详情、画面片段放入剪辑列表、文档、放行检查
- **Success signal**: 成功指标里的开 / 关对比达标
- **状态说明（2026-11-01）**：代码完成、测试通过，审查无 CRITICAL / HIGH；③ 显示画面信息与画面片段、可放入剪辑列表并导出；旧项目画面结果可认回。等放行检查 #34 与开 / 关对比验收后标 complete

### Parallelism Notes

Phase 1（接口实测）和 Phase 2（界面与流程）互不依赖，可以同时做。Phase 3 依赖 1 的参数结论和 2 的开关；4、5 依次依赖前一阶段。

---

## Decisions Log

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| 视觉理解在哪里跑 | 火山 MediaKit「视频理解智能策略」（底层方舟视觉大模型） | 直接接方舟 Files API；本机视觉模型 | 用户指定 MediaKit；与转写同服务、同 Key、同上传流程；效果好、两平台一致 |
| 是否可选 | 可选，默认关闭 | 默认开启 | 用户要求；画面上云需剪辑师主动选择 |
| 开关位置 | ② 分析页显眼位置 | ① 新建表单、项目设置 | 用户要求 |
| 创建后是否自动分析 | 不自动；按钮改为「创建项目」 | 保持自动开始 | 用户要求，给开关留出勾选时机 |
| 运行中能否改开关 | 不能，只能停止；完成或停止后可改并重新运行 | 运行中随时可改 | 用户要求 |
| 时长 / 费用上限 | 都不设，单独记账 | 设预算 | 用户要求 |
| 平台 | Mac 和 Windows 一起做 | 先做 Mac | 用户要求；云端能力两平台成本一致 |
| 代理素材来源 | 从已有 540p 浏览小样转出 | 从原片重新编码 | 快；分辨率已满足单帧像素上限 |
| 上传 | MediaKit 本地上传（`mediakit://`） | TOS、方舟 Files API | 现有转写已在用，无需新密钥 |
| 长素材 | 按单视频 1000 帧上限切段（每段 ≤2 小时） | 整段上传 | 整段会被稀疏抽帧，画面看得粗 |
| 整合方式 | 程序按时间对齐 + DeepSeek 做语义判断 | 全部交给大模型合并 | 时间不被模型改错、可检查、成本低；用户提出的大模型方案作为第二步保留 |
| 模型 | 档位可选，默认 Economy（mini 模型） | 固定 pro | 用户要求默认便宜；用 MediaKit 自带档位，不自己管模型名 |
| ASR | v1 保留 MediaKit 转写，技术验证后再决定是否替代 | 立即用内嵌音轨替代 | 片段与切点依赖句级时间戳；关闭开关时仍需转写 |

---

## Research Summary

**Market Context**
- MediaKit 视频理解智能策略：`POST /api/v1/tools/video-understand-router`，输入支持 `mediakit://`，单任务 ≤10 个视频、单视频 ≤2 小时、≤1000 帧；`prompt` 自然语言指令；`level` Economy（默认，`doubao-seed-2-0-mini`，约 30% 帧）/ Balanced（`doubao-seed-2-0-pro`，约 60%）/ Quality（pro，1fps）；`manual_option` 可设 `fps`（0.2–5）、`max_snapshot_number`、`need_audio`（音频用 `doubao-seed-2-0-lite`）；输出 `contents` 为自由文本 + `token_usage`；MediaKit 不另收处理费，按方舟 tokens 计费 —— [视频理解智能策略](https://docs.volcengine.com/docs/6448/2551133?lang=zh)、[计费说明](https://docs.volcengine.com/docs/Intelligentprocessing/Billinginstructions-7?lang=zh)
- MediaKit 智能语义切片：`POST /api/v1/tools/semantic-segment`，综合画面与语音切出语义完整片段，只输出起止时间（`segments[].start_ms/end_ms`），单视频 ≤3 小时，参数 `min_duration`（默认 3 秒）/ `max_duration`（默认 30 秒）/ `max_shift_tolerance`，按输入时长计费 —— [智能语义切片](https://docs.volcengine.com/docs/intelligent-processing/semantic-segment-guide?lang=zh)
- 以下为直接接方舟的调研（未采用，作参考）：
- 火山方舟视频理解：Responses / Chat API 支持视频；Files API 单文件 512 MB（TOS 2 GB），Base64 / URL 50 MB；`fps` 默认 1、范围 0.2–5；Seed 2.0 起单视频抽帧 16–1280 帧、默认 token 上限约 8 万；无专门时间戳字段，时间格式靠提示词约定 —— [视频理解](https://docs.volcengine.com/docs/ark/video-understanding?lang=zh)、[文件输入 (File API)](https://docs.volcengine.com/docs/ark/file-api?lang=zh)、[多模态理解](https://docs.volcengine.com/docs/82379/1958521?lang=zh)、[多模态向量化 API](https://docs.volcengine.com/docs/ark/Embeddings-2?lang=zh)
- 视频内嵌音轨：方舟音频理解文档称可解析视频音轨做语音识别、内容和情绪理解，示例模型 `doubao-seed-2-1-lite`；音频理解另有字级时间戳和说话人模式，但未说明是否适用于视频内嵌音轨 —— [音频理解](https://docs.volcengine.com/docs/ark/audio-understanding?lang=zh)
- 价格：`doubao-seed-2-1-pro` 输入 6 元 / 输出 30 元每百万 tokens；`doubao-seed-2-1-turbo` 3 / 15；lite 未查到 —— [模型详情](https://ark.volcengine.com/region:cn-beijing/model/detail?name=doubao-seed-2-1-pro)、[模型价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)、[火山方舟产品页](https://www.volcengine.com/product/ark)

**Technical Context**
- 创建即分析：`gui/static/project-form.js:20,124-150` → `gui/static/step-analyze.js:75 startAnalysis()`
- 分析步骤：`gui/analysis.py:20-32`（界面 11 项）、`pipeline/readiness.py:16`（实际顺序）、`aicut.py:649 cmd_prepare`；停止：`gui/jobs.py:337 cancel_job`
- "需要更新"：`pipeline/fingerprints.py:89 analysis_inputs` → `work/analysis_inputs.json` → `gui/wizard.py:108-115`
- 浏览小样：`aicut.py:343 cmd_junk`，`work/proxy.mp4`（540p30）
- 云端客户端范式：`pipeline/cloud.py`（预签名上传、退避重试、脱敏、续传）；密钥：`pipeline/secrets.py:23 PROVIDERS`
- 片段：`pipeline/format_transcript.py`（≤35 秒合并段，字段 id/start/end/speaker/lines/text/duration）；标注：`pipeline/understand_text.py`；判定：`pipeline/classify.py`
- 外发告知：`pipeline/consent.py`（`CONSENT_VERSION = 1`）与 `gui/static/settings.js` 两处同步
- 用量：`pipeline/usage.py`（`work/llm_usage.json`，默认 300 万 tokens）

---

*Generated: 2026-10-30*
*Status: DRAFT - needs validation*
