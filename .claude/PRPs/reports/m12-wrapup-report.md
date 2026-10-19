# Implementation Report: M12 收尾（KI-80 / KI-88 / KI-89）

## Summary
- **KI-80**：`to_jianying.main()` 把 `--staging` 转成绝对路径（`os.path.abspath`，不解析符号链接），`bundle_media` 对 `final_dir` 兜底绝对化。相对 staging 的 dry-run 不再 FAIL。
- **KI-88**：新增 `gui/session.py`。页面不再含任何凭证；入口地址 `/?nonce=…`（一次性、5 分钟、内存）兑换为 `aicut_session_<port>` 会话 cookie（`Path=/; HttpOnly; SameSite=Strict`），302 回去掉 nonce 的地址。页面、`/api/*`、`/media/*` 只认 cookie；无凭证页面得到 403「请从剪辑台 App 打开」。`X-AICUT-Token` 整条删除；子窗口由 `/api/window` 各发一个 nonce；桌面壳 `webview.start(private_mode=False)`；浏览器模式 `--open` 打开 nonce 地址，不带 `--open` 时终端打印一次性链接。
- **KI-89**：切片命名 `work/clips/<id>-<clip_key>.mp4`，时间线指向带键文件；`manifest.json` 只读（旧缓存键一致 → 硬链接/复制复用，不重切）；补切写到时间线里的路径（旧命名补切时同步 manifest 键）；出片后 `prune_unreferenced` 删除不被任何版本引用的切片（任一时间线读不出则不删）。切片逻辑从 `aicut.ensure_clips` 下沉到 `pipeline/clips.ensure`。

## Assessment vs Reality
| 项 | 计划 | 实际 |
|---|---|---|
| 复杂度 | Medium | Medium（28 个已改文件 + 3 个新文件） |
| 行数约束 | < 800 | `aicut.py` 750（原 766）、`gui/server.py` 638（原 617） |

## Tasks Completed
1. KI-80 回归测试（2 个，先红）→ 修复 → 绿
2. `gui/session.py` 单测（7 个，先红：ImportError）→ 实现 → 绿
3. 服务端接线集成测试（9 个，先红）→ 实现；`conftest.call` 改发 cookie；更新 security / hardening / media 测试
4. 桌面壳 / 子窗口测试先改（红）→ `desktop.py`、`app/main.py` 实现 → 绿
5. 前端：`common.js` 改为显式 `credentials:'same-origin'`，4 个页面删 token meta（对应测试先改为红）
6. KI-89 测试（10 个，先红：v1 与 v2 指向同一个 `S01.mp4`）→ 实现 → 绿；旧命名断言的 2 个测试按新命名更新
7. 文档：`docs/GUI.md` 安全模型改写；`known-issues.md` 新登记 KI-90；`PROGRESS.md`、`README.md`；`packaging/ai-cut.spec` 加 `gui.session`；PRD 第 12 行挂 plan 链接
8. 自审修复：`restore_missing` 只认 `work/clips` 下的 `.mp4`（防止被篡改的时间线借补切覆盖 `manifest.json`），加回归测试

## Validation Results
| 层 | 结果 |
|---|---|
| Lint / 类型检查 | 未配置（CLAUDE.md） |
| `uv run pytest` | **1788 passed**（基线 1756，新增 32 个，0 失败） |
| `uv run pytest --cov` | **93.96%**（门槛 80%）；`gui/session.py` 100%，`pipeline/clips.py` 98% |
| 结构守卫 | `tests/test_structure.py` 通过（行数、spec hiddenimports） |
| 实机冒烟（curl） | 隔离数据目录、端口 61030：无 cookie `GET /` → 403 gate 页；`/api/projects`、`/media/p1/proxy` 无 cookie → 403；旧 `X-AICUT-Token` 头 → 403；`/?nonce=` → 302 `Location: /` + 正确 `Set-Cookie`、`no-store`；重放 nonce → 403；带 cookie 页面 200 且不含秘密；API 200、media Range 206；`/api/window` 200；错 Host → 403；跨站 Origin POST → 403；服务重启后旧 cookie → 403；`curl -L` 一次走完 nonce 入口 → 200 |
| 实机冒烟（Chrome DevTools） | 打开 nonce 地址后地址栏为 `/`；`document.cookie` 为空（HttpOnly）；页面无 token meta；fetch `/api/projects` 200、`/media/p1/proxy` 206、`/api/window` 200；子页面带 cookie 200、`credentials:'omit'` 403 |
| 服务已停止 | 是 |

## Files Changed
- 新增：`gui/session.py`、`tests/test_m12_wrapup.py`、`.claude/PRPs/plans/m12-wrapup.plan.md`、本报告
- 产品代码：`gui/server.py`、`gui/desktop.py`、`app/main.py`、`gui/static/common.js`、`gui/static/{index,browse,confirm,calibrate}.html`、`pipeline/clips.py`、`pipeline/timeline.py`、`pipeline/to_jianying.py`、`aicut.py`、`packaging/ai-cut.spec`
- 测试：`tests/conftest.py`、`test_server_security.py`、`test_server_hardening.py`、`test_server_media.py`、`test_server_desktop.py`、`test_app_main.py`、`test_frontend_js.py`、`test_static_pages.py`、`test_aicut_build.py`、`test_m8_followup.py`
- 文档：`docs/GUI.md`、`docs/known-issues.md`（KI-90）、`docs/PROGRESS.md`、`README.md`、`.claude/prds/ai-cut-go-live.prd.md`

## Deviations from Plan
- 未改 `CHANGELOG.md`：现有 CHANGELOG 只有 0.1.0 升级须知，本次变化对剪辑师无操作要求，不加噪音。
- 自审新增的 `.mp4` 后缀限制是先修后补测试（非严格先红）。
- KI-80/88/89 状态列未回填（D12：提交后回填提交号）。

## Issues Encountered
- pywebview 6.2.1 cocoa 在 `private_mode=True` 时每建窗口都清空共享 `defaultDataStore`，会把主窗口 cookie 清掉 → 改 `private_mode=False`（D8）。
- 本机 `http_proxy` 使带伪造 Host 的 curl 走了代理（502），用 `--noproxy '*'` 复验为 403，非产品问题。

## Tests Written
`tests/test_m12_wrapup.py`（32 个）：KI-80 ×2、session ×7、服务端接线 ×9、KI-89 ×14（含旧缓存复用 / 复制退回 / 复用失败重切 / 补切路径 / manifest 一致 / 清理保守性 / 非切片路径不写）。

## 待实机确认
- [ ] 打包 App：主窗口经 302 拿到 `SameSite=Strict` cookie 后正常加载（WKWebView 行为无法在测试里验证；回退方案：200 + `Refresh` 头）。
- [ ] App 内开「浏览素材」等子窗口：代理片能播放，主窗口仍可操作（`private_mode=False` 生效）。
- [ ] 双击「启动剪辑台.command」：默认浏览器打开并跳回 `/`。
- [ ] 旧项目升级后第一次「生成成片」：旧切片被硬链接复用、不全量重切；旧版本仍能导出 Windows 包。

## 安全复审跟进（无 CRITICAL/HIGH；以下 3 项已修，均先写失败测试）
1. **MEDIUM 并发出片误删切片**：`pipeline/project_lock.build_section(pdir, blocking=True)`，用独立的 `.aicut-build.lock` 加 `LOCK_EX`。`cmd_build` 里「切片 → 写时间线 / 快照 → `prune_unreferenced`」整段在这把锁内，同项目出片串行。另外 `prune_unreferenced` 跳过一小时内修改过的文件（`PRUNE_MIN_AGE_S = 3600`，`now` 可注入）。测试：锁互斥、`cmd_build` 事件顺序为 `lock → cut → prune → unlock`、新写的未引用切片保留，改旧后才删。
2. **LOW `--open` 打不开浏览器**：新增 `server.open_browser(url)`。`webbrowser.open` 返回 False 时打印一次性链接。测试覆盖 False 和 True 两种情况。
3. **LOW 补切内容可能和当初不一致**：`restore_missing` 补切带键文件前，先校验 `clip_name(shot, 当前素材) == dst.name`。不一致就在切任何一镜之前抛 `ClipsUnavailable`（`KEY_MISMATCH`），提示重新生成这一版。旧命名 `<id>.mp4` 不受这条校验限制，行为与以前一致。测试：换素材后补切直接拒绝，ffmpeg 不被调用。
- 会话轮换 / 登出未做，按协调方要求由对方登记。
- 既有测试 2 个改为先把文件改旧再断言清理。

**复审后验证**：`uv run pytest` **1793 passed**；`--cov` **93.96%**；`aicut.py` 750 行，`gui/server.py` 646 行。
改动文件：`pipeline/project_lock.py`、`pipeline/clips.py`、`aicut.py`、`gui/server.py`、`tests/test_m12_wrapup.py`（共 37 个测试）。
