# Plan: Windows 上运行（里程碑 16）

## Summary
让剪辑台 App 在 Windows 10/11 x64 上跑通「填 Key → 新建 → 分析 → 选段 → 预览片 → 导出进 Windows 剪映」。同一套 Python + pywebview，加一层平台适配（文件锁、进程树、系统交互、路径、编码器、字体、日志）；Windows 包只在 GitHub Actions 的 Windows runner 上构建（PyInstaller onedir → zip），ffmpeg 用 BtbN 的 LGPL 预编译构建并钉 SHA256。Mac 行为与产物不变。

## User Story
作为用 Windows 电脑的剪辑师，我想解压就能运行剪辑台、直接把粗剪装进本机剪映，这样不用借一台 Mac。

## Problem → Solution
App 只能在 Apple 芯片 Mac 上跑（`fcntl` 导入即崩、`killpg`、`osascript`/`open`、`h264_videotoolbox`、`~/Movies` 草稿根、`/System/Library/Fonts`…）→ 平台差异集中在少数几个模块里，Windows 走等价实现；CI 在 Windows 上跑测试并产出 zip。

## Metadata
- **Complexity**: XL（约 30 个文件；分 8 个任务，每个任务自成一次提交）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: 里程碑 16 · Windows 上运行
- **Estimated Files**: 新建 ~10，修改 ~25（含测试与文档）

---

## UX Design

### Before
Windows 上无法运行；⑥ 导出只有「导出到 Mac 剪映」「生成 Windows 剪映包」。

### After（用户 2026-10-21 已定）
```
Mac（不变）                         Windows
⑥ [导出到 Mac 剪映]                 ⑥ [导出到 Windows 剪映]   ← 直接装进本机草稿库
   [生成 Windows 剪映包]               （不显示 zip 包按钮）
   在访达中显示                        在文件资源管理器中显示
   这台 Mac 暂时不能分析               这台电脑暂时不能分析
   请先退出剪映（⌘Q）                  请先关闭剪映窗口
```

### Interaction Changes
| Touchpoint | Before | After (Windows) | Notes |
|---|---|---|---|
| ⑥ 本机导出按钮 | 导出到 Mac 剪映 | 导出到 Windows 剪映 | 内部导出种类仍是 `mac`（= 装进本机草稿库），不改存储格式 |
| ⑥ Windows 包按钮 | 显示 | 不显示 | 后端能力保留 |
| 版本卡片 | Mac 剪映：{draft} | Windows 剪映：{draft} | |
| 所有「访达」 | 在访达中显示 / 选中 | 在文件资源管理器中显示 / 选中 | step-export.js、support.js、gui/support.py 的 REVEAL_FAILED_MSG |
| 「这台 Mac」 | 这台 Mac 暂时不能分析 | 这台电脑暂时不能分析 | jobs.js |
| 剪映运行中提示 | 退出剪映（⌘Q） | 关闭剪映窗口 | step-export.js COPY_JY_RUNNING_BODY |
| 编码器不可用 | 「VideoToolbox / Apple 芯片 Mac」 | 「Windows 视频编码组件」 | encode.py 后端文案，按平台给 |

具体 Windows 文案（实现时照抄）：
- `导出到 Windows 剪映`、`已在 Windows 剪映里：{draft}`、`Windows 剪映：{draft}`、`Windows 剪映草稿名：{draft}（改版前生成，未记录是否导入过）`
- `在文件资源管理器中显示`；诊断包：`诊断包 {name} 已保存到「{folder}」文件夹并在文件资源管理器中选中，直接拖进微信发给开发者`
- `这台电脑暂时不能分析`
- `导出到 Windows 剪映前请先关闭剪映窗口，否则剪映会覆盖草稿库。`
- 编码器：`本机无法使用 Windows 视频编码组件（{detail}），分析后也无法生成切片和预览，已在调用云端之前停下。请确认系统是 Windows 10/11 完整版（N 版需安装「媒体功能包」）后重启再试；仍不行请导出诊断包发给开发者`

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/project_lock.py` | 14-66 | 共享锁 + 非阻塞独占锁的语义（必须保留） |
| P0 | `pipeline/shots_store.py` | 15, 56-97 | 非阻塞轮询独占锁 |
| P0 | `pipeline/schema.py` | 13, 218-260 | 阻塞独占锁 + 不支持时退回进程内锁 |
| P0 | `gui/jobs.py` | 35-110, 240-430 | 任务子进程、取消、shutdown_all、遗留任务检测 |
| P0 | `pipeline/proc.py` | 20-70, 160-237 | 冻结版路径、dispatch、父进程看门狗 |
| P0 | `pipeline/encode.py` | 1-60 | 编码参数与预检 |
| P0 | `pipeline/to_jianying.py` | 40-50, 160-180, 240-330, 360-470, 560-640 | 草稿根、globalSetting、platform 字段、剪映运行检测、安装 |
| P1 | `packaging/build_package.py` | 40-110, 180-200 | `rewrite_for_windows`：Windows 草稿 platform 字段的已验证写法；`tasklist` 用法 |
| P1 | `pipeline/render_preview.py` | 25-60, 105-125 | 字体、滤镜路径安全检查 |
| P1 | `pipeline/applog.py` | 37-64, 120-180 | 日志目录、fchmod、路径脱敏 |
| P1 | `pipeline/jy_version.py`、`gui/jianying.py` | all | 剪映版本 / App 定位 |
| P1 | `gui/opener.py`、`gui/support.py`、`gui/server.py` | 25；33；430-445, 491-513, 575-586 | open / reveal / 选文件 / 信号 |
| P1 | `packaging/ai-cut.spec`、`packaging/build_ffmpeg.sh` | all | 打包与 ffmpeg 校验清单 |
| P2 | `tests/conftest.py` | all | autouse 隔离夹具 |
| P2 | `tests/test_server_jobs.py`、`tests/test_proc.py`、`tests/test_shots_store.py` | 见 Task | POSIX 专属测试 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| BtbN 构建 | https://github.com/BtbN/FFmpeg-Builds | 变体 `win64-lgpl`（无 x264/x265）；含 openh264、amf、ffnvcodec、onevpl；每天构建，月末构建保留两年；`latest` 会漂，必须钉日期 tag 的资产 + SHA256 |
| Media Foundation 编码器 | FFmpeg `libavcodec/mfenc.c` | `h264_mf`；`hw_encoding` 默认 0（用系统软件 MFT，结果稳定）；不认 `-allow_sw`；支持 `-b:v`、`-rate_control`、`-profile:v`；输入 nv12/yuv420p |
| pywebview on Windows | uv.lock | Windows 自动装 `pythonnet`（clr-loader）；渲染器 EdgeChromium（WebView2，Win11 自带、Win10 首次自动装） |
| PyInstaller 冻结 | pywebview freezing 文档 | 会顺带打包未用到的渲染器依赖，用 `excludes` 排除 |
| LockFileEx | Win32 API | `LOCKFILE_EXCLUSIVE_LOCK=2`、`LOCKFILE_FAIL_IMMEDIATELY=1`；不带 EXCLUSIVE 即共享锁；冲突时 `ERROR_LOCK_VIOLATION=33` |
| Job Object | Win32 API | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000`；子进程默认继承父进程的 job；`TerminateJobObject` 杀整棵树；句柄关闭（含剪辑台被强杀）即全部结束 |
| os.kill on Windows | Python 文档 | `os.kill(pid, 0)` 在 Windows 上会调用 `TerminateProcess`——**会杀进程**，绝不能当存活探测 |

---

## Patterns to Mirror

### NAMING / MODULE HEADER
```python
# SOURCE: pipeline/project_lock.py:20-24
LOCK_FILE = ".aicut-busy.lock"
BUILD_LOCK_FILE = ".aicut-build.lock"
LOCK_MODE = 0o600
UNSUPPORTED = "项目锁不可用（%s），%s 不加锁继续"
_LOG = logging.getLogger("aicut.project_lock")
```
模块常量全大写、中文 docstring、logger 名 `aicut.<模块>`；中文文案常量集中放模块顶部。

### ERROR_HANDLING（锁冲突 → 业务异常；平台不支持 → warning 后放行）
```python
# SOURCE: pipeline/project_lock.py:37-50
fd = _open(pdir, name)
try:
    try:
        fcntl.flock(fd, mode)
    except BlockingIOError as exc:
        raise Busy(str(pdir)) from exc
    except OSError as exc:
        _LOG.warning(UNSUPPORTED, exc, Path(pdir).name)
        yield
        return
    yield
finally:
    os.close(fd)  # 关闭即释放
```
新的锁封装必须在冲突时抛 `BlockingIOError`、其它失败抛 `OSError`，这样三个调用方的 except 分支不用改。

### SUBPROCESS（文本输出一律显式 UTF-8）
```python
# SOURCE: pipeline/encode.py:44
r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
           timeout=PREFLIGHT_TIMEOUT_S)
```

### 可注入依赖便于测试
```python
# SOURCE: pipeline/encode.py:37
def preflight(runner=subprocess.run) -> str | None:
```
平台分支一律写成「模块常量 `IS_WIN` + 可 monkeypatch 的函数」，测试在 Mac 上 monkeypatch `IS_WIN=True` 覆盖 Windows 分支的纯逻辑部分（命令行拼接、路径、文案选择），真正调 Win32 API 的部分只在 Windows CI 上测。

### TEST_STRUCTURE
```python
# SOURCE: tests/conftest.py（autouse 隔离）+ 能力 skip 约定
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")
```
新增平台 skip 统一写法：`POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX 专属：…")`、`WIN_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows 专属")`，放进 `tests/platform_marks.py` 供各测试文件导入。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/plat.py` | CREATE | `IS_WIN`、`NO_WINDOW`（subprocess 不弹黑框的 kwargs）、`pid_alive(pid)`、`process_image(pid)`、各平台默认目录（草稿根、globalSetting、日志、配置） |
| `pipeline/filelock.py` | CREATE | `flock(fd, mode)` + `LOCK_SH/LOCK_EX/LOCK_NB/LOCK_UN`：POSIX 转 fcntl，Windows 用 ctypes `LockFileEx/UnlockFileEx`；冲突抛 `BlockingIOError` |
| `pipeline/proctree.py` | CREATE | 任务进程树：`spawn_kwargs()`、`attach(popen)`、`terminate(tree)`、`kill(tree)`、`alive(tree)`、`close(tree)`；POSIX = 进程组，Windows = Job Object |
| `pipeline/project_lock.py`、`pipeline/shots_store.py`、`pipeline/schema.py` | UPDATE | `fcntl` → `filelock` |
| `gui/jobs.py` | UPDATE | 用 `proctree`；遗留任务检测用 `plat.pid_alive`/`plat.process_image`；`HOMEBREW_BIN` 只在 macOS 前置 |
| `pipeline/proc.py` | UPDATE | `bundled_bin` 认 `ffmpeg.exe`；看门狗：Windows 上不装（Job Object 已保证父进程死则全树死） |
| `pipeline/media_io.py` | UPDATE | `_alive` 改用 `plat.pid_alive` |
| `gui/server.py` | UPDATE | `SIGHUP` 用 `getattr` 守卫；`/api/pick` 无 PICKER 时 Windows 返回空路径；`/api/open` 改调 `opener` 的语义函数 |
| `gui/opener.py` | UPDATE | 新增 `open_path(p)`、`reveal(p)`、`open_app(app)`：Mac 仍是 `open` / `open -R` / `open -a`，Windows 是 `os.startfile` / `explorer /select,` / `os.startfile(exe)` |
| `gui/support.py`、`gui/jianying.py` | UPDATE | 改调 `opener.reveal` / `opener.open_app`；`REVEAL_FAILED_MSG` 按平台 |
| `pipeline/to_jianying.py` | UPDATE | 草稿根 / globalSetting 按平台；`is_absolute()` 替代 `startswith("/")`；platform 字段按平台（Windows 照 `rewrite_for_windows` 的已验证写法）；`os.uname` → `platform.release()`；`jianying_running` Windows 用 `tasklist` |
| `pipeline/jy_version.py` | UPDATE | Windows：`installed_version()` 返回 None（只影响非阻断的兼容提示）；剪映 exe 候选路径 |
| `pipeline/encode.py` | UPDATE | 按平台选编码器与参数；预检按候选顺序试、缓存第一个可用的；失败文案按平台 |
| `pipeline/render_preview.py` | UPDATE | Windows 字体候选；滤镜路径转义（盘符冒号）；`FALLBACK_TMP` 不再写死 `/tmp` |
| `pipeline/applog.py` | UPDATE | Windows 日志目录 `%LOCALAPPDATA%\剪辑台\logs`；`os.fchmod` 守卫；脱敏正则认 `C:\Users\<名>\` 与 `C:/Users/<名>/` |
| `pipeline/secrets.py` | UPDATE | Windows 默认配置目录 `%APPDATA%\ai-cut`（`AI_CUT_CONFIG_DIR` 仍优先） |
| `pipeline/diagnostics.py` | UPDATE | 冻结版版本号：Windows 读打包时写入的 `build_info.json`；`text=True` 补 encoding |
| `gui/views.py`、`pipeline/pyver.py`、`pipeline/jy_env.py`、`packaging/version.py` | UPDATE | `text=True` 的 subprocess 补 `encoding="utf-8", errors="replace"` 与 `**plat.NO_WINDOW` |
| `gui/static/platform.js` | CREATE | `IS_WIN`（看 `navigator.userAgent`）+ `platformCopy(mac, win)` |
| `gui/static/step-export.js`、`gui/static/jobs.js`、`gui/static/support.js` | UPDATE | 平台文案；Windows 隐藏 zip 包按钮 |
| `gui/static/index.html`、`gui/static_files.py` | UPDATE | 引入 `platform.js`（在用到它的脚本之前），加白名单 |
| `packaging/ai-cut.spec` | UPDATE | `sys.platform` 分支：Windows 用 `webview.platforms.winforms`/`edgechromium` hiddenimports、`ffmpeg.exe`、不建 BUNDLE、写 `build_info.json`、UTF-8 模式 |
| `packaging/fetch_ffmpeg_win.py` | CREATE | 下载钉死的 BtbN win64-lgpl zip + 源码，校验 SHA256，解出 `vendor/bin/ffmpeg.exe`、`ffprobe.exe`，跑与 `build_ffmpeg.sh` 等价的 verify |
| `packaging/build_win.py` | CREATE | Windows 构建入口：fetch ffmpeg → pyinstaller → 拷 NOTICES / 说明 / 源码 → 打 `ai-cut-windows-x64-<ver>.zip` |
| `packaging/首次打开说明-Windows.txt` | CREATE | SmartScreen「更多信息 → 仍要运行」、WebView2 说明 |
| `packaging/THIRD-PARTY-NOTICES.txt` | UPDATE | 增 Windows 版 ffmpeg（BtbN 构建、版本、源码位置） |
| `.github/workflows/windows.yml` | CREATE | Windows runner：uv、node、pytest、构建 zip、上传 artifact |
| `tests/platform_marks.py` | CREATE | `POSIX_ONLY`、`WIN_ONLY` |
| `tests/test_filelock.py`、`tests/test_proctree.py`、`tests/test_plat.py`、`tests/test_fetch_ffmpeg_win.py` | CREATE | 新模块测试 |
| 现有 POSIX 专属测试 | UPDATE | 见 Task 8 |
| `docs/PACKAGING.md`、`docs/PROGRESS.md`、`CHANGELOG.md`、`CLAUDE.md`、PRD | UPDATE | Windows 构建与放行检查 |

## NOT Building

- Windows ARM64、代码签名、自动更新（PRD M16 已排除）
- Inno Setup 安装程序（第一版只出 zip）
- 在 Mac 上交叉打 Windows 包；Mac 的 CI
- 浏览器版剪辑台在 Windows 上的选文件框（`gui/server.py --open` 是开发用；Windows 上无 PICKER 时返回空路径 = 取消）
- Windows 版 `启动剪辑台.command` 等价物
- 剪映 Windows 版版本号读取（`installed_version` 返回 None，兼容提示不出）
- 硬件编码（NVENC/QSV/AMF）；`h264_mf` 用默认软件 MFT
- 内部导出种类 `mac` 改名（存储格式不变）

---

## Step-by-Step Tasks

> 每个任务：先写红灯测试 → 实现 → Mac 上 `uv run pytest` 全绿 → 审查无 CRITICAL/HIGH → 提交并 push → 看 Windows CI。CI 失败的修完再进下一项。

### Task 1: CI 骨架 + 最小验证（先回答三个未知数）
- **ACTION**: 新建 `packaging/fetch_ffmpeg_win.py`、`.github/workflows/windows.yml`；CI 先只跑「验证作业」，pytest 作业设 `continue-on-error: true`（此时 Windows 上 `import fcntl` 必失败）。
- **IMPLEMENT**:
  - 钉版本：从 `https://api.github.com/repos/BtbN/FFmpeg-Builds/releases` 选最近一个**月末日期 tag**（`autobuild-YYYY-MM-DD-HH-MM`，保留两年）里的 `ffmpeg-n8.1-*-win64-lgpl-8.1.zip`（与 Mac 的 FFmpeg 8.1.3 同一大版本；没有就用该 tag 的 n8.x）。在 Mac 上下载到 scratchpad 算 SHA256（只计算哈希，不执行），写进脚本常量 `FFMPEG_ZIP_URL`/`FFMPEG_ZIP_SHA256`；版本字符串里的 commit（`-g<hash>`）对应的 FFmpeg 源码用 `https://github.com/FFmpeg/FFmpeg/archive/<hash>.tar.gz`，BtbN 构建脚本用该 tag 对应 commit 的 `archive/<commit>.tar.gz`，两者都钉 SHA256。
  - `verify()`：`ffmpeg -version` 首行含钉死版本；`-L` 含 "GNU Lesser General Public"；`-buildconf` 不含 `enable-gpl|enable-nonfree|libx26[45]`、含 `--enable-libfreetype` `--enable-libharfbuzz`；编码器含 `aac pcm_s16le rawvideo` 且含 `h264_mf` 或 `libopenh264`；滤镜清单与 `packaging/build_ffmpeg.sh:26` REQUIRED_FILTERS 一致（复制成常量并加测试保证两边一致）；写 `vendor/licenses/ffmpeg-buildconf.txt`。
  - CI 验证作业（`windows-2022`）：checkout（`fetch-depth: 0`）→ `astral-sh/setup-uv`（钉 SHA）→ `uv python install 3.12` → `uv sync --group dev` → `uv run python packaging/fetch_ffmpeg_win.py` → 用 `vendor/bin/ffmpeg.exe` 对 `h264_mf`、`libopenh264` 各试编一段 5 秒 1080p 彩条 + 正弦音并 ffprobe 打印 codec/profile/pix_fmt/耗时 → keyring 读写删（服务名 `ai-cut-ci`）→ `uv run python -c "import webview, webview.platforms.edgechromium"`。
  - workflow：`on: push (branches: main)`、`workflow_dispatch`；`permissions: contents: read`；`concurrency` 取消同分支旧运行；所有 action 钉完整 SHA（注释写 tag）。
- **MIRROR**: `packaging/build_ffmpeg.sh` 的 verify/fetch 结构与提示风格；`packaging/version.py` 的 Python 风格。
- **GOTCHA**: BtbN 的 `latest` 资产会漂，不能用；下载要 `timeout` + 校验失败删文件；`vendor/` 不入库；CI 里 keyring 服务名不能是 `ai-cut`。
- **VALIDATE**: Mac 上对 `fetch_ffmpeg_win.py` 的纯逻辑（用伪造的 `-version/-L/-buildconf/-encoders/-filters` 输出）单测通过；push 后 CI 验证作业绿，日志里记录 `h264_mf` 与 `libopenh264` 的结果。**若两个都不可用 → 停下回报用户**。结论回填 Notes。

### Task 2: 文件锁跨平台（`pipeline/filelock.py`）
- **ACTION**: 新建 `filelock.py`，三个锁模块改用它。
- **IMPLEMENT**:
  - POSIX：`LOCK_SH/LOCK_EX/LOCK_NB/LOCK_UN` 直接取 `fcntl` 的值，`flock = fcntl.flock`；Windows：自定义常量。
  - Windows `flock(fd, mode)`：`msvcrt.get_osfhandle(fd)` → `LockFileEx(h, flags, 0, 1, 0, byref(OVERLAPPED()))`，flags = `LOCKFILE_EXCLUSIVE_LOCK if EX` | `LOCKFILE_FAIL_IMMEDIATELY if NB`；返回 0 时 `GetLastError()==33` → `BlockingIOError`，其它 → `OSError(winerror)`；`LOCK_UN` → `UnlockFileEx`。锁区间固定 offset 0、长度 1。
  - 三个调用方只换导入与常量名；测试里 `monkeypatch` 目标改为 `<模块>.filelock.flock`。
- **MIRROR**: ERROR_HANDLING 模式；ctypes 声明 `argtypes/restype`，`use_last_error=True`。
- **GOTCHA**: Windows 上同一进程两个 fd 对同一区域加锁也互斥（与 flock 一致）；Windows 关闭句柄后锁释放是异步的——`project_lock`/`shots_store` 退出时先显式 `LOCK_UN` 再 close（`schema.locked` 已如此）。
- **VALIDATE**: `tests/test_filelock.py`（跨平台）：SH+SH 共存；SH 持有时 EX|NB → BlockingIOError；EX 持有时 EX|NB → BlockingIOError；解锁后可再锁；跨进程版本。现有 `tests/test_server_maintenance.py:61-74` 不改照绿。

### Task 3: 任务进程树（`pipeline/proctree.py`）+ 存活探测（`pipeline/plat.py`）
- **ACTION**: 抽出 jobs/proc 的进程组逻辑，Windows 用 Job Object。
- **IMPLEMENT**:
  - `plat.py`：`IS_WIN = sys.platform == "win32"`；`NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}`；`pid_alive(pid)`：POSIX `os.kill(pid,0)`（保持现有 PermissionError=活着的语义），Windows `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetExitCodeProcess == STILL_ACTIVE(259)`；`process_image(pid) -> str | None`：POSIX 现有 `ps -o command=`，Windows `QueryFullProcessImageNameW`。
  - `proctree.py`：`spawn_kwargs()` → POSIX `{"start_new_session": True}`，Windows `{"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}`；`attach(popen) -> Tree`（Windows：`CreateJobObjectW` + `SetInformationJobObject(JobObjectExtendedLimitInformation, KILL_ON_JOB_CLOSE)` + `AssignProcessToJobObject`；POSIX：记 pgid=pid）；`terminate(tree)`（POSIX killpg SIGTERM；Windows `TerminateJobObject(job, 1)`——Windows 没有可靠的温和停止，`.aicut-partial` 机制保证半成品不被当成成品）；`kill(tree)`（POSIX killpg SIGKILL；Windows 同 terminate）；`alive(tree)`（POSIX `killpg(pid,0)`；Windows `QueryInformationJobObject(JobObjectBasicAccountingInformation).ActiveProcesses > 0`）；`close(tree)`（Windows 关 job 句柄）。
  - `gui/jobs.py`：`Popen(..., **proctree.spawn_kwargs())`，紧接着 `tree = proctree.attach(child)` 存进任务记录；`_killpg/_group_alive` 换成 `proctree.terminate/kill/alive`；任务结束时 `proctree.close`；`HOMEBREW_BIN` 前置只在 `sys.platform == "darwin"`；`_looks_like_job` 用 `plat.process_image`（Windows：镜像名是本 App 的 exe 或 python.exe 即视为像）；`stale_job` 用 `plat.pid_alive`。
  - `pipeline/proc.py`：`start_parent_watchdog()` 在 Windows 直接返回（注释：Job Object KILL_ON_JOB_CLOSE 已保证）；`bundled_bin` 认 `ffmpeg.exe`。
  - `pipeline/media_io.py:_alive` → `plat.pid_alive`。
  - `gui/server.py:579-580`：`for name in ("SIGTERM", "SIGHUP"): sig = getattr(signal, name, None)`。
- **MIRROR**: `gui/jobs.py:301-305` 的守卫（`pid<=0` 直接返回、忽略 ProcessLookupError/PermissionError）。
- **GOTCHA**: 绝不能在 Windows 上用 `os.kill(pid, 0)`；Job 赋值发生在进程启动之后，有毫秒级窗口——子进程此时还在 Python 启动阶段，不会拉起 ffmpeg，注释说明；Windows 上 `os.killpg`/`signal.SIGKILL` 不存在，模块顶层不能引用它们。
- **VALIDATE**: `tests/test_proctree.py`：POSIX 分支（现有进程组用例迁过来）+ WIN_ONLY（起 python 子进程再起孙进程，`terminate` 后两者都不在；关句柄后全树结束；`alive` 前后变化）；`tests/test_plat.py`：`pid_alive(os.getpid())` 真、已退出进程假；`tests/test_server_jobs.py` 断言 `start_new_session` 的用例改为断言用了 `proctree.spawn_kwargs()`；进程组/信号类用例标 `POSIX_ONLY`，并为取消、shutdown_all、遗留 marker 各补一条 WIN_ONLY 等价用例。

### Task 4: 剪映草稿、系统交互、路径
- **ACTION**: 让导出到本机剪映、打开/定位、选文件、日志、配置在 Windows 上工作。
- **IMPLEMENT**:
  - `plat.py` 默认目录：草稿根 Windows = `%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft`；globalSetting = `%LOCALAPPDATA%\JianyingPro\User Data\Config\globalSetting`；Mac 不变。`to_jianying.resolve_draft_root` 优先级不变（`AI_CUT_DRAFT_ROOT` > globalSetting > 默认）。
  - `to_jianying._custom_draft_path`：`startswith("/")` → `Path(value).is_absolute()`；Qt INI 里 Windows 路径可能是 `C:/...` 或 `C:\\...`，解码后统一 `Path`。
  - platform 字段：抽 `platform_fields()`——Mac 保持现值（`os: mac`、`app_version: VERIFIED_VERSION`、`os_version: platform.release()`，与 `os.uname().release` 相同）；Windows 用 `packaging/build_package.py:54-58` 已在真机验证过的那组值。Windows 也写 `draft_info.json` + `draft_content.json` 两个文件（与 Windows 包一致）。
  - `jianying_running()`：Windows `tasklist /FI "IMAGENAME eq JianyingPro.exe" /FO CSV /NH`（参考 `packaging/build_package.py:188`），输出含 `JianyingPro.exe` 即运行中。
  - 安装：核对 `to_jianying.py:583/597/639` 的 `os.rename` 在 Windows 目标存在时的行为，保证「同名草稿已存在」时不覆盖、行为与 Mac 一致；写 WIN_ONLY 测试。
  - `jy_version.py`：Windows `installed_version()` → None；剪映 App 定位候选 `%LOCALAPPDATA%\JianyingPro\Apps\JianyingPro.exe`、`%LOCALAPPDATA%\JianyingPro\JianyingPro.exe`（存在才返回；未经真机验证，注释说明，按钮在找不到时本来就不显示）。
  - `gui/opener.py`：保留 `run_open(args)`（Mac 内部用），新增 `open_path(p)`、`reveal(p)`、`open_app(app)`；Windows：`os.startfile(str(p))`、`subprocess.run(["explorer", f"/select,{p}"], **plat.NO_WINDOW)`（explorer 返回码不可靠，只在异常时抛 `OpenFailed`）、`os.startfile(str(app))`。`gui/server.py` `/api/open`、`gui/support.py:reveal`、`gui/jianying.py` 改调语义函数；`REVEAL_FAILED_MSG` 按平台（访达 → 文件资源管理器）。
  - `gui/server.py` `/api/pick`：无 PICKER 且 Windows → `{"path": ""}`。
  - `pipeline/secrets.py`：Windows 默认配置目录 `%APPDATA%\ai-cut`。
  - `pipeline/applog.py`：Windows 日志目录 `%LOCALAPPDATA%\剪辑台\logs`；`os.fchmod` 用 `hasattr` 守卫；`_ABS_PATH` 脱敏补 `[A-Za-z]:[\\/]Users[\\/][^\\/]+` → `~`。
  - `pipeline/diagnostics.py`：冻结版版本号 Windows 读 `proc.resource_path("build_info.json")`；`text=True` 补 encoding。
  - 其余 `text=True` 无 encoding 的 subprocess（`gui/views.py:146`、`pipeline/pyver.py:35`、`pipeline/jy_env.py:42,50,69`、`packaging/version.py:38`）补 `encoding="utf-8", errors="replace"`；所有在 GUI 进程里跑的 subprocess 加 `**plat.NO_WINDOW`。
- **MIRROR**: `pipeline/to_jianying.py:441-447` 的优先级写法；`gui/opener.py` 的 `OpenFailed` + 超时。
- **GOTCHA**: `%LOCALAPPDATA%`/`%APPDATA%` 缺失时退回 `Path.home()/"AppData"/...`；Mac 端调用的命令与参数必须与改动前逐字一致（现有测试断言 `["open","-R",...]` 照绿）。
- **VALIDATE**: Mac 上 monkeypatch `plat.IS_WIN=True` + 伪造环境变量测：默认草稿根/globalSetting 路径、`is_absolute` 接受 `C:/…`、platform 字段等于 `rewrite_for_windows` 的值、`tasklist` 输出解析、opener 拼出的命令、applog 脱敏 `C:\Users\张三\x.mp4` → `~\x.mp4`；WIN_ONLY：真实装一份草稿到临时草稿根并用 `research/validate_draft.py` 校验。

### Task 5: 编码器与预览字幕
- **ACTION**: 编码器按平台；预览片字幕在 Windows 上能找到字体、滤镜路径合法。
- **IMPLEMENT**:
  - `encode.py`：`ENCODERS = {"darwin": ["h264_videotoolbox"], "win32": [Task 1 结论的顺序，预期 "h264_mf", "libopenh264"]}`；`ENCODER_ARGS` 每个编码器自己的额外参数（videotoolbox：`-allow_sw 1`；h264_mf / libopenh264：按 Task 1 日志定）；`h264_args(kind)` 用 `encoder()`（=预检选中的那个，未预检时取首个）；`preflight()` 依次试候选，缓存第一个成功的名字与结果；`ENCODER_UNAVAILABLE` 按平台（Windows 文案见 UX 节）。`-profile:v high` 若某编码器不支持则在该编码器参数里覆盖。
  - 测试里写死 `h264_videotoolbox` 的地方（`tests/test_encode.py:57-60`、`tests/test_e2e_draft.py:32-41`、`tests/test_render_preview.py:70`、`tests/test_m5_review2.py:29`）改为按 `encode.ENCODERS[sys.platform]` 判断能力；e2e 的 skip 条件改为「当前平台候选编码器有一个可用」，这样 Windows CI 会跑 e2e。
  - `render_preview.py`：`FONT_CANDIDATES` 按平台（Windows：`%WINDIR%\Fonts\msyh.ttc`、`msyhbd.ttc`、`simhei.ttf`、`simsun.ttc`）；`fontfile`/`textfile` 进滤镜图前统一 `_filter_path(p)`：反斜杠 → `/`，`:` → `\:`，`'` 按 ffmpeg 规则转义；Windows 的退回目录用 `%PUBLIC%\Documents\aicut-tmp`（ASCII、普通用户可写）而不是 `/tmp`。
- **MIRROR**: `pipeline/encode.py:37-60` 预检 + `_PREFLIGHT` 进程缓存；`tests/conftest.py:_encoder_ok` 重置缓存。
- **GOTCHA**: `conftest._encoder_ok` 现在重置 `_PREFLIGHT`，新增的「已选编码器」缓存也要一起重置；Mac 上编码参数与预检失败文案必须与改动前逐字一致。
- **VALIDATE**: 单测覆盖候选回退（第一个失败第二个成功 → 选第二个，`h264_args` 用第二个）、全失败文案按平台、`_filter_path("C:\\Users\\a b\\t.txt")`；Windows CI 上 `tests/test_e2e_draft.py`、`tests/test_render_preview.py` 真跑通过。

### Task 6: 前端平台文案
- **ACTION**: 新建 `gui/static/platform.js`，三个前端文件按平台取文案；Windows 隐藏「生成 Windows 剪映包」。
- **IMPLEMENT**: `platform.js`：`const IS_WIN = typeof navigator !== 'undefined' && /Windows/.test(navigator.userAgent || '');` `function platformCopy(mac, win){ return IS_WIN ? win : mac; }`；`step-export.js`/`jobs.js`/`support.js` 里受影响的 `COPY_*` 常量改为 `platformCopy('<原文>', '<Windows 文案>')`（文案见 UX 节，逐字照抄）；step-export 在 `IS_WIN` 时不渲染 Windows 包按钮与其用法 / 已生成 / blocked 提示；`index.html` 在 step-export/jobs/support 之前引入 `platform.js`；`gui/static_files.py` 白名单加 `platform.js`。
- **MIRROR**: 现有前端测试（node + DOM 桩，如 `tests/test_frontend_*.py`）加载脚本的方式。
- **GOTCHA**: 前端测试沙箱可能没有 `navigator`——必须容错（无 → Mac）；文案常量仍放在文件顶部「产品可直接改这里」区；加载 step-export 等脚本的现有前端测试需要同时加载 `platform.js`。
- **VALIDATE**: 新增前端测试：默认 UA 文案与改动前逐字一致、Windows 包按钮在；注入 Windows UA 后文案为 Windows 版、无 Windows 包按钮。

### Task 7: Windows 打包
- **ACTION**: spec 平台分支 + `packaging/build_win.py` + CI 构建作业。
- **IMPLEMENT**:
  - `ai-cut.spec`：`IS_WIN = sys.platform == "win32"`；hiddenimports 平台分支（Mac 保留 `webview.platforms.cocoa`；Windows 用 `webview.platforms.winforms`、`webview.platforms.edgechromium`、`clr_loader`、`pythonnet`）；ffmpeg 名带 `.exe`；Windows 不建 `BUNDLE`、`codesign_identity=None`；Windows 排除 `webview.platforms.cocoa/gtk/qt`；两平台都写 `build_info.json`（version、build、git commit）进 datas；Windows `EXE(..., console=False)`，并加 `options=[("X utf8_mode=1", None, "OPTION")]`。
  - `build_win.py`：`fetch_ffmpeg_win.py` → `uv run pyinstaller packaging/ai-cut.spec --noconfirm --clean` → 拷 `THIRD-PARTY-NOTICES.txt`、`首次打开说明-Windows.txt`、`vendor/sources/*`、`vendor/licenses/*` → zip 成 `dist/ai-cut-windows-x64-<SHORT_VERSION>-<BUILD>.zip`（顶层目录 `ai-cut/`）。
  - CI：workflow 加 `test` 作业（`uv run pytest`，去掉 continue-on-error）与 `build` 作业（needs: test；`uv run python packaging/build_win.py`；冒烟：以 `pipeline/proc.py` 的 `CLI_FLAG` 实际值运行 `dist\ai-cut\ai-cut.exe <CLI_FLAG> list`，隔离环境变量下退出码 0；`actions/upload-artifact` 上传 zip，保留 14 天）。
  - Mac 侧 `build_app.sh` 不变；spec 改动后在 Mac 上跑一次 `./packaging/build_app.sh` 确认 `.app` 照常产出并启动。
- **MIRROR**: `packaging/build_app.sh` 的步骤与提示风格；`packaging/version.py` 取版本。
- **GOTCHA**: `build_number` 需要完整 git 历史（checkout `fetch-depth: 0`）；冒烟必须设 `AI_CUT_SECRETS=file` 与 `AI_CUT_CONFIG_DIR/AI_CUT_PROJECTS/AI_CUT_DRAFT_ROOT/AI_CUT_LOG_DIR` 指向 runner 临时目录；zip 文件名用 ASCII。
- **VALIDATE**: CI 三个作业全绿，artifact 可下载；Mac 上 `./packaging/build_app.sh` exit 0。

### Task 8: 剩余测试平台化 + 文档
- **ACTION**: 让全量 pytest 在 Windows CI 上全绿；更新文档。
- **IMPLEMENT**:
  - `tests/platform_marks.py`；直接用 `fcntl` 的测试改用 `filelock`（`tests/test_shots_store.py`、`test_result_api.py:50-62`、`test_server_wizard.py:243-247`、`test_schema.py:362-366`，以及子进程辅助 `_hold_flock_in_subprocess`）；真正 POSIX 语义的（进程组、SIGTERM、`ps`、bash 启动器 `test_launcher.py`、`test_m5_review2.py` 的 bash）标 `POSIX_ONLY`；写死 `/tmp/...`、`Library/Logs`、`/System/Library/Fonts` 的断言改为取平台默认值；在 Windows CI 上逐个修到全绿——只有确属 POSIX 语义的才能 `POSIX_ONLY`，每处注明理由，不许用 skip 掩盖产品代码缺陷。
  - 文档：`docs/PACKAGING.md` 加 Windows 小节（CI 构建、ffmpeg 来源与校验、产物、已知限制）并改「仅 arm64」；`docs/PROGRESS.md` 5.6 更新、待人工放行检查新增 #27–#30（见 Manual Validation）；`CHANGELOG.md` 未发布下加「Windows 上运行（里程碑 16）」；`CLAUDE.md` 命令区加 Windows 打包方式；PRD 里程碑 16 状态与链接。
- **VALIDATE**: Mac 全量 `uv run pytest` 绿、覆盖率 ≥ 80%；Windows CI 全量 pytest 绿。

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| filelock 共享 | 两个 fd 都 SH | 都成功 | |
| filelock 互斥 | SH 持有时 EX\|NB | BlockingIOError | ✓ |
| filelock 跨进程 | 子进程持 EX | 父进程 EX\|NB 失败；子退出后成功 | ✓ |
| proctree 杀树（WIN_ONLY/POSIX_ONLY 各一） | 子 + 孙进程 | terminate 后都不在 | ✓ |
| proctree 关闭句柄（WIN_ONLY） | close(tree) | 全树结束 | ✓ |
| pid_alive | 自身 / 已退出 | True / False | ✓ |
| 草稿根 Windows | IS_WIN + LOCALAPPDATA | `...\JianyingPro\User Data\Projects\com.lveditor.draft` | |
| globalSetting Windows 路径 | `C:/D/drafts` | 被接受 | ✓ |
| platform 字段 Windows | — | 等于 rewrite_for_windows 的值 | |
| tasklist 解析 | 有 / 无 JianyingPro.exe | True / False | ✓ |
| 编码器回退 | 首选失败 | 选第二个 | ✓ |
| 编码器全失败 | — | 平台文案 | ✓ |
| 滤镜路径转义 | `C:\Users\a b\t.txt` | `C\:/Users/a b/t.txt` | ✓ |
| 日志脱敏 | `C:\Users\张三\x.mp4` | `~\x.mp4` | ✓ |
| fetch_ffmpeg_win verify | 伪造输出（含 GPL / 缺编码器 / 缺滤镜） | 分别报错 | ✓ |
| 前端文案 | 默认 / Windows UA | Mac 原文 / Windows 文案 + 无 zip 按钮 | |

### Edge Cases Checklist
- [ ] 用户名含中文 / 空格（路径、滤镜、日志脱敏）
- [ ] `%LOCALAPPDATA%` 缺失
- [ ] Windows N 版无 Media Foundation（预检文案）
- [ ] 同名草稿已存在
- [ ] 剪映运行中导出
- [ ] 取消任务时 ffmpeg 正在写文件（半成品不被采用）
- [ ] 剪辑台被强杀（Job Object 带走全树）
- [ ] 旧版 `.aicut-*.lock` 文件残留

---

## Validation Commands

### Static Analysis
```bash
node --check gui/static/*.js
```
EXPECT: 无语法错误（项目未配置 lint / 类型检查）

### Unit Tests / Full Suite（Mac）
```bash
uv run pytest
```
EXPECT: 全绿，覆盖率 ≥ 80%

### Windows（CI）
`.github/workflows/windows.yml`：验证、测试、构建 + 冒烟，全绿；用 `gh run watch` / `gh run view --log-failed` 看结果。

### Mac 打包回归
```bash
./packaging/build_app.sh
```
EXPECT: exit 0，`dist/AI粗剪.app` 正常启动

### Manual Validation（新增放行检查 #27–#30，用户在真实 Windows 上做）
- [ ] #27 解压 zip，SmartScreen「更多信息 → 仍要运行」后窗口正常打开；没有黑色命令行窗口闪出
- [ ] #28 填 Key（存入 Windows 凭据管理器）→ 新建 → 分析 → 选段 → 生成预览片（中文字幕正常）
- [ ] #29 ⑥「导出到 Windows 剪映」→ 打开剪映能看到并播放；剪映开着时会先提示关闭；同名草稿不被覆盖
- [ ] #30 分析中途取消、分析中途直接关窗口 → 任务管理器里没有残留的 ffmpeg / ai-cut 进程

---

## Acceptance Criteria
- [ ] Task 1–8 完成，每个任务单独提交并推送
- [ ] Mac 全量测试绿、覆盖率 ≥ 80%；Mac 打包回归通过
- [ ] Windows CI（验证、测试、构建）全绿，zip artifact 可下载
- [ ] Mac 上所有行为、命令、文案与改动前逐字一致
- [ ] 用户确定的 Windows 文案与导出入口已实现

## Completion Checklist
- [ ] 平台差异只在 `plat.py`、`filelock.py`、`proctree.py`、`encode.py`、`opener.py` 与少数默认路径处
- [ ] 所有新 subprocess 带 `encoding="utf-8", errors="replace"`（文本时）与 `**plat.NO_WINDOW`
- [ ] Windows 分支上没有任何 `os.kill(pid, 0)`
- [ ] 无硬编码密钥；CI 冒烟不碰真实钥匙串 / 剪映草稿库
- [ ] 文档与放行检查更新

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| BtbN LGPL 构建无 `h264_mf` 且 `libopenh264` 画质 / 速度不够 | 中 | 高 | Task 1 先验证；都不行就停下回报 |
| 剪映 Windows 的 globalSetting / exe 路径与假设不同 | 中 | 中 | 有 `AI_CUT_DRAFT_ROOT` 兜底；放行检查 #29 实测 |
| 窗口化 exe 的子进程 stdout / 控制台窗口问题 | 中 | 中 | 子进程用管道 + `CREATE_NO_WINDOW`；CI 冒烟 + 放行检查 #27 |
| WebView2 在冻结后加载失败 | 低 | 高 | hiddenimports 显式列 winforms/edgechromium；放行检查 #27 |
| Windows 路径过长（> 260） | 低 | 中 | 出错时日志可查；放行检查实测 |
| Windows CI 上大量测试首次失败、耗时 | 高 | 中 | Task 8 逐个修；只把 POSIX 语义测试标 POSIX_ONLY |

## Notes
- 用户决定（2026-10-21）：仓库公开推到 `crystaldust/ai-precut`；⑥ 按平台对称（Windows 只显示「导出到 Windows 剪映」）；Mac 字样文案在 Windows 上按平台替换，Mac 不变。
- 内部导出种类 `mac` 的含义是「装进本机剪映草稿库」，Windows 沿用，不改存储格式（命名债）。
- Task 1 结论（CI run 39636023202，`a992a1e`）：钉 BtbN `autobuild-2026-09-30-13-08` / FFmpeg `n8.1.3-9-g29e619e767`；该 LGPL 变体用 `--enable-version3`（随包许可证为 LGPLv3 + GPLv3 文本）。两个编码器都可用：
  - `libopenh264`：`-profile:v high` 可用，产出 High profile，5 秒 1080p 耗时 1.4s；
  - `h264_mf`：`-profile:v high` 被拒（该编码器不认这个命名值），不带 profile 产出 Constrained Baseline，耗时 1.3s。
  - keyring（Windows 凭据管理器）读写删通过；`webview.platforms.edgechromium` 可导入。
  - Task 5 决定：Windows 候选顺序先在 CI 探针里补试 `h264_mf -profile:v 100/77`（数值 profile）；能出 High/Main 就首选 h264_mf（系统编码器，专利由系统授权覆盖），否则首选 libopenh264（High）、h264_mf 兜底。
