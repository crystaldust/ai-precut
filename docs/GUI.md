# 剪辑台（图形界面）

给剪辑师用的界面：**双击启动 → 浏览器里点点 → 出片**。不用碰 JSON、不用记命令。

---

## 一、剪辑师怎么用（6 步）

1. **双击** `启动剪辑台.command`，浏览器会自动打开（地址一般是 `http://127.0.0.1:8765`）。
   > 关掉那个黑色终端窗口，就是退出。
   > **第一次打开**会先弹「哪些数据会发到云端」的说明：音轨（16kHz 单声道）→ 火山引擎转写，转写文字 → DeepSeek 分析；原片和画面不出本机。点「我知道了，继续」后，在左下角 **⚙ 设置 · API Key** 里填两个 Key（只存本机钥匙串）。
2. 左上角 **＋ 新建项目** → 选素材文件 → 填项目名/片名 → 选风格预设。
3. 点 **① 处理素材**，等进度条走完（抽音轨、转写、找废片）。
4. 去 **文稿** 标签，点句子右边的 **＋** 把要的句子加进分镜表；
   去 **分镜表** 标签，用 ↑↓ 调顺序、改字幕、删镜头，选中一行还能"试听这一镜"。
5. 点 **② 生成成片**，跑完去 **版本** 标签看片，打开剪映精修。
6. 要在 Windows 上精修：**版本** 标签 → 「导出 Windows 剪映包」→ 完成后点「在访达中显示」，把 `片名_vN_Windows.zip` 拷到 Windows，解压后双击 `INSTALL.bat`。

> 任务弹窗里随时可以「取消任务」；失败或取消后可以「重试」或「关闭」。同一时间只跑一个任务。

> 每次生成都是新版本（v1、v2、v3…），不会覆盖上一版。剪映里的草稿名是 `片名_v3`。

**常见操作对照**

| 想做的事 | 在哪点 |
|---|---|
| 换一句字幕 | 分镜表 → 直接改那个输入框（自动保存） |
| 镜头长一点/短一点 | 分镜表 → 选中 → 小播放器定位 → 设为入点/出点 |
| 删镜头 / 调顺序 | 分镜表 → ✕ / ↑ ↓ |
| 加一个空镜 | 分镜表 → ＋空镜（用当前位置，默认 3 秒） |
| 重出一版 | 生成成片（版本号自动 +1） |
| 剪映正开着不能生成工程 | 生成成片 → 勾"只出预览" |

---

## 二、开发者怎么维护

### 架构（三层，别搞混）

```
gui/static/index.html   界面（原生 JS，无框架无构建；任务弹窗 jobs.js、设置 settings.js）
        ↓ fetch
gui/server.py           本地服务（127.0.0.1，只做转发和文件服务）；任务子进程 gui/jobs.py，Key/告知 gui/settings.py
        ↓ subprocess
aicut.py                业务入口（和命令行完全同一套逻辑）
        ↓
pipeline/*.py           切、渲染、草稿生成、转写整理、废片检测
```

**原则：GUI 不实现业务逻辑。** 任何流程改动都改 `aicut.py`，GUI 只负责按钮和展示。这样命令行和界面永远一致。

### 加一个功能的标准路径

1. `aicut.py` 加子命令，本地跑通；
2. `gui/server.py` 加一个 `/api/xxx`，内部 `subprocess` 调它（异步任务用 `gui/jobs.py` 的 `start_job`，并在 `JOB_COMMANDS` 登记）；
3. `index.html` 加按钮 + 调接口。

### 接口一览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/projects` | 项目列表 |
| GET | `/api/presets` | 预设列表 |
| GET | `/api/state?project=` | 项目全量状态（阶段/版本/分镜/文稿/废片） |
| GET | `/api/job/<id>` | 任务进度（轮询，含日志）：`{status: running/done/failed/cancelled, log, exit, task, project}` |
| GET | `/api/config` | 设置页：是否已确认数据外发说明 + 两种 Key 的状态（只给掩码） |
| POST | `/api/new` | 新建项目 |
| POST | `/api/pick` | 弹 macOS 选文件对话框，返回路径（浏览器拿不到本地路径，必须走这里） |
| POST | `/api/shots?project=` | 保存分镜表 |
| POST | `/api/job` | 起任务：`{project, task:'prepare'|'build'|'select'|'export', no_draft, version, target}`；已有任务在跑 → 409 `{job_id}`；处理素材缺告知 / 缺 Key → 409 `{need:'consent'|'keys', missing}` |
| POST | `/api/job/<id>/cancel` | 取消任务（连同它拉起的 ffmpeg 一起停） |
| POST | `/api/config/consent` | 记录「已阅读数据外发说明」（存 `~/.config/ai-cut/consent.json`，不进项目） |
| POST | `/api/config/key` | 保存 Key：`{provider:'mediakit'|'deepseek', value}`，存本机钥匙串，响应只含掩码 |
| POST | `/api/config/key/delete` | 清除 Key：`{provider}` |
| POST | `/api/open` | 在访达打开项目 / 打开剪映 / `{target:'export', version}` 在访达中选中这一版的 Windows 包 |
| GET | `/media/<project>/proxy` | 代理片（支持 Range，能拖进度条） |
| GET | `/media/<project>/preview/v3` | 某一版的预览片 |

### 界面改哪里

- 配色：`index.html` 顶部 `:root` 里的 CSS 变量；
- 文案/按钮：搜中文即可，都是硬编码；
- 分镜表一行：搜 `viewShots()`；
- 任务进度弹窗：`static/jobs.js` 的 `startJob()` / `pollJob()`（文案常量在文件顶部）；
- 设置页与首次使用的数据外发说明：`static/settings.js`（文案常量在文件顶部）。

### 部署到另一台 Mac

| 依赖 | 怎么装 |
|---|---|
| Python 3.10+ | `brew install python` 或官网安装包 |
| ffmpeg | `brew install ffmpeg` |
| API Key | 首次打开剪辑台后，在左下角「⚙ 设置 · API Key」里填（存本机钥匙串） |
| pyJianYingDraft | 不用管，第一次点"生成成片"时自动装到 `~/.aicut/venv` |
| 剪映专业版 | Mac 版即可；生成草稿前要先退出剪映 |

交付时把整个目录拷过去，**再把 `projects/` 里旧项目清掉**（或保留一个做示范）。

### 已知限制

- 只支持 macOS（用到 `osascript` 选文件、剪映 Mac 版草稿路径）。
- 只监听 `127.0.0.1`，不能远程访问（也是安全考虑：别把草稿操作暴露到局域网）。
- 一次只跑一个任务（`gui/jobs.py` 的 `MAX_ACTIVE_JOBS`）；再点会提示「已有任务在运行」，可以查看进度或先取消它。
- 剪映 11.6 打开草稿后会自动加密工程，之后脚本不能再改写——所以永远出新版本，不改旧版。

---

## 三、从命令行跑（调试用）

```bash
python3 gui/server.py --port 8765 --open   # 前台启动，看日志
python3 gui/server.py --port 8800          # 换端口
```

服务端会把 `aicut.py` 的输出实时打到浏览器弹窗里，出问题就把那段日志发回来。
