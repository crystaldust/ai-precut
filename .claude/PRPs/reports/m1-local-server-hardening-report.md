# Implementation Report: 里程碑 1 · 本地服务安全，编辑不丢

## Summary
按 `.claude/PRPs/plans/m1-local-server-hardening.plan.md` 实现 GL-05 / GL-06 / GL-07 / GL-18 / GL-21 / GL-23：

- **GL-05**：所有请求校验 Host（`127.0.0.1:<port>` / `localhost:<port>`）；`/api/*` 要求每次启动随机生成的 token（`X-AICUT-Token`，由服务端注入到 HTML 的 `<meta name="aicut-token">`）；POST 另外校验 Origin（缺失放行、`null` 和外站拒绝）与 `Content-Type: application/json`（否则 415）；所有响应加 `nosniff` / `X-Frame-Options: DENY` / `CORP: same-origin`。新增 `gui/static/common.js` 给同源 `/api/` 请求自动加 token。`/media/*`、`/static/*` 只校验 Host。
- **GL-06**：`pipeline/schema.py` 新增 `check_project_name` / `check_version` / `check_shot_ids`（唯一一份），server（`project_path`、`/api/job`、`/api/new`、`/media/.../preview/<v>`）和 aicut（`project_dir`、`cmd_new`、`cmd_build`、`ensure_clips`）共用；`/api/new` 校验预设、改用 `--x=value` 传参；`/api/confirm` 的 ValueError 不再导致断连。
- **GL-07**：`common.js` 提供 `esc()`（含单引号）和 `num()`；index/browse/confirm 删除本地 `escapeHtml`/`escapeAttr`，所有 LLM/磁盘来源文本过 `esc()`，数字过 `num()`，内联事件只传数字下标（`jumpSeg(i)`、`toggleMustIdx(i)`、`pick(qi,oi)`）。
- **GL-18**：`schema.write_json` 唯一临时文件原子写，`jdump` / `aicut.save_json` / `schema.save` / `review._save` 全部改用它；`review` 读改写加 `_LOCK`，损坏的 `overrides.json` 抛 `OverridesCorrupt`（ValueError 子类），server 返回 409 且不覆盖；坏请求体（非法 JSON / 非 UTF-8 / 非对象 / 非法 Content-Length）返回 400 不落盘；`/api/shots` 缺 `shots` 列表返回 400。
- **GL-21**：`/media/` 先按 `/` 切分再逐段 `unquote`，中文/空格项目名可播放、可 Range；`%2F` 不会造出新路径层级。
- **GL-23**：服务端 `/api/shots` 拒绝重复/缺失/非法 id（不再兜底生成 `sh{i}`），aicut `ensure_clips` 在 mkdir/ffmpeg 前拒绝；前端 `renumber()` 改为「现有 shNN 最大编号 +1」，并修正重复/非法 id。

需用户决策项均按计划推荐默认值实现，文案各在一个命名常量里：
- overrides.json 损坏 → 409 拒绝写入：`review.OverridesCorrupt` 消息（`pipeline/review.py`）
- token 失效文案：`gui/server.py` `TOKEN_EXPIRED_MSG = "页面已过期，请刷新"`
- 项目名规则：`pipeline/schema.py` `PROJECT_NAME_MAX = 100`、`PROJECT_NAME_ERROR`

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large（与预估一致） |
| Confidence | — | 高：自动化覆盖全部服务端路径；前端仅剩人工验证 |
| Files Changed | 16（UPDATE 10，CREATE 6） | 17（UPDATE 10，CREATE 7）；`docs/go-live-blockers.md` 未改（见偏差） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | schema 原子写与校验函数 | done | 额外加了 `test_save_concurrent_same_path`（RED 已验证）；控制字符也拒绝 DEL(0x7f) |
| 2 | review 区分损坏、加锁 | done | 额外覆盖 `clear(id)` 损坏不覆盖 |
| 3 | aicut 守卫 | done | 偏差：`cmd_new` 也加了项目名校验（见下） |
| 4 | 测试脚手架 conftest | done | `serve_forever(poll_interval=0.01)`，否则每个用例 teardown 0.5s |
| 5 | 请求守卫 / token 注入 / 安全头 | done | Host 比较做了 lower() |
| 6 | 路由参数校验 | done | |
| 7 | 保存不丢（服务端） | done | |
| 8 | /media percent-decode | done | |
| 9 | common.js 与 token（前端） | done | fetch 补丁按同源 + pathname 判断，兼容 Request 对象 |
| 10 | 前端 XSS | done | 额外：index 版本列表 `num(v.shots)`、`fmtLong(num(v.duration))`；文稿页 `seek(${num(s.start)})`；browse `lv${num(s.level)}`、`num(s.dur)`；text 先截断再转义（避免把实体截半） |
| 11 | 前端镜头 id 唯一 | done | node 实测：`[sh01,sh03,'',sh03,sel02,'../x']` → `sh01,sh03,sh04,sh05,sel02,sh06` |
| 12 | 登记册状态 | 未做 | 需要提交号，按指令不提交，由编排方提交后填写 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | 无 lint/typecheck 配置；AST 语法冒烟通过；`node --check` 校验 common.js 及 4 个页面内联脚本通过 |
| Unit Tests | Pass | 112 → 253 passed（新增 141 个），约 2s |
| Build | N/A | 未打包（`build_app.sh` 不在本次验证范围） |
| Integration | Pass | 真实起 `gui/server.py --port 18765`（临时 `AI_CUT_PROJECTS`），curl 验证：无 token 403、带 token 200、外部 Host 403、跨站 Origin 403、text/plain 415、中文项目 `/media` 200（1000 字节）、损坏 overrides POST 409 且文件仍为 `{bad`、`/static/common.js` 200、三个安全头齐全；之后已停止服务并清理临时文件 |
| Edge Cases | Pass | 空 body / `{}` / `shots: []`；类型不对（数组 body、None id、数字 id、非 dict 元素、非 UTF-8）；并发（write_json、jdump、aicut.save_json、schema.save、review 50 线程、20 并发 POST /api/shots）；无权限（无/错 token、外部 Host、错端口、跨站/`null` Origin） |
| Coverage | 未跑 | pytest-cov 未安装，按指令不安装依赖 |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `pipeline/schema.py` | UPDATED | +55 / -4 |
| `pipeline/review.py` | UPDATED | 约 +45 / -26 |
| `aicut.py` | UPDATED | +15 / -4（含删除已无用的 `import os`） |
| `gui/server.py` | UPDATED | 约 +135 / -35 |
| `gui/static/common.js` | CREATED | +31 |
| `gui/static/index.html` | UPDATED | 约 +28 / -16 |
| `gui/static/browse.html` | UPDATED | 约 +23 / -18 |
| `gui/static/confirm.html` | UPDATED | 约 +14 / -10 |
| `gui/static/calibrate.html` | UPDATED | +2 |
| `tests/conftest.py` | CREATED | +55 |
| `tests/test_server_security.py` | CREATED | 约 +250 |
| `tests/test_server_save.py` | CREATED | 约 +165 |
| `tests/test_server_media.py` | CREATED | +50 |
| `tests/test_static_pages.py` | CREATED | 约 +90 |
| `tests/test_aicut_guards.py` | CREATED | 约 +100 |
| `tests/test_schema.py` | UPDATED | +94 |
| `tests/test_review.py` | UPDATED | +70 |

## Deviations from Plan
1. **Phase 2 分支 / 拉取 / 提交 / 归档**：按用户环境规则留在 `main`，不建分支、不 pull、不 git add/commit，计划文件不移动到 `completed/`。
2. **Task 12 未做**：登记册要求填提交号，本次不提交，留给编排方提交后填写 `docs/go-live-blockers.md`。
3. **`aicut.cmd_new` 也加了项目名校验**：计划只写了 `project_dir`，但 `cmd_new` 直接用 `PROJECTS / args.name`，CLI `new ../evil` 会在项目根之外建目录，属于 GL-06 同一类问题。加了 `test_new_rejects_traversal_name`（先 RED 再 GREEN）。
4. **抽出 `aicut.check_or_die(check, value)`**：三处「schema 校验 → die」共用这一个函数，避免重复 try/except。
5. **`/api/new` 的 name 非字符串时不再 `.strip()` 崩溃**：先判断类型再交给 `check_project_name`（GL-06 范围内）。
6. **静态守卫 `(s.summary ||` 用例**：计划原文的字面量检查会误命中修复后的 `esc(s.summary ||`，改为负向后顾正则 `(?<!esc)\(s\.summary \|\|`，已用 HEAD 版本 browse.html 确认它能命中旧写法。
7. **`common.js` fetch 补丁**：用 `new URL(..., location.href)` 判断「同源且 pathname 以 `/api/` 开头」，绝对 URL 和 Request 对象也覆盖；跨源 URL 不加 token（防止 token 外泄）。

## Issues Encountered
- 测试服务 teardown 每个用例耗时 0.5s（`serve_forever` 默认轮询间隔），全量从 28s 降到 2s：fixture 里传 `poll_interval=0.01`。
- `test_project_dir_*` 最初是假绿（目录不存在本来就会 die），改为先建好同名项目 / 项目根，再确认 RED。
- 沙箱里 curl 默认走代理，`Host: evil.example` 返回了代理的 502；加 `--noproxy '*'` 后得到服务端真实的 403。

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/test_schema.py` | +39（含参数化） | write_json / save 并发、项目名 / 版本 / 镜头 id 白名单 |
| `tests/test_review.py` | +8 | 损坏检测、损坏不覆盖（set_level/set_must/clear）、50 线程无丢更新 |
| `tests/test_aicut_guards.py` | 7 | project_dir、cmd_new、cmd_build version、ensure_clips 穿越/重复、save_json 并发 |
| `tests/test_server_security.py` | 40 | GL-05 全部守卫 + GL-06 路由校验 |
| `tests/test_server_save.py` | 14 | jdump 并发、坏请求体、shots 校验、并发保存、overrides 损坏 409 |
| `tests/test_server_media.py` | 5 | 中文/空格项目 proxy、Range、preview、编码斜杠/编码 `..` |
| `tests/test_static_pages.py` | 28 | meta + common.js 顺序、esc、pick JSON、内联事件无字符串插值、无本地 escape、LLM 字段转义、renumber |

## 新发现缺陷
首轮报告列出的前三条已在「审查修复」里修掉（SchemaTooNew 返回 409、`/api/new` 的 title 类型校验、`/api/state` 非法名返回 400）。下面两条仍未修（不在范围内，建议登记）：
- `aicut.py:547`：`cmd_build` 里的 `spec["shots"]`，shots.json 缺 `shots` 键时抛 KeyError，`run_cli` 只打印 traceback，没有 `die` 的友好提示。
- `gui/static/confirm.html` 的 `renderQuestions`：磁盘上的多选答案不是数组时 `(chosen||[]).includes` 会抛错，整页问题渲染不出来。
- 规模提醒：`gui/server.py` 现在 834 行，超过 800 行的软上限。建议之后把路由处理拆到单独模块，本次没有动结构。

## Pending Manual Checks（需人工）
- [ ] pywebview 桌面壳（`uv run python app/main.py`）：新建项目 → 处理素材 → 分镜表增删改 → 生成成片，全程无 403。**重点确认 WKWebView 同源 POST 的 Origin 不是 `null`**（若是，会全部 403，见计划 Risks 第 1 条）。
- [ ] 浏览器模式（`python3 gui/server.py --open`）：同上；「浏览素材」「剪辑偏好」「确认与提问」新窗口的 API 正常。
- [ ] 浏览器模式重启服务后，旧标签页操作出现「页面已过期，请刷新」，刷新后恢复。
- [ ] 另一端口的本地 HTML 执行跨站 `fetch('http://127.0.0.1:8765/api/job', …)` 被拒，未启动任务。
- [ ] 计划「Browser Validation」中的恶意内容项目：两种模式都没有 alert，文本按原样显示；中文项目代理视频能播放、能拖动；确认页选项可勾选；浏览页 A/D/S 改档位和星标后刷新仍在。
- [ ] 分镜表：sh01–sh03 删 sh02 后新加一镜 → sh04；出片后 `work/clips/` 每个 id 一个切片。
- [ ] 手动改坏 `work/overrides.json` → 浏览页显示带路径的错误，文件未被改写。

## Next Steps
- [ ] 代码审查（`/ecc:code-review` / `/ecc:python-review`）
- [ ] 编排方提交（Task 5 与 Task 9 必须同一提交）后，在 `docs/go-live-blockers.md` 填 GL-05/06/07/18/21/23 的提交号


---

## 审查修复（code review + security review 之后，无 CRITICAL）

测试从 253 增加到 **373 passed**，没有回归，全量约 4 秒。每一项都先写测试再改代码。所有新测试先跑过、确认失败（RED）后才改实现，下面三类例外：
- `test_frontend_js.py`：测的是第一轮已经上线的前端代码，从一开始就是绿的，属于行为固化测试。
- GL-21 的编码用例：第一轮的实现本来就会拒绝这些输入，这批测试是补覆盖。
- CLI 首尾空格用例：schema 层的测试已经先 RED 过了。

### HIGH
1. **写接口不再建「幽灵目录」**：`/api/shots`、`/api/confirm/answers`、`/api/browse/level|must`、`/api/open`、POST/GET `/api/calibrate` 都改用 `existing_project`，项目不存在返回 404，名字不合法返回 400。测试逐个接口断言：返回 404、没有建出目录、`subprocess.run` 没有被调用。
2. **请求字段类型校验，请求不再断连**：
   - 新增 `schema.clean_shots`，返回新列表、不改输入。规则：in/out 必须是非负有限数（拒绝 NaN、Infinity、bool、非数字），而且出点要晚于入点；sub/note 只能是字符串或空。`/api/shots` 用它做校验，错误用中文返回 400。**这关闭了 KI-31 的数值部分**。
   - 新增 `schema.check_title`：片名不能为空，不能含 `/`、`\\` 或控制字符，长度沿用项目名的上限（100 字 / 255 字节），错误文案放在 `TITLE_ERROR`。`/api/new` 在渲染之前就校验片名；material 也必须是非空字符串。
   - `do_GET` / `do_POST` 外面统一包了一层 `_safely`：意外异常把 traceback 打到 stderr，返回 500 JSON（文案在 `INTERNAL_ERROR_MSG`）；如果响应已经开始写，就只断开连接。连接类错误（断管、对端重置、超时）静默关闭。
   - 新增 `schema.ensure_supported`，`migrate` 和 `project_state` 共用。`/api/state`、GET/POST `/api/calibrate` 遇到版本过新的项目返回 409，文件不动；`/api/state` 遇到非法名返回 400。
   - 这一项关闭 KI-31（数值部分）、KI-45、KI-46、KI-47。

### MEDIUM
3. 版本号正则改成 `v[0-9]{1,4}`，`v٣`、`v１` 都会被拒绝。镜头 id 的正则本来就是显式写的 ASCII 字符类，不受影响。
4. 请求体处理：
   - 缺少 Content-Length 返回 411。
   - 负数、非整数（包括 `1e3`）或非 ASCII 数字返回 400。
   - 超过 `MAX_BODY_BYTES`（2 MB）返回 413，而且不读请求体。
   - `Handler.timeout = REQUEST_TIMEOUT_S`（60 秒）。
5. 所有 HTML 响应都加了 `PAGE_CSP`，内容和审查给的一致。先 grep 过四个页面：没有任何外部字体、CDN 或 data: 资源，内联脚本、样式和内联事件靠 `'unsafe-inline'` 保留。
6. `/media`：先 `resolve(strict=True)`，要求结果是项目目录内的普通文件；符号链接逃逸、目录、不存在的文件一律返回 404。
7. 项目名：在 100 字之外再加 `PROJECT_NAME_MAX_BYTES = 255`（按 UTF-8 字节算），首尾有空白（包括全角空格和 tab）直接拒绝，CLI 和服务端都生效。`PROJECT_NAME_ERROR` 文案同步改为「项目名不能以 - 或 . 开头，首尾不能有空格，不能含斜杠或控制字符，最长 100 字（255 字节）」。服务端 `/api/new` 不再偷偷 strip 项目名；前端本来就会 trim，不受影响。
8. 测试收紧：
   - `test_same_origin_post_allowed` 改为断言 200。
   - `test_bad_project_query_is_rejected_not_crash` 改为断言 400（并加了 `/api/state?project=-h`）。
   - `test_new_uses_equals_form` 改用 conftest 里的 `preset_dir` 夹具（预设名「测试预设」），并用以 `-` 开头的 material 和 title 证明 `--x=value` 写法有效。
   - `test_server_media.py` 增加 `%2F`、`%2e%2e`、`%2E%2E`、`%5C`、`%00`、`%2d%2dhelp`、`%20p1`，以及 version 段的编码用例，另有符号链接逃逸和目录两条。
   - 新增 `tests/test_frontend_js.py`：在 node vm 里真正执行 `common.js`，覆盖 esc、num、fetch 补丁（同源 /api 带 token，/media、/static、外站不带），以及从 index.html 抽出来的 `nextShotId` / `renumber`；没有 node 时整文件 skip。

### 新增 / 修改文件（审查修复部分）
- 修改：`pipeline/schema.py`、`gui/server.py`、`tests/conftest.py`（新增 `preset_dir`）、`tests/test_schema.py`、`tests/test_server_security.py`、`tests/test_server_media.py`、`tests/test_aicut_guards.py`。
- 新建：`tests/test_server_hardening.py`（43 个用例）、`tests/test_frontend_js.py`（20 个用例）。

### 额外验证：真实浏览器
起了真实服务（临时目录，项目名「九月 一号」，所有文本字段都塞了 `<img onerror>` / `');alert(1)//` 这类内容），用 Chrome DevTools 依次打开四个页面，结果：
- **index**：项目列表、文稿、分镜、废片、版本、预览六个视图都渲染过，页面上没有出现任何 `<img>` 元素，也没有 alert；带 token 保存分镜返回 200。
- **browse**：内联事件只有 `jumpSeg(0)` 和 `jump(0, null, 4)`（字符串类型的 `at` 被 `num()` 转成了 0）；星标点击后服务端已经保存。
- **confirm**：选项的点击事件是 `pick(0,0)`，能选中，恶意文本原样保存。
- **calibrate**：POST 返回 200。

四个页面的控制台都**没有 CSP 拦截**。看到的只有三类：缺少代理视频导致的 404、浏览页 `play()` 被拒绝（同样因为没有视频）、表单无障碍提示。测试结束后已经停掉服务、关闭页面、删除临时目录。

### 仍未做（按协调方要求，留给 KI 登记）
- 前端保存顺序（L3）
- project.json 读改写加锁 + fsync
- prototype.html 被当作静态文件对外提供
