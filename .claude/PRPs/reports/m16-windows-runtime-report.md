# Implementation Report: Windows 上运行（里程碑 16）

## Summary

剪辑台在 Windows 10/11 x64 上可运行：跨平台文件锁（`pipeline/filelock.py`）、任务进程树（Windows 用 Job Object）、Windows 路径 / 剪映草稿库 / 打开与定位、按平台选 H.264 编码器（`h264_mf` 优先、`libopenh264` 兜底，惰性预检）、字体与滤镜路径转义、日志脱敏、按平台的界面文案（⑥ 在 Windows 只显示「导出到 Windows 剪映」）。Windows 包只在 CI（`.github/workflows/windows.yml`：verify → test → build）里构建，产出 `ai-cut-windows-x64-<版本>-<构建号>.zip`；随包 ffmpeg 为 BtbN LGPLv3 构建（钉 tag 与 SHA256，附许可全文与源码）。Task 8 收尾：剩余 POSIX 专属测试加平台标记，Windows CI 的 `test` 作业去掉 `continue-on-error`，补文档。

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large；8 个任务，11 次提交（含两次 CI 修复） |
| Tests | — | 见 Validation Results |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | CI 骨架 + ffmpeg 钉版 / 自检 + 编码器探针 | done | `a992a1e`；h264_mf 与 libopenh264 都可用 |
| 2 | 文件锁跨平台 | done | `f67c0cb` |
| 3 | 任务进程树 | done | `d1c8df2` |
| 4 | 路径 / 剪映安装 / 打开 / 日志 / 原子 I/O | done | `b32907c` |
| 5 | 编码器按平台 + 惰性预检、字体、滤镜路径 | done | `5a65e13`、`7f4fc79`（h264_mf 用数值 profile 100 = High） |
| 6 | 按平台界面文案 | done | `ad6fef7` |
| 7 | Windows 打包（spec 分支、`build_win.py`、CI build + 冒烟） | done | `b4bccf5`，CI 修复 `2daf93f`、`da24e0b` |
| 8 | 剩余测试平台化 + 文档 | done | 见下 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | 未配置 | |
| Unit Tests (Mac) | Pass | 3754 passed, 12 skipped（Mac） |
| Windows CI | verify ✓ / build ✓（artifact `ai-cut-windows-x64`）；test 在 run 40308909912 仅剩 launcher 与 build_ffmpeg.sh 的 10 个用例失败，Task 8 已标记，待推送后复核 | |
| Integration | N/A | 未在真实 Windows 机器上跑；放行检查 #27–#30 待人工 |

## Review Findings Fixed

各任务审查中的 CRITICAL / HIGH 已在对应提交内修掉；Task 8 本身无新增审查发现。

## Deviations from Plan

- Task 8：仅 `tests/test_launcher.py`（3 个 bash 启动器用例）与 `tests/test_m5_review2.py`（`build_ffmpeg.sh` 的 7 个 verify / 下载用例，含参数化展开）标 `posix_only("<理由>")`；其余此前在各任务里已改成平台无关。没有新增 `mac_only` 标记（桩的 otool 在 Linux 也能跑，POSIX 语义足够）。
- 一直在 `main` 上开发；计划文件未移入 `completed/`，与前例一致。
- PRD 提交范围写到 `da24e0b`，文档提交不计入。

## Issues Encountered

CI 才暴露的两个根因（本地 Mac 都没有）：

1. 仓库的 `packaging/` 目录遮住 PyPI 的 `packaging` 包：`python -m PyInstaller` 把当前目录放进 `sys.path` 首位，PyInstaller 导入 `packaging` 时拿到仓库目录。修复：用 `python -P` 运行（`2daf93f`）。Mac 上用 `build_app.sh` 直接调 `pyinstaller` 可执行文件，路径顺序不同，所以没触发。
2. 窗口化 exe 在没有有效标准句柄时挂死：CI 冒烟起 `ai-cut.exe` 时没接 stdout / stderr，打开 fd 1 失败，PyInstaller 窗口化版的 traceback 模态对话框永远等待（run 40294379863）。GUI 拉起子进程始终带管道，本地与单测不走冻结 exe，所以只有 CI 冒烟能复现。修复：`proc._line_buffered_stdio` 在 std fd 无效时回退 devnull；spec 在 Windows 上 `disable_windowed_traceback`（出错直接退出而非弹模态框）；冒烟改为像 GUI 一样重定向输出并在失败 / 超时时打印日志（`da24e0b`）。

## Next Steps

- [ ] 推送后确认 Windows CI 的 `test` 作业在无 `continue-on-error` 下全绿
- [ ] 真机放行检查 `docs/PROGRESS.md` #27–#30（首次打开 / 填 Key 到预览片 / 导出到 Windows 剪映 / 取消与关窗口无残留进程）
- [ ] 待决文案：`COPY_CACHE_INTRO` 在 Windows 上怎么说（现在是否沿用 Mac 表述）需用户定
