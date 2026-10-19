# 实施报告：里程碑 9 · 密钥与运维

## 概要
按 `.claude/PRPs/plans/m9-secrets-ops.plan.md` 完成 22 个任务（阶段 0 / A / B / C / D / E），外加补充范围 KI-83、KI-84、KI-86、KI-87。
计划是在 963374c 上写的；实施时已经落地 M7 / M8 / M6，阶段 0 按当前文件重新拆分，各任务实施前都重新读了代码。
基线 `uv run pytest` 1426 passed → 完成后 **1660 passed**（新增 234 个）。没有 commit，没有切分支，没有归档计划。

## 计划预估与实际
| 指标 | 计划 | 实际 |
|---|---|---|
| 复杂度 | XL | XL |
| 涉及文件 | 约 45 | 71 个已修改 + 27 个新增（含测试） |
| aicut.py | ≤ 800 | 915 → **766** |
| gui/server.py | ≤ 650 | 740 → **612** |

## 任务完成情况
| # | 任务 | 状态 | 说明 |
|---|---|---|---|
| 1 | 拆分 aicut.py（KI-55） | 完成 | 新增 timeline / prompts / brief / config_cli / cli_args；`main()` 每次调用时从 globals 取 `cmd_*`，原有打桩点照常生效。`clip_key` 已在 M6 移进 build_documentary，本次不搬 |
| 2 | 拆分 gui/server.py（KI-54） | 完成 | 新增 views.py（project_state / projects_list / presets_payload / health_payload）、media.py；`server.project_state`、`server.jload` 保留为包装 / 重导出。browse / confirm 的 payload 在 M8 已拆到 payloads.py |
| 3 | 掩码分档 + 读出去空白（KI-67、KI-74） | 完成 | |
| 4 | 不改共享目录权限；删除时屏蔽旧版文件（KI-28） | 完成 | `legacy_ignored.json`；重新 set 后恢复 |
| 5 | 第三方错误文本脱敏；failed.json 原子写（KI-29、KI-70） | 完成 | cloud._redact、record_failure、llm._api_error / 网络错误、任务日志 |
| 6 | 缓存 file_id 失效时立即重传（KI-75） | 完成 | 换新 token；任务进入终态时清除上传缓存 |
| 7 | write_json fsync、清理陈旧 tmp、跨进程锁（KI-51） | 完成 | `schema.locked / update / update_project`；flock 不可用时退回进程内锁并记 warning |
| 8 | cmd_new 原子占位（KI-69） | 完成 | `create_json_exclusive`（硬链接；不支持时退回 O_EXCL） |
| 9 | ffmpeg / ffprobe 超时（KI-61） | 完成 | 另给 to_jianying 子进程也加了超时 |
| 10 | 完成标记绑定素材指纹（KI-62） | 完成 | D7：旧标记补写指纹 |
| 11 | `.aicut-partial/` + 按写者 pid 清理（KI-63） | 完成 | |
| 12 | 认领 wav 前校验 RIFF 头（KI-65） | 完成 | |
| 13 | LLM 结果复用 + 用量账本 + 预算（KI-32） | 完成 | 预算 300 万 tokens（用户已确认）；界面信息行显示用量 |
| 14 | 磁盘预检 + 清理缓存（KI-33） | 完成 | `aicut clean [--dry-run]`、`/api/cache*`、「清理缓存」按钮 |
| 15 | 任务表清理、日志上限、遗留任务提示（KI-68、KI-71） | 完成 | `#stalebar` 提示条 |
| 16 | 看门狗不再依赖 pgrep（KI-72） | 完成 | |
| 17 | uv 启动脚本、pyJianYingDraft 锁版本、构建号、CHANGELOG、产物版本号（KI-34、KI-37） | 完成 | |
| 18 | Range 按 RFC 修正（KI-30） | 完成 | |
| 19 | 静态文件白名单，prototype 移出（KI-52） | 完成 | |
| 20 | 保存串行、切项目竞态、生成成片前先存盘、createProject 残留（KI-35、KI-50、KI-57） | 完成 | 浏览页失败回滚在 M8 已做 |
| 21 | 脚本外置 + 事件委托 + CSP 收紧（KI-53）；App 内开子窗口（KI-36） | 完成 | |
| 22 | 文档 + 全量验证 | 完成 | README、docs/GUI.md、docs/PACKAGING.md、CHANGELOG.md |
| + | KI-83 `summary --model` | 完成 | |
| + | KI-84 `rules_version` | 完成 | `RULES_VERSION = 2`；缺版本或旧版本的规则按当前题目重算 |
| + | KI-86 旧版决策问题的提示 + 重新生成 | 完成 | `questions.has_legacy_focus`；确认页提示卡片；新增任务 `questions`（执行 `questions --force`），要求已确认外发说明并有 DeepSeek Key |
| + | KI-87 英文分句拼接补空格 | 完成 | `shot_sub.join_lines`，format_transcript 和截短镜头的字幕共用 |

## 验证结果
| 层级 | 结果 | 备注 |
|---|---|---|
| 静态检查 | 通过 | compileall、全部 `node --check gui/static/*.js`、两个 shell 脚本 `bash -n` |
| 单元 / 集成测试 | 通过 | 1660 passed |
| 构建 | 未运行 | 没有执行 PyInstaller 打包（只有文本守卫） |
| 浏览器 | 通过 | chrome-devtools MCP，在隔离端口和隔离数据目录下逐页检查 index / browse / confirm / calibrate：无 CSP 拦截。所有按钮经委托生效：清理缓存、↑↓ 连点后服务端顺序与界面一致、改字幕后 flush 已落盘、设置 / 外发说明 / 新建 / 关于 / 目标时长、浏览页筛选 / 分类 / 必留 / 试听、确认页选项 / 保存 / 重新生成（缺告知时正确拦截）、偏好保存。curl 检查：`bytes=-10` → 206，`bytes=999999-` → 416，`/static/prototype.html` → 404 |

## 偏离计划之处
1. 阶段 0 按当前代码重新规划：aicut 不搬 `clip_key`（已在 build_documentary）；server 的 browse / confirm payload 在 M8 已拆出，另外多拆了 projects_list / presets_payload / health_payload。`aicut status` 的产物清单挪到 `readiness.STATUS_ARTIFACTS`，为后续接线留出行数。
2. `schema.update` 分成通用的 `update` 和用于 project.json 的 `update_project`（读时迁移、写时补版本）。原因：`load()` 要求 name / material，不能用于任意 JSON。
3. `MeteredClient` 可以接收无参工厂，按需创建客户端；`aicut.metered()` 先查预算，超了直接 die（summary / questions 内部的兜底会吞掉异常）。账本写失败只打印 `[!]` 并记日志，不让已付费的结果作废。
4. KI-61：understand_visual 在 M8 已改用带超时的 `run_analysis`，本次没有再改。
5. KI-34：jy_env 在 M8（KI-82）已接管 venv。本次在 jy_env 加了 `JY_PIN` 和版本核对；开发态如果当前解释器已装 pyJianYingDraft，直接使用当前解释器。
6. KI-36：`/api/window` 的页面白名单加入 `confirm`（确认页是 M6 新增的入口，计划里没有）。
7. KI-28：没有改 gui/settings.py。删除 Key 后旧版文件已被屏蔽，设置页自然显示「未配置」，不需要额外提示。
8. KI-35 浏览页的回滚在 M8 已实现，并由已有的静态守卫覆盖，本次没有新增 node 测试。
9. KI-87 顺带修了 `shot_sub.sub_for` 截短镜头时分句拼接没有空格的问题（同一根因），并加了回归测试。
10. TDD：Task 20 / 21 的前端行为测试是在外置重构之后补写的。补写后用变异的方式确认过 RED：删掉序号检查、保存队列和 flush，对应 4 个测试变红，恢复后变绿。KI-33 的 `/api/cache*` 路由在 Task 15 之前就做了。用量账本容错是自查时补的，测试也是后补的。

## 改写的既有测试（规格变更或源码迁移，断言意图不变）
- KI-67 掩码：test_secrets（mask_keeps_edges）、test_applog ×2、test_cloud（401 掩码）、test_server_config、test_diagnostics。
- KI-69：test_aicut_cli 的两个新建失败用例，打桩对象从 `schema.save` 改为 `create_json_exclusive`。
- KI-62：test_aicut_cli 里 `complete_or_adopt` 的桩加上 `**k`。
- KI-63：test_media_io 的 commits_and_marks、stale_partials、glob 元字符三条，改为新的临时目录格式。
- KI-65：test_aicut_build 的旧 wav 认领用例改为写完整的 wav。
- KI-34：test_jy_env 的 venv 复用用例改为「只核对版本」；test_aicut_build 的 dev 用例打桩 `available_here`。
- KI-72：test_proc 的看门狗用例打桩 `signal.signal`，不在 pytest 进程里真的安装处理函数。
- KI-84：test_select ×4、test_m8_review ×1 里的「已存规则」夹具补上 `rules_version`。
- KI-53：test_frontend_jobs / test_frontend_js / test_static_pages / test_confirm_flow / test_server_support 改为读外置的 .js；`onclick=...` 断言改成 `data-act=...`；node 桩补上 `addEventListener`、`flushPendingSave`；「不拼字符串的内联事件」守卫换成更强的「没有任何 on* 属性」。

## 新增测试文件
test_structure、test_usage、test_diskspace、test_cache、test_server_maintenance、test_server_desktop、test_launcher、schema_workers（跨进程测试用的 worker），另外在 25 个既有测试文件里新增了用例。

## 新发现缺陷（未修，需要登记）
- `gui/payloads.py:47`：`t["count"] += 1`。scored 文件里的话题缺 `count` 字段时（手改或旧格式文件）`/api/browse` 返回 500 KeyError，应该按 0 处理。
- `gui/static/browse.js:123`（`jump`）：没有代理片时 `pv.play()` 抛出未处理的 Promise 拒绝（控制台 Uncaught (in promise)），界面无影响。
- `aicut.cmd_clean`（aicut.py，cmd_clean）：命令行清理不检查剪辑台是否正在对同一项目跑任务（GUI 路由会返回 409）。在生成成片过程中从终端执行 `aicut clean` 可能删掉正在使用的切片。
- `gui/server.py` HEAD 请求不受支持（501）。属于既有行为，影响很小。

## 待人工验证
- 用 App 模式（`uv run python app/main.py`）：「浏览素材」「确认与提问」「剪辑偏好」应在 App 内开新窗口；收紧 CSP 后「选择素材」的 pywebview 文件框和 JS 桥应仍可用。
- 强杀剪辑台时任务还在跑：重开后顶部应出现提示条。
- 双击 `启动剪辑台.command`：有 uv 时正常启动，没有 uv 时给出提示。
- `./packaging/build_app.sh`：Info.plist 里 `CFBundleVersion` 应等于 git 提交数；未设置签名身份时应打印警告；包里的 `gui/static` 只有白名单文件。
- 真实素材上第二次「重新处理」：日志应显示「沿用上次的标注结果」，用量不增加。
- 真实云端：缓存的 file_id 被拒后会重新上传一次（只用假 transport 测过）。

## 下一步
- `/code-review`；由编排方决定是否提交，以及更新登记册状态。

---

## 审查修复（代码审查 + 安全审查之后）

测试 1660 → **1702 passed**。`aicut.py` 766 行、`gui/server.py` 617 行。行数靠拆模块降下来（新增 `pipeline/project_cli.py`、`clips.py`、`project_lock.py`、`transcript_stamp.py`），没有用一行写多条语句的办法凑行数。每一项都是先写测试，确认失败后再改实现（L21 是把原用例的断言反过来改写）。审查给的 r1 / r2 复现脚本现在的结果：账本 1000（不再是 2000）、并发写失败 0 次（原来 95 次）、话题统计不再翻倍。r3、r4 本来就是通过的。

### HIGH
- **H1 用量重复计账**：每次调用前清空 `last_usage`（MeteredClient 和 DeepSeekClient 两处都清）；只有成功的调用才记账；接口没给 `total_tokens` 时按 prompt + completion 计。新增测试：先成功一次、再失败一次，账本保持 1000。
- **H2 清理切片后旧版本导出失败**：每次出片在 `output/vN/shots_snapshot.json` 记下当时的分镜表。导出时先调用 `clips.restore_missing`：只补切缺失的切片（还在的不动，可能已被新一版重切，不能覆盖），补切与 ensure_clips 用同一个 `clips.cut_clip`。本次修复之前出的版本没有快照，切片又被清理过时，直接说明原因并让剪辑师重新生成成片。清理缓存弹窗的说明里写明会删哪些、旧版本会按需重切。

### MEDIUM
- **M3 清理与运行中的任务冲突**：新增 `pipeline/project_lock.py`。所有读写项目产物的 aicut 命令持项目共享锁（flock，进程退出自动释放）；`aicut clean` 和 `/api/cache/clean` 要独占锁，拿不到就拒绝（GUI 返回 409）。上次剪辑台留下的任务、终端里的命令都会持锁，所以这两种情况也会被拒绝。
- **M4 删临时目录和并发写者抢**：`atomic_output` 不再删 `.aicut-partial/`，空目录改由「清理缓存」删。
- **M5 磁盘预检把已有产物也算进去**：处理素材只算还没完成的 wav / 代理；生成成片只算要重切的镜头，加上预览（覆盖一个预览已完整的同名版本时不算预览）。什么都不用写时不查磁盘。
- **M6 预算挡住了命中缓存的步骤**：`metered()` 不再提前退出，改为每次真正调用模型前才查预算。summarize / questions 遇到超预算原样抛出，不走兜底；aicut 捕获后以非零退出。
- **M7 换了素材仍沿用旧转写**：转写成功后记下素材指纹（`transcript_source.json`）。指纹变了就作废 `transcript_raw.json`，打印 `[!]` 说明并重新转写；下游各步骤按各自的输入哈希重算。没有记录的旧项目视为一致并补记。逐句标注复用的指纹加入了 start / end / speaker。
- **M8 `questions --force` 失败会冲掉原题**：已有题目时模型失败抛 `RegenerateFailed`，原题和答案不动，命令非零退出；questions.json 改为原子写。第一次生成失败仍用兜底模板。
- **M9 浏览页话题统计翻倍**：累加前先清零；话题缺 `count` 字段时也不再 500（这正是我上次登记的新缺陷，已一并修掉）。
- **安全（MEDIUM）**：在 docs/GUI.md 补了「安全模型（单用户本机）」一节，写明不防同机其他用户 / 进程从 `GET /` 拿到 token。认证方案没改，由编排方登记 KI。

### LOW
- L10：四处 `.play()` 改走 `playQuietly`（吞掉 rejection），并加了静态守卫测试。
- L11：支持 HEAD，静态文件、媒体和页面都只回响应头。
- L12：清理缓存列项时，统计过程中文件消失就跳过。
- L13：`DEFAULT_MODEL` 只在 llm.py 定义一处。
- L14：Range 的数字超过 15 位直接返回 416（原来超长数字串会让 `int()` 报错变成 500）。
- L15：清理缓存删除前要求路径真实存在、不是符号链接，并且解析后仍在项目目录里（`work/` 被换成符号链接也不会越界删除）。
- L16：schema 的锁文件用 O_NOFOLLOW 打开，权限 0600。
- L17：任务失败说明（「无法启动任务」「任务异常中断」）也经过 `applog.redact`。
- L18：`legacy_ignored.json` 损坏时按「全部屏蔽」处理（fail closed）。旧版明文文件确实已被屏蔽、但仍在电脑上时，设置页提示用户自己删除。浏览器复查时发现这条提示一开始写成「只要不是从旧文件读就提示」，Key 来自环境变量时也会误报，已改为只在确实屏蔽时提示并加了测试。
- L19：启动脚本改为 `uv run --locked`。
- L20：构建号只认 ASCII 数字（`[0-9]+`）。
- L21：写者进程还活着的临时文件，不论放了多久都不删。

### 改写的既有测试（规格变化）
- test_media_io 三条、test_render_preview 两条：空的 `.aicut-partial/` 目录现在会留着。
- test_media_io：活着的写者留下的旧临时文件改为保留。
- test_secrets：坏的屏蔽文件改为 fail closed（删掉原「坏文件当作没屏蔽」用例）。
- test_aicut_must_keep 两条：超预算改为在真正调用模型时触发。
- test_diskspace：`need_for_build` 改成两个参数。
- test_launcher：启动参数里多了 `--locked`。
- test_aicut_build：重抽音轨的用例把 M7 的作废逻辑打桩掉，M7 另有专门用例。

### 验证
- 全量 1702 passed；所有 `node --check`、compileall、`bash -n` 都通过。
- 浏览器复查（chrome-devtools MCP，隔离端口、隔离数据目录）：浏览页分类视图统计正确，主页文稿跳转、设置、清理缓存都正常，控制台没有 CSP 拦截。服务器已停。

### 仍待处理 / 说明
- 「预览是否已是最新」是近似判断：只有覆盖一个预览已完整的同名版本时才不计预览，可能少估一次预览渲染的空间。
- 共享 work/clips 本身的问题（新版本重切同 id 镜头会改动旧版本引用的切片）属于既有设计，这次没有改；补切时只补缺失的、不覆盖已有的，至少不会让情况变得更糟。
