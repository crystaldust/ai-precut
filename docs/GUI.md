# 剪辑台（图形界面）

> 界面是**六步项目向导**：① 新建 → ② 分析 → ③ 看素材 → ④ 定标准 → ⑤ 看结果 → ⑥ 导出（设计见 [界面流程 v2](界面流程-v2.md)）。
> M13 已完成 ①–④ 和整个外壳；⑤ ⑥ 暂时沿用原来的分镜表和版本页面，随 M14 重做。

给剪辑师用的界面：**双击启动 → 一步一步点 → 出片**。不用碰 JSON、不用记命令。

---

## 一、剪辑师怎么用

**启动**：双击 `启动剪辑台.command`（或打开 App），浏览器会自动打开（地址一般是 `http://127.0.0.1:8765`）。
关掉那个黑色终端窗口，就是退出。

**第一次打开**：先全屏告知两条外发数据流——音轨（16kHz 单声道）→ 火山引擎转写，转写文字 → DeepSeek 分析；
原始视频和画面不出本机。点「我知道了，继续」后直接填两个 Key（只存本机钥匙串），都填好才进欢迎页。
之后在「更多 → 设置 · API Key」里改。

**界面外壳**

- 左边是**项目栏**：平时收成一条窄边（☰ + 项目首字），悬停或点 ☰ 浮出；点「固定」就一直展开（重启后也记得）。
  每个项目显示「名称 · 当前步骤」。
- 顶栏是**步骤条**：灰色 = 还没到（悬停会说先完成哪一步）；蓝色实底 = 当前；✓ = 已完成，可以回看；
  ⚠ 橙色 = 需要更新（比如改了偏好，要重新分析）。「更多」菜单里是项目设置、打开项目文件夹、清理缓存、
  设置 · API Key、快捷键、导出诊断包、关于。
- 有任务在跑时，顶栏出现**任务胶囊**（「正在分析 6/11 · 3 分钟」），点开看日志、取消。同一时间只跑一个任务；
  有任务时其它「开始」类按钮会置灰并说明原因。
- 底部是「← 上一步」「下一步：X →」。④ 的「下一步」就是闸门按钮「确认，生成分镜表」。

**六步**

1. **① 新建**：点「＋ 新建项目」，选素材文件，填项目名 / 片名 / 目标时长 / 风格预设；「剪辑偏好」（语气、观众、
   最多 3 句指定原话）可展开也可跳过。「创建并开始分析」后直接进入 ②。以后想改偏好或片名：「更多 → 项目设置」
   （改偏好会让 ② 变 ⚠，要重新分析；只改片名不影响任何步骤）。
2. **② 分析**：11 项进度（读取素材 → 生成浏览小样 → 抽音轨 → 云端转写 → … → 初步选段），每项有状态和耗时。
   大约 10–15 分钟，可以关掉窗口，回来会接着跑。失败会说明失败的步骤和原因，点「重试（从这一步接着跑）」，
   已完成的步骤秒过；也可以「导出诊断包」。这台 Mac 编码器不可用时会提示并给诊断包入口。完成后自动进入 ③。
3. **③ 看素材**：上面是 AI 的理解（一句话摘要、关键信息、说话人、按档位上色的分布条）；下面是片段列表（按时间 /
   按话题，7 个筛选：全部 / 待定 / 可用 / 废片 / 剪辑列表 / 不可用 / 未用），右边是播放器和**剪辑列表**面板。
   挑段节奏：**↓ 换段 → 空格听 → S 放入剪辑列表**。A 标可用、D 标废片、X 标不可用（进片时彻底排除，包括手动分镜表
   里对应的镜头）、Z 撤销。剪辑列表里的片段 100% 进片；合计超过目标时会提示建议改成多长。
   快捷键可在「更多 → 快捷键」里自定义（与已有键冲突会被拒绝，可「恢复默认」；记在本机，所有项目通用）。
   标记之后 ⑤ 会变 ⚠「素材标记改过了」，不会自动重新选段。
4. **④ 定标准**（闸门）：左边小目录显示三块的完成情况，三块都不强制：
   - **分析对不对**（可选）：摘要 + 话题 / 关键信息 / 说话人。话题可以改名（只改显示名）；展开话题可以改某段的档位。
   - **裁决待定**：一次一段，看原文、依据、听一下，**A 可用 / D 废片**，也可以「先跳过」。
     「剩下的按 AI 建议」= 剩下的待定先不进片，**不会替你标可用或废片**，之后仍可在 ③ 改。
   - **决策问题**：3–5 题，每个选项下一行「选了会怎样」；点选即自动保存；可以「重新出题」；兜底模板出的题会标明。
   点底部「确认，生成分镜表」：保存答案并重新选段，完成后自动进入 ⑤。如果还有待定没裁完，会先问
   「还有 N 段待定，按 AI 建议处理？」，不会拦住你。改版前就出过片的旧项目，④ 顶部有一行提示，可以直接去 ⑤ ⑥。
5. **⑤ 看结果**（暂住）：分镜表可以改字幕、调顺序、删镜头、设入出点、试听；「改目标时长」；顶部 ⚠ 横幅可以「重新选段」。
6. **⑥ 导出**（暂住）：「生成新版本」导出到 Mac 剪映，「生成 Windows 剪映包」完成后「在访达中显示」，把
   `片名_vN_Windows.zip` 拷到 Windows 解压后双击 `INSTALL.bat`。含「不可用」片段的旧版本不能导出 Windows 包。

> 每次生成都是新版本（v1、v2、v3…），不会覆盖上一版。剪映里的草稿名是 `片名_v3`。

**常见操作对照**

| 想做的事 | 在哪点 |
|---|---|
| 改偏好 / 片名 / 预设 | 更多 → 项目设置 |
| 把一段放进片子 | ③ 选中后按 S（剪辑列表） |
| 这段绝对不要 / 涉及隐私 | ③ 选中后按 X（不可用） |
| 一次裁完待定 | ④ 裁决待定（A / D） |
| 换一句字幕 | ⑤ 分镜表 → 直接改那个输入框（自动保存） |
| 镜头长一点/短一点 | ⑤ 分镜表 → 选中 → 小播放器定位 → 设为入点/出点 |
| 删镜头 / 调顺序 / 加空镜 | ⑤ 分镜表 → ✕ / ↑ ↓ / ＋空镜 |
| 重出一版 | ⑥ 生成新版本（版本号自动 +1） |
| 出了问题要发给开发 | 更多 → 导出诊断包 |

---

## 二、开发者怎么维护

### 架构（三层，别搞混）

```
gui/static/index.html   界面（原生 JS，无框架无构建；一个页面、一个窗口，六步都在 #stage 里切换）
        ↓ fetch
gui/server.py           本地服务（127.0.0.1，只做转发和文件服务）；项目内容类接口在 gui/project_routes.py，
                        步骤状态 gui/wizard.py，分析进度 gui/analysis.py，界面偏好 gui/prefs.py，
                        任务子进程 gui/jobs.py，Key/告知 gui/settings.py
        ↓ subprocess
aicut.py                业务入口（和命令行完全同一套逻辑）
        ↓
pipeline/*.py           切、渲染、草稿生成、转写整理、废片检测
```

**原则：GUI 不实现业务逻辑。** 任何流程改动都改 `aicut.py`，GUI 只负责按钮和展示。这样命令行和界面永远一致。

### 加一个功能的标准路径

1. `aicut.py` 加子命令，本地跑通；
2. `gui/server.py` 加一个 `/api/xxx`，内部 `subprocess` 调它（异步任务用 `gui/jobs.py` 的 `start_job`，并在 `JOB_COMMANDS` 登记）；
3. 在对应步骤的 `gui/static/step-*.js` 加按钮 + 调接口（步骤状态由 `gui/wizard.py` 的 `derive()` 统一推导，前端不自己推）。

### 接口一览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/projects` | 项目列表（含每项的「当前步骤」）+ `stale_job`（上次退出时留下、仍在跑的任务，顶部提示条显示） |
| GET | `/api/presets` | 预设列表 |
| GET | `/api/state?project=` | 项目全量状态：阶段 / 版本 / 分镜 / 警告，加 `wizard`（六步状态 `steps` + `next` + `legacy`）和 `busy`（全局正在跑的任务） |
| GET | `/api/analysis?project=` | ② 的人话进度：11 项 `{label, status, seconds}`、`done/total`、`failed`、`notice`；重新分析时只显示要重跑的部分 |
| GET | `/api/browse?project=` | ③ 的数据：摘要、`segments`（含 `must_keep` / `unusable` / `inCut`）、`speakers`、`clip_list` |
| GET | `/api/confirm?project=` | ④ 的数据：`questions`、`answers`、`pending`（待定段的 id 和起止，按时间）、`segments`（精简分段，文字最多 400 字）、`topics`（显示名 + 原名 + 段数）、`speakers`；还没有决策问题 → 404，分析结果不完整 → 409 |
| GET | `/api/prefs` | 界面偏好（快捷键、项目栏是否固定），存 `~/.config/ai-cut/ui_prefs.json`，所有项目通用 |
| GET | `/api/job/<id>` | 任务进度（轮询，含日志）：`{status: running/done/failed/cancelled, log, exit, task, project}` |
| GET | `/api/config` | 设置页：是否已确认数据外发说明 + 两种 Key 的状态（只给掩码） |
| POST | `/api/new` | 新建项目（可带 `calibration` 剪辑偏好，创建后直接开始分析） |
| POST | `/api/project/settings` | 项目设置：片名 / 预设（白名单）/ 剪辑偏好；响应带最新 `wizard`（改偏好会让 ② 变 ⚠） |
| POST | `/api/pick` | 弹 macOS 选文件对话框，返回路径（浏览器拿不到本地路径，必须走这里） |
| POST | `/api/shots?project=` | 保存分镜表 |
| POST | `/api/browse/must` | S：放入 / 移出剪辑列表 `{project, id, must}`；与「不可用」互斥，响应带 `cleared`、`segment`、`clip_list`、`wizard` |
| POST | `/api/browse/level` | A / D：人工档位 `{project, id, level}`；`level: null` = 撤销人工档位；响应同上 |
| POST | `/api/browse/unusable` | X：标 / 取消不可用；标记时会把手动分镜表里对应镜头移除（`removed_shots`，撤销时可 `restore_shots` 放回） |
| POST | `/api/topics/rename` | 话题改名 `{project, name, display}`：只改显示名，选段 / 答案仍按原名匹配；`display` 为空 = 恢复原名；重名 / 超长 → 400 |
| POST | `/api/confirm/answers` | ④ 保存答案 `{project, answers, confirmed?}`：不带 `confirmed` = 草稿（不动确认状态、不起任务）；`confirmed:true` 保存并起「重新选段」任务（`job_id`，没能起来时 `job_error`）；响应带 `wizard` |
| POST | `/api/prefs` | 改界面偏好；快捷键冲突 / 非法键位 → 400 并说明 |
| POST | `/api/prefs/reset` | 恢复默认快捷键 `{what:'shortcuts'}` |
| POST | `/api/job` | 起任务：`{project, task:'prepare'|'build'|'select'|'export'|'questions', version, target}`；已有任务在跑 → 409 `{job_id}`；分析 / 重新出题缺告知 / 缺 Key → 409 `{need:'consent'|'keys', missing}`，编码器不可用等 → `need:'encoder'` |
| GET | `/api/cache?project=` | 「清理缓存」弹窗：可清理的项 `{items:[{label,path,bytes}], total}` |
| POST | `/api/cache/clean` | 清理缓存 `{project}` → `{freed}`；这个项目有任务在跑 → 409 |
| POST | `/api/job/<id>/cancel` | 取消任务（连同它拉起的 ffmpeg 一起停） |
| POST | `/api/config/consent` | 记录「已阅读数据外发说明」（存 `~/.config/ai-cut/consent.json`，不进项目） |
| POST | `/api/config/key` | 保存 Key：`{provider:'mediakit'|'deepseek', value}`，存本机钥匙串，响应只含掩码 |
| POST | `/api/config/key/delete` | 清除 Key：`{provider}` |
| POST | `/api/open` | 在访达打开项目 / 打开剪映 / `{target:'export', version}` 在访达中选中这一版的 Windows 包 |
| GET | `/media/<project>/proxy` | 浏览小样（支持 Range，能拖进度条） |
| GET | `/media/<project>/preview/v3` | 某一版的预览片 |

### 安全模型（单用户本机）

- 服务只监听 `127.0.0.1`，校验 `Host` / `Origin`，写接口要求 `application/json`。这挡住的是**别的网站**
  （浏览器里的跨站请求、DNS 重绑定）。
- **页面里没有任何凭证**（KI-88）。桌面壳 / 「启动剪辑台」打开的是一次性入口 `/?nonce=<随机串>`（5 分钟内有效、
  只能用一次，只存在服务进程内存里）；服务端兑换后下发会话 cookie `aicut_session_<端口>`
  （`HttpOnly; SameSite=Strict; Path=/`，每次启动随机、不落盘）并跳回去掉 nonce 的地址。之后页面、`/api/*`、
  `/media/*`（`<video>` 播放）都只认这个 cookie；`/static/*.js` 不含秘密，照常公开。M13 起只有一个窗口
  （没有子窗口）。没有有效 nonce / cookie 的页面请求只得到 403「请从剪辑台 App 打开」。
- 因此**同一台 Mac 上的其他用户或进程** `GET /` 拿不到任何凭证，也调不动接口。nonce 不出现在进程参数里：
  App 内由 pywebview 直接加载；浏览器模式经 `osascript` 的标准输入传给默认浏览器。
- 桌面壳用 `webview.start(private_mode=False)`；会话 cookie 本身不写盘，每次启动值都不同。
- **残余风险（KI-90）**：浏览器模式下 cookie 不按端口隔离。若本机另一用户在 `127.0.0.1` 的其他端口起服务并诱导
  剪辑师用**同一浏览器**访问，对方能收到这个 cookie。App（WKWebView 只加载剪辑台自己的页面）不受影响；多人
  共用的电脑请用 App，不要用浏览器模式。
- 浏览器模式：服务重启后旧标签页的请求会被拒（「页面已过期：请关掉这个页面，从剪辑台重新打开」）；
  不带 `--open` 启动时，终端会打印一条一次性入口链接。
- 页面 CSP 只允许同源脚本（`script-src 'self'`）；静态文件只发 `gui/static_files.py` 白名单里的。

### 界面改哪里

主页只有一个 `index.html`，脚本按下面的顺序加载（`gui/static/` 里每个 `.js` 都 ≤ 400 行，`tests/test_static_pages.py` 守卫）：

| 文件 | 管什么 |
|---|---|
| `common.js` | 必须最先加载：`esc()` / `num()` 转义、同源 `fetch` 带 cookie、`data-act` 事件委托（`ACTIONS`） |
| `base.js` | 全局 `state`、`api()` / `postJson()`、`toast`、格式化、弹窗 |
| `jobs.js` | 任务：启动 / 轮询 / 取消 / 重试、顶栏任务胶囊、启动类按钮置灰 |
| `settings.js` | 首次使用的数据外发告知与 Key、设置页 |
| `support.js` | 关于 / 诊断包 / 清理缓存 / 打开文件夹 |
| `sidebar.js` | 项目栏（收起 / 浮出 / 固定） |
| `wizard.js` | 步骤条、横幅、底部导航、「更多」菜单（步骤名常量 `STEP_NAMES` 与服务端一致） |
| `shortcuts.js` | 键位解析 / 冲突检查 / 「快捷键」录制弹窗 / 全局按键分发（③ ④ 共用） |
| `cliplist.js` | ③ 的标记（S A D X Z）、撤销栈、剪辑列表面板 |
| `project-form.js` | ① 新建项目、项目设置 |
| `step-analyze.js` | ② 分析进度 |
| `step-browse.js` | ③ 看素材页面（摘要、分布条、列表、筛选、播放器） |
| `step-criteria.js` | ④ 页面骨架与加载、目录、决策问题（草稿自动保存）、闸门、档位修改 |
| `criteria-analysis.js` | ④「分析对不对」：话题改名、关键信息、说话人、逐段改档位 |
| `criteria-pending.js` | ④「裁决待定」：一次一段、A / D、先跳过、剩下的按 AI 建议、播放器 |
| `step-result.js` / `step-export.js` | ⑤ 分镜表 / ⑥ 导出（暂住，随 M14 重做） |
| `app.js` | 项目选择与状态刷新、步骤切换、分镜表保存队列、启动 |
| `main.js` | 最后加载，只调用 `boot()` |

- CSP 只允许同源脚本：**不要写 `onclick=` 之类的内联事件**，在元素上写 `data-act="动作名"`
  （输入框 `data-input`、下拉框 `data-change`），再在脚本末尾的 `ACTIONS` 里注册；动态文本进 HTML 前一律过
  `esc()` / `num()`（包括 AI 生成的问题和选项、服务端报错）；新增静态文件要加进 `gui/static_files.py`
  的白名单，否则服务端 404、打包也不带；
- 配色与布局：`app.css` 顶部 `:root` 的 CSS 变量；
- 文案：每个文件顶部的 `COPY_*` 常量；名词按 PRD §12，`tests/test_terms.py` 会拦住「必留」「待判断」「原片」等旧叫法；
- 步骤状态（锁定 / 可进 / 完成 / 需要更新）只在 `gui/wizard.py` 推导，前端只渲染；
- 不用 `localStorage`：要持久的偏好走 `/api/prefs`；
- 前端测试：`tests/fe_harness.py` 在 node vm 里加载这些脚本，`tests/fe_fixtures.py` / `fe_browse.py` / `fe_criteria.py` 是各步的测试数据。

### 部署到另一台 Mac

| 依赖 | 怎么装 |
|---|---|
| uv | 按 https://docs.astral.sh/uv/ 安装；双击 `启动剪辑台.command` 会用 uv 按 `uv.lock` 准备 Python 3.12 与依赖 |
| ffmpeg | `brew install ffmpeg` |
| API Key | 首次打开剪辑台后，在「更多 → 设置 · API Key」里填（存本机钥匙串） |
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
