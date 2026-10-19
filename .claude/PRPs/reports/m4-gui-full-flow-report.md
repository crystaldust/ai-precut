# Implementation Report: M4 · GUI 独立完成全流程（GL-02 / GL-14 / GL-16 / GL-17 / GL-20 / GL-22）

## Summary
剪辑师可以只在剪辑台里完成以下全部事情：
- 首次打开先看数据外发说明。
- 在「⚙ 设置 · API Key」填 Key。
- 处理素材，缺告知或缺 Key 时被拦截并引导去补。
- 生成成片，导出 Windows 剪映包（带「在访达中显示」）。

任务行为：
- 全部任务一律走子进程。打包版是 App 带 `--aicut-cli` / `--aicut-module` 重启自己。
- 全局互斥，可以取消，取消时连同 ffmpeg 一起停。
- 失败或取消后，弹窗可以重试、可以关闭。

ASR 续查状态绑定音频指纹和 backend，终态失败时清除。新建项目不再卡死，留下的空目录可以复用。字幕框可以正常输入。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Files Changed | 19（改 10 + 新建 9） | 32（改 17 + 新建 15，含测试 / 文档 / spec） |
| Tests | 基线 112（计划写于 M1 前） | 基线 638 → 755 passed（+117） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 0 | 测试 harness | done | M1 已有 `gui_server`/`call`/`make_project`，未建第二套。新增 autouse `_isolate_secrets`（`AI_CUT_SECRETS=file` + 临时 `AI_CUT_CONFIG_DIR` + 清 env Key / `LEGACY_FILES`）、`no_keys`、收尾 `_stop_jobs` |
| 1 | `proc.cli_cmd/module_cmd/dispatch` + `app/main.py` 先分发 | done | dispatch 复用 M3 的 `proc.exit_code`；缺模块名返回 2；`sys.argv` 恢复 |
| 2 | export_draft 走 `proc.module_cmd` | done | 另加 `stdin=DEVNULL` |
| 3 | 任务执行重写（GL-17） | done | 偏差：抽到新模块 `gui/jobs.py`（见下） |
| 4 | 新建项目（GL-20） | done | 偏差：空目录才复用，非空目录拒绝 |
| 5 | `asr_state` + cloud（GL-16） | done | 偏差：状态写失败不致命 |
| 6 | consent + secrets 元数据 | done | 原子写复用 M1 的 `schema.write_json` |
| 7 | Key / 告知端点 + prepare 前置拦截 | done | 偏差：抽到 `gui/settings.py`；已转写项目不再要求火山 Key |
| 8 | CLI prepare 缺 Key 直接失败 | done | 与 GUI 共用 `pipeline/readiness.py` |
| 9 | Windows 导出任务 + 版本状态 + 在访达中显示 | done | 参数一律 `--x=value`；片名清洗并截断 |
| 10 | 任务弹窗（取消 / 重试 / 关闭 / 冲突 / 重连）+ `pick()` 不重绘 | done | 偏差：搬到 `gui/static/jobs.js` |
| 11 | 设置弹窗 + 首次打开告知 | done | `gui/static/settings.js`；旧版 `~/.mediakit/api_key` 来源只读 |
| 12 | 版本卡片 Windows 导出入口 | done | onclick 只传版本下标，不拼版本名 |
| 13 | 文档 | done（部分） | 更新了 `docs/GUI.md`；按指示未改 go-live-blockers / known-issues 的状态 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | pass | 未配置 lint / typecheck。`py_compile` 全部通过；`node --check` 覆盖 jobs.js、settings.js、index 内联脚本，以及三者拼接（防跨文件 const 重复声明） |
| Unit Tests | pass | `uv run pytest`：755 passed（基线 638） |
| Build | 待人工 | 未打包（见待人工验证） |
| Integration | pass | 真实 `gui/server.py`（端口 8911，项目 / 配置目录全部隔离到 scratchpad）curl 冒烟，已停服务。结果见下表 |
| Edge Cases | pass | 坏 Key、坏版本、非字符串 task、超长片名、孙进程忽略 SIGTERM，均有测试 |

curl 冒烟结果：

| 项目 | 结果 |
|---|---|
| `/api/config` | 只返回掩码 |
| `jobs.js` / `settings.js` | 200 |
| `new` | 秒回，空目录可复用 |
| prepare | 先 409 consent，再 409 keys（只缺 deepseek） |
| export 无时间线 | 400 |
| 未知任务 | 400 |
| 真 prepare | 失败后状态为 failed，并带退出码 |
| 并发第二个任务 | 409，带 job_id |

## Files Changed

| File | Action |
|---|---|
| `gui/jobs.py` | CREATED（任务表、子进程、互斥、取消、短命令、Windows 导出参数） |
| `gui/settings.py` | CREATED（`/api/config*`、`PrepareBlocked`） |
| `gui/static/jobs.js` | CREATED（任务弹窗、版本卡导出入口，文案常量） |
| `gui/static/settings.js` | CREATED（设置、外发告知、首次打开检查，文案常量） |
| `pipeline/asr_state.py` | CREATED |
| `pipeline/consent.py` | CREATED |
| `pipeline/readiness.py` | CREATED |
| `gui/server.py` | UPDATED（849 → 766 行；移走任务执行，新增路由） |
| `gui/static/index.html` | UPDATED（639 → 617 行） |
| `aicut.py` | UPDATED（902 → 912 行；`new --no-input`、prepare 前置检查） |
| `app/main.py` | UPDATED |
| `pipeline/proc.py` | UPDATED |
| `pipeline/export_draft.py` | UPDATED |
| `pipeline/cloud.py` | UPDATED |
| `pipeline/secrets.py` | UPDATED |
| `packaging/ai-cut.spec` | UPDATED（hiddenimports 增加新模块） |
| `docs/GUI.md` | UPDATED |
| tests | 新建 `test_aicut_cli` / `test_asr_state` / `test_consent` / `test_frontend_jobs` / `test_server_config` / `test_server_export` / `test_server_jobs`；修改 `conftest` / `test_proc` / `test_cloud` / `test_export_draft` / `test_server_security` / `test_static_pages` |

## Deviations from Plan

1. **任务执行搬进 `gui/jobs.py`，设置路由搬进 `gui/settings.py`。** server.py 原本超过 800 行软上限（KI-54），这样处理后降到 766 行。server 仍再导出 `start_job` / `run_aicut` / `JOBS` / `JOB_COMMANDS`，保持既有测试的打桩点。
2. **prepare 的前置检查放在 `/api/job` 路由里，不放在 `start_job` 里。** 原因是检查需要项目目录。检查仍在登记任务之前做，所以不会留下幽灵任务。
3. **`/api/state` 的 `job` 字段返回 `{id, task}`，不是只返回 id。** 前端重新挂回进度弹窗时需要知道任务名，标题和「重试」才正确。
4. **就绪判断共用 `pipeline/readiness.py`。** 已有 `work/transcript_raw.json` 的项目只要求 DeepSeek Key，与 CLI 跳过转写的条件一致。计划原本是 GUI 一律要求两个 Key。DeepSeek Key 始终必需，不提供跳过选项（按产品决定）。
5. **`aicut new` 只复用空目录。** 非空且没有 `project.json` 的目录直接拒绝，避免占用用户的文件夹。只有本次新建的目录才会在失败时删除。
6. **`asr_state.save` 写失败只打 `[!]` 警告，不中断转写。** 这次转写照常进行，只是失去续查能力。读状态时，非有限数、bool 型的 `at` 和损坏的 JSON 一律判为作废。
7. **前端拆出 `jobs.js` 和 `settings.js`，放在内联脚本之前加载。** 原先在 index.html 的 `JOB_TITLES` 等常量随之迁移。`test_static_pages` 中两个按源码位置锚定的守卫测试改为读 `jobs.js`，断言内容不变。
8. **`/api/new` 的参数多了 `--no-input`（放在项目名后）。** `test_server_security::test_new_uses_equals_form` 的期望 argv 同步更新。
9. **`test_cloud::test_transcribe_resumes_from_saved_task` 改为用新格式状态文件。** 旧格式现在按设计作废并重新提交，另有新测试覆盖这一点。
10. **采纳代码审查（无 CRITICAL / HIGH）的 MEDIUM / LOW 意见：**
    - 宽限期 SIGKILL 改为以「任务仍在 running」为准。之前 aicut 已退出但 ffmpeg 不理 SIGTERM 时，会一直占住全局互斥。
    - 已被 wait() 回收的子进程不再发信号。
    - 重复点取消只发一次信号。
    - 非字符串 task 返回 400，不再是 500。
    - zip 名里的片名截断到 60 字。
    - 凭证隔离改为全局 autouse。
11. **TDD 偏差：** `export_args` / `windows_zip` 先于 `test_server_export.py` 写完（那批测试首次运行时大部分已绿）；`jobs.js` / `settings.js` 也先于其测试写完。`pick()` 的测试、CLI、consent、asr_state、jobs、config 的测试都先确认了 RED。

## Issues Encountered
- 真机冒烟发现，`settings.js` 对来自旧版 `~/.mediakit/api_key` 的 Key 也显示「清除」，但 `secrets.delete` 删不掉那个文件。已改为只读提示，并补了测试。
- KI-15：开发模式下的 `module_cmd` 仍以脚本方式运行 `pipeline/to_jianying.py`，与改动前行为一致。在 Homebrew Python 3.14 下仍可能触发 KI-15。本次未修，设计上也不依赖它。

## 新发现缺陷（未修，需登记）
- `aicut.py:222`（`cmd_ingest`）：素材无法被 ffprobe 识别时抛 `KeyError: 'format'`，用户看到的是 traceback 而不是中文报错。真机冒烟中复现。
- `pipeline/secrets.py:88-94`（`mask`）：长度大于 8 就显示前 4 后 4 位，9–12 位的 Key 几乎全部暴露。新端点允许 8 位以上的 Key（审查 MEDIUM 3）。
- `gui/jobs.py:44` 附近（`JOBS` 与每个任务的 `log`）：从不裁剪。长时间使用或 ffmpeg 日志很多时内存无界增长。原逻辑也是如此，计划写明不做任务历史。
- `aicut.py` `cmd_new`：「检查为空」与 `mkdir(exist_ok=True)` 之间有一个很小的竞争窗口。GUI 侧有全局互斥，影响很低。

## Tests Written

| Test File | Tests | Area |
|---|---|---|
| `tests/test_server_jobs.py` | 21 | 互斥 409、取消（进程组 + 孙进程忽略 SIGTERM）、失败状态、启动失败、state.job、Popen 参数、冻结命令、`/api/new --no-input`、`run_aicut` 冻结 / 超时 |
| `tests/test_server_config.py` | 19 | Key 存取只回掩码、坏 Key、钥匙串失败 500 不回显、清除、env 来源、prepare 409 consent → keys → 200、Key 不进项目 / 日志 / state |
| `tests/test_server_export.py` | 16 | export 参数、坏版本、无时间线、片名清洗 / 截断、state 中的 windows_zip、在访达中显示 |
| `tests/test_frontend_jobs.py` | 18 | `pick()` 不重绘、弹窗按钮、409 分流、版本卡注入防护、设置页转义 / env / legacy、首次打开告知、明文不进 toast、脚本加载顺序 |
| `tests/test_asr_state.py` | 12 | 指纹、backend、过期、损坏 / 旧格式、音频缺失 |
| `tests/test_aicut_cli.py` | 9 | `new --no-input`、空目录复用、非空拒绝、失败清理；prepare 缺 Key 前置失败、已转写只要 DeepSeek |
| `tests/test_consent.py` | 5 | accept / 版本变化 / 损坏 |
| `tests/test_proc.py` | +10 | `cli_cmd` / `module_cmd` / `dispatch`、入口先分发 |
| `tests/test_cloud.py` | +6 | 终态失败清状态、超时 / 网络保留、换音频重提、旧格式重提 |
| `tests/test_export_draft.py` | +2 | 冻结 / 开发两种命令构造 |

## 待人工验证
- 打包：`./packaging/build_app.sh`，然后：
  - `"dist/AI粗剪.app/Contents/MacOS/ai-cut" --aicut-cli list`：应即时返回，不弹窗，Dock 上不多出图标。
  - `"dist/AI粗剪.app/Contents/MacOS/ai-cut" --aicut-module pipeline.to_jianying --help`：应打印 argparse 帮助。
  - 打包版跑完整流程。
- 计划 Manual Validation 第 1–14 项（浏览器 / 桌面壳）：
  - 字幕框连续输入。
  - 取消后 `ps aux | grep ffmpeg` 无残留。
  - 失败后弹窗可关闭。
  - 冲突时可「查看进行中的任务」。
  - 切项目后能重新挂回进度弹窗。
  - 杀掉服务后显示「连接中断」。
  - 首次打开出现外发告知。
  - Keychain 首次写入时的系统授权框。
  - env Key 只读提示。
  - CLI prepare 缺 Key 时报错。
  - 导出 Windows 包，并在访达中显示。
- Windows 实机：把 zip 拷过去，双击 `INSTALL.bat`，剪映能打开并播放。
- 用 `.command` 启动时新建项目秒回。
- ASR 失败后重新提交、换素材后重新提交（会产生真实云端调用，测试中未做）。
- 计划需要的 `docs/go-live-blockers.md` 状态 / 提交号回填：按本轮指示未改，由提交时处理。

## 审查修复（第 2 轮：代码审查 + 安全审查，0 CRITICAL / 2 HIGH）

所有修复都先写测试并确认失败，再改实现。全量 `uv run pytest`：755 → **810 passed**。`tests/test_server_jobs.py` + `tests/test_proc.py` 连跑 3 次都稳定，测试后没有残留进程，`~/.config/ai-cut` 也没有被写入。

| # | 级别 | 问题 | 修复 | 主要测试 |
|---|---|---|---|---|
| 1 | HIGH | 关窗口、服务退出 / 崩溃或 Ctrl+C 后，aicut / ffmpeg 变成孤儿进程，继续运行并计费；重启后的互斥看不到它 | 见表后「HIGH-1 的四层防护」 | `test_shutdown_all_*`、`test_parent_watchdog_kills_own_group_when_parent_dies`（真实「父进程退出 → 子进程和孙进程都退出」）、`test_stale_job_*`、`test_marker_*` |
| 2 | HIGH | 设置页死循环：409 缺 Key 时点「完成」，会重新起任务 → 409 → 再弹设置，没有出口 | 见表后「HIGH-2 的改动」 | node 测试：缺 Key 时点「完成」后遮罩关闭，且不会再起任务；Key 齐时点「完成」只重试一次；「关闭」按钮；`modalDismissable` |
| 3 | MEDIUM | 鉴权失败、缺 mediakit-cli、返回不是 JSON 时也会清掉 ASR 续查状态 | 新增 `CloudError.terminal`，只在 `wait_task` 收到云端终态（failed / error / canceled / cancelled）时设置；`transcribe` 只在 `terminal` 时清除状态 | 3 个保留状态的用例，加终态标记的参数化用例 |
| 4 | MEDIUM | 「查看进行中的任务」之后点「重试」，会重跑一个用户没看到参数的任务 | `attachJob` / `attachRunningJob` 把 `jobUi.last` 置空；任务结束后只显示「关闭」。409 响应体增加 `task` / `project` | `test_attach_*`、`test_conflict_body_names_running_task_and_project` |
| 5 | MEDIUM | 命令行不检查是否已确认外发说明 | 见表后「MEDIUM-5 的改动」 | `test_*_requires_consent`、`test_config_consent_prints_notice_and_records` |
| 6 | MEDIUM | 打包版冒烟 | 已完成，见下方「打包版冒烟」 | — |
| 7 | LOW | 非字符串片名会让 `/api/state` 返回 500；双向 / 零宽字符可以伪装文件名 | `windows_zip` 遇到非字符串或空片名时改用项目名；`_UNSAFE_FILENAME` 增加过滤 U+200B–U+200F、U+202A–U+202E、U+2066–U+2069 和 0x7f | `test_non_string_title_never_500`、`test_bidi_and_zero_width_chars_stripped` |
| 8 | LOW | 异常分支不回收子进程；线程起不来时任务残留 | 见表后「LOW-8 的改动」 | `test_reader_exception_reaps_child_and_fails_job`、`test_thread_start_failure_unregisters_job`、`test_error_right_after_popen_fails_job_instead_of_hanging` |
| 9 | LOW | `--aicut-module` 可以运行任意模块 | `proc.ALLOWED_MODULES = {"pipeline.to_jianying"}`；`dispatch` 遇到白名单外的模块返回 2，`module_cmd` 直接抛 `ValueError` | `test_dispatch_rejects_module_outside_allowlist`、`test_module_cmd_rejects_module_outside_allowlist` |
| 10 | LOW | 凭证临时文件先以默认权限创建、名字固定；清除操作不核实是否真的删掉 | `_write_file` 改用 `os.open(O_CREAT\|O_EXCL, 0o600)` 加随机文件名，失败不留残渣；`delete()` 删除后核实钥匙串和文件里确实没有了，否则抛 `SecretDeleteError` → `/api/config/key/delete` 返回 500「清除失败：…」 | `test_cred_temp_file_created_0600_with_unique_name`、`test_delete_raises_when_keychain_still_has_key`、`test_delete_failure_is_500_with_clear_message` |
| 11 | LOW | 保存 Key 失败也会清空输入框 | 保存成功后才清空 | `test_save_key_failure_keeps_input` |
| 12 | LOW | 测试收尾时没有等任务线程退出 | `_stop_jobs` 先 join 任务线程再清表（任务记录里保存 `thread`）；补了「取消请求早于 Popen 返回」的竞争用例 | `test_stop_jobs_helper_joins_threads`、`test_cancel_before_popen_still_stops_job` |
| 13 | LOW | 轮询出错被报成「启动失败」 | `startJob` 改用 `then(ok, err)`；轮询抛错时显示「连接中断」 | `test_poll_error_not_reported_as_start_failure` |

#9 和 #10 还有两点补充：
- #9：`test_proc` 里两个用临时假模块的 dispatch 用例，改为 monkeypatch `ALLOWED_MODULES`。
- #10：这次修掉的是 **KI-28 中「凭证文件创建时权限」那一部分**；`failed.json` 脱敏不在本次范围。

### HIGH-1 的四层防护
1. **退出时主动停任务**：新增 `jobs.shutdown_all()`，做法是 SIGTERM → 宽限期 → 对进程组里还活着的进程（含孙进程）SIGKILL → 回收。调用位置有三处：
   - 用 `atexit` 注册；
   - `app/main.py` 的 `finally`；
   - `gui/server.py main()` 的 `finally`，并把 SIGTERM / SIGHUP 转成 `sys.exit`，关终端窗口时也会走到 `finally`。
2. **剪辑台被强杀时子进程自行退出**：任务的环境变量里带 `AI_CUT_PARENT_PID`。
   - 看门狗 `proc.start_parent_watchdog()` 在两处启动：`proc.dispatch`（打包版）和 `aicut.py` 的 `__main__`（开发版）。
   - 这个环境变量读取后立即删除，aicut 再拉起的 `--aicut-module` 子进程不会误判。
   - 看门狗在子线程里，没法设置信号处理函数，所以分两步：先用 `pgrep -g` 找到同组的其它进程逐个发 SIGTERM，宽限期后对整组（含自己）SIGKILL。
3. **跨重启 / 跨实例的任务记录**：运行中的任务写在配置目录的 `job.marker`。
   - 起新任务前，如果记录里的 pid 还活着，并且命令行里带 aicut 字样（防 pid 被复用），返回 409，提示「上次剪辑台退出时留下的任务还在后台运行…（进程 N）」。
   - 记录失效时自动清掉。
   - 服务启动时也会把这条提示打印到终端（`report_stale_job()`）。
4. **测试**：`_isolate_secrets` 已把配置目录隔离到临时目录，所以 `job.marker` 不会落到真实的 `~/.config`。

### HIGH-2 的改动
- `openSettings(then, required)`：`required` 取自 409 响应里的 `missing`。
- 「完成」：这次需要的 Key 都齐了才继续执行 `then`，否则只关闭并提示「还缺 Key」。
- 新增「关闭」按钮：只关闭，丢弃 `then`。
- 所有弹窗都支持 Esc / 点遮罩空白处关闭；任务运行中（正在轮询进度）除外，取消必须明确点「取消任务」。
- 确认外发说明后直接执行 `then`，由服务端判断还缺哪个 Key，不再提前弹出全部 Key。

### MEDIUM-5 的改动
- 告知文案和记录集中在 `pipeline/consent.py`（`NOTICE_LINES`、`CLI_REQUIRED_MSG`），剪辑台和命令行共用同一份确认记录。
- `aicut.require_consent()` 放在每一处外发之前：
  - transcribe：只在需要调 ASR 时检查；
  - text、summary、questions（跳过不生成时不检查）；
  - prepare：一开始就检查，先于缺 Key 检查。
- 新增命令 `aicut config consent`：打印告知并记录确认。
- 走到 LLM 的旧用例 `tests/test_aicut_must_keep.py` 加了模块级 `pytestmark = usefixtures("consented")`。
- 新 fixture：`consented`（conftest）。

### LOW-8 的改动
- 任务记录里保存 `thread`；线程起不来时撤销登记、释放互斥。
- 从 Popen 之后到读完日志，整段都在异常保护里。出异常时先终止进程组、关闭管道，再等待回收子进程（`wait(timeout)`），最后把任务标为 failed。

### 打包版冒烟
条件确认：`vendor/bin/ffmpeg` 存在，PyInstaller 6.22.3 在 dev 环境里，没有下载任何东西。

构建命令：`uv run pyinstaller packaging/ai-cut.spec --distpath <scratchpad>/dist --workpath <scratchpad>/build --noconfirm`，退出码 0。

运行 `AI粗剪.app/Contents/MacOS/ai-cut`（项目 / 配置 / 草稿目录都隔离到 scratchpad）：

| 命令 | 退出码 | 耗时 | 输出 |
|---|---|---|---|
| `--aicut-cli list` | 0 | ≈0.1s | 无项目时为空；建项目后打印 `f1 … 纪实3min []` |
| `--aicut-module pipeline.to_jianying --help` | 0 | ≈0.1s | 打印 argparse 帮助 |
| `--aicut-module os` | 2 | ≈0.1s | 打印白名单用法提示 |
| `--aicut-cli new f1 --no-input …` | 0 | — | 项目已创建 |
| `--aicut-cli prepare f1`（未确认外发说明） | 1 | — | 打印外发说明提示 |

- 每条命令都在约 0.1s 内退出，没有残留的 App 进程，所以没有打开窗口。Dock 上是否闪出图标无法在无头环境里观察，留给人工确认。
- 注意：一开始用 `perl -e 'alarm 30; exec …'` 包着运行时，三条命令都卡满 30s 后被 SIGALRM 杀掉，没有任何输出。直接运行则都在 0.1s 内正常退出，所以这是那个包装方式的问题，不是 App 的问题。
- 未完成：按要求删除 scratchpad 里的构建产物时，GateGuard 两次拦下删除命令（已给出事实说明，并原样重试过）。没有绕过它，产物还在：`/private/tmp/claude-501/-Users-developer-Documents-deepseek-harness-default-workspace/6616b588-1b33-4f4c-99b5-1726d4d66e60/scratchpad/`（`dist`、`build`、`frozen`、`smoke`、`pyi.log`），需要人工删除。
- 仓库里的 `build/ai-cut` 是更早的构建（10-19 00:45），已被 gitignore，不是这次产生的。

### 其它
- **工作区里有两处改动不是我做的**：`docs/known-issues.md` 和 `.claude/prds/ai-cut-go-live.prd.md` 显示为已修改，我没有动过（推测是协调方在登记）。
- **审查测试顺带发现并修掉的问题**：Popen 之后、读日志之前如果抛异常（例如写任务记录失败），线程会直接死掉，任务永远停在 running 并占住互斥。现在这一段都在异常保护里，任务会转为 failed。另外，`tests/test_server_target.py` 里的 FakePopen 补上了 `pid` / `returncode`，跟真 Popen 保持一致。
- **文件行数**：`gui/server.py` 784 行，`aicut.py` 931 行（KI-55 仍超上限），`gui/jobs.py` 387 行。
- **按指示未做的**：L-5（掩码处理第三方报错里可能带出的 Key）由协调方登记。

### 新发现缺陷（第 2 轮，未修）
- `gui/server.py`：`/api/state` 在每次请求里调用 `jobs.project_job()`，但跨实例的 `job.marker` 只在起任务时检查，界面不会主动显示「上次留下的任务还在跑」，只在点按钮时出现 409 提示。属于体验问题，未改。
- `pipeline/proc.py` 看门狗依赖系统的 `pgrep`（macOS 自带）。`pgrep` 不可用时会跳过 SIGTERM 这一步，直接在宽限期后对整组发 SIGKILL。功能上仍然不会留孤儿，只是失去了「先体面退出」。
