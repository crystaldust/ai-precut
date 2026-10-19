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
| GET | `/api/projects` | 项目列表 + `stale_job`（上次退出时留下、仍在跑的任务，顶部提示条显示） |
| GET | `/api/presets` | 预设列表 |
| GET | `/api/state?project=` | 项目全量状态（阶段/版本/分镜/文稿/废片） |
| GET | `/api/job/<id>` | 任务进度（轮询，含日志）：`{status: running/done/failed/cancelled, log, exit, task, project}` |
| GET | `/api/config` | 设置页：是否已确认数据外发说明 + 两种 Key 的状态（只给掩码） |
| POST | `/api/new` | 新建项目 |
| POST | `/api/pick` | 弹 macOS 选文件对话框，返回路径（浏览器拿不到本地路径，必须走这里） |
| POST | `/api/shots?project=` | 保存分镜表 |
| POST | `/api/job` | 起任务：`{project, task:'prepare'|'build'|'select'|'export'|'questions', no_draft, version, target}`；已有任务在跑 → 409 `{job_id}`；处理素材 / 重新生成决策问题缺告知 / 缺 Key → 409 `{need:'consent'|'keys', missing}` |
| GET | `/api/cache?project=` | 「清理缓存」弹窗：可清理的项 `{items:[{label,path,bytes}], total}` |
| POST | `/api/cache/clean` | 清理缓存 `{project}` → `{freed}`；这个项目有任务在跑 → 409 |
| POST | `/api/window` | App 内开子窗口 `{project, page:'browse'|'calibrate'|'confirm'}` → `{opened}`；`false` 时页面自己 `window.open`（浏览器模式） |
| POST | `/api/job/<id>/cancel` | 取消任务（连同它拉起的 ffmpeg 一起停） |
| POST | `/api/config/consent` | 记录「已阅读数据外发说明」（存 `~/.config/ai-cut/consent.json`，不进项目） |
| POST | `/api/config/key` | 保存 Key：`{provider:'mediakit'|'deepseek', value}`，存本机钥匙串，响应只含掩码 |
| POST | `/api/config/key/delete` | 清除 Key：`{provider}` |
| POST | `/api/open` | 在访达打开项目 / 打开剪映 / `{target:'export', version}` 在访达中选中这一版的 Windows 包 |
| GET | `/media/<project>/proxy` | 代理片（支持 Range，能拖进度条） |
| GET | `/media/<project>/preview/v3` | 某一版的预览片 |

### 安全模型（单用户本机）

- 服务只监听 `127.0.0.1`，校验 `Host` / `Origin`，写接口要求 `application/json`。这挡住的是**别的网站**
  （浏览器里的跨站请求、DNS 重绑定）。
- **页面里没有任何凭证**（KI-88）。桌面壳 / 「启动剪辑台」打开的是一次性入口 `/?nonce=<随机串>`（5 分钟内有效、
  只能用一次，只存在服务进程内存里）；服务端兑换后下发会话 cookie `aicut_session_<端口>`
  （`HttpOnly; SameSite=Strict; Path=/`，每次启动随机、不落盘）并跳回去掉 nonce 的地址。之后页面、`/api/*`、
  `/media/*`（`<video>` 播放）都只认这个 cookie；`/static/*.js` 不含秘密，照常公开。子窗口由 `/api/window`
  在服务端各发一个 nonce，不依赖窗口间共享 cookie。没有有效 nonce / cookie 的页面请求只得到 403
  「请从剪辑台 App 打开」。
- 因此**同一台 Mac 上的其他用户或进程** `GET /` 拿不到任何凭证，也调不动接口。nonce 不出现在进程参数里：
  App 内由 pywebview 直接加载；浏览器模式经 `osascript` 的标准输入传给默认浏览器。
- 桌面壳用 `webview.start(private_mode=False)`：pywebview 的 private 模式每开一个窗口都会清空共享的 WebKit
  数据，开子窗口会把主窗口登出。会话 cookie 本身不写盘，每次启动值都不同。
- **残余风险（KI-90）**：浏览器模式下 cookie 不按端口隔离。若本机另一用户在 `127.0.0.1` 的其他端口起服务并诱导
  剪辑师用**同一浏览器**访问，对方能收到这个 cookie。App（WKWebView 只加载剪辑台自己的页面）不受影响；多人
  共用的电脑请用 App，不要用浏览器模式。
- 浏览器模式：服务重启后旧标签页的请求会被拒（「页面已过期：请关掉这个页面，从剪辑台重新打开」）；
  不带 `--open` 启动时，终端会打印一条一次性入口链接。
- 页面 CSP 只允许同源脚本（`script-src 'self'`）；静态文件只发 `gui/static_files.py` 白名单里的。

### 界面改哪里

- 脚本：每个页面的脚本在同名 `.js` 里（`index.js` / `browse.js` / `confirm.js` / `calibrate.js`）。
  CSP 只允许同源脚本：**不要写 `onclick=` 之类的内联事件**，在元素上写 `data-act="动作名"`
  （输入框 `data-input`、下拉框 `data-change`），再在脚本末尾的 `ACTIONS` 里注册；新增静态文件要加进
  `gui/static_files.py` 的白名单，否则服务端 404、打包也不带；
- 配色：`index.html` 顶部 `:root` 里的 CSS 变量；
- 文案/按钮：搜中文即可，都是硬编码；
- 分镜表一行：搜 `viewShots()`；
- 任务进度弹窗：`static/jobs.js` 的 `startJob()` / `pollJob()`（文案常量在文件顶部）；
- 设置页与首次使用的数据外发说明：`static/settings.js`（文案常量在文件顶部）。

### 部署到另一台 Mac

| 依赖 | 怎么装 |
|---|---|
| uv | 按 https://docs.astral.sh/uv/ 安装；双击 `启动剪辑台.command` 会用 uv 按 `uv.lock` 准备 Python 3.12 与依赖 |
| ffmpeg | `brew install ffmpeg` |
| API Key | 首次打开剪辑台后，在左下角「⚙ 设置 · API Key」里填（存本机钥匙串） |
| pyJianYingDraft | 不用管：uv 环境里已装（锁定 0.3.1）；不在 uv 环境里运行时才自动装到 `~/.aicut/venv`（同样锁版本） |
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
