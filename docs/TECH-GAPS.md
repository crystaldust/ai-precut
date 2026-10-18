# 技术因素审查 · 缺口清单

> 目的：在开工前把 PRD/PLAN 里**没写、但会影响交付**的技术因素找出来。
> 结论：找到 12 项，其中 4 项必须在 M1 前定掉（否则返工），其余按里程碑归位。

---

## 1. 总览

| # | 因素 | 现状 | 风险 | 处理 | 归属 |
|---|---|---|---|---|---|
| 1 | **环境隔离与依赖锁定** | 无（裸 python3 + 临时 venv） | 换机器就装不上；版本漂移 | **uv + pyproject + uv.lock** | ✅ 已解决 |
| 2 | **ffmpeg 许可（GPL/LGPL）** | 未评估 | 分发二进制有合规义务 | 用 LGPL 构建 + 附许可文本 | M5 前 |
| 3 | **密钥管理实现** | 明文 `~/.mediakit/api_key` | 客户机器泄露 | `keyring` + 首次向导 | M1 |
| 4 | **数据 schema 版本与迁移** | 无版本号 | 升级后旧项目打不开 | `schema_version` + 迁移函数 | M1 |
| 5 | **云端调用超时/重试/限流** | 裸调用，无超时策略 | 卡死、重复计费 | 统一 client：超时+指数退避+幂等 token | M1 |
| 6 | **Windows 路径/编码/长路径** | 只在 Mac 验证 | 中文路径、GBK 控制台、260 字符 | 统一 `pathlib` + UTF-8 + 长路径前缀 | M4 |
| 7 | **单实例与并发** | 无锁 | 两个 ffmpeg 抢满 CPU；端口冲突 | 单实例锁 + 任务队列串行 | M4 |
| 8 | **磁盘空间与清理** | 无预检 | 9GB 素材 + 代理 + 草稿副本撑爆磁盘 | 启动预检 + 代理/切片 TTL 清理 | M4 |
| 9 | **测试与回归样本** | 手工验证 | 改一处崩一片 | 单测 + 剪映草稿黄金文件 + 3 条素材 e2e | M1 起 |
| 10 | **打包细节（pywebview/资源/WebView2）** | 未做 | 打包后白屏、找不到 static | hooks + `sys._MEIPASS` + 资源清单 | M5 |
| 11 | **构建矩阵（arm64 / x86_64）** | 只做本机 | Intel 机器跑不了 | 双架构产物 + 冒烟测试 | M5 |
| 12 | **版本号 / changelog / 回滚** | 无 | 出问题无法定位版本 | 语义化版本 + 变更记录 + 产物校验和 | M5 |

---

## 2. 必须现在定的四项

### 2.1 环境隔离：uv（已落地）

- `uv python install 3.12`（120ms，托管在 `~/.local/share/uv/python`）
- `uv sync --group dev` → 生成 `.venv`（3.12.13）
- `uv run python aicut.py list` 可直接跑现有代码
- **打包验证**：在 uv 的 venv 里装 `pyinstaller 6.22.3`，`--onefile` 出一个 8.6MB 可执行文件并成功运行（10 秒）

结论：**uv 隔离环境完全支持 PyInstaller 打包**，不需要额外处理。

### 2.2 密钥：Keychain / Credential Manager

- 用 `keyring`，service 名 `ai-cut`，账号 `mediakit` / `deepseek`
- 首次启动向导：粘贴 Key → 校验（发一个最小请求）→ 存 Keychain
- 日志与诊断包**永不打印 Key**；`config show` 只显示掩码（`AKLT****9f2a`）

### 2.3 schema 版本

- `project.json` 增加 `"schema_version": 1`
- 读取时若版本低于当前，跑迁移函数；高于则提示"项目由更新版本创建"
- 迁移函数写单测（v0 → v1 的样例文件）

### 2.4 云端调用的统一 client

现在 `aicut.py` 里直接 `subprocess.run(["mediakit-cli", ...])`，没有超时与重试。要抽成 `pipeline/cloud.py`：

| 项 | 策略 |
|---|---|
| 超时 | 提交 30s；轮询单次 20s；总超时 = 素材时长 × 2 + 10min |
| 重试 | 网络类错误指数退避 3 次（1s/3s/9s），业务错误不重试 |
| 幂等 | 复用 `client_token`（同一次逻辑请求的重试链用同一个） |
| 限额 | 单项目并发 ASR = 1；全局限 2 |
| 失败 | 落 `work/failed.json`，界面给"重试 / 跳过" |

---

## 3. 其余八项要点

### 3.1 ffmpeg 许可（合规）

ffmpeg 有两种构建：**LGPL**（不含 x264/x265 等 GPL 组件）与 **GPL**。
我们只通过命令行调用，不链接其库，属于"调用独立程序"；但**随包分发 ffmpeg 二进制本身仍需遵守其许可**（附许可文本、提供源码获取方式）。

- 建议：选 **LGPL 构建**（BtbN 的 `*-lgpl-*`），体积也更小；
- 若某功能确实需要 GPL 组件（如 libx264 编码），再评估是否接受 GPL 义务；
- 随包附 `THIRD-PARTY-NOTICES.md`，列出 ffmpeg / PyInstaller / pywebview 的许可。

### 3.2 Windows 路径与编码

| 坑 | 处理 |
|---|---|
| 控制台 GBK | 所有 `subprocess` 显式 `encoding="utf-8", errors="replace"`；日志文件 UTF-8 |
| 中文/空格路径 | 全程 `pathlib`，拼接不吃 shell；ffmpeg 参数用 list 传，不拼字符串 |
| 长路径 >260 | 关键目录用短名（`%LOCALAPPDATA%\ai-cut`），草稿名限长 |
| 换行/编码 | 写 JSON 用 `ensure_ascii=False` + UTF-8 无 BOM；对外文本用 CRLF |

### 3.3 单实例与并发

- 启动时抢锁文件（`~/Library/Application Support/ai-cut/instance.lock`），已存在则聚焦已有窗口
- ffmpeg 任务一律进**串行队列**（一次只跑一个重任务），状态显示"排队中"
- 端口：服务绑定 8765 起，被占则 +1（已有逻辑）

### 3.4 磁盘与清理

- 导入前预检：素材所在盘剩余 ≥ 素材体积 × 0.5 + 2GB
- 代理（540p）与切片缓存设 TTL（默认 14 天），启动时清理过期项
- 草稿副本进剪映库后，本地 staging 立即删除

### 3.5 测试与回归

| 层 | 内容 |
|---|---|
| 单测 | 时间码换算、字幕切卡、覆盖选段约束、schema 迁移 |
| 黄金文件 | 3 份已知草稿 JSON（Mac / Win-6.x / 5.9），断言结构一致 |
| e2e | 3 条真实素材（各 ≤5 分钟）跑全流程，产出 预览 + 草稿 |
| 回归 | 每次改 `to_jianying.py` 必须跑 `validate_draft.py` 全绿 |

### 3.6 打包细节（M5 重点）

- `pywebview` 需要 `--collect-all webview`（含 WebView2/EdgeChromium 的 JS 资源）
- 静态资源用 `sys._MEIPASS` 解析，不能写 `__file__` 相对路径
- macOS：`.app` 内启动本地 HTTP 服务 + WKWebView 加载 `http://127.0.0.1:port`
- Windows：检测 WebView2 Runtime，缺失时引导安装（Evergreen Bootstrapper ~1.5MB）
- 退出时杀掉子进程组（ffmpeg 不能被留在后台转码）

### 3.7 构建矩阵

- macOS arm64（必须）、macOS x86_64（可选，按用户机器定）
- Windows x64（必须）
- 产物附 `SHA256SUMS`，交付时给出校验方法

### 3.8 版本与回滚

- 语义化版本 `0.x.y`，界面"关于"显示版本 + 构建时间 + git commit
- `CHANGELOG.md` 记录每次交付的变更与已知问题
- 回滚方式：保留上一版安装包；数据 schema 向后兼容（只升不降）

---

## 4. 与文档的对应关系

| 文档 | 需要补充的内容 |
|---|---|
| `TECH-STACK.md` | ✅ 已加：环境管理（uv）、许可、缺口指引 |
| `PLAN-AI粗剪工具.md` | ✅ 已加：M1 前置任务（密钥/schema/cloud client）、M5 打包细节 |
| `PRD-AI粗剪工具.md` | 待加：非功能需求补"可复现构建"与"许可合规"两条 |
| `SOP.md` | 待加：开发环境用 uv（面向维护者） |
| `README.md` | 待加：`uv sync` 快速开始 |
