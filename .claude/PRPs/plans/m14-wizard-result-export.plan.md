# Plan: M14 · 向导：看结果与导出（GL-26 ⑤⑥ / GL-27 / KI-94 / KI-95 / KI-98 / KI-100）

## 产品决定（2026-10-20 用户确认：Q1–Q7 全部按推荐默认；标 ⚑ 处即受影响位置）

| # | 问题 | 推荐默认（本计划按此实现） | 备选 | 影响 |
|---|---|---|---|---|
| Q1 | 同一张分镜表先「导出到 Mac 剪映」、又「生成 Windows 剪映包」：算一个版本还是两个？（规格只说「每次导出生成新版本 vN」） | **算同一个版本**：当前分镜表已经导出过（某个 vN 的预览片指纹 = 当前预览片指纹）就往这一版里补另一种导出物，不新开版本；同一版再点「导出到 Mac 剪映」→ 按钮变成「已在 Mac 剪映里：片名_vN」+「打开剪映」（剪映不允许同名草稿，KI-59） | 每点一次都新开 vN（同一张表会出现 v3 = Mac、v4 = Windows 两个内容相同的版本） | T4 `outputs.build_args`、T15 |
| Q2 | 闸门 B 没过（当前分镜表没有预览片）时，⑥ 能不能进？ | **有历史版本就能进**（看历史、对比、回到某一版、补旧版的 Windows 包），但「本次导出」两个按钮置灰并说明「先在「⑤ 看结果」生成当前分镜表的预览片」；一个版本都没有时 ⑥ 才是「未到」 | 严格闸门：没过 ⑤ 就锁 ⑥（改一个字就看不到历史版本） | T7 `derive()`、T15 |
| Q3 | 含「不可用」片段的旧版本（KI-100）：除了不能生成 Windows 包，还要拦什么？ | **拦「生成 / 在访达中显示」它的 Windows 包**（`/api/open target=export` 同样 409）；卡片上红字「这一版含 N 段已标为不可用的片段」；预览片仍可在剪辑台里播放、可参与对比（只在本机看，不外发）；「回到这一版」允许，但恢复时自动去掉含不可用片段的镜头并提示（同 M13 D12）；已进剪映草稿库的 Mac 草稿程序改不了，只提示 | 连预览片播放 / 对比也禁掉；或「回到这一版」也禁掉 | T6、T15、T16 |
| Q4 | 未采用清单的「原因」怎么显示？PRD FR-8 写「时长 / 重复 / 未勾选必留」，但**选段没有任何去重判断**（`pipeline/select.py:450-456` 只有「话题未入选 / 超出话题预算 / 不在候选池」），而本里程碑不改算法 | 按现有数据映射成人话，**不显示「因重复」**并登记 **KI-101**：<br>· 话题有入选但时长满了 →「因时长：这个话题的时长已经用完」<br>· 话题一句都没入选 →「未勾选为必须记住的信息」<br>· 话题被排除 →「你在决策问题里排除了这个话题」<br>另加两类（M14 新出现的情况）：「你从分镜表里删掉了」（在 AI 选段里、但手动删了）、「剪辑列表里的片段 · 出片前必须加回」（必留段不在当前分镜表里，出片会被拦，GL-25） | 实现去重判断（改选段算法，超出 M14 范围，需另立项） | T5 `select.unused[].cause`、T6、T11 |
| Q5 | 「你手动改过分镜表（N 处）」的 N 怎么数？哪些改动会触发询问？ | **与「分叉时的 AI 选段」逐镜比对**：新增 / 删除 / 改字幕 / 改入出点各算一处，顺序变了算一处；`shots.json` 存在但 0 处改动 → **不询问，直接按新 AI 选段覆盖**；「回到某一版」「加回」都算手动修改 | 只要存过 `shots.json` 就算手动改过（哪怕内容和 AI 一样也会被问） | T1、T2、T12 |
| Q6 | ② 「重新分析」（偏好 / 预设改过后）最后会重跑选段：手动改过分镜表时要不要也弹「覆盖 / 保留」？（FR-7 列的触发项里没有它） | **不弹，按「保留我的修改」处理**（= 现状：分析不碰 `shots.json`）；⑤ 页顶部一行「分析结果更新了：分镜表仍是你手动改的那一版；需要时点「恢复为 AI 选段」」 | 重新分析前也弹三选一询问 | T12、T10 |
| Q7 | 分镜表「展开看被删的替代句」指什么？ | **同一话题里没进片的可用段**（就是未采用清单里同话题的那几条，最多 3 条，按时间），每条可「试听」「加回」 | 同一句话被截掉的部分（选段截短镜头时丢掉的尾巴）；或 LLM 给的备选句（没有这份数据） | T6 `alternatives`、T11 |

> 以上任何一条改了，只影响标注的 Task，其它切片照做。

---

## Summary
把 ⑤ 看结果、⑥ 导出从 M13 的「暂住」旧视图换成正式版，关掉 GL-26 剩余部分、GL-27、KI-94、KI-95、KI-98、KI-100。核心是**把出片拆成两步**：⑤「生成预览片」只渲染到项目的暂存目录 `output/preview/`、**不产生版本**；⑥「导出到 Mac 剪映 / 生成 Windows 剪映包」把**同一份**暂存时间线与预览片「晋升」为 `output/vN`（FR-8「预览与最终剪映工程同一份 timeline」），再装草稿或打包。
⑤ 有顶栏摘要（目标 / 当前 / 镜头数 / 剪辑列表 n/n 进片 / 超目标警告）、可改字幕的分镜表（为什么选它、展开替代句、选中行设入出点）、预览片、未采用清单（原因 + 试听 + 加回）、「恢复为 AI 选段」，闸门 B「看过了，去导出 →」只在当前分镜表的预览片已生成时可点。凡会重新选段的操作（⑤ 改时长、⑤ 横幅重新选段、④ 重新确认）在手动改过分镜表时先问「覆盖 / 保留我的修改 / 取消」并列出改了什么（KI-95）。⑥ 有本次导出、历史版本卡片（含不可用片段的版本被标出并拦 Windows 包，KI-100）、两版对比（并排播放 + 镜头差异，KI-94）、回到这一版；「打开剪映」只在检测到剪映且做过 Mac 导出后出现（KI-98）。

## User Story
作为剪辑师，我想在「看结果」里改时长、改分镜表、从未采用清单里一键加回漏掉的段，自己点「生成预览片」看一遍，确认无误后再导出到 Mac 剪映或生成 Windows 包；手动改过的分镜表不会被悄悄覆盖，导出过的版本能并排对比、能回到某一版，这样我能放心地反复调整，不怕丢东西。

## Problem → Solution
- 「生成新版本」= 切片 + 预览 + 草稿 + 版本号一起做（`aicut.py:569-620`），看预览就得先出一个版本，版本列表被试看填满（GL-26）→ 新命令 `aicut preview` 只写 `output/preview/`（不进版本列表），`aicut build` 改为「暂存 → 晋升为 vN → 草稿 / Windows 包」，GUI 导出时带 `--require-preview` 只晋升用户看过的那一份。
- 未采用清单只在 `selection.json.unused` 里（GL-27）→ ⑤ 右下列表：可用但不在**当前**分镜表里的段 + 原因（⚑Q4）+ 试听 + 加回（按时间插入，算一次手动修改）。
- 手动改过分镜表后答案和时长不再生效、也回不去（KI-95）→ 重新选段前三选一询问 + 改动清单；「恢复为 AI 选段」；覆盖前自动备份；`shots.json` 读改写跨进程加锁。
- 版本只能逐个看（KI-94）→ 对比两版（并排播放 + 新增 / 删除 / 改字幕 / 改入出点）+ 回到这一版（覆盖当前分镜表前先确认，不删任何版本）。
- 「打开剪映」硬编码 `/Applications/VideoFusion-macOS.app`、随时可点（KI-98，`gui/server.py:486-488`）→ 先检测（两个固定位置 + Spotlight 按 bundle id 找），没装就不显示，只在 Mac 导出后出现。
- 事后标「不可用」不会让旧产物失效（KI-100）→ 版本卡片标出，拦旧版 Windows 包的生成与「在访达中显示」（⚑Q3）。
- 顺带：`--no-draft` 出的版本卡片上也写着「Mac 剪映草稿名」，剪映里其实没有这份草稿（`gui/views.py:45`）→ 登记 **KI-102**，用每版的 `export.json` 记录真实导出物后修复。

## Metadata
- **Complexity**: **XL**（约 40 个文件：新建 ~12、改 ~28）→ 拆成 3 个子切片，**每个提交后 App 都能从新建走到剪映打开**：
  - **M14a 后端地基**（界面不变，M13 暂住的 ⑤⑥ 照常可用）：腾行数 → 镜头差异 / 分镜表存储与锁 → 预览暂存与版本晋升 → 选段 `--manual` 与未采用原因 → ⑤⑥ 新接口、版本卡片数据、KI-98 检测、KI-100 拦截
  - **M14b ⑤ 看结果**：顶栏、分镜表、预览片、未采用清单、KI-95 询问、恢复为 AI 选段、闸门 B；`derive()` 的 ⑤ 规则
  - **M14c ⑥ 导出 + 收尾**：本次导出、历史版本、对比、回到这一版、打开剪映；`derive()` 的 ⑥ 规则与服务端闸门；文档与登记
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 14「向导：看结果与导出」（GL-26 ⑤⑥、GL-27、KI-94、KI-95、KI-98，及 M13 留下的 KI-100）
- **Estimated Files**: ~40（见 Files to Change）
- **Spec**: `docs/界面流程-v2.md` §三.⑤⑥、§六、§七.3；`docs/PRD-AI粗剪工具.md` v1.3 FR-7（210-229）/ FR-8（231-237）/ FR-9 / FR-10（247-252）/ FR-11（254-258）、§12。设计稿 `designs/aicut.pen`（加密，**不要用 Read / Grep 打开**；规格文档已描述）。

### 基线（2026-10-20，HEAD `ae810ae`）
- `uv run pytest`：2637 passed，覆盖率 94.4%（M13 报告）。实现前先跑一遍确认基线全绿，红的先查清再动手。
- 行数红线（`tests/test_structure.py:6-7`）：`aicut.py` ≤ 800（**现 765，只剩 35 行**）、`gui/server.py` ≤ 650（现 568）；前端每个 `gui/static/*.js` ≤ 400（`tests/test_static_pages.py:34`）；`gui/project_routes.py` 已 459 行 → M14 的新接口一律放新模块。
- 静态白名单 = 磁盘上的文件集合（`tests/test_static_pages.py:296-300`）；`index.html` 脚本顺序有守卫（`tests/test_static_pages.py:35-37,309`）；`tests/fe_harness.py:17-19` 的 `SCRIPTS` 要同步。

---

## 冒烟 / 手工测试的硬规则（每个实现者、每次都遵守）

M13 有一次冒烟没设 `AI_CUT_SECRETS=file`，把假 Key 写进了用户的登录钥匙串（M13 报告 Issues Encountered）。**本里程碑任何手工启动剪辑台、App 或 `aicut` 命令做冒烟时，一律先建临时目录并带上全部隔离变量，绝不碰真实钥匙串、真实配置目录、真实项目目录和真实剪映草稿库：**

```bash
SMOKE=$(mktemp -d /tmp/aicut-smoke.XXXXXX)
export AI_CUT_SECRETS=file                       # 强制文件后端：绝不读写登录钥匙串
export AI_CUT_CONFIG_DIR="$SMOKE/cfg"            # 告知记录、Key 文件、ui_prefs.json、job.marker
export AI_CUT_PROJECTS="$SMOKE/projects"         # 项目目录（注意：不是 AI_CUT_DATA_DIR，M13 计划里写错了）
export AI_CUT_DRAFT_ROOT="$SMOKE/jy_drafts"      # 剪映草稿根：Mac 导出写到这里，不进真实草稿库
export AI_CUT_LOG_DIR="$SMOKE/logs"
uv run python gui/server.py --port 8899 --open   # 或 uv run python app/main.py
```

- 冒烟里用假 Key（如 `fake-key-12345678`）时必须确认 `AI_CUT_SECRETS=file` 已生效：`uv run python -c 'from pipeline import secrets; print(secrets._force_file())'` 打印 `True`（`pipeline/secrets.py:69-70`）。
- 「导出到 Mac 剪映」在冒烟里只验证草稿落在 `$SMOKE/jy_drafts` 下；**真机在剪映里打开并播放**属于人工放行检查（`docs/PROGRESS.md` #20–#24，由用户执行），实现者不把草稿装进真实剪映。
- 自动化测试已经由 `tests/conftest.py:12-38` 的 autouse 夹具隔离（`AI_CUT_SECRETS=file`、`AI_CUT_CONFIG_DIR`、`AI_CUT_DRAFT_ROOT`、`AI_CUT_LOG_DIR`），新测试不得绕过（不要在测试里 `monkeypatch.delenv("AI_CUT_SECRETS")`）。
- 冒烟结束：`rm -rf "$SMOKE"`；**事后核对**：`security find-generic-password -s ai-cut 2>&1 | head -1` 应为「could not be found」，有就说明泄漏了，立刻报告用户，不要自己删用户的条目。

---

## 工程决策（按默认执行，均可事后改）

| # | 决策 | 默认 | 理由 |
|---|---|---|---|
| E1 | 预览片放哪 | 项目内暂存目录 `output/preview/`（`outputs.PREVIEW_DIR = "preview"`）：`timeline.json`、`shots_snapshot.json`、`preview.mp4`（+完成标记）、`.timeline.sha`、`preview.json`（`{inputs, shots, duration, at}`）。版本列表只认 `output/v<数字>`（`views._versions` 的 `glob("v*")` + `next_version` 的数字校验天然排除它） | 切片清理 `clips._referenced`（`pipeline/clips.py:180-189`）扫的是 `output/*/timeline.json`，暂存时间线自动算「被引用」，预览用到的切片不会被清掉；放 `work/` 下则要改清理逻辑 |
| E2 | 「当前分镜表的预览片」怎么判 | 输入指纹 `fingerprints.preview_inputs(pdir, cfg)` = `{table, unusable, preset, material}`：`table` = 当前分镜表（手动优先，否则 AI 选段）每镜 `[id, in, out, sub]` 的 sha1；`unusable` = 标为不可用的片段 id 集合的 sha1；写在 `preview.json.inputs`（渲染开始前取，成功后才写，同 M13 D3）。`fresh` = 指纹相等且 `preview.mp4` 完整（`media_io.is_complete`，**不用** `complete_or_adopt`：状态判定不能写盘） | 与 M13 的「需要更新」同一套办法；不用 mtime |
| E3 | 闸门 B「看过了」 | = 当前分镜表的预览片**已生成**（规格 §三.⑤「已生成才可点」）；不追踪是否播放完 | 规格原文；播放进度跟踪既不可靠（拖动、倍速）也无规格 |
| E4 | 导出 = 晋升 | `aicut build` 先确保暂存预览片是当前分镜表的（CLI：不是就重新暂存；GUI 带 `--require-preview`：不是就 `[x]` 停），再把暂存里的 5 个文件**硬链接**（失败退回复制）到 `output/vN/`，写 `vN/export.json`，然后装 Mac 草稿或打 Windows 包 | FR-8 验收「预览与最终剪映工程内容一致（同一份 timeline 生成）」；硬链接不占额外磁盘、不重渲染 |
| E5 | 每版导出物记录 | `output/vN/export.json = {"mac": {"draft", "at"} \| null, "windows": {"zip", "at"} \| null}`；Mac 草稿装成功后才写 `mac`；Windows zip 以文件存在为准（沿用 `jobs.windows_export_state`），同时写 `windows`。没有 `export.json` 的旧版本 = `legacy`，卡片照旧显示草稿名但注明「改版前生成」 | 修 KI-102；KI-98「只在 Mac 导出后出现」需要知道哪一版真的进了剪映 |
| E6 | 版本卡片怎么知道「是不是当前分镜表」 | 晋升时把 `preview.json`（含 `inputs`）一起带进 `vN/`；`current = vN/preview.json.inputs == preview_inputs(now)` | ⑥「已完成」与 ⚑Q1 的「同一版补另一种导出物」都靠它 |
| E7 | 「手动分镜表」的基线 | 第一次写出 `shots.json` 时（`/api/shots`、加回、回到这一版、撤销不可用都可能是第一次），在同一把锁内把当时的 AI 选段（`work/shots-selected.json` 的 `shots`）存成 `work/manual_base.json`；改动清单 = `shot_diff.diff(base, 当前手动表)`。删除 `shots.json`（覆盖 / 恢复为 AI 选段）时一并删基线。没有基线的旧项目 → 和当前 AI 选段比 | ⚑Q5：「保留我的修改」之后 AI 选段会变，和新 AI 选段比会把 AI 的变化算成「你的修改」 |
| E8 | 镜头配对（改动清单与版本对比共用） | 纯函数 `pipeline/shot_diff.py`：先按 `id` 且时间重叠配对，剩下的按时间重叠率（交 / 并）≥ `PAIR_MIN_IOU = 0.5` 贪心配对；配上的比 `sub`（去首尾空白）与入出点（差 > `RETIME_TOLERANCE_S = 0.05` 算改入出点）；没配上的分别是新增 / 删除；配上的相对顺序变了 → `reordered=True`（算一处） | AI 选段每次都从 `sel01` 编号（`pipeline/select.py:445-447`），同一个 id 在两版里可能是完全不同的内容，只按 id 比会出错 |
| E9 | `shots.json` 并发 | `pipeline/shots_store.py` 增加 `locked(pdir)`：线程锁 `LOCK` + 项目内文件锁 `.aicut-shots.lock`（`fcntl.flock`，同 `project_lock` 写法，文件系统不支持时只记 warning）。所有整体重写 `shots.json` 的路径都走它：`/api/shots`、不可用移除 / 放回、恢复为 AI 选段、回到这一版、`aicut select --manual=replace` | 「覆盖」发生在 `aicut select` 子进程里，与剪辑台进程的保存是跨进程竞争，线程锁挡不住 |
| E10 | 重新选段任务进行中能不能改分镜表 | 服务端：这个项目有 `select` 任务在跑时，`/api/shots`、恢复为 AI 选段、回到这一版一律 409「正在重新选段，完成后再改」；前端：此时 ⑤ 分镜表只读（输入框 `readonly`、按钮置灰，提示同上） | 选「覆盖」时任务结束会删 `shots.json`，期间的保存会被吞掉或复活旧表 |
| E11 | 覆盖前的快照 | 删除 / 替换 `shots.json` 前存 `work/shots_backups/<UTC 时间>-<原因>.json`（原因：`replace` 覆盖、`restore-ai`、`restore-vN`），只留最近 `BACKUP_KEEP = 10` 份；**不做**恢复备份的界面 | PRD Risks「覆盖前留快照」；界面只承诺「不会悄悄丢」 |
| E12 | 「保留我的修改」的语义 | 照常跑选段（更新 `selection.json`、`shots-selected.json`、未采用原因、建议时长、⑤ 的「需要更新」指纹），**不碰** `shots.json` 与基线 = M13 现状；`aicut select --manual=keep`（默认） | FR-7「保留我的修改（只更新未采用清单和建议）」 |
| E13 | 未采用清单的口径 | 服务端算（`gui/result_payload.py`）：可用（level 3、含人工裁决）且没标不可用、与**当前**分镜表重叠 ≤ 1.0 秒（与 ③ 的 `inCut` 同阈值，`gui/payloads.py:40-42`）的段；外加不在当前分镜表里的剪辑列表段（排最前，⚑Q4）。原因优先级：剪辑列表 → 你删掉的（在 AI 选段 `segment_id` 里）→ `selection.unused[].cause` → 旧 `reason` 文本映射 → 「没有进片」 | 「可用但没进片」应以剪辑师眼前那张表为准；保留手动修改时 `selection.unused` 是相对 AI 表算的，不能直接用 |
| E14 | 「加回」 | 服务端在每条未采用里给好 `shot = {in, out, sub}`（整段，`sub` 用 `shot_sub.sub_for`，与必留段进片同一写法 `pipeline/select.py:138-144`）；前端按时间插入 `state.shots`（第一个 `in` 比它大的镜头之前，同 `gui/project_routes.py:395-397`），`nextShotId()` 取号，走现有保存队列 `saveShots(true)`，存完重新拉 ⑤ 数据 | 复用已测过的单通道保存队列（KI-50），不新增一条与之竞争的服务端写路径 |
| E15 | ⑤ 的播放器 | 右上一个播放器两种模式：「预览片」（`/media/<项目>/current-preview?v=<at>`）/「素材」（浏览小样，选中镜头或试听未采用段时自动切过去）。「设为入点 / 出点」只在素材模式出现。原来贴在页面底部的 `#shotbar` 删掉 | 入出点必须在素材上定（预览片是剪过的）；两块播放器并排太挤 |
| E16 | 超目标提示 | 去掉选段 / 分析完成后自动弹「改目标时长」（`gui/static/jobs.js:203-204`）；改为 ⑤ 顶栏警告条「剪辑列表共 X，超过目标 Y · 建议改为 Z」+「改为 Z」按钮（点了走 KI-95 询问 → 重新选段） | 规格 §三.⑤「这里变成警告条并直接给建议时长」；自动弹窗打断 ④→⑤ 的跳转 |
| E17 | ⑤ 的数据从哪来 | 新 `GET /api/result`：顶栏、每镜的 `why / topic / alternatives`（按镜头 id 映射）、未采用清单、预览片状态、手动改动清单、`wizard`；分镜表本身仍用 `/api/state.shots` + 前端保存队列。进入 ⑤、每次保存成功、任务完成后重拉（带序号防乱序，同 `app.js:50-63` 的 `stateSeq`） | `/api/state` 每次轮询都要轻；⑤ 的计算（覆盖率、未采用、替代句）只在 ⑤ 需要 |
| E18 | KI-98 剪映检测 | `jy_version.find_app()`：先查 `APP_CANDIDATES`（`/Applications`、`~/Applications`），再 `mdfind "kMDItemCFBundleIdentifier == 'com.lemon.lvpro'"`（超时 `MDFIND_TIMEOUT_S = 3`，只取 `.app` 结尾、存在的第一条）；剪辑台进程内缓存 `JIANYING_CACHE_S = 60` 秒。`/api/open target=jianying` 用找到的路径 `open -a`，没找到 → 404「没找到剪映专业版…」 | bundle id 已在 `pipeline/to_jianying.py:5` 记录；Spotlight 是系统自带、只读、本机 |
| E19 | Mac 导出时剪映开着 | 起任务前检查 `to_jianying.jianying_running()`（`pipeline/to_jianying.py:464-466`）：开着 → 409 `need: "close_jianying"`；前端弹「剪映正在运行」+「我已关掉，继续」（重试同一请求）+「取消」 | 规格 §三.⑥「剪映开着时先提示关掉剪映」；否则要等切片、晋升都做完才在装草稿时失败 |
| E20 | 前端文件 | `step-result.js` 重写为 ⑤ 页面骨架；新增 `result-table.js`（分镜表 + 播放器 + 入出点，从现 `step-result.js` 迁）、`result-unused.js`（未采用清单 / 替代句 / 试听 / 加回）、`reselect.js`（KI-95 询问、恢复为 AI 选段）；`step-export.js` 重写；新增 `export-compare.js`（对比、回到这一版）。每个 ≤ 400 行 | 守住 M13 的「每个脚本聚焦一件事」 |
| E21 | 新路由模块 | `gui/result_routes.py`（`/api/result`、`/api/result/restore-ai`、`/api/versions/compare`、`/api/versions/restore`）+ `gui/result_payload.py`（纯数据组装）；`server.py` 只加一行委托、`/api/shots` 的锁 / 基线 / 409、`/api/open` 的两处、`/media/<p>/current-preview` | `project_routes.py` 已 459 行；server.py 留余量 |
| E22 | aicut.py 腾行数 | 先做一个行为不变的提交：`cmd_calibrate` 主体搬到 `pipeline/project_cli.calibrate(...)`（输出函数注入，同 `project_cli.clean`，`aicut.py:713`）、Windows 打包主体搬到 `pipeline/outputs.package_windows(...)`；之后新增的 `cmd_preview` 与 `build` 的晋升逻辑也尽量放 `pipeline/outputs.py`，aicut 只做编排 | 现在只剩 35 行余量 |
| E23 | ② 重新分析 + 手动分镜表（⚑Q6） | `cmd_prepare` 末尾的 `select` 走默认 `--manual=keep`；⑤ 页面在「`source == 'manual'` 且选段指纹的 `scored` 分项变过」时显示 Q6 的那行提示 | 与 FR-7 列出的触发项一致，不额外打断 |
| E24 | 新增 KI | 登记 **KI-101**（未采用原因缺「因重复」：选段没有去重判断，⚑Q4，状态 open，不在 M14 修）、**KI-102**（`--no-draft` 的版本卡片也显示「Mac 剪映草稿名」，T6 修复并钉测试） | 用户硬约定：发现即登记 + 钉住 |

---

## 步骤状态判定（`gui/wizard.py`，T7 / T13 / T16 的规格；①–④ 不变）

### 新增 Facts（`collect` 读盘；全部「坏了也不抛」）
| 字段 | 来源 | 说明 |
|---|---|---|
| `preview_inputs_now` | `fingerprints.preview_inputs(pdir, cfg)` | 轻量模式（项目列表 `digests=False`）也算：只读 `shots.json` / `shots-selected.json` / `overrides.json` 三个小文件 |
| `preview_saved` | `output/preview/preview.json["inputs"]`（`outputs.read_stamp`） | 无 / 损坏 → `None` |
| `preview_complete` | `media_io.is_complete(output/preview/preview.mp4)` | 不认领旧文件（无写盘副作用） |
| `preview_fresh` | `preview_saved is not None and preview_saved == preview_inputs_now and preview_complete and table 非空` | |
| `has_versions` | 现有 `_has_versions(pdir)` | |
| `exported_current` | 任一 `output/v*/preview.json["inputs"] == preview_inputs_now` | 旧版本没有这份文件 → 不算 |

### derive(facts) 中 ⑤⑥ 的新规则
| 步 | locked（hint） | stale（banner / action） | done | 否则 |
|---|---|---|---|---|
| ⑤ 看结果 `result` | ④ 不是 done/stale →「先完成「④ 定标准」」（不变） | 选段输入指纹有分项变了（不变，M13 `_result_step`） | **M14b 起**：`preview_fresh` 且不 stale | available |
| ⑥ 导出 `export` | ④ 不是 done/stale（不变）；**M14c 起**：否则 `not preview_fresh and not has_versions` →「先在「⑤ 看结果」生成预览片」（⚑Q2） | — | **M14c 起**：`exported_current` | available |

- `next`：分析没完成 → `analyze`；否则依次取 ④ → ⑤ → ⑥ 里第一个 `stale` 或 `available`；都不是 → `export`（不变）。⑤ 已完成而 ⑥ 未完成时 next = `export`。
- 新常量：`LOCKED_EXPORT_HINT = "先在「⑤ 看结果」生成预览片"`。
- 下游不连锁（M13 D4）：⑤ 的 stale 不让 ⑥ stale；⑥ 只看「当前表导没导出过」。

---

## UX Design

### Before（M13 暂住）
```
⑤ 看结果：[改目标时长][＋空镜][按时间排序] 共 18 镜 · 2:58
  # | 入点 | 出点 | 时长 | 字幕 | ↑↓⧉✕          （没有「为什么选它」、没有未采用清单、没有预览片）
  底部 #shotbar：浏览小样播放器 [设为入点][设为出点][试听这一镜]
  横幅：素材标记改过了 · [重新选段]  + 一行「你手动改过分镜表，重新选段只更新建议，不会覆盖它」
⑥ 导出：[生成新版本（导出到 Mac 剪映）][打开剪映 ← 永远可点、路径写死]
  v3 18 镜 · 2:58 · 10-20 14:02  Mac 剪映草稿名：片名_v3（哪怕只出了预览）  [生成 Windows 剪映包]  <预览片>
  弹窗「生成新版本」：☐ 这次只生成预览片，不导出到剪映   ← 看预览也要开一个新版本
```

### After
```
⑤ 看结果
┌ 目标 3:00 [改] · 当前 2:58 · 镜头 18 · 剪辑列表 6/6 进片 ✓ ─────────────── [恢复为 AI 选段]* ┐
│ （超目标时）⚠ 剪辑列表共 3:40，超过目标 3:00 · 建议改为 3:40 [改为 3:40]                        │
├ 分镜表 ───────────────────────────────┬ 播放器  (●预览片 | ○素材) ─────────────────────┤
│ 01 00:12.3–00:20.1 7.8s [字幕可改…]   │ <video>                                         │
│    为什么选它：含金额 · 讲合同  [▸ 替代句 2] │ 素材模式：[设为入点][设为出点][试听这一镜]       │
│    ↑ ↓ ✕                               │ 预览片：分镜表改过了 · [重新生成预览片]          │
│ 02 …                                   ├ 未采用清单（12）────────────────────────────┤
│ [＋空镜] [按时间排序]                  │ 03:12 讲退费 「…原文…」 因时长  [试听][加回]     │
│                                        │ 05:40 讲合同 「…」 你从分镜表里删掉了 [试听][加回] │
└────────────────────────────────────────┴─────────────────────────────────────────────────┘
← 上一步                                                   [看过了，去导出 →]（预览片已生成才可点）
* 只在手动改过时出现
改时长 / 横幅重新选段 / ④ 重新确认（手动改过时）：
  ┌ 你手动改过分镜表（3 处）。按新的设置重新选段会覆盖这些修改。 ┐
  │ · 第 4 镜改了字幕 · 新增第 7 镜 · 删除了 00:52 那一镜         │
  │ [覆盖，用新的 AI 选段] [保留我的修改] [取消]                  │
  └───────────────────────────────────────────────────────────┘

⑥ 导出
┌ 本次导出（当前分镜表 18 镜 · 2:58 · 预览片 14:02）──────────────────────────────────────┐
│ [导出到 Mac 剪映]  [生成 Windows 剪映包]     （闸门 B 没过：两个都置灰 + 说明，⚑Q2）        │
│ 完成后：已导出 v4 → Mac 剪映草稿「片名_v4」 [打开剪映]（检测到剪映才有）                    │
│         Windows 包 片名_v4_Windows.zip 312 MB [在访达中显示] 拷到 Windows 解压，双击 INSTALL.bat │
├ 历史版本 ──────────────────────────────────────────── [对比两版] ┤
│ ☐ v4 · 10-20 15:10 · 2:58 · 18 镜 · 当前  Mac 剪映：片名_v4 · Windows 包 312 MB  <预览片> [回到这一版] │
│ ☐ v3 · ⚠ 这一版含 2 段已标为不可用的片段：Windows 包不能再生成或打开 <预览片> [回到这一版]            │
└─────────────────────────────────────────────────────────────────────┘
对比：v3 | v4 两个播放器并排 [同时播放]；新增 2 · 删除 1 · 改字幕 3 · 改入出点 1（逐条列出）
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 看预览片 | 只能在 ⑥ 生成新版本（勾「只生成预览片」也开版本号） | ⑤「生成预览片」，不产生版本；表改过显示「重新生成预览片」 | §七.3：进入 ⑤ 不自动生成 |
| 闸门 B | 没有 | ⑤ 底部「看过了，去导出 →」，当前表的预览片生成过才可点 | E3 |
| 改目标时长 | 弹窗 | 顶栏「改」就地分 + 秒；手动改过先问 | KI-95 |
| 超目标 | 任务完成后自动弹窗 | ⑤ 顶栏警告条 + 建议时长按钮 | E16 |
| 未采用清单 | 无 | ⑤ 右下：原因 + 试听 + 加回 | GL-27 / ⚑Q4 |
| 手动改过后重新选段 | 静默保留手动表，只一行说明 | 三选一询问 + 改动清单；「恢复为 AI 选段」 | KI-95 / ⚑Q5 |
| 导出 | 一个「生成新版本」弹窗（含只出预览勾选） | 「导出到 Mac 剪映」「生成 Windows 剪映包」两个按钮，晋升当前预览片为 vN | E4 / ⚑Q1 |
| 打开剪映 | 永远可点、路径写死 | 检测到剪映且这一版导出过 Mac 才出现 | KI-98 |
| 版本卡片 | 草稿名永远显示；含不可用的旧版本照样可导出 / 定位 zip | 只显示真实导出物；含不可用的标红并拦 Windows 包 | KI-100 / KI-102 / ⚑Q3 |
| 对比 / 回退 | 无 | 选两版并排播放 + 镜头差异；「回到这一版」先确认 | KI-94 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `docs/界面流程-v2.md` | 107-133, 152-165 | ⑤⑥ 逐屏规格；§六 旧入口去向；§七 已定 |
| P0 | `docs/PRD-AI粗剪工具.md` | 120-124, 210-258, 383-392 | 闸门 B、FR-7..FR-11、术语（预览片 / 版本） |
| P0 | `.claude/PRPs/plans/m13-wizard-setup-to-criteria.plan.md` | 1-112 | 产品决定 P1–P9、工程决策 D1–D20、步骤状态表（M14 只改 ⑤⑥ 两行） |
| P0 | `.claude/PRPs/reports/m13-wizard-setup-to-criteria-report.md` | 全部 | 实际实现与偏差（`timeline_hits` 读快照、`base.js` / `main.js`、冒烟写钥匙串事故） |
| P0 | `aicut.py` | 445-469, 485-514, 529-620, 623-648, 651-666, 738-760 | select、export、build、草稿、prepare、入口 |
| P0 | `gui/server.py` | 278-296, 351-366, 436-492 | 起任务、媒体路由、/api/shots、/api/open |
| P0 | `gui/jobs.py` | 29-33, 109-131, 436-479 | 任务表、`busy_view` / `project_job_detail`、Windows 导出参数 |
| P0 | `gui/views.py` | 30-75 | `_versions`、`project_state` |
| P0 | `gui/wizard.py` | 45-130 | `collect` / `derive`（M14 只动 ⑤⑥） |
| P0 | `gui/project_routes.py` | 343-439 | 手动分镜表的锁内读改写、按时间插回（加回 / 回到这一版照抄） |
| P0 | `pipeline/select.py` | 138-193, 311-477, 581-638 | 必留镜头写法、未采用、`run` 写 selection |
| P0 | `pipeline/exclusions.py` | 全部 | 不可用：`spans` / `drop_overlapping` / `filter_shots` / `timeline_hits` |
| P0 | `pipeline/clips.py` | 119-200 | 快照、补切、切片清理（暂存目录被视为引用） |
| P0 | `pipeline/fingerprints.py` | 全部 | 指纹写法（新增 `preview_inputs` / `table_digest` / `unusable_digest`） |
| P0 | `gui/static/step-result.js`、`step-export.js`、`jobs.js`、`wizard.js`、`app.js`、`base.js` | 全部 | 要替换 / 改的前端 |
| P0 | `gui/static/step-criteria.js` | 240-290 | ④ 闸门（KI-95 询问挂在这里） |
| P1 | `pipeline/shots_store.py`、`pipeline/project_lock.py` | 全部 | 线程锁 + flock 写法 |
| P1 | `pipeline/jy_version.py`、`pipeline/to_jianying.py` | 全部 / 441-466, 509-519 | 剪映位置、是否在运行、同名草稿 |
| P1 | `pipeline/export_draft.py` | 82-127 | Windows 打包 |
| P1 | `pipeline/cli_args.py` | 30-56 | 子命令定义 |
| P1 | `gui/settings.py` | 24-65 | `PrepareBlocked` / `check_ready`（加 build 的剪映检查） |
| P1 | `gui/confirm.py` | 全部 | ④ 确认起选段（加 `manual`） |
| P1 | `gui/payloads.py` | 22-86, 172-197 | 剪辑列表 / `inCut` 阈值 |
| P1 | `tests/conftest.py`、`tests/fe_harness.py`、`tests/fe_fixtures.py`、`tests/test_frontend_steps.py`、`tests/test_unusable.py` | 全部 | 测试夹具与现有 ⑤⑥ 测试 |
| P1 | `tests/test_static_pages.py`、`tests/test_structure.py`、`tests/test_terms.py` | 全部 | 静态守卫、行数、名词 |
| P2 | `docs/GUI.md` | 10-72, 97-130, 151-185 | 「剪辑师怎么用」、接口表、文件地图 |
| P2 | `docs/PROGRESS.md` | 94-118 | 放行检查表（加 #20–#24） |

## External Documentation

No external research needed — feature uses established internal patterns.

KEY_INSIGHT: macOS `mdfind "kMDItemCFBundleIdentifier == 'com.lemon.lvpro'"` 用 Spotlight 元数据按 bundle id 找已安装 App，本机只读、不联网；Spotlight 被关闭或目录被排除时返回空。
APPLIES_TO: E18 / T6 `jy_version.find_app()`。
GOTCHA: `mdfind` 可能很慢或返回已删除到废纸篓的副本 → 设超时、只认存在且以 `.app` 结尾、不在 `~/.Trash` 下的路径；检测失败一律当「没装」（只是不显示按钮，不影响导出）。

KEY_INSIGHT: `os.link` 在同一 APFS 卷上创建硬链接，`output/preview/` 与 `output/vN/` 必在同一卷；目标已存在时要先写临时名再 `os.replace`。
APPLIES_TO: E4 / T3 `outputs.promote()`。
GOTCHA: 硬链接共享 inode——之后重新生成预览片时 `media_io.atomic_output` 是写临时文件再改名（新 inode），不会改到已晋升版本里的那一份；**不能**用原地截断写（`open(..., "wb")`）改暂存文件。

---

## Patterns to Mirror

### NAMING_CONVENTION（中文文案做模块常量；KI 编号进注释）
// SOURCE: pipeline/exclusions.py:14-25
```python
UNUSABLE_OVERLAP_S = 0.1   # D12：与不可用片段重叠超过这么多秒的镜头整镜剔除（隐私优先）
DROPPED_WARNING = "已自动剔除 {n} 个含「不可用」片段的镜头：{ids}"
EXPORT_BLOCKED = "这一版含 {n} 段已标为不可用的片段，不能再导出；请生成新版本"
```
// SOURCE: gui/static/step-export.js:4-17（前端：`COPY_*` 在文件顶部）
```js
/* 界面文案：产品可直接改这里 */
const COPY_EXPORT_NEW = '生成新版本（导出到 Mac 剪映）';
const COPY_EXPORT_OPEN_JIANYING = '打开剪映';
```

### ROUTE_MODULE（路由子模块：返回 (状态码, JSON) 或 None；项目解析由 server 传入）
// SOURCE: gui/project_routes.py:88-114
```python
def _get_analysis(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        pdir = existing(name)
        cfg = schema.read_json(pdir / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    ...
GET_ROUTES = {"/api/analysis": _get_analysis, ...}

def handle_get(path: str, q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict] | None:
    route = GET_ROUTES.get(path)
    return route(q, lookup, existing) if route else None
```
// SOURCE: gui/server.py:331-332, 385-388（server 里的接线）
```python
if (hit := project_routes.handle_get(p, q, project_path, existing_project)) is not None:
    return self._json(hit[1], hit[0])
```

### ERROR_HANDLING（写已落盘后拼响应失败也回 200 + warning；CorruptJSON 先于 ValueError）
// SOURCE: gui/project_routes.py:313-320
```python
def _saved_response(pdir: Path, name: str, sid: str, cleared: str | None, **extra) -> dict:
    try:
        return {**_mark_response(pdir, name, sid, cleared), **extra}
    except Exception:  # noqa: BLE001 - 写已落盘，响应拼装失败不能让界面回滚
        LOG.exception("标记已保存，但拼响应失败：%s", sid)
        return {"ok": True, ..., "warning": SAVED_BUT_STALE_MSG, **extra}
```

### REPOSITORY_PATTERN（手动分镜表：锁内读改写、先备份、按时间插回、不新建）
// SOURCE: gui/project_routes.py:343-360, 381-400
```python
def _remove_manual_shots(pdir: Path, marked: list) -> list[dict]:
    shots_path = pdir / "shots.json"
    with shots_store.LOCK:
        if not shots_path.exists():
            return []
        raw = schema.read_json(shots_path)
        shots = schema.read_shots(shots_path)
        kept, dropped = exclusions.drop_overlapping(shots, marked)
        ...
        schema.write_json(pdir / "work" / SHOTS_BACKUP, raw)
        schema.write_json(shots_path, {**raw, "shots": kept})
...
for shot in sorted(added, key=lambda s: (s["in"], s["out"])):
    at = next((i for i, cur in enumerate(shots) if cur["in"] > shot["in"]), len(shots))
    shots = [*shots[:at], shot, *shots[at:]]
```

### FILE_LOCK_PATTERN（跨进程：flock，不支持就 warning 放行）
// SOURCE: pipeline/project_lock.py:36-51
```python
@contextlib.contextmanager
def _locked(pdir: Path, mode: int, name: str = LOCK_FILE) -> Iterator[None]:
    fd = _open(pdir, name)
    try:
        try:
            fcntl.flock(fd, mode)
        except BlockingIOError as exc:
            raise Busy(str(pdir)) from exc
        except OSError as exc:
            _LOG.warning(UNSUPPORTED, exc, Path(pdir).name)
            yield
            return
        yield
    finally:
        os.close(fd)  # 关闭即释放
```

### SERVICE_PATTERN（出片：护栏 → 锁内切片 / 时间线 / 快照 → 预览 → 草稿；戳在产物之后写）
// SOURCE: aicut.py:583-620、547-560
```python
try:  # GL-25：切片（耗时）之前确认分镜表覆盖全部必留段
    missing = select.missing_must_keep(pdir / "work", shots)
...
with project_lock.build_section(pdir):  # KI-89 复审：切片 → 时间线 → 清理，同项目出片串行
    with applog.stage(pdir / "work", "clips"):
        clip_paths = ensure_clips(pdir, c, shots)
    ...
    save_json(vdir / "timeline.json", schema.stamp(tl))
    clips.save_snapshot(vdir, shots)
    clips.prune_unreferenced(pdir)
...
def ensure_preview(vdir: Path, tl_hash: str) -> Path:
    preview, stamp = vdir / "preview.mp4", vdir / ".timeline.sha"
    if stamp.exists() and stamp.read_text().strip() == tl_hash and media_io.complete_or_adopt(preview):
        info("预览片无变化，跳过渲染")
        return preview
    ...
    stamp.write_text(tl_hash)  # 必须在产物落盘之后
```

### DELEGATED_CLI（只读 / 维护命令搬出 aicut.py，输出函数注入）
// SOURCE: aicut.py:711-718；pipeline/project_cli.py:1-5
```python
def cmd_clean(args) -> None:
    project_cli.clean(project_dir(args.name), args.dry_run, ok=ok, info=info, die=die)
# pipeline/project_cli.py：输出函数由调用方注入（同 config_cli），本模块不 import aicut。
```

### LOGGING_PATTERN
// SOURCE: gui/project_routes.py:18, 318；pipeline/exclusions.py:113
```python
LOG = applog.get("gui")
LOG.exception("标记已保存，但拼响应失败：%s", sid)
LOG.warning("导出拦截：%s 没有留存分镜表，无法核对不可用片段", Path(vdir).name)
```
→ 日志里只写版本号、镜头 id、计数、动作名；**不写字幕原文、片名、偏好内容**。

### FRONTEND_PATTERN（CSP：事件委托 data-act；动态值过 esc()/num()；单通道保存队列；序号防乱序）
// SOURCE: gui/static/app.js:50-67, 127-146
```js
let stateSeq = 0;
async function refresh(name=state.project){
  const seq = ++stateSeq;
  let data;
  try { data = await api('/api/state?project='+encodeURIComponent(name)); }
  catch(e){ if(seq !== stateSeq) e.stale = true; throw e; }
  if(seq !== stateSeq) return false;
  ...
const saveQ = {chain: Promise.resolve(true), queued: null};
function saveShots(silent){ ... saveQ.chain = slot.done; return slot.done; }
```
// SOURCE: gui/static/step-criteria.js:253-258（询问弹窗：按钮走 data-act，modalKind 标记）
```js
function askGate(n){
  showModal(COPY_GATE_ASK.replace('{n}', n),
    `<p>${esc(COPY_GATE_ASK_NOTE)}</p><div class="job-actions">`
    + `<button class="primary" data-act="gateGo">${esc(COPY_GATE_GO)}</button>`
    + `<button class="ghost" data-act="closeModal">${esc(COPY_GATE_BACK)}</button></div>`);
  state.modalKind = 'gate';
}
```

### TEST_STRUCTURE（服务端集成 / CLI / node vm）
// SOURCE: tests/conftest.py:101-129；tests/test_unusable.py:1-40
```python
def call(gs, method, path, body=None, *, token=True, headers=None, raw=None): ...
def make_project(root, name="p1", shots=None, **files): ...
pytestmark = pytest.mark.usefixtures("consented")
def _seg(i, start, dur, topic="讲合同", *, level=3, must=False, unusable=False, text=""): ...
```
// SOURCE: tests/test_aicut_build.py:331-350（打桩 aicut 上的名字测 cmd_build）
```python
monkeypatch.setattr(aicut, "ensure_clips", lambda *a: project / "work/clips")
monkeypatch.setattr(aicut, "ensure_preview", lambda vdir, h: hashes.append(h) or vdir / "p.mp4")
monkeypatch.setattr(aicut, "install_draft", lambda *a: None)
aicut.cmd_build(argparse.Namespace(name="p", version="v1", no_draft=True))
```
// SOURCE: tests/test_frontend_steps.py:12-20, 34-43（node：`in_ready(script, routes)`、`act()`、`calls`）
```python
def test_stale_result_banner_reselect_starts_select_job():
    out = in_ready("""await go('result'); const banner = el('#banner').innerHTML;
      await act('reselect'); await tick();
      return [banner, calls.filter(c => c.path === '/api/job').map(c => c.body), ...];""",
                   {"GET /api/state": {**READY_STATE, "wizard": stale}})
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/project_cli.py` | UPDATE | 接收 `cmd_calibrate` 主体（E22） |
| `pipeline/outputs.py` | CREATE | 暂存目录、`preview.json` 戳、晋升、`export.json`、Windows zip 路径与打包、`build_args`（E1/E4/E5/E22） |
| `pipeline/shot_diff.py` | CREATE | 镜头配对与差异（E8）；改动清单人话 |
| `pipeline/shots_store.py` | UPDATE | `locked(pdir)`（线程锁 + flock）、`current()`、`write_manual()`（首次写基线）、`drop_manual()`、`backup()`（E7/E9/E11） |
| `pipeline/fingerprints.py` | UPDATE | `table_digest`、`unusable_digest`、`preview_inputs`（E2） |
| `pipeline/select.py` | UPDATE | `unused[].cause`；`with_lines` 公开别名（加回的字幕） |
| `pipeline/jy_version.py` | UPDATE | `find_app()`（E18） |
| `pipeline/cli_args.py` | UPDATE | `preview` 子命令；`build --windows --require-preview`；`select --manual` |
| `aicut.py` | UPDATE | `cmd_preview`；`cmd_build` 拆为暂存 + 晋升；`cmd_select --manual=replace`；`cmd_export` 默认时间线排除暂存；委托瘦身 |
| `gui/result_payload.py` | CREATE | ⑤ 数据：顶栏、镜头注解、未采用清单、预览片状态、手动改动；版本对比数据 |
| `gui/result_routes.py` | CREATE | `/api/result`、`/api/result/restore-ai`、`/api/versions/compare`、`/api/versions/restore` |
| `gui/server.py` | UPDATE | 委托新路由；`/api/shots` 锁 / 基线 / 409；`/api/open` 剪映检测 + KI-100；`/media/<p>/current-preview` |
| `gui/views.py` | UPDATE | `_versions` 加 `exports / legacy / current / unusable_hits / blocked / has_snapshot`（KI-100、KI-102）；`project_state` 加 `manual`、`jianying`、`preview` |
| `gui/wizard.py` | UPDATE | ⑤⑥ 规则（M14b / M14c 各一半） |
| `gui/jobs.py` | UPDATE | `preview` 任务；`build` 的 `target` / 复用版本 / `--require-preview`；`select` 的 `manual`；`windows_zip` 委托 `outputs` |
| `gui/settings.py` | UPDATE | `check_ready(pdir, task, body)`：Mac 导出时剪映在运行 → `need=close_jianying`（E19） |
| `gui/confirm.py` | UPDATE | `manual: replace|keep` → 选段任务参数 |
| `gui/static_files.py` | UPDATE | 新增 4 个脚本 |
| `gui/static/index.html` | UPDATE | 脚本顺序；删 `#shotbar` |
| `gui/static/app.css` | UPDATE | ⑤ 两栏布局、顶栏、播放器模式切换、未采用清单、⑥ 本次导出 / 卡片 / 对比 |
| `gui/static/step-result.js` | UPDATE（重写） | ⑤ 骨架、顶栏、改时长、预览片、闸门 B |
| `gui/static/result-table.js` | CREATE | 分镜表（从旧 step-result.js 迁）+ 播放器 + 入出点 + 为什么选它 / 替代句 |
| `gui/static/result-unused.js` | CREATE | 未采用清单、试听、加回 |
| `gui/static/reselect.js` | CREATE | KI-95 询问、恢复为 AI 选段 |
| `gui/static/step-export.js` | UPDATE（重写） | 本次导出、历史版本卡片、打开剪映、KI-100 |
| `gui/static/export-compare.js` | CREATE | 对比两版、回到这一版 |
| `gui/static/wizard.js` | UPDATE | `reselect` 走询问；⑤ 的下一步 = 闸门 B；删 `COPY_MANUAL_SHOTS_NOTE` |
| `gui/static/step-criteria.js` | UPDATE | 闸门确认前走 KI-95 询问；删手动分镜表说明 |
| `gui/static/jobs.js` | UPDATE | `preview` 任务文案；删自动弹改时长；`need=close_jianying`；完成后刷新 ⑤ / ⑥ 数据 |
| `gui/static/app.js` | UPDATE | `STEP_VIEWS` / `ENTER_HOOKS` 换成新页面；离开 ⑤ 前 flush |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports：`pipeline.outputs`、`pipeline.shot_diff`、`gui.result_payload`、`gui.result_routes`（`tests/test_structure.py` 守卫） |
| `tests/test_shot_diff.py` | CREATE | 配对 / 差异 / 人话 |
| `tests/test_shots_store.py` | CREATE | 锁、基线、备份、删除 |
| `tests/test_outputs.py` | CREATE | 暂存戳、晋升、export.json、build_args、Windows 路径 |
| `tests/test_preview_export.py` | CREATE | `aicut preview` / `build` 晋升 / `--require-preview` / `--windows` / `select --manual` |
| `tests/test_result_api.py` | CREATE | `/api/result`、恢复为 AI、对比、回到这一版、`/api/shots` 409 与基线 |
| `tests/test_versions_view.py` | CREATE | 版本卡片字段、KI-100、KI-102、`/api/open` 剪映 / 拦截 |
| `tests/test_frontend_result.py` | CREATE | node：⑤ 页面、顶栏、改时长、预览片、未采用、加回、闸门 B |
| `tests/test_frontend_reselect.py` | CREATE | node：KI-95 三个入口的询问与参数、恢复为 AI |
| `tests/test_frontend_export.py` | CREATE | node：⑥ 本次导出、卡片、打开剪映、KI-100、对比、回到这一版 |
| `tests/test_wizard_state.py`、`test_frontend_steps.py`、`test_frontend_gate.py`、`test_frontend_js.py`、`test_frontend_jobs.py`、`test_static_pages.py`、`test_terms.py`、`test_server_export.py`、`test_aicut_build.py`、`test_e2e_draft.py`、`test_jy_version.py`、`test_select.py`、`test_confirm_flow.py`、`fe_harness.py`、`fe_fixtures.py` | UPDATE | 跟随新接口 / 新文件 / 新语义 |
| `docs/GUI.md`、`docs/known-issues.md`（KI-94/95/98/100 状态、新增 KI-101/102）、`docs/go-live-blockers.md`（GL-26、GL-27）、`docs/PROGRESS.md`（放行检查 #20–#24）、`CHANGELOG.md`、`.claude/prds/ai-cut-go-live.prd.md` | UPDATE | 文档与登记 |

## NOT Building

- 任何选段 / 分析算法改动：不加「去重」判断（⚑Q4 → KI-101 open）、不改话题预算、不改必留规则。
- 手动修改的逐条撤销 / 历史记录界面；`work/shots_backups/` 的恢复界面（E11 只保证不丢）。
- 版本删除、版本改名、版本备注。
- 对比时的逐帧同步播放 / 同步拖动（只做「同时播放」从头开始）。
- 自动生成预览片（§七.3 已定手动）；渲染进度百分比。
- 删除已进剪映草稿库的 Mac 草稿、删除旧版本的 Windows zip 文件（⚑Q3 只拦，不删）。
- Windows 上运行剪辑台（PRD Open Questions）。
- ② 重新分析前的覆盖询问（⚑Q6）。
- 新的快捷键（⑤ 里不加键盘操作；③ 的快捷键不扩展到 ⑤）。

---

## Step-by-Step Tasks

> 每个 Task 先写测试（RED，记下实际看到的失败数）→ 实现（GREEN）→ 重构。每个 **Commit** 边界走用户约定的闭环：`find . -name "*.tsbuildinfo" -delete`（本仓无 TS，命令照跑无害）→ `uv run pytest -q` → `uv run pytest --cov -q`（≥ 80%）→ `wc -l aicut.py gui/server.py gui/static/*.js` → `/ecc:code-review` 或 `ecc:python-reviewer` + `ecc:typescript-reviewer`（JS）无 CRITICAL/HIGH → commit + push → 等 CI 绿。行号均为 HEAD `ae810ae` 的位置，前面的 Task 合入后会偏移——**按函数名 / 文本锚点定位**。任何手工冒烟一律按上文「冒烟 / 手工测试的硬规则」。

### ===== M14a 后端地基（界面不变，M13 暂住的 ⑤⑥ 照常可用）=====

### Task 0: 基线 + 腾行数（行为不变）
- **ACTION**: 先跑 `uv run pytest -q` 记录基线（应 2637 passed）。然后：`cmd_calibrate` 主体搬到 `pipeline/project_cli.calibrate(pdir, c, args, *, ok, ask)`；`cmd_export` 里 `name = …` 到 `ok(f"已导出…")`（`aicut.py:503-514`）搬到 `pipeline/outputs.package_windows(timeline, name, out, *, info, warn) -> dict`（新文件，此时只有这一个函数 + 文案常量）。
- **IMPLEMENT**:
  ```python
  # aicut.py
  def cmd_calibrate(args) -> None:
      """运行时校准剪辑偏好；不传参数则交互式问答。"""
      pdir = project_dir(args.name)
      project_cli.calibrate(pdir, cfg(pdir), args, ok=ok, ask=ask_calibration)
  ```
  `package_windows` 内部保留原样的 `info("生成草稿并打包…")`、`export_draft.build_windows_package`、逐条 `warn`、`(RuntimeError, FileNotFoundError)` → 抛 `outputs.PackageFailed(str(exc))`，由 cmd_export `die`。
- **MIRROR**: DELEGATED_CLI。
- **IMPORTS**: `aicut.py` 加 `outputs`（同一 import 行，`aicut.py:38`）；`packaging/ai-cut.spec` 加 `"pipeline.outputs"`。
- **GOTCHA**: `tests/test_aicut_build.py::test_cmd_export_shows_to_jianying_warnings`（297 行）打桩 `export_draft.build_windows_package`——搬家后要打桩 `outputs.export_draft.build_windows_package` 或保持 `outputs` 内 `from pipeline import export_draft` 并以模块属性调用（推荐后者，原测试的 `monkeypatch.setattr(aicut.export_draft, ...)` 仍然生效，因为是同一个模块对象）。`ask_calibration` 在 aicut 上有再导出守卫（`tests/test_structure.py:28-33`），保留。目标：aicut.py ≤ 735 行。
- **VALIDATE**: `uv run pytest tests/test_aicut_build.py tests/test_aicut_cli.py tests/test_style.py tests/test_structure.py -q` 全绿且未改任何断言。

**Commit A0**：`refactor: move calibrate and windows packaging bodies out of aicut.py`

### Task 1: 镜头差异（pipeline/shot_diff.py）
- **ACTION**: 先写 `tests/test_shot_diff.py`（纯函数，表驱动）：
  1. 两张一样的表 → 全空、`reordered=False`、`count == 0`；
  2. 只改一镜字幕（首尾空白不算）→ `sub_changed=[{before, after}]`；
  3. 入出点挪 0.04 秒 → 不算；挪 0.2 秒 → `retimed`；
  4. id 相同但时间完全不重叠（AI 两次选段都叫 `sel03`）→ 一删一增，不当改字幕；
  5. id 不同、时间重叠率 ≥ 0.5（手动复制后改 id）→ 配上；< 0.5 → 一删一增；
  6. 两镜互换位置 → `reordered=True`，`count == 1`；
  7. `describe(d, limit=8)` → `["新增第 7 镜「…」", "删除了 00:52 那一镜", "第 4 镜改了字幕", "第 2 镜改了入出点", "调整了镜头顺序"]`，字幕截 `DESCRIBE_SUB_CHARS = 12` 字，超过 limit 只给前 limit 条 + `more`；
  8. 不改入参（传入后原列表与 dict 不变）。
- **IMPLEMENT**:
  ```python
  PAIR_MIN_IOU = 0.5          # 时间重叠率（交 / 并）达到这么多才算同一镜（E8）
  RETIME_TOLERANCE_S = 0.05   # 入出点变化小于这个不算改（入出点保留两位小数）
  DESCRIBE_SUB_CHARS = 12
  ADDED = "新增第 {n} 镜「{sub}」"; REMOVED = "删除了 {tc} 那一镜"; SUB_CHANGED = "第 {n} 镜改了字幕"
  RETIMED = "第 {n} 镜改了入出点"; REORDERED = "调整了镜头顺序"
  def pair(old: list[dict], new: list[dict]) -> list[tuple[int, int]]
  def diff(old: list[dict], new: list[dict]) -> dict   # {added, removed, sub_changed, retimed, reordered}
  def count(d: dict) -> int
  def describe(d: dict, new: list[dict], limit: int = 8) -> tuple[list[str], int]   # (行, 余下几条)
  ```
  镜号 `n` = 在 `new`（删除的用 `old`）里的位置 +1；时间码 `mm:ss`。
- **MIRROR**: `pipeline/exclusions.py:48-66`（纯函数、不改入参）；`pipeline/select.py:202-214`（时间码 / 截字的人话写法）。
- **IMPORTS**: 无（纯 Python）。
- **GOTCHA**: 配对先 id+重叠、再 IoU 贪心，**按 IoU 降序**挑，避免先到先得配错；入出点可能是 int（手写 JSON）→ 一律 `float()`；`sub` 可能缺失 → `""`。
- **VALIDATE**: `uv run pytest tests/test_shot_diff.py -q`

### Task 2: 分镜表存储（锁、基线、备份）+ `/api/shots` 接入
- **ACTION**: 先写 `tests/test_shots_store.py` 与 `tests/test_result_api.py::test_shots_*`：
  1. `locked(pdir)` 可重入于不同线程顺序执行；文件锁文件 `.aicut-shots.lock` 权限 0600；`fcntl.flock` 抛 `OSError` 时 warning 放行（打桩）；
  2. `current(pdir)` → `(shots, "manual")` / `(shots, "selection")` / `([], None)`；`shots.json` 损坏 → 抛 `CorruptJSON`（不当没有）；
  3. `write_manual(pdir, shots, raw_meta)`：`shots.json` 不存在时同时写 `work/manual_base.json = {"shots": <shots-selected 的 shots 或 []>, "at"}`；已存在时不动基线；
  4. `drop_manual(pdir, reason)`：先 `backup(pdir, reason)` 写 `work/shots_backups/<YYYYmmddTHHMMSSZ>-<reason>.json`，再删 `shots.json` 与基线；没有 `shots.json` → 返回 `None`、什么都不做；第 11 份备份写入后只剩最近 10 份；
  5. `manual_changes(pdir)` → `{"edited": bool, "count", "changes": [...], "more"}`：无手动表 → `edited=False`；有手动表、count == 0 → `edited=False`（⚑Q5：一样的表不算改过）；无基线（旧项目）→ 与当前 AI 选段比；
  6. `POST /api/shots`：第一次保存写出基线；这个项目有 `select` 任务在跑（打桩 `jobs.project_job` 返回 `{"task": "select"}`）→ 409 `SHOTS_BUSY_MSG`、文件不变；其它任务在跑 → 照常保存。
- **IMPLEMENT**（`pipeline/shots_store.py`）：
  ```python
  LOCK = threading.Lock()            # 保留：现有调用方不改名
  FILE_LOCK = ".aicut-shots.lock"
  BASE_FILE = "work/manual_base.json"
  BACKUP_DIR = "work/shots_backups"
  BACKUP_KEEP = 10
  SHOTS_BUSY_MSG = "正在重新选段，完成后再改分镜表"
  @contextlib.contextmanager
  def locked(pdir: Path) -> Iterator[None]      # with LOCK: flock(LOCK_EX)（阻塞，最多等任务写完那一下）
  def current(pdir: Path) -> tuple[list[dict], str | None]
  def write_manual(pdir: Path, shots: list[dict], meta: dict) -> None   # 调用方已持 locked
  def backup(pdir: Path, reason: str) -> Path | None
  def drop_manual(pdir: Path, reason: str) -> Path | None             # 调用方已持 locked
  def manual_changes(pdir: Path, limit: int = 8) -> dict
  ```
  `gui/server.py` 的 `/api/shots`（436-462）：`existing_project` 之后 `if (j := jobs.project_job(name)) and j["task"] == "select": return 409`；`with shots_store.locked(pdir): shots_store.write_manual(pdir, clean, {...})`。`gui/project_routes.py` 里两处 `with shots_store.LOCK:`（349、382）改成 `with shots_store.locked(pdir):`，`_restore_manual_shots` 不新建表的语义不变。
- **MIRROR**: FILE_LOCK_PATTERN、REPOSITORY_PATTERN。
- **IMPORTS**: `fcntl, os, contextlib, threading, datetime`；`from pipeline import schema, shot_diff, applog`。
- **GOTCHA**: `locked` 里**先拿线程锁再拿文件锁**，释放顺序相反，避免同进程两线程都去 flock；flock 用**阻塞**模式（不是 `LOCK_NB`）——跨进程方是 `aicut select --manual=replace` 的一次删文件，很快；备份文件名用 UTC，避免时区重复；`manual_changes` 读不出基线 / 表 → `edited=False` 且带 `error`（不抛：它在 `/api/state` 里用）。server.py 净增 ≤ 8 行。
- **VALIDATE**: `uv run pytest tests/test_shots_store.py tests/test_result_api.py -k shots tests/test_server_save.py tests/test_unusable.py tests/test_browse_marks.py -q`

### Task 3: 预览暂存与版本晋升（pipeline/outputs.py + 指纹）
- **ACTION**: 先写 `tests/test_outputs.py` 与 `tests/test_fingerprints.py` 增补：
  1. `fingerprints.table_digest(shots)` 只看 `[id, in, out, sub]`（`note` 变了不变）；`unusable_digest(work)` 只看 `unusable is True` 的 id 集合；`preview_inputs(pdir, cfg)` 键 = `("table", "unusable", "preset", "material")`，手动表优先，没有用 AI 选段，都没有 → `table == ""`；`shots.json` 损坏 → `"corrupt"`（不抛）；
  2. `outputs.write_stamp(staging, inputs, shots, duration)` / `read_stamp(dir)`（损坏 → `None`）；
  3. `outputs.preview_state(pdir, cfg)` → `{"status": "none"|"fresh"|"outdated", "reasons": [...分项名], "at", "duration", "shots"}`；`outdated` 的 `reasons` 用 `fingerprints.changed`；
  4. `outputs.promote(staging, vdir)`：五个文件（`timeline.json`、`shots_snapshot.json`、`preview.mp4` 及其完成标记、`.timeline.sha`、`preview.json`）出现在 `vdir`，与暂存是同一 inode（`os.stat().st_ino` 相等）；`os.link` 抛 `OSError` 时退回复制；目标已存在时被替换；暂存里缺 `preview.mp4` 完成标记 → 抛 `PreviewMissing`；
  5. `outputs.mark_export(vdir, "mac", draft=…)` / `read_exports(vdir)` → `{"mac": …, "windows": …}`，旧版本无文件 → `None`（= legacy）；
  6. `outputs.matching_version(pdir, inputs)` → 最大的 `vN` 使 `vN/preview.json.inputs == inputs`，没有 → `None`；
  7. `outputs.windows_zip(pdir, version, title)` 与原 `jobs.windows_zip` 完全一致（把 `tests/test_server_export.py:133-145` 两个纯函数测试改成同时断言两边相等）。
- **IMPLEMENT**:
  ```python
  PREVIEW_DIR = "preview"                     # output/preview：当前分镜表的预览片暂存（不是版本，E1）
  STAMP_FILE = "preview.json"
  EXPORT_FILE = "export.json"
  PROMOTED = ("timeline.json", "shots_snapshot.json", "preview.mp4", ".timeline.sha", STAMP_FILE)
  PREVIEW_STALE = "分镜表在生成预览片之后改过了：先在「⑤ 看结果」重新生成预览片，再导出"
  PREVIEW_NONE = "还没有当前分镜表的预览片：先在「⑤ 看结果」生成预览片"
  def staging_dir(pdir: Path) -> Path
  def write_stamp(d: Path, inputs: dict, shots: int, duration: float) -> None
  def read_stamp(d: Path) -> dict | None
  def preview_state(pdir: Path, cfg: dict) -> dict
  def promote(staging: Path, vdir: Path) -> None
  def mark_export(vdir: Path, kind: str, **info) -> None     # 读改写 export.json（原子）
  def read_exports(vdir: Path) -> dict | None
  def matching_version(pdir: Path, inputs: dict) -> str | None
  def windows_zip(pdir: Path, version: str, title: str | None) -> Path
  ```
  `jobs.windows_zip` 改为 `return outputs.windows_zip(...)`（`_UNSAFE_FILENAME`、`ZIP_TITLE_MAX_CHARS` 搬过去，jobs 里保留同名别名以免测试断裂）。
- **MIRROR**: `pipeline/fingerprints.py:30-83`；`pipeline/clips.py:128-137`（快照读写）；`media_io.done_marker` 的完成标记约定。
- **IMPORTS**: `from pipeline import fingerprints, media_io, schema, shots_store, export_draft`。
- **GOTCHA**: `preview_inputs` 读当前表**不能**调 `shots_store.current`（它对损坏抛异常）→ 用宽松读 + 损坏记 `CORRUPT`；完成标记文件名以 `media_io.done_marker(path)` 为准，不要硬写；`promote` 先在 `vdir` 写临时名再 `os.replace`，单个文件失败时已替换的保留（下一次晋升会覆盖），抛错由 build `die`。
- **VALIDATE**: `uv run pytest tests/test_outputs.py tests/test_fingerprints.py tests/test_server_export.py -q`

### Task 4: `aicut preview` + `build` 拆成「暂存 → 晋升」
- **ACTION**: 先写 `tests/test_preview_export.py`（打桩方式同 `tests/test_aicut_build.py:331-350`）：
  1. `aicut preview p`：在 `output/preview/` 写出时间线、快照、预览片、`preview.json`（`inputs` = 开始时的 `preview_inputs`）；**不**新建任何 `output/v*`；必留缺失 / 全部被不可用剔除 → `[x]` 退出 1 且不写戳；渲染失败 → 不写戳（旧戳保持）；
  2. 同一张表连跑两次 `preview` → 第二次「预览片无变化，跳过渲染」（`ensure_preview` 收到相同哈希）；
  3. `aicut build p`（CLI，无旗标）：暂存（必要时重渲染）→ 晋升到 `v1` → 装草稿 → `v1/export.json.mac.draft == "<片名>_v1"`；`--no-draft` → `export.json.mac is None`；
  4. `aicut build p --require-preview`：暂存戳与当前不一致 → `[x] PREVIEW_STALE`、不新建版本、不调用切片 / 渲染；一致 → 不渲染，直接晋升；
  5. `aicut build p --windows --no-draft --require-preview`：晋升后打 Windows 包到 `outputs.windows_zip(pdir, v, title)`，`export.json.windows.zip` 写入；打包失败 → `[x]`，版本目录保留（时间线已在），`export.json.windows` 不写；
  6. `aicut build p --version v1 --windows --no-draft --require-preview`（⚑Q1 复用）：不新开 `v2`，`v1/export.json` 同时有 `mac` 与 `windows`；
  7. `aicut export p`（不带 `--timeline`）：最新时间线只在 `output/v*/` 里找，不会挑中 `output/preview/`；
  8. `tests/test_e2e_draft.py`：现有 `build` / `build --no-draft` 用例照常通过；新增一段：`preview` → `build --require-preview` → 版本里的 `preview.mp4` 与暂存同一 inode、草稿名 `<片名>_v1`。
- **IMPLEMENT**（aicut.py，按函数拆，编排留在 aicut、细节进 outputs）：
  ```python
  def _current_shots(pdir: Path) -> tuple[list[dict], bool]:   # 原 cmd_build 573-597：取表 + 必留 + 不可用剔除；返回 (shots, 来自选段)
  def _stage(pdir: Path, c: dict, preset: dict, shots: list[dict]) -> Path:  # 原 598-616 的磁盘预检、锁内切片 / 时间线 / 快照、预览；目录 = outputs.staging_dir
  def cmd_preview(args) -> None:
      pdir = project_dir(args.name); c = cfg(pdir)
      inputs = fingerprints.preview_inputs(pdir, c)        # 开始时取（E2）
      shots, _ = _current_shots(pdir)
      staging = _stage(pdir, c, load_preset(c["preset"]), shots)
      outputs.write_stamp(staging, inputs, len(shots), _total(staging))
      ok(f"预览片：{staging / 'preview.mp4'}（不产生版本）")
  def cmd_build(args) -> None:
      # require_preview：戳 != 当前 → die(outputs.PREVIEW_STALE / PREVIEW_NONE)；否则 cmd_preview(args) 同样的暂存
      # version = args.version or next_version(pdir)；outputs.promote(staging, vdir)
      # 非 no_draft 且 export.json 里还没有 mac：install_draft(...) → outputs.mark_export(vdir, "mac", draft=name)
      # getattr(args, "windows", False)：outputs.package_windows(...) → mark_export(vdir, "windows", zip=…)
  ```
  `cli_args`：`preview` 加进 `NAME_ONLY`；`build` / `run` 增 `--windows`、`--require-preview`。`cmd_build` 里所有新属性用 `getattr(args, "...", False)`（`cmd_run` 透传的 args 没有它们，`aicut.py:669-675`）。
- **MIRROR**: SERVICE_PATTERN（护栏 → 锁内 → 预览 → 草稿；戳最后写）。
- **IMPORTS**: 已在 T0 加 `outputs`；`fingerprints` 已导入（`aicut.py:38`）。
- **GOTCHA**:
  - 暂存目录名 `preview` 被 `next_version`（数字校验）与 `views._versions`（`glob("v*")`）排除；`cmd_export` 默认时间线的 `glob("*/timeline.json")`（`aicut.py:490`）**必须**改成只认 `v<数字>`。
  - `ensure_preview` 的复用依赖 `.timeline.sha` 与完成标记——暂存目录照用；晋升后版本目录里的 `.timeline.sha` 与预览一致，旧的「覆盖已有版本」路径（`--version v1` 重跑）仍然复用。
  - `build_need`（`aicut.py:174-178`）现在按版本目录算预览空间 → 改为按暂存目录算；晋升是硬链接，不再算一份预览。
  - **`--require-preview` 路径不调用 `ensure_clips`**，但 Windows 打包前仍要 `clips.restore_missing`（清理缓存后切片可能没了，`aicut.py:498-501` 的现有逻辑搬进 `package_windows` 之前调用）。
  - Mac 草稿同名（KI-59）：`--version vK` 复用且 `export.json.mac` 已有 → 跳过装草稿并 `info("这一版已经在 Mac 剪映里：…")`，不报错。
  - aicut.py 最终 ≤ 800（T0 后约 735，本 Task 预算 +55）。超了就把 `_stage` 的锁内部分搬进 `outputs.stage_timeline(...)`，保留 `ensure_clips` / `compose_timeline` / `ensure_preview` 在 aicut 上被调用（测试打桩点）。
- **VALIDATE**: `uv run pytest tests/test_preview_export.py tests/test_aicut_build.py tests/test_aicut_must_keep.py tests/test_unusable.py tests/test_clips_restore.py tests/test_e2e_draft.py tests/test_structure.py -q`

### Task 5: 选段 `--manual` + 未采用原因 + 任务参数
- **ACTION**: 先写测试：
  1. `select.select()` 的 `unused[i]["cause"]`：话题被排除 → `"excluded"`；话题一镜都没入选 → `"not_must"`；话题有入选 → `"duration"`；`reason` 文本保持原样（旧断言不破）；
  2. `aicut select p --manual=replace`：选段成功后 `shots.json` 被备份并删除、基线一并删；选段失败（`SelectionError`）→ `shots.json` 原样；没有 `shots.json` → 无事发生；`--manual=keep`（默认）→ `shots.json` 不动；非法值 → argparse 报错；
  3. `jobs.job_extra`：`select` + `{"manual": "replace"}` → `["--manual=replace"]`；`{"manual": "keep"}` → `["--manual=keep"]`；其它值 → `ValueError("manual 只能是 replace 或 keep")`；与 `target` 可同时给；
  4. `jobs.job_extra`：新任务 `preview` → `[]`；`build` + `{"target": "mac"}` → `["--require-preview"]`（无匹配版本）或 `["--require-preview", "--version", "v3"]`（`matching_version` 命中，⚑Q1）；`{"target": "windows"}` → 再加 `["--windows", "--no-draft"]`；`target` 缺省 → 旧参数（M13 暂住界面还在用，M14c 再改为必填）；预览片不是当前的 → `ValueError(outputs.PREVIEW_STALE)`（→ 400）；命中的版本已有 `mac` 且 `target == "mac"` → `ValueError(ALREADY_IN_JIANYING.format(draft=…))`；
  5. `settings.check_ready(pdir, "build", {"target": "mac"})`：打桩 `to_jianying.jianying_running` 返回 True → `PrepareBlocked("close_jianying", JIANYING_RUNNING_MSG)`；`target == "windows"` 不检查；
  6. `POST /api/confirm/answers {confirmed: true, manual: "replace"}` → 起的选段任务参数含 `--manual=replace`；非法 `manual` → 400 且答案**不**落盘（先校验再写）；
  7. `JOB_COMMANDS["preview"] == ["preview"]`，`TASK_LABELS["preview"] == "生成预览片"`。
- **IMPLEMENT**:
  - `pipeline/select.py` 未采用（450-456）加 `"cause"`（常量 `CAUSE_EXCLUDED / CAUSE_NOT_MUST / CAUSE_DURATION`）；`with_lines = _with_lines`（公开别名，⑤ 加回算字幕用）。
  - `aicut.cmd_select`：选段与保存新目标之后，`if getattr(args, "manual", "keep") == "replace": outputs.replace_manual(pdir)`（= `with shots_store.locked(pdir): shots_store.drop_manual(pdir, "replace")`，有备份则 `info(MANUAL_REPLACED.format(path=…))`）。
  - `gui/jobs.py`：`JOB_COMMANDS["preview"]`、`TASK_LABELS["preview"]`；`job_extra` 的 `select` 分支收 `manual`，`build` 分支委托 `outputs.build_args(pdir, body, cfg)`；`_start_job`（server.py:278-296）把 `body` 传给 `settings.check_ready(pdir, task, body)`。
  - `gui/confirm.py`：`manual = _check_manual(body.get("manual"))`（在写盘前），起任务时 `extra = [f"--manual={manual}"]`。
- **MIRROR**: `gui/jobs.py:467-479`（白名单翻译参数）；`gui/settings.py:41-65`（前置检查表）。
- **IMPORTS**: `gui/settings.py`：`from pipeline import to_jianying`（只用 `jianying_running`；注意它 import 时读 `AI_CUT_DRAFT_ROOT`——只在函数里调用，不改模块级状态）。
- **GOTCHA**: `--manual=replace` 必须在**选段成功之后**才删（失败时 die 已经退出）；`confirm.save_answers` 现在「先写答案再起任务」，`manual` 校验要放在写答案之前，否则非法值会留下半个确认；`build_args` 用的 `cfg` 来自 `jload(project.json)`，读不出时让 `existing_project` 早已 409。
- **VALIDATE**: `uv run pytest tests/test_select.py tests/test_preview_export.py tests/test_server_jobs.py tests/test_server_export.py tests/test_confirm_flow.py tests/test_server_config.py -q`

**Commit A1**：`feat(gl-26,ki-95): preview staging, export promotes preview to a version, manual shot table lock and replace mode`

### Task 6: ⑤⑥ 接口 + 版本卡片数据 + KI-98 / KI-100 后端
- **ACTION**: 先写 `tests/test_result_api.py`、`tests/test_versions_view.py`、`tests/test_jy_version.py` 增补：
  1. `GET /api/result?project=p1`（造 scored + overrides + selection + shots-selected）：
     - `topbar = {target, total, shots, clip: {count, covered, missing: [ids]}, over_target, must_total, suggested_target}`：剪辑列表段被当前表覆盖才算 covered（`select.uncovered_must_keep`）；不可用的剪辑列表段不计；
     - `notes = {shot_id: {why, topic, segment_id, alternatives: [{id, start, end, text}]}}`：AI 选段的镜头 `why` = selection 里该镜的 `reason`；手动加回 / 手动挪过的镜头按与片段重叠找 `level_reason`，找不到 → `"手动添加"`；替代句 = 同话题未采用段前 3 条（⚑Q7）；
     - `unused`：含 `cause / cause_label / shot{in,out,sub}`；有手动表时以手动表为准；被手动删掉的 AI 段 → `cause="removed"`；不在当前表的剪辑列表段排最前 `cause="must"`；不可用段不出现；level 1/2 不出现；
     - `preview`：`outputs.preview_state` + `url = "/media/<项目>/current-preview?v=<at>"`（`status == "none"` 时 `url = null`）；
     - `manual = shots_store.manual_changes(pdir)`；`source`；`wizard`；
     - 坏项目名 400、不存在 404、`overrides.json` 损坏 409、还没分析（无 scored）→ 200 且 `unused=[]`、`notes={}`（纯手工流程也能看 ⑤）。
  2. `POST /api/result/restore-ai {project}`：有手动表 → 备份 + 删除（基线一并删）→ `{ok, backup, wizard}`；没有 AI 选段（无 `shots-selected.json`）→ 409 `NO_AI_SELECTION_MSG` 且文件不变；有任务在跑 → 409；没有手动表 → 200 `{ok, backup: null}`。
  3. `GET /api/versions/compare?project&a=v1&b=v2`：两版都有快照 → `diff`（`shot_diff.diff(a, b)`）+ 两边 `{name, preview, shots, duration, has_snapshot}`；任一缺快照 → `diff: null`、`note = COMPARE_NO_SNAPSHOT`；`a == b` → 400；版本号非法 → 400；不存在 → 404。
  4. `POST /api/versions/restore {project, version}`：写 `shots.json` = 该版快照（`schema.clean_shots`），先备份当前手动表（`restore-vN`），没有基线时写基线；快照里与不可用片段重叠的镜头剔除并在 `dropped` 列出（⚑Q3）；剔完为空 → 409；无快照 → 409 `RESTORE_NO_SNAPSHOT`；有任务在跑 → 409；**不删除任何版本目录**（断言 `output/` 下目录集合不变）。
  5. `/api/state.versions[]` 新字段：`exports`（`read_exports`）、`legacy`（无 `export.json`）、`current`（E6）、`has_snapshot`、`unusable_hits`（`exclusions.timeline_hits`；`ExclusionError` → `None` 且 `blocked = str(exc)`）、`blocked`（hits > 0 → `EXPORT_BLOCKED.format(n)`）；**KI-102**：`draft` 字段只在 `exports.mac` 存在或 `legacy` 时给，`--no-draft` 出的新版本 `draft is None`。
  6. `/api/state` 新字段：`manual`、`preview`（只有 `status`）、`jianying = {"installed": bool}`（打桩 `jy_version.find_app`；第二次调用在缓存期内不再调用）。
  7. `POST /api/open {target: "jianying"}`：`find_app()` 返回路径 → `open -a <路径>`（打桩 `subprocess.run` 断言参数）；返回 `None` → 404 `JIANYING_NOT_FOUND`；`{target: "export", version}` 且该版 `unusable_hits > 0` 或无法确认 → 409 `EXPORT_BLOCKED`，不调用 `open`。
  8. `GET /media/<p>/current-preview` → 发 `output/preview/preview.mp4`；不存在 → 404；路径穿越（`%2F`）同 GL-21 测试。
  9. `jy_version.find_app(candidates, runner)`：候选里有就返回；没有时解析 `mdfind` 输出（打桩 runner：多行、含 `~/.Trash/…`、不存在的路径、非 `.app`）；`mdfind` 超时 / 不存在 → `None`。
- **IMPLEMENT**:
  - `gui/result_payload.py`：`result(pdir, name) -> dict`、`compare(pdir, a, b) -> dict`；纯数据组装，读盘用 `schema.read_json` / `review.apply`（同 `gui/payloads.py:22-34`）；文案常量 `CAUSE_LABELS = {"must": "剪辑列表里的片段 · 出片前必须加回", "removed": "你从分镜表里删掉了", "excluded": "你在决策问题里排除了这个话题", "not_must": "未勾选为必须记住的信息", "duration": "因时长：这个话题的时长已经用完", "other": "没有进片"}`（⚑Q4）、`LEGACY_REASON_CAUSE = {"话题未入选": "excluded", "超出话题预算": "duration", "不在候选池": "other"}`、`MANUAL_WHY = "手动添加"`、`ALTERNATIVES_MAX = 3`、`IN_CUT_OVERLAP_S = 1.0`（与 `payloads.in_cut` 同值，注释写明）。
  - `gui/result_routes.py`：四个路由；写类先 `jobs.project_job(name)` 判忙 → 409 `BUSY_MSG = "这个项目正在{label}，完成后再试"`；写都在 `shots_store.locked(pdir)` 内。
  - `gui/views.py`：`_versions` 增字段；`project_state` 增 `manual / preview / jianying`；`jianying` 用模块级 `(at, value)` 缓存。
  - `gui/server.py`：`result_routes.handle_get/handle_post` 委托（各一行，放在 `project_routes` 之后）；`/api/open` 的 jianying 分支与 export 分支；媒体路由加 `current-preview`。
  - `pipeline/jy_version.py`：`BUNDLE_ID = "com.lemon.lvpro"`、`MDFIND_TIMEOUT_S = 3`、`find_app(candidates=APP_CANDIDATES, runner=subprocess.run) -> Path | None`；`installed_version` 改为先 `find_app()` 再读 plist（保持原签名与测试）。
- **MIRROR**: ROUTE_MODULE、ERROR_HANDLING、REPOSITORY_PATTERN；`gui/views.py:30-48`（版本卡片宽松读）。
- **IMPORTS**: `gui/result_payload.py`：`from pipeline import exclusions, outputs, review, schema, select, shot_diff, shot_sub, shots_store, topic_names`；`gui/result_routes.py`：`from gui import jobs, result_payload, wizard`；`packaging/ai-cut.spec` 加四个模块名。
- **GOTCHA**:
  - `/api/state` 每 0.9 秒被任务轮询间接触发刷新：`manual_changes` / `preview_state` / `_versions` 的 `timeline_hits` 都要便宜；`timeline_hits` 在**没有任何不可用标记时直接返回 0、不读快照**（`pipeline/exclusions.py:105-110` 已是如此），保持。
  - `views._versions` 里 `ExclusionError` 不能让 `/api/state` 失败（只标 `blocked`）。
  - 替代句、未采用的文字截 `payloads.SEGMENT_TEXT_MAX_CHARS`（400）字，不整段灌给界面。
  - `conftest.py` 已有 `_no_real_jianying_version` autouse（`tests/conftest.py:136-142`）——`find_app` 也要被它挡住：在该夹具里同时把 `jy_version.find_app` 打桩成返回 `None`（`test_jy_version` 自己显式传参不受影响）。
  - server.py 目标 ≤ 610 行。
- **VALIDATE**: `uv run pytest tests/test_result_api.py tests/test_versions_view.py tests/test_jy_version.py tests/test_server_export.py tests/test_server_media.py tests/test_server_security.py tests/test_views.py tests/test_structure.py -q`

### Task 7: `derive()` 准备 ⑤⑥ 的事实（规则先不启用）
- **ACTION**: 先写 `tests/test_wizard_state.py` 增补 `collect()` 读盘用例：`preview_fresh` / `has_versions` / `exported_current` 按「步骤状态判定」新增 Facts 一节计算；`digests=False` 也算预览事实；`shots.json` 损坏 → `preview_fresh=False`、不抛；`collect` 不写任何文件（目录快照前后相同）。`derive()` 的现有表驱动用例**全部不变**（本 Task 只加事实，不改规则，保证 M13 暂住界面行为不变）。
- **IMPLEMENT**: `wizard.collect` 增四个键；`derive` 不读它们（M14b / M14c 再接）。
- **MIRROR**: `gui/wizard.py:45-68`。
- **IMPORTS**: `from pipeline import outputs`。
- **GOTCHA**: `outputs.preview_state` 用 `media_io.is_complete`，不能调 `complete_or_adopt`（会写完成标记）。
- **VALIDATE**: `uv run pytest tests/test_wizard_state.py tests/test_views.py -q`

**Commit A2**：`feat(gl-27,ki-94,ki-98,ki-100,ki-102): result and version APIs, jianying detection, unusable version guard`（M14a 结束：旧界面照常可用；「打开剪映」已改为检测路径；含不可用的旧版本已拦 zip 定位）

### ===== M14b ⑤ 看结果 =====

### Task 8: 前端文件拆分与骨架
- **ACTION**: 先改守卫：`tests/test_static_pages.py` 的 `INDEX_SCRIPT_ORDER`、`tests/fe_harness.py` 的 `SCRIPTS` 加入 `reselect.js`、`result-table.js`、`result-unused.js`（位于 `step-criteria.js` 系列之后、`step-result.js` 之前；`export-compare.js` 在 M14c 加）；`tests/test_frontend_js.py:93` 读 `SHOT_ID_RE` 改为 `result-table.js`；`STATIC_FILES` 同步。
- **IMPLEMENT**: 把现 `step-result.js` 的分镜表部分（62-133：`viewShots` 行渲染、`pick / seekNoSwitch / edit / SHOT_ID_RE / nextShotId / renumber / move / dup / del / addBlank / sortShots`）与播放器 / 入出点（18-60）原样迁到 `result-table.js`；`step-result.js` 暂时只留 `viewResult()` 调旧渲染 + `openTarget / saveTarget`，保证这一步行为不变；`#shotbar` 先保留。
- **MIRROR**: M13 T11 的拆分方式（原样迁移，只改容器 id）。
- **IMPORTS**: `gui/static_files.py`、`index.html`。
- **GOTCHA**: `tests/test_static_pages.py::test_every_index_script_is_loaded_by_some_page` 与白名单守卫要同时改；迁移后立刻跑全部前端测试确认零行为变化，再进入 T9。
- **VALIDATE**: `uv run pytest tests/test_static_pages.py tests/test_frontend_js.py tests/test_frontend_steps.py -q`

### Task 9: ⑤ 页面：顶栏、改时长、预览片、闸门 B
- **ACTION**: 先写 `tests/test_frontend_result.py`（node；`fe_fixtures` 增 `RESULT_PAYLOAD` 与 `in_result(script, routes)`）：
  1. 进入 ⑤ → `GET /api/result?project=…` 一次；顶栏文字「目标 3:00 · 当前 2:58 · 镜头 18 · 剪辑列表 6/6 进片 ✓」，数字全部过 `num()`；剪辑列表没覆盖全 →「剪辑列表 5/6 进片」+ `.warn`；
  2. 超目标：警告条「剪辑列表共 3 分 40 秒，超过目标 3 分 0 秒 · 建议改为 3 分 40 秒」+ 按钮 `data-act="applySuggested"`；
  3. 「改」→ 顶栏就地出现分 + 秒输入（`durationFields('tgt', …)`）与「确定」「取消」；确定 → 调 `confirmReselect({target})`（T12），**没有手动修改**时直接 `POST /api/job {task:'select', target, manual:'replace'}`（⚑Q5：一样的表直接覆盖；没有手动表时也带 `replace`，服务端无表即无事）；非法时长 → toast `COPY_TARGET_RANGE`、不发请求；
  4. 预览片区：`status=none` →「还没有预览片」+「生成预览片」(`data-act="makePreview" data-starts-job`)；`fresh` → `<video src=…current-preview?v=…>`；`outdated` →「分镜表改过了 · 重新生成预览片」（原因 `unusable` 时文案「有片段标成了不可用 · 重新生成预览片」）；
  5. `makePreview()`：先 `flushPendingSave()`，失败 → toast 且不起任务；成功 → `startJob('preview')`（不弹日志窗口，只在胶囊）；任务完成且仍在 ⑤ → 重拉 `/api/result` 并切到预览片模式；
  6. 闸门 B：底部导航右侧是「看过了，去导出 →」：`preview.status !== 'fresh'` → `aria-disabled="true"` + `title = COPY_GATE_B_HINT`；`fresh` → `data-act="go" data-step="export"`；
  7. 切项目 / 离开 ⑤：在途 `/api/result` 回包被丢弃（序号）；离开前 `flushPendingSave()`（保留 `app.js:109` 现有规则）；
  8. `jobs.js`：`JOB_TITLES.preview = '正在生成预览片'`、`JOB_DONE.preview = '预览片已生成'`；**删除**选段完成后自动弹改时长（E16）——`tests/test_static_pages.py::test_over_target_modal_opened_after_job` 改为断言 `openTarget(true)` 不再出现。
- **IMPLEMENT**（`step-result.js`）：`viewResult()`（两栏骨架：左 `#rTable`、右上 `#rPlayer`、右下 `#rUnused`，顶栏 `#rTop`）、`enterResult()` / `loadResult()`（`resultSeq`）、`renderTop()`、`openTargetInline() / applyTarget() / applySuggested()`、`renderPreview()`、`makePreview()`、`resultGateHtml()`；`wizard.js::renderNav` 在 `viewing === 'result'` 时用 `resultGateHtml()`（同 `criteria` 的写法，`wizard.js:111`）。文案常量：`COPY_TOP = '目标 {target} · 当前 {total} · 镜头 {n} · 剪辑列表 {c}/{m} 进片'`、`COPY_TOP_CHANGE = '改'`、`COPY_OVER = '剪辑列表共 {must}，超过目标 {target} · 建议改为 {suggest}'`、`COPY_OVER_APPLY = '改为 {suggest}'`、`COPY_PREVIEW_NONE = '还没有预览片'`、`COPY_PREVIEW_MAKE = '生成预览片'`、`COPY_PREVIEW_OUTDATED = '分镜表改过了 · 重新生成预览片'`、`COPY_PREVIEW_UNUSABLE = '有片段标成了不可用 · 重新生成预览片'`、`COPY_GATE_B = '看过了，去导出 →'`、`COPY_GATE_B_HINT = '先生成当前分镜表的预览片'`、`COPY_ANALYSIS_UPDATED_MANUAL = '分析结果更新了：分镜表仍是你手动改的那一版；需要时点「恢复为 AI 选段」'`（⚑Q6，`source==='manual'` 且 ⑤ 的 `reasons` 含 `scored` 时显示）。
- **MIRROR**: FRONTEND_PATTERN；`gui/static/step-result.js:136-157`（`durationFields` / `readDuration` 的用法）。
- **IMPORTS**: —（全局函数：`durationFields / readDuration`（project-form.js）、`startJob`（jobs.js）、`confirmReselect`（reselect.js））。
- **GOTCHA**: 预览片 `<video>` 的 `src` 带 `?v=<at>` 防缓存；轮询刷新（`refresh()` → `renderView()`）不能重建正在播放的 `<video>`——⑤ 的播放器与 `#shotbar` 一样**只在换项目 / 预览片换了 / 模式切换时重建**（`stageIs` 缓存外另记 `playerFor = project + at + mode`）；顶栏数字随本地编辑实时变（`当前` 用 `state.shots` 求和），覆盖率等服务端数字在保存后重拉更新。
- **VALIDATE**: `uv run pytest tests/test_frontend_result.py tests/test_frontend_jobs.py tests/test_static_pages.py -q`

### Task 10: 分镜表（为什么选它、替代句、选中行设入出点、播放器模式）
- **ACTION**: 先写 `tests/test_frontend_result.py` 增补：
  1. 每行：镜号、`入点–出点`、时长、字幕 `<textarea data-input="editSub">`、小字「为什么选它：<why> · <topic>」（`notes[id]` 缺失 → 不显示这一行）、「▸ 替代句 N」（N=0 不显示）；全部 LLM / 字幕字段过 `esc()`；
  2. 点「▸ 替代句」只展开这一行（不重绘整表，GL-22），每条替代句「试听」「加回」（复用 T11 的动作）；
  3. 选中一行（`pick`）→ 播放器切「素材」模式并定位到入点、出现「设为入点 / 出点 / 试听这一镜」；切回「预览片」模式时这三个按钮消失；
  4. `mark('in')` / `mark('out')` 与旧行为一致（迁移的旧测试 `tests/test_frontend_steps.py` 中 ⑤ 相关用例改到这里）；
  5. ↑↓ ⧉ ✕、＋空镜、按时间排序照旧（走保存队列）；每次保存成功后重拉 `/api/result`（防抖 `RESULT_RELOAD_MS = 400`，连续保存只拉一次）；
  6. E10：`state.data.busy` 或胶囊显示本项目 `select` 任务在跑 → 字幕框 `readonly`、行内按钮 `disabled`、表头提示「正在重新选段，完成后再改分镜表」；任务结束恢复；
  7. 空表 → 「分镜表还是空的」+「去「③ 看素材」」（保留 M13 文案）。
- **IMPLEMENT**: `result-table.js`：`tableHtml(shots, notes, locked)`、`rowHtml`、`toggleAlt(i)`、`setPlayerMode(mode)`、`renderPlayer()`（替代 `renderShotBar`）、迁移来的编辑函数；`index.html` 删 `#shotbar`，`app.js::showProjectError` 与 `renderView` 中对 `#shotbar` 的引用一并删（`app.js:44,101`）。
- **MIRROR**: `gui/static/step-result.js:18-133`（原逻辑）；GL-22「选中只切 class」。
- **IMPORTS**: —
- **GOTCHA**: `tests/test_frontend_steps.py` 里 `#shotbar` 相关 3 个用例（12-32 行）迁移并改断言到 `#rPlayer`；`stopPlaySel` 的 `setInterval`（旧 `step-result.js:44-52`）换成 `timeupdate` 监听（同 M13 T17 对 ③ 的处理），切项目 / 换模式时移除监听。
- **VALIDATE**: `uv run pytest tests/test_frontend_result.py tests/test_frontend_steps.py tests/test_frontend_js.py -q`

### Task 11: 未采用清单（试听、加回）
- **ACTION**: 先写测试（node）：
  1. 列表标题「未采用清单（N）」；每行：时间码、话题、原文（截断、`esc()`）、原因标签（`cause_label`），`cause==='must'` 的行 `.must` 置顶红字；
  2. 「试听」→ 播放器切素材模式，从 `start − 0.3` 播到 `end + 0.3`（常量 `PAD_S`，与 ③ 同值）；
  3. 「加回」→ `state.shots` 按时间插入（第一个 `in` 大于它的镜头之前；全都更早 → 末尾），新 id 由 `nextShotId()` 给，字段 `{id, in, out, sub, note: topic}`；随即 `saveShots(true)`；该行立刻从列表里消失（乐观），保存失败 → 回滚 `state.shots`、行恢复、toast 原因；成功 → toast「已加回第 N 镜（算一次手动修改）」，重拉 `/api/result`（`manual.edited` 变 true，「恢复为 AI 选段」出现）；
  4. 空清单 → 「没有未采用的可用片段」；
  5. 连点两次同一行「加回」只插一次（行内 `busy` 标记）。
- **IMPLEMENT**（`result-unused.js`）：`unusedHtml(list)`、`audition(item)`、`addBack(item)`；常量 `COPY_UNUSED_TITLE = '未采用清单（{n}）'`、`COPY_UNUSED_EMPTY = '没有未采用的可用片段'`、`COPY_AUDITION = '试听'`、`COPY_ADD_BACK = '加回'`、`COPY_ADDED_BACK = '已加回第 {n} 镜（算一次手动修改）'`。
- **MIRROR**: `gui/project_routes.py:395-397`（按时间插入）；FRONTEND_PATTERN 的乐观更新 + 回滚。
- **IMPORTS**: —
- **GOTCHA**: 插入位置以**当前本地表**为准（剪辑师可能刚手动排过序），不是按全表重新排序；`shot.in/out` 来自服务端（整段），前端不再取整。
- **VALIDATE**: `uv run pytest tests/test_frontend_result.py -k unused -q`

### Task 12: KI-95 询问（三个入口）+ 恢复为 AI 选段
- **ACTION**: 先写 `tests/test_frontend_reselect.py`（node）：
  1. `confirmReselect(extra)`：先 `flushPendingSave()` 再 `refreshOrWarn()`；`state.data.manual.edited === false` → 直接 `startJob('select', {...extra, manual:'replace'})`，不弹窗；
  2. `edited === true` → 弹窗标题「你手动改过分镜表（3 处）」，正文「按新的设置重新选段会覆盖这些修改。」+ 改动清单（`changes` 逐条 `esc()`，`more > 0` 时加「等另外 N 处」）+ 三个按钮：「覆盖，用新的 AI 选段」→ `manual:'replace'`；「保留我的修改」+ 小字「只更新未采用清单和建议」→ `manual:'keep'`；「取消」→ 不发任何请求；
  3. 三个入口都走它：⑤ 顶栏改时长 / 「改为建议时长」（带 `target`）；⑤ 横幅「重新选段」（`ACTIONS.reselect`，`wizard.js:152` 改为 `confirmReselect({})`）；④ 闸门（`submitGate` 在 `POST /api/confirm/answers {confirmed:true}` 里带上选择的 `manual`；选「取消」→ 不确认，留在 ④，状态行「已取消：答案已保存为草稿」）；
  4. 「恢复为 AI 选段」按钮只在 `manual.edited` 时出现在 ⑤ 顶栏右侧；点 → 确认框「恢复为 AI 选段？当前手动修改（N 处）会被替换，已自动备份」→ 确定 → `POST /api/result/restore-ai` → 成功后 `refreshOrWarn()` + 重拉 ⑤；409 → toast 服务端原因；
  5. 保存还没落盘（`flushPendingSave()` 返回 false）→ toast「分镜表还没保存成功，先不重新选段」，不弹询问；
  6. 删除 `COPY_MANUAL_SHOTS_NOTE`（`wizard.js:14,85-87`、`step-criteria.js:243-245`）及其测试（`tests/test_frontend_gate.py::test_nav_gate_shows_manual_shot_table_note_on_the_next_line` 改为断言 ④ 闸门旁**没有**这行说明、点闸门时有询问）。
- **IMPLEMENT**（`reselect.js`）：`confirmReselect(extra, opts)`（返回 Promise<'replace'|'keep'|null>，`opts.submit` 默认是起选段任务；④ 传自己的提交函数）、`manualChangesHtml(m)`、`openRestoreAi()`、`restoreAi()`；常量 `COPY_RESELECT_TITLE = '你手动改过分镜表（{n} 处）'`、`COPY_RESELECT_BODY = '按新的设置重新选段会覆盖这些修改。'`、`COPY_RESELECT_REPLACE = '覆盖，用新的 AI 选段'`、`COPY_RESELECT_KEEP = '保留我的修改'`、`COPY_RESELECT_KEEP_NOTE = '只更新未采用清单和建议'`、`COPY_RESELECT_CANCEL = '取消'`、`COPY_CHANGES_MORE = '等另外 {n} 处'`、`COPY_RESTORE_AI = '恢复为 AI 选段'`、`COPY_RESTORE_AI_ASK = '恢复为 AI 选段？当前手动修改（{n} 处）会被替换，已自动备份'`、`COPY_RESELECT_SAVE_FIRST = '分镜表还没保存成功，先不重新选段'`、`COPY_GATE_CANCELLED = '已取消：答案已保存为草稿'`。
- **MIRROR**: `gui/static/step-criteria.js:253-258`（询问弹窗）、`260-289`（闸门提交）。
- **IMPORTS**: —
- **GOTCHA**: ④ 闸门里「待定还没裁完」的询问（M13 P1）在**前**，KI-95 询问在**后**——两个弹窗串行，第二个弹出前 `closeModal()`；`state.modalKind` 标 `'reselect'`，Esc / 点遮罩 = 取消；同一时刻只允许一个 `confirmReselect` 在途（重复点按钮忽略）。
- **VALIDATE**: `uv run pytest tests/test_frontend_reselect.py tests/test_frontend_gate.py tests/test_frontend_criteria.py tests/test_frontend_steps.py -q`

### Task 13: `derive()` ⑤ 规则启用
- **ACTION**: 先改 `tests/test_wizard_state.py` 表驱动：⑤ `preview_fresh` 且选段不过期 → `done`、next 变 `export`；`preview_fresh` 但选段过期 → `stale`；预览片过期 → `available`；空表 → 永不 `done`。前端：`tests/test_frontend_result.py` 断言生成预览片完成并刷新后步骤条 ⑤ 显示 ✓。
- **IMPLEMENT**: `_result_step(f)`：过期优先；否则 `DONE if f.get("preview_fresh") else AVAILABLE`。
- **MIRROR**: `gui/wizard.py:106-112`。
- **IMPORTS**: —
- **GOTCHA**: 项目栏「当前步骤」随之变化（⑤ 完成后显示「⑥ 导出」）——`tests/test_views.py` 的项目列表用例按新规则更新。
- **VALIDATE**: `uv run pytest tests/test_wizard_state.py tests/test_views.py tests/test_frontend_result.py -q`

**Commit B1**：`feat(gl-26,gl-27,ki-95): step 5 result with preview, unused list, add back and reselect prompt`（M14b 结束：⑤ 正式版；⑥ 仍是 M13 暂住视图，旧「生成新版本」按钮照常可用）

### ===== M14c ⑥ 导出 + 收尾 =====

### Task 14: 服务端闸门 + `derive()` ⑥ 规则
- **ACTION**: 先写测试：
  1. `jobs.job_extra("build", body)`：`target` 缺省 → `ValueError("缺少导出目标：mac 或 windows")`（旧暂存界面在本切片一并删除）；`target` 非法 → 400；
  2. `derive()`：④ 已过、无预览片、无版本 → ⑥ `locked` + `LOCKED_EXPORT_HINT`（⚑Q2）；无预览片但有版本 → `available`；`exported_current` → `done`；
  3. `next`：⑤ done、⑥ available → `export`；⑥ done → `export`。
- **IMPLEMENT**: `outputs.build_args` 把「target 必填」打开；`wizard._export_step(f)`。
- **MIRROR**: `gui/wizard.py:115-130`。
- **IMPORTS**: —
- **GOTCHA**: CLI `aicut build` 不受影响（参数校验只在 GUI 的 `job_extra`）。
- **VALIDATE**: `uv run pytest tests/test_wizard_state.py tests/test_server_jobs.py tests/test_outputs.py -q`

### Task 15: ⑥ 本次导出 + 历史版本卡片 + 打开剪映（KI-98）+ KI-100
- **ACTION**: 先写 `tests/test_frontend_export.py`（node）：
  1. 本次导出卡片：「当前分镜表 18 镜 · 2:58 · 预览片 14:02」；`preview.status !== 'fresh'` → 两个按钮 `disabled` + `title = COPY_EXPORT_NEED_PREVIEW`（⚑Q2）；
  2. 「导出到 Mac 剪映」→ `startJob('build', {target:'mac'})`（弹日志窗口，同现有 `MODAL_TASKS`）；409 `need:'close_jianying'` → 弹「剪映正在运行」+「我已关掉，继续」（重发同一请求）+「取消」，**不**弹 KI-97 的「这台 Mac 暂时不能分析」；
  3. 「生成 Windows 剪映包」→ `startJob('build', {target:'windows'})`；完成 → 卡片出现「已生成 片名_v4_Windows.zip（312 MB）」「在访达中显示」+ 一行「拷到 Windows 解压，双击 INSTALL.bat」；
  4. 当前表已导出到 Mac（某版 `current && exports.mac`）→ Mac 按钮变成「已在 Mac 剪映里：片名_v4」（禁用），旁边「打开剪映」只在 `state.data.jianying.installed` 时出现（KI-98）；`installed=false` → 一行「没检测到剪映专业版，装好后在剪映的本地草稿里找「片名_v4」」；
  5. 历史卡片：版本号、时间、时长、镜头数、「当前」标记、`exports.mac` → 「Mac 剪映：片名_vN」、`legacy` → 「Mac 剪映草稿名：片名_vN（改版前生成，未记录是否导入过）」、新版本无 `mac` → 不显示草稿名（KI-102）；Windows：有 zip → 大小 +「在访达中显示」；没有 →「生成 Windows 剪映包」（`startJob('export', {version})`）；预览片 `<video>`（`legacy` 且无预览片 →「这一版只有工程，没有预览片」）；
  6. KI-100：`unusable_hits > 0` 或 `blocked` → 卡片 `.blocked` + 红字 `blocked` 文案；Windows 的生成 / 在访达中显示按钮都不渲染；预览片照常（⚑Q3）；
  7. 所有动态字段 `esc()` / `num()`；`data-i` 用 `num(i)`；
  8. 任务完成（build / export）且仍在 ⑥ → `refreshOrWarn()`，卡片更新；在别的步骤 → 只 toast。
- **IMPLEMENT**（`step-export.js` 重写）：`viewExport()`、`currentExportHtml()`、`versionCardHtml(v, i)`、`exportMac()`、`exportWindows()`、`exportVersion(i)`（保留）、`revealExport(i)`（保留）、`openJianying()`（保留，失败 toast）、`closeJianyingModal(again)`；`jobs.js::onJobStartError` 在 `blocked && d.need === 'close_jianying'` 时调用它；删 `openBuild / doBuild`（M13 暂住弹窗）。文案常量：`COPY_EXPORT_CURRENT = '当前分镜表 {n} 镜 · {dur} · 预览片 {at}'`、`COPY_EXPORT_MAC = '导出到 Mac 剪映'`、`COPY_EXPORT_WIN = '生成 Windows 剪映包'`、`COPY_EXPORT_NEED_PREVIEW = '先在「⑤ 看结果」生成当前分镜表的预览片'`、`COPY_IN_JIANYING = '已在 Mac 剪映里：{draft}'`、`COPY_NO_JIANYING = '没检测到剪映专业版，装好后在剪映的本地草稿里找「{draft}」'`、`COPY_WIN_USAGE = '拷到 Windows 解压，双击 INSTALL.bat'`、`COPY_LEGACY_DRAFT = '（改版前生成，未记录是否导入过）'`、`COPY_JY_RUNNING_TITLE = '剪映正在运行'`、`COPY_JY_RUNNING_BODY = '导出到 Mac 剪映前请先退出剪映（⌘Q），否则剪映会覆盖草稿库。'`、`COPY_JY_RUNNING_GO = '我已关掉，继续'`、`COPY_HISTORY = '历史版本'`、`COPY_CURRENT_TAG = '当前'`。
- **MIRROR**: `gui/static/step-export.js:19-77`（原卡片与按钮）；FRONTEND_PATTERN。
- **IMPORTS**: —
- **GOTCHA**: `tests/test_frontend_steps.py` 61-92 行四个 ⑥ 用例按新界面重写（`openBuild` / `noDraft` 不再存在）；`tests/test_terms.py` 的 `BANNED_UI`（含「生成成片」「第一版」「已出片」「只出预览」）会扫新文案——用「导出」「版本 vN」「预览片」。
- **VALIDATE**: `uv run pytest tests/test_frontend_export.py tests/test_frontend_steps.py tests/test_frontend_jobs.py tests/test_terms.py tests/test_static_pages.py -q`

### Task 16: 对比两版 + 回到这一版（KI-94）
- **ACTION**: 先写测试（node，`tests/test_frontend_export.py` 增补）：
  1. 「对比两版」按钮在版本数 ≥ 2 时出现；点后每张卡片出现勾选框，选满两个自动 `GET /api/versions/compare?project&a&b`（a = 较早那版）；选第三个替换最早选的；
  2. 对比面板：两个 `<video>` 并排（各自的版本预览片；无预览片显示文字）+「同时播放」（两个都 `currentTime=0` 再 `playQuietly`）+ 差异汇总「新增 2 · 删除 1 · 改字幕 3 · 改入出点 1」+ 逐条列表（改字幕显示「之前 → 之后」，`esc()`）；`diff: null` → 显示服务端 `note`；
  3. 「关闭对比」→ 两个视频 `pause()` 并移除面板；切项目 / 离开 ⑥ 同样暂停；
  4. 「回到这一版」→ 确认框「用 v3 的分镜表替换当前分镜表？当前的分镜表会自动备份，不会删除任何版本。」→ 确定 → `POST /api/versions/restore` → 成功 toast「已回到 v3 的分镜表（N 镜）」，`dropped` 非空时追加「；已去掉 2 个含不可用片段的镜头」（⚑Q3）→ `refreshOrWarn()` → `go('result')`；无快照的版本该按钮禁用 + `title = COPY_RESTORE_NO_SNAPSHOT`；409 → toast 原因、停在 ⑥。
- **IMPLEMENT**（`export-compare.js`）：`toggleCompare()`、`pickCompare(i)`、`loadCompare(a, b)`（序号防乱序）、`compareHtml(data)`、`playBoth()`、`closeCompare()`、`askRestore(i)`、`restoreVersion(name)`；常量 `COPY_COMPARE = '对比两版'`、`COPY_COMPARE_PICK = '选两个版本'`、`COPY_PLAY_BOTH = '同时播放'`、`COPY_DIFF_SUMMARY = '新增 {a} · 删除 {r} · 改字幕 {s} · 改入出点 {t}'`、`COPY_DIFF_REORDERED = '镜头顺序也变了'`、`COPY_COMPARE_CLOSE = '关闭对比'`、`COPY_RESTORE = '回到这一版'`、`COPY_RESTORE_ASK = '用 {v} 的分镜表替换当前分镜表？当前的分镜表会自动备份，不会删除任何版本。'`、`COPY_RESTORED = '已回到 {v} 的分镜表（{n} 镜）'`、`COPY_RESTORE_DROPPED = '；已去掉 {n} 个含不可用片段的镜头'`、`COPY_RESTORE_NO_SNAPSHOT = '这一版是改版前生成的，没有留存分镜表，不能回到这一版'`。`index.html` / `fe_harness.SCRIPTS` / `INDEX_SCRIPT_ORDER` / `STATIC_FILES` 加 `export-compare.js`（`step-export.js` 之后）。
- **MIRROR**: `gui/static/step-criteria.js:253-258`（确认弹窗）；`common.js` 的 `playQuietly`。
- **IMPORTS**: —
- **GOTCHA**: 回到某一版会改 `shots.json` → ⑤ 预览片变 `outdated`、⑥ 的「当前」标记跟着变；restore 前要 `flushPendingSave()`（⑤ 可能还有防抖中的保存，会把恢复的表覆盖掉）。
- **VALIDATE**: `uv run pytest tests/test_frontend_export.py tests/test_static_pages.py tests/test_result_api.py -k "compare or restore" -q`

### Task 17: 名词与静态守卫、全量回归
- **ACTION**: `tests/test_terms.py` 跑新文件（`ALL_SOURCES` 自动覆盖）；`STEP_NAMES` 不变；新增断言：前端不再出现「这次只生成预览片」「生成新版本」作为按钮文案（`grep` 新旧词）；`tests/test_static_pages.py` 的 `test_target_copy_in_named_constants` 等按新常量名更新（`COPY_TARGET_MANUAL_NOTE` 删除）。
- **IMPLEMENT**: 按守卫逐个改。
- **MIRROR**: `tests/test_terms.py:99-130`。
- **IMPORTS**: —
- **GOTCHA**: `jobs.TASK_LABELS["build"]` 改为「导出」（胶囊「正在导出…」、冲突提示「已有任务在运行：项目 · 导出」），同步 `JOB_TITLES / JOB_LABELS / JOB_DONE`（`build: '正在导出' / '导出' / '已导出'`）与 grep 到的断言。
- **VALIDATE**: `uv run pytest -q`；`uv run pytest --cov -q`；`wc -l aicut.py gui/server.py gui/static/*.js`

### Task 18: 文档与登记
- **ACTION**:
  - `docs/GUI.md`：「一、剪辑师怎么用」⑤⑥ 两节按新界面重写（生成预览片不产生版本、闸门 B、未采用清单、手动修改询问、恢复为 AI 选段、导出 Mac / Windows、对比、回到这一版、打开剪映只在检测到时出现）；接口表加 `/api/result`、`/api/result/restore-ai`、`/api/versions/compare`、`/api/versions/restore`、`/media/<p>/current-preview`，改 `/api/job`（`preview` 任务、`build.target`、`select.manual`、`need:'close_jianying'`）、`/api/open`、`/api/state`（`manual / preview / jianying`、版本卡片新字段）、`/api/confirm/answers`（`manual`）；「界面改哪里」加新脚本与 `gui/result_*.py`、`pipeline/outputs.py`、`pipeline/shot_diff.py`；「三、从命令行跑」加 `aicut preview`、`build --windows --require-preview`、`select --manual`。
  - `docs/known-issues.md`：KI-94 / KI-95 / KI-98 / KI-100 → fixed（提交号回填）；新增 KI-101（open，⚑Q4）、KI-102（fixed）。
  - `docs/go-live-blockers.md`：GL-26「①–⑥ 完成（M13、M14）」、GL-27 fixed。
  - `docs/PROGRESS.md`「待人工放行检查」加 #20–#24（见下文 Manual Validation 的分组，每组一行）。
  - `CHANGELOG.md`（仓库根目录）一节；PRD 第 14 行加 report 链接、状态 complete（实现报告由 `/prp-implement` 生成）。
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py -q`

**Commit C1**：`feat(gl-26,ki-94,ki-98,ki-100): step 6 export with versions, compare, restore and jianying detection`
**Commit C2**：`docs: M14 wizard result and export (GUI.md, known issues, blockers, release checks, changelog)`

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| shot_diff 同 id 不同内容 | 两次 AI 选段都有 `sel03` | 一删一增，不是改字幕 | 是（E8） |
| shot_diff 互换顺序 | 两镜换位 | `reordered=True`，1 处 | 是 |
| 手动表 0 处改动 | `shots.json` == 基线 | `edited=False`，不询问 | 是（⚑Q5） |
| 无基线旧项目 | 只有 `shots.json` + selection | 与 AI 选段比 | 是 |
| shots_store 并发 | 线程 A 保存 / 进程 B replace | 串行，不丢更新 | 是（E9） |
| 备份轮转 | 第 11 次备份 | 只剩 10 份 | 是 |
| preview_inputs | `note` 变 | 不变 | 是 |
| preview_inputs | 标了不可用 | `unusable` 变 | |
| preview 不产生版本 | `aicut preview` | 无 `output/v*` | |
| build --require-preview 过期 | 表在预览后改过 | `[x]`、不切片、不建版本 | 是 |
| build 晋升 | 预览新鲜 | vN 文件与暂存同 inode | |
| 复用版本 | 同表先 Mac 后 Windows | 一个 vN，两种导出物 | 是（⚑Q1） |
| 同表再导 Mac | `exports.mac` 已有 | 400 已在剪映里 | 是 |
| export 默认时间线 | 有 `output/preview/` | 只挑 v* | 是 |
| select --manual=replace 失败 | `SelectionError` | `shots.json` 原样 | 是 |
| 未采用 cause | 排除 / 未入选 / 时长 | excluded / not_must / duration | |
| 未采用 手动删的 | AI 有、手动表没有 | `removed` | 是 |
| 未采用 剪辑列表段 | 必留不在表里 | `must` 置顶 | 是 |
| restore-ai 无 AI 选段 | 无 shots-selected | 409、文件不变 | 是 |
| versions/restore 含不可用 | 快照有隐私镜 | 剔除并 `dropped` | 是（⚑Q3） |
| versions/restore 不删版本 | 任意 | `output/` 目录集合不变 | |
| KI-100 卡片 | 旧版本命中不可用 | `blocked`、zip 定位 409 | |
| KI-102 | `--no-draft` 新版本 | `draft is None` | |
| find_app | 只在 Spotlight 里 | 返回 mdfind 路径；Trash / 不存在被过滤 | 是 |
| /api/open 剪映没装 | `find_app → None` | 404，不调用 open | |
| close_jianying | 剪映在跑 + mac | 409 need | |
| derive ⑤ | 预览新鲜 + 不过期 | done，next=export | |
| derive ⑥ | 无预览无版本 | locked（⚑Q2） | |
| 前端询问 | edited=false | 不弹窗，`manual:replace` | 是 |
| 前端询问取消 | ④ 闸门 | 不确认，答案仍是草稿 | 是 |
| 前端加回失败 | 保存 500 | 回滚、行恢复 | 是 |
| 前端闸门 B | outdated | 按钮 aria-disabled | |

### Edge Cases Checklist
- [x] 空分镜表（⑤ 不能 done、不能生成预览片的提示、⑥ 本次导出置灰）
- [x] 没有分析结果的纯手工项目（`/api/result` 200、未采用为空）
- [x] 改版前的旧项目：版本没有 `export.json` / `preview.json` / 快照（卡片 legacy、不能对比 / 回退、⑥ 因有版本可进）
- [x] 非法输入：坏项目名 / 版本号、`manual` 非法值、`target` 非法、对比同一版
- [x] 并发：重新选段（replace）进行中保存分镜表（409 + 前端只读）；预览渲染中改表（戳在开始时取 → 之后显示过期）；连点加回 / 导出
- [x] 损坏：`shots.json`、`manual_base.json`、`preview.json`、`export.json`、`shots_snapshot.json`、`overrides.json`
- [x] 剪映：没装 / 装在非标准位置 / 正在运行 / 同名草稿已存在
- [x] 清理缓存后导出（暂存时间线引用的切片不被清；Windows 打包前补切）
- [x] 权限 / 安全：新接口全部经 `_deny_reason`；媒体路由走 `media.serve_file` 的根目录校验；所有动态文本过 `esc()`

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
uv run pytest tests/test_shot_diff.py tests/test_shots_store.py tests/test_outputs.py tests/test_preview_export.py tests/test_result_api.py tests/test_versions_view.py tests/test_wizard_state.py tests/test_jy_version.py -q
uv run pytest tests/test_frontend_result.py tests/test_frontend_reselect.py tests/test_frontend_export.py tests/test_frontend_steps.py tests/test_frontend_gate.py tests/test_frontend_jobs.py tests/test_static_pages.py tests/test_terms.py -q
```
EXPECT: 全部通过（node 缺失时前端测试 skip——CI 有 node）

### Full Test Suite
```bash
find . -name "*.tsbuildinfo" -not -path "./node_modules/*" -delete
uv run pytest -q
uv run pytest --cov -q
wc -l aicut.py gui/server.py gui/project_routes.py gui/result_*.py gui/static/*.js
```
EXPECT: 无回归；覆盖率 ≥ 80%；aicut.py ≤ 800、server.py ≤ 650、每个前端 JS ≤ 400

### Browser Validation（严格按「冒烟 / 手工测试的硬规则」设置环境变量）
```bash
SMOKE=$(mktemp -d /tmp/aicut-smoke.XXXXXX)
AI_CUT_SECRETS=file AI_CUT_CONFIG_DIR="$SMOKE/cfg" AI_CUT_PROJECTS="$SMOKE/projects" \
AI_CUT_DRAFT_ROOT="$SMOKE/jy_drafts" AI_CUT_LOG_DIR="$SMOKE/logs" \
  uv run python gui/server.py --port 8899 --open
# App 模式同样带上这五个变量：uv run python app/main.py
```
EXPECT: 下列手工走查全部通过；结束后 `rm -rf "$SMOKE"` 并核对钥匙串无 `ai-cut` 条目

### Manual Validation（App 与浏览器模式各一遍；一条 5–10 分钟真实素材 + 一个改版前已出过片的旧项目；冒烟环境同上）
**⑤ 看结果（GL-26 / GL-27 / FR-7 / FR-8）**
- [ ] 进入 ⑤ 不自动生成预览片；顶栏「目标 · 当前 · 镜头 · 剪辑列表 n/n 进片」数字正确，编辑时「当前」实时变
- [ ] 「改」就地分 + 秒；没手动改过时直接重新选段，完成后分镜表换成新结果
- [ ] 剪辑列表超目标：顶栏警告条 + 「改为建议时长」；选段 / 分析完成后不再自动弹窗
- [ ] 分镜表：改字幕自动保存；「为什么选它」；展开替代句可试听 / 加回；选中行切到素材模式、设入出点
- [ ] 「生成预览片」只在胶囊里跑；完成后播放器显示预览片；改一个字后显示「分镜表改过了 · 重新生成预览片」，闸门 B 变灰
- [ ] 未采用清单：原因四类可见（⚑Q4）；试听前后各 0.3 秒；加回出现在按时间正确的位置，下一次预览片里有它
- [ ] 「看过了，去导出 →」只在当前表的预览片生成后可点

**KI-95 手动修改与重新选段**
- [ ] 手动改 3 处后：⑤ 改时长、⑤ 横幅重新选段、④ 重新确认，三处都弹询问并列出 3 处改动
- [ ] 「覆盖」→ 分镜表 = 新 AI 选段，`work/shots_backups/` 多一份备份；「保留」→ 分镜表不变，未采用清单 / 建议更新；「取消」→ 什么都没发生（④ 不确认）
- [ ] 「恢复为 AI 选段」只在手动改过时出现，确认后恢复
- [ ] 重新选段（覆盖）进行中，⑤ 分镜表只读并说明原因

**⑥ 导出（FR-9 / FR-10 / KI-98 / KI-100）**
- [ ] 当前表没有预览片：⑥ 本次导出两个按钮置灰并说明；有历史版本时 ⑥ 仍可进（⚑Q2）
- [ ] 「导出到 Mac 剪映」：剪映开着 → 先提示关掉；关掉后继续 → 生成 vN，草稿落在 `$SMOKE/jy_drafts/<片名>_vN`；之后同表再点显示「已在 Mac 剪映里」
- [ ] 同一张表再「生成 Windows 剪映包」→ 不新开版本，同一 vN 出现 zip（⚑Q1）；「在访达中显示」+ 用法一行
- [ ] 「打开剪映」：本机装了剪映才出现；把剪映挪到别的目录（或在测试机未装）时不出现 / 点了给出说明，不报系统错误
- [ ] 历史卡片：只有真的导出过 Mac 才写草稿名；`--no-draft` 旧路径 / 改版前的版本显示 legacy 说明
- [ ] 在 ③ 把某个已进旧版本的片段标「不可用」→ 该版卡片标红，Windows 包不能生成 / 打开，预览片仍可看
- [ ] 对比两版：并排播放、同时播放、差异汇总与逐条明细正确；改版前的版本只能并排看
- [ ] 回到 v1：确认后 ⑤ 显示 v1 的分镜表、预览片变过期；`output/` 下所有版本都还在

**旧项目**
- [ ] 改版前已出过片的项目：⑥ 能看历史版本；没有快照的版本「回到这一版」禁用并说明

**人工放行检查（由用户执行，真实剪映，不在冒烟环境里）** → 写进 `docs/PROGRESS.md` #20–#24：⑤ 全流程计时、Mac 导出后在剪映里打开并播放、Windows 包在 Windows 剪映打开、KI-95 三入口、KI-100 / 对比 / 回退。

---

## Acceptance Criteria
- [ ] GL-26（⑤⑥）：每个可点按钮在当时都能成功或说明原因（「点了才发现不能用 = 0 处」，按上表走查）
- [ ] GL-27：未采用清单（原因 + 试听 + 加回），加回出现在分镜表并进入下一次预览片
- [ ] FR-8：预览片不产生版本；当前表的预览片生成过才能过闸门 B；导出的版本与预览片同一份时间线
- [ ] KI-94：对比两版（并排 + 差异）；回到这一版先确认、不删版本
- [ ] KI-95：手动改过后三个入口都询问；选「覆盖」后分镜表等于新选段结果（FR-7 验收）；「恢复为 AI 选段」；从不静默覆盖
- [ ] KI-98：「打开剪映」只在检测到剪映且做过 Mac 导出后出现；不再写死路径
- [ ] KI-100：含不可用片段的版本被标出、Windows 包被拦
- [ ] KI-101 已登记（open）、KI-102 已修并钉测试
- [ ] `uv run pytest` 全绿；`--cov` ≥ 80%；行数守卫通过
- [ ] App 在 A0 / A1 / A2 / B1 / C1 每个提交后都能从新建走到剪映打开

## Completion Checklist
- [ ] 新接口都在路由子模块里，返回 (状态码, JSON)；损坏 → 409、CorruptJSON 先于 ValueError
- [ ] 中文文案全部是命名常量（Python 模块常量 / JS 文件顶部 `COPY_*`）
- [ ] 不可变更新（shot_diff、outputs、前端 state 更新都返回新对象；`shots.json` 读改写在 `shots_store.locked` 内）
- [ ] 前端：无内联脚本与 on* 属性；data-* 过 `num()`/`esc()`；新文件进白名单与脚本顺序守卫；不用 localStorage
- [ ] 日志不含字幕原文 / 片名 / 偏好内容
- [ ] 测试沿用 `gui_server` / `call` / `make_project` / node vm 夹具；任何手工冒烟都带 `AI_CUT_SECRETS=file` 与临时目录
- [ ] 文档：GUI.md、known-issues（KI-94/95/98/100 状态，KI-101/102）、go-live-blockers（GL-26/27）、PROGRESS 放行检查、CHANGELOG、PRD
- [ ] 没有做 NOT Building 里的任何一项

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 「覆盖」与保存的跨进程竞争丢编辑 | 中 | 高 | E9 文件锁 + E10 任务中只读 / 409 + E11 覆盖前备份；先写「不丢编辑」回归测试（PRD Risks） |
| 晋升用硬链接，之后原地改写暂存文件会连带改掉已发布版本 | 低 | 高 | 所有写都走 `media_io.atomic_output` / `schema.write_json`（新 inode）；`test_outputs` 断言重新生成预览片后旧版本 inode 不变 |
| aicut.py 只剩 35 行余量 | 高 | 低 | T0 先腾约 30 行；编排之外的逻辑进 `pipeline/outputs.py`；结构守卫兜底 |
| `/api/state` 变重（版本命中、手动改动、预览状态） | 中 | 中 | 无不可用标记时不读快照；剪映检测缓存 60 秒；改动清单只读两个小 JSON；必要时把 `manual` 挪到 `/api/result` |
| 前端改动面大，node vm 测不到布局 / 视频播放 | 高 | 中 | 关键交互抽纯函数测；每个子切片结束做一次冒烟走查；放行检查 #20–#24 真机 |
| 镜头配对规则误判（改动清单 / 对比不准） | 中 | 低 | E8 规则表驱动单测；只用于显示与询问，不影响出片 |
| `mdfind` 慢或 Spotlight 关闭 | 低 | 低 | 3 秒超时、缓存、失败当未安装（只是不显示按钮） |
| ⚑ 产品决定被推翻 | 中 | 低~中 | 每条只影响标注的 Task；Q1/Q2/Q3 的默认都可以在 `outputs.build_args` / `derive` / `_versions` 一处改 |

## Notes
- 子切片顺序 A0 → A1 → A2 → B1 → C1 → C2 不可调换：B1 依赖 A1 的 `preview` 任务与 `--manual`、A2 的 `/api/result`；C1 依赖 A1 的晋升与 A2 的版本字段，并在同一提交里删掉 M13 暂住的「生成新版本」弹窗、打开 `target` 必填与 ⑥ 的锁规则。
- M13 的接手点（M13 计划 Notes）已全部落实：`derive()` ⑤⑥ 两行、`step-result.js` / `step-export.js` 替换、KI-95 询问挂在 `wizard.js` 的 `reselect` 与 ④ 闸门。
- 本计划没有写任何实现代码，也没有提交；`storyboard/`、`work/`、`designs/`、`storyboard-seedream/` 未触碰。
