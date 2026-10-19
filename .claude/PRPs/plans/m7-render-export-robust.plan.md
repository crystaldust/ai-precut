# Plan: 里程碑 7「渲染与导出健壮」（KI-13..KI-18 / KI-59 / KI-64 / KI-76）

## Summary
让预览渲染与剪映导出在「特殊字幕、无音轨、模板缺失、同名草稿、剪映版本变化、Windows 安装失败」这些情况下**不崩、且如实报错**：
预览字幕改走 `textfile=` + `expansion=none`，彻底绕开 drawtext 的多层转义（KI-13 / KI-76）；无音轨镜头补静音、所有音轨统一成 48k 立体声（KI-14）；
开发态 pipeline 子进程改由 `-P` + `runpy` 引导，不再把 `pipeline/` 放到 `sys.path[0]`，`select.py` / `secrets.py` 不会遮蔽标准库（KI-15）；
`run` 子命令补齐 `build` 需要的参数（KI-16）；剪映版本常量集中、版本跨大版本时警告、加黄金草稿回归（KI-17）；
模板缺失直接失败、导出路径不再吞警告、Windows 安装脚本失败不再打印 `[OK] Done`（KI-18）；同名草稿在拷媒体之前就报「已存在」（KI-59）；`zip_pkg` 不再打印临时 zip 路径（KI-64）。

## User Story
作为剪辑师，我希望字幕里有引号、百分号，素材没有声音，或者导出出了问题时，App 告诉我真实原因、给出可用的结果，而不是渲染失败、空等几分钟后才说「已存在」，或者 Windows 上提示成功、草稿却打不开。

## Problem → Solution
- **现状**（2026-10-19 在当前代码 `963374c` 上复现）：
  - 字幕含 `'` → `No such filter: 'ok:fontsize=…'`，ffmpeg 7.0（vendor）与 9.0（Homebrew）都失败（KI-13）；含 `%` → `Stray % near ''`，vendor 版该条字幕不显示，Homebrew 版 `Error while filtering`（KI-76）。`esc()` 其实已经转义了 `%`，但它是在单引号里加 `\`，ffmpeg 不认，所以没用。
  - 素材无音轨 → 切片没有音轨 → `render_preview` 的 `[i:a]` 报 `matches no streams`，退出码 234（KI-14）。
  - `/opt/homebrew/bin/python3 pipeline/render_preview.py --help` → `subprocess` 导入 `select` 时拿到 `pipeline/select.py` → `ModuleNotFoundError: No module named 'pipeline'`；`to_jianying.py`、`junk_detect.py`、`understand_visual.py` 同样失败。本机 `~/.aicut/venv` 就是 Homebrew 3.14，所以开发态 `aicut build` 的草稿步骤**现在就会失败**（KI-15）。
  - `aicut run <项目>` 在已有 shots.json 时调用 `cmd_build(args)`，`args` 里没有 `version`，抛 `AttributeError`（KI-16）。
  - 版本号 `"11.0.0"`、模板路径 `base_template_11.0.json` 分散写死；本机剪映是 11.6.0；没有固定 pyJianYingDraft 输出结构的回归测试（KI-17）。
  - 模板缺失只 `warn`；Windows 导出走 `export_draft` 子进程，成功时 stdout 整个丢掉，警告一条都看不到；`INSTALL.bat` 拷贝失败或 `fix_paths.ps1` 失败仍打印 `[OK] Done.`（KI-18）。
  - 同名草稿：`_prepare_root` 只检查剪映是否在运行、注册表是否存在，等 `build_staging` + `bundle_media` 拷完媒体后，`install()` 才报「已存在」（KI-59）。
  - `package_draft` 调用 `zip_pkg(pkg, tmp_zip)`，打印的是 `.<名>.partial-xxxx.zip`（KI-64）。
- **目标**：每个场景都有失败在先（RED）的测试；修完后预览能正确渲染任意文字，无音轨也能出片；开发态在 Homebrew Python 下能跑；同名、模板缺失、版本跨大版本、Windows 安装失败都在第一时间给出人能看懂的说明。

## Metadata
- **Complexity**: Large（9 个源文件 + 1 个新模块 + 1 份 spec + 1 个 shell 脚本；约 9 个测试文件，其中 3 个新建；外加 1 份黄金快照）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: 里程碑 7「渲染与导出健壮」（KI-13..KI-18 KI-59 KI-64 KI-76）
- **Estimated Files**: 23（源 12 + 测试 10 + golden 1）；关闭时另改 `docs/known-issues.md` 状态列和 PRD 第 7 行

---

## KI 现状核对（在当前代码上重新定位）

| KI | 登记位置 | 当前位置 | 结论 |
|---|---|---|---|
| KI-13 | `render_preview.py:33-36` | `pipeline/render_preview.py:39-42`（`esc`）、`:76-82`（drawtext） | **仍存在**：实测两版 ffmpeg 都失败 |
| KI-14 | `render_preview.py:53` | `pipeline/render_preview.py:59-60`（`[i:a]`）、`aicut.py:513-516`（切片不补音轨） | **无音轨部分仍存在**。「声道布局不一致导致 concat 失败」在 ffmpeg 7.0 / 9.0 上复现不了（会自动协商），但输出声道跟着第一段走（实测首段 5.1 → 整片 5.1），所以仍然统一成立体声 |
| KI-15 | `pipeline/select.py`、`pipeline/secrets.py` | 同左；触发点是 `aicut.py:150-152`（`_run_pipeline` 开发分支）、`aicut.py:660`（`install_draft`）、`pipeline/proc.py:122-123`（`module_cmd` 开发分支） | **仍存在**：Homebrew 3.14 实测崩溃；打包版走 `run_inprocess`，不受影响 |
| KI-16 | `aicut.py:601-605` | `aicut.py:690-696`（`cmd_run`）、`:866-869`（`run` 解析器） | **仍存在** |
| KI-17 | `to_jianying.py:197, 308` | `pipeline/to_jianying.py:53`（`TEMPLATE`）、`:296-314`（`align_with_template`）、`:325`（`app_version "11.0.0"`）；`packaging/ai-cut.spec:35` | **仍存在**（行号已变）；pyJianYingDraft 已由 `uv.lock` 锁在 0.3.1，但没有测试固定它的输出结构 |
| KI-18 | `to_jianying.py:176-178`；`build_package.py:157-221`；`export_draft.py:39-75` | ①`to_jianying.py:303-305`；②`packaging/build_package.py:157-201`（BAT）、`:203-221`（PS1）；③`export_draft.py:74` | ①**部分仍存在**：`aicut build` 成功后会经 `parse_report` 把警告再报一遍（M3），但模板缺失仍然只是警告，Windows 导出路径（`export_draft.py:95-98`）成功时整个 stdout 被丢掉；②**仍存在**；③「导出后不调 `inspect_package`」**已修复**（`ef3899f`/`6f8ba02`：`check_package(inspect_package(tmp_zip))`） |
| KI-59 | `to_jianying.py`（`install`） | `pipeline/to_jianying.py:656-662`（`_prepare_root`）、`:623-624`（`install` 里的「已存在」） | **仍存在** |
| KI-64 | `build_package.py`（`zip_pkg`） | `packaging/build_package.py:264-272`；调用方 `pipeline/export_draft.py:73` | **仍存在** |
| KI-76 | `render_preview.py:37-40` | `pipeline/render_preview.py:39-42` | **仍存在**（登记里说「不转义 `%`」不准确：转义了，但写法无效） |

没有已经完全过时的条目。

---

## UX Design

### Before
```
┌────────────────────────────────────────────────────────────────┐
│ 出片：字幕「他说'好'，100% 搞定」                                │
│  [·] 渲染预览片…                                                │
│  No such filter: '0'          → [x] pipeline.render_preview 执行失败 │
│                                                                │
│ 出片：手机录屏素材（无音轨）                                     │
│  Stream specifier ':a' … matches no streams → [x] 执行失败        │
│                                                                │
│ 开发态（Homebrew Python 建的 ~/.aicut/venv）出草稿                │
│  ModuleNotFoundError: No module named 'pipeline'               │
│                                                                │
│ aicut run 项目（已有 shots.json）→ AttributeError: version       │
│                                                                │
│ 第二次出同名草稿：拷 3 分钟媒体 → 「草稿已存在」                   │
│                                                                │
│ Windows：xcopy / fix_paths 失败 → 仍然 [OK] Done.               │
│          打开剪映：媒体丢失                                       │
│ 导出 Windows 包：「打包完成：…/.九月一号_v3.partial-1a2b3c4d.zip」  │
└────────────────────────────────────────────────────────────────┘
```

### After
```
┌────────────────────────────────────────────────────────────────┐
│ 出片：字幕「他说'好'，100% 搞定」 → 预览里原样显示                 │
│ 出片：无音轨素材 → 预览片带一条静音立体声轨，正常出片               │
│ 开发态 Homebrew Python → 草稿正常生成                             │
│ aicut run 项目 → 走完 build（也支持 --version / --no-draft）       │
│ 同名草稿 → 立刻报「草稿已存在：…（换名字，或先在剪映里删除）」，      │
│            不拷媒体                                              │
│ 模板缺失 → 「找不到剪映 11.0 草稿骨架模板 …，安装包不完整」，退出码 1 │
│ 剪映 12.x → [!] 剪映版本 12.0.0 与已验证的 11.x 不同 …（照常交付）   │
│ Windows 导出 → 字幕顺延等警告在导出日志里逐条可见                    │
│ Windows 安装失败 → [X] … NOT installed correctly，exit /b 1        │
│ 导出 Windows 包 → 只显示「[✓] 已导出：dist/九月一号_v3.zip（…MB）」 │
└────────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 预览字幕 | `'` 渲染失败；`%` 那条不显示，或整片失败 | 原样显示 | `textfile` + `expansion=none` |
| 无音轨素材出片 | 预览失败 | 静音轨 | 剪映草稿本来就能生成，不用改 |
| `aicut run` | 有 shots.json 时崩溃 | 正常 build；新增 `--version` / `--no-draft` | 参数与 `build` 相同 |
| 同名草稿 | 拷完媒体才报错 | 开头就报错 | 文案不变 |
| 模板缺失 | `[warn]` 后照常交付 | 失败，退出码 1 | 需用户决策 D1 |
| 剪映大版本变化 | 无提示 | `[!]` 警告，照常交付 | 需用户决策 D2 |
| Windows 导出警告 | 看不到 | `[!]` 逐条显示 | 与 `install_draft` 的展示方式一致 |
| `INSTALL.bat` | 失败也打印 `[OK] Done.` | 失败打印 `[X]`，`exit /b 1` | 能看到 PS1 的错误原因 |
| 导出日志 | 显示临时 zip 路径 | 不再显示 | `cmd_export` 本来就打印最终路径 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/render_preview.py` | 1-113 | KI-13/14/76 的改动对象（整个文件） |
| P0 | `pipeline/media_io.py` | 87-137 | `run_ffmpeg` / `MediaError` / 注入 `runner` 的 ffprobe 写法（`has_audio` 照这个写） |
| P0 | `pipeline/to_jianying.py` | 35-66, 296-315, 317-333, 613-697 | 模板、版本、`install`、`_prepare_root`、`main` |
| P0 | `aicut.py` | 144-158, 587-600, 609-674, 690-696, 852-869, 904-907 | `_run_pipeline`、`ensure_preview`、`cmd_build`、`install_draft`、`cmd_run`、解析器 |
| P0 | `pipeline/proc.py` | 34-44, 83-123 | `app_root`、`run_inprocess`、`module_cmd`（开发分支是 KI-15 的触发点） |
| P1 | `pipeline/export_draft.py` | 56-104 | `package_draft` / `build_windows_package`（KI-18 吞警告、KI-64） |
| P1 | `packaging/build_package.py` | 157-221, 258-272, 275-325 | BAT / PS1 / `zip_pkg` / `main` |
| P1 | `tests/test_to_jianying.py` | 1-30, 88-127, 420-505 | `clip` / `jy_root` / `staged` / `_run_main` 夹具 |
| P1 | `tests/test_aicut_build.py` | 1-60, 200-245 | `project` 夹具、`fake_ffmpeg`、`_frozen` |
| P1 | `tests/test_media_io.py` | 10-13, 91-135 | `FakeProc` / `_probe` 假 runner |
| P1 | `tests/test_proc.py` | 100-112, 242-245 | `module_cmd` 测试（要跟着改） |
| P1 | `tests/test_export_draft.py` | 1-30, 100-140 | `fake_draft` / `_capture_run`（要跟着改） |
| P2 | `tests/test_encode.py` | 52-65 | 「有 VT 才跑真编码」的 skip 写法 |
| P2 | `tests/test_packaging.py` | 1-12, 77-100 | 静态检查脚本 / spec 的断言风格 |
| P2 | `packaging/build_ffmpeg.sh` | 24-27, 54-60 | `REQUIRED_FILTERS` 自检 |
| P2 | `packaging/ai-cut.spec` | 20-37 | hiddenimports / datas |
| P2 | `research/validate_draft.py` | 51, 231-245 | 也引用 11.0 模板（本里程碑不改，见 NOT Building） |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| drawtext `textfile` / `expansion` | ffmpeg-filters 文档 · drawtext | `textfile` 从 UTF-8 文件读文字；`expansion=none` 原样输出，不解析 `%{…}` |
| 滤镜图转义 | ffmpeg-filters 文档 · Notes on filtergraph escaping | 有两层转义（选项值、滤镜图），单引号里不能转义 `'`。所以只有不经过转义的 textfile 才可靠 |
| Python `-P` | Python 3.11 命令行文档 | `-P` 不把脚本目录或 cwd 插到 `sys.path[0]`；项目要求 ≥3.11，JY venv 也是从 `sys.executable` 建的 |
| `runpy.run_module(alter_sys=True)` | Python 标准库文档 | 以 `__main__` 运行模块，`SystemExit` 原样抛出，退出码不变 |

### Phase 3 实测结论
```
KEY_INSIGHT: esc() 生成 text='it\'s, ok'，单引号内 \ 不是转义 → 引号提前闭合 → 后面的 , 被当成滤镜分隔
APPLIES_TO: Task 2
GOTCHA: 只要文字经过滤镜图解析，任何转义都不可靠；textfile + expansion=none 在 vendor 7.0 / Homebrew 9.0 上
        对 "it's, ok" "don't: stop 100%" "他说'好'%{pts}" 'x\y [a];b' 全部 rc=0

KEY_INSIGHT: 带引号的 textfile 路径如果含 ':' ',' '[' ';' 或空格，两版 ffmpeg 都会失败（Invalid argument / No such file）
APPLIES_TO: Task 2（字幕临时目录）
GOTCHA: 临时目录必须是「安全字符」路径。macOS 默认 $TMPDIR=/var/folders/xx/…/T/ 是安全的；不安全时退回 /tmp

KEY_INSIGHT: anullsrc=r=48000:cl=stereo,atrim=duration=D 作为滤镜图内的源，不需要额外的 -f lavfi 输入；
             aformat=sample_rates=48000:channel_layouts=stereo 统一声道
APPLIES_TO: Task 2
GOTCHA: build_ffmpeg.sh 的 REQUIRED_FILTERS 要加上 anullsrc、aformat（LGPL 构建默认包含，但自检要覆盖）

KEY_INSIGHT: python -P -c "import runpy,sys; sys.path.append(sys.argv.pop(1)); runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)" ROOT pipeline.x args…
             在 Homebrew 3.14、~/.aicut/venv、uv 3.12 下都能跑，任意 cwd 都行；select 解析到 lib-dynload
APPLIES_TO: Task 4
GOTCHA: 不能用 `python -m` + cwd=ROOT，因为那样仓库根会排在 sys.path[0]，packaging/ 会遮蔽 PyPI 的 packaging
        （to_jianying.py:36-39 的注释就是为了防这个）。append 到末尾才安全

KEY_INSIGHT: 无音轨素材切片（-c:a aac -ac 2 对无音轨输入不报错）→ to_jianying --dry-run 校验通过；只有预览会失败
APPLIES_TO: Task 2（只改 render_preview，不改 ensure_clips）
```

---

## Unified Discovery Table

| Category | File:Lines | Pattern | Key Snippet |
|---|---|---|---|
| Naming | `pipeline/media_io.py:19-22` | 模块级大写常量，带中文行尾注释 | `STDERR_TAIL = 800       # 失败时带回的…` |
| Naming | `pipeline/to_jianying.py:55-58` | 面向用户的文案用大写常量 | `JY_RUNNING = "剪映正在运行…"` |
| Error | `pipeline/media_io.py:87-96` | ffmpeg 失败 → `MediaError`，带 stderr 末尾 | `raise MediaError(f"ffmpeg 失败（退出码 …）：{tail}")` |
| Error | `pipeline/to_jianying.py:68-69, 694-695` | 安装类失败 → `InstallError`，`main` 统一 `sys.exit(str(exc))` | `except InstallError as exc: sys.exit(str(exc))` |
| Error | `aicut.py:49-52` | CLI 层 `die()`：记日志并打印 `[x]` | `def die(msg)` |
| Logging | `aicut.py:55-64`；`to_jianying.py:84-87` | `[·]/[✓]/[!]/[x]` 前缀 print；to_jianying 用 `warn()` 汇总 | `warn(f"…")` |
| Types | `pipeline/to_jianying.py:164-170` | 普通 dict + 类型注解，不用 dataclass | `def expected(tl: dict, …) -> dict` |
| Tests | `tests/test_media_io.py:10-13, 126-135` | 注入假 `runner` | `FakeProc` / `_probe()` |
| Tests | `tests/test_to_jianying.py:88-101` | 真 ffmpeg 生成 1 秒片段，没有 ffmpeg 就 skip | `clip` fixture |
| Tests | `tests/test_encode.py:52-60` | 没有 VT 就 skip 真编码 | `@pytest.mark.skipif(not _has_vt(), …)` |
| Config | `pyproject.toml:9-13`；`uv.lock:484-485` | pyJianYingDraft `==0.3.*`，锁定 0.3.1 | — |
| Deps | `pipeline/render_preview.py:19-23` | 脚本方式运行时 `sys.path.append(ROOT)` | `from pipeline import encode  # noqa: E402` |

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: pipeline/media_io.py:19-22
PARTIAL_TAG = ".partial-"
DONE_SUFFIX = ".done"
STDERR_TAIL = 800       # 失败时带回的 ffmpeg stderr 末尾字符数
FFMPEG_BASE = ["ffmpeg", "-y", "-loglevel", "error"]
```
```python
# SOURCE: pipeline/to_jianying.py:55-58
JY_RUNNING = "剪映正在运行，请先完全退出（Cmd+Q）再安装"
JY_MISSING = ("找不到剪映草稿库：{meta}\n"
              "请确认已安装剪映专业版并至少打开过一次；…")
```

### ERROR_HANDLING
```python
# SOURCE: pipeline/media_io.py:87-96
def run_ffmpeg(args: list[str], *, runner=subprocess.run) -> None:
    """ffmpeg <args>；非零退出抛 MediaError 并带上 stderr 末尾。"""
    try:
        r = runner([*FFMPEG_BASE, *args], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError as exc:  # 没装 ffmpeg / 不可执行
        raise MediaError(f"无法运行 ffmpeg：{exc}") from exc
    if r.returncode != 0:
        tail = (r.stderr or "").strip()[-STDERR_TAIL:]
        raise MediaError(f"ffmpeg 失败（退出码 {r.returncode}）：{tail}")
```
```python
# SOURCE: pipeline/media_io.py:110-121  —— ffprobe + 注入 runner（has_audio 照这个写）
def _probe_duration(path: Path, runner) -> float:
    try:
        r = runner([*FFPROBE_DURATION, str(path)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError:
        return 0.0
    if r.returncode != 0:
        return 0.0
```
```python
# SOURCE: pipeline/to_jianying.py:656-662
def _prepare_root(dry_run: bool) -> Path:
    """解析草稿根；要安装时先确认剪映没在跑、草稿库可用，再花几分钟拷媒体。"""
    root = resolve_draft_root()  # 每次现算：冻结版同进程多次调用、测试隔离都依赖这一点
    if not dry_run:
        _ensure_not_running()
        load_registry(root)
    return root
```

### LOGGING_PATTERN
```python
# SOURCE: pipeline/to_jianying.py:84-87
def warn(msg: str) -> None:
    """打印并记入汇总：成功时 aicut 会把汇总里的每条再报一次，免得淹没在日志里。"""
    print(f"[warn] {msg}")
    _WARNINGS.append(msg)
```
```python
# SOURCE: aicut.py:666-668  —— 子进程报告里的警告由 aicut 再报一次
    report = to_jianying.parse_report(out)
    for w in report["warnings"]:
        warn(w)
```

### REPOSITORY_PATTERN（产物原子写）
```python
# SOURCE: aicut.py:587-600
def ensure_preview(vdir: Path, tl_hash: str) -> Path:
    """预览片：哈希一致且有完成标记才复用；渲染写临时文件，成功才改名（GL-15）。"""
    ...
    try:
        with media_io.atomic_output(preview) as tmp:
            _run_pipeline("pipeline.render_preview", [str(vdir / "timeline.json"), "-o", str(tmp)])
    except media_io.MediaError as exc:
        die(f"预览片渲染失败：{exc}")
```

### SERVICE_PATTERN（开发态 / 打包态两种运行方式）
```python
# SOURCE: aicut.py:144-157
def _run_pipeline(module: str, argv: list[str]) -> None:
    """跑一个 pipeline 脚本：开发用子进程，打包后同进程导入。"""
    if proc.FROZEN:
        code, out = proc.run_inprocess(module, argv)
        ...
    script = str(PIPELINE / (module.split(".")[-1] + ".py"))      # ← KI-15 触发点
    r = subprocess.run([sys.executable, script, *argv], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
```
```python
# SOURCE: pipeline/proc.py:116-123
def module_cmd(module_name: str, args: list[str]) -> list[str]:
    if module_name not in ALLOWED_MODULES:
        raise ValueError(f"不允许以子进程运行的模块：{module_name}")
    if FROZEN:
        return [sys.executable, MODULE_FLAG, module_name, *args]
    script = app_root().joinpath(*module_name.split(".")).with_suffix(".py")   # ← KI-15
    return [sys.executable, str(script), *args]
```

### TEST_STRUCTURE
```python
# SOURCE: tests/test_to_jianying.py:420-433
def _run_main(tmp_path, tl_file, *extra):
    return proc.run_inprocess("pipeline.to_jianying",
                              [str(tl_file), "--name", "T", "--staging", str(tmp_path / "stg"),
                               *extra])

def test_frozen_path_reports_missing_jianying(tmp_path, monkeypatch):
    tl = _timeline_file(tmp_path, text_timeline([{"text": "a", "start": 0.0, "end": 1.0, **SUB}]))
    monkeypatch.setattr(tj, "jianying_running", lambda: False)
    code, out = _run_main(tmp_path, tl)
    assert code == 1 and "找不到剪映草稿库" in out
    assert not (tmp_path / "stg" / "T").exists(), "确认剪映在之前不该先花时间生成草稿"
```
```python
# SOURCE: tests/test_media_io.py:126-135
def _probe(duration):
    def runner(args, **kw):
        if duration is None:
            return FakeProc(1, "Invalid data found when processing input")
        p = FakeProc(0)
        p.stdout = f"{duration}\n"
        return p
    return runner
```
```python
# SOURCE: tests/test_aicut_build.py:208-210
def _frozen(monkeypatch, code, out):
    monkeypatch.setattr(aicut.proc, "FROZEN", True)
    monkeypatch.setattr(aicut.proc, "run_inprocess", lambda m, argv: (code, out))
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/render_preview.py` | UPDATE | KI-13/76：用 textfile 写字幕；KI-14：补静音轨并统一声道；ffmpeg 失败改走 `media_io.run_ffmpeg` |
| `pipeline/media_io.py` | UPDATE | 新增 `has_audio()`（ffprobe，可注入 runner） |
| `packaging/build_ffmpeg.sh` | UPDATE | `REQUIRED_FILTERS` 加上 `anullsrc aformat` |
| `pipeline/proc.py` | UPDATE | 新增 `dev_module_cmd()`；`module_cmd` 开发分支改用它（KI-15） |
| `aicut.py` | UPDATE | `_run_pipeline` / `install_draft` 改用 `proc.dev_module_cmd`，删除 `PIPELINE`（KI-15）；`run` 加 build 参数（KI-16）；`cmd_export` 打印警告（KI-18）。净增 ≤ 5 行 |
| `pipeline/jy_version.py` | CREATE | KI-17：已验证版本、模板路径、读取已装剪映版本、跨大版本警告 |
| `pipeline/to_jianying.py` | UPDATE | KI-17：用 jy_version 常量；KI-18：模板缺失改为失败；KI-59：同名草稿在拷媒体前就检查 |
| `pipeline/export_draft.py` | UPDATE | KI-18：成功时解析并返回警告；KI-15：开发分支用 `-P` 引导（经 `module_cmd`） |
| `packaging/build_package.py` | UPDATE | KI-18：BAT / PS1 如实报告失败；KI-64：`zip_pkg` 不再打印 |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 加 `pipeline.jy_version` |
| `pipeline/to_jianying.py`、`junk_detect.py`、`format_transcript.py`、`render_preview.py` 模块文档字符串 | UPDATE | 用法改成 `python -m pipeline.xxx`（KI-15，只改文档） |
| `tests/test_render_preview.py` | CREATE | KI-13/14/76 单元测试 + 真 ffmpeg 集成测试 |
| `tests/test_media_io.py` | UPDATE | `has_audio` |
| `tests/test_proc.py` | UPDATE | `dev_module_cmd` + 遮蔽复现；改写 `test_module_cmd_dev_runs_script` |
| `tests/test_aicut_build.py` | UPDATE | KI-15（`_run_pipeline` / `install_draft` 的命令形态）、KI-16 |
| `tests/test_to_jianying.py` | UPDATE | KI-18 模板缺失、KI-59、KI-17 版本警告接线 |
| `tests/test_jy_version.py` | CREATE | KI-17 |
| `tests/test_jianying_golden.py` + `tests/golden/jianying_draft_shape.json` | CREATE | KI-17 黄金草稿回归 |
| `tests/test_export_draft.py` | UPDATE | KI-18 警告透传、KI-64、开发分支命令形态 |
| `tests/test_packaging.py` | UPDATE | KI-18 BAT / PS1、REQUIRED_FILTERS、spec |
| `docs/known-issues.md`、`.claude/prds/ai-cut-go-live.prd.md` | UPDATE（提交后） | 状态列填提交号；第 7 行改为 complete（按 M1–M5 的惯例） |

## NOT Building

- 不改 `ensure_clips` 给无音轨切片补音轨。剪映草稿不需要，只修预览这一处，少一次重新编码。
- 不重命名 `pipeline/select.py` / `pipeline/secrets.py`。理由见 Notes 的「备选方案」。
- 不改字体选择（KI-73 属 M6）、不改字幕截断或分卡（KI-01 属 M6）。
- 不改 `research/validate_draft.py` 里的 11.0 引用（研究脚本，单独可运行，不影响结论）。
- 不把 `platform.app_version` 改成探测到的版本（没验证过；见 D3）。
- 不固定 `ensure_jy_python` 里的 `pip install pyJianYingDraft` 版本（KI-34 属 M9）。
- 不改 `INSTALL.bat` 覆盖同名草稿的 `rd /s /q` 行为（不在任何 KI 里，见 Notes「观察」）。
- 不给 ffmpeg 加超时（KI-61）、不改 `aicut.run` 的 stderr 丢失问题（KI-20）、不拆 `aicut.py`（KI-55）。
- 不做 Windows 实机自动化测试；BAT 只做静态断言，再加一条人工验证。

---

## Step-by-Step Tasks

> 每个 Task 先写测试，跑一遍确认 RED（失败原因要和缺陷对得上），再实现到 GREEN。全程 `uv run pytest`，基线 987 passed。

### Task 1: RED —— 预览渲染测试（KI-13 / KI-14 / KI-76）
- **ACTION**: 新建 `tests/test_render_preview.py`；在 `tests/test_media_io.py` 加 `has_audio` 用例。
- **IMPLEMENT**:
  ```python
  """pipeline/render_preview：特殊字幕（KI-13/KI-76）、无音轨与声道统一（KI-14）。"""
  import shutil, subprocess, json
  from pathlib import Path
  import pytest
  from pipeline import media_io, proc
  from pipeline import render_preview as rp

  NASTY = ["it's, ok", "don't: stop 100%", "他说'好'%{pts}", "x\\y [a];b"]

  def tl(texts=(), n=1):
      return {"project": {"width": 320, "height": 240, "fps": 30},
              "video": [{"source": f"/m/{i}.mp4", "in": 0.0, "out": 1.0, "timeline_in": float(i)}
                        for i in range(n)],
              "text": [{"text": t, "start": 0.0, "end": 1.0, "style": {"align": 2}} for t in texts]}

  def test_subtitle_files_keep_text_verbatim(tmp_path):
      paths = rp.subtitle_files(tl(NASTY)["text"], tmp_path)
      assert [p.read_text(encoding="utf-8") for p in paths] == NASTY   # 原样，无转义、无换行

  def test_build_uses_textfile_without_expansion(tmp_path):
      t = tl(NASTY)
      fc, _ = rp.build(t, text_paths=rp.subtitle_files(t["text"], tmp_path), has_audio=[True])
      assert "text='" not in fc and fc.count("expansion=none") == len(NASTY)
      assert all(s not in fc for s in NASTY)                          # 文字不进滤镜图

  def test_build_fills_silence_for_input_without_audio():
      fc, _ = rp.build(tl(n=2), text_paths=[], has_audio=[False, True])
      assert "[0:a]" not in fc and "anullsrc=r=48000:cl=stereo" in fc and "[1:a]" in fc
      assert fc.count("aformat=sample_rates=48000:channel_layouts=stereo") == 2

  def test_text_dir_falls_back_when_tmp_has_filter_metachars(monkeypatch):
      monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "/var/x:y")
      assert rp.text_dir_base() == "/tmp"
  ```
  另加真 ffmpeg 集成用例：`@pytest.mark.skipif(not _has_vt_and_drawtext())`（照 `tests/test_encode.py:52-57` 写，再加一条 `"drawtext" in ffmpeg -filters`）。用 `subprocess.run(["ffmpeg", …])` 现做 3 个 1 秒片段：无音轨（`color` + `-c:v mpeg4`）、单声道 44.1k（`sine … -ac 1`）、5.1（`pan=5.1|c0=c0`），再写 timeline（含 `NASTY` 字幕），然后 `proc.run_inprocess("pipeline.render_preview", [tl, "-o", out])` → `code == 0`；用 `ffprobe -show_entries stream=codec_type,channel_layout,sample_rate` 断言只有一条音轨，且为 `stereo,48000`。另外一条用例：source 文件不存在 → `code == 1`，输出里有「预览片渲染失败」。
  `tests/test_media_io.py`：
  ```python
  def _streams(stdout, code=0):
      def runner(args, **kw):
          assert "-select_streams" in args and "a" in args
          p = FakeProc(code, "boom" if code else ""); p.stdout = stdout
          return p
      return runner

  def test_has_audio_true_when_ffprobe_lists_stream(tmp_path):
      assert mio.has_audio(tmp_path / "a.mp4", runner=_streams("1\n"))
  def test_has_audio_false_when_no_audio_stream(tmp_path):
      assert not mio.has_audio(tmp_path / "a.mp4", runner=_streams(""))
  def test_has_audio_unreadable_is_media_error(tmp_path):
      with pytest.raises(mio.MediaError, match="读不了素材"):
          mio.has_audio(tmp_path / "a.mp4", runner=_streams("", code=1))
  ```
- **MIRROR**: TEST_STRUCTURE（`_probe` 假 runner；`clip` fixture 的真 ffmpeg 写法）
- **IMPORTS**: 见上
- **GOTCHA**: 集成用例里的 timeline 宽高要用 320×240，不然 VT 编码慢；`render_preview` 在开发环境走 PATH 上的 `ffmpeg`（本机是 Homebrew 9.0），打包版走 vendor。两版都已手工验证过，测试只跑 PATH 上那个。
- **VALIDATE**: `uv run pytest tests/test_render_preview.py tests/test_media_io.py` → 新用例 RED（`AttributeError: subtitle_files / has_audio`；集成用例报 ffmpeg 失败）

### Task 2: GREEN —— 实现 `render_preview` + `media_io.has_audio`
- **ACTION**: 改 `pipeline/render_preview.py`；在 `pipeline/media_io.py` 末尾加 `has_audio`；在 `packaging/build_ffmpeg.sh:26` 加滤镜。
- **IMPLEMENT**:
  ```python
  # pipeline/media_io.py
  FFPROBE_AUDIO = ["ffprobe", "-v", "error", "-select_streams", "a",
                   "-show_entries", "stream=index", "-of", "csv=p=0"]

  def has_audio(path: Path, *, runner=subprocess.run) -> bool:
      """素材有没有音轨；ffprobe 读不了 → MediaError（不当作「没音轨」糊过去）。"""
      try:
          r = runner([*FFPROBE_AUDIO, str(path)], capture_output=True, text=True,
                     encoding="utf-8", errors="replace")
      except OSError as exc:
          raise MediaError(f"无法运行 ffprobe：{exc}") from exc
      if r.returncode != 0:
          raise MediaError(f"读不了素材 {Path(path).name}：{(r.stderr or '').strip()[-STDERR_TAIL:]}")
      return bool((r.stdout or "").strip())
  ```
  ```python
  # pipeline/render_preview.py（删掉 esc；main 不再用 subprocess.run(check=True)）
  import re, tempfile
  from pipeline import encode, media_io  # noqa: E402

  SAMPLE_RATE = 48000
  AUDIO_NORM = f"aresample={SAMPLE_RATE},aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
  SAFE_FILTER_PATH = re.compile(r"[A-Za-z0-9/._-]+")  # 滤镜图里不用转义就能放的路径
  FALLBACK_TMP = "/tmp"
  TEXT_DIR_PREFIX = "aicut-preview-"

  def text_dir_base() -> str:
      """字幕文件放哪：$TMPDIR 含滤镜图元字符（: , [ ; 空格 …）时退回 /tmp（Phase 3 实测）。"""
      base = tempfile.gettempdir()
      return base if SAFE_FILTER_PATH.fullmatch(base) else FALLBACK_TMP

  def subtitle_files(texts: list[dict], text_dir: Path) -> list[Path]:
      """每条字幕写成一个 UTF-8 文件（按 start 排序），drawtext 用 textfile 读入，不经过任何转义（KI-13/KI-76）。"""
      out = []
      for i, t in enumerate(sorted(texts, key=lambda x: x["start"])):
          p = Path(text_dir) / f"{i}.txt"
          p.write_text(t["text"], encoding="utf-8")
          out.append(p)
      return out

  def _audio_branch(i: int, s: dict, dur: float, has: bool) -> str:
      src = (f"[{i}:a]atrim=start={s['in']}:duration={dur},asetpts=PTS-STARTPTS"
             if has else f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={dur}")  # KI-14：无音轨补静音
      return f"{src},{AUDIO_NORM}[a{i}]"
  ```
  `build(tl, *, text_paths: list[Path], has_audio: list[bool]) -> tuple[str, int]`：视频分支不变；音频分支改用 `_audio_branch`；drawtext 那行改成
  `f"{chain}drawtext=fontfile='{pick_font()}':textfile='{path}':expansion=none:"`（`path` 来自 `text_paths[i]`，与排序后的 `tl["text"]` 一一对应，后面 fontsize 等保持原样）。
  `main()`：
  ```python
      tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
      segs = sorted(tl["video"], key=lambda s: s["timeline_in"])
      try:
          audio = [media_io.has_audio(Path(s["source"])) for s in segs]
          with tempfile.TemporaryDirectory(prefix=TEXT_DIR_PREFIX, dir=text_dir_base()) as tmp:
              fc, n = build(tl, text_paths=subtitle_files(tl.get("text", []), Path(tmp)),
                            has_audio=audio)
              inputs = [a for s in segs for a in ("-i", s["source"])]
              print(f"渲染 {n} 个镜头 → {args.out}")
              media_io.run_ffmpeg([*inputs, "-filter_complex", fc, "-map", "[vout]", "-map", "[ac]",
                                   *encode.h264_args("preview"), "-c:a", "aac", "-b:a", "192k",
                                   "-movflags", "+faststart", args.out])
      except media_io.MediaError as exc:
          sys.exit(f"预览片渲染失败：{exc}")
  ```
  `build_ffmpeg.sh:26`：`REQUIRED_FILTERS="drawtext … aresample format anullsrc aformat"`。
- **MIRROR**: ERROR_HANDLING（`run_ffmpeg` / `_probe_duration`）、NAMING_CONVENTION
- **IMPORTS**: `re`、`tempfile`；`from pipeline import encode, media_io`；删除 `import subprocess`
- **GOTCHA**:
  - `media_io.run_ffmpeg` 已经带了 `-y -loglevel error`，输出路径放在 args 最后。
  - `test_encode.py:47-49` 要求 `render_preview.py` 里出现 `encode.h264_args(`，这一点要保留。
  - `aicut.ensure_preview` 在 `atomic_output` 里调用，`-o` 是临时文件，并且已经在 `die` 里接住了渲染失败，不用改。
  - 开发态 `_run_pipeline` 失败时只打印末尾 600 字符，打包态由 `run_inprocess` 收集 `SystemExit` 的文字。两种情况下「预览片渲染失败：…」都能看到。
  - 文本文件末尾**不要**加换行，否则 drawtext 会多渲染一行。
- **VALIDATE**: Task 1 的用例全部 GREEN；`uv run pytest tests/test_encode.py tests/test_aicut_build.py` 无回归

### Task 3: RED —— 标准库遮蔽（KI-15）
- **ACTION**: 改 `tests/test_proc.py`、`tests/test_aicut_build.py`、`tests/test_export_draft.py`
- **IMPLEMENT**:
  ```python
  # tests/test_proc.py —— 用机制复现，不依赖本机 select 是不是内建模块（uv 的 3.12 里是内建，复现不了）
  def test_dev_module_cmd_does_not_put_package_dir_first(tmp_path):
      pkg = tmp_path / "root" / "pkg"
      pkg.mkdir(parents=True)
      (pkg / "__init__.py").write_text("")
      (pkg / "json.py").write_text("raise ImportError('shadowed stdlib')\n")   # 模拟 pipeline/select.py
      (pkg / "tool.py").write_text("import json, sys\nprint(json.__file__)\nsys.exit(3)\n")
      cmd = proc.dev_module_cmd(sys.executable, "pkg.tool", [], root=tmp_path / "root")
      r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
      assert r.returncode == 3, r.stderr                # 退出码原样透传
      assert "pkg" not in r.stdout                      # 拿到的是标准库 json

  def test_module_cmd_dev_uses_bootstrap(monkeypatch):     # 替换 test_module_cmd_dev_runs_script
      monkeypatch.setattr(proc, "FROZEN", False)
      cmd = proc.module_cmd("pipeline.to_jianying", ["a"])
      assert cmd[:2] == [sys.executable, "-P"] and cmd[-2:] == ["pipeline.to_jianying", "a"]
      assert not any(str(c).endswith(".py") for c in cmd)

  @pytest.mark.skipif(not _python_with_dynamic_select(), reason="需要 select 不是内建模块的 Python（如 Homebrew）")
  def test_render_preview_help_runs_under_homebrew_python():
      py = _python_with_dynamic_select()
      r = subprocess.run(proc.dev_module_cmd(py, "pipeline.render_preview", ["--help"]),
                         capture_output=True, text=True)
      assert r.returncode == 0, r.stderr
  ```
  `_python_with_dynamic_select()`：在 `("/opt/homebrew/bin/python3", "/usr/local/bin/python3")` 里找一个存在的，并且满足 `python -c "import sys;print('select' in sys.builtin_module_names)"` 输出 `False` 且版本 ≥3.11，找不到返回 `None`。
  `tests/test_aicut_build.py`：
  ```python
  def test_run_pipeline_dev_uses_bootstrap_not_script_path(monkeypatch):
      monkeypatch.setattr(aicut.proc, "FROZEN", False)
      seen = {}
      def fake_run(cmd, **kw):
          seen["cmd"] = cmd
          return aicut.subprocess.CompletedProcess(cmd, 0, "", "")
      monkeypatch.setattr(aicut.subprocess, "run", fake_run)
      aicut._run_pipeline("pipeline.render_preview", ["t.json", "-o", "o.mp4"])
      assert seen["cmd"][1] == "-P" and "pipeline.render_preview" in seen["cmd"]
      assert not any(str(c).endswith("render_preview.py") for c in seen["cmd"])
  ```
  `install_draft` 也照这样写一条（`ensure_jy_python` 打桩返回 `"py"` → `cmd[0] == "py" and cmd[1] == "-P"`）。
  `tests/test_export_draft.py:124-133` 的 `test_build_dev_runs_to_jianying_script` 改成断言 `seen["argv"][1] == "-P"` 并且 `"pipeline.to_jianying" in seen["argv"]`。
- **MIRROR**: TEST_STRUCTURE
- **GOTCHA**: `tests/test_proc.py` 需要 `import subprocess`（看一下文件头，没有就补上）。
- **VALIDATE**: 新用例 RED（`AttributeError: dev_module_cmd`；命令里还是 `.py` 路径）

### Task 4: GREEN —— `proc.dev_module_cmd` 与调用方
- **ACTION**: 改 `pipeline/proc.py`、`aicut.py`；更新 4 个 pipeline 脚本文档字符串里的用法
- **IMPLEMENT**:
  ```python
  # pipeline/proc.py
  # 开发态跑 pipeline 模块：-P 不把脚本目录放进 sys.path[0]（否则 pipeline/select.py、secrets.py 会遮蔽
  # 标准库，Homebrew Python 下 subprocess → import select 直接崩，KI-15）；仓库根 append 到末尾，
  # 免得仓库根的 packaging/ 遮蔽 PyPI 的 packaging。
  DEV_BOOTSTRAP = ("import runpy, sys; sys.path.append(sys.argv.pop(1)); "
                   "runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)")

  def dev_module_cmd(python: str, module_name: str, args: list[str],
                     root: Path | None = None) -> list[str]:
      """开发态以 __main__ 跑 module_name 的 argv（任意 cwd 可用，相对路径参数含义不变）。"""
      return [python, "-P", "-c", DEV_BOOTSTRAP, str(root or app_root()), module_name, *args]

  def module_cmd(module_name: str, args: list[str]) -> list[str]:
      ...
      if FROZEN:
          return [sys.executable, MODULE_FLAG, module_name, *args]
      return dev_module_cmd(sys.executable, module_name, args)
  ```
  `aicut.py:150-152` → `r = subprocess.run(proc.dev_module_cmd(sys.executable, module, argv), capture_output=True, …)`；
  `aicut.py:660` → `subprocess.run(proc.dev_module_cmd(ensure_jy_python(), "pipeline.to_jianying", argv), …)`；
  删除 `aicut.py:42` 的 `PIPELINE`（这里改完后没有别的引用，先 `grep -n PIPELINE aicut.py` 确认）。
  文档字符串：`render_preview.py:8-9`、`to_jianying.py:17-19`、`junk_detect.py:11-12`、`format_transcript.py:13` 改成 `python -m pipeline.xxx …`（在仓库根运行）。
- **MIRROR**: SERVICE_PATTERN
- **IMPORTS**: 无新增（`proc` 已有 `Path`、`sys`）
- **GOTCHA**:
  - `-P` 需要 Python ≥3.11。`pyproject` 要求 `>=3.11`，JY venv 由 `sys.executable` 创建，所以都满足。`ensure_jy_python` 里旧的 3.10 venv 如果还在，会报 `Unknown option: -P`，这一条写进 Risks。
  - `alter_sys=True` 会把 `sys.argv[0]` 改成模块路径，所以 argparse 的 prog 显示成 `render_preview.py`，没关系。
  - `ALLOWED_MODULES` 只约束 `module_cmd`；`dev_module_cmd` 只有开发态用到，不需要白名单。
- **VALIDATE**: Task 3 GREEN；`uv run pytest tests/test_proc.py tests/test_aicut_build.py tests/test_export_draft.py`；手动执行 `/opt/homebrew/bin/python3 -P -c "<DEV_BOOTSTRAP>" $PWD pipeline.to_jianying --help`，退出码 0

### Task 5: RED → GREEN —— `aicut run` 参数（KI-16）
- **ACTION**: 先在 `tests/test_aicut_build.py` 写测试，再改 `aicut.py` 解析器
- **IMPLEMENT**:
  ```python
  # 测试
  def test_run_with_shots_reaches_build_with_build_options(project, monkeypatch):
      (project / "shots.json").write_text('{"shots": []}', encoding="utf-8")
      for step in ("cmd_ingest", "cmd_transcribe", "cmd_junk", "cmd_brief"):
          monkeypatch.setattr(aicut, step, lambda a: None)
      seen = []
      monkeypatch.setattr(aicut, "cmd_build", lambda a: seen.append((a.version, a.no_draft)))
      aicut.main(["run", "p"])
      aicut.main(["run", "p", "--version", "v2", "--no-draft"])
      assert seen == [(None, False), ("v2", True)]
  ```
  ```python
  # aicut.py：抽出 build 选项，build / run 共用
  def _add_build_options(p) -> None:
      p.add_argument("--version"); p.add_argument("--no-draft", action="store_true")
  ```
  把 `run` 从 `aicut.py:866-869` 的循环里拿出来，单独 `add_parser("run")` + `_add_build_options(p)`；`build`（`:904-907`）也改成调用 `_add_build_options`。顶部 docstring 第 19 行附近把 `run` 的用法补上 `[--version v2] [--no-draft]`。
- **MIRROR**: `aicut.py:852-907` 现有的解析器写法（`p = sub.add_parser(...); p.add_argument(...); p.set_defaults(fn=...)`）
- **GOTCHA**: 测试里 `project` 夹具已经把 `PROJECTS` 指向 tmp；`cmd_run` 用 `project_dir(args.name)`，项目名 `p` 是合法的。
- **VALIDATE**: 改之前 RED（`AttributeError: 'Namespace' object has no attribute 'version'`），改之后 GREEN

### Task 6: RED —— 剪映导出健壮（KI-17 / KI-18① / KI-59）
- **ACTION**: 新建 `tests/test_jy_version.py`；在 `tests/test_to_jianying.py` 加用例
- **IMPLEMENT**:
  ```python
  # tests/test_jy_version.py
  import plistlib
  from pipeline import jy_version as jv

  def fake_app(tmp_path, version):
      app = tmp_path / "VideoFusion-macOS.app"
      (app / "Contents").mkdir(parents=True)
      (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))
      return app

  def test_installed_version_reads_info_plist(tmp_path):
      assert jv.installed_version([fake_app(tmp_path, "11.6.0")]) == "11.6.0"
  def test_installed_version_none_when_missing_or_corrupt(tmp_path):
      bad = tmp_path / "X.app/Contents"; bad.mkdir(parents=True); (bad / "Info.plist").write_text("garbage")
      assert jv.installed_version([tmp_path / "nope.app", tmp_path / "X.app"]) is None
  @pytest.mark.parametrize("v,warns", [("11.6.0", False), ("11.0.0", False), ("12.0.1", True),
                                       ("10.8.0", True), (None, False), ("abc", False)])
  def test_compat_warning_only_on_major_change(v, warns):
      assert (jv.compat_warning(v) is not None) == warns
  def test_template_is_the_verified_version_and_exists():
      assert jv.TEMPLATE.name == f"base_template_{jv.VERIFIED_SERIES}.json" and jv.TEMPLATE.exists()
  ```
  ```python
  # tests/test_to_jianying.py
  def test_missing_template_fails_before_generating(tmp_path, clip, monkeypatch):   # KI-18①
      monkeypatch.setattr(tj, "TEMPLATE", tmp_path / "nope.json")
      code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)), "--dry-run")
      assert code == 1 and "骨架模板" in out and "nope.json" in out
      assert not (tmp_path / "stg" / "T").exists()

  def test_same_name_draft_rejected_before_copying_media(tmp_path, jy_root, clip, monkeypatch):  # KI-59
      (jy_root / "T").mkdir(); (jy_root / "T" / "keep.txt").write_text("x")
      monkeypatch.setattr(tj, "bundle_media", lambda *a: pytest.fail("不该先拷媒体"))
      code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
      assert code == 1 and "草稿已存在" in out
      assert not (tmp_path / "stg" / "T").exists() and (jy_root / "T" / "keep.txt").exists()

  def test_own_orphan_does_not_block_precheck(tmp_path, jy_root, clip):              # KI-59 边界
      (jy_root / "T").mkdir(); (jy_root / "T" / tj.INSTALL_MARKER).write_text("T")
      code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
      assert code == 0, out

  def test_major_version_mismatch_is_reported_as_warning(tmp_path, jy_root, clip, monkeypatch):  # KI-17
      monkeypatch.setattr(tj.jy_version, "installed_version", lambda *a: "12.0.0")
      code, out = _run_main(tmp_path, _timeline_file(tmp_path, full_timeline(clip)))
      assert code == 0, out
      assert any("12.0.0" in w for w in tj.parse_report(out)["warnings"])

  def test_platform_app_version_comes_from_jy_version(tmp_path, jy_root, clip):
      d, _, _, _ = staged(tmp_path, jy_root, clip)
      assert _content(d)["platform"]["app_version"] == tj.jy_version.VERIFIED_VERSION
  ```
  另外在 `tests/conftest.py` 加一个 autouse fixture `_no_real_jianying_version`，把 `jy_version.installed_version` 打桩成 `lambda *a: None`，避免开发机上装的剪映版本影响测试，做法同 `_isolate_jianying`。`test_jy_version.py` 直接调用模块函数并显式传入 candidates，不受这个打桩影响。打桩要用 `monkeypatch.setattr(jy_version, "installed_version", …)`，并且 `to_jianying` 必须通过 `jy_version.installed_version()` 调用，不能 `from … import`。
- **MIRROR**: TEST_STRUCTURE（`_run_main` / `jy_root` / `clip`）
- **GOTCHA**: `test_installed_version_none_when_missing_or_corrupt` 直接调用真函数，所以 conftest 的打桩不能作用于 `test_jy_version.py`：在 fixture 里判断 `request.node.module.__name__.endswith("test_jy_version")` 时跳过，或者先存一份原函数 `jv._installed_version_impl` 给测试用。推荐前者，更简单。
- **VALIDATE**: 全部 RED（`ModuleNotFoundError: pipeline.jy_version`；模板缺失时 code==0；同名时 `bundle_media` 被调用）

### Task 7: GREEN —— `pipeline/jy_version.py` + `to_jianying` 改动
- **ACTION**: 新建模块；改 `to_jianying.py`；spec 的 hiddenimports 加 `"pipeline.jy_version"`
- **IMPLEMENT**:
  ```python
  # pipeline/jy_version.py
  # -*- coding: utf-8 -*-
  """剪映版本的唯一来源（KI-17）：已验证版本、对应的草稿骨架模板、读取本机已装剪映的版本。

  pyJianYingDraft 0.3.1 只声明支持到剪映 10.8；我们用剪映 11.0 自己写出的空草稿做骨架（align_with_template），
  并由 tests/test_jianying_golden.py 固定生成结果的结构。剪映跨大版本时提醒，不阻断（产品默认 D2）。
  """
  from __future__ import annotations

  import plistlib
  from pathlib import Path

  ROOT = Path(__file__).resolve().parent.parent
  VERIFIED_VERSION = "11.0.0"          # 模板来源，也是写进草稿的 platform.app_version
  VERIFIED_SERIES = "11.0"
  TEMPLATE = ROOT / "research" / f"base_template_{VERIFIED_SERIES}.json"
  APP_CANDIDATES = (Path("/Applications/VideoFusion-macOS.app"),
                    Path.home() / "Applications/VideoFusion-macOS.app")
  VERSION_KEY = "CFBundleShortVersionString"
  MAJOR_MISMATCH = ("本机剪映版本 {found} 与已验证的 {series}.x 不同：草稿已通过静态校验，"
                    "若打开异常请导出诊断包反馈")

  def installed_version(candidates=APP_CANDIDATES) -> str | None:
      """读剪映 App 的 Info.plist；没装 / 读不了返回 None（剪映在不在由注册表检查负责）。"""
      for app in candidates:
          try:
              with open(Path(app) / "Contents/Info.plist", "rb") as f:
                  v = plistlib.load(f).get(VERSION_KEY)
          except (OSError, plistlib.InvalidFileException, ValueError):
              continue
          if isinstance(v, str) and v:
              return v
      return None

  def _major(v: str) -> int | None:
      head = v.split(".", 1)[0]
      return int(head) if head.isdigit() else None

  def compat_warning(found: str | None) -> str | None:
      if not found or _major(found) is None or _major(found) == _major(VERIFIED_VERSION):
          return None
      return MAJOR_MISMATCH.format(found=found, series=VERIFIED_SERIES.split(".")[0])
  ```
  `to_jianying.py`：
  - `:41` 改成 `from pipeline import jy_version, schema  # noqa: E402`；`:53` 改成 `TEMPLATE = jy_version.TEMPLATE`，保留 `TEMPLATE` 这个名字，测试会 monkeypatch 它。
  - 新增文案常量：`TEMPLATE_MISSING = "找不到剪映 {series} 草稿骨架模板：{path}（安装包不完整，请重新安装；开发环境请检查 research/）"`；`DRAFT_EXISTS = "草稿已存在：{target}（换名字，或先在剪映里删除）"`，`install()` 里也用它，测试里匹配「已存在」的断言照样能过。
  - `align_with_template`（`:303-305`）：`if not template.exists(): raise InstallError(TEMPLATE_MISSING.format(...))`。docstring 里的「11.0」改成引用 `jy_version.VERIFIED_SERIES`。
  - `macify`（`:325`）：`"app_version": jy_version.VERIFIED_VERSION`。
  - 新增：
    ```python
    def _is_own_orphan(target: Path, registry: dict) -> bool:
        return (target / INSTALL_MARKER).exists() and not _is_registered(registry, target)

    def _ensure_name_free(root: Path, name: str, registry: dict) -> None:
        """同名草稿要在拷媒体之前就报（KI-59）；上次被强杀留下的自家孤儿不算，install() 会清掉。"""
        target = root / name
        if target.exists() and not _is_own_orphan(target, registry):
            raise InstallError(DRAFT_EXISTS.format(target=target))
    ```
    `_clear_own_orphan` 改成复用 `_is_own_orphan`；`install()` 里 `:623-624` 改成 `_ensure_name_free(root, name, registry)`（放在清理孤儿之后，行为和现在一样）。
  - `_prepare_root(dry_run, name)`：
    ```python
    root = resolve_draft_root()
    if not TEMPLATE.exists():                       # KI-18：拷媒体之前就失败（dry-run 也是）
        raise InstallError(TEMPLATE_MISSING.format(series=jy_version.VERIFIED_SERIES, path=TEMPLATE))
    if not dry_run:
        _ensure_not_running()
        _ensure_name_free(root, name, load_registry(root))
        if note := jy_version.compat_warning(jy_version.installed_version()):
            warn(note)                              # KI-17：进警告汇总，aicut 会再报一次
    return root
    ```
    `main()` 里 `:677` 改成 `_prepare_root(args.dry_run, name)`。
  - 模块文档字符串第 5 行改成「已验证：剪映专业版 {VERIFIED_SERIES}（见 pipeline/jy_version.py）」，不要再写死。
- **MIRROR**: ERROR_HANDLING（`InstallError` → `main` 里 `sys.exit`）、LOGGING_PATTERN（`warn`）
- **IMPORTS**: `plistlib`（标准库）
- **GOTCHA**:
  - `_prepare_root` 在 `reset_warnings()` 之后调用，`warn` 会进当次的汇总（`to_jianying.py:674-677`）。
  - 冻结版里 `jy_version.ROOT` = `_MEIPASS`，spec 已经把模板放在 `research/` 下（`ai-cut.spec:35`），路径一致。
  - `test_install_never_touches_user_folder_with_same_name`（`tests/test_to_jianying.py:218-226`）直接调用 `install()`，仍然要求「已存在」，并且 `d.exists()`，这条要保持通过。
- **VALIDATE**: Task 6 GREEN；`uv run pytest tests/test_to_jianying.py tests/test_jy_version.py tests/test_validate_draft.py tests/test_packaging.py`

### Task 8: 黄金草稿回归（KI-17）
- **ACTION**: 新建 `tests/test_jianying_golden.py` 和 `tests/golden/jianying_draft_shape.json`
- **IMPLEMENT**:
  ```python
  """剪映草稿黄金回归（KI-17）：固定 pyJianYingDraft 0.3.1 + 11.0 骨架生成结果的结构。

  只比「结构」（键路径 + 值类型 + 关键版本字段 + 轨道/素材计数），不比 id、时间戳、路径、时长数值。
  有意升级 pyJianYingDraft 或模板时：AICUT_UPDATE_GOLDEN=1 uv run pytest tests/test_jianying_golden.py，
  然后人工审阅 git diff，并在剪映 Mac / Windows 实机打开一次再提交。
  """
  import importlib.metadata, json, os, tomllib
  from pathlib import Path
  import pytest
  from pipeline import proc
  from tests.test_to_jianying import clip, full_timeline, SUB, CARD  # noqa: F401  复用夹具

  GOLDEN = Path(__file__).parent / "golden" / "jianying_draft_shape.json"
  ROOT = Path(__file__).resolve().parent.parent

  def shape(obj, path="$") -> set[str]:
      if isinstance(obj, dict):
          return {f"{path}:dict"}.union(*(shape(v, f"{path}.{k}") for k, v in obj.items()))
      if isinstance(obj, list):
          return {f"{path}:list"}.union(*(shape(v, f"{path}[]") for v in obj))
      return {f"{path}:{type(obj).__name__}"}

  def snapshot(d: Path) -> dict:
      content = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
      meta = json.loads((d / "draft_meta_info.json").read_text(encoding="utf-8"))
      return {"pyjianyingdraft": importlib.metadata.version("pyJianYingDraft"),
              "version": content["version"], "new_version": content["new_version"],
              "app_version": content["platform"]["app_version"],
              "tracks": [[t["type"], t.get("name", ""), len(t["segments"])] for t in content["tracks"]],
              "materials_nonempty": {k: len(v) for k, v in sorted(content["materials"].items())
                                     if isinstance(v, list) and v},
              "content_shape": sorted(shape(content)), "meta_shape": sorted(shape(meta))}

  def test_draft_matches_golden(tmp_path, clip):
      tl = tmp_path / "timeline.json"
      tl.write_text(json.dumps(full_timeline(clip, [
          {"text": "他说'好'，100%", "start": 0.0, "end": 0.6, **SUB},
          {"text": "卡", "start": 0.0, "end": 0.8, **CARD}]), ensure_ascii=False), encoding="utf-8")
      code, out = proc.run_inprocess("pipeline.to_jianying", [str(tl), "--name", "G",
                                     "--staging", str(tmp_path / "stg"), "--dry-run"])
      assert code == 0, out
      got = snapshot(tmp_path / "stg" / "G")
      if os.environ.get("AICUT_UPDATE_GOLDEN") == "1":
          GOLDEN.parent.mkdir(exist_ok=True)
          GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
          pytest.skip("已重写黄金快照，请人工审阅 diff")
      assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))

  def test_lockfile_pins_the_golden_library_version():
      lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
      pinned = next(p["version"] for p in lock["package"] if p["name"] == "pyjianyingdraft")
      assert pinned == json.loads(GOLDEN.read_text(encoding="utf-8"))["pyjianyingdraft"]
  ```
  第一次生成：`AICUT_UPDATE_GOLDEN=1 uv run pytest tests/test_jianying_golden.py`，然后检查快照：`version == 360000`、`new_version == "75.0.0"`（来自 11.0 模板）、`app_version == "11.0.0"`、`tracks` 为 video + `subtitle` + `card`。
- **MIRROR**: TEST_STRUCTURE（`clip` 夹具；`run_inprocess` 跑 main）
- **GOTCHA**:
  - 从别的测试模块导入夹具，pytest 是认的（导入后就成为本模块的 fixture）。如果实现时发现有问题，就把 `clip` / `full_timeline` 挪到 `tests/conftest.py`；那样会改动 `test_to_jianying.py` 的导入，也可以接受。
  - `shape` 是在「类型」层面比较的。如果 VT 和 mpeg4 生成的素材某个字段类型不同（比如 int 和 float），快照会因编码器而变。生成快照后，把 `PATH` 指向 `vendor/bin` 再跑一次，确认两者一致；不一致就把那个键路径（例如 `$.materials.videos[].*`）从 `content_shape` 里排除，并加注释说明。
  - `tests/golden/` 不在 `.gitignore` 里（只忽略了 `*.mp4`），可以提交。
- **VALIDATE**: 生成快照后，不带环境变量连跑两次都 GREEN；人为把 `jy_version.VERIFIED_VERSION` 改成 `"11.1.0"`，应该 RED（然后改回来）

### Task 9: RED → GREEN —— Windows 导出：警告透传、BAT/PS1、`zip_pkg`（KI-18② / KI-18 吞警告 / KI-64）
- **ACTION**: 先写测试（`tests/test_export_draft.py`、`tests/test_packaging.py`），再改 `export_draft.py`、`build_package.py`、`aicut.cmd_export`
- **IMPLEMENT**:
  测试：
  ```python
  # tests/test_export_draft.py
  def test_package_output_never_shows_partial_zip(tmp_path, capsys):            # KI-64
      ex.package_draft(fake_draft(tmp_path), "N", tmp_path / "out" / "N.zip")
      assert ".partial-" not in capsys.readouterr().out

  def test_build_returns_to_jianying_warnings(tmp_path, monkeypatch):            # KI-18
      tl = tmp_path / "timeline.json"; tl.write_text("{}", encoding="utf-8")
      def fake_run(argv, **kw):
          staging = Path(argv[argv.index("--staging") + 1])
          (staging / "x").mkdir(parents=True)
          return subprocess.CompletedProcess(argv, 0, "[!] 1 条警告\n  - 字幕顺延\n", "")
      monkeypatch.setattr(ex.subprocess, "run", fake_run)
      monkeypatch.setattr(ex, "package_draft", lambda d, n, out: Path(out).write_bytes(b"z"))
      assert ex.build_windows_package(tl, "x", tmp_path / "o.zip")["warnings"] == ["字幕顺延"]
  ```
  `tests/test_aicut_build.py`：打桩 `export_draft.build_windows_package` 返回 `{"zip": …, "size": 1, "warnings": ["字幕顺延"]}`，调用 `aicut.cmd_export(argparse.Namespace(name="p", timeline=str(tl), package_name=None, out=str(tmp_path)))`，断言输出里有 `[!] 字幕顺延`。
  ```python
  # tests/test_packaging.py
  BP = _read("packaging/build_package.py")          # 读源码文本，不 import（见 GOTCHA）
  BAT = re.search(r'BAT = r"""(.*?)"""', BP, re.S).group(1)
  PS1 = re.search(r'PS1 = r"""(.*?)"""', BP, re.S).group(1)

  def test_install_bat_reports_failure_instead_of_ok():
      bat = BAT
      assert 'set "FAILED=0"' in bat and 'set "FAILED=1"' in bat
      ps_line = next(l for l in bat.splitlines() if "fix_paths.ps1" in l)
      assert ">nul 2>&1" not in ps_line                      # 失败原因要看得见
      after_ps = bat.split(ps_line, 1)[1]
      assert after_ps.lstrip().startswith("if errorlevel 1")  # PS1 失败被检查
      assert bat.index('if "%FAILED%"=="1"') < bat.index("[OK] Done.")
      assert bat.count("exit /b 1") >= 3                      # 无根目录 / 剪映在跑 / 安装失败
      assert 'if "%COUNT%"=="0"' in bat                       # 包里没有草稿也不算成功

  def test_fix_paths_ps1_prints_reason_on_failure():
      assert "Write-Host" in PS1.split("catch", 1)[1] and "exit 1" in PS1

  def test_ffmpeg_build_checks_preview_audio_filters():
      sh = _read("packaging/build_ffmpeg.sh")
      filters = re.search(r'REQUIRED_FILTERS="([^"]+)"', sh).group(1).split()
      assert {"anullsrc", "aformat"} <= set(filters)

  def test_spec_includes_jy_version():
      assert '"pipeline.jy_version"' in _read("packaging/ai-cut.spec")
  ```
  实现：
  - `build_package.py` 的 `zip_pkg`（`:264-272`）：去掉 print，`return out_zip.stat().st_size`；`main()`（`:323`）改成 `size = zip_pkg(...)` 后打印 `打包完成：{最终 zip}（{size/1e6:.1f} MB）`。
  - BAT（`:179-194`）：
    ```bat
    set "PKG=%~dp0"
    set "FAILED=0"
    set "COUNT=0"
    for /d %%D in ("%PKG%drafts\*") do (
      set "NAME=%%~nxD"
      set /a COUNT+=1
      echo [*] Installing !NAME! ...
      if exist "%ROOT%\!NAME!" rd /s /q "%ROOT%\!NAME!"
      xcopy "%%D" "%ROOT%\!NAME!\" /E /I /Y /Q >nul
      if errorlevel 1 (
        echo [X] Copy failed for !NAME!. Try running as administrator.
        set "FAILED=1"
      ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%PKG%fix_paths.ps1" -DraftDir "%ROOT%\!NAME!"
        if errorlevel 1 (
          echo [X] Path fix failed for !NAME! - JianYing would show missing media.
          set "FAILED=1"
        ) else (
          echo     installed to: %ROOT%\!NAME!
        )
      )
    )

    if "%COUNT%"=="0" (
      echo [X] No draft found in this package. Unzip the whole package first.
      pause & exit /b 1
    )
    if "%FAILED%"=="1" (
      echo.
      echo [X] Some drafts were NOT installed correctly. See the messages above.
      echo     Send a screenshot of this window to the developer.
      pause & exit /b 1
    )
    echo.
    echo [OK] Done.
    ```
  - PS1 的 `catch`（`:217-219`）：`Write-Host "[X] fix_paths failed: $($_.Exception.Message)"; exit 1`。PS1 必须保持纯 ASCII 文本（它以 utf-8-sig 写出，内容本来就是 ASCII）。
  - `export_draft.build_windows_package`（`:95-104`）：成功后 `warnings = to_jianying.parse_report(result.stdout)["warnings"]`，返回值加 `"warnings": warnings`。导入用 `from pipeline import proc, to_jianying  # noqa: E402`。
  - `aicut.cmd_export`（`:461`）：在 `ok(...)` 之前加 `for w in res.get("warnings", []): warn(w)`。
- **MIRROR**: LOGGING_PATTERN（`aicut.py:666-668` 的再报一次）、`tests/test_packaging.py` 的静态断言风格
- **IMPORTS**: `export_draft.py` 加 `to_jianying`（它顶层只依赖 `pipeline.schema`，不会提前导入 pyJianYingDraft）
- **GOTCHA**:
  - 在 `tests/test_packaging.py` 里 `from packaging.build_package import BAT` 时，`packaging` 可能解析成 PyPI 的包。`export_draft.py:25` 是用 `sys.path.insert(0, ROOT)` 解决的。测试里改用 `_read("packaging/build_package.py")` 读源码文本，再用正则 `BAT = r"""(.*?)"""` 取出来，最稳，和该文件其他用例的风格一致。
  - BAT 里 `if errorlevel 1` 写在括号块里，是运行时求值，可以用；**不要**改成 `%errorlevel%`（括号块里会在解析时就展开）。`set /a COUNT+=1` 在块内可以用，块外读 `%COUNT%` 也没问题。
  - 去掉 `>nul 2>&1` 后，PS1 成功时没有任何输出（它本来就不打印），只有失败时 `Write-Host` 会显示。
  - `NOTES` 里「看到 [OK] Done 后」仍然成立，不用改。
- **VALIDATE**: 改之前 RED（`KeyError: 'warnings'`；输出里有 `.partial-`；BAT 断言失败），改之后 GREEN

### Task 10: 全量验证 + 关闭登记
- **ACTION**: 跑全量测试，做手动验证（见下），commit；在 `docs/known-issues.md` 把 KI-13..18 / 59 / 64 / 76 的状态填上提交号；PRD 第 7 行改为 `complete` 并附 plan / report / 提交号，和 M1–M5 一样。
- **VALIDATE**: `uv run pytest` 全绿，用例数 ≥ 987 + 新增数，0 failed

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_subtitle_files_keep_text_verbatim` | `'` `%` `:` `\` `[;]` `%{pts}` | 文件内容与原文完全一致 | ✓ |
| `test_build_uses_textfile_without_expansion` | 同上 | 滤镜图里没有原文、没有 `text='` | ✓ |
| `test_build_fills_silence_for_input_without_audio` | `has_audio=[False, True]` | `anullsrc` + 两路都有 `aformat` | ✓ |
| `test_text_dir_falls_back_…` | `$TMPDIR` 含 `:` | `/tmp` | ✓ |
| 真 ffmpeg：特殊字幕 + 无音轨 + 单声道 + 5.1 | 3 个 1 秒片段 | rc 0，单条 stereo/48000 音轨 | ✓ |
| 真 ffmpeg：source 不存在 | 缺文件 | rc 1，提示「预览片渲染失败」 | ✓ |
| `has_audio` ×3 | 有 / 无 / ffprobe 失败 | True / False / MediaError | ✓ |
| `test_dev_module_cmd_does_not_put_package_dir_first` | 包内同名 `json.py` | 拿到标准库 json，退出码 3 透传 | ✓ |
| Homebrew Python 跑 render_preview `--help` | 动态 select | rc 0（没有这种 Python 就 skip） | ✓ |
| `_run_pipeline` / `install_draft` / `module_cmd` 命令形态 | 开发态 | `-P` 引导，不出现 `.py` 路径 | |
| `test_run_with_shots_reaches_build…` | `run p` / `run p --version v2 --no-draft` | `(None, False)` / `("v2", True)` | ✓ |
| `jy_version` ×4 | plist 11.6 / 缺失 / 损坏 / 12.x / 10.8 / 非数字 | 版本 / None / 是否警告 | ✓ |
| 模板缺失 | `TEMPLATE` 指向不存在的文件 | rc 1，不生成暂存目录 | ✓ |
| 同名草稿 | 根目录下有用户的 `T/` | rc 1，`bundle_media` 未被调用 | ✓ |
| 自家孤儿 | `T/` 带安装中标记 | 正常安装 | ✓ |
| 跨大版本 | 打桩 12.0.0 | rc 0，警告汇总里有 12.0.0 | |
| 黄金快照 | 固定时间线 | 结构与快照一致；lock 版本与快照一致 | |
| 导出警告透传 / `cmd_export` 显示 | 子进程输出带汇总 | `warnings == ["字幕顺延"]`、`[!] 字幕顺延` | |
| `zip_pkg` 不打印临时路径 | `package_draft` | 输出里没有 `.partial-` | |
| BAT / PS1 静态检查 | 源码文本 | FAILED / COUNT / errorlevel / exit /b 1 / Write-Host | |

### Edge Cases Checklist
- [x] 空输入：时间线没有字幕（`subtitle_files([])` → `[]`，滤镜图里没有 drawtext）；包里没有草稿（BAT 检查 COUNT）
- [x] 超大输入：字幕条数多 → 每条一个小文件，在临时目录里，结束时自动清理
- [x] 非法类型：`Info.plist` 损坏、版本号不是数字
- [x] 并发：`TemporaryDirectory` 每次唯一；`_WARNINGS` 和现在一样，靠 GUI 全局互斥（GL-17）
- [x] 依赖失败：ffprobe 缺失或读不了 → `MediaError` 带原因
- [x] 权限：草稿根下有用户的同名目录 → 不碰，直接报错

---

## Validation Commands

### Static Analysis
```bash
uv run python -m compileall -q aicut.py pipeline gui packaging
bash -n packaging/build_ffmpeg.sh
```
EXPECT: 无输出（仓库没有配置 lint / typecheck）

### Unit Tests
```bash
uv run pytest tests/test_render_preview.py tests/test_media_io.py tests/test_proc.py \
  tests/test_aicut_build.py tests/test_to_jianying.py tests/test_jy_version.py \
  tests/test_jianying_golden.py tests/test_export_draft.py tests/test_packaging.py
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest
```
EXPECT: ≥ 987 + 新增，0 failed（没有 VT / drawtext / Homebrew Python 时，相应用例 skip）

### Database Validation
N/A

### Browser Validation
N/A（不改 GUI；GUI 的导出任务日志直接显示 `aicut export` 的 stdout，`[!]` 警告会自然出现）

### Manual Validation
- [ ] `PATH=$PWD/vendor/bin:$PATH uv run python -m pytest tests/test_render_preview.py`：vendor ffmpeg 7.0 也通过
- [ ] `/opt/homebrew/bin/python3 -P -c "$(uv run python -c 'from pipeline import proc;print(proc.DEV_BOOTSTRAP)')" $PWD pipeline.to_jianying --help` → rc 0
- [ ] 真实项目：在已有 shots.json 的项目上跑 `uv run python aicut.py run <项目> --no-draft`，能出预览片；把一条 shot 的 `sub` 改成 `他说'好'，100%` 再 build，预览里原样显示
- [ ] 无音轨素材（例如 `ffmpeg -f lavfi -i color -t 10 -c:v h264_videotoolbox x.mp4`）走 `new → build`，预览片有静音轨
- [ ] 同一个版本 `build --version v1` 跑两次：第二次在「生成剪映草稿」后立刻报「草稿已存在」（不拷媒体）
- [ ] Windows 实机（PRD 放行检查一并做）：在 `INSTALL.bat` 里人为把草稿目录设为只读，确认出现 `[X] … NOT installed correctly` 且窗口不显示 `[OK] Done.`；正常情况下仍显示 `[OK] Done.`
- [ ] 剪映 Mac（本机 11.6.0）打开新生成的草稿：能播放，有字幕

---

## Acceptance Criteria
- [ ] Task 1–10 全部完成
- [ ] 所有验证命令通过
- [ ] 每个 KI 至少有一条改代码前 RED、改代码后 GREEN 的测试
- [ ] 不新增运行时依赖（`plistlib`、`runpy`、`tempfile` 都是标准库）
- [ ] `aicut.py` 行数不增加超过 5 行；`gui/server.py` 不改

## Completion Checklist
- [ ] 错误走 `MediaError` / `InstallError` → `sys.exit` / `die`，和现有风格一致
- [ ] 文案用大写常量；警告用 `warn()` 汇总，由 aicut 再报一次
- [ ] 测试复用 `clip` / `jy_root` / `_run_main` / `FakeProc` / `project` 夹具
- [ ] 没有硬编码版本号（统一放在 `jy_version`）
- [ ] 脚本文档字符串的用法已同步为 `python -m pipeline.xxx`
- [ ] 没有超出这 9 个 KI 的改动
- [ ] 计划自包含，实施时不需要再去搜代码

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 旧的 `~/.aicut/venv` 是 Python 3.10 或更早，不认识 `-P` | 低 | 中（开发态草稿步骤失败） | `-P` 的报错很明确；Notes 里写上「删除 ~/.aicut/venv 后重建」；打包版不受影响 |
| 黄金快照的 `shape` 随编码器（VT / mpeg4）变化 | 中 | 低（测试误报） | Task 8 GOTCHA：用两种编码器各跑一次，不一致就排除对应键路径 |
| `$TMPDIR` 被用户改成含特殊字符的路径 | 低 | 中 | 退回 `/tmp`，有单测 |
| 模板缺失改成失败后，开发者本地少了 research 文件就跑不通 | 低 | 低 | 文案指明路径；这正是想要的「如实报错」 |
| BAT 改动无法在 macOS 上执行验证 | 中 | 中 | 静态断言 + Windows 实机人工验证（并入放行检查） |
| `textfile` 读文件时 drawtext 的编码假设 | 低 | 中 | 写入时明确用 UTF-8；集成测试用中文字幕覆盖 |

## Notes

### 需用户决策（实现时按推荐默认做，除非用户另有指示）
- **D1（KI-18）模板缺失：直接失败，还是警告后继续？** 推荐 **失败（退出码 1，不交付）**。缺模板说明安装包不完整，生成的是 5.9 结构的草稿，剪映 11 打开有风险；这和 M3「校验 FAIL 不交付」一致。
- **D2（KI-17）本机剪映版本和已验证版本不一致：怎么处理？** 推荐 **只在大版本不同时（≠11）警告，并照常交付**；同一大版本（例如本机 11.6.0）不提示。阻断会让剪映自动升级后整个 App 不可用；剪辑师 2026-10-18 已实测剪映能打开（PRD §9）。
- **D3（KI-17）草稿里的 `platform.app_version`：写死已验证版本，还是写成探测到的版本？** 推荐 **继续写 `11.0.0`**。探测值没有验证过；剪映 11.0 自己写出的空草稿里这个字段本来就是空串，可以加载（`to_jianying.py:324` 注释）。
- **D4（KI-18）Windows 安装失败的提示文案**：BAT 必须是纯 ASCII，所以只能用英文提示（现有 BAT 也全是英文）。推荐用 Task 9 里的英文文案；README.txt（中文）不改。

### 备选方案（已否决）
- **重命名 `pipeline/select.py` → `selection.py`、`secrets.py` → `keys.py`**：能从根本上消除同名，但要改 `aicut.py`、`gui/server.py`、`readiness.py`、spec 和大量测试（例如 `monkeypatch.setattr(aicut.secrets, …)`），而且两个超过 800 行的文件也在其中。真正的问题是「用脚本方式运行」，`-P` 引导只改 3 个调用点，就能把这一类问题都解决，包括以后新增的同名模块。
- **`python -m` + `cwd=ROOT`**：仓库根会成为 `sys.path[0]`，`packaging/` 会遮蔽 PyPI 的 `packaging`；相对路径参数的含义也会变。否决。
- **继续转义 `text=`**：drawtext 有两层转义，单引号里无法转义 `'`。实测表明只有 textfile 在两个 ffmpeg 版本上都可靠。
- **在 `ensure_clips` 给无音轨切片补静音轨**：会多一次重编码，而剪映草稿本来就没问题。只修预览。

### 观察（不在本里程碑范围，未登记）
- `INSTALL.bat:183` 遇到同名草稿会 `rd /s /q` 直接删除用户已有的同名草稿，而 README 写的是「不会动你已有的任何草稿」。草稿名带版本号，撞名概率低。建议按硬约定登记新的 KI，由用户决定排期；本计划不实现。
- `research/validate_draft.py:51` 也写死了 11.0 模板路径；它是独立的研究脚本，本次不改。
