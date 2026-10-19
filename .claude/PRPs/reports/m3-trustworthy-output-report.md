# Implementation Report: 里程碑 3「交付物可信」（GL-10 / GL-11 / GL-12 / GL-13 / GL-15）

## Summary
- GL-10：字幕与字幕卡分两条文本轨（`subtitle` / `card`），丢弃非正时长文字、同轨重叠后者顺延；文本段改用 `trange_seconds(start, end=end)` 消除 1µs 取整重叠；片头/片尾卡逻辑合并为 `build_documentary.card_entries()`（aicut 复用），超出成片时长的卡跳过并 `[warn]`（D1 默认）。
- GL-11：`research/validate_draft.check()` 可导入、每次清空模块级列表；校验门内嵌到 `to_jianying.install()`（移入草稿根 → 校验 → 注册），FAIL 时回滚、非零退出、不打印 `[✓]`；删除 aicut 里安装后才校验的 `_validate_draft` 与写死的 `DRAFT_ROOT`；`run_inprocess` 采纳 `main()` 的 int 返回值。
- GL-12：新增 `proc.exit_code()`，`run_inprocess` 与 `aicut.run_cli` 统一用它解析 `SystemExit`，`sys.exit("文字")` → 退出码 1 且文字进日志。
- GL-13：`resolve_draft_root()`（`AI_CUT_DRAFT_ROOT` > 剪映 `globalSetting` 的 `currentCustomDraftPath`（含 Qt `\xHHHH` 解码）> 默认路径，每次 main 现算）；`load_registry()` 对剪映未装 / 目录不可访问 / 注册表坏给出中文 `InstallError`；`install()` 带 `.aicut_installing` 标记、注册表备份、任何异常回滚（挪回暂存目录、还原注册表），只自动清理「带标记且未注册」的孤儿目录，绝不动用户同名目录；非 dry-run 在拷媒体**之前**检查剪映是否运行、草稿库是否可用；dry-run（Windows 导出）不依赖剪映。
- GL-15：新模块 `pipeline/media_io.py`（同目录同扩展名随机临时名 → `os.replace` → `<名>.done` 标记，大小校验；中断/异常不留半成品，重做先作废旧标记，清理陈旧临时文件且 glob 转义）。接入：asr.wav、proxy.mp4、work/clips/*.mp4（每镜落 manifest）、output/vN/preview.mp4（`ensure_preview`）、build_documentary 切片、transcript_raw.json（改用 `schema.write_json` 原子写）；下游门槛（analyze/scenes/quality）与 `status` 显示改用 `is_complete`。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 高（单测 + 临时草稿根真实媒体安装校验 OK=65/67 FAIL=0） |
| Files Changed | 16 | 18（9 源/配置 + 1 新源 + 8 测试；未改 docs 登记册，按指示） |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 0 | 测试隔离护栏 | done | 合并进既有 `tests/conftest.py`（autouse `_isolate_jianying`），未新建文件 |
| 1 | GL-12 + GL-11(a) 退出码 | done | |
| 2 | GL-11(b) `validate_draft.check()` | done | CLI 输出与改前逐字一致（真实草稿 `九月一号_v4` 新旧版 diff 为空） |
| 3 | GL-10 分轨 / 过滤 | done | 追加 1µs 取整重叠回归用例 |
| 4 | GL-13 + GL-11(c) 安装事务 | done | 偏差见下：复用 `schema.write_json` |
| 5 | GL-15(a) `media_io` | done | 追加「ffmpeg 不存在 → MediaError」 |
| 6 | GL-15(b) 接入所有输出点 | done | 偏差见下：cloud 用 `schema.write_json` |
| 7 | 收尾验证 | done（自动化部分） | 未提交、未改登记册、未归档计划（按指示）；打包冒烟与剪映打开草稿为待人工 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | pass | 未配置 lint/typecheck；`uv run python -m compileall -q aicut.py pipeline research` 退出 0 |
| Unit Tests | pass | 510 → 584 passed（+74） |
| Build | N/A | 打包冒烟待人工 |
| Integration | pass | 真实项目时间线安装进**临时**草稿根：`校验通过：OK=65 WARN=0 FAIL=0`；加纪实3min 卡片后两条文本轨、`OK=67 FAIL=0`；同名重跑「草稿已存在」；根不存在时在生成草稿前报「找不到剪映草稿库…」；Windows 导出（dry-run）打包成功、占位符/安装脚本齐全 |
| Edge Cases | pass | 中断（KeyboardInterrupt / SystemExit）、旧版无标记产物、大小不符、空产出、陈旧临时文件、glob 元字符、注册失败回滚、校验失败回滚、孤儿清理、用户同名目录、坏注册表 |

范围自检：`grep DRAFT_ROOT\|_validate_draft aicut.py`、`int(exc.code`、`"ffmpeg", "-y"`（aicut / build_documentary）、`proxy.exists()\|wav.exists()` 均无结果。
真实剪映库：全量测试前后 `root_meta_info.json` mtime 不变（Oct 18 20:06:15），`.bak` 数量不变（12）。

## Files Changed

| File | Action | Lines |
|---|---|---|
| `pipeline/media_io.py` | CREATED | +103 |
| `pipeline/to_jianying.py` | UPDATED | 275 行变动 |
| `aicut.py` | UPDATED | +56 / -66（897 → 893 行） |
| `pipeline/build_documentary.py` | UPDATED | 53 行变动 |
| `research/validate_draft.py` | UPDATED | 47 行变动 |
| `pipeline/proc.py` | UPDATED | +20 / -3 |
| `pipeline/schema.py` | UPDATED | `write_json` 增加 `indent` 关键字参数 |
| `pipeline/cloud.py` | UPDATED | transcript_raw 原子写 |
| `packaging/ai-cut.spec` | UPDATED | hiddenimports + `pipeline.build_documentary`、`pipeline.media_io` |
| `tests/conftest.py` | UPDATED | autouse 草稿库隔离 |
| `tests/test_proc.py` / `test_cloud.py` / `test_schema.py` | UPDATED | 回归用例 |
| `tests/test_aicut_build.py` / `test_build_documentary.py` / `test_media_io.py` / `test_to_jianying.py` / `test_validate_draft.py` | CREATED | 回归用例 |

## Deviations from Plan
1. **`to_jianying.write_json` 复用 `schema.write_json(..., indent=None)`**（WHAT）——计划保留其固定 `.tmp` 名实现；按「不另造 JSON 原子写」的要求改为薄封装（WHY：固定临时名正是 GL-18 的并发互踩问题）。为保持草稿 JSON 紧凑格式，给 `schema.write_json` 加了 `indent` 关键字（默认 2，现有调用不变），并补测试。
2. **`cloud.transcribe` 用 `schema.write_json`**，而非计划里的手写 uuid 临时名 + `os.replace`（同上理由）；测试改为整体让 `os.replace` 失败并断言无残留，不依赖实现细节。
3. **`tests/conftest.py` 合并而非新建**（文件在 M1/M2 已存在）。
4. **基线**：计划写 112，实际开工时为 510（M1/M2 已落地）。
5. 额外小加固（均有测试）：`run_ffmpeg` 把 `OSError`（未装 ffmpeg）转为 `MediaError`；校验 FAIL 超 10 条时注明「另有 N 条」；`load_registry` 也接住 `UnicodeDecodeError`；`build_documentary.main` 切片失败 `sys.exit` 中文原因；`test_main_refuses_while_jianying_running`、`test_main_validation_fail_exits_nonzero` 等端到端用例。
6. 产品默认按指示实现并放入命名常量：D1 `build_documentary.CARD_SKIPPED_WARNING`（跳过 + `[warn]`），D2 `to_jianying.SUBTITLE_TRACK / CARD_TRACK = "subtitle" / "card"`；其他文案常量 `JY_RUNNING`、`JY_MISSING`。

## Issues Encountered
- 用 `~/.aicut/venv`（Homebrew Python 3.14）以脚本方式跑 `pipeline/to_jianying.py` 直接崩溃：`pipeline/select.py` 遮蔽标准库 `select`。已用 `git show HEAD:` 版本复现，**改动前即存在**，属范围外，登记于下。真实媒体验证改用项目 uv Python 3.12（`select` 为内建模块，不受影响）。

## 新发现缺陷（未修，建议登记）
1. **[高] 开发模式 `aicut build` 生成剪映草稿必崩（本机）**：`aicut.py:640`（`ensure_jy_python()` 选 `~/.aicut/venv/bin/python`，本机为 Homebrew 3.14）以脚本方式运行 `pipeline/to_jianying.py`，`pipeline/to_jianying.py:28` `import subprocess` → `import select` 命中 `pipeline/select.py`（脚本目录在 `sys.path[0]`），其 `pipeline/select.py:17` `from pipeline import classify, review` → `ModuleNotFoundError`。自 a7e588a 引入 `pipeline/select.py` 起存在；凡 `select` 不是内建模块的解释器、以脚本方式运行任一 `pipeline/*.py` 都会中招（`media_io` 现在也 `import subprocess`，`build_documentary.py` 脚本方式同样受影响）。打包版与 uv Python 3.12 不受影响。
2. **[低] 同名草稿重跑先拷媒体再报「已存在」**：`pipeline/to_jianying.py` `main()` 预检只查剪映运行与注册表，目标目录存在性要到 `install()`（`pipeline/to_jianying.py:404`）才查，重跑会白拷一遍媒体（改动前行为相同）。
3. **[低] 草稿失败输出被截尾**：`aicut.py:637`、`aicut.py:644` 只打印子任务输出末尾 600/500 字符，10 条 FAIL 明细较长时开头「草稿静态校验未通过」可能被截掉（结论仍以非零退出码体现）。

## Pending Manual Checks
- [ ] 剪映里打开安装后的草稿，确认 `subtitle` / `card` 两条文本轨、片头卡显示正常（需在真实剪映草稿库里装一次，本次只装进临时根）。
- [ ] 开发模式完整 `uv run python aicut.py build <纪实3min 项目> --version vX`：被新发现缺陷 1 阻断，需修复后再验。
- [ ] `AI_CUT_DRAFT_ROOT=/tmp/不存在 uv run python aicut.py build <项目>` 走 aicut 全链路（脚本层已验证）。
- [ ] 抽音轨 / 生成代理时 Ctrl+C，确认无 `asr.wav` / `proxy.mp4` / `.partial-` 残留，重跑重新生成（单测覆盖，未在真素材上手动中断）。
- [ ] 打包冒烟：`./packaging/build_app.sh` → `dist/AI粗剪.app`，剪映运行中点导出 → 日志出现「剪映正在运行…」、任务 failed；剪映未装 / 草稿目录不可访问时日志出现中文原因。
- [ ] 旧项目首次重跑会因无 `.done` 标记重新抽音轨 / 重做代理与切片（计划已接受的一次性成本；`aicut status` 对旧项目的 音轨 / 分析代理 现显示为 `·`）。GUI `gui/server.py:184` 的 `has_proxy` 仍以 `exists()` 判断（计划 NOT Building）。
- [ ] 中文自定义草稿目录下 `globalSetting` 的真实转义格式（本机为默认 ASCII 路径，Qt `\xHHHH` 解码仅按假设实现并单测）。

## Tests Written

| Test File | Coverage |
|---|---|
| `tests/test_proc.py` | `sys.exit("文字")`、`main()` 返回值、int/bool/None 退出码、argv 还原 |
| `tests/test_validate_draft.py` | `check()` 不跨调用累积、不打印、`run_inprocess` 透传 FAIL、CLI 格式 |
| `tests/test_to_jianying.py` | 分轨、非正时长、无文字不建轨、1µs 取整重叠、`layout_texts` 不改入参；`macify` 根路径、安装成功、`with_entry` 不可变、注册失败回滚 + 重试、校验失败回滚、孤儿清理、用户同名目录、注册表 4 种异常、草稿根解析 5 种、冻结路径缺剪映、剪映运行中拒装、端到端安装、校验 FAIL 端到端、dry-run |
| `tests/test_media_io.py` | 原子提交、3 种中断、重做作废旧标记、旧文件无标记、大小不符、坏标记、空产出、陈旧临时文件、glob 元字符、stderr 尾巴、ffmpeg 不存在、临时路径参数、真 ffmpeg |
| `tests/test_aicut_build.py` | `run_cli` 文字退出、`compose_timeline` 卡片、抽音轨中断 / 旧 wav / 失败、analyze/scenes/quality 门槛、代理失败、切片续切、预览重渲染 / 失败不写 stamp、status 标记 |
| `tests/test_build_documentary.py` | `card_entries` 跳过 / 截断、`cut_shot` 经 `media_io` |
| `tests/test_cloud.py` | transcript_raw 原子写 |
| `tests/test_schema.py` | `write_json(indent=None)` 紧凑输出 |

## Next Steps
- [ ] 代码审查（`/ecc:code-review` 或 `/ecc:python-review`）
- [ ] 提交后在 `docs/go-live-blockers.md` 将 GL-10/11/12/13/15 状态填提交号，并登记上面的新发现缺陷

---

## 审查修复（code review + silent-failure review 之后）

全部按 TDD：先写失败用例确认 RED，再实现。测试 584 → **638 passed**。真实剪映库 `root_meta_info.json` mtime 与 `.bak` 数量（12）不变；真实媒体验证全部装进 scratchpad 临时草稿根。

| # | 问题 | 处理 |
|---|---|---|
| H1 | 成功时 to_jianying 的警告 / 位置 / 备份被吞；失败只打最后 500/600 字符 | to_jianying 新增警告汇总（`warn()` → 末尾 `草稿位置：` / `注册表备份：` / `[!] N 条警告` + `  - …` 块，`parse_report()` 解析）；校验 WARN、模板缺失、封面失败、文字丢弃 / 顺延都进汇总。aicut 新增 `install_draft()`：成功时逐条 `warn()` 重报并打印草稿位置与备份；失败按行打印末尾 `DRAFT_LOG_LINES=40` 行（开发模式合并 stdout+stderr）并 `die("草稿未安装（已回滚，剪映草稿库保持原样）")`（顺带解决 KI-60） |
| H2 | Windows 导出绕过校验门 | `--dry-run` 也跑 `validate_draft.check`（`relocate=(安装后路径, 暂存目录)` 把素材路径映射回暂存目录），FAIL 非零退出；`export_draft.package_draft` 写同目录临时 zip → `inspect_package` + `check_package`（INSTALL.bat / fix_paths.ps1 / 草稿 / 占位符缺一不可）→ `os.replace`；`_pkg_<name>` 与临时 zip 在 `finally` 清理。用户输出目录不放 `.done` |
| H3 | 自定义草稿路径解析失败会悄悄退回默认目录 | 设置文件不存在 / 无该键 / 空值 → 默认目录；读不了、`@ByteArray`、`\\` 等未知转义、不成对代理、相对路径 → `InstallError` 并显示原值。`\xHHHH` 按 UTF-16 码元 + `surrogatepass` 解码（代理对 OK）。原「相对路径静默回退」用例已改为「必须报错」 |
| H4 | 校验门覆盖面 | 先只读检查真实草稿：我们生成的（`九月一号_v2/_v4`、新建）都有 `draft_content.json` / `draft_info.json` / `draft_meta_info.json` / `Resources/` / `draft_cover.jpg`；剪映打开过的 `九月一号_v3` 的 `draft_info.json` 被剪映改写成**非明文**格式。于是：A 段新增必需 `draft_info.json`（非明文只 WARN，封面不强制——F 段已管素材路径）；新增 I 段：0 个视频片段 → FAIL；可选 `expect`（视频段数 / 文字段数 / 视频终点，容差 `VIDEO_END_TOLERANCE_US=100ms`）与时间线核对，安装与 dry-run 都传。真实草稿 v2/v3/v4/粗剪v1 仍 PASS（v3、粗剪v1 各 1 条 WARN） |
| M5 | 剪映中途被打开 | `install()` 在备份前、写注册表前各查一次 `jianying_running()` |
| M6 | 回滚健壮性 / 跨卷 | 回滚每步独立 try；失败打印 `[ERROR] 回滚失败：…` 并 `raise InstallError(...) from 原始错误`（消息含原因）；`_undo_placement` 报告挪回 / 删除了什么，不带安装中标记的目录拒绝删除。放置改为「先在草稿根内建 `.<名>.aicut-tmp` → 再 `os.rename` 到位」：同卷直接改名；跨卷（EXDEV）先建临时目录、**先写安装中标记**再 copytree，半拷目录总认得出是我们的，失败时删除、暂存原件保留；`.aicut-tmp` 孤儿下次自动清理 |
| M7 | 旧项目无 `.done` 标记 | `media_io.complete_or_adopt()`：无标记、大小 > 0 且 ffprobe 读得出正时长 → 补写标记认领（有标记但大小不符的不认领）；aicut 全部门槛 / status、build_documentary、`gui/server.py` 的「抽音轨」阶段、`has_proxy`、版本 `preview` 都改用它，GUI 与 CLI 判定一致 |
| M8 | 截短 / 顺延不可见 | `layout_texts` 按轨汇总「N 条字幕与前一条重叠，起点已顺延」；负起点截到 0；`card_entries` 片尾卡被截短时 `[warn]` |
| M9 | 封面 | `macify(..., runner=)` 检查返回码，失败进警告汇总；没有 ffmpeg → `InstallError` |
| M10 | 注册表备份 | 回滚成功后删除本次 `.bak`；成功安装后只留最新 `BACKUP_KEEP=5` 份；还原走临时文件 + `os.replace`；同秒重名自动加后缀 |

### 审查修复新增 / 修改的文件
- 新增 `tests/test_server_media_state.py`
- 修改 `pipeline/to_jianying.py`（701 行）、`research/validate_draft.py`、`pipeline/media_io.py`、`pipeline/export_draft.py`、`pipeline/build_documentary.py`、`aicut.py`（902 行，较开工前 897 净增 5：新增 `install_draft`，删了 cmd_build 里内联的两段）、`gui/server.py`
- 测试：`test_to_jianying.py`（安装类用例改用 ffmpeg 现做的 1 秒片段，无 ffmpeg 时 skip）、`test_validate_draft.py`、`test_media_io.py`、`test_aicut_build.py`、`test_build_documentary.py`、`test_export_draft.py`

### 接口变化（调用方须知）
- `to_jianying.install(...)` 多了可选参数 `expect`，返回值由 `Path` 改为 `(草稿目录, 注册表备份)`。
- `validate_draft.check(draft_dir, ref_schema, expect=None, relocate=None)`。
- `to_jianying.build_staging(..., texts=None)`、`macify(..., runner=subprocess.run)`。

### 真实媒体复验（临时草稿根）
- 带纪实3min 卡片的真实时间线：`校验通过：OK=69 WARN=0 FAIL=0`（含时间线核对），输出末尾出现 `草稿位置：` / `注册表备份：` / `[!] 1 条警告` 汇总，草稿根内无残留临时目录。
- Windows 导出：dry-run 校验通过，输出目录只有 `M3_export.zip`。

### 审查修复中新发现（未修）
4. **[低] 导出时打印临时 zip 路径**：`packaging/build_package.py:272` 的 `zip_pkg` 打印「打包完成：…/.M3_export.partial-xxxx.zip」，现在写的是临时名，日志里路径会让人误会（最终文件名由 aicut「已导出」那行给出）。
5. **[低] 旧项目认领的残余风险**：`complete_or_adopt` 对没有标记的旧 wav，ffprobe 可能按文件大小估出正时长，从而认领到旧版本中断留下的半截 wav（审查明确要求认领，按要求实现；新产物不受影响）。
6. **[信息] aicut.py 仍在 800 行软上限之上**（902，KI-55）。
