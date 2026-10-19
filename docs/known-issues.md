# 已知问题（KI）

> 不阻断首批交付、但需要排期修复的问题。来源：2026-10-19 全面审查。阻断项见 [go-live-blockers.md](go-live-blockers.md)。
> 关闭时在「状态」填提交号。

## 成片质量

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-01 | 成片字幕被截成前 28 字；镜头被预算截断时字幕不跟着裁剪 | `pipeline/select.py:154,215,250` | open |
| KI-02 | `_fix_ending` 会把开场 hook 挪到片尾；取第一个匹配而非最后一个；关键词过泛 | `pipeline/select.py:325-345` | open |
| KI-03 | 必留原话按逗号切分，碎片命中大量句子被强制入选，成片超长 | `pipeline/select.py:141-160, 395-397` | open |
| KI-04 | 答案规则 `focus`/`pacing` 只解析不生效；兜底问题「关键信息」绑定空规则；label 截断 12 字互相覆盖 | `pipeline/select.py:87-113`；`pipeline/questions.py:91-92` | open |
| KI-05 | 确认页答案不生效：页面无入口，prepare 在确认前已跑完选段，无 select 任务 | `gui/server.py:224-251, 600-606`；`aicut.py:588-598` | open |
| KI-06 | `signals` 未并入 scored 段 → 情绪权重、情绪结尾永远无效 | `pipeline/select.py:77-78, 340-341`；`pipeline/classify.py` | open |
| KI-07 | 必留话题关键词写死为培训场景且过宽（真实项目 19 话题判 14 个必留）；应外置到 presets | `pipeline/classify.py:19-27, 48` | open |
| KI-08 | 抢话代理指标过宽（换人+停顿<0.25s 即判可用） | `pipeline/classify.py:101-134` | open |
| KI-09 | 话题分段一次调用、输出上限 3000 token，长素材 JSON 截断即整条流水线崩；模型脏输出（`"false"` 字符串、非 dict）未校验 | `pipeline/understand_text.py:135-189` | open |
| KI-10 | `--model` 只记标签不传给客户端 | `pipeline/understand_text.py:184-189`；`pipeline/summarize.py:94-115` | open |
| KI-11 | 预览缓存哈希漏入出点 → 改镜头后复用旧预览；切片缓存只看文件存在 | `aicut.py:557-563`；`pipeline/build_documentary.py:80` | open |
| KI-12 | 人工裁决按 segment id 存储，重新分段后套到错误句子上 | `pipeline/review.py:23-67` | open |

## 渲染 / 导出

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-13 | 字幕含单引号 → 预览渲染 ffmpeg 失败 | `pipeline/render_preview.py:33-36` | open |
| KI-14 | 素材无音轨 → 预览渲染失败；声道布局不一致时 concat 失败 | `pipeline/render_preview.py:53` | open |
| KI-15 | `pipeline/select.py`、`pipeline/secrets.py` 与标准库同名，Homebrew Python 下脚本方式运行崩溃 | `pipeline/select.py`；`pipeline/secrets.py` | open |
| KI-16 | `aicut.py run` 在已有 shots.json 时必崩（args 缺 `version`/`no_draft`） | `aicut.py:601-605` | open |
| KI-17 | 剪映模板/版本写死 11.0；pyJianYingDraft 只声明支持到 10.8；缺黄金草稿回归 | `pipeline/to_jianying.py:197, 308` | open |
| KI-18 | 模板缺失只 warn 被子进程输出吞掉；Windows 包安装脚本失败仍打印 `[OK] Done`；导出后不调 `inspect_package` | `pipeline/to_jianying.py:176-178`；`packaging/build_package.py:157-221`；`pipeline/export_draft.py:39-75` | open |

## 静默失败 / 健壮性

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-19 | ffmpeg/ffprobe 不查返回码：废片检测、抽帧、切点失败后得到「看起来成功」的空结果；`duration==0` 除零 | `pipeline/junk_detect.py:68-69, 104, 174`；`pipeline/understand_visual.py:35-38, 96-125`；`aicut.py:186-194` | open |
| KI-20 | `check=True`+`capture_output` 抛错时 stderr 丢失，用户看不到 ffmpeg 真实原因 | `aicut.py:61-62` | open |
| KI-21 | `jload` 等把 JSON 损坏当默认值，界面显示误导信息 | `gui/server.py:74-78`；`pipeline/classify.py:116-121`；`aicut.py:399,530` | open |
| KI-22 | questions 兜底结果被缓存固化；LLM 错误只写文件不展示 | `pipeline/questions.py:132-134`；`pipeline/summarize.py:111-113` | open |
| KI-23 | must_lines / must_topics / 答案标签匹配不到时静默跳过，不提示 | `pipeline/select.py:99-101, 166-167, 279-298` | open |
| KI-24 | 转写时间字段缺失默认 0；包含句使 `end` 回退；时间码 59.999 显示 `00:60.00` | `pipeline/format_transcript.py:30, 41-49, 75-84` | open |
| KI-25 | LLM 重试不覆盖 `RemoteDisconnected`/`ConnectionResetError`/200 非 JSON | `pipeline/llm.py:26-34, 77` | open |
| KI-26 | `default_project` 共享可变 DEFAULTS，跨项目污染 | `pipeline/schema.py:24-42` | open |
| KI-27 | 废片检测：文件末尾未闭合的静音/冻帧丢失；重叠区间重复计算；`--scene` 结果被丢弃 | `pipeline/junk_detect.py:62-136` | open |

## 安全 / 密钥

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-28 | 密钥文件先以默认权限创建再 chmod；`chmod` 父目录可能改动共享目录；`delete` 不清 legacy key；keyring 删除失败被吞 | `pipeline/secrets.py:58-141` | partial `6f8ba02`（凭证文件创建权限已修） |
| KI-29 | CLI 输出原文写入 `failed.json`，未经 `secrets.mask` 脱敏；网络错误子串匹配过宽 | `pipeline/cloud.py:76-82, 187-203` | open |
| KI-30 | Range 请求解析错误（后缀范围、越界未返回 416） | `gui/server.py:340-350` | open |
| KI-31 | 请求体非法时未捕获异常直接断连；shots 入出点未校验（负数、nan、out≤in） | `gui/server.py:99-110, 534-543` | fixed `624e979` |

## 运维 / 体验

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-32 | 无费用控制：每次 prepare 重调 LLM，无用量统计与预算上限 | `aicut.py:590-597`；`pipeline/llm.py:95` | open |
| KI-33 | 退出 App 不停后台任务，ffmpeg 成孤儿进程；无磁盘空间预检与缓存清理 | `app/main.py:35-38`；`gui/server.py:270` | open |
| KI-34 | `.command` 启动脚本不走 uv、Python 版本不受控；非冻结 `pip install pyJianYingDraft` 未固定版本 | `启动剪辑台.command:5-13`；`aicut.py:98-112` | open |
| KI-35 | 前端竞态：切项目旧响应覆盖新数据；出片前未 flush 防抖保存；乐观更新不检查响应 | `gui/static/index.html:202-216, 372-374, 435-443`；`browse.html:200-213` | open |
| KI-36 | pywebview 中 `window.open(..., '_blank')` 可能无效（浏览素材、剪辑偏好按钮） | `gui/static/index.html:529, 533` | open |
| KI-37 | 升级丢授权（adhoc cdhash 变化）、`CFBundleVersion` 固定为 1、无 CHANGELOG；中间产物无 schema 版本 | `packaging/ai-cut.spec` | open |

## 测试

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-38 | 覆盖率 51%（aicut.py 未纳入统计，实际约 40%），要求 80%；`gui/server.py`、`to_jianying.py`、`junk_detect.py`、`format_transcript.py`、`build_documentary.py`、`render_preview.py` 为 0% | `tests/` | open |
| KI-39 | 无端到端测试（素材 → 剪映草稿）；`test_proc.py` 断言近乎恒真 | `tests/test_proc.py:19-28`；`tests/test_export_draft.py` | open |

## 文档

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-40 | 成功指标与验收不可检验：满意度无样本/方法；FR-5 验收样本 41 段违反自身 ≤40 上限；时间预算 PRD 与 PLAN 不一致 | `docs/PRD-AI粗剪工具.md` §5 §10；`docs/PLAN-AI粗剪工具.md:102` | open |
| KI-41 | c 路（画面）PRD 要求景别/人脸/OCR/道具，代码只做画质，需实现或降级为 P1/P2 | PRD FR-2；`pipeline/understand_visual.py:5` | open |
| KI-42 | PLAN 漏 PRD 需求（Brief 模型、FR-10 对比/回退、FR-11、FR-12、FR-13）且多出 PRD 没有的范围（剪辑偏好三问 / schema v2）；PLAN 排期、风险表、人天未随 M0 完成更新 | `docs/PLAN-AI粗剪工具.md` | open |
| KI-43 | 术语三套并存（废片/待定/可用、L1–L3、必留/可选/可删），「必留」一词三义；闸门定义、分类名是否已定在文档间冲突 | PRD §12；`docs/产品设计-AI粗剪工作流.md`；`docs/选段与理解-改进方案.md` | open |
| KI-44 | 非功能需求缺成本上限、断网/服务失败降级；DoD 无量化门槛和测试策略 | PRD §7；PLAN DoD | open |

## 2026-10-19 实施中新发现

| 编号 | 问题 | 位置 | 状态 |
|---|---|---|---|
| KI-45 | `schema.SchemaTooNew` 继承 `Exception`，`except (ValueError, OSError)` 接不住，项目版本过新时连接直接断开 | `gui/server.py`（`/api/state`、POST `/api/calibrate`）；`pipeline/schema.py:21` | fixed `624e979` |
| KI-46 | `/api/new` 的 title 非字符串时 `.strip()` 抛 AttributeError，连接断开 | `gui/server.py`（`/api/new`） | fixed `624e979` |
| KI-47 | `/api/state` 项目名不合法时返回 404，应为 400 | `gui/server.py`（`/api/state`） | fixed `624e979` |
| KI-48 | shots.json 缺 `shots` 键时 KeyError，用户只看到 traceback | `aicut.py`（`cmd_build`） | open |
| KI-49 | 磁盘上的多选答案不是数组时 `.includes` 抛错，确认页问题整页渲染失败 | `gui/static/confirm.html`（`renderQuestions`） | open |
| KI-50 | 前端 `move`/`dup`/`del` 的 `saveShots(true)` 不 await，连续操作时并发 POST 可能让旧状态覆盖新状态（原子写只保证不损坏，不保证顺序） | `gui/static/index.html`（`saveShots` 调用点） | open |
| KI-51 | `project.json` 读改写无锁（`/api/calibrate` 与 aicut 子进程 `schema.save` 之间可丢更新）；`write_json` 未 `fsync`，被强杀留 `.tmp` 残片 | `gui/server.py`（`/api/calibrate`）；`pipeline/schema.py`（`write_json`） | open |
| KI-52 | `gui/static/prototype.html` 是演示页但仍由 `/static/` 公开服务，含未转义插值 | `gui/static/prototype.html` | open |
| KI-53 | CSP 仍需 `'unsafe-inline'`：内联脚本与内联事件改成 `addEventListener` 后才能收紧 | `gui/static/*.html` | open |
| KI-54 | `gui/server.py` 834 行，超过 800 行软上限；路由宜拆到独立模块 | `gui/server.py` | open |
| KI-55 | `aicut.py` 881 行，超过 800 行软上限（同 KI-54） | `aicut.py` | open |
| KI-56 | `overrides.json` 损坏时 `select`/`prepare` 不捕获 `OverridesCorrupt`，打出 traceback 而非人话 | `aicut.py`（`cmd_select`）；`pipeline/select.py`（`review.load` 调用处） | open |
| KI-57 | `createProject` 残留按 URL hash 选项目的启动代码，与随后的 `selectProject(name)` 抢切项目 | `gui/static/index.html`（`createProject`） | open |
| KI-58 | `_level_of` 只按话题名判必留话题，按关键信息占比判出的必留话题内句子拿不到「必留→待定」保护，与 `topics[].must` 口径不一 | `pipeline/classify.py`（`_level_of`） | open |
| KI-59 | 同名草稿重跑先拷完媒体才在 `install()` 报「已存在」，白耗时间 | `pipeline/to_jianying.py`（`install`） | open |
| KI-60 | 子任务失败输出只打印末尾 600/500 字符，「草稿静态校验未通过」的开头可能被截掉 | `aicut.py`（`cmd_build` 调 to_jianying 处） | fixed `ef3899f` |
| KI-61 | ffmpeg 调用无超时，坏素材/网络盘卡住时 GUI 任务永远 running（取消见 GL-17） | `pipeline/media_io.py`（`run_ffmpeg`） | open |
| KI-62 | `.done` 只绑定产物大小，不绑定输入指纹：换素材后 `proxy.mp4`/`asr.wav` 仍算完成 | `pipeline/media_io.py`（`is_complete`）；`aicut.py` 音轨/代理处 | open |
| KI-63 | `.partial-*` 临时文件与成品同目录，未来对 `clips/*.mp4` 的 glob 会读到半成品；`_clear_stale_partials` 会删并发写者的临时文件 | `pipeline/media_io.py` | open |
| KI-64 | `zip_pkg` 打印的是临时 zip 路径（`.xxx.partial-….zip`），易误导 | `packaging/build_package.py`（`zip_pkg`） | open |
| KI-65 | 旧项目 wav 认领：无标记的旧 wav 中断残片可能被 ffprobe 按大小估出正时长而被认领 | `pipeline/media_io.py`（`complete_or_adopt`） | open |
| KI-66 | 素材无法被 ffprobe 识别时 `cmd_ingest` 抛 `KeyError: 'format'`，用户看到 traceback | `aicut.py`（`cmd_ingest`） | open |
| KI-67 | `secrets.mask` 长度 >8 即显示前 4 后 4，9–12 位 Key 几乎全暴露 | `pipeline/secrets.py`（`mask`） | open |
| KI-68 | `JOBS` 与任务日志从不清理，长时间使用内存持续增长 | `gui/jobs.py`（`JOBS`） | open |
| KI-69 | `cmd_new` 判空目录与建目录之间有竞争窗口（GUI 有全局互斥，影响低） | `aicut.py`（`cmd_new`） | open |
| KI-70 | 第三方错误文本（mediakit-cli 输出前 400 字、LLM 响应体前 300 字）未按已知 Key 脱敏就进任务日志与 `failed.json`（纵深防御） | `pipeline/cloud.py`；`pipeline/llm.py` | open |
| KI-71 | 上次退出遗留的后台任务只在点按钮时以 409 出现，界面不主动提示 | `gui/server.py`（`report_stale_job`）；`gui/static/index.html` | open |
| KI-72 | 看门狗依赖系统 `pgrep`，缺失时跳过「先正常退出」直接 SIGKILL 整组 | `pipeline/proc.py`（`start_parent_watchdog`） | open |
| KI-73 | 预览字幕首选字体 `/System/Library/Fonts/PingFang.ttc` 在当前 macOS 上不存在，实际回落宋体 | `pipeline/render_preview.py:20-24` | open |
| KI-74 | 从钥匙串/凭证文件读出的 Key 未去首尾空白，带换行时 LLM 请求头报错 | `pipeline/secrets.py`（`get`） | open |
| KI-75 | ASR 上传缓存：云端提前作废 file_id 时要等 12h 过期才重传 | `pipeline/cloud.py`（`work/asr_upload.json`） | open |
| KI-76 | 预览字幕 `esc()` 不转义 `%`：LGPL ffmpeg 报 `Stray %` 该条字幕静默不显示，Homebrew ffmpeg 直接失败 | `pipeline/render_preview.py:37-40` | open |
| KI-77 | 废片判定：冻帧与静音完全重叠时只给「待定/参考」，「无语音 + 画面静止」强信号只对黑场成立 | `pipeline/junk_detect.py`（`judge`） | open |
| KI-78 | Windows `INSTALL.bat` 遇同名草稿用 `rd /s /q` 删除已有草稿，与 README「不会动你已有的任何草稿」矛盾 | `packaging/build_package.py` 生成的 `INSTALL.bat` | open |
