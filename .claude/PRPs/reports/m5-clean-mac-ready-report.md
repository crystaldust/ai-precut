# Implementation Report: M5 干净 Mac 可装可用（GL-01 / GL-03 / GL-04 / GL-19）

## Summary
- **GL-01**：`pipeline/cloud.py` 改为标准库 urllib 直连 MediaKit HTTPS（申请上传地址 → PUT 音轨 → 提交 → 轮询），零外部进程；`mediakit_env()` / `secrets.env_with_secret()` 删除。
- **GL-04**：新增 `pipeline/encode.py`（h264_videotoolbox，命名常量码率 proxy 1500k / clip 12M / preview 8M），全仓 4 处 libx264 替换且仍走 `media_io.ffmpeg_to/atomic_output`；新增 `packaging/build_ffmpeg.sh`（SHA256 钉死源码、LGPL 静态构建、`--verify-only` 自检）、`THIRD-PARTY-NOTICES.txt`；`build_app.sh` 去掉 osxexperts 无校验下载，随 dist 交付 notices / 首次打开说明 / `sources/`；spec 带上新模块与 `licenses/`；GUI 新增「关于 / 第三方许可」。
- **GL-19**：`pipeline/applog.py`（RotatingFileHandler 5MB×5、脱敏 Filter、主线程/子线程异常钩子、`stage()` 写 `work/timings.json`），接入 app/main、gui/server、gui/jobs、aicut CLI、打包子进程（`proc.dispatch`）、llm/cloud 登记 Key；`pipeline/diagnostics.py` + `gui/support.py` 的 `POST /api/diagnostics`（与其它路由同一 `_deny_reason`）+ 侧栏 / 任务失败弹窗「导出诊断包」。
- **GL-03**：`packaging/首次打开说明-macOS.txt`（macOS 15+「仍要打开」+ 13/14 右键）；`docs/PACKAGING.md`、`docs/交付形态调研.md` 同步。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 高；drawtext 已按决策 A 补 HarfBuzz，scratch 构建全绿 |
| Files Changed | ~26（11 新建 / 15 修改） | 36（15 新建 / 21 修改，不含本报告） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | HTTP CloudClient 测试先行 | done | RED 53 failed → GREEN；保留原有 GL-15/16 语义用例 |
| 2 | 实现 HTTP `cloud.py` | done | 偏差 D1–D4 |
| 3 | 调用方改造 + 清理 mediakit-cli | done | |
| 4 | encode 测试先行 | done | |
| 5 | `encode.py` + 替换 libx264 | done | 真编码用例在本机执行（未 skip） |
| 6 | `build_ffmpeg.sh` | done | 偏差 D5–D7；第二轮按决策 A 加 HarfBuzz，见「ffmpeg 临时构建结果」 |
| 7 | build_app / spec / NOTICES | done | |
| 8 | `test_packaging.py` | done | |
| 9 | applog 测试先行 | done | |
| 10 | 实现 `applog.py` | done | 偏差 D8 |
| 11 | 接入日志 | done | 偏差 D9–D10 |
| 12 | diagnostics 测试先行 + 实现 | done | 偏差 D11 |
| 13 | GUI「导出诊断包」 | done | 偏差 D12–D13 |
| 14 | GL-03 文档 | done | |
| 15 | 文档同步 | done（部分） | 按指示未改 go-live-blockers / known-issues / PROGRESS 状态 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | `compileall` 无输出；`bash -n` 两个脚本通过（仓库无 lint/typecheck） |
| Unit Tests | Pass | 810 → 930 passed（+120）；另以 scratch LGPL ffmpeg 置于 PATH 最前再跑一遍：930 passed、0 skipped |
| Build | N/A | 未跑 PyInstaller / 未覆盖 vendor、dist（按指示）；ffmpeg 在 scratchpad 构建 |
| Integration | Pass（mock） | GUI 路由经真实 HTTP 服务测试；未发任何真实云端请求 |
| Edge Cases | Pass | 无 Key、401、非 JSON、业务失败、预签名过期、上传缓存失效、日志目录不可写、钥匙串异常、符号链接 |

## ffmpeg 临时构建结果 · 第二轮（决策 A：补 HarfBuzz）
- HarfBuzz 14.6.0：GitHub 官方 release 资产 `https://github.com/harfbuzz/harfbuzz/releases/download/14.6.0/harfbuzz-14.6.0.tar.xz`（2026-10-05 发布，为当时 latest）。
  **SHA256 来源**：GitHub Releases API 为该资产发布的 `digest` 字段 `sha256:d07a007327277708a2a73ae437887cdbaf282937f6d03ca5467723e9099af586`；下载后本地 `shasum -a 256` 与之一致，钉进 `HARFBUZZ_SHA256`。
- 构建：cmake 静态（`BUILD_SHARED_LIBS=OFF`），`HB_HAVE_FREETYPE=ON` 显式指向自建 `libfreetype.a`（vf_drawtext 用 `hb-ft.h`），glib/icu/cairo/graphite2/gobject/introspection/CoreText 全关，utils/subset/raster/vector/gpu 不建，`CMAKE_IGNORE_PREFIX_PATH` 排除 Homebrew；ffmpeg 加 `--enable-libharfbuzz`（无需额外 `-lc++`）。
- `--verify-only` 退出 0：LGPL ✓；无 gpl/nonfree/x264 ✓；buildconf 含 `--enable-libfreetype --enable-libharfbuzz` ✓（新增检查）；**drawtext ✓** 及其余滤镜/编码器 ✓；`otool -L` 仍只有 `/System/Library/*` 与 `/usr/lib/{libSystem,libz}` ✓；licenses 下有 `FFmpeg-COPYING.LGPLv2.1 / FreeType-FTL.TXT / HarfBuzz-COPYING / ffmpeg-buildconf.txt`。
- 带字幕完整预览：两段 1920×1080 VT 素材 → `pipeline/render_preview.py`（代码同一路径：trim/scale/pad/concat + 逐条 drawtext + VT 8M）→ 1080×1920 h264 High yuv420p + aac，4.5 s；抽帧确认中文底部字幕「我们在山里拍了三天：风很大。」与居中字幕卡「第二章 · 回家」正确渲染（字体回落宋体，见新缺陷）。
- 代码另无 `subtitles`/`ass` 滤镜调用，字幕只走 drawtext。

## ffmpeg 临时构建结果 · 第一轮（scratchpad，未触碰 vendor/ 与 dist/）
- 下载：两个钉死 URL 均可用；SHA256 与计划一致（ffmpeg 8.1.3 `7138d28c…78a3`，FreeType 2.14.3 `36bc4f1c…a5f`）。
- 构建：`AICUT_FFMPEG_OUT=… AICUT_FFMPEG_WORK=… ./packaging/build_ffmpeg.sh` 编译成功（无需 nasm：arm64 汇编走 clang）。
- 自检：LGPL ✓；buildconf 无 gpl/nonfree/x264/x265 ✓；`otool -L` 只有 `/System/Library/*` 与 `/usr/lib/{libSystem,libz}` ✓；编码器 h264_videotoolbox / aac / pcm_s16le / rawvideo ✓；滤镜 scdet / blackdetect / freezedetect / silencedetect / concat / scale / pad / setsar / fps / trim / setpts / atrim / asetpts / aresample / format ✓；**drawtext ✗**。
- 原因：FFmpeg 8.1.3 `configure:4125` 为 `drawtext_filter_deps="libfreetype libharfbuzz"`——计划假设「drawtext 只需 FreeType」不成立。HarfBuzz 不在授权下载清单内，按指示停在此步并上报。
- 编码实测：lavfi testsrc2 1080×1920 2s → VT 1500k / 12M / 8M 均成功（h264 High yuv420p + aac）；10-bit（yuv420p10le）输入经 `-pix_fmt yuv420p` 编码成功；`render_preview.py` 无字幕时间线经 scratch ffmpeg 渲染成功，有字幕时间线失败于 `No such filter: drawtext`。
- 反向验证：`--verify-only` 对 Homebrew ffmpeg 与当前 `vendor/bin`（osxexperts GPL 版）均报「不是 LGPL / 含 GPL / 非系统库」并 exit 1，且未写 licenses。

## Deviations from Plan
- **D1** `BACKEND = "mediakit-http-v1"`（原 `mediakit-cli`）：旧续查状态自动作废（M4 约定）。
- **D2** 保留 M4 的 `CloudError(retryable, terminal)` 语义：网络/429/5xx 耗尽 → retryable；任务 failed/error/canceled → terminal（才清 `asr_task.json`）；401/403、4xx、非 JSON、业务失败均非 terminal。DONE 也认 `success/succeeded`。
- **D3** 上传缓存 `work/asr_upload.json` 绑定 **音频 sha256 指纹**（复用 `asr_state.fingerprint`，非计划的 size+mtime——GL-15 原子重写会改 mtime）+ Key 的 sha256 短指纹 + endpoint + BACKEND + 12h TTL；不存 Key、不存上传地址；转写成功后删除。写盘用 `schema.write_json`。
- **D4** 上传失败对 403（预签名过期）与 429/5xx/网络错误重新申请地址再传；其余 4xx 立即失败。`CloudClient.__repr__` 只显示掩码。`X-Amk-*` 值为命名常量 `CLIENT_RUNTIME="aicut"` / `CLIENT_TASK_SOURCE="cli/aicut"`。
- **D5** 计划 `verify()` 用 `grep -q "GNU Lesser General Public License"`，但 `ffmpeg -L` 原文在 "Public" 后换行 → 永远判失败；且 `pipefail` 下 `cmd | grep -q` 会因 SIGPIPE 误判。改为先收进变量再 grep "GNU Lesser General Public"。verify 改为一次列出全部问题后再 exit 1，并按代码实际用到的编码器/滤镜清单（REQUIRED_ENCODERS / REQUIRED_FILTERS）校验。
- **D6** 脚本加 `AICUT_FFMPEG_OUT` / `AICUT_FFMPEG_WORK` 覆盖产物与中间目录（为了在 scratchpad 验证而不覆盖 vendor/）；开头检查 clang/make/pkg-config/curl/shasum/tar/otool；`PKG_CONFIG_LIBDIR` 指向自建 prefix 防止探到 Homebrew 的 .pc；bash 里紧邻中文全角符号的变量一律写成 `${VAR}`（实测 `$FREETYPE_VER（` 被当成变量名报 unbound）。
- **D7** drawtext 需要 HarfBuzz（计划遗漏）。按决策 A：钉死 HarfBuzz 14.6.0 源码、cmake 静态编入；工具检查加 cmake；verify 新增 `REQUIRED_LIBS`（libfreetype libharfbuzz）；NOTICES 加 HarfBuzz（Old MIT 全文）；`HarfBuzz-COPYING` 进 licenses；源码包经 `vendor/sources/*.tar.xz` 随 `dist/sources/`；PACKAGING / TECH-STACK 同步。
- **D15** `tests/test_to_jianying.py` 夹具不再用 libx264：有 h264_videotoolbox 时用 `encode.h264_args("clip")`，否则退回原生 mpeg4；无 ffmpeg 仍 skip。新增守卫 `test_test_fixtures_do_not_need_x264`。
- **D8** `applog` 额外提供 `current_log_file()`；目录不可写退回 NullHandler；`reset_for_tests()` 按安装时保存的原钩子还原（防止测试替换链路目标后泄漏）。conftest 新增 autouse `_isolate_logs`（`AI_CUT_LOG_DIR` → tmp + 测后卸载）。
- **D9** 打包版任务子进程在 `proc.dispatch` 里 `applog.setup("cli")`（计划只在 `aicut.__main__`，那样冻结版子任务没有日志）。
- **D10** `cmd_prepare` 改为遍历 `PREPARE_STEPS` 并 `applog.stage()`；`cmd_build` 包 clips/preview/draft。aicut.py 行数保持 931（KI-55 不增长）。`gui/server.py` 789 行（<800）：诊断/关于路由放在新模块 `gui/support.py`，server 只加两处分发。`INTERNAL_ERROR_MSG` 从「把终端里的报错发给开发」改为「点左下角『导出诊断包』发给开发」（打包版没有终端）。
- **D11** 诊断包对 `project.json` 用**字段白名单**（name/title/preset/platform/target_duration/created/schema_version + material 文件名），去掉 calibration/brief（用户内容）；所有文本另把用户主目录替换为 `~`；`secrets.status()` 失败不影响导出；响应只返回文件名与所在文件夹名，不回完整路径。
- **D12** 「关于 / 第三方许可」：`GET /api/about` 返回 THIRD-PARTY-NOTICES 全文与版本（打包版读 `licenses/`，开发版读 `packaging/`），前端 `support.js` 弹窗（文本全程 `esc()`）。
- **D13** 任务失败 / 中断弹窗（`jobActionsHtml('ended')`）加「导出诊断包」按钮；未改弹窗关闭逻辑。
- **D14** 未修改 `docs/go-live-blockers.md`、`known-issues.md`、`docs/PROGRESS.md` 的状态（按指示由用户决定）；未归档计划、未提交。

## 代码审查（ecc:python-reviewer）与修复
无 CRITICAL。3 个 HIGH 已修（先补失败测试再修）：
- H1 提交成功但响应丢失 → 重跑换新 client_token 重复计费：提交前把 token 落盘 `work/asr_submit.json`（绑定音频指纹 + BACKEND），重跑复用；拿到 task_id 后或非可重试失败时清除。
- H2 `http.client.HTTPException`（IncompleteRead 等）逃出重试且不写 failed.json：传输层统一转为 `CloudError(retryable=True)`。
- H3 urllib 跟随重定向会把 `Authorization: Bearer` 带到新地址：自定义 opener 拒绝重定向，3xx 当错误。
已修 MEDIUM：轮询 404 视为终态并清续查状态；Key 含空白/控制字符提前报错（不让 http.client 带出原文）；上传未给 Content-Type 时用 `application/octet-stream`（防 urllib 补 form-urlencoded）；RedactFilter 格式化异常兜底、`stack_info` 脱敏、`setup()` 加锁；诊断包去掉 `title`（用户文本）、主目录脱敏兼顾 resolve 路径与 `/`、`work` 本身是符号链接时跳过；访达选中失败仍返回成功（`revealed:false`）。
未修 MEDIUM（列为待办）：云端提前作废已缓存 file_id 时，要到 12h TTL 才重传（提交被拒会报错，用户重试也会命中同一缓存）；`secrets.get` 对钥匙串/文件来源不 `.strip()`（已由 cloud 的控制字符检查兜住，llm 侧未覆盖）。

## Issues Encountered
- bash 变量紧贴全角括号 → `unbound variable`（D6 修复）。
- 计划的 LGPL grep 文案与 `pipefail` 误判（D5 修复）。
- drawtext 依赖 HarfBuzz（D7，blocked，待决策）。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_cloud.py`（重写） | 61 | 上传/提交/轮询/重试/幂等 token/脱敏/续查/上传缓存/默认传输层 |
| `tests/test_encode.py` | 10 | VT 参数、命名常量、全仓无 libx264、经 media_io 真编码 |
| `tests/test_packaging.py` | 10 | 无 mediakit-cli 调用、NOTICES 覆盖 uv.lock 运行时闭包、构建脚本 LGPL/钉哈希/自检清单、build_app/spec |
| `tests/test_applog.py` | 22 | 落盘、轮转、脱敏（Key/Bearer/sk-/预签名/参数/堆栈）、异常钩子、阶段计时、不可写目录 |
| `tests/test_applog_wiring.py` | 9 | die/run_cli 记日志、prepare/build 计时、冻结子进程 cli.log、入口先装日志、Key 登记、GUI 任务进 app.log |
| `tests/test_diagnostics.py` | 14 | 内容白名单、隐私排除、脱敏、meta、无项目、原子写、符号链接、默认目录、ffmpeg 信息 |
| `tests/test_server_support.py` | 17 | token/Origin 校验、项目名校验、导出与访达选中、失败、关于页、前端入口与转义 |

## 新发现缺陷（未修，建议登记）
- `pipeline/render_preview.py:20-24`：`FONT_CANDIDATES` 首选 `/System/Library/Fonts/PingFang.ttc` 在本机（macOS 26）不存在，实际回落到宋体；新系统上预览字幕字体与预期不符。
- `pipeline/render_preview.py:37-40` `esc()`：文本含 `%` 时转义不足——LGPL 构建报 `Stray %` 并静默丢掉该条字幕，Homebrew ffmpeg 9.0.2 直接失败（退出码 234）；与构建无关，属既有缺陷。
- `pipeline/cloud.py` `record_failure`：仍是非原子 `write_text`（KI-29 范围，未动）。
- `pipeline/secrets.py:get`：钥匙串 / 凭证文件分支返回值不 `.strip()`（只有环境变量分支 strip），带换行的 Key 会让 llm 侧 HTTP 头报错。
- `pipeline/cloud.py` 上传缓存：云端提前作废 file_id 时缓存不失效（见审查节）。

## Next Steps（需用户）
- 真账号 ASR 冒烟、干净 Mac 放行检查、剪映播放 VT 切片、码率评审。

## 第三轮：安全审查整改（M5 Python 部分，无 CRITICAL/HIGH）
测试先行：新增 `tests/test_m5_hardening.py`（30 条，全部先 RED）。测试数 930 → 960 passed；把 scratch LGPL ffmpeg 放在 PATH 最前再跑也是 960 passed；`~/Library/Logs/剪辑台` 未被创建。

| # | 级别 | 整改 |
|---|---|---|
| 1 | MEDIUM | `gui/jobs.py`：app.log 只记任务起止、退出码、输出行数，以及以 `[错误]`/`[x]`/`[!]`/`Traceback` 开头的行（路径只留文件名、截 300 字），普通输出不再进日志。`llm.py`：模型 / 接口正文不再写进 LLMError，改为「N 字，摘要 sha1 前 8 位」；HTTP 错误只取接口的 `error.message`。`understand_text.py` 结构异常同理。诊断包所有文本把绝对路径换成文件名（`applog.strip_paths`）。`diagnostics.py` 文档改为如实写明「保证什么 / 尽力而为什么」；导出时界面先显示一行说明（`COPY_DIAG_NOTICE`，在 toast 里，不弹确认框） |
| 2 | MEDIUM | `settings.save_key` 保存前先 `register_secret`；`start_job` 与导出诊断包之前调用 `applog.register_known_secrets()`，经新增的 `secrets.peek()` 只读环境变量、凭证文件和旧版文件，不碰钥匙串（有测试断言）。脱敏规则新增：Bearer/Basic 大小写不敏感、`sk-[A-Za-z0-9_-]{8,}`（覆盖 sk-proj-），以及 `AKLT`/`AKTP` 前缀的火山引擎 Key（仓库测试和文档里都是 AKLT 格式） |
| 3 | MEDIUM | `failed.json` 的 context 里，绝对路径一律只存文件名（`record_failure` 内部统一处理，转写处也只传文件名）；诊断包里的 failed.json 只保留 stage/error/at |
| 4 | LOW | 日志目录 0700；日志文件用自定义 `_open` 一创建就是 0600（轮转出的新文件同样）；诊断 zip 改名前先 chmod 0600 |
| 5 | LOW | 上传地址必须是 https 且有主机名，否则拒绝上传；`Request` 构造时的 ValueError 转成 CloudError，消息里只有异常类型名，不带 URL |
| 6 | LOW | 上传失败只记 HTTP 状态码和 `<Code>` 元素，不记正文 |
| 7 | LOW | 新增 `pipeline/safe_http.py`：响应体最多读 8 MB，超过就抛 CloudError / LLMError |
| 8 | LOW | 200 但返回体不是 JSON 时改为可重试：在请求循环内退避重试；用完次数后抛 retryable，提交阶段的 client_token 文件保留 |
| 9 | LOW | Key 含非 ASCII 字符时直接报 CloudError，不发请求 |
| 10 | LOW | CLI 进程每次运行写一个独立文件 `cli-YYYYmmdd-HHMMSS-<pid>.log`，不轮转，最多保留 `CLI_LOG_KEEP=20` 个；app.log 仍按大小轮转；诊断包用 `*.log*` 一并收集 |
| 11 | LOW | `llm.py` 改用 `safe_http` 的不跟随重定向 opener，与 cloud 共用（另捕获 `http.client.HTTPException`） |
| 12 | LOW | 诊断包 meta 里的 credentials 只留 configured/source，不带掩码 |

为配合新要求修改的旧测试：`test_cloud.py` 里两个假 `read()` 补上 size 参数；`test_diagnostics.py` 的掩码和 `~` 断言改为新规格；`test_applog*.py` 的 cli 日志改用 `current_log_file()` 定位。
未修（已由协调方登记为 KI）：`render_preview.esc()` 的 `%` 转义问题。

## 第四轮：终审整改（无 CRITICAL/HIGH）
测试先行：新增 `tests/test_m5_review2.py`（27 条，先确认失败再实现；其中 `--verify-only` / `--verify-sources` / 下载失败用假的 ffmpeg / otool / curl **实际执行脚本**，验证的是行为而不是 grep 文本）。测试数 960 → 987 passed；scratch LGPL ffmpeg 放在 PATH 最前再跑也是 987 passed。对真实 scratch 构建重跑 `--verify-only` 与 `--verify-sources` 均通过；`encode.preflight()` 实测返回可用。

| # | 级别 | 整改 |
|---|---|---|
| 1 | MEDIUM | `verify()` 先核对 `ffmpeg -version` 首行是否为 `ffmpeg version $FFMPEG_VER `；新增 `--verify-sources`（三个源码包是否齐全、哈希是否正确），`build_app.sh` 拷 `dist/sources` 之前必须先过这一步 |
| 2 | MEDIUM | `encode.preflight()`：用 0.1 秒 lavfi 画面加 `h264_args("proxy")` 输出到 `-f null -`，结果按进程缓存；失败时返回 `ENCODER_UNAVAILABLE`（「本机无法使用 VideoToolbox 硬件编码…」）。`cmd_prepare` 在检查完外发确认和 Key 之后、任何付费步骤之前调用它；GUI 的 `check_prepare_ready` 失败时返回 409，`need="encoder"`。conftest 的 autouse 默认视为可用，预检本身用假 runner 测 |
| 3 | MEDIUM | `_request` 与上传循环中，不可重试的 CloudError（响应过大、地址无效等）直接抛出，不再重试，也不再被标成可重试。`wait_task` 的状态在顶层或 `result` 里都认（completed / failed 两种形状都有测试），failed 时错误信息也会去 `result` 里找 |
| 4 | LOW | 构建脚本拆开所有 `a && b`（curl/mv、make/make install、cmake build/install、rm/mkdir）；下载失败时脚本以 curl 自己的退出码停下（实测 22）。另外修了一个原有隐患：otool 本身失败时，以前在 pipefail 下会被当成「没有非系统库」放行，现在算自检失败 |
| 5 | LOW | `timings.json`：成功、不到 1 秒、且比上次成功更短的运行视为「已完成被跳过」，保留原耗时，只加 `last_skipped`（启发式，不改 aicut 各命令）；失败照常覆盖 |
| 6 | LOW | PACKAGING.md 的日志文件名（`app.log` 轮转、`cli-时间-pid.log`）与诊断包内容按实现重写；NOTICES 写明位置为 `AI粗剪.app/Contents/Resources/licenses/`（依据：spec 的 datas 目标为 `licenses`，PyInstaller 6.22.3 把数据文件放在 Contents/Resources；未实际打包核对） |
| 7 | LOW | `support.reveal` 检查 `open -R` 的返回码；失败时返回 `revealed:false` 和 `REVEAL_FAILED_MSG`，前端显示这条提示 |
| 8 | LOW | `_prune_cli_logs` 对单个文件的 stat / unlink 失败都忽略，多个进程同时清理也不会关掉日志 |
| 9 | LOW | 随包的 `ffmpeg-buildconf.txt` 把 `--prefix=…` 改写为 `--prefix=<build-prefix>` |
| 10 | LOW | import 时给 `aicut` logger 挂 NullHandler 并设 `propagate=False`，`setup()` 之前的记录不会走 lastResort（不脱敏的 stderr） |
| 11 | LOW | 前端 `exportDiag` 请求进行中会忽略重复点击，所有「导出诊断包」按钮置为 disabled，结束后恢复 |
| 12 | LOW | 见上，脚本的执行级测试：LGPL 通过并去掉 prefix；GPL / 版本不符 / 缺 drawtext / 链接 Homebrew 库 / otool 失败 / 源码包哈希不符时都会失败；下载失败停在 curl |

其他：为保持 aicut.py 931 行（KI-55），`PREPARE_STEPS` 移到 `pipeline/readiness.py`；为配合新规格，改了 `test_m5_review2` 里 build_app 顺序断言的定位方式。
