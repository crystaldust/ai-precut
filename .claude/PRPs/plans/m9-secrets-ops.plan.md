# Plan: 里程碑 9 · 密钥与运维

## Summary
关闭 M9 范围内的 27 条 KI（KI-28..KI-37、KI-50..KI-55、KI-57、KI-61..KI-63、KI-65、KI-67..KI-72、KI-74、KI-75；KI-31 已在 `624e979` 修复）。
分五个阶段：先做两个纯结构拆分（KI-55、KI-54），给后面的新逻辑腾出行数；然后依次处理密钥与脱敏、持久化与媒体产物、运维（费用 / 磁盘 / 任务表 / 看门狗 / 启动脚本 / 版本号），最后是 HTTP 边界与前端（Range、静态白名单、保存顺序、子窗口、CSP）。
所有新逻辑放进 `pipeline/` 或 `gui/` 的新模块。`aicut.py` 和 `gui/server.py` 只做接线，结束时两个文件都要低于 800 行，并由测试守住。

## User Story
作为剪辑工作室的剪辑师（以及给他打包、维护 App 的开发者），
我希望 Key 不会通过文件权限、掩码、日志或失败记录泄露；LLM 费用有统计、有上限；磁盘、进程、任务表、启动脚本和版本号都可控；剪辑台的本地页面没有越权或乱序写入；
这样我能长期放心地用它处理真实素材，升级时也不会丢授权、丢编辑。

## Problem → Solution
**现状**
- Key 掩码会暴露大半个短 Key；从钥匙串读出的 Key 带换行；删除 Key 后旧版文件里的 Key 仍然生效；写凭证文件时会 chmod 共享目录。
- 第三方报错原文不经脱敏就进 `failed.json` 和任务日志。
- 每次「处理素材」都重新调 LLM，没有用量统计和预算上限。
- 没有磁盘预检和缓存清理；ffmpeg 卡住时任务永远 running。
- `.done` 标记不认素材是否换过；`.partial-*` 临时文件和成品放在同一目录；中断留下的旧 wav 会被认领。
- `project.json` 读改写没有锁，写盘没有 fsync。
- 任务表无限增长；看门狗依赖 `pgrep`；上次遗留的任务只在用户点按钮时才以 409 出现。
- `.command` 启动脚本不走 uv；`pyJianYingDraft` 安装不锁版本；`CFBundleVersion` 固定为 1，没有 CHANGELOG。
- HTTP 层：Range 解析错误；`prototype.html` 对外提供；CSP 依赖 `'unsafe-inline'`。
- 前端：切项目时旧响应会覆盖新数据，保存会乱序；在 pywebview 里 `window.open` 无效。
- 两个入口文件超过（或贴着）800 行。

**目标**
上面每一条都改为正确行为，并有回归测试钉住。

## Metadata
- **Complexity**: XL（约 45 个文件，新建约 16 个、修改约 29 个；22 个任务，分 5 个阶段，每个阶段可以单独提交）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 9「密钥与运维」
- **Estimated Files**: ~45
- **基线**：`uv run pytest` 987 passed

---

## 逐条现状核对（已对照当前代码重新定位）

| KI | 结论 | 当前位置 / 依据 |
|---|---|---|
| KI-28 | **部分仍在**。凭证文件以 0600 创建（`6f8ba02`）、钥匙串删除失败会抛 `SecretDeleteError`（M4），这两项已修。仍在的问题：① 每次写凭证都执行 `os.chmod(path.parent, 0700)`，当 `AI_CUT_CONFIG_DIR` 指向共享目录时会改掉该目录权限；② `delete()` 不处理旧版文件，删除后 `get()` 照样从 `~/.mediakit/api_key` 读出 Key | `pipeline/secrets.py:85-98`（第 89 行 chmod）、`:127-133`、`:172-190` |
| KI-29 | **部分过时**。mediakit-cli 已被 HTTP 客户端取代（GL-01），按 CLI 输出子串判断网络错误的逻辑已不存在，现在用类型化的 `CloudError(retryable)`（`pipeline/cloud.py:97-109, 238-269`）。仍在的问题：`record_failure` 只截断不脱敏（没有经过 `applog.redact`），且写盘不是原子的 | `pipeline/cloud.py:466-483` |
| KI-30 | **仍在**。后缀范围 `bytes=-500` 被解析成 0–500；起点越界时返回 206 和非法的 Content-Range，没有返回 416 | `gui/server.py:360-366` |
| KI-31 | **已修复** `624e979` | `gui/server.py:340-346, 619-626`（`BadRequest`、`schema.clean_shots`） |
| KI-32 | **仍在**。`understand_text.run` 即使上次的完整结果、输入都没变也会重跑（只有 partial 文件才走续跑）；`summarize.run` 每次都调用；没有用量记录和预算。`client.last_usage` 只留最后一次 | `pipeline/understand_text.py:298-336`、`pipeline/summarize.py:94-119`、`pipeline/llm.py:103,147`、`aicut.py:270-293, 370-381` |
| KI-33 | **部分已修**。「退出不停任务 / 孤儿 ffmpeg」已由 M4 修复（`gui/jobs.py:275-310` 的 `shutdown_all`、atexit，`app/main.py:43-47`，`pipeline/proc.py:194-210` 的看门狗）。仍在：没有磁盘空间预检，没有缓存清理 | `aicut.py:676-687`（prepare）、`:609-650`（build） |
| KI-34 | **仍在**。`.command` 直接用 `command -v python3`；开发模式 `pip install pyJianYingDraft` 不锁版本 | `启动剪辑台.command:5-13`、`aicut.py:127-141` |
| KI-35 | **仍在**。① `refresh()` 不校验返回的是不是当前项目；② `startJob('build')` 不 flush 防抖保存；③ 浏览页 `setLevel` / `toggleMust` 先改本地状态，不检查响应 | `gui/static/index.html:243-259, 426-441`、`gui/static/jobs.js:56-69`、`gui/static/browse.html:205-218` |
| KI-36 | **仍在**。已核实 pywebview cocoa 的 `createWebViewWithConfiguration` 只处理 `WKNavigationTypeLinkActivated`，`window.open` 属于 Other 类型，直接返回 nil、什么也不做 | `gui/static/index.html:610-617`；`.venv/.../webview/platforms/cocoa.py:261-269` |
| KI-37 | **仍在**。`CFBundleVersion: "1"`；没有 CHANGELOG；adhoc 签名（spec 只读 `CODESIGN_IDENTITY`）；中间产物没有 schema 版本 | `packaging/ai-cut.spec:77, 87-96` |
| KI-50 | **仍在**。`move` / `dup` / `del` / `sortShots` 调 `saveShots(true)` 不 await，可能同时有多个 POST 在路上 | `gui/static/index.html:456-476` |
| KI-51 | **仍在**。`/api/calibrate` 与 `aicut cmd_select` / `cmd_calibrate` 都对 `project.json` 读改写，不加锁；`write_json` 不 fsync，被强杀会留下 `.tmp` | `gui/server.py:641-654`、`aicut.py:403-427, 732-758`、`pipeline/schema.py:114-124` |
| KI-52 | **仍在**。`prototype.html` 被 gitignore（生成物），但仍在 `gui/static/` 下，由 `/static/` 对外提供，打包时也被 spec 整目录带走 | `gui/server.py:434-441`、`packaging/ai-cut.spec:33`、`prototype/make_prototype.py:337` |
| KI-53 | **仍在**。`PAGE_CSP` 含 `script-src 'unsafe-inline'`；页面里有 4 段内联脚本和约 80 处内联事件（index 41、browse 17、confirm 6、calibrate 4、jobs/settings/support 模板里 11） | `gui/server.py:59-63` |
| KI-54 | **仍在（性质变了）**。M4 已把文件从 834 行降到 789 行，但仍贴着上限，而本里程碑要新增路由，必须先拆 | `gui/server.py`（789 行） |
| KI-55 | **仍在**。931 行 | `aicut.py` |
| KI-57 | **仍在** | `gui/static/index.html:600-604` |
| KI-61 | **仍在**。`run_ffmpeg`、`_probe_duration`、`aicut._run_pipeline`、`aicut.probe_duration` / `run` 都没有设超时 | `pipeline/media_io.py:87-121`、`aicut.py:84-85, 118-124, 144-157` |
| KI-62 | **仍在**。标记里只记了 `{"size"}` | `pipeline/media_io.py:34-44, 59-66` |
| KI-63 | **仍在**。临时文件 `.{stem}.partial-xxxx{suffix}` 和成品在同一目录，pathlib 的 `glob("*.mp4")` 会匹配到点开头的文件；`_clear_stale_partials` 不区分写入者，会删掉别人的临时文件 | `pipeline/media_io.py:47-56` |
| KI-65 | **仍在**。无标记的 wav 只要 ffprobe 读得出正时长就会被认领 | `pipeline/media_io.py:124-137` |
| KI-67 | **仍在**。长度 >8 就显示前 4 后 4 | `pipeline/secrets.py:101-107` |
| KI-68 | **仍在**。`JOBS` 从不清理，每个任务的 `log` 也没有上限 | `gui/jobs.py:57, 152-177, 198-202` |
| KI-69 | **仍在**。判断空目录到 `mkdir` / `save` 之间有竞争窗口 | `aicut.py:167-209` |
| KI-70 | **仍在**。LLM 错误里的 `_api_error` 只截断不脱敏；任务日志 `JOBS[..]["log"]` 存的是原文。mediakit-cli 输出那一半已过时（GL-01） | `pipeline/llm.py:46-55, 128`、`gui/jobs.py:198-202` |
| KI-71 | **仍在**。只在启动时打印到 stderr（打包版看不到），界面不会主动提示 | `gui/server.py:727-734`、`app/main.py:42` |
| KI-72 | **仍在** | `pipeline/proc.py:169-191` |
| KI-74 | **仍在**。`get()` 和 `peek()` 从钥匙串、凭证文件读出的值都不 strip | `pipeline/secrets.py:119-126, 142-143` |
| KI-75 | **仍在**。只有过期或指纹不符时缓存才失效 | `pipeline/cloud.py:279-310, 323-346, 404-429` |

---

## UX Design

### Before
```
┌──────────────── 剪辑台（App） ─────────────────────────────┐
│ 点「浏览素材」/「剪辑偏好」→ 没有任何反应（window.open 无效）  │
│ 分镜表连点 ↑↓✕ → 刷新后顺序回退（并发保存乱序）               │
│ 改完字幕立刻点「生成成片」→ 用的是改之前的字幕                  │
│ 快速切项目 → A 项目的数据显示在 B 项目名下                     │
│ 上次遗留的任务还在跑 → 什么提示都没有，点按钮才弹 409          │
│ 磁盘快满 → 跑到一半 ffmpeg 报错；卡住的 ffmpeg → 永远「处理中」 │
│ 每次「重新处理」→ 又付一遍 LLM 费用，界面看不到用了多少         │
└────────────────────────────────────────────────────────────┘
```

### After
```
┌──────────────── 剪辑台（App） ─────────────────────────────┐
│ 「浏览素材」/「剪辑偏好」→ App 内新开一个窗口                  │
│ 分镜表操作 → 保存按顺序逐个发出，生成成片前先把未保存的改动存盘  │
│ 快速切项目 → 只显示最后选中的那个项目                          │
│ 顶部提示条：「上次退出时留下的任务还在后台运行…」               │
│ 处理素材 / 生成成片 → 先查磁盘空间，不够就在开始前说明          │
│ ffmpeg 超时 → 任务失败，日志里写明「超过 N 分钟没有完成」       │
│ 重新处理 → 输入没变就沿用上次的 LLM 结果；项目信息行显示已用量  │
│ 「清理缓存」→ 确认弹窗列出可释放的空间                          │
└────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 浏览素材 / 剪辑偏好按钮 | pywebview 中无效 | `POST /api/window` 在 App 内开新窗口；浏览器模式退回 `window.open` | KI-36，需用户决策 D8 |
| 分镜表 ↑↓⧉✕ / 排序 | 并发发出多个 POST | 单通道串行保存，始终发送最新快照 | KI-50 |
| 生成成片 | 不等待防抖保存 | 先 `flushSave()` 再起任务 | KI-35 |
| 切项目 | 旧响应覆盖新项目 | 请求带序号，过期的响应丢弃 | KI-35 |
| 浏览页 A/D/S 改档 | 失败也显示成功 | 失败时回滚本地状态并显示错误 | KI-35 |
| 新建项目后 | 残留的 hash 导航抢着切项目 | 只执行 `selectProject(name)` | KI-57 |
| 打开剪辑台 | 遗留任务不提示 | `/api/projects` 返回 `stale_job`，顶部显示提示条 | KI-71 |
| 项目操作栏 | — | 新增「清理缓存」按钮 + 确认弹窗 | KI-33，需用户决策 D4 |
| 项目信息行 | — | 「LLM 已用 12.3 万 tokens」 | KI-32 |
| 设置 · Key 掩码 | `AKLT****9f2a`（长度 >8 就显示 8 位） | 按长度分档显示 | KI-67，D1 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/secrets.py` | 1-213 | KI-28/67/74 都在这里 |
| P0 | `pipeline/cloud.py` | 79-110, 238-346, 404-483 | KI-29/70/75；`_redact`、上传缓存、`record_failure` |
| P0 | `pipeline/applog.py` | 33-120 | `register_secret` / `redact` / `_PATTERNS`，脱敏要统一用它 |
| P0 | `pipeline/media_io.py` | 1-137 | KI-61/62/63/65 |
| P0 | `pipeline/schema.py` | 114-124, 225-229 | KI-51 `write_json` / `save` |
| P0 | `gui/server.py` | 76-240, 349-402, 422-560, 727-789 | KI-30/52/53/54/71 |
| P0 | `gui/jobs.py` | 54-232, 313-360 | KI-68/70/71 |
| P0 | `aicut.py` | 84-210, 229-427, 491-687, 796-931 | KI-32/33/34/51/55/61/62/69 |
| P0 | `tests/conftest.py` | 1-150 | 自动隔离夹具、`gui_server`、`call`、`make_project` |
| P1 | `gui/static/index.html` | 175-628 | KI-35/36/50/53/57 |
| P1 | `gui/static/jobs.js`、`settings.js`、`support.js`、`common.js` | 全部 | KI-53 事件委托；`support.js:18-19` 用 `[onclick="exportDiag()"]` 查按钮 |
| P1 | `gui/static/browse.html`、`confirm.html`、`calibrate.html` | `<script>` 段 | KI-35/53 |
| P1 | `pipeline/proc.py` | 168-210 | KI-72 |
| P1 | `pipeline/understand_text.py` | 244-336；`pipeline/summarize.py:94-119`；`pipeline/llm.py:81-153` | KI-32 |
| P1 | `packaging/ai-cut.spec`、`packaging/build_app.sh`、`启动剪辑台.command`、`pyproject.toml` | 全部 | KI-34/37/52 |
| P2 | `tests/test_cloud.py:1-100`、`tests/test_media_io.py`、`tests/test_server_jobs.py:1-66`、`tests/test_frontend_jobs.py:1-80`、`tests/test_frontend_js.py:1-50`、`tests/test_static_pages.py:1-60`、`tests/test_m5_review2.py:1-70` | — | 测试写法 |
| P2 | `gui/support.py`、`gui/settings.py` | 全部 | 「路由模块返回 (状态码, JSON)」的拆分范式 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| HTTP Range | RFC 9110 §14.1.2、§15.5.17 | `bytes=-N` 表示最后 N 字节；起点 ≥ 文件大小时返回 416，并带 `Content-Range: bytes */<size>`；终点越界时截到 size-1 |
| pywebview 运行时开窗 | 已安装版本源码 `webview/__init__.py`、`platforms/cocoa.py:261-269` | `window.open` 被吞；`webview.create_window()` 可以在 `start()` 之后从任意线程调用 |
| `fcntl.flock` | Python 文档 | 跨进程咨询锁，进程退出时自动释放；锁要加在独立的 `.lock` 文件上（`os.replace` 会换掉 inode） |
| `subprocess.run(timeout=)` | Python 文档 | 超时会先 kill 子进程，再抛 `TimeoutExpired` |
| WAV 头 | RIFF 规范 | 偏移 4 处是 `RIFF size` = 文件大小 − 8；ffmpeg 先写占位值，trailer 时回填，所以中断留下的文件这里不匹配 |

KEY_INSIGHT: pywebview 注入的 JS（`evaluateJavaScript` / WKUserScript）不受页面 CSP 约束。
APPLIES_TO: Task 21（CSP 收紧）。
GOTCHA: 没有在本机验证过，列为人工验证项。去掉 `'unsafe-inline'` 后，在 App 里点一遍「选择素材」（pywebview 的 file dialog）和全部按钮。

---

## Patterns to Mirror

### NAMING_CONVENTION（文案常量 + 小写函数 + 模块级常量）
```python
# SOURCE: gui/jobs.py:29-52
JOB_COMMANDS = {"prepare": ["prepare"], "build": ["build"], "select": ["select"],
                "export": ["export"]}
MAX_ACTIVE_JOBS = 1          # 重任务全局串行：ffmpeg / ASR 吃满资源，也避免重复计费
CANCEL_GRACE_S = 5.0         # SIGTERM 后等这么久仍未退出就 SIGKILL
...
JOB_CONFLICT_MSG = "已有任务在运行：{project} · {task}。等它结束，或先取消它"
```

### ERROR_HANDLING（类型化异常 + 中文消息 + 路由翻译成状态码）
```python
# SOURCE: pipeline/cloud.py:59-72
class CloudError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, terminal: bool = False,
                 status: int | None = None) -> None:
```
```python
# SOURCE: gui/server.py:404-420
        except JobConflict as e:  # 含 StaleJob（job_id 为 None：上次留下的进程，界面无法接管）
            return self._json({"error": str(e), "job_id": e.job_id, "task": e.task,
                               "project": e.project}, 409)
        except settings.PrepareBlocked as e:
            return self._json({"error": str(e), "need": e.need, "missing": e.missing}, 409)
        except (ValueError, FileNotFoundError) as e:
            return self._json({"error": str(e)}, 400)
```
CLI 一律 `die(msg)`（`aicut.py:49-52`）：先记 `LOG.error`，再打印 `[x] …`，退出码 1。

### LOGGING_PATTERN
```python
# SOURCE: gui/jobs.py:54-56, 146-149
LOG = applog.get("job")  # app.log 只记任务要点（起止、退出码、行数、错误行），不记普通输出（GL-19）
LOGGED_PREFIXES = ("[错误]", "[x]", "[!]", "Traceback")
def _log_line(job_id: str, line: str) -> None:
    text = line.strip()
    if text.startswith(LOGGED_PREFIXES):
        LOG.info("[%s] %s", job_id, applog.strip_paths(text)[:LOGGED_LINE_MAX])
```
脱敏统一用：
```python
# SOURCE: pipeline/applog.py:72-100
def register_secret(value: str | None) -> None:
    if value and len(value) >= MIN_SECRET_LEN:
        with _LOCK:
            _SECRETS.add(value)
...
def redact(text: str) -> str:
    with _LOCK:
        known = sorted(_SECRETS, key=len, reverse=True)
    for value in known:
        text = text.replace(value, secrets.mask(value))
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
```

### REPOSITORY_PATTERN（原子写盘：唯一临时名 → `os.replace`）
```python
# SOURCE: pipeline/schema.py:114-124
def write_json(path: Path, obj: Any, *, indent: int | None = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
```

### SERVICE_PATTERN（路由模块：`handle_get` / `handle_post` 返回 (状态码, JSON) 或 None，项目解析由 server 传入）
```python
# SOURCE: gui/support.py:76-82
def handle_get(path: str) -> tuple[int, dict] | None:
    return (200, about_payload()) if path == "/api/about" else None

def handle_post(path: str, body: dict,
                resolve: Callable[[str], Path]) -> tuple[int, dict] | None:
    return export_diagnostics(body, resolve) if path == "/api/diagnostics" else None
```
```python
# SOURCE: gui/server.py:564-567
        if (hit := settings.handle_post(p, body)) is not None:
            return self._json(hit[1], hit[0])
        if (hit := support.handle_post(p, body, existing_project)) is not None:
            return self._json(hit[1], hit[0])
```

### TEST_STRUCTURE
```python
# SOURCE: tests/conftest.py:76-92（gui_server：PROJECTS 指向 tmp，随机端口）
@pytest.fixture
def gui_server(tmp_path, monkeypatch):
    from gui import jobs, server
    monkeypatch.setattr(server, "PROJECTS", tmp_path)
    _stop_jobs(jobs)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
```
```python
# SOURCE: tests/test_cloud.py:57-72（云端一律注入假 transport / uploader）
def make(routes, uploads=None, **kw):
    http = FakeHttp(routes)
    ...
    c = cloud.CloudClient(sleep=lambda _: None, transport=http.transport,
                          uploader=uploader, **kw)
```
```python
# SOURCE: tests/test_media_io.py:10-13, 91-95（假 runner）
class FakeProc:
    def __init__(self, code=0, err=""):
        self.returncode, self.stdout, self.stderr = code, "", err
def test_run_ffmpeg_raises_with_stderr_tail():
    def runner(args, **kw):
        return FakeProc(1, "No such file or directory")
```
前端测试有两种：`tests/test_frontend_jobs.py` 在 node vm 里加载 `common.js` 加被测 js 文件，打桩 `state` / `api` / `el()` 后执行；`tests/test_static_pages.py` 对源码做文本守卫。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/timeline.py` | CREATE | KI-55：从 aicut 搬出 `compose_timeline` / `clip_key` |
| `pipeline/cli_args.py` | CREATE | KI-55：argparse 构造器，handler 从 aicut 现取 |
| `pipeline/prompts.py` | CREATE | KI-55：`ask_target` / `ask_calibration` |
| `pipeline/brief.py` | CREATE | KI-55：`render_brief()` 只拼 markdown |
| `pipeline/config_cli.py` | CREATE | KI-55：`cmd_config` 的逻辑 |
| `gui/views.py` | CREATE | KI-54：`project_state` / `browse_payload` / `confirm_payload` / `jload` |
| `gui/media.py` | CREATE | KI-54 + KI-30：`parse_range` / `serve_file` |
| `gui/desktop.py` | CREATE | KI-36：窗口打开器注入点 + `/api/window` |
| `gui/static_files.py` | CREATE | KI-52：静态文件白名单常量（零依赖，server 与 spec 共用） |
| `gui/maintenance.py` | CREATE | KI-33/71：`/api/cache`、`/api/cache/clean` 路由，以及 `stale_job` 摘要 |
| `pipeline/usage.py` | CREATE | KI-32：用量账本、预算、计量客户端 |
| `pipeline/diskspace.py` | CREATE | KI-33：磁盘空间估算与预检 |
| `pipeline/cache.py` | CREATE | KI-33：可清理项与清理 |
| `packaging/version.py` | CREATE | KI-37：短版本号、构建号 |
| `CHANGELOG.md` | CREATE | KI-37 |
| `gui/static/index.js`、`browse.js`、`confirm.js`、`calibrate.js` | CREATE | KI-53：内联脚本外置 |
| `pipeline/secrets.py` | UPDATE | KI-28/67/74 |
| `pipeline/cloud.py` | UPDATE | KI-29/70/75 |
| `pipeline/llm.py` | UPDATE | KI-70（错误文本走 `applog.redact`） |
| `pipeline/schema.py` | UPDATE | KI-51/69：`update()` 加锁、fsync、清理陈旧 tmp、`create_json_exclusive()`、`ARTIFACT_SCHEMA` |
| `pipeline/media_io.py` | UPDATE | KI-61/62/63/65 |
| `pipeline/proc.py` | UPDATE | KI-72 |
| `pipeline/understand_text.py`、`pipeline/summarize.py` | UPDATE | KI-32 命中缓存时跳过；KI-37 写入 `artifact_schema` |
| `pipeline/classify.py`、`pipeline/select.py` | UPDATE | KI-37 写入 `artifact_schema`（只加一个字段） |
| `pipeline/understand_visual.py` | UPDATE | KI-61：subprocess 加 `timeout=` |
| `aicut.py` | UPDATE | 拆分 + 接线（预算、磁盘、clean、超时、指纹、互斥新建、锁） |
| `gui/server.py` | UPDATE | 拆分 + 静态白名单 + CSP + 新路由分发 |
| `gui/jobs.py` | UPDATE | KI-68/70 |
| `gui/settings.py` | UPDATE | KI-28：删除时提示旧版来源 |
| `app/main.py` | UPDATE | KI-36：注入窗口打开器 |
| `gui/static/index.html`、`browse.html`、`confirm.html`、`calibrate.html`、`jobs.js`、`settings.js`、`support.js`、`common.js` | UPDATE | KI-35/36/50/53/57/71 |
| `prototype/make_prototype.py`、`.gitignore` | UPDATE | KI-52：产物移出 `gui/static/` |
| `packaging/ai-cut.spec`、`packaging/build_app.sh`、`启动剪辑台.command` | UPDATE | KI-34/37/52 |
| `docs/PACKAGING.md`、`docs/GUI.md`、`README.md` | UPDATE | 记录新命令、版本号、签名说明 |
| tests（见各任务） | CREATE/UPDATE | TDD |

## NOT Building

- KI 登记册以外的任何功能。不改 `docs/known-issues.md`、`docs/go-live-blockers.md`、PRD 的状态，由编排方在提交后填写。
- 不做 Developer ID 签名和公证（PRD 已决定不做）。KI-37 只做构建号、CHANGELOG，以及「稳定签名身份」的说明和告警。
- 不迁移中间产物，只在产物里打 `artifact_schema` 版本号；读取方遇到缺这个字段的旧文件，当作版本 0 照常读。
- 不改选段 / 分档 / 字幕的逻辑（M6）；不改 render_preview 的转义和字体（M7）；不处理 junk_detect / understand_visual 的返回码（KI-19，M8）。M9 只给这两处加 `timeout=`。
- 不做费用的金额换算，只统计 tokens（D3）。
- KI-11 的切片缓存键（素材替换后切片是否失效）不在本次范围，KI-62 只处理 `asr.wav` 和 `proxy.mp4`。
- 不加并发任务、排队、远程更新。
- `style-src 'unsafe-inline'` 保留（D9）。

---

## Step-by-Step Tasks

> 每个任务先写失败的测试，确认 RED，再实现。每个阶段结束时跑一次 `uv run pytest`，全绿后才进下一阶段。
> 阶段之间可以单独提交（编排方决定）。

### 阶段 0 · 结构拆分（行为不变，KI-55 / KI-54）

#### Task 1: 拆 `aicut.py`（KI-55）
- **ACTION**：把纯函数和解析器搬进新模块，`aicut` 用 re-export 保留原名，现有打桩点不变。
- **IMPLEMENT**：
  - `pipeline/timeline.py`：搬 `aicut.py:491-494`（`clip_key`）和 `:535-584`（`compose_timeline`，其中的 `import re` 提到模块顶部）。依赖 `build_documentary.card_entries` / `CARD_SIZE`。
  - `pipeline/prompts.py`：搬 `aicut.py:67`（`TARGET_PROMPT`）、`:699-729`（`ask_target`、`ask_calibration`）。
  - `pipeline/brief.py`：`render_brief(c: dict, preset: dict, segs: list, junk: list) -> str`，取自 `aicut.py:470-484`。`cmd_brief` 只负责读文件、调用、写盘。
  - `pipeline/config_cli.py`：`run(args, *, ok, info, die)`，取自 `aicut.py:761-793`，`cmd_config` 一行转发。输出函数通过参数注入，这样不 import aicut，也没有循环依赖。
  - `pipeline/cli_args.py`：`build_parser(handlers: dict[str, Callable]) -> argparse.ArgumentParser`，取自 `aicut.py:853-922`，`set_defaults(fn=handlers["new"])` 等。`aicut.main(argv)` 改为：
    ```python
    def main(argv=None):
        handlers = {n[4:]: f for n, f in globals().items() if n.startswith("cmd_")}
        args = cli_args.build_parser(handlers).parse_args(argv)
        args.fn(args)
    ```
    handler 每次调用时从 `globals()` 现取，所以 `monkeypatch.setattr(aicut, "cmd_select", …)` 依然有效。
  - `aicut.py` 顶部：`from pipeline.timeline import clip_key, compose_timeline  # noqa: F401 - 测试按 aicut.<名> 打桩`，`prompts` 同样处理。
- **MIRROR**：`gui/server.py:36-38`（`from gui.jobs import (...)  # noqa: E402,F401 - 路由与测试都按 server.<名字> 引用`）。
- **IMPORTS**：`from pipeline import brief, cli_args, config_cli` 等。
- **GOTCHA**：
  - `tests/test_aicut_*` 有 61 处 `monkeypatch.setattr(aicut, …)`，其中 `compose_timeline`、`ask_target`、`ask_calibration`、`ensure_clips`、`_run_pipeline`、`run`、`PROJECTS`、`PRESETS` 必须保持「由 aicut 内部按全局名查找」。`cmd_build` 和 `cmd_new` 要通过 aicut 的全局名调用。
  - `cmd_*` 留在 aicut（它们读 `aicut.PROJECTS`）。
  - 新模块要加进 `packaging/ai-cut.spec` 的 `hidden`。
- **VALIDATE**：先写 `tests/test_structure.py::test_entry_files_under_soft_ceiling`（`aicut.py` ≤ 800 行，`gui/server.py` ≤ 650 行，RED）和 `test_new_pipeline_modules_in_spec_hiddenimports`（扫描 `pipeline/*.py`、`gui/*.py`，确认 spec 里都有，RED）。拆完后 987 个测试原样全绿，`aicut.py` ≈ 740 行。

#### Task 2: 拆 `gui/server.py`（KI-54，同时为 KI-30 准备）
- **ACTION**：只搬与路由无关的代码；路由仍在 server 里，并通过 server 的全局名调用。
- **IMPLEMENT**：
  - `gui/views.py`：`jload`、`project_state(pdir, name)`、`browse_payload(pdir, name)`、`confirm_payload(pdir)`，取自 `server.py:77-81, 119-238`。依赖 `media_io / notices / review / schema / select / jobs`。
  - `server.py` 保留薄包装（测试会 `monkeypatch.setattr(server, "project_state", boom)`）：
    ```python
    def project_state(name: str) -> dict:
        return views.project_state(project_path(name), name)
    ```
    `browse_payload`、`confirm_payload` 同样处理；`jload = views.jload`。
  - `gui/media.py`：`serve_file(handler, path: Path, root: Path)`，取自 `server.py:349-401`，`Handler._serve_media` 改成一行转发。Range 解析在 Task 18 修。
- **MIRROR**：`gui/support.py` 的模块头部说明与 `LOG = applog.get("gui")`。
- **GOTCHA**：`test_server_hardening.py:91` 打桩的是 `server.project_state`，路由必须调用 server 的这个名字，不能直接调 `views.project_state`。`gui_server` 只打桩 `server.PROJECTS`，所以 views 只能接收已经解析好的 `pdir`，自己不能读 PROJECTS。
- **VALIDATE**：Task 1 的行数守卫（server ≤ 650）转绿，全量测试全绿。

### 阶段 A · 密钥与脱敏（KI-67 / KI-74 / KI-28 / KI-29 / KI-70 / KI-75）

#### Task 3: 掩码分档 + 读出时去空白（KI-67、KI-74）
- **ACTION**：重写 `secrets.mask`；`get` / `peek` 对所有来源统一 strip。
- **IMPLEMENT**：
  ```python
  MASK_FULL_MIN = 24   # ≥24 位：前 4 + 后 4（最多暴露 1/3）
  MASK_TAIL_MIN = 16   # 16–23 位：只留后 4
  MASK_SHORT = "********"  # 更短：固定 8 个星号，连长度也不暴露
  def mask(value):
      if not value: return ""
      if len(value) >= MASK_FULL_MIN: return f"{value[:4]}****{value[-4:]}"
      if len(value) >= MASK_TAIL_MIN: return f"****{value[-4:]}"
      return MASK_SHORT
  def _clean(value): return value.strip() if isinstance(value, str) and value.strip() else None
  ```
  `get()` 第 119-126 行、`peek()` 第 142-143 行的返回值都改为过 `_clean()`。
- **MIRROR**：`secrets.py:101-107` 原有写法。
- **GOTCHA**：下面这些旧断言是按旧掩码写的，要同步改成新格式（这是规格变更，不是改测试凑绿）：`test_secrets.py:10-11`（18 位 → `****9f2a`，`short` → `********`）；`test_applog.py:57,86`、`test_cloud.py:165`（19 位 `AKLTsecretkey123456` → `****3456`）；`test_server_config.py:46`；`test_frontend_jobs.py:157-211` 的假数据不用改（只是展示用字符串）。`test_diagnostics.py:74` 的 `"AKLT****" in blob` 先按新实现跑：Key 若没登记会命中 `_PATTERNS` 里的 AKLT 规则，仍然成立；若失败，改成断言 Key 原文不出现。
- **VALIDATE**：新增 `test_secrets.py::test_mask_tiers`（12 / 16 / 23 / 24 / 48 位）、`test_get_strips_keychain_and_file_values`（假 keyring 返回 `"sk-x…\n"`；凭证文件里写 `" AKLT…\n"`；全是空白时返回 None）、`test_peek_strips`。

#### Task 4: 凭证目录不 chmod 共享目录；删除时屏蔽旧版文件（KI-28）
- **ACTION**：① 只在本程序新建配置目录时才设 0700；已存在的目录一律不 chmod。② `delete()` 之后，旧版文件不再被读取（D2）。
- **IMPLEMENT**：
  ```python
  def _ensure_dir(d: Path) -> None:
      try:
          d.mkdir(parents=True, mode=stat.S_IRWXU)   # 新建：一步到位 0700
      except FileExistsError:
          pass                                      # 已存在（可能是共享目录）：不改权限
  LEGACY_IGNORE_FILE = "legacy_ignored.json"        # 配置目录下：[provider, …]
  def _legacy_ignored() -> set[str]: ...            # 坏文件 → 空集
  def _legacy_value(provider) -> str | None:
      if provider in _legacy_ignored(): return None
      ...                                           # 原第 127-132 行
  ```
  `delete()` 末尾：若 `LEGACY_FILES.get(provider)` 存在，就把 provider 写进 ignore 文件（用 `schema.write_json`）。`get` / `peek` / `status` 都改走 `_legacy_value`。`set()` 成功后从 ignore 里移除该 provider（重新配置后恢复正常优先级）。
- **MIRROR**：`_write_file` 的错误处理；`secrets.py:35-36` `SecretDeleteError`。
- **GOTCHA**：`mkdir(mode=)` 受 umask 影响，但 0700 & ~umask 仍然只给 owner，可以接受。`parents=True` 时中间目录用默认权限，这是合理的（那些目录不归我们管）。
- **VALIDATE**：`test_secrets.py::test_existing_shared_dir_mode_untouched`（预先建 0755 目录 → `set` → 目录仍是 0755，文件是 0600）、`test_new_config_dir_is_0700`、`test_delete_also_hides_legacy_key`（legacy 有值 → `delete` → `get` 返回 None、`status.source == ""`，旧版文件本身还在）、`test_set_after_delete_restores_normal_priority`。

#### Task 5: 第三方错误文本统一脱敏；`failed.json` 原子写（KI-29、KI-70）
- **ACTION**：所有可能带第三方原文的出口都过 `applog.redact`。
- **IMPLEMENT**：
  - `cloud.record_failure`（`cloud.py:466-483`）：`error` 先 `applog.redact(...)`，再折叠空白、截断到 800 字；读旧文件时补上 `UnicodeDecodeError` 和「不是 list」两种情况（都当空列表）；写盘改用 `schema.write_json(path, items[-50:])`。
  - `cloud._redact`（`:79-84`）：在现有替换之后再过一遍 `applog.redact(text)`（覆盖已登记的另一个 Key，以及 sk- / Bearer 样式）。
  - `llm._api_error` 和第 128 行的 HTTP 错误消息：`applog.redact(msg)[:ERROR_SNIPPET]`；`default_transport` 第 78 行的网络错误同样处理。
  - `gui/jobs.py:198-202`：`JOBS[job_id]["log"].append(applog.redact(line.rstrip()))`。`register_known_secrets()` 已经在 `start_job` 开头调用过。
- **MIRROR**：`applog.redact`、`cloud._redact`。
- **GOTCHA**：`applog` import 了 `secrets`、`schema`，`cloud` / `llm` 已经 import `applog`，不会循环依赖。`redact` 每行都要加锁复制一次集合，开销可以接受。
- **VALIDATE**：
  - `test_cloud.py::test_record_failure_redacts_registered_secret_and_patterns`（登记一个 DeepSeek Key，error 里带它和 `sk-…`、`Bearer x` → 文件里都没有）、`test_record_failure_atomic_and_tolerates_bad_file`（旧文件是 `{}` 或非 UTF-8 → 不抛，结果是 list）。
  - `test_llm.py::test_http_error_message_is_redacted`（假 transport 返回 401，`{"error":{"message":"bad key sk-abcdefgh12345678"}}`）。
  - `test_server_jobs.py::test_job_log_lines_are_redacted`（`fake_command` 让子进程打印一个已登记的 Key → `/api/job/<id>` 的 log 里只有掩码）。

#### Task 6: 云端作废缓存的 file_id 时立即重传（KI-75）
- **ACTION**：提交时用的是缓存里的 file_id，而云端拒绝（不可重试、非鉴权）→ 删缓存、换新 client_token、重新上传、再提交一次；任务终态失败时也删上传缓存。
- **IMPLEMENT**：在 `submit_asr`（`cloud.py:349-370`）中：
  ```python
  cached = None if remote else self._cached_file_id(Path(audio), workdir)
  file_id = str(audio) if remote else (cached or self._upload(Path(audio), workdir))
  try:
      data = self._request("POST", SUBMIT_PATH, payload(file_id, client_token), ...)
  except CloudError as exc:
      if not cached or exc.retryable or exc.status in AUTH_STATUS:
          raise
      _forget_upload(workdir); print(UPLOAD_CACHE_STALE)
      file_id = self._upload(Path(audio), workdir)
      data = self._request("POST", SUBMIT_PATH, payload(file_id, uuid.uuid4().hex), ...)
  ```
  `_upload` 里原来的「续用缓存」分支挪到这里（`_upload` 只负责上传）。`transcribe` 的 `except` 分支：`exc.terminal` 时额外执行 `_forget_upload(workdir)`。
  新增常量：`UPLOAD_CACHE_STALE = "[·] 云端已不认上次上传的音轨，重新上传"`。
- **MIRROR**：`cloud.py:404-429` 的 transcribe 异常处理。
- **GOTCHA**：重传后的提交必须用新 client_token。用旧 token 的话，云端去重可能直接把上次失败的结果还回来（M5 H1 的语义）。同时 `transcribe` 外层的 `_submit_token` 文件要清掉：调用 `_clear_submit_token(workdir)`（submit_asr 需要 workdir，已有参数）。
- **VALIDATE**：`test_cloud.py::test_stale_cached_file_id_reuploads_once_with_fresh_token`（先写一份有效缓存；SUBMIT 依次返回 `(400, {"message":"file not found"})` 和 `ok_task()` → 上传 1 次，两次提交的 `client_token` 不同，`audio_url` 是新的 file_id）、`test_auth_error_with_cached_file_does_not_reupload`、`test_terminal_task_failure_forgets_upload_cache`；原 `test_upload_reused_within_ttl` 保持绿。

### 阶段 B · 持久化与媒体产物（KI-51 / KI-69 / KI-61 / KI-62 / KI-63 / KI-65）

#### Task 7: `write_json` fsync + 清理陈旧 tmp；`schema.update()` 跨进程锁（KI-51）
- **IMPLEMENT**（`pipeline/schema.py`）：
  ```python
  STALE_TMP_S = 600  # 超过这么久的同名临时文件视为被强杀留下的残片
  def write_json(path, obj, *, indent=2):
      ...
      with open(tmp, "w", encoding="utf-8") as f:
          f.write(json.dumps(...)); f.flush(); os.fsync(f.fileno())
      os.replace(tmp, path)
      _fsync_dir(path.parent)          # 目录项也落盘；失败（如某些网络盘）忽略
      _clear_stale_tmps(path)          # glob.escape(f".{path.name}.") + "*.tmp"，只删 mtime 早于 STALE_TMP_S 的
  @contextlib.contextmanager
  def locked(path):                    # fcntl.flock(LOCK_EX) 加在 <path>.lock 上（不能锁 path 本身：os.replace 会换 inode）
  def update(path, mutate) -> dict:    # with locked(path): cfg = load(path); new = mutate(dict(cfg)); save(path, new); return new
  ```
  调用方改为：
  - `aicut.cmd_select:424-425`：`schema.update(p, lambda c: {**c, "target_duration": new_target})`
  - `aicut.cmd_calibrate:745-757`：同上（reset 和保存两处）
  - `gui/server.py:651-652` `/api/calibrate`：`cfg = schema.update(pdir / "project.json", lambda c: {**c, "calibration": style.normalize(body.get("calibration") or {})})`
- **MIRROR**：`review.py:20, 55-75` 的进程内 `_LOCK` 读改写。
- **GOTCHA**：
  - `.lock` 文件留在项目目录里，诊断包和 cache 清理都不要碰它。
  - `/api/projects` 的 `glob("*/project.json")` 不受影响。
  - `_clear_stale_tmps` 不能删并发写者正在写的 tmp：tmp 名字唯一，且只删超过 600 秒的。
  - `test_write_json_concurrent_same_path` 断言没有残留 `.tmp`，仍然成立。
- **VALIDATE**：`test_schema.py::test_write_json_fsyncs_file`（monkeypatch `os.fsync` 记录调用）、`test_stale_tmp_from_killed_writer_is_cleaned`（预置 mtime=1 小时前的 `.project.json.<hex>.tmp`）、`test_fresh_foreign_tmp_is_kept`、`test_update_serializes_across_processes`（用 `multiprocessing` 起两个进程各执行 50 次 `update` 自增计数 → 最终 100；macOS 用 spawn，被测函数要放在模块顶层）、`test_server_calibrate_does_not_clobber_target`（在 `update` 的锁内模拟另一个写者，或直接断言 server 调的是 `schema.update`）。

#### Task 8: `cmd_new` 原子占位（KI-69）
- **IMPLEMENT**：`schema.create_json_exclusive(path, obj)`：先把内容写进唯一 tmp 并 fsync，再 `os.link(tmp, path)`（目标已存在时抛 `FileExistsError`），最后 `unlink(tmp)`。`aicut.cmd_new:200-207` 改为：
  ```python
  created = not pdir.exists()
  pdir.mkdir(parents=True, exist_ok=True)
  try:
      schema.create_json_exclusive(pdir / "project.json", schema.migrate(project)[0])
  except FileExistsError:
      die(f"项目已存在：{pdir}")
  except BaseException:
      if created: shutil.rmtree(pdir, ignore_errors=True)
      raise
  ```
- **GOTCHA**：die 的时候不能删目录（目录是别人刚建的）。所以 `FileExistsError` 必须写在 `BaseException` 之前，并且不进入 rmtree 分支。
- **VALIDATE**：`test_aicut_guards.py::test_cmd_new_loses_race_without_clobbering`（monkeypatch `schema.create_json_exclusive` 先写入别人的 project.json 再抛 `FileExistsError` → 退出码 1，对方文件内容不变，目录还在）、`test_schema.py::test_create_json_exclusive_refuses_existing`。

#### Task 9: ffmpeg / ffprobe 超时（KI-61）
- **IMPLEMENT**（`pipeline/media_io.py`）：
  ```python
  FFMPEG_TIMEOUT_S = 3600              # 未指定时的兜底
  FFMPEG_MIN_TIMEOUT_S = 600
  FFMPEG_TIMEOUT_PER_MEDIA_S = 1.0     # 每秒素材允许 1 秒（VT 硬编 540p 远快于实时）
  PROBE_TIMEOUT_S = 60
  FFMPEG_TIMEOUT_MSG = "ffmpeg 超过 {m} 分钟没有完成，已停止（素材可能损坏，或在不稳定的网络盘上）"
  def timeout_for(media_s: float) -> float: return max(FFMPEG_MIN_TIMEOUT_S, media_s * FFMPEG_TIMEOUT_PER_MEDIA_S)
  def run_ffmpeg(args, *, runner=subprocess.run, timeout=FFMPEG_TIMEOUT_S):
      try: r = runner([...], capture_output=True, ..., timeout=timeout)
      except subprocess.TimeoutExpired as exc: raise MediaError(FFMPEG_TIMEOUT_MSG.format(m=round(timeout/60))) from exc
  ```
  `ffmpeg_to(..., timeout=)` 透传；`_probe_duration` 加 `timeout=PROBE_TIMEOUT_S`，超时返回 0.0。
  aicut 侧：
  - `probe_duration` 和 `cmd_ingest` 的 `run(...)` 加 `timeout=media_io.PROBE_TIMEOUT_S`，超时就 die。
  - 抽音轨、代理（`:238, :331`）传 `timeout=media_io.timeout_for(素材时长)`，素材时长从 `materials.json` 读，读不到时用 `FFMPEG_TIMEOUT_S`。
  - 切片（`:513`）传 `timeout_for(镜头时长 × 10)`。
  - `_run_pipeline` 的 `subprocess.run` 加 `timeout=FFMPEG_TIMEOUT_S`，捕获 `TimeoutExpired` 后 die（覆盖 render_preview / junk_detect / format_transcript）。
  - `understand_visual.py:20,35,90` 的 subprocess 加 `timeout=media_io.FFMPEG_TIMEOUT_S`；`cmd_scenes` / `cmd_quality` 捕获 `subprocess.TimeoutExpired` 后 die。
- **GOTCHA**：所有测试里的假 runner 签名都是 `runner(args, **kw)`，多传一个 `timeout` 不会坏。`subprocess.run` 超时时会自己 kill 子进程，不留孤儿。
- **VALIDATE**：`test_media_io.py::test_run_ffmpeg_timeout_is_media_error`（runner 抛 `TimeoutExpired`）、`test_ffmpeg_to_passes_timeout`、`test_probe_timeout_returns_zero`；`test_aicut_build.py::test_run_pipeline_timeout_dies`。

#### Task 10: 完成标记绑定素材指纹（KI-62）
- **IMPLEMENT**：
  ```python
  def source_fingerprint(src) -> dict | None:   # {"path": str(resolve), "size", "mtime_ns"}；不可访问 → None
  def atomic_output(dst, *, source=None)        # 标记写 {"size": …, "source": fp}
  def is_complete(dst, *, source=None) -> bool:
      ...大小校验...
      if source is None: return True
      want = source_fingerprint(source)
      if want is None: return True              # 素材暂时不可访问（外接盘没插）：不判失效
      have = meta.get("source")
      if have is None: _write_marker(dst, source); return True   # D7：旧标记补写指纹
      return have == want
  def complete_or_adopt(dst, *, runner=..., source=None)   # 认领旧文件时一并写入指纹
  ```
  `ffmpeg_to(dst, args, *, source=None, ...)` 透传。接线：`aicut.py:235, 238, 262`（wav，`source=c["material"]`）、`:328, 331, 345, 358`（proxy），`gui/views.project_state` 里的 `asr.wav` / `proxy.mp4`（`source=cfg.get("material")`），以及 `cmd_status` 的 MEDIA 判断。
- **GOTCHA**：
  - `cmd_analyze` 原本不读 cfg，需要加一行 `c = cfg(pdir)`。
  - 指纹用 mtime_ns + size，不算内容哈希：素材可能有 10 GB 以上，算哈希太贵。代价是「原地改写、大小和 mtime 都不变」这种情况查不出来，可以接受。
  - `_write_marker` 的签名要加 `source` 参数。
- **VALIDATE**：`test_media_io.py::test_replaced_source_invalidates_marker`（写完后改素材内容 → `is_complete(source=…)` 为 False）、`test_unreachable_source_does_not_invalidate`、`test_legacy_marker_without_source_is_backfilled`、`test_adopted_legacy_file_records_source`；`test_aicut_build.py::test_transcribe_reextracts_wav_when_material_replaced`。

#### Task 11: 临时文件移到 `.aicut-partial/`，只清理死掉的写者留下的（KI-63）
- **IMPLEMENT**：
  ```python
  PARTIAL_DIR = ".aicut-partial"
  STALE_PARTIAL_S = 24 * 3600
  def _partial_path(dst):
      d = dst.parent / PARTIAL_DIR; d.mkdir(exist_ok=True)
      return d / f"{dst.stem}.{os.getpid()}.{uuid.uuid4().hex[:8]}{dst.suffix}"   # 保留扩展名：ffmpeg 靠它选封装
  def _clear_stale_partials(dst):
      pattern = f"{glob.escape(dst.stem)}.*{glob.escape(dst.suffix)}"
      for p in (dst.parent / PARTIAL_DIR).glob(pattern):
          pid = _pid_of(p)        # 解析中间那段；解析不了视为陈旧
          if pid is None or not _alive(pid) or _age(p) > STALE_PARTIAL_S: p.unlink(missing_ok=True)
  # atomic_output 的 finally：tmp.unlink 之后 rmdir 空的 PARTIAL_DIR（OSError 忽略）
  ```
  旧格式 `.{stem}.partial-*{suffix}` 也要顺手清理一次（兼容 M3 产物）。
- **GOTCHA**：
  - `os.replace` 跨子目录、同一文件系统，仍然是原子的。
  - 以下旧测试按新规格改写：`test_atomic_output_commits_and_marks` 里 `tmp.parent == dst.parent` 改为 `tmp.parent.name == PARTIAL_DIR`；`test_stale_partials_from_killed_run_are_cleaned` 改为预置 pid=999999 的新格式文件，再加一条旧格式文件的用例。
  - `test_interrupted_write_leaves_no_final_file` 断言 `tmp_path` 为空，依赖 rmdir 空目录这一步。
  - `_alive` 用 `os.kill(pid, 0)`：`PermissionError` 视为活着，`ProcessLookupError` 视为死了。
- **VALIDATE**：`test_media_io.py::test_partials_not_matched_by_media_glob`（写入过程中 `dst.parent.glob("*.mp4")` 为空）、`test_live_writer_partial_is_kept`（用当前进程 pid 命名 → 不删）、`test_dead_writer_partial_is_removed`、`test_legacy_partial_name_is_cleaned`。

#### Task 12: 旧 wav 认领前先校验 RIFF 头（KI-65）
- **IMPLEMENT**：
  ```python
  def wav_header_complete(path) -> bool:
      """RIFF/WAVE 且 RIFF size + 8 == 文件大小（允许 1 字节补齐）；ffmpeg 中断时这里是占位值。"""
  # complete_or_adopt：dst.suffix.lower() == ".wav" 且 not wav_header_complete(dst) → False（在 probe 之前）
  ```
- **GOTCHA**：RF64（文件大于 4 GB）的 RIFF size 是 0xFFFFFFFF。16 kHz 单声道 wav 每小时约 115 MB，用不到 RF64，所以 RF64 一律不认领，让它重新生成。
- **VALIDATE**：`test_media_io.py::test_truncated_wav_is_not_adopted`（用 `wave` 模块写一个完整 wav，再截掉末尾 → False，且不会调 probe）、`test_complete_wav_is_adopted`、`test_placeholder_riff_size_not_adopted`（0xFFFFFFFF）。

### 阶段 C · 运维（KI-32 / KI-33 / KI-68 / KI-71 / KI-72 / KI-34 / KI-37）

#### Task 13: LLM 结果复用 + 用量账本 + 预算（KI-32）
- **IMPLEMENT**：
  - `pipeline/understand_text.py`：
    - 加 `PROMPT_VERSION = 1`，并入 `_fingerprint`（提示词改了就失效）。
    - `run()` 开头：`out_path` 存在、`complete is True`、`input_hash == fp`、文件里没有 `failures` → 直接返回 `{**cached, "cached": True}`，不调用客户端。
    - 客户端改为延迟创建（命中缓存时连 Key 都不读）。
  - `pipeline/summarize.py`：结果里写 `input_hash`（topics + 要点 + style + model + `PROMPT_VERSION` 的 sha1）。命中条件：旧结果 `fallback is False`、hash 相同、没有 `error` 字段。兜底结果永远不复用，以免把兜底固化，这一点与 KI-22 一致。写盘改用 `schema.write_json`。
  - `pipeline/usage.py`：
    ```python
    USAGE_FILE = "llm_usage.json"     # work/ 下：{"total_tokens", "by_stage": {stage: {...}}, "calls"}
    BUDGET_ENV = "AI_CUT_LLM_BUDGET_TOKENS"
    DEFAULT_BUDGET_TOKENS = 3_000_000  # D3
    BUDGET_EXCEEDED = "本项目 LLM 用量已达上限（{used} / {budget} tokens）…设置 AI_CUT_LLM_BUDGET_TOKENS 调高，或设为 0 不限"
    class BudgetExceeded(LLMError)  # retryable=False
    def budget() -> int | None      # env 非法 → 默认；0 → None（不限）
    def load(workdir) -> dict       # 坏文件 → 空账本（不阻断）
    def record(workdir, stage, usage: dict) -> None  # 加锁（schema.locked）+ write_json
    class MeteredClient:            # 包住 DeepSeekClient：chat_json 前查预算，后记 last_usage
        def __init__(self, client, workdir, stage): ...
        model = property(lambda self: self._client.model)
    ```
  - `aicut.cmd_text` / `cmd_summary` / `cmd_questions`：`client = usage.MeteredClient(DeepSeekClient(), work, "text")` 后传入 `run(..., client=client)`。命中缓存时打印 `info("输入没变，沿用上次的标注结果（不重新计费）")`。`BudgetExceeded` 走现有的 `except LLMError → die`。`cmd_summary` / `cmd_questions` 也要捕获 `BudgetExceeded` 后 die（summarize 内部有 `except Exception` 兜底会把它吞掉，所以要在调用 run 之前先 `usage.check(work)`）。
  - 展示：`cmd_status` 末尾打印「LLM 用量：N tokens（上限 M）」；`gui/views.project_state` 增加 `"llm_usage": {"total_tokens", "budget"}`；`index.html` 的 meta 行追加「LLM 已用 X 万 tokens」（`num()` + `esc()`）。
- **MIRROR**：`understand_text._resumable`（`:268-276`）的判定写法；`schema.write_json`。
- **GOTCHA**：
  - 测试里的假客户端（`tests/test_understand_text.py` 的 FakeClient）没有 `last_usage`，`MeteredClient` 要用 `getattr(client, "last_usage", {}) or {}`。
  - 命中缓存时 `resumed=False`，`cmd_text` 的文案要兼容。
  - KI-22（questions 兜底被缓存）属于 M8，这里不碰 `questions.run` 的复用逻辑，只给它包上计量。
- **VALIDATE**：
  - `test_understand_text.py::test_complete_unchanged_input_is_not_reannotated`（第二次调用时客户端调用数为 0）、`test_prompt_version_change_invalidates_cache`。
  - `test_summarize.py::test_unchanged_summary_reused_but_fallback_never_reused`。
  - 新文件 `tests/test_usage.py`：记账累加、坏文件不阻断、超预算抛 `BudgetExceeded` 且不调用底层客户端、`0` 表示不限、env 非法时用默认值。
  - `test_aicut_must_keep.py::test_text_budget_exceeded_dies`；`test_server_media_state.py::test_state_reports_llm_usage`。

#### Task 14: 磁盘预检 + 缓存清理（KI-33）
- **IMPLEMENT**：
  - `pipeline/diskspace.py`：
    ```python
    MARGIN_BYTES = 1 * 1024**3            # D5
    WAV_BYTES_PER_S = 16000 * 2           # 16 kHz 单声道 s16
    def _bps(kind): return encode.<码率常量> / 8 + 音频码率 / 8   # proxy / clip / preview，取 encode.py 的命名常量
    def need_for_prepare(media_s) -> int; def need_for_build(shots_s) -> int
    def shortfall(path, need, *, usage=shutil.disk_usage) -> str | None   # 不足 → DISK_LOW.format(need=…, free=…, path=…)
    ```
    `aicut.cmd_prepare` 在 `encode.preflight()` 之后检查：素材时长先用 `probe_duration(material)` 取，取不到时按 0 估算，只检查 1 GB 余量。`cmd_build` 在 GL-25 检查之后、`ensure_clips` 之前，按镜头总时长检查。空间不够就 die。
  - `pipeline/cache.py`：
    ```python
    def items(pdir) -> list[dict]   # [{"label","path"(相对),"bytes"}]：work/clips/、各处 .aicut-partial/ 及旧格式 .partial-*、
                                    # work/audio/asr.wav(+.done)——仅当 transcript_raw.json 与 segments_audio.json 都在
    def clean(pdir) -> int          # 删除上述各项，返回释放的字节数；proxy / preview / output / *.json 一律不动（D4）
    ```
  - CLI：新子命令 `aicut clean <项目> [--dry-run]`，在 `cli_args` 里注册，`cmd_clean` 放 aicut，约 10 行。
  - GUI：`gui/maintenance.py`：`GET /api/cache?project=` 返回 `{items, total}`；`POST /api/cache/clean {project}`，若该项目有任务在跑（`jobs.active_job(project)`）返回 409，否则返回 `{freed}`。server 里只加两行分发：`maintenance.handle_get(p, q, existing_project)` 和 `handle_post`。
  - 前端：`index.html` 操作栏加「清理缓存」按钮 → 弹窗列出各项和总大小 →「清理」→ toast「已释放 X MB」。文案常量 `COPY_CACHE_*`。
- **GOTCHA**：
  - clean 删 `work/clips/` 时，`manifest.json` 一起删（manifest 在 clips 目录里）。
  - 删掉 asr.wav 后 `cmd_transcribe` 会重新抽音轨，但因为 `transcript_raw.json` 存在，不会重新 ASR；`readiness.needed_keys` 也不要求 mediakit Key。
  - 必须拒绝符号链接逃逸：只用 `pdir` 下的固定相对路径，`rglob` 时跳过符号链接（`is_symlink()`）。
- **VALIDATE**：新文件 `tests/test_diskspace.py`（注入假 `disk_usage`：够 / 不够 / 刚好）、`tests/test_cache.py`（列项、清理、保留 proxy 和 output、条件删 wav、符号链接不跟随）；`tests/test_server_maintenance.py`（GET 列表、POST 清理、任务运行中 409、非法项目 400、不存在 404、无 token 403）；`test_aicut_cli.py::test_prepare_dies_when_disk_low`（monkeypatch `diskspace.shortfall`）、`test_clean_dry_run_deletes_nothing`。

#### Task 15: 任务表清理 + 日志上限 + 遗留任务主动提示（KI-68、KI-71）
- **IMPLEMENT**（`gui/jobs.py`）：
  ```python
  MAX_FINISHED_JOBS = 20       # D13
  JOB_LOG_MAX_LINES = 5000
  JOB_LOG_TRIMMED = "…（前面省略 {n} 行，完整输出见日志文件）"
  def _prune_locked(): 按 started 排序，删掉超出 MAX_FINISHED_JOBS 的已结束任务（running 永不删）
  # start_job 登记前调用 _prune_locked()
  # _run_job 追加日志：超过上限时删掉最早的一批，只保留末尾 JOB_LOG_MAX_LINES 行，首行换成 JOB_LOG_TRIMMED，trimmed 计数累加
  def stale_job_view() -> dict | None:   # 给界面：{project, task(label), pid, message}
  ```
  `/api/projects` 的响应加 `"stale_job": jobs.stale_job_view()`（路由在 server 里，只多一个字段）。`index.html` 的 `loadProjects()` 拿到 `stale_job` 后用 warnbar 同款提示条（新元素 `#stalebar`，内容 `esc()`）显示 `message`。
- **GOTCHA**：
  - `stale_job()` 会跑 `ps`，`/api/projects` 只在页面加载和新建项目时调用，频率很低。
  - 日志裁剪必须在 `JOBS_LOCK` 内完成。
  - `job_view` 返回 `list(job["log"])`，不用改。
  - `_stop_jobs` 夹具会清空 `JOBS`，不受影响。
- **VALIDATE**：`test_server_jobs.py::test_finished_jobs_are_pruned_beyond_limit`（monkeypatch `MAX_FINISHED_JOBS=2`，跑 4 个短任务 → JOBS 里只剩 2 个，running 的不被删）、`test_job_log_is_capped_with_note`（`JOB_LOG_MAX_LINES=10`，子进程打印 30 行 → log 首行是省略说明，末行是 `[退出码]`）、`test_projects_endpoint_reports_stale_job`（复用 `_orphan` 辅助函数）；`test_static_pages.py::test_index_shows_stale_job_bar`。

#### Task 16: 看门狗不依赖 `pgrep`（KI-72）
- **IMPLEMENT**（`pipeline/proc.py`）：
  ```python
  _SELF_KILL = threading.Event()
  def _on_sigterm(signum, frame):
      if _SELF_KILL.is_set():          # 自己发给整组的 SIGTERM：主进程不退，等宽限期后统一 SIGKILL
          return
      signal.signal(signal.SIGTERM, signal.SIG_DFL); os.kill(os.getpid(), signal.SIGTERM)   # 其余情况保持默认语义（GUI 取消照常生效）
  def start_parent_watchdog():
      ...
      signal.signal(signal.SIGTERM, _on_sigterm)   # 在主线程（dispatch / aicut __main__）里安装
      ...
  def _kill_own_group():
      pgid = os.getpgrp()
      if pgid != os.getpid(): os._exit(1)
      _SELF_KILL.set()
      with contextlib.suppress(OSError): os.killpg(pgid, signal.SIGTERM)
      time.sleep(WATCHDOG_GRACE_S)
      os.killpg(pgid, signal.SIGKILL)
  ```
  删除 `_group_members`。
- **GOTCHA**：
  - `signal.signal` 只能在主线程调用。`start_parent_watchdog` 已有的两个调用点（`proc.dispatch`、`aicut.__main__`）都在主线程。安装时如果不在主线程（抛 `ValueError`），就退回只做 SIGKILL 整组，并记一条 warning。
  - `test_parent_watchdog_env_not_inherited_by_grandchildren` 在 pytest 主线程里调用，会真的装上处理函数，测试结束要还原：在测试里用 `monkeypatch.setattr(signal, "signal", …)` 记录调用。
- **VALIDATE**：`test_proc.py::test_parent_watchdog_kills_own_group_when_parent_dies` 保持绿（真实进程）；新增 `test_watchdog_does_not_need_pgrep`（子进程里把 PATH 设为空目录后，同一场景孙进程仍然被杀）、`test_sigterm_without_self_kill_keeps_default_behavior`（子进程装上处理函数后收到外部 SIGTERM → 退出码 -15）。

#### Task 17: 启动脚本走 uv；pyJianYingDraft 锁版本；构建号 / CHANGELOG / 中间产物版本（KI-34、KI-37）
- **IMPLEMENT**：
  - `启动剪辑台.command`：
    ```bash
    UV="$(command -v uv || true)"; [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
    if [ -z "$UV" ]; then echo "找不到 uv：请先安装 uv（https://docs.astral.sh/uv/）…"; read -r -p "按回车关闭…" _; exit 1; fi
    exec "$UV" run --python 3.12 python gui/server.py --open
    ```
  - `aicut.ensure_jy_python`（`:127-141`）：
    - 开发模式下，若当前解释器能 `importlib.util.find_spec("pyJianYingDraft")`（uv 环境里本来就装了），直接返回 `sys.executable`。
    - 否则走原来的 venv 路径，安装 `JY_PIN = "pyJianYingDraft==0.3.1"`（与 `uv.lock` 一致）。
    - venv 已存在时，用 `importlib.metadata` 核对版本，不一致就重装。
  - `packaging/version.py`：`short_version(root)` 读 `pyproject.toml`；`build_number(root, env=os.environ, run=subprocess.run)` 取 `AICUT_BUILD_NUMBER`，没有就用 `git rev-list --count HEAD`，两者都拿不到时抛 `RuntimeError`（构建失败，不能静默打成 1）。
  - `packaging/ai-cut.spec`：`CFBundleShortVersionString` 和 `CFBundleVersion` 都改为调用 `packaging/version.py`（spec 里 `sys.path.insert(0, str(ROOT))`）。
  - `packaging/build_app.sh`：未设 `CODESIGN_IDENTITY` 时打印 `[!] 未设置 CODESIGN_IDENTITY：adhoc 签名，升级后 macOS 会把它当新 App，需要重新授权钥匙串 / 文稿目录（见 docs/PACKAGING.md）`。
  - `CHANGELOG.md`：建立 0.1.0 条目，并在「升级须知」里写明 adhoc 签名下升级后要重新授权。`docs/PACKAGING.md` 增加「稳定签名身份（自签证书）」的手动步骤（D10）。
  - 中间产物版本：`schema.ARTIFACT_SCHEMA = 1`，`schema.stamp(obj) -> {**obj, "artifact_schema": ARTIFACT_SCHEMA}`。在以下写盘处加上：`understand_text.run`（`segments_text.json`）、`classify.run`（`segments_scored.json`）、`select.run`（`selection.json`）、`aicut.cmd_build`（`timeline.json`）。读取方不改，缺字段的旧文件照常读（NOT Building）。
- **GOTCHA**：
  - `packaging/` 目录名和 PyPI 上的 `packaging` 包同名。spec 在 PyInstaller 进程里运行，`import packaging.version` 会命中第三方包，所以要用 `importlib.util.spec_from_file_location` 按文件路径加载 `packaging/version.py`。测试同理，或者用 `runpy.run_path`。
  - timeline.json 会被 `to_jianying` / `render_preview` / `export_draft` 读取，多出一个顶层字段不影响（它们按键读）。实施时用 `grep -n "for k in tl\|tl.items()" pipeline/` 确认没有遍历顶层键的代码。
- **VALIDATE**：新文件 `tests/test_launcher.py`：
  - `.command` 用假 `uv` 真跑（`PATH=<stubs>`，假 uv 把参数写进文件）→ 参数是 `run --python 3.12 python gui/server.py --open`；PATH 里没有 uv、`HOME` 指向空目录时 → 退出码 1，并且有提示（stdin 用 `/dev/null`，保证 `read` 立即返回）。
  - `test_ensure_jy_python_prefers_current_env`、`test_jy_venv_install_is_pinned`（打桩 `aicut.run`，断言 `pyJianYingDraft==0.3.1`）。
  - `version.build_number` 的三种来源和失败情况。
  - spec 文本守卫：没有 `"CFBundleVersion": "1"`，并且调用了 version。
  - `CHANGELOG.md` 存在，且包含 pyproject 里的版本号。
  - `test_artifact_schema_stamped`（四个产物各一条）。

### 阶段 D · HTTP 边界与前端（KI-30 / KI-52 / KI-35 / KI-50 / KI-57 / KI-36 / KI-53）

#### Task 18: Range 解析修正（KI-30）
- **IMPLEMENT**（`gui/media.py`）：
  ```python
  def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
      """None=没有或无法理解（按 200 全量）；"unsatisfiable"=416；(start, end) 闭区间。只认单段 bytes=。"""
      # bytes=N-      → (N, size-1)；N>=size → 416
      # bytes=-N      → (max(0,size-N), size-1)；N==0 → 416
      # bytes=a-b     → a>b → None（RFC：语法无效时忽略 Range）；a>=size → 416；b 截到 size-1
      # 多段 / 非 bytes 单位 / 空 → None
  ```
  `serve_file`：返回 416 时带 `Content-Range: bytes */{size}` 和安全头，没有响应体；size 为 0 且带了 Range 时也返回 416。
- **VALIDATE**：`tests/test_server_media.py` 增加参数化用例：`bytes=-100`（最后 100 字节）、`bytes=990-`、`bytes=1000-`（416 + `bytes */1000`）、`bytes=5-2`（200 全量）、`bytes=0-99999`（截到 999）、`bytes=0-1,5-6`（200）、`items=0-1`（200）、`bytes=-0`（416）。另加 `test_parse_range_unit` 纯函数表驱动测试。

#### Task 19: 静态文件白名单；prototype 移出（KI-52）
- **IMPLEMENT**：
  - `gui/server.py`：`STATIC_FILES = frozenset({"index.html","browse.html","calibrate.html","confirm.html","common.js","jobs.js","settings.js","support.js","index.js","browse.js","confirm.js","calibrate.js"})`。`/static/<name>` 只认白名单里的单段文件名，其他一律 404。
  - `prototype/make_prototype.py:10-11, 337`：输出路径改为 `prototype/prototype.html`（用 `open` 直接打开本地文件）。`.gitignore` 第 10 行同步修改。
  - `packaging/ai-cut.spec`：`gui/static` 改为逐个列出 `STATIC_FILES` 的文件。spec 不能 import server，所以在 `gui/static_files.py` 里放这个常量（零依赖），server 和 spec 都从这里读。
- **GOTCHA**：本机 `gui/static/prototype.html` 还在（gitignored），实施时不要删用户文件。白名单生效后它自然就访问不到了。
- **VALIDATE**：`test_server_security.py::test_prototype_not_served`（在 STATIC 下放一个 prototype.html → 404）、`test_unlisted_static_file_404`、`test_every_script_referenced_by_pages_is_whitelisted`（解析各页面的 `<script src="/static/…">`，逐个请求 → 200）；`test_packaging.py::test_spec_ships_only_whitelisted_static`。

#### Task 20: 前端保存顺序、切项目竞态、浏览页回滚、createProject 残留（KI-35、KI-50、KI-57）
- **IMPLEMENT**（写进 Task 21 外置后的 `index.js`；如果按顺序先做本任务，就先改 index.html，再随 Task 21 一起搬走）：
  ```js
  // 单通道保存：同一时间只有一个 POST；进行中再请求就只标记 pending，结束后再发一次最新快照
  const saveQ = {inflight: null, pending: false};
  function saveShots(silent){ if(saveQ.inflight){ saveQ.pending = true; return saveQ.inflight; } return saveQ.inflight = doSave(silent).finally(()=>{ saveQ.inflight=null; if(saveQ.pending){ saveQ.pending=false; saveShots(true); } }); }
  async function flushSave(){ clearTimeout(saveTimer); saveTimer=null; await saveShots(true); while(saveQ.inflight) await saveQ.inflight; }
  // refresh：请求序号
  let stateSeq = 0;
  async function refresh(){ const seq = ++stateSeq, name = state.project; const d = await api(...name...); if(seq !== stateSeq || name !== state.project) return; ... }
  ```
  - `jobs.js startJob`：`task === 'build'` 时先 `await flushSave()`，失败就 toast 并停止。`startJob` 改成 async，保持返回 Promise（`test_frontend_jobs` 会 await 它）。
  - 切项目（`selectProject`）前也 `await flushSave()`，否则防抖中的保存会带着新项目名 POST 出去：`saveShots` 必须在调用时就捕获 `state.project`，`doSave(project, shots)` 用参数，不读全局。
  - `createProject`（`index.html:600-604`）：删除残留的 hash 导航，只保留 `await loadProjects(); await selectProject(name);`。
  - `browse.js` 的 `setLevel` / `toggleMust`：先记住旧值，再 POST；`!r.ok` 时恢复旧值并重新 render，然后在 `#now` 显示 `esc(err.error || COPY_SAVE_FAILED)`。
- **GOTCHA**：防抖期间如果切了项目，旧项目的分镜必须先存到旧项目名下，不能存进新项目。这就是在调用时捕获项目名的原因。
- **VALIDATE**（node vm，沿用 `tests/test_frontend_jobs.py` 的 HARNESS / STUBS）：
  - `test_saves_are_serialized_and_last_state_wins`：假 api 每次返回一个手动 resolve 的 Promise；连续调用 3 次 `saveShots` → 同一时间只有 1 个 in-flight，总共 2 次 POST，最后一次 body 是最新的 shots。
  - `test_build_flushes_pending_save_first`：打桩 `saveTimer` 有待发保存 → `startJob('build')` 的 `/api/shots` 先于 `/api/job`。
  - `test_stale_state_response_is_dropped`：A 的响应在 B 之后到 → `state.data` 是 B。
  - `test_debounced_save_keeps_original_project`。
  - `test_browse_set_level_rolls_back_on_failure`（加载 `browse.js`）。
  - `test_static_pages.py::test_create_project_has_no_hash_navigation`。

#### Task 21: 内联脚本外置 + 事件委托 + CSP 收紧（KI-53），App 内开子窗口（KI-36）
- **IMPLEMENT**：
  - `common.js` 增加委托分发：
    ```js
    window.ACTIONS = {};
    function dispatch(attr, ev){ const el = ev.target.closest(`[${attr}]`); if(!el) return; const fn = ACTIONS[el.getAttribute(attr)]; if(fn) fn(el, ev); }
    document.addEventListener('click',  e => dispatch('data-act', e));
    document.addEventListener('input',  e => dispatch('data-input', e));
    document.addEventListener('change', e => dispatch('data-change', e));
    ```
    `closest` 只取最内层，所以 `<tr data-act="pick">` 里 `<button data-act="move">` 被点时只执行 move，自然替代了原来的 `event.stopPropagation()`。
  - 四个页面的 `<script>…</script>` 原样搬进 `index.js` / `browse.js` / `confirm.js` / `calibrate.js`，页面里用 `<script src="/static/xxx.js"></script>` 引用，放在 common/jobs/settings/support 之后。
  - 所有 `onclick="f(${i})"` 改成 `data-act="f" data-i="${num(i)}"`，并注册 `ACTIONS.f = el => f(+el.dataset.i)`。字符串参数（`settings.js:63-64` 的 `saveKey('${p.key}')`）改成 `data-provider="${esc(p.key)}"`。`oninput="edit(${i},'sub',this.value)"` 改成 `data-input="editSub" data-i`。`onchange="syncTarget()"` 改成 `data-change="syncTarget"`。`confirm.html` 里 input 的 `onclick="event.preventDefault()"`：在 `ACTIONS.pick` 里调用 `ev.preventDefault()`，input 本身加 `tabindex="-1"`。`calibrate.html:61` 的 `location.href=…` 改成 `data-act="goBrowse"`。
  - `support.js:18-19`：`[onclick="exportDiag()"]` 改成 `[data-act="exportDiag"]`。
  - `gui/server.py:60-63`：`script-src 'self'`（去掉 `'unsafe-inline'`），并补一句注释说明 style 仍需要 inline。
  - KI-36：
    - `gui/desktop.py`：`OPENER = None`，`set_window_opener(fn)`；`handle_post(path, body, resolve, port)` 处理 `/api/window`：`page` 只认 `{"browse","calibrate"}`，项目经 `resolve` 校验。url = `http://127.0.0.1:{port}/static/{page}.html?project={quote(name)}`。有 OPENER 就调用 `OPENER(title, url)` 并返回 `{"opened": true}`，否则返回 `{"opened": false}`。
    - `app/main.py`：`server.set_window_opener(lambda title, url: webview.create_window(title, url, width=1280, height=860))`（在 `serve_in_background` 之后）。
    - 前端 `openBrowse` / `openCalibrate`：先 POST `/api/window`，`opened` 为 false 时退回 `window.open(url, '_blank')`。
- **MIRROR**：`server.set_picker`（`server.py:71-73`）、`app/main.py:35-41`；`support.handle_post(p, body, existing_project)`。
- **GOTCHA**：
  - 下面这些测试按「源码位置迁移」改读新文件，断言意图不变：`tests/test_frontend_js.py::_shot_id_src`（改读 index.js）、`tests/test_frontend_jobs.py::_index_fn`（改读 index.js）、`tests/test_static_pages.py::_first_inline_script`（改成断言 `common.js` 在 `index.js` 之前加载）、`test_static_pages.py:102` 的 `'onclick="openTarget(false)"'`（改成 `data-act="openTarget"`）、`test_no_string_interpolation_in_inline_handlers`（改成更强的「没有任何 on* 属性」）。
  - 遍历 `data-act` 时，模板里的数字仍然必须过 `num()`，文本必须过 `esc()`（GL-07）。
  - 浏览器模式里打开子页面仍然用 `window.open`。
  - pywebview 注入的 JS 桥不受 CSP 影响（见 External Documentation），但要人工验证。
- **VALIDATE**：
  - `test_static_pages.py::test_no_inline_event_handlers`（对 `gui/static/*.html`、`*.js` 里所有模板做正则 `\son[a-z]+\s*=` → 0 处）、`test_no_inline_script_blocks`（`<script>` 必须带 `src`）。
  - `test_server_security.py::test_csp_has_no_unsafe_inline_script`。
  - `test_frontend_js.py::test_action_dispatch_uses_innermost_target`（node vm 打桩 `closest`）。
  - `tests/test_server_desktop.py`：没有 opener 时 `{"opened": false}`；打桩 opener 后收到正确的 url 和 title；`page` 不在白名单 → 400；项目不存在 → 404；没有 token → 403。
  - `node --check gui/static/*.js`。

### 阶段 E · 收尾

#### Task 22: 文档与全量验证
- **ACTION**：
  - `README.md` / `docs/GUI.md` 写入 `aicut clean`、`AI_CUT_LLM_BUDGET_TOKENS`、清理缓存按钮、子窗口；`docs/PACKAGING.md` 写入构建号、签名身份。
  - 跑全量测试和所有静态检查。
  - 实施报告里列出「改写的既有测试」表（Task 3 / 11 / 21）。
- **VALIDATE**：见下方 Validation Commands。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_mask_tiers` | 12 / 16 / 23 / 24 / 48 位 | `********` / `****xxxx` / 同前 / `ab12****wxyz` | 是 |
| `test_get_strips_keychain_and_file_values` | `"key\n"`、`"   "` | 去空白后的值、None | 是 |
| `test_delete_also_hides_legacy_key` | 有旧版文件 | 删除后 `get` 为 None，文件仍在 | 是 |
| `test_record_failure_redacts…` | error 带已登记 Key、`sk-…`、Bearer | 文件里没有原文 | — |
| `test_stale_cached_file_id_reuploads_once_with_fresh_token` | 缓存命中 + 400 | 上传 1 次、提交 2 次、token 不同 | 是 |
| `test_update_serializes_across_processes` | 2 进程 × 50 次 | 计数 100 | 并发 |
| `test_cmd_new_loses_race_without_clobbering` | 链接时 `FileExistsError` | die、对方文件不变 | 并发 |
| `test_run_ffmpeg_timeout_is_media_error` | `TimeoutExpired` | `MediaError` 带分钟数 | — |
| `test_replaced_source_invalidates_marker` | 改素材 | 未完成 | — |
| `test_partials_not_matched_by_media_glob` | 写入中 glob | 空 | — |
| `test_truncated_wav_is_not_adopted` | 截断 wav | False、不 probe | 是 |
| `test_complete_unchanged_input_is_not_reannotated` | 第二次 run | 0 次调用 | — |
| `test_usage budget` | 已用 ≥ 预算 | `BudgetExceeded`、不调用底层 | 是 |
| `test_parse_range_unit` | 8 种 Range | 见 Task 18 | 是 |
| `test_finished_jobs_are_pruned_beyond_limit` | 4 个任务、上限 2 | 剩 2 个、running 保留 | — |
| `test_saves_are_serialized_and_last_state_wins` | 3 连发 | 1 个 in-flight、2 次 POST、最终最新 | 并发 |
| `test_no_inline_event_handlers` | 全部静态文件 | 0 处 | — |

### Edge Cases Checklist
- [x] 空输入：空 Range、空 Key、空账本、空缓存目录
- [x] 最大输入：日志 5000 行上限、RF64 wav、超大素材的超时计算
- [x] 非法类型：坏 `failed.json`、坏 `llm_usage.json`、坏 `legacy_ignored.json`、非法预算 env
- [x] 并发：project.json 跨进程 `update`、`cmd_new` 竞争、前端保存串行、partial 文件的并发写者
- [x] 网络失败：上传缓存作废、LLM 错误脱敏
- [x] 权限：共享配置目录不 chmod、`os.kill` 的 PermissionError 当活着处理、`/api/cache*` 与 `/api/window` 的 token / Host 校验

---

## Validation Commands

### Static Analysis
```bash
# 仓库未配置 lint / typecheck；做语法冒烟与 JS 语法检查
uv run python -m compileall -q aicut.py pipeline gui packaging app
for f in gui/static/*.js; do node --check "$f"; done
bash -n "启动剪辑台.command" && bash -n packaging/build_app.sh
```
EXPECT: 无输出、退出码 0

### Unit Tests
```bash
uv run pytest tests/test_secrets.py tests/test_cloud.py tests/test_llm.py tests/test_schema.py \
  tests/test_media_io.py tests/test_proc.py tests/test_usage.py tests/test_diskspace.py tests/test_cache.py \
  tests/test_server_jobs.py tests/test_server_media.py tests/test_server_security.py \
  tests/test_server_maintenance.py tests/test_server_desktop.py tests/test_static_pages.py \
  tests/test_frontend_js.py tests/test_frontend_jobs.py tests/test_launcher.py tests/test_structure.py
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 987 + 新增，全部通过，没有回归

### Database Validation
N/A（没有数据库）

### Browser Validation
```bash
AI_CUT_PROJECTS=<scratchpad>/proj AI_CUT_CONFIG_DIR=<scratchpad>/cfg AI_CUT_LOG_DIR=<scratchpad>/logs \
  uv run python gui/server.py --port 18990
```
EXPECT：
- 四个页面的控制台都没有 CSP 拦截。
- 所有按钮可用。
- `curl --noproxy '*' -H 'Range: bytes=-10'` 返回 206 和最后 10 字节；`bytes=999999-` 返回 416。
- `/static/prototype.html` 返回 404。

### Manual Validation
- [ ] App 模式（`uv run python app/main.py`）：「浏览素材」「剪辑偏好」在 App 内新开窗口；「选择素材」文件框正常（CSP 收紧后 pywebview 桥仍可用）。
- [ ] 分镜表快速连点 ↑↓✕ 十次后刷新，顺序与界面一致；改完字幕立刻点「生成成片」，新版本里是新字幕。
- [ ] 快速在两个项目之间切换，标题和分镜表始终属于最后选中的项目。
- [ ] 强杀剪辑台但任务还在跑 → 重开后顶部有提示条。
- [ ] 删除 Key 后，若 `~/.mediakit/api_key` 存在，设置页显示「未配置」。
- [ ] 第二次「重新处理」时日志显示「沿用上次的标注结果」，项目信息行的 LLM 用量不增长。
- [ ] 「清理缓存」弹窗列出 clips 大小；清理后「生成成片」能重新切片并成功。
- [ ] 双击 `启动剪辑台.command`：有 uv 时启动；没有 uv 时给出提示。
- [ ] `./packaging/build_app.sh`：Info.plist 里 `CFBundleVersion` 等于 git 提交数；未设签名身份时有警告。

---

## Acceptance Criteria
- [ ] 22 个任务全部完成；27 条 KI 中除 KI-31（已修）外，逐条有回归测试
- [ ] `uv run pytest` 全绿；`node --check` 全绿
- [ ] `aicut.py` ≤ 800 行、`gui/server.py` ≤ 650 行（测试守卫）
- [ ] CSP 中不再有 `script-src 'unsafe-inline'`
- [ ] 符合 UX「After」

## Completion Checklist
- [ ] 文案全部是命名常量（`*_MSG` / `COPY_*`）
- [ ] 第三方文本一律经过 `applog.redact`
- [ ] 写盘一律走 `schema.write_json` / `update` / `create_json_exclusive`，媒体产物一律走 `media_io`
- [ ] 测试沿用 conftest 的隔离夹具，不碰真实钥匙串、`~/.config`、`~/Library/Logs`、剪映草稿库
- [ ] 新模块都加进 spec 的 hiddenimports
- [ ] 没有登记册以外的范围

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| CSP 收紧后 pywebview 的文件选择 / JS 桥失效 | 低 | 高 | 人工验证；如果失效，单独给 pywebview 模式回退（仍然不在页面里放内联脚本） |
| 事件委托改造面大（约 80 处），漏改的按钮会失灵 | 中 | 中 | 「没有 on* 属性」守卫测试，加上浏览器里逐个点一遍 |
| 跨进程 flock 在网络盘 / 外接盘上不可用 | 低 | 中 | `flock` 抛 OSError 时退回进程内锁，并记一条 warning（不阻断保存） |
| 改了掩码格式后，界面 / 诊断里的旧断言、旧截图失效 | 高 | 低 | 已列出要改写的测试；文档截图不更新 |
| 拆分 aicut / server 打断现有打桩点 | 中 | 中 | 只搬纯函数，handler 和路由按全局名查找；阶段 0 单独跑全量 |
| 预算默认值过低，挡住正常长素材 | 低 | 中 | 默认 300 万 tokens 并支持 env 调整；超限文案给出调整方法 |

## Notes

### 需用户决策（实施按「推荐默认」进行，除非用户另行指定）
| # | 问题 | 推荐默认 |
|---|---|---|
| D1 | Key 掩码规则（KI-67） | ≥24 位 `前4****后4`；16–23 位 `****后4`；<16 位固定 `********` |
| D2 | 删除 Key 时怎么处理旧版 `~/.mediakit/api_key`（KI-28） | 不删别的工具的文件，在配置目录记一条「已忽略」，之后不再读它；重新填 Key 后恢复 |
| D3 | LLM 预算（KI-32） | 每个项目累计 3,000,000 tokens 上限，`AI_CUT_LLM_BUDGET_TOKENS` 可调，0 = 不限；界面只显示 tokens，不折算金额 |
| D4 | 「清理缓存」删哪些（KI-33） | `work/clips/`、残留的临时文件，以及在转写与声音分析都已完成时的 `asr.wav`；不删 proxy、预览、成片和任何 JSON；GUI 加按钮并弹确认 |
| D5 | 磁盘预检阈值（KI-33） | 按码率估算产物大小，再加 1 GB 余量；不够就在开始前停下并说明需要多少 |
| D6 | ffmpeg 超时（KI-61） | 抽音轨 / 代理：`max(10 分钟, 素材时长 × 1)`；切片：`max(10 分钟, 镜头时长 × 10)`；ffprobe 60 秒；其他 60 分钟 |
| D7 | 旧完成标记没有素材指纹（KI-62） | 视为与当前素材一致，补写指纹（和 M3「认领旧产物」的口径一致）；另一种做法是一律重做，更安全但旧项目要重新生成代理 |
| D8 | 子页面怎么打开（KI-36） | App 内新开 pywebview 窗口；浏览器模式仍然开新标签 |
| D9 | CSP 收紧范围（KI-53） | 只收紧 `script-src`；`style-src` 保留 `'unsafe-inline'`（内联 style 属性很多，风险低） |
| D10 | 升级丢授权（KI-37） | 不引入证书（PRD 不做签名）；构建时未设 `CODESIGN_IDENTITY` 就告警；文档写自签证书步骤；CHANGELOG 注明 adhoc 签名下升级需要重新授权 |
| D11 | prototype.html（KI-52） | 生成器改为输出到 `prototype/prototype.html`；服务端只发白名单文件；打包排除 |
| D12 | `.command` 没有 uv 时（KI-34） | 提示安装 uv 后退出，不回落系统 python3 |
| D13 | 任务表保留量（KI-68） | 保留最近 20 个已结束任务；单任务日志最多 5000 行，保留末尾 |
| D14 | 遗留任务提示方式（KI-71） | 打开剪辑台时顶部提示条（与警告条同样式），不弹窗 |

### 其它
- 本计划**未**修改 PRD 的里程碑状态（编排约束：只写本计划文件）。prp-plan 规范里「更新 PRD 为 in-progress」的那一步由编排方执行。
- 阶段 0 的两个拆分必须先做：之后 aicut 还要加约 40 行（预算、磁盘、clean、超时、指纹），server 还要加约 15 行（白名单、分发、stale_job）。
- 与其它里程碑的边界：KI-22（M8）不碰 questions 的缓存；KI-19（M8）的返回码不碰，M9 只加 `timeout=`；KI-15（M7）的 `pipeline/select.py` 遮蔽标准库问题不碰。Task 17 让开发模式优先用 uv 环境（不再走 `~/.aicut/venv` 的 Homebrew Python），会附带降低 KI-15 的触发概率，但 KI-15 不因此关闭。
