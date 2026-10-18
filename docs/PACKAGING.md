# macOS 打包说明

## 一条命令

```bash
./packaging/build_app.sh
open "dist/AI粗剪.app"
```

首次会自动下载 ffmpeg/ffprobe 静态二进制到 `vendor/bin/`（约 60MB，不进 git），
然后 PyInstaller 打出 `dist/AI粗剪.app`（约 135MB，内含 Python 3.12 + WebKit 壳 + 两个静态二进制）。

## 打包后行为差异

| 项 | 开发 | 打包后 |
|---|---|---|
| 项目目录 | 仓库内 `projects/` | `~/Documents/AI粗剪/`（可用 `AI_CUT_PROJECTS` 覆盖） |
| 子任务 | 子进程跑 `aicut.py` | 同进程导入执行（`pipeline/proc.run_inprocess`） |
| ffmpeg | 系统 PATH | App 内 `Contents/Frameworks/bin/`，启动时插到 PATH 最前 |
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
| 生成 540p 分析代理 | 3–4 分钟 | ultrafast/crf30；这是首次分析的主要耗时 |
| 云端 ASR | 5–10 分钟 | 后台任务，可中断；重跑会**接着查**，不重复计费 |
| 三路分析 + 三档 + 摘要 + 问题 + 选段 | 1–2 分钟 | 本地 + LLM |
| 切片 + 渲染预览 | 2–3 分钟 | 依赖成片长度 |

**首次完整分析约 10–15 分钟**，之后重跑会跳过已完成的步骤。

## 已知限制

1. **未签名/未公证**：首次打开会被 Gatekeeper 拦，右键 → 打开。
2. **ffmpeg 是 GPL 构建**（含 x264/x265）：自己用没问题；对外分发需换 LGPL 构建或履行 GPL 义务。
3. **仅 arm64**：Intel Mac 需要另外一份 x86_64 静态二进制与构建。
4. 首次启动会弹**钥匙串授权**（读 API Key），选"始终允许"。

## 换图标 / 改版本

- 图标：`icon=None` 改为 `.icns` 路径；
- 版本：`packaging/ai-cut.spec` 里的 `CFBundleShortVersionString`。
