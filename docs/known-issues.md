# 已知问题（KI）

> 不阻断首批交付、但需要排期修复的问题。来源：2026-10-19 全面审查。阻断项见 [go-live-blockers.md](go-live-blockers.md)。
> 关闭时在「状态」填提交号。

## 成片质量

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-01 | 成片字幕被截成前 28 字；镜头被预算截断时字幕不跟着裁剪 | `pipeline/select.py:154,215,250` | fixed `bc3c705` |
| KI-02 | `_fix_ending` 会把开场 hook 挪到片尾；取第一个匹配而非最后一个；关键词过泛 | `pipeline/select.py:325-345` | fixed `bc3c705` |
| KI-03 | 必留原话按逗号切分，碎片命中大量句子被强制入选，成片超长 | `pipeline/select.py:141-160, 395-397` | fixed `bc3c705` |
| KI-04 | 答案规则 `focus`/`pacing` 只解析不生效；兜底问题「关键信息」绑定空规则；label 截断 12 字互相覆盖 | `pipeline/select.py:87-113`；`pipeline/questions.py:91-92` | fixed `bc3c705` |
| KI-05 | 确认页答案不生效：页面无入口，prepare 在确认前已跑完选段，无 select 任务 | `gui/server.py:224-251, 600-606`；`aicut.py:588-598` | fixed `bc3c705` |
| KI-06 | `signals` 未并入 scored 段 → 情绪权重、情绪结尾永远无效 | `pipeline/select.py:77-78, 340-341`；`pipeline/classify.py` | fixed `bc3c705` |
| KI-07 | 必留话题关键词写死为培训场景且过宽（真实项目 19 话题判 14 个必留）；应外置到 presets | `pipeline/classify.py:19-27, 48` | fixed `bc3c705` |
| KI-08 | 抢话代理指标过宽（换人+停顿<0.25s 即判可用） | `pipeline/classify.py:101-134` | fixed `bc3c705` |
| KI-09 | 话题分段一次调用、输出上限 3000 token，长素材 JSON 截断即整条流水线崩；模型脏输出（`"false"` 字符串、非 dict）未校验 | `pipeline/understand_text.py:135-189` | fixed `bc3c705` |
| KI-10 | `--model` 只记标签不传给客户端 | `pipeline/understand_text.py:184-189`；`pipeline/summarize.py:94-115` | fixed `bc3c705` |
| KI-11 | 预览缓存哈希漏入出点 → 改镜头后复用旧预览；切片缓存只看文件存在 | `aicut.py:557-563`；`pipeline/build_documentary.py:80` | fixed `bc3c705` |
| KI-12 | 人工裁决按 segment id 存储，重新分段后套到错误句子上 | `pipeline/review.py:23-67` | fixed `bc3c705` |

## 渲染 / 导出

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-13 | 字幕含单引号 → 预览渲染 ffmpeg 失败 | `pipeline/render_preview.py:33-36` | fixed `71e44e7` |
| KI-14 | 素材无音轨 → 预览渲染失败；声道布局不一致时 concat 失败 | `pipeline/render_preview.py:53` | fixed `71e44e7` |
| KI-15 | `pipeline/select.py`、`pipeline/secrets.py` 与标准库同名，Homebrew Python 下脚本方式运行崩溃 | `pipeline/select.py`；`pipeline/secrets.py` | fixed `71e44e7` |
| KI-16 | `aicut.py run` 在已有 shots.json 时必崩（args 缺 `version`/`no_draft`） | `aicut.py:601-605` | fixed `71e44e7` |
| KI-17 | 剪映模板/版本写死 11.0；pyJianYingDraft 只声明支持到 10.8；缺黄金草稿回归 | `pipeline/to_jianying.py:197, 308` | fixed `71e44e7` |
| KI-18 | 模板缺失只 warn 被子进程输出吞掉；Windows 包安装脚本失败仍打印 `[OK] Done`；导出后不调 `inspect_package` | `pipeline/to_jianying.py:176-178`；`packaging/build_package.py:157-221`；`pipeline/export_draft.py:39-75` | fixed `71e44e7`（Windows 实机待验证） |

## 静默失败 / 健壮性

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-19 | ffmpeg/ffprobe 不查返回码：废片检测、抽帧、切点失败后得到「看起来成功」的空结果；`duration==0` 除零 | `pipeline/junk_detect.py:68-69, 104, 174`；`pipeline/understand_visual.py:35-38, 96-125`；`aicut.py:186-194` | fixed `ef3c020` |
| KI-20 | `check=True`+`capture_output` 抛错时 stderr 丢失，用户看不到 ffmpeg 真实原因 | `aicut.py:61-62` | fixed `ef3c020` |
| KI-21 | `jload` 等把 JSON 损坏当默认值，界面显示误导信息 | `gui/server.py:74-78`；`pipeline/classify.py:116-121`；`aicut.py:399,530` | fixed `ef3c020` |
| KI-22 | questions 兜底结果被缓存固化；LLM 错误只写文件不展示 | `pipeline/questions.py:132-134`；`pipeline/summarize.py:111-113` | fixed `ef3c020` |
| KI-23 | must_lines / must_topics / 答案标签匹配不到时静默跳过，不提示 | `pipeline/select.py:99-101, 166-167, 279-298` | fixed `ef3c020` |
| KI-24 | 转写时间字段缺失默认 0；包含句使 `end` 回退；时间码 59.999 显示 `00:60.00` | `pipeline/format_transcript.py:30, 41-49, 75-84` | fixed `ef3c020` |
| KI-25 | LLM 重试不覆盖 `RemoteDisconnected`/`ConnectionResetError`/200 非 JSON | `pipeline/llm.py:26-34, 77` | fixed `ef3c020` |
| KI-26 | `default_project` 共享可变 DEFAULTS，跨项目污染 | `pipeline/schema.py:24-42` | fixed `ef3c020` |
| KI-27 | 废片检测：文件末尾未闭合的静音/冻帧丢失；重叠区间重复计算；`--scene` 结果被丢弃 | `pipeline/junk_detect.py:62-136` | fixed `ef3c020` |

## 安全 / 密钥

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-28 | 密钥文件先以默认权限创建再 chmod；`chmod` 父目录可能改动共享目录；`delete` 不清 legacy key；keyring 删除失败被吞 | `pipeline/secrets.py:58-141` | fixed `9017287` |
| KI-29 | CLI 输出原文写入 `failed.json`，未经 `secrets.mask` 脱敏；网络错误子串匹配过宽 | `pipeline/cloud.py:76-82, 187-203` | fixed `9017287` |
| KI-30 | Range 请求解析错误（后缀范围、越界未返回 416） | `gui/server.py:340-350` | fixed `9017287` |
| KI-31 | 请求体非法时未捕获异常直接断连；shots 入出点未校验（负数、nan、out≤in） | `gui/server.py:99-110, 534-543` | fixed `624e979` |

## 运维 / 体验

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-32 | 无费用控制：每次 prepare 重调 LLM，无用量统计与预算上限 | `aicut.py:590-597`；`pipeline/llm.py:95` | fixed `9017287` |
| KI-33 | 退出 App 不停后台任务，ffmpeg 成孤儿进程；无磁盘空间预检与缓存清理 | `app/main.py:35-38`；`gui/server.py:270` | fixed `9017287` |
| KI-34 | `.command` 启动脚本不走 uv、Python 版本不受控；非冻结 `pip install pyJianYingDraft` 未固定版本 | `启动剪辑台.command:5-13`；`aicut.py:98-112` | fixed `9017287` |
| KI-35 | 前端竞态：切项目旧响应覆盖新数据；出片前未 flush 防抖保存；乐观更新不检查响应 | `gui/static/index.html:202-216, 372-374, 435-443`；`browse.html:200-213` | fixed `9017287` |
| KI-36 | pywebview 中 `window.open(..., '_blank')` 可能无效（浏览素材、剪辑偏好按钮） | `gui/static/index.html:529, 533` | fixed `9017287` |
| KI-37 | 升级丢授权（adhoc cdhash 变化）、`CFBundleVersion` 固定为 1、无 CHANGELOG；中间产物无 schema 版本 | `packaging/ai-cut.spec` | fixed `9017287` |

## 测试

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-38 | 覆盖率 51%（aicut.py 未纳入统计，实际约 40%），要求 80%；`gui/server.py`、`to_jianying.py`、`junk_detect.py`、`format_transcript.py`、`build_documentary.py`、`render_preview.py` 为 0% | `tests/` | fixed `25c76fc` |
| KI-39 | 无端到端测试（素材 → 剪映草稿）；`test_proc.py` 断言近乎恒真 | `tests/test_proc.py:19-28`；`tests/test_export_draft.py` | fixed `25c76fc` |

## 文档

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-40 | 成功指标与验收不可检验：满意度无样本/方法；FR-5 验收样本 41 段违反自身 ≤40 上限；时间预算 PRD 与 PLAN 不一致 | `docs/PRD-AI粗剪工具.md` §5 §10；`docs/PLAN-AI粗剪工具.md:102` | fixed `83d2a1a` |
| KI-41 | c 路（画面）PRD 要求景别/人脸/OCR/道具，代码只做画质，需实现或降级为 P1/P2 | PRD FR-2；`pipeline/understand_visual.py:5` | fixed `83d2a1a` |
| KI-42 | PLAN 漏 PRD 需求（Brief 模型、FR-10 对比/回退、FR-11、FR-12、FR-13）且多出 PRD 没有的范围（剪辑偏好三问 / schema v2）；PLAN 排期、风险表、人天未随 M0 完成更新 | `docs/PLAN-AI粗剪工具.md` | fixed `83d2a1a`（PLAN 原有 FR-10..13 任务行，补的是验收与追溯） |
| KI-43 | 术语三套并存（废片/待定/可用、L1–L3、必留/可选/可删），「必留」一词三义；闸门定义、分类名是否已定在文档间冲突 | PRD §12；`docs/产品设计-AI粗剪工作流.md`；`docs/选段与理解-改进方案.md` | fixed `83d2a1a` |
| KI-44 | 非功能需求缺成本上限、断网/服务失败降级；DoD 无量化门槛和测试策略 | PRD §7；PLAN DoD | fixed `83d2a1a` |

## 2026-10-19 实施中新发现

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-45 | `schema.SchemaTooNew` 继承 `Exception`，`except (ValueError, OSError)` 接不住，项目版本过新时连接直接断开 | `gui/server.py`（`/api/state`、POST `/api/calibrate`）；`pipeline/schema.py:21` | fixed `624e979` |
| KI-46 | `/api/new` 的 title 非字符串时 `.strip()` 抛 AttributeError，连接断开 | `gui/server.py`（`/api/new`） | fixed `624e979` |
| KI-47 | `/api/state` 项目名不合法时返回 404，应为 400 | `gui/server.py`（`/api/state`） | fixed `624e979` |
| KI-48 | shots.json 缺 `shots` 键时 KeyError，用户只看到 traceback | `aicut.py`（`cmd_build`） | fixed `ef3c020` |
| KI-49 | 磁盘上的多选答案不是数组时 `.includes` 抛错，确认页问题整页渲染失败 | `gui/static/confirm.html`（`renderQuestions`） | fixed `ef3c020` |
| KI-50 | 前端 `move`/`dup`/`del` 的 `saveShots(true)` 不 await，连续操作时并发 POST 可能让旧状态覆盖新状态（原子写只保证不损坏，不保证顺序） | `gui/static/index.html`（`saveShots` 调用点） | fixed `9017287` |
| KI-51 | `project.json` 读改写无锁（`/api/calibrate` 与 aicut 子进程 `schema.save` 之间可丢更新）；`write_json` 未 `fsync`，被强杀留 `.tmp` 残片 | `gui/server.py`（`/api/calibrate`）；`pipeline/schema.py`（`write_json`） | fixed `9017287` |
| KI-52 | `gui/static/prototype.html` 是演示页但仍由 `/static/` 公开服务，含未转义插值 | `gui/static/prototype.html` | fixed `9017287` |
| KI-53 | CSP 仍需 `'unsafe-inline'`：内联脚本与内联事件改成 `addEventListener` 后才能收紧 | `gui/static/*.html` | fixed `9017287` |
| KI-54 | `gui/server.py` 834 行，超过 800 行软上限；路由宜拆到独立模块 | `gui/server.py` | fixed `9017287` |
| KI-55 | `aicut.py` 881 行，超过 800 行软上限（同 KI-54） | `aicut.py` | fixed `9017287` |
| KI-56 | `overrides.json` 损坏时 `select`/`prepare` 不捕获 `OverridesCorrupt`，打出 traceback 而非人话 | `aicut.py`（`cmd_select`）；`pipeline/select.py`（`review.load` 调用处） | fixed `ef3c020` |
| KI-57 | `createProject` 残留按 URL hash 选项目的启动代码，与随后的 `selectProject(name)` 抢切项目 | `gui/static/index.html`（`createProject`） | fixed `9017287` |
| KI-58 | `_level_of` 只按话题名判必留话题，按关键信息占比判出的必留话题内句子拿不到「必留→待定」保护，与 `topics[].must` 口径不一 | `pipeline/classify.py`（`_level_of`） | fixed `bc3c705` |
| KI-59 | 同名草稿重跑先拷完媒体才在 `install()` 报「已存在」，白耗时间 | `pipeline/to_jianying.py`（`install`） | fixed `71e44e7` |
| KI-60 | 子任务失败输出只打印末尾 600/500 字符，「草稿静态校验未通过」的开头可能被截掉 | `aicut.py`（`cmd_build` 调 to_jianying 处） | fixed `ef3899f` |
| KI-61 | ffmpeg 调用无超时，坏素材/网络盘卡住时 GUI 任务永远 running（取消见 GL-17） | `pipeline/media_io.py`（`run_ffmpeg`） | fixed `9017287` |
| KI-62 | `.done` 只绑定产物大小，不绑定输入指纹：换素材后 `proxy.mp4`/`asr.wav` 仍算完成 | `pipeline/media_io.py`（`is_complete`）；`aicut.py` 音轨/代理处 | fixed `9017287` |
| KI-63 | `.partial-*` 临时文件与成品同目录，未来对 `clips/*.mp4` 的 glob 会读到半成品；`_clear_stale_partials` 会删并发写者的临时文件 | `pipeline/media_io.py` | fixed `9017287` |
| KI-64 | `zip_pkg` 打印的是临时 zip 路径（`.xxx.partial-….zip`），易误导 | `packaging/build_package.py`（`zip_pkg`） | fixed `71e44e7` |
| KI-65 | 旧项目 wav 认领：无标记的旧 wav 中断残片可能被 ffprobe 按大小估出正时长而被认领 | `pipeline/media_io.py`（`complete_or_adopt`） | fixed `9017287` |
| KI-66 | 素材无法被 ffprobe 识别时 `cmd_ingest` 抛 `KeyError: 'format'`，用户看到 traceback | `aicut.py`（`cmd_ingest`） | fixed `ef3c020` |
| KI-67 | `secrets.mask` 长度 >8 即显示前 4 后 4，9–12 位 Key 几乎全暴露 | `pipeline/secrets.py`（`mask`） | fixed `9017287` |
| KI-68 | `JOBS` 与任务日志从不清理，长时间使用内存持续增长 | `gui/jobs.py`（`JOBS`） | fixed `9017287` |
| KI-69 | `cmd_new` 判空目录与建目录之间有竞争窗口（GUI 有全局互斥，影响低） | `aicut.py`（`cmd_new`） | fixed `9017287` |
| KI-70 | 第三方错误文本（mediakit-cli 输出前 400 字、LLM 响应体前 300 字）未按已知 Key 脱敏就进任务日志与 `failed.json`（纵深防御） | `pipeline/cloud.py`；`pipeline/llm.py` | fixed `9017287` |
| KI-71 | 上次退出遗留的后台任务只在点按钮时以 409 出现，界面不主动提示 | `gui/server.py`（`report_stale_job`）；`gui/static/index.html` | fixed `9017287` |
| KI-72 | 看门狗依赖系统 `pgrep`，缺失时跳过「先正常退出」直接 SIGKILL 整组 | `pipeline/proc.py`（`start_parent_watchdog`） | fixed `9017287` |
| KI-73 | 预览字幕首选字体 `/System/Library/Fonts/PingFang.ttc` 在当前 macOS 上不存在，实际回落宋体 | `pipeline/render_preview.py:20-24` | fixed `bc3c705` |
| KI-74 | 从钥匙串/凭证文件读出的 Key 未去首尾空白，带换行时 LLM 请求头报错 | `pipeline/secrets.py`（`get`） | fixed `9017287` |
| KI-75 | ASR 上传缓存：云端提前作废 file_id 时要等 12h 过期才重传 | `pipeline/cloud.py`（`work/asr_upload.json`） | fixed `9017287` |
| KI-76 | 预览字幕 `esc()` 不转义 `%`：LGPL ffmpeg 报 `Stray %` 该条字幕静默不显示，Homebrew ffmpeg 直接失败 | `pipeline/render_preview.py:37-40` | fixed `71e44e7` |
| KI-77 | 废片判定：冻帧与静音完全重叠时只给「待定/参考」，「无语音 + 画面静止」强信号只对黑场成立 | `pipeline/junk_detect.py`（`judge`） | fixed `ef3c020` |
| KI-78 | Windows `INSTALL.bat` 遇同名草稿用 `rd /s /q` 删除已有草稿，与 README「不会动你已有的任何草稿」矛盾 | `packaging/build_package.py` 生成的 `INSTALL.bat` | fixed `71e44e7`（Windows 实机待验证） |
| KI-79 | `INSTALL.bat` 里 `echo [!] JianYing is running…` 的 `!` 在延迟扩展下被吞，显示成 `[]` | `packaging/build_package.py:175` | fixed `71e44e7` |
| KI-80 | `to_jianying.py` 命令行直接传相对 `--staging` 时素材路径写成相对路径，静态校验 FAIL（aicut 调用不受影响） | `pipeline/to_jianying.py:250-270`（`bundle_media`） | fixed `6478a24` |
| KI-81 | 研究用 `--minimal` 分支仍写死 11.0 模板路径，缺失时静默跳过 | `packaging/build_package.py:143`（`make_minimal_draft`） | fixed `71e44e7` |
| KI-82 | `ensure_jy_python` 不检查已有 venv 的 Python 版本，≤3.10 的旧 venv 不认 `-P` | `aicut.py:136` | fixed `71e44e7` |
| KI-83 | `aicut summary` 子命令无 `--model`，CLI 上 KI-10 只对 `text` 生效 | `aicut.py`（`summary` 子命令） | fixed `9017287` |
| KI-84 | 旧逻辑存下的跨题串规则会沿用到剪辑师重新保存确认页为止 | `pipeline/select.py`（`_current_rules`） | fixed `9017287` |
| KI-85 | `review.clear()` 按存储时 id 删除，裁决被重定位后删不到（目前无调用方） | `pipeline/review.py`（`clear`） | fixed `bc3c705` |
| KI-86 | 旧项目的 `questions.json` 由旧提示词生成，focus 为自由文本，M6 后只警告不生效；需提供「重新生成决策问题」入口或提示 | `pipeline/questions.py`；`gui/static/confirm.html` | fixed `9017287` |
| KI-87 | 英文素材分句拼整句时无空格（"world.good"） | `pipeline/format_transcript.py:116` | fixed `9017287` |
| KI-88 | 同机其他用户可经 `GET /` 取到页面里的 token 后调用全部 API（单用户威胁模型下可接受）；改为一次性 nonce 换 HttpOnly SameSite=Strict cookie | `gui/server.py`（`_send_page`、`_deny_reason`） | fixed `6478a24` |
| KI-89 | 各版本共用 `work/clips`：新版本重切同名镜头会改动旧版本引用的切片（旧版本重新导出可能与当初不一致） | `aicut.py`（`ensure_clips`）；`pipeline/clips.py` | fixed `6478a24` |
| KI-90 | 浏览器模式下会话 cookie 不按端口隔离（RFC 6265）：本机另一用户在 127.0.0.1 其他端口起服务并诱导剪辑师用同一浏览器访问，可收到 cookie（App 内 WKWebView 不受影响；单用户本机威胁模型下低） | `gui/session.py`；`docs/GUI.md` 安全模型 | open（接受：多人共用电脑用 App） |
| KI-91 | 会话凭据为进程级常量：所有窗口共用、无登出与轮换（进程退出即失效，本地单用户可接受） | `gui/session.py` | open |
| KI-92 | 新建项目时长只能填秒、放在预设下方，预设下拉写死时长（如 175s），切换预设还会覆盖手填值 → 剪辑师以为最长只有 3 分钟，与「时长由剪辑师定」（FR-1）不符；改为「分 + 秒」自由填写（10 秒–60 分钟），放在预设上方，换预设不覆盖手填值，改目标时长弹窗同样处理 | `gui/static/index.js`（`openNew`、`syncTarget`、`openTarget`） | fixed `c0fbe05` |

## 2026-10-20 界面流程梳理

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-93 | 「不可用」标记（FR-11）界面上没有入口 | `gui/static/step-browse.js`、`cliplist.js`；`pipeline/review.py` | fixed `f815ddc`（存储 / 选段 / 出片 / 导出）+ `d65c994`（③ 的 X 入口、手动分镜表即时移除、撤销） |
| KI-94 | 版本只能逐个看，不能对比两版、不能回退（FR-10） | `gui/static/step-export.js`、`export-compare.js`；`gui/result_routes.py` | fixed `1f63524`（对比 / 回到这一版的接口）+ `6d812f7`（⑥ 对比两版并排播放 + 镜头差异、回到这一版先确认且不删版本） |
| KI-95 | 手动改过分镜表（哪怕一个字）后，确认答案、改时长都不再影响分镜表，且没有「恢复为 AI 选段」；应先询问覆盖 / 保留（PRD FR-7） | `gui/views.py`；`gui/static/reselect.js` | fixed `6972b5c` + `aa18643`（手动分镜表 `manual` 锁定 / 替换模式；⑤ 改时长、横幅重新选段、④ 重新确认三个入口先询问「覆盖 / 保留 / 取消」，0 处改动不询问；「恢复为 AI 选段」；覆盖前备份） |
| KI-96 | 名词混乱：「预览」tab 放的是代理片、预览片在「版本」tab；「废片」tab（画面技术问题）与「废片」档位同名；待定 / 待判断混用；窗口「浏览素材」页标题「素材浏览」；阶段条用「素材台账」「策划分派单」等内部术语且只列 6 项（实际 12 步）。统一按 PRD §12 | `gui/static/*`；`gui/views.py:58-65` | fixed `efeb92b`（M13：前端名词守卫 `tests/test_terms.py`，后端文案 `b2f4c69`） |
| KI-97 | 任务前置检查返回 `need=encoder` 时前端没处理，只记一行「[错误]」日志 | `gui/static/jobs.js:76-80` | fixed `5d25267`（`need=encoder` 及未知前置条件：弹窗说明 + 导出诊断包） |
| KI-98 | 「打开剪映」硬编码 `/Applications/VideoFusion-macOS.app`，任何时候都可点；剪映装在别处时无提示 | `gui/server.py`；`gui/jianying.py` | fixed `1f63524` + `6d812f7`（只在 `/Applications` 下找并校验 bundle id，结果缓存；没装 → 界面不给「打开剪映」、`/api/open` 404；打开失败的原因原样提示；⑥ 只在做过 Mac 导出且检测到时显示） |
| KI-99 | `/api/browse` 判断已用 / 未用只看手动 `shots.json`：没有手动分镜表时所有片段都显示「未用」 | `gui/payloads.py:35-39` | fixed `d65c994`（没有手动分镜表时以 `work/shots-selected.json` 为准，手动的优先） |
| KI-100 | 事后标「不可用」不会让已落盘的产物失效：旧版本的 Windows zip、预览片、已进剪映草稿库的 Mac 草稿仍可打开 / 定位，界面也不提示（FR-11「所有版本均不出现」） | `gui/static/`（版本卡片）；`gui/server.py`（`/api/open target=export`） | fixed `1f63524` + `6d812f7`（版本卡片 `blocked` 标红并拦这一版 Windows 包的生成 / 在访达中显示；预览片仍可看、可对比；已进剪映草稿库的 Mac 草稿程序改不了，只提示） |
| KI-101 | 未采用清单无法给出「因重复」原因：选段没有任何去重判断（只有话题未入选 / 超出话题预算 / 不在候选池），PRD FR-8 列的「重复」无数据来源 | `pipeline/select.py`（unused 生成处） | open（改选段算法，需另立项） |
| KI-102 | `--no-draft` 出的版本卡片也显示「Mac 剪映草稿名」，剪映草稿库里其实没有这份草稿 | `gui/views.py`（版本数据）；`gui/static/step-export.js` | fixed `1f63524` + `6d812f7`（`export.json` 记录真实导出物，草稿名只在导出过 Mac 的版本上显示；改版前的版本标「改版前生成，未记录是否导入过」） |
| KI-103 | ③ 看素材只能逐段放入剪辑列表 / 改标记（逐个按 S 或点「＋ 剪辑列表」），段多时太慢（2026-10-21 用户反馈） | `gui/static/batch-select.js`、`step-browse.js`、`cliplist.js`；`gui/browse_batch.py`；`pipeline/review.py` | fixed `d899c9e`（勾选框 + Shift 连选、全选当前筛选；批量放入 / 移出剪辑列表、标为可用 / 废片 / 不可用，一个原子请求；Z 整批撤销） |
