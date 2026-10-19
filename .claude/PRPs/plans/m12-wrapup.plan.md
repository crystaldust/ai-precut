# Plan: M12 收尾（KI-80 / KI-88 / KI-89）

## Summary
三件互不相关的收尾修复：
① **KI-80**：`pipeline/to_jianying.py` 直接用相对 `--staging` 跑时，草稿里的素材路径与 dry-run 校验的重定位路径都是相对路径 → 静态校验 FAIL。入口处把 staging 变成绝对路径，`bundle_media` 再兜底一次。
② **KI-88**：页面 HTML 不再内嵌长期 token。桌面壳 / 浏览器启动器打开 `/?nonce=<一次性随机串>`，服务端一次性兑换成 `HttpOnly; SameSite=Strict; Path=/` 的会话 cookie 并 302 回去掉 nonce 的地址；`/api/*` 与 `/media/*` 都只认 cookie（Host / Origin / Content-Type 检查保留）。没有有效 nonce / cookie 的页面请求只拿到一张「请从剪辑台 App 打开」的极简页。子窗口（`/api/window`）由服务端给每个新窗口单独发 nonce，`X-AICUT-Token` 请求头整条路径删除。
③ **KI-89**：切片按内容命名 `work/clips/<id>-<clip_key>.mp4`，时间线 `source` 指向带键的文件；新版本重切同名镜头只会产生新文件，不再改动旧版本引用的切片。旧时间线（指向 `<id>.mp4`）照常可用、可补切；旧缓存在键一致时硬链接复用，不重切；出片成功后清掉不再被任何版本引用的切片。

## User Story
As 剪辑师（以及维护剪辑台的开发），
I want 同一台 Mac 上的其他账户拿不到剪辑台的访问凭证、旧版本重新导出与当初一模一样、命令行用相对路径也能出草稿，
So that 我交出去的每一版都可复现，本机数据不被旁人读写。

## Problem → Solution
- KI-80：`main()` 把 `Path(args.staging)` 原样传给 `build_staging` → `draft_dir` 相对 → dry-run 校验 `relocate=(root/name, draft_dir)` 把素材路径改写成相对路径 → 校验找不到文件 FAIL
  → `main()` 里 `staging = Path(os.path.abspath(Path(args.staging).expanduser()))`；`bundle_media` 对 `final_dir` 也 `abspath`（不用 `resolve()`：macOS 上 `/var` → `/private/var` 会让既有测试的路径比较失配）。
- KI-88：`_send_page` 把 `API_TOKEN` 替换进 `<meta name="aicut-token">`，`GET /` 只校验 Host → 本机任何用户 `curl -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/` 即得 token
  → 新模块 `gui/session.py` 管理一次性 nonce 与会话 cookie；页面不再含任何秘密。
- KI-89：`ensure_clips` 切到 `work/clips/<id>.mp4`，manifest 记 `{id: key}`；vN+1 改了 S03 的入出点 → 覆盖 `S03.mp4` → vN 的 `timeline.json` 仍指向它 → vN 重新导出内容变了
  → 文件名带键，内容不同则文件不同；`manifest.json` 只读（兼容旧缓存），不再写。

## Metadata
- **Complexity**: Medium（约 14 个文件，后端为主，前端只改 `common.js` 与 4 个页面的 meta）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 12「收尾」（KI-80 KI-88 KI-89）
- **Estimated Files**: CREATE 2（`gui/session.py`、`tests/test_m12_wrapup.py`）/ UPDATE ~14

---

## 产品 / 设计决策（按默认值执行，均可事后改）

| # | 决策 | 默认值 | 理由 |
|---|---|---|---|
| D1 | nonce 有效期与数量 | 一次性、**5 分钟**过期、仅存内存；未兑换的 nonce 最多 64 个（超出丢最旧的） | 浏览器冷启动可能要几十秒；只在本进程内产生，不落盘 |
| D2 | 无凭证时页面 | HTTP **403** + 极简 HTML：「请从剪辑台 App 打开」，附一句「浏览器模式：请重新双击『启动剪辑台』」；同样带 CSP，不含脚本 | 用户要求的文案；403 便于测试区分 |
| D3 | API / 媒体无 cookie 时的提示 | 403 JSON，文案改为「页面已过期：请关掉这个页面，从剪辑台重新打开」（常量 `TOKEN_EXPIRED_MSG` 名字保留） | 刷新已经不能恢复（刷新只会看到 D2 的页面） |
| D4 | 哪些路径要 cookie | `/`、`/index.html`、白名单内的 `/static/*.html`、`/api/*`、`/media/*`；`/static/*.js` **不要**（不含秘密，保持现状） | 用户要求 `<video>` 也带 cookie；JS 公开无风险 |
| D5 | `X-AICUT-Token` 请求头 | **整条删除**（服务端、`common.js`、页面 meta） | 子窗口改为每窗一个 nonce，不再需要 |
| D6 | 浏览器模式入口 | `--open`：`webbrowser.open(<nonce 地址>)`，终端只打印不带 nonce 的地址；不带 `--open`：终端打印一条一次性入口链接 | macOS 的 `webbrowser` 经 `osascript` 的 **stdin** 传 URL，`ps` 看不到 nonce |
| D7 | cookie 形态 | 名字 `aicut_session_<port>`、值为每次启动随机 32 字节 hex；会话 cookie（无 Max-Age）；`Path=/; HttpOnly; SameSite=Strict` | cookie 不按端口隔离，名字带端口避免两个剪辑台实例互相覆盖 |
| D8 | 桌面壳 `webview.start(private_mode=False)` | 改为 `False` | pywebview 6.2.1 cocoa 在 private_mode 下**每建一个窗口**都清空共享的 defaultDataStore（`cocoa.py:632-641`），开子窗口会把主窗口的 cookie 清掉；会话 cookie 本身不落盘，每次启动值也不同 |
| D9 | 切片文件名 | `<id>-<clip_key>.mp4`（`clip_key` 已是 12 位 sha1 hex，含素材路径 + 入出点 + id） | 用户指定格式；键定长，`id` 里有 `-` 也不歧义 |
| D10 | 旧缓存兼容 | `manifest[id] == key` 且旧 `<id>.mp4` 完整 → 硬链接（失败退回复制）成带键文件，不重切；之后不再写 manifest | 升级后第一次出片不必全量重切；不写 manifest 才不会把新键记到旧内容上 |
| D11 | 清理不再被引用的切片 | 出片写完 `timeline.json` 后，删除 `work/clips/*.mp4` 中**不被任何 `output/*/timeline.json` 引用**的文件（连同 `.done` 标记）；任一时间线读不出就整次跳过 | 带键命名会让每次改入出点都留下新文件；草稿与 Windows 包都拷贝媒体，不引用 `work/clips` |
| D12 | KI 状态回填 | 本里程碑不改 KI-80/88/89 的「状态」列，提交后由 docs 提交回填提交号（与 M10/M11 一致） | 本次不提交 |

---

## UX Design

### Before
```
App 启动 → 窗口打开 http://127.0.0.1:8765/ → 页面源码里有 token
同机其他账户：curl http://127.0.0.1:8765/ → 拿到 token → 调全部 API
```

### After
```
App 启动 → 窗口打开 /?nonce=N1 → 302 /（Set-Cookie）→ 正常使用
子窗口：POST /api/window → 服务端发 N2 → 新窗口打开 /static/browse.html?project=p&nonce=N2 → 302 → 正常
同机其他账户：curl / → 403「请从剪辑台 App 打开」；/api/* → 403
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 浏览器模式双击「启动剪辑台」 | 打开 `/` | 打开 `/?nonce=…` 并立即跳回 `/` | 关掉标签后，在同一浏览器会话内直接访问 `/` 仍可用（cookie 还在） |
| 浏览器里服务重启后的旧标签 | 「页面已过期，请刷新」 | 「页面已过期：请关掉这个页面，从剪辑台重新打开」 | 重新双击启动器会开新标签 |
| 剪辑师在 App 里 | 无变化 | 无变化 | WKWebView 是否接受 302 上的 cookie：**需实机确认**（见手工检查） |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `gui/server.py` | 49-60, 171-175, 214-234, 280-300, 367-383, 581-604 | token 注入、访问控制、页面 / 媒体路由、浏览器入口 |
| P0 | `gui/desktop.py` | 16-50 | 子窗口 URL 拼装 |
| P0 | `app/main.py` | 29-52 | 主窗口 URL、`webview.start()` |
| P0 | `gui/static/common.js` | 1-23 | 前端 fetch 补丁（带 token） |
| P0 | `aicut.py` | 524-557, 595-615 | `ensure_clips` / `actual_durations` / `cmd_build` |
| P0 | `pipeline/clips.py` | 全部 | 切一镜、补切、磁盘预检 |
| P0 | `pipeline/to_jianying.py` | 244-270, 684-701 | `bundle_media`、`main` |
| P1 | `pipeline/timeline.py` | 35-50 | `compose_timeline` 写 `source` |
| P1 | `pipeline/media_io.py` | 52-54, 80-100, 152-180, 317-360 | 完成标记、原子落盘、manifest、旧文件认领 |
| P1 | `tests/conftest.py` | 72-115 | `gui_server` 夹具、`call()` 默认带凭证 |
| P2 | `.venv/.../webview/platforms/cocoa.py` | 626-646 | private_mode 清数据 |
| P2 | `docs/GUI.md` | 82-89 | 安全模型（要改写） |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| pywebview 6.2.1 cocoa 数据存储 | `.venv/lib/python3.12/site-packages/webview/platforms/cocoa.py:626-646` | private_mode=True 时每个窗口初始化都 `removeDataOfTypes…modifiedSince 1970`，作用于共享的 `defaultDataStore` → 子窗口会清掉主窗口 cookie；private_mode=False 直接用 defaultDataStore |
| WKWebView cookie | WebKit：应用 `loadRequest` 发起的导航按同站处理；302 响应上的 `Set-Cookie` 在跟随重定向前写入 | 推断，无法在测试里验证 → 列为手工检查 |
| Python `webbrowser`（3.12, macOS） | `webbrowser.MacOSXOSAScript.open` | 通过 `os.popen("osascript","w")` 把脚本写进 stdin，URL 不出现在进程参数里 |
| Cookie 与端口 | RFC 6265 §8.5 | cookie 不按端口隔离：同一浏览器访问 127.0.0.1 上任意端口都会带上 → 浏览器模式残余风险（登记 KI-90） |

KEY_INSIGHT: cookie 不分端口；SameSite 的 "site" 也不看端口。
APPLIES_TO: 浏览器模式（App 内 WKWebView 不访问别的站点，不受影响）。
GOTCHA: 本机另一个用户在 127.0.0.1 其他端口起服务并诱导剪辑师用**同一浏览器**访问，就能收到 cookie → 文档写明，登记 KI-90（低）。

---

## Patterns to Mirror

### NAMING_CONVENTION / 常量
// SOURCE: gui/server.py:49-55
```python
API_TOKEN = os.urandom(32).hex()  # 每次启动随机生成；页面加载时由服务端注入
TOKEN_HEADER = "X-AICUT-Token"
TOKEN_EXPIRED_MSG = "页面已过期，请刷新"
ALLOWED_HOSTNAMES = ("127.0.0.1", "localhost")
```
→ 新常量全大写，中文文案做模块常量；模块 docstring 写清楚 KI 编号。

### ERROR_HANDLING（访问控制返回 (状态码, 原因)）
// SOURCE: gui/server.py:218-234
```python
def _deny_reason(self, path: str, post: bool) -> tuple[int, str] | None:
    ...
    if path.startswith("/api/"):
        given = self.headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(given.encode(), API_TOKEN.encode()):
            return 403, TOKEN_EXPIRED_MSG
    return None
```

### SERVICE_PATTERN（gui 子模块：纯函数 + 模块级状态 + 注入）
// SOURCE: gui/desktop.py:16-27
```python
PAGE_URL = "http://127.0.0.1:{port}/static/{page}.html?project={project}"
OPENER: Callable[[str, str], object] | None = None
def set_window_opener(fn): global OPENER; OPENER = fn
```

### 切片缓存（每镜落盘、失败 die）
// SOURCE: aicut.py:524-547
```python
for sh in shots:
    key = build_documentary.clip_key(sh, src)
    dst = clips_dir / f"{sh['id']}.mp4"
    if manifest.get(sh["id"]) == key and media_io.complete_or_adopt(dst):
        continue
    info(f"切镜头 {sh['id']}（{sh['out'] - sh['in']:.1f}s）")
    try:
        clips.cut_clip(dst, src, sh)
    except media_io.MediaError as exc:
        die(f"切镜头 {sh['id']} 失败：{exc}")
```

### 原子落盘
// SOURCE: pipeline/media_io.py:152-167
```python
with media_io.atomic_output(dst) as tmp:   # 块结束才改名并写 .done 标记
    ...
```

### TEST_STRUCTURE
// SOURCE: tests/conftest.py:101-115、tests/test_clips_restore.py:12-30
```python
def call(gs, method, path, body=None, *, token=True, headers=None, raw=None):
    h = {"Host": f"127.0.0.1:{gs.port}"}
    if token: h["X-AICUT-Token"] = ...
def fake_ffmpeg(calls):
    def run(args, **kw):
        calls.append(args); Path(args[-1]).write_bytes(b"clip")
    return run
```
→ `call(token=True)` 改为带 `Cookie: aicut_session_<port>=<secret>`；参数名 `token` 保留（语义 = 带凭证），免得改 60+ 处调用。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `gui/session.py` | CREATE | nonce 发放/兑换、cookie 头、cookie 校验、入口 URL |
| `gui/server.py` | UPDATE | 去 token 注入；页面/媒体/API 统一 cookie；nonce 兑换 302；无凭证页；`main()` 入口 URL |
| `gui/desktop.py` | UPDATE | 子窗口 URL 附带新 nonce |
| `app/main.py` | UPDATE | 主窗口用 nonce URL；`webview.start(private_mode=False)` |
| `gui/static/common.js` | UPDATE | 去 token；同源 `/api/` 显式 `credentials:'same-origin'` |
| `gui/static/{index,browse,confirm,calibrate}.html` | UPDATE | 删 `<meta name="aicut-token">` |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 加 `gui.session`（`tests/test_structure.py` 有守卫） |
| `pipeline/clips.py` | UPDATE | `clip_name/clip_path`、`ensure`（从 aicut 下沉）、旧缓存硬链接、`pending_cut_seconds`、`restore_missing` 按 `source` 补切、`prune_unreferenced` |
| `pipeline/timeline.py` | UPDATE | `compose_timeline` 接受 `{id: Path}`（仍兼容传目录） |
| `aicut.py` | UPDATE | `ensure_clips` 返回 `{id: Path}`；`actual_durations` 按路径；`cmd_build` 出片后清理 |
| `pipeline/to_jianying.py` | UPDATE | staging / final_dir 绝对化 |
| `tests/conftest.py` + 受影响测试 | UPDATE | cookie 凭证；切片新命名 |
| `tests/test_m12_wrapup.py` | CREATE | 三个 KI 的回归测试 |
| `docs/GUI.md`、`docs/known-issues.md`、`CHANGELOG.md`、PRD | UPDATE | 安全模型；登记 KI-90；里程碑 plan 链接 |

## NOT Building

- 不做 HTTPS / `Secure` / `__Host-` 前缀 cookie（127.0.0.1 明文 HTTP，浏览器对 Secure 的放行不一致）。
- 不做按端口隔离 cookie 的额外机制（KI-90 登记，浏览器模式残余风险）。
- 不做「从终端重新签发入口链接」的命令。
- 不改「清理缓存」的范围（仍整个删 `work/clips/`，旧版本导出按快照补切）。
- 不迁移 / 改写已有版本的 `timeline.json`。
- 不回填 KI-80/88/89 状态列（提交后回填）。

---

## Step-by-Step Tasks

### Task 1: KI-80 相对 staging（RED → GREEN）
- **ACTION**: 先写测试：`monkeypatch.chdir(tmp_path)`，`proc.run_inprocess("pipeline.to_jianying", [tl, "--name","T","--staging","stg","--dry-run"])` → `code == 0`，草稿 `draft_content.json` 里视频素材 `path` 是绝对路径；再写 `bundle_media(d, Path("rel/T"))` 写出绝对路径的单测。
- **IMPLEMENT**: `main()`：`staging = Path(os.path.abspath(Path(args.staging).expanduser()))`；`bundle_media`：`final_res = Path(os.path.abspath(final_dir)) / "Resources"`。
- **MIRROR**: `tests/test_jianying_golden.py:45-52`（dry-run 入口调用）、`tests/test_to_jianying.py:92-110`（`clip`、`full_timeline` 夹具）。
- **GOTCHA**: 用 `abspath` 不用 `resolve()`；`clip` 夹具要 ffmpeg，无 ffmpeg 自动 skip。
- **VALIDATE**: `uv run pytest tests/test_m12_wrapup.py -k ki80 tests/test_to_jianying.py tests/test_jianying_golden.py`

### Task 2: KI-88 `gui/session.py`（RED → GREEN）
- **ACTION**: 先写单测：nonce 一次性、过期失效、上限淘汰；`cookie_header(port)` 含 `HttpOnly`、`SameSite=Strict`、`Path=/`，不含 `Max-Age/Expires`；`has_valid_cookie` 对缺失 / 错值 / 别的端口名 / 畸形 cookie 串返回 False，对多 cookie 串中的正确值返回 True；`entry_url` 拼 `?nonce=` 或 `&nonce=`。
- **IMPLEMENT**:
  ```python
  SECRET = secrets.token_hex(32); NONCE_TTL_S = 300; MAX_PENDING = 64
  COOKIE_NAME = "aicut_session_{port}"
  def issue_nonce(*, now=time.monotonic) -> str
  def redeem(nonce: str, *, now=time.monotonic) -> bool   # pop；过期 False
  def cookie_name(port: int) -> str
  def cookie_header(port: int) -> str
  def has_valid_cookie(raw: str | None, port: int) -> bool   # 手工按 ; 切，hmac.compare_digest
  def entry_url(url: str) -> str
  ```
- **MIRROR**: `gui/desktop.py` 模块结构；锁用 `threading.Lock`（`gui/jobs.py` 的 `JOBS_LOCK` 写法）。
- **GOTCHA**: 不用 `http.cookies.SimpleCookie`：别的本地应用写的畸形 cookie 会让它整串解析失败；nonce 用 `secrets.token_urlsafe(32)`。
- **VALIDATE**: `uv run pytest tests/test_m12_wrapup.py -k session`

### Task 3: KI-88 服务端接线（RED → GREEN）
- **ACTION**: 先写集成测试（`gui_server` 夹具）：
  1. 无 cookie `GET /` → 403，正文含「请从剪辑台 App 打开」，且不含 `SECRET`；
  2. `GET /?nonce=<有效>` → 302，`Location: /`，`Set-Cookie` 属性正确；再用同一 nonce → 403；
  3. `GET /static/browse.html?project=p1&nonce=…` → 302 到 `/static/browse.html?project=p1`；
  4. 带 cookie `GET /` → 200，页面不含 `__AICUT_TOKEN__`、不含 `SECRET`；
  5. `/api/projects`、`/media/p1/proxy` 无 cookie 403、带 cookie 200；`X-AICUT-Token` 头不再被接受；
  6. 错 Host 时带有效 nonce 也 403 且 nonce 不被消耗。
  改旧测试：`conftest.call` 带 cookie；`test_server_security` 中 token 相关 5 个测试改为 cookie 语义；`test_server_hardening._raw_post` 改 Cookie 头；`test_static_pages` / `test_frontend_js` 去 meta/token 断言，改为断言 `credentials`。
- **IMPLEMENT**: `server.py`：删 `API_TOKEN/TOKEN_HEADER/TOKEN_PLACEHOLDER/hmac`；`_send_page` 不再替换；`_deny_reason` 对 `/api/`、`/media/` 用 `session.has_valid_cookie(self.headers.get("Cookie"), port)`；`_route_get` 在 Host 检查后对页面路径调用 `_page_or_gate(p, q, f)`：有 nonce → 兑换成功则 302 + Set-Cookie；已有有效 cookie → 302 去掉 nonce；否则 → 403 gate 页。`main()`：`--open` 时 `webbrowser.open(session.entry_url(url))`，否则打印一次性入口链接。
- **MIRROR**: `_send()` 的 `extra` 头参数；`_json` 的错误返回。
- **GOTCHA**: 302 也要 `Cache-Control: no-store` 与安全头（`_send` 已统一加）；Location 只用已知页面路径拼，避免开放重定向；保持 `server.py` < 800 行（`tests/test_structure.py`）。
- **VALIDATE**: `uv run pytest tests/test_server_*.py tests/test_static_pages.py tests/test_frontend_js.py tests/test_m12_wrapup.py`

### Task 4: KI-88 桌面壳与子窗口（RED → GREEN）
- **ACTION**: 先改测试：`test_server_desktop.test_opener_gets_local_url_and_title` 断言 URL 以原地址 + `&nonce=` 开头且 nonce 可兑换一次；`test_app_main` 断言主窗口 URL 带 `?nonce=`、`start` 收到 `private_mode=False`。
- **IMPLEMENT**: `desktop.handle_post` 拼 URL 后 `session.entry_url(url)`；`app/main.py`：`webview.create_window("AI 粗剪", server.entry_url(url), …)`（server 暴露 `entry_url = session.entry_url`），`webview.start(private_mode=False)`。
- **GOTCHA**: `test_app_main` 的假 `start()` 不接受参数 → 改成 `start(**kw)` 并记录。
- **VALIDATE**: `uv run pytest tests/test_server_desktop.py tests/test_app_main.py`

### Task 5: KI-88 前端
- **ACTION**: `common.js`：删 meta/TOKEN；同源 `/api/` 请求 `opt.credentials = 'same-origin'`；4 个 html 删 meta。
- **VALIDATE**: `tests/test_frontend_js.py`（node 执行）、`tests/test_static_pages.py`

### Task 6: KI-89 切片按内容命名（RED → GREEN）
- **ACTION**: 先写测试：
  1. 出 v1（S01 0–1s）→ 改 S01 为 0–2s 出 v2 → v1 时间线引用的文件字节与 v1 当时一致、路径不同于 v2；
  2. `compose_timeline` 的 `source` = `clips/<id>-<key>.mp4`；
  3. 旧缓存：`S01.mp4` 完整 + manifest 键一致 → 不调 ffmpeg，生成带键文件；manifest 键不一致 → 重切；
  4. `pending_cut_seconds` 按新规则；
  5. 旧时间线（`S01.mp4`）被清理后导出 → 补切到时间线里写的那个路径；新时间线（带键）同理；
  6. `prune_unreferenced`：删未引用、留被任一版本引用的（含旧式名）；有时间线读不出 → 一个都不删。
  改旧测试：`test_aicut_build.test_clips_resume_after_failure`、`test_m8_followup.test_corrupt_clip_manifest_recut_with_warning`、`test_clips_restore.test_pending_cut_seconds_skips_cached_clips` 按新命名断言。
- **IMPLEMENT**（`pipeline/clips.py`）：
  ```python
  def clip_name(shot, src) -> str: return f"{shot['id']}-{build_documentary.clip_key(shot, src)}.mp4"
  def _adopt_legacy(clips_dir, shot, key, manifest, dst) -> bool  # 硬链接 / 复制进 atomic_output
  def is_cached(clips_dir, shot, src, manifest) -> bool
  def ensure(pdir, src, shots, say) -> dict[str, Path]   # 抛 media_io.MediaError（带镜头 id）
  def referenced(pdir) -> set[str] | None
  def prune_unreferenced(pdir) -> int
  ```
  `restore_missing` 补切到 `Path(v["source"])`；`aicut.ensure_clips` 变薄壳（check ids、调 `clips.ensure`、MediaError → die）；`actual_durations(paths, shots)`；`compose_timeline(..., clips: dict[str, Path] | Path, ...)`；`cmd_build` 写完时间线后 `clips.prune_unreferenced(pdir)`。
- **GOTCHA**: 测试里大量 monkeypatch `ensure_clips` 返回目录 `project/"work/clips"` → `actual_durations`/`compose_timeline` 必须同时兼容目录（旧 `<id>.mp4` 命名），否则一堆不相关测试会崩；清理在 `--version` 覆盖同名版本时会删掉被覆盖版本独有的切片，这正是预期。
- **VALIDATE**: `uv run pytest tests/test_m12_wrapup.py -k ki89 tests/test_aicut_build.py tests/test_clips_restore.py tests/test_m8_followup.py tests/test_e2e_draft.py`

### Task 7: 文档与登记
- **ACTION**: `docs/GUI.md` 安全模型改写（nonce → cookie、能防什么、不能防什么、KI-90）；`known-issues.md` 新增 KI-90；`CHANGELOG.md` 记一笔；PRD 第 12 行加 plan 链接；`packaging/ai-cut.spec` 加 `gui.session`。
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py tests/test_structure.py tests/test_packaging.py`

### Task 8: 全量验证 + 实机冒烟
- `uv run pytest`、`uv run pytest --cov`（≥ 80%）；`wc -l aicut.py gui/server.py` < 800。
- 用隔离数据目录在空闲端口起 `gui/server.py`，curl 验证 nonce → cookie 流程，再停掉。

---

## Testing Strategy

### Unit / Integration Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| ki80 相对 staging dry-run | `--staging stg`，cwd=tmp | code 0，素材路径绝对 | 是 |
| session nonce 一次性 | 兑换两次 | True, False | 是 |
| session nonce 过期 | now+301s | False | 是 |
| session cookie 畸形串 | `"a; =; b=="` | False，不抛异常 | 是 |
| GET / 无 cookie | — | 403 gate 页，无秘密 | |
| GET /?nonce | 有效 nonce | 302 + Set-Cookie | |
| 子窗口 nonce | POST /api/window | URL 带可兑换 nonce | |
| media 无 cookie | — | 403 | |
| 旧版本切片不变 | v1→改入出点→v2 | v1 文件字节不变 | 是 |
| 旧缓存硬链接 | manifest 命中 | 0 次 ffmpeg | 是 |
| prune 保守 | 坏 timeline | 0 删除 | 是 |

### Edge Cases Checklist
- [x] 空 / 畸形 Cookie 头
- [x] nonce 重放、过期、错 Host
- [x] 两个实例不同端口（cookie 名带端口）
- [x] 旧时间线 + 清理缓存
- [x] 时间线损坏时清理

---

## Validation Commands

### Static Analysis
未配置 lint / 类型检查（CLAUDE.md）。`uv run python -m py_compile gui/session.py`。

### Unit Tests
```bash
uv run pytest tests/test_m12_wrapup.py -q
```

### Full Test Suite
```bash
uv run pytest -q
uv run pytest --cov -q
```
EXPECT: 全绿（基线 1756 passed），覆盖率 ≥ 80%。

### Browser Validation
```bash
AI_CUT_DATA_DIR=<tmp> uv run python gui/server.py --port <free>   # 打印一次性入口链接
curl -si -H "Host: 127.0.0.1:<port>" http://127.0.0.1:<port>/            # 403 gate
curl -si "http://127.0.0.1:<port>/?nonce=<N>"                             # 302 + Set-Cookie
curl -s -b "aicut_session_<port>=<v>" http://127.0.0.1:<port>/api/projects # 200
```

### Manual Validation（需实机）
- [ ] 打包 App 启动，主窗口正常加载项目列表（WKWebView 接受 302 上的 `SameSite=Strict` cookie）。
- [ ] App 内打开「浏览素材」子窗口：能播放代理片（`<video>` 带 cookie），主窗口仍可操作（未被清 cookie）。
- [ ] 双击「启动剪辑台.command」：默认浏览器打开后跳回 `/`，可用。

---

## Acceptance Criteria
- [ ] 三个 KI 的回归测试先红后绿
- [ ] `uv run pytest` 全绿；`--cov` ≥ 80%
- [ ] `aicut.py`、`gui/server.py` < 800 行
- [ ] 页面响应里不再含任何长期秘密；无 cookie 时 `/`、`/api/*`、`/media/*` 均 403
- [ ] 旧版本时间线引用的切片在新一版出片后字节不变
- [ ] curl 冒烟通过

## Completion Checklist
- [ ] 代码沿用既有模式（常量 + 中文文案、`_send` 统一安全头、原子落盘）
- [ ] 错误处理与 codebase 一致（MediaError → die；403 JSON）
- [ ] 测试沿用 `gui_server` / `call` / `fake_ffmpeg`
- [ ] 文档更新：GUI.md 安全模型、known-issues KI-90、CHANGELOG
- [ ] 无范围外改动

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WKWebView 不在 302 上保存 / 发送 Strict cookie | 低 | 高（App 打不开） | 手工检查；回退方案：改为 200 响应 + `Refresh: 0; url=/` 头 |
| private_mode=False 带来的持久化副作用 | 低 | 低 | 所有响应 `no-store`；会话 cookie 不落盘；前端不用 localStorage |
| 清理切片误删 | 低 | 中 | 只删未被任何时间线引用的；时间线读不出整次跳过；有单测 |
| 大量既有测试依赖 `<id>.mp4` | 中 | 低 | `compose_timeline` / `actual_durations` 兼容目录参数 |

## Notes
- 本里程碑无破坏性数据迁移；旧版本 `timeline.json` 保持原样可用。
- KI-90（新登记）：浏览器模式下会话 cookie 不按端口隔离。
