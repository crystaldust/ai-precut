# macOS 打包说明

## 一条命令

```bash
./packaging/build_app.sh
open "dist/AI粗剪.app"
```

首次会用 `packaging/build_ffmpeg.sh` **从源码构建** LGPL 静态 ffmpeg/ffprobe 到 `vendor/bin/`
（FFmpeg 8.1.3 + FreeType 2.14.3 + HarfBuzz 14.6.0，源码包 SHA256 钉死、`curl -f` 下载，5–10 分钟；构建机需要
Xcode Command Line Tools、`pkg-config` 与 `cmake`，用户机器不需要；不进 git），构建后自检
（LGPL、`otool -L` 只链系统库、`h264_videotoolbox` 与代码用到的滤镜齐全），不过就中止。
已有 `vendor/bin/ffmpeg` 也要先过 `./packaging/build_ffmpeg.sh --verify-only` 才复用。
然后 PyInstaller 打出 `dist/AI粗剪.app`，并在 `dist/` 旁放：

- `THIRD-PARTY-NOTICES.txt`（第三方许可声明；App 内「关于 / 第三方许可」显示同一份）；
- `首次打开说明-macOS.txt`（给剪辑师：macOS 15+「仍要打开」路径）；
- `sources/`：ffmpeg / FreeType / HarfBuzz 源码包 + `build_ffmpeg.sh`（LGPL 对应源码随包提供）。

## 打包后行为差异

| 项 | 开发 | 打包后 |
|---|---|---|
| 项目目录 | 仓库内 `projects/` | `~/Documents/AI粗剪/`（可用 `AI_CUT_PROJECTS` 覆盖） |
| 子任务 | 子进程跑 `aicut.py` | 同进程导入执行（`pipeline/proc.run_inprocess`） |
| ffmpeg | 系统 PATH | App 内 `Contents/Frameworks/bin/`（LGPL 自建），启动时插到 PATH 最前 |
| H.264 编码 | `h264_videotoolbox`（`pipeline/encode.py`） | 同左；码率显式：代理 1.5M / 切片 12M / 预览 8M |
| 语音转写 | Python 直连 MediaKit HTTPS API（`pipeline/cloud.py`） | 同左；不需要 Node / mediakit-cli |
| 日志 | `~/Library/Logs/剪辑台/`（可用 `AI_CUT_LOG_DIR` 覆盖） | 同左 |
| 文件选择 | osascript | pywebview 原生对话框 |
| pyJianYingDraft | `~/.aicut/venv` | 直接打进 App |

## 已验证（2026-10-18）

- App 启动 → 本地服务自动选端口 → 窗口正常；
- `/api/health` 显示的 ffmpeg 是 **App 内置 7.0**，不是系统 Homebrew；
- 在 App 内新建项目并跑完整 `prepare`：抽音轨 → 云端 ASR → 声音/文本/画面三路 → 三档 → 摘要 → 问题 → 选段，**退出码 0**；
- 在 App 内跑 `build`：切镜头 → 渲染预览 → 生成剪映草稿 → 校验 **PASS**。

## 给后续开发的硬规则

打包后**没有可用的 Python 解释器路径**，所以：

- 任何"再起一个 aicut 进程"的代码路径都必须换成 `server.run_aicut([...])`
  （冻结时同进程执行，开发时走子进程）；
- 任何 `sys.executable pipeline/xxx.py` 都必须换成 `aicut._run_pipeline(...)`
  或 `pipeline.proc.run_inprocess(...)`。

违反这条规则的表现很具体：**点一下创建项目，会弹出第二个 App 窗口，且请求永远不返回**
（旧代码用 `sys.executable` 调 `aicut.py`，在 .app 里等于又启动了一次 App）。
这个 bug 在 2026-10-18 出现过并修复，见 `server.run_aicut`。

## 性能参考（54 分钟 1080×1920 素材）

| 阶段 | 耗时 | 说明 |
|---|---|---|
| 生成 540p 分析代理 | 待实测 | VideoToolbox 1.5Mbps（原 x264 ultrafast/crf30 为 3–4 分钟）；这是首次分析的主要耗时 |
| 云端 ASR | 5–10 分钟 | 后台任务，可中断；重跑会**接着查**，不重复计费 |
| 三路分析 + 三档 + 摘要 + 问题 + 选段 | 1–2 分钟 | 本地 + LLM |
| 切片 + 渲染预览 | 2–3 分钟 | 依赖成片长度 |

**首次完整分析约 10–15 分钟**，之后重跑会跳过已完成的步骤。

## 已知限制

1. **未签名/未公证**：首次打开会被 Gatekeeper 拦。macOS 15（Sequoia）起右键 → 打开**不再有效**，
   须先双击一次，再到 系统设置 → 隐私与安全性 → 底部「仍要打开」→ 输入密码（详见随 dist 交付的
   `packaging/首次打开说明-macOS.txt`）；macOS 13/14 仍可按住 Control 点 App →「打开」。
2. **ffmpeg 为 LGPL 构建**（`packaging/build_ffmpeg.sh`，无 x264/x265、无 `--enable-gpl/--enable-nonfree`），
   H.264 一律走 VideoToolbox；许可见 `THIRD-PARTY-NOTICES.txt`，对应源码随包在 `dist/sources/`。
   FFmpeg 8.x 的 `drawtext`（预览片字幕）依赖 libfreetype **和 libharfbuzz**：脚本同时静态编入
   FreeType 2.14.3（FTL）与 HarfBuzz 14.6.0（Old MIT，cmake 构建，glib/icu/cairo/graphite/CoreText 全关）。
3. **仅 arm64**：Intel Mac 需要另外一份 x86_64 静态二进制与构建。
4. 首次启动会弹**钥匙串授权**（读 API Key），选"始终允许"。

## 日志与诊断包（GL-19）

- 日志目录 `~/Library/Logs/剪辑台/`（0700，文件 0600，可用 `AI_CUT_LOG_DIR` 覆盖），UTF-8：
  - `app.log`：剪辑台进程，5 MB × 5 份轮转（`app.log.1`…`app.log.5`）；任务只记起止、退出码、输出行数，
    以及以 `[错误]` / `[x]` / `[!]` / `Traceback` 开头的行（路径只留文件名，每行最多 300 字），不记普通输出；
  - `cli-YYYYmmdd-HHMMSS-<pid>.log`：每次命令行 / 任务子进程运行一个文件（多进程不共写），只保留最近 20 个；
  - 已登记的 API Key、`Bearer` / `Basic` 令牌、`sk-` 令牌、`AKLT…` / `AKTP…` Key、URL 查询串（预签名地址）一律打码。
- 阶段耗时：每个项目 `work/timings.json`（处理素材 12 段 + 生成成片的 clips / preview / draft）；
  已完成而被跳过的步骤（成功且 < 1 秒、短于上次）不覆盖原耗时，只记 `last_skipped`。
- 诊断包：剪辑台左侧栏底部或任务失败弹窗里点「导出诊断包」（导出时先提示内容范围）→ 保存到「下载」
  （没有则桌面），文件 0600，并在访达中选中（打不开访达时提示去「下载」里找）。内容：
  - `meta.json`：版本、macOS、架构、Python、是否打包版、ffmpeg 版本与是否 LGPL、日志目录、是否已确认外发说明、
    各 Key **是否已配置 + 来源**（不含明文，也不含掩码）；
  - `logs/`：日志目录下全部 `*.log*`；
  - `project/`（导出时选中了项目才有）：`project.json` 只留 name / preset / platform / target_duration / created /
    schema_version 与素材文件名；`work/timings.json`、`work/asr_task.json`；`work/failed.json` 只留 stage / error / at；
    `files.txt`（work/ 下相对路径 + 字节数，不跟随符号链接）。
  - 所有文本：打码同上，绝对路径只留文件名。**不含**转写文本、分镜 / 选段、音视频、片名、剪辑偏好。
    日志里的错误行和云端错误文案仍可能夹带少量用户内容（尽力而为，见 `pipeline/diagnostics.py`）。

## 换图标 / 改版本

- 图标：`icon=None` 改为 `.icns` 路径；
- 版本：`packaging/ai-cut.spec` 里的 `CFBundleShortVersionString`。
