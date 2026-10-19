# 技术栈 · AI 粗剪工具

> 本文是 [实施计划](PLAN-AI粗剪工具.md) 的附录，也是环境搭建的唯一依据。
> 原则：**能用标准库就不引依赖，能本地算就不上云。**

---

## 1. 总览

| 层 | 选型 | 版本 | 理由 |
|---|---|---|---|
| 语言 | Python | **3.11 – 3.12**（打包固定 3.12） | 生态最稳；3.13+ 的打包/原生扩展支持还不齐 |
| 环境管理 | **uv** | 0.10+ | 一条命令装 Python、锁依赖、建隔离环境；打包就在该环境内进行 |
| HTTP 服务 | 标准库 `http.server` | — | 无依赖、可打包；单机单用户，不需要并发框架 |
| 前端 | 原生 HTML/CSS/JS | — | 无构建步骤，改完刷新即生效；打包体积最小 |
| 桌面壳 | `pywebview` | ≥5 | 用系统 WebView（macOS WKWebView / Win WebView2），不背 Chromium |
| 媒体处理 | **ffmpeg / ffprobe 静态二进制** | 8.1.3（LGPL 自建，`packaging/build_ffmpeg.sh`） | 静态包不依赖用户机器；通过 subprocess 调用；H.264 一律 `h264_videotoolbox`（`pipeline/encode.py`） |
| 剪映草稿 | `pyJianYingDraft`（锁定版本） | 0.3.x | 生成 5.9 格式时间线，再适配各平台 |
| 语音转写 | 火山引擎 MediaKit HTTPS API（`pipeline/cloud.py`，标准库 urllib 直连） | 协议同 mediakit-cli 0.2.1 | 云端 ASR，带时间戳与说话人；**唯一允许上传素材的地方（仅音轨）**；不依赖 Node |
| 视频理解 / OCR | 未接入 | — | PRD FR-2 列为 P2；画面帧不出本机（PRD §7），如做须本地实现 |
| LLM | DeepSeek API（OpenAI 兼容） | — | 话题分段、信息类型、提问生成 |
| 存储 | JSON 文件 | — | 单机、单用户、可 diff、可手改 |
| 打包 | PyInstaller `onedir` | — | 目录式，启动快、不易被杀软误报 |
| 测试 | `pytest` + 黄金文件 | — | 纯逻辑单测 + 草稿结构比对 |

**不用**：FastAPI/Flask（不需要）、Electron（体积 2 倍）、数据库（单用户）、Node/Rust（无必要）、Docker（交付是桌面应用）。

---

## 2. 运行时依赖（用户机器）

| 依赖 | 来源 | 说明 |
|---|---|---|
| Python | 内嵌（PyInstaller 打包） | 用户不需要安装 |
| ffmpeg / ffprobe | 随包附带静态二进制 | 约 40–90 MB，见交付调研 |
| WebView | 系统自带 | macOS WKWebView；Win10/11 WebView2（缺失时安装器引导） |
| 网络 | 处理素材时需要 | 仅 ASR / LLM 需要；断网时云端步骤明确失败可重试，浏览、裁决、改分镜、预览、导出离线可用（PRD §7「断网与服务失败」） |

---

## 3. 开发环境（uv）

### 3.1 为什么是 uv

- **自带 Python 版本**：`uv python install 3.12` 一条命令（实测 120ms），不依赖 Homebrew；
- **锁文件**：`uv.lock` 固定 48 个包的确切版本，换机器/换人结果一致；
- **隔离干净**：`.venv` 由 uv 管理，不进库；
- **能打包**：PyInstaller 在 uv 的 venv 里正常工作（已实测，见 §3.3）。

### 3.2 常用命令

```bash
# 首次
uv python install 3.12          # 装托管 Python（不需要 brew）
uv sync --group dev             # 按 uv.lock 建 .venv 并装依赖

# 日常
uv run python aicut.py status 2026-09-01_活动
uv run python gui/server.py --open

# 改依赖
uv add <包名>                   # 或直接改 pyproject.toml 后 uv lock
uv lock --upgrade-package <包名>  # 只升某个包

# 打包（M5）
uv run pyinstaller packaging/ai-cut.spec --noconfirm --clean
```

### 3.3 打包可行性（已实测）

| 步骤 | 结果 |
|---|---|
| `uv python install 3.12` | 3.12.13，120ms |
| `uv venv --python 3.12` | 创建成功 |
| `uv pip install pyJianYingDraft pyinstaller pywebview` | 10 秒装完（含 pyobjc 一整套） |
| `pyinstaller --onefile hello.py` | 10 秒产出 8.6MB 可执行文件，**运行正常** |

结论：**uv 隔离环境完全支持 PyInstaller 打包**，不需要额外处理，也不需要系统 Python。

### 3.4 依赖清单（pyproject.toml）

运行时只 3 个：`pywebview`、`pyJianYingDraft`（锁 0.3.x）、`keyring`；开发期加 `pytest`、`pyinstaller`。
`ffmpeg` 不走 pip——开发用系统 `ffmpeg`，打包换静态二进制。

> `ffmpeg` 不进 pip：开发时用系统 `ffmpeg`（已在 PATH），打包时替换为静态二进制。

---

## 4. 外部服务

| 服务 | 调用方式 | 凭证 | 失败时怎么办（PRD §7「断网与服务失败」） |
|---|---|---|---|
| MediaKit ASR | HTTPS：申请上传地址 → PUT 音轨 → `POST /api/v1/tools/asr-subtitles` → 轮询 `GET /api/v1/tasks/{id}` | `MEDIAKIT_API_KEY`（Keychain，Bearer） | 缺 Key：处理前拦截并引导去设置（GL-02）；网络 / 服务失败：任务失败给中文原因，可重试；已提交任务续查、绑定音频指纹（GL-16） |
| DeepSeek API | HTTPS `POST /chat/completions` | `DEEPSEEK_API_KEY`（Keychain） | 话题分段 / 逐句标注失败：任务失败，已标注部分落盘，重试只补失败句（GL-09）；内容摘要 / 决策问题失败：退回兜底并在界面标明（KI-22）；超出项目 token 预算（默认 300 万，`AI_CUT_LLM_BUDGET_TOKENS`）：停止调用并说明（KI-32） |

**隐私边界**：只上传 16k 单声道音轨（→ 火山引擎 ASR）与转写文本（→ DeepSeek）；原片与画面帧永不出本机（PRD §7）。首次使用前须确认外发告知（GL-02）。

---

## 5. 版本约束

- 代码兼容 **Python 3.11+**（不用 3.12 独有语法糖）
- 打包固定 **3.12**：`pywebview` / `pyobjc` / PyInstaller 的 wheel 最齐
- 开发环境由 `uv.lock` 固定为 3.12.13，**不再依赖 Homebrew 的 3.14**
- 换机器复现：`git clone && uv sync --group dev` 即可

---

## 6. 目录约定

```
default-workspace/          ← 代码根目录（git 仓库）
├── aicut.py                ← 业务入口（CLI）
├── gui/                    ← 界面：server.py + static/
├── pipeline/               ← 处理模块（切、渲染、草稿、分析）
├── presets/                ← 风格预设 + brief 模板
├── packaging/              ← 打包脚本
├── docs/                   ← PRD / PLAN / 本文件 / 架构图
├── prototype/              ← 原型生成器
├── research/               ← 调研与校验器
├── projects/               ← 项目数据（**不进 git**）
└── dist/                   ← 构建产物（**不进 git**）
```

`projects/` 与 `dist/` 体积大、可重建，全部走 `.gitignore`。

---

## 7. 为什么是"标准库 + 原生 JS"

这套工具是**单机单用户的桌面应用**：

- 没有多租户、没有并发压力 → 不需要 FastAPI
- 前端只有 5 个页面、几十个交互 → 不需要框架和构建链
- 打包体积直接影响交付体验 → 每省 100MB 都值

代价是前端代码略啰嗦，但换来"没有 node_modules、没有构建失败、没有版本冲突"。

---

## 8. 第三方许可

| 组件 | 许可 | 分发义务 |
|---|---|---|
| ffmpeg / ffprobe | LGPL 2.1+（**已采用 LGPL 自建**，见 `packaging/build_ffmpeg.sh`） | 随包附许可全文、configure 行与源码（`dist/sources/`）；声明见 `packaging/THIRD-PARTY-NOTICES.txt` |
| FreeType 2.14.3 / HarfBuzz 14.6.0（静态编入 ffmpeg，drawtext 用） | FTL / Old MIT | FTL 须在文档署名；两者许可全文与源码随包 |
| PyInstaller | GPL + 启动器例外 | 打包产物不受 GPL 约束（有例外条款），附声明即可 |
| pywebview | BSD-3 | 附声明 |
| pyJianYingDraft | 见其仓库许可 | 附声明 |
| Python 运行时 | PSF | 附声明 |

随包交付 `THIRD-PARTY-NOTICES.md`，列全上述组件与版本。

## 9. 缺口与待办

技术因素的系统性审查见 **[TECH-GAPS.md](TECH-GAPS.md)**（12 项，4 项需在 M1 前定）。

## 10. DeepSeek Harness 插件对照

本机已装且**够用**的只有 mediakit 系列（`~/.agents/skills`）：

| 能力 | 由谁提供 | 本方案是否用 |
|---|---|---|
| 语音转字幕 / 视频理解 / OCR / 抽帧 | `byted-mediakit-video` | ✅ ASR 协议参照（运行时 HTTPS 直连）；视频理解 / OCR 不用（画面帧不出本机） |
| 音频转码 / 人声分离 / 语音端点 | `byted-mediakit-audio` | ⏳ 远场收音差时再启用 |
| 裁剪 / 拼接 / 字幕压制 | `byted-mediakit-editing` | ❌ 直接用 ffmpeg，少一层依赖 |
| 图片处理 / OCR | `byted-mediakit-image` | ❌ 不需要 |
| 统一入口与鉴权检查 | `byted-mediakit-shared` | ✅ 已用于 `MEDIAKIT_API_KEY` |

**结论：不需要再装新插件。** Python、ffmpeg、pywebview 都不是 harness 插件，是本地依赖，由 `requirements.txt` + 静态二进制管理。
