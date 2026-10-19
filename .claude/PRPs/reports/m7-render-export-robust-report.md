# Implementation Report: 里程碑 7「渲染与导出健壮」（KI-13..KI-18 / KI-59 / KI-64 / KI-76 + KI-78）

## Summary
- **预览字幕（KI-13 / KI-76）**：预览改用 `textfile` + `expansion=none`。每条字幕写成一个 UTF-8 临时文件，文字不再经过滤镜图的转义。如果 `$TMPDIR` 里有滤镜图元字符，就改用 `/tmp`。
- **无音轨（KI-14）**：没有音轨的镜头补一段 `anullsrc` 静音，所有音轨统一成 48k 立体声。新增 `media_io.has_audio`。ffmpeg 失败时统一报 `MediaError`，提示「预览片渲染失败：…」。
- **遮蔽标准库（KI-15）**：开发态的子进程改由 `proc.dev_module_cmd` 启动：`python -P -c <runpy 引导> ROOT module args`。`pipeline/select.py`、`secrets.py` 不会再遮蔽标准库。打包版的路径不变。
- **`aicut run` 参数（KI-16）**：`run` 与 `build` 现在共用 `--version` / `--no-draft`。
- **版本常量（KI-17）**：新增 `pipeline/jy_version.py`，统一管理已验证版本、模板路径和读取已装剪映版本。本机剪映大版本 ≠ 11 时进警告汇总。另加一份黄金草稿结构快照。
- **导出健壮（KI-18）**：
  - 模板缺失直接失败，退出码 1（dry-run 也检查）。
  - Windows 导出成功时，警告会透传，并由 `cmd_export` 再报一次。
  - `INSTALL.bat` 失败时打印 `[X]` 并 `exit /b 1`；PS1 失败时打印原因。
- **同名草稿（KI-59）**：在拷媒体之前就检查。
- **临时 zip 路径（KI-64）**：`zip_pkg` 不再打印。
- **追加 KI-78**：`INSTALL.bat` 不再删除已有的同名草稿。安装前先检查同名，有冲突就停下并说明，什么都不装，`exit /b 1`。安装中途失败时，只删本次自己装了一半的副本。README.txt 已同步说明。

## Assessment vs Reality
| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large |
| Confidence | — | 高。全量测试通过；KI-15 用真实 Homebrew 3.14 venv 实测 |
| Files Changed | 23 | 25（源 12：含新建 `pipeline/jy_version.py`；测试 13：新建 3 个测试文件 + 1 份 golden，改 9 个） |

## Tasks Completed
| # | Task | Status | Notes |
|---|---|---|---|
| 1 | RED：预览渲染测试 | [done] | 9 条用例（含真 ffmpeg 集成：静音 / 单声道 44.1k / 5.1 + 特殊字幕），另加 4 条 `has_audio` |
| 2 | GREEN：render_preview + has_audio + REQUIRED_FILTERS | [done] | Homebrew ffmpeg 与 vendor ffmpeg 7.0 都通过 |
| 3 | RED：KI-15 | [done] | 机制复现（包内 `json.py`）+ Homebrew Python 参数化 3 个模块 |
| 4 | GREEN：`dev_module_cmd` 与调用方 | [done] | 删除 `aicut.PIPELINE`；4 个脚本的文档字符串改成 `python -m` |
| 5 | KI-16 | [done] | 偏离：见下 |
| 6 | RED：jy_version / 模板 / 同名 / 版本警告 | [done] | |
| 7 | GREEN：jy_version + to_jianying | [done] | |
| 8 | 黄金回归 | [done] | 偏离：`new_version` 实际是 110.0.0，见下 |
| 9 | Windows 导出 + BAT/PS1 + zip_pkg + KI-78 | [done] | KI-78 为追加范围 |
| 10 | 全量验证 | [done] | 按要求未 commit，未改登记册状态，未改 PRD |

## Validation Results
| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | `compileall` 与 `bash -n build_ffmpeg.sh` 通过（仓库没有配置 lint / typecheck） |
| Unit Tests | Pass | 987 → **1044 passed**，0 skipped，0 failed |
| Build | N/A | 没有打包 .app |
| Integration | Pass | 真 ffmpeg 渲染；真实 `~/.aicut/venv`（Homebrew 3.14）跑 `to_jianying` dry-run（校验 OK=15 FAIL=0）和 `render_preview`（无音轨素材 → `audio,48000,stereo`） |
| Edge Cases | Pass | 空字幕、`$TMPDIR` 含元字符、plist 损坏或非字符串、自家孤儿目录、包里没有草稿 / 同名 / 失败 |

KI-15 修前实测：`~/.aicut/venv/bin/python pipeline/to_jianying.py --help` 报 `ModuleNotFoundError: No module named 'pipeline'`。修后用 `-P` 引导，to_jianying / render_preview / junk_detect / format_transcript 的 `--help` 都是 rc=0，understand_visual 也能导入。

打包路径核对：`module_cmd` 在 FROZEN 时仍返回 `[exe, --aicut-module, …]`；`_run_module_main` / `run_inprocess` 实测 rc=0。

## Files Changed
| File | Action |
|---|---|
| `pipeline/render_preview.py` | UPDATED（textfile、静音补轨、MediaError） |
| `pipeline/media_io.py` | UPDATED（`has_audio`） |
| `pipeline/proc.py` | UPDATED（`DEV_BOOTSTRAP` / `dev_module_cmd`） |
| `pipeline/jy_version.py` | CREATED |
| `pipeline/to_jianying.py` | UPDATED（模板缺失失败、`_ensure_name_free`、版本警告、常量） |
| `pipeline/export_draft.py` | UPDATED（返回 warnings） |
| `pipeline/junk_detect.py`、`pipeline/format_transcript.py` | UPDATED（只改文档字符串） |
| `aicut.py` | UPDATED（931 → 930 行） |
| `packaging/build_package.py` | UPDATED（BAT / PS1 / README / zip_pkg） |
| `packaging/build_ffmpeg.sh` | UPDATED（`anullsrc aformat`） |
| `packaging/ai-cut.spec` | UPDATED（hiddenimport `pipeline.jy_version`） |
| `tests/test_render_preview.py`、`tests/test_jy_version.py`、`tests/test_jianying_golden.py`、`tests/golden/jianying_draft_shape.json` | CREATED |
| `tests/conftest.py`、`test_aicut_build.py`、`test_export_draft.py`、`test_media_io.py`、`test_packaging.py`、`test_proc.py`、`test_to_jianying.py`、`test_m5_review2.py` | UPDATED |

## Deviations from Plan
1. **KI-16 的写法**：没有新增 `_add_build_options` 函数，而是把 `run` 和 `build` 放进同一个三行循环，一起注册参数。
   - 原因：`aicut.py` 不许变长。用辅助函数会到 933 行。
   - 影响：`--help` 里 `build` 的排位变了。
2. **黄金快照的 `new_version`**：实际是 `"110.0.0"`，不是计划预期的 `"75.0.0"`。
   - 原因：`align_with_template` 本来就让 pyJianYingDraft 生成的顶层键覆盖模板。这是现有行为，没有改；快照如实记录。
   - `version` = 360000、`app_version` = 11.0.0 与预期一致。VideoToolbox 和 mpeg4 素材生成的快照相同，所以没有排除任何键路径。
3. **BAT 冲突检查**：拷贝之前单独跑一个预检循环，只要有同名就整包不装。拷贝失败、或 PS1 失败时，`rd` 掉本次自己建的副本（预检已保证它之前不存在），这样重试不会被半装的目录挡住。
   - 这个做法覆盖了「需要重装自家旧版本」的情况，所以没有采用 `.bak-<时间戳>` 改名方案。
4. **新增守卫测试**：除计划内的用例外，还加了：
   - spec 带的模板名与 `jy_version.TEMPLATE` 一致；
   - BAT / PS1 是纯 ASCII；
   - BAT 的 echo 行不用解析期展开的 `%ROOT%`。
5. **代码审查（python-reviewer）的 HIGH 项**：
   - **已修**：`%LOCALAPPDATA%` 含 `)` 时，括号块里 `echo … %ROOT%` 会提前闭合块。三处 echo（其中一处是原有代码）改成 `!ROOT!`，先 RED 再 GREEN。
   - **判定不适用**：草稿名含 `!` 会被延迟展开吞掉。导出包的草稿名先经过 `_api_name`（只留 ASCII 字母数字和 `-_`），`!` 到不了 BAT。
   - **验证后不采纳**：空字幕 textfile 会让 ffmpeg 报错。两个版本的 ffmpeg 实测 rc=0。
6. 改了 `tests/test_m5_review2.py` 的假 ffmpeg 桩：它列出的滤镜加上 `anullsrc aformat`，因为 REQUIRED_FILTERS 合理地变多了。

## Issues Encountered
- 做「改 `VERIFIED_VERSION` 应 RED」的验证时，用 sed 改了又在同一秒内改回，文件大小也没变，`__pycache__` 里的 pyc 因此被当作仍然有效，全量跑出了假红。删掉 `pipeline/__pycache__/jy_version*.pyc` 后正常。这和 tsbuildinfo 陈旧是同一类问题。

## 新发现缺陷（未修，建议登记）
1. `packaging/build_package.py:175`：`echo [!] JianYing is running…` 在 `enabledelayedexpansion` 下，单个 `!` 会被吞掉，显示成 `[] JianYing is running…`。只是外观问题。
2. `pipeline/to_jianying.py:250-270`（`bundle_media`）：直接在命令行用相对路径 `--staging` 时，素材路径会写成相对路径，静态校验 FAIL。aicut 和导出都传绝对路径，不受影响。
3. `packaging/build_package.py:143`（`make_minimal_draft`，研究用的 `--minimal` 分支）：仍然写死 `research/base_template_11.0.json`，模板缺失时静默跳过，和 D1 / `jy_version` 不一致。该分支不在产品导出链路上。
4. `aicut.py:136`（`ensure_jy_python`）：不检查已有 `~/.aicut/venv` 的 Python 版本。用 3.10 及以下建的旧 venv 会报 `Unknown option: -P`（计划 Risks 已列出）。本机 venv 是 3.14，不受影响。

## 待人工验证
- Windows 实机：
  - 正常安装仍显示 `[OK] Done.`；
  - 已有同名草稿时出现 `[X] … already exists`，并且原草稿不变；
  - 把目标设为只读时出现 `[X] … NOT installed correctly`，半装副本被删除；
  - 用户目录名含 `)` 时脚本能正常运行。
- 剪映 Mac（本机 11.6.0）打开新生成的草稿：能播放，有字幕。
- 真实项目：
  - `aicut run <项目> --no-draft` 能出预览片；
  - 字幕 `他说'好'，100%` 在预览里原样显示；
  - 同一版本 build 两次，第二次在拷媒体之前就报「草稿已存在」。
- 登记册状态和 PRD 第 7 行：等提交后再填（本次按要求没动）。

## 审查修复（协调方第二轮代码审查：无 CRITICAL/HIGH，以下 MEDIUM/LOW 均已修，TDD）

测试数：1044 → **1086 passed**，0 skipped，0 failed（`uv run pytest`）。`aicut.py` 930 → 924 行。

| # | 问题 | 修法 | 测试 |
|---|---|---|---|
| 1a | 入口在 <3.11 下的报错不清楚 | 新增 `pipeline/pyver.py`（只用 3.6+ 语法）。`aicut.py`、`gui/server.py`、`app/main.py` 在导入项目代码之前调用 `require_supported_python()`，给出中文说明，退出码 1 | `tests/test_pyver.py`：单元测试；静态测试（检查发生在首个项目导入之前）；用 macOS 自带 3.9 实跑三个入口，rc=1，有中文提示，无 Traceback |
| 1b | `dev_module_cmd` 在 <3.11 下不认 `-P` | 引导代码先剔除 `sys.path` 里的 `''` / `'.'`，再导入 runpy。`-P` 只在 `pyver.supports_safe_path(python)` 为真时加：当前解释器直接看版本，其他解释器跑一次探针 | 退回路径的行为测试；用真实 3.9 跑引导；包目录和 cwd 里都放遮蔽标准库的 `json.py` |
| 1c / KI-82 | 用旧 venv 跑 `ensure_jy_python` | 逻辑移到新模块 `pipeline/jy_env.py`：venv 不认 `-P` 时用当前解释器 `venv --clear` 原地重建，再装依赖；失败抛 `JyEnvError`，由 aicut `die`。`aicut.ensure_jy_python` 缩成薄包装 | `tests/test_jy_env.py`，以及 `test_aicut_build` 的接线测试。本机 `~/.aicut/venv`（3.14）探针为 True，所以不会被重建（只读核对） |
| 2 | 草稿名含 `! % ^ & \| < > "` 时，cmd 会改写名字，回滚的 `rd` 可能删到别的目录 | `build_package.check_draft_name`：`write_installer` 遇到不安全名字时什么都不写，抛 ValueError；`build_package.py --name` 在动手之前退出 | 8 个字符逐个生成 BAT 并断言被拒；`_api_name` 的产物总能通过；CLI 在动手之前退出 |
| 3 | 遮蔽测试不能证明隔离有效 | 测试改成 cwd 里也放 `json.py`，并在 cwd 下运行 | 变异验证：同时去掉 `-P` 和剔除 → 4 条 RED；只去剔除 → 2 条 RED（退回路径 + 真实 3.9）；只去 `-P` → 2 条 RED（`-P` 在场的结构断言）。说明：在 3.11+ 上，cwd 已经由剔除那一层兜住，所以只去 `-P` 时行为测试不会变红，失败的是结构断言 |
| 4 / KI-81 | `build_package.py` 独立运行时写死模板路径 | `make_minimal_draft` 改用 `jy_version.TEMPLATE`，缺失时一开始就 `sys.exit`（非 0）。`TEMPLATE_MISSING` 文案移到 `jy_version`，`to_jianying` 引用它 | 源码里不再写死路径；缺模板时非 0 退出，且不生成目录 |
| 5 | render_preview 独立运行时不是原子写出 | `media_io.atomic_output` 新增 `mark=False`；render_preview 用它原子写出、不写标记（aicut 外层的 `atomic_output` 负责完成标记，避免嵌套时多出一个孤儿 `.done`） | 成功时写的是临时文件，目录里只剩 `o.mp4`；失败时不留半成品。在 aicut 式外层包装下实跑：目录里只有 `preview.mp4` 和 `preview.mp4.done` |
| 6 | 字幕临时目录是否残留 | — | 成功（真 ffmpeg 与假 ffmpeg 各一条）和失败两种情况都断言不残留 `aicut-preview-*` |
| KI-79 | `echo [!]` 在延迟扩展下被吞 | 改成 `echo [X] JianYing is running…`（这是终止提示，和其他 `[X]` 一致） | 所有 echo 行除 `!ROOT!` / `!NAME!` 外不得含 `!` |

其他：spec 的 hiddenimports 加了 `pipeline.jy_env`、`pipeline.pyver`，有测试守卫。

本轮新增或修改的文件：
- 新建：`pipeline/pyver.py`、`pipeline/jy_env.py`、`tests/test_pyver.py`、`tests/test_jy_env.py`
- 修改：`aicut.py`、`gui/server.py`、`app/main.py`、`pipeline/proc.py`、`pipeline/media_io.py`、`pipeline/render_preview.py`、`pipeline/jy_version.py`、`pipeline/to_jianying.py`、`packaging/build_package.py`、`packaging/ai-cut.spec`，以及 `tests/test_proc.py`、`test_aicut_build.py`、`test_export_draft.py`、`test_render_preview.py`、`test_media_io.py`、`test_packaging.py`

追加的待人工验证：Windows 上 `[X] JianYing is running…` 的显示。
