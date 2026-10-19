# Plan: 里程碑 3「交付物可信」（GL-10 / GL-11 / GL-12 / GL-13 / GL-15）

## Summary
让交付给剪辑师的东西「要么完整正确，要么明确失败」：剪映草稿导出不再因字幕卡重叠/负时长崩溃（GL-10）；静态校验 FAIL 时不安装、不打印 `[✓]`（GL-11）；打包版 `sys.exit("文字")` 的错误信息不再丢失（GL-12）；草稿安装「移动 + 校验 + 注册」整体原子、失败回滚、剪映未装或改过草稿目录时给出可读错误（GL-13）；所有 ffmpeg 产物先写临时文件再原子改名，并以 `.done` 完成标记判定完成，中断后不复用半成品（GL-15）。

## User Story
作为剪辑师，我希望 App 只在剪映草稿和中间产物完整、校验通过时才告诉我「完成」，失败时告诉我真实原因并且可以直接重试，这样我不会打开一个坏草稿、也不会为半截音轨的转写付费。

## Problem → Solution
- 现状：片头字幕卡与第 1 句字幕同轨 → `SegmentOverlap` 崩溃（`纪实3min` 预设必现）；片尾卡 `at` 超总时长 → 负时长片段；校验 FAIL 仍 `[✓]`；打包版 `run_inprocess` 丢弃 `main()` 返回值、`int("文字")` 抛 `ValueError`；先 move 后 register，失败留孤儿、重试报「已存在」；剪映未装直接 `FileNotFoundError` 栈；ffmpeg 直写最终文件、`exists()` 判完成 → 半截 wav 被送去转写并计费。
- 目标：字幕/字幕卡分轨 + 无效卡过滤；校验内嵌到安装流程，FAIL 回滚且非零退出；退出码统一由 `proc.exit_code()` 解析；`install()` 带安装中标记、校验门、注册表备份与回滚；新模块 `pipeline/media_io.py` 提供「临时文件 → `os.replace` → `.done` 标记」，覆盖全部 GL-15 列出的 ffmpeg 输出点（外加同类的预览片与转写 JSON）。

## Metadata
- **Complexity**: Large（跨 8 个源文件 + 7 个测试文件，引入一个新的共享模块与一套安装事务）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: 里程碑 3「交付物可信」（GL-10 GL-11 GL-12 GL-13 GL-15）
- **Estimated Files**: 16（8 源 + 1 spec + 7 测试；外加关闭时改 `docs/go-live-blockers.md` 状态列）

---

## UX Design

### Before
```
┌──────────────────────────────────────────────────────────────┐
│ build 纪实3min 项目                                           │
│  [·] 生成剪映草稿…                                            │
│  Traceback … SegmentOverlap: New segment overlaps …   ← 崩溃  │
│                                                              │
│ build 成片 150s（片尾卡 at=170）                              │
│  [✓] 剪映草稿：九月一号_v5                                     │
│  [✓] 校验：结果：OK=60 WARN=0 FAIL=1 => FAIL   ← 坏草稿照交付 │
│                                                              │
│ 打包版：剪映没装                                               │
│  [退出码] -1   [错误] invalid literal for int() …  ← 原因丢失  │
│ 重试 → 草稿已存在：…/九月一号_v5（换名字或先删除）← 孤儿       │
│                                                              │
│ 抽音轨时关掉 App → 重开 → 直接拿半截 asr.wav 去转写并计费      │
└──────────────────────────────────────────────────────────────┘
```

### After
```
┌──────────────────────────────────────────────────────────────┐
│ build 纪实3min 项目                                           │
│  [warn] 字幕卡 '签完合同…' 超出成片时长 150.0s，已跳过          │
│  校验通过：OK=60 WARN=0 FAIL=0                                │
│  [✓] 剪映草稿：九月一号_v5（已通过静态校验）                    │
│                                                              │
│ 校验 FAIL：                                                   │
│  草稿静态校验未通过，已撤销安装：                               │
│    [FAIL] segment … 的 target_timerange 非法 …                │
│  未通过校验的草稿保留在暂存目录：~/.aicut/staging/…            │
│  [x] 草稿生成失败         （退出码 1，剪映草稿库保持原样）      │
│                                                              │
│ 剪映没装 / 草稿目录不可访问：                                   │
│  找不到剪映草稿库：…/root_meta_info.json                       │
│  请确认已安装剪映专业版并至少打开过一次；…（打包版同样可见）     │
│                                                              │
│ 抽音轨时被中断 → 重开 → 「抽音轨…」重新抽，不会送半截去转写     │
└──────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| `aicut build`（含 GUI build 任务） | 崩溃或坏草稿 `[✓]` | 卡片分轨；校验 FAIL → 非零退出 + FAIL 明细 | GUI 任务状态随退出码变 failed |
| 剪映草稿轨道 | 1 条文本轨（字幕+卡混排） | 2 条文本轨：`subtitle`、`card` | 剪辑师在剪映里看到字幕卡独立一轨（更易整体删改） |
| 打包版错误日志 | `sys.exit("…")` 文字丢失 | 文字原样进任务日志 | GL-12 |
| 重试导出 | 「草稿已存在」 | 自己留下的半装草稿自动清理后重装 | 只清带 `.aicut_installing` 标记且未注册的目录 |
| `aicut status` | 半截 wav/proxy 显示 ✓ | 只有带完成标记才 ✓ | |
| 片尾卡超出成片 | 负时长片段 → 崩/校验 FAIL | 跳过并 `[warn]` | 见「需用户决策」D1 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/to_jianying.py` | 1-321（全文） | GL-10/11/13 的主战场：`DRAFT_ROOT` 常量、`build_staging`、`macify`、`register`、`main` |
| P0 | `pipeline/proc.py` | 58-75 | `run_inprocess`：GL-11（丢返回值）、GL-12（`int(exc.code)`） |
| P0 | `aicut.py` | 43, 61-75, 115-140, 199-221, 224-235, 279-321, 429-454, 466-518, 527-585, 687-714, 725-735 | GL-11 `_validate_draft`、GL-15 四个 ffmpeg 点、GL-10 卡片、GL-12 `run_cli` |
| P0 | `research/validate_draft.py` | 1-66, 224-244 | 模块级 `fails/warns/oks` 全局列表、`main()` 返回 int；要抽出 `check()` |
| P1 | `pipeline/build_documentary.py` | 48-57, 77-108 | GL-10（卡片）+ GL-15（`cut_shot` 直写、`exists()` 判完成） |
| P1 | `pipeline/render_preview.py` | 82-101 | 预览片直写 `args.out`，由 aicut 传临时路径解决 |
| P1 | `pipeline/cloud.py` | 160-184 | `transcript_raw.json` 非原子写（aicut.py:210 用 `exists()` 判完成） |
| P1 | `pipeline/export_draft.py` | 23-27, 55-75 | `sys.path` 注入写法；Windows 导出用 `AI_CUT_DRAFT_ROOT` + `--dry-run`，必须保持可用 |
| P1 | `tests/test_cloud.py` | 1-31 | runner 注入 + FakeProc 的测试写法 |
| P1 | `tests/test_secrets.py` | 15-23 | `monkeypatch` 隔离环境变量/模块属性的 fixture 写法 |
| P2 | `tests/test_proc.py`, `tests/test_export_draft.py` | 全文 | 现有断言风格（中文 assert 消息、tmp_path 造假草稿） |
| P2 | `gui/server.py` | 40-57, 245-266 | 冻结模式下 GUI 如何调用 `run_cli`、如何根据退出码标 failed |
| P2 | `packaging/ai-cut.spec` | 15-33 | hiddenimports / datas 列表（新增模块要登记） |
| P2 | `presets/纪实3min.json` | 20-31 | 卡片 `at=0/dur=4.5` 与 `at=170/dur=5.5`，GL-10 必现来源 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| pyJianYingDraft 0.3.1 多文本轨 | 本地 `.venv/lib/python3.12/site-packages/pyJianYingDraft/_script_file_tracks.py:36-52, 109-127`；`_script_file_segments.py:51-69` | 同类型第二条轨必须 `TrackSpec(TrackType.text, name=...)` 命名；有多条同类轨时 `add_segment(seg, "轨名")` 必须传轨名，否则 `NameError` |
| `SegmentOverlap` | `pyJianYingDraft/exceptions.py:7` | `class SegmentOverlap(ValueError)`；同轨首尾相接不算重叠 |
| `trange_seconds` | `pyJianYingDraft/time_util.py:91-103` | 「分别将起点和终点取整到微秒，再计算整数微秒时长…连续片段建议共用绝对终点」→ 文本段改用 `trange_seconds(start, end=end)`，避免 `us(a)+us(b-a)≠us(b)` 的 1µs 重叠 |
| 负时长 | 实测（scratchpad）：`TextSegment` 的 `trange(5s, -2s)` **不报错**照样生成草稿 | 必须在上游过滤，pyJianYingDraft 不兜底；validator E 段会判 FAIL |
| 剪映自定义草稿目录 | 本机只读查看 `~/Movies/JianyingPro/User Data/Config/globalSetting`：Qt INI，`[General]` 段内 `currentCustomDraftPath=/Users/…/com.lveditor.draft` | 解析该键即可定位草稿根；非 ASCII 路径可能以 Qt 的 `\xHHHH` 转义存储（未实测），需解码，解析失败回退默认路径 |
| 沙盒容器 | `~/Library/Containers/com.lemon.lvpro/Data/Movies` 是指向 `~/Movies` 的符号链接 | 只需查 `~/Movies/...` 一处 `globalSetting` |
| `os.replace` | Python 文档 | 同一文件系统内原子；临时文件必须与目标同目录 |
| ffmpeg 输出格式推断 | ffmpeg 行为 | 由输出文件扩展名推断封装格式 → 临时文件名必须保留原扩展名（`.wav`/`.mp4`），不能用 `x.mp4.tmp` |

KEY_INSIGHT: 校验器的 F 段要求素材路径真实存在，而 `bundle_media` 已把路径改写成「安装后」位置 → 校验只能在 move 到草稿根之后、register 之前做。
APPLIES_TO: Task 4 `install()` 的步骤顺序。
GOTCHA: 剪映运行中不能装（已有 `pgrep` 检查）；move 后未注册的目录剪映看不到（注册表驱动），所以「move → 校验 → register」窗口内对用户不可见，FAIL 时挪回暂存目录即可。

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: pipeline/cloud.py:28-29
class CloudError(RuntimeError):
    """云端调用的终态失败。"""
```
```python
# SOURCE: pipeline/to_jianying.py:30-32  （模块级大写常量、snake_case 函数）
DRAFT_ROOT = Path(os.environ.get("AI_CUT_DRAFT_ROOT")
                  or (Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"))
ROOT_META = DRAFT_ROOT / "root_meta_info.json"
```
新代码：异常类 `XxxError(RuntimeError)` + 一行中文 docstring；常量全大写；文件头 `# -*- coding: utf-8 -*-` + 中文模块 docstring + `from __future__ import annotations`。

### ERROR_HANDLING
```python
# SOURCE: aicut.py:48-50
def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)
```
```python
# SOURCE: aicut.py:389-392  （库函数抛领域异常，命令层转成 die）
    try:
        res = export_draft.build_windows_package(timeline, name, out)
    except (RuntimeError, FileNotFoundError) as exc:
        die(str(exc))
```
```python
# SOURCE: pipeline/to_jianying.py:51-54  （pipeline 脚本层用 sys.exit("中文原因")）
def safe_name(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        sys.exit(f"非法草稿名：{name!r}")
    return name
```
规则：库函数抛 `XxxError`；aicut 命令层 `except XxxError as exc: die(...)`；pipeline 脚本 `main()` 里 `except XxxError as exc: sys.exit(str(exc))`（GL-12 修好后打包版也能看到文字）。

### LOGGING_PATTERN
```python
# SOURCE: aicut.py:53-58
def info(msg: str) -> None:
    print(f"[·] {msg}")


def ok(msg: str) -> None:
    print(f"[✓] {msg}")
```
```python
# SOURCE: pipeline/to_jianying.py:176-178
    if not template.exists():
        print(f"[warn] 找不到 11.0 模板 {template}，跳过骨架对齐")
        return
```
全仓无 `logging`（GL-19 另做）；沿用 `print` + `[·]/[✓]/[x]/[warn]` 前缀。

### REPOSITORY_PATTERN（原子落盘）
```python
# SOURCE: aicut.py:71-75
def save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
```
```python
# SOURCE: pipeline/to_jianying.py:40-43
def write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
```
注意：现有写法用**固定** `.tmp` 名（GL-18 已证实并发会互踩）。新写的 `media_io` 一律用带随机后缀的临时名。

### SERVICE_PATTERN（依赖注入以便测试）
```python
# SOURCE: pipeline/cloud.py:36-55
class CloudClient:
    def __init__(
        self,
        cli: str = "mediakit-cli",
        *,
        ...
        sleep=time.sleep,
        ...
        runner=subprocess.run,
        env: dict | None = None,
    ) -> None:
```
```python
# SOURCE: pipeline/export_draft.py:23-24  （脚本方式运行时让仓库根可导入）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
```
新代码：`media_io.run_ffmpeg(args, *, runner=subprocess.run)`；`to_jianying.resolve_draft_root(env=None, home=None)`；剪映进程检测抽成 `jianying_running()` 便于 monkeypatch。**sys.path 用 `append` 而不是 `insert(0)`**（见 Task 4 GOTCHA）。

### TEST_STRUCTURE
```python
# SOURCE: tests/test_cloud.py:10-31
class FakeProc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def make_runner(sequence):
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        item = sequence[min(len(calls) - 1, len(sequence) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return runner, calls
```
```python
# SOURCE: tests/test_secrets.py:15-23
@pytest.fixture
def file_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CUT_SECRETS", "file")
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "cfg"))
    for var in secrets.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    # 隔离历史遗留文件，避免读到本机真实 key
    monkeypatch.setattr(secrets, "LEGACY_FILES", {}, raising=False)
    return tmp_path / "cfg"
```
```python
# SOURCE: tests/test_proc.py:21-24
def test_run_inprocess_captures_system_exit():
    code, out = proc.run_inprocess("pipeline.proc", [])
    assert code == 1  # 该模块没有 main()，应被兜住而不是抛异常
    assert "main" in out
```
约定：`from pipeline import xxx`（pytest `pythonpath=["."]`，见 `pyproject.toml`）；纯函数式 `test_<行为>()`；中文注释说明意图；`tmp_path` 造文件；不写 conftest 以外的共享 fixture 文件。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `tests/conftest.py` | CREATE | autouse fixture：把 `AI_CUT_DRAFT_ROOT` 指到 tmp、禁止测试触碰真实 `~/Movies/JianyingPro` |
| `pipeline/proc.py` | UPDATE | GL-12 `exit_code()`；GL-11 `run_inprocess` 采纳 `main()` 返回值 |
| `research/validate_draft.py` | UPDATE | 抽出可导入的 `check()`，每次调用清空全局列表（冻结版同进程重复调用会累积旧 FAIL） |
| `pipeline/to_jianying.py` | UPDATE | GL-10 分轨/过滤；GL-13 `resolve_draft_root`/`load_registry`/`install` 事务；GL-11 安装前校验门 |
| `pipeline/media_io.py` | CREATE | GL-15 共享「临时文件 → 原子改名 → `.done` 标记」+ `run_ffmpeg`（编码参数由调用方给，GL-04 兼容） |
| `aicut.py` | UPDATE | GL-10 卡片；GL-11 删除 `_validate_draft`/`DRAFT_ROOT`；GL-12 `run_cli`；GL-15 wav/proxy/clips/preview + 下游门槛 + status |
| `pipeline/build_documentary.py` | UPDATE | GL-10 `card_entries()`（aicut 复用）；GL-15 `cut_shot` 走 `media_io` |
| `pipeline/cloud.py` | UPDATE | GL-15：`transcript_raw.json` 原子写（aicut.py:210 以其存在判完成） |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 增加 `pipeline.media_io`、`pipeline.build_documentary` |
| `tests/test_proc.py` | UPDATE | GL-11/12 回归 |
| `tests/test_validate_draft.py` | CREATE | `check()` 可重复调用、`run_inprocess` 透传 FAIL 退出码 |
| `tests/test_to_jianying.py` | CREATE | GL-10/11/13 回归（真实 pyJianYingDraft，纯文本时间线，无需媒体） |
| `tests/test_media_io.py` | CREATE | GL-15 原语回归 |
| `tests/test_aicut_build.py` | CREATE | GL-10 `compose_timeline`、GL-15 aicut 各输出点、GL-12 `run_cli` |
| `tests/test_build_documentary.py` | CREATE | GL-10 `card_entries`、GL-15 `cut_shot` 改造 |
| `tests/test_cloud.py` | UPDATE | `transcript_raw.json` 原子写回归 |
| `docs/go-live-blockers.md` | UPDATE（收尾） | GL-10/11/12/13/15 状态列填提交号（登记册约定） |

## NOT Building

- **KI-11**（预览缓存哈希漏出点、切片缓存不看 in/out）：本计划只把「存在」换成「完成标记」，不改缓存键；`.done` 标记的 JSON 预留了放 `key` 的位置。
- **KI-18**（模板缺失 warn 被吞、Windows 包安装脚本假成功、导出后不调 `inspect_package`）：Windows 导出（`--dry-run`）路径**不加**校验门。
- **KI-20**（`aicut.run(check=True)` 丢 stderr）：只有改到 `media_io` 的 ffmpeg 点顺带带上 stderr 尾巴，`aicut.run` 本身不改。
- **GL-04**（libx264 → h264_videotoolbox、LGPL ffmpeg）：编码参数原样保留在各调用点。
- **GL-16**（ASR 任务绑定音频指纹、失败清 `asr_task.json`）：不碰 `asr_task.json`，不做 wav↔transcript 绑定。
- **GL-17**（任务互斥、冻结模式 `redirect_stdout`/`sys.argv` 多线程互踩）：`run_inprocess` 只改退出码解析，不加锁。
- **GL-14**（GUI Windows 导出入口）、**GL-19**（日志落盘）、**GL-06**（镜头 id 路径穿越）。
- `gui/server.py` 里 `(work / "proxy.mp4").exists()` 等展示用判断（server.py:125,139）：原子改名后 `exists()` 本身即可信，无需改。
- 不把 `aicut.compose_timeline` 与 `build_documentary` 的 `split_sub` 重复合并（只合并本次涉及的卡片逻辑）。
- 不做「旧项目半成品自动识别」（如按 ffprobe 时长判断旧 wav 是否完整）——见 Notes。

---

## Step-by-Step Tasks

> 每个 Task 严格 TDD：先写列出的回归测试 → `uv run pytest <文件>` 看到**按预期失败**（RED）→ 最小实现（GREEN）→ 全量 `uv run pytest`。基线：`112 passed`（2026-10-19 实测）。

### Task 0: 测试隔离护栏
- **ACTION**: 新建 `tests/conftest.py`。
- **IMPLEMENT**:
  ```python
  # -*- coding: utf-8 -*-
  import pytest


  @pytest.fixture(autouse=True)
  def _isolate_jianying(tmp_path, monkeypatch):
      """任何测试都不许碰真实剪映草稿库：默认把草稿根指向一个不存在的临时目录。"""
      monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(tmp_path / "jy_guard_root"))
  ```
- **MIRROR**: TEST_STRUCTURE（`test_secrets.py:15-23` 的 monkeypatch 隔离）。
- **IMPORTS**: `pytest`。
- **GOTCHA**: `resolve_draft_root` 的单测需要 `monkeypatch.delenv("AI_CUT_DRAFT_ROOT")` 才能测到 globalSetting 分支。
- **VALIDATE**: `uv run pytest` 仍 112 passed。

### Task 1: GL-12 + GL-11(a) —— 退出码解析与 `main()` 返回值
- **ACTION**: 改 `pipeline/proc.py:58-75`、`aicut.py:725-735`。
- **先写的回归测试**（`tests/test_proc.py` 追加）：
  ```python
  import sys
  import textwrap

  import pytest


  def _fake_module(tmp_path, monkeypatch, name, body):
      (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
      monkeypatch.syspath_prepend(str(tmp_path))
      return name


  def test_run_inprocess_keeps_text_of_sys_exit_string(tmp_path, monkeypatch):
      mod = _fake_module(tmp_path, monkeypatch, "fake_exit_text", """
          import sys
          def main():
              print("开始")
              sys.exit("找不到剪映草稿库")
      """)
      code, out = proc.run_inprocess(mod, [])
      assert code == 1
      assert "找不到剪映草稿库" in out  # GL-12：文字不能丢，也不能抛 ValueError


  @pytest.mark.parametrize("ret, expected", [(None, 0), (0, 0), (1, 1), (3, 3)])
  def test_run_inprocess_honors_main_return_value(tmp_path, monkeypatch, ret, expected):
      mod = _fake_module(tmp_path, monkeypatch, f"fake_ret_{expected}_{ret}", f"""
          def main():
              return {ret!r}
      """)
      code, _ = proc.run_inprocess(mod, [])
      assert code == expected  # GL-11：validate_draft.main() 返回 1 必须透传


  @pytest.mark.parametrize("exit_arg, expected", [(None, 0), (0, 0), (2, 2), (True, 1)])
  def test_run_inprocess_int_exit_codes(tmp_path, monkeypatch, exit_arg, expected):
      mod = _fake_module(tmp_path, monkeypatch, f"fake_exit_{expected}_{exit_arg}", f"""
          import sys
          def main():
              sys.exit({exit_arg!r})
      """)
      assert proc.run_inprocess(mod, [])[0] == expected


  def test_run_inprocess_restores_argv(tmp_path, monkeypatch):
      before = list(sys.argv)
      mod = _fake_module(tmp_path, monkeypatch, "fake_exit_restore", """
          import sys
          def main():
              sys.exit("x")
      """)
      proc.run_inprocess(mod, ["a"])
      assert sys.argv == before
  ```
  `tests/test_aicut_build.py`（新建）先放：
  ```python
  import aicut


  def test_run_cli_keeps_text_of_sys_exit_string(monkeypatch, capsys):
      def boom(argv):
          raise SystemExit("剪映正在运行，请先完全退出（Cmd+Q）再安装")
      monkeypatch.setattr(aicut, "main", boom)
      assert aicut.run_cli(["build", "x"]) == 1
      assert "剪映正在运行" in capsys.readouterr().out
  ```
  RED 预期：字符串用例抛 `ValueError: invalid literal for int()`；返回值用例 `code == 0 != 1`。
- **IMPLEMENT**（`pipeline/proc.py`）：
  ```python
  def exit_code(exc: SystemExit, out=None) -> int:
      """SystemExit → 退出码。sys.exit("文字") 按 Python 语义记 1，并把文字写进输出（GL-12）。"""
      code = exc.code
      if code is None:
          return 0
      if isinstance(code, int):  # bool 是 int 的子类：True → 1
          return int(code)
      if out is not None:
          out.write(f"{code}\n")
      return 1


  def run_inprocess(module_name: str, argv: list[str]) -> tuple[int, str]:
      """导入模块并以 argv 运行它的 main()，返回 (退出码, 输出)。

      main() 返回 int 时视为退出码（validate_draft.main 返回 1 表示 FAIL，GL-11）。
      """
      out = io.StringIO()
      old_argv = sys.argv
      sys.argv = [module_name, *argv]
      code = 0
      try:
          module = importlib.import_module(module_name)
          with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
              ret = module.main()
          if isinstance(ret, int):
              code = int(ret)
      except SystemExit as exc:
          code = exit_code(exc, out)
      except Exception:  # noqa: BLE001 - 打包环境里必须把错误变成日志
          code = 1
          out.write(traceback.format_exc())
      finally:
          sys.argv = old_argv
      return code, out.getvalue()
  ```
  `aicut.py:725-735`：
  ```python
  def run_cli(argv: list[str]) -> int:
      """执行一条命令并返回退出码（供 GUI 在同一进程里调用）。"""
      try:
          main(argv)
          return 0
      except SystemExit as exc:
          return proc.exit_code(exc, sys.stdout)
      except Exception:  # noqa: BLE001
          import traceback
          traceback.print_exc()
          return 1
  ```
- **MIRROR**: ERROR_HANDLING；现有 `run_inprocess` 结构不变，只替换两处。
- **IMPORTS**: 无新增（`aicut` 已 `from pipeline import proc`）。
- **GOTCHA**: `exit_code` 写文字到 `out` 时 `out` 已离开 `redirect_stdout` 上下文——直接写 `StringIO` 对象，不要 `print`。`run_cli` 里 `sys.stdout` 在 GUI 冻结模式下已被重定向到任务日志（`gui/server.py:49, 257`），所以写 `sys.stdout` 即进日志。不要动 `sys.argv` 的线程问题（GL-17）。
- **VALIDATE**: `uv run pytest tests/test_proc.py tests/test_aicut_build.py -q` 全绿；原 `test_run_inprocess_captures_system_exit` 仍绿。

### Task 2: GL-11(b) —— `validate_draft.check()` 可导入、可重复调用
- **ACTION**: 重构 `research/validate_draft.py:33-66, 224-244`，CLI 行为（输出格式、退出码）保持不变。
- **先写的回归测试**（`tests/test_validate_draft.py` 新建）：
  ```python
  import json

  from pipeline import proc
  from research import validate_draft as vd


  def _good_draft(tmp_path):
      d = tmp_path / "good"
      d.mkdir()
      content = {k: {} for k in ("canvas_config", "config", "keyframes")}
      content.update({"duration": 1_000_000, "fps": 30.0, "id": "48F27DD5-BD09-41F9-A570-4415480DE4A7",
                      "materials": {}, "tracks": [], "version": 360000, "new_version": "x"})
      (d / "draft_content.json").write_text(json.dumps(content), encoding="utf-8")
      (d / "draft_meta_info.json").write_text("{}", encoding="utf-8")
      return d


  def test_check_does_not_carry_fails_between_calls(tmp_path):
      bad = tmp_path / "bad"; bad.mkdir()
      assert vd.check(str(bad))["fails"], "缺 draft_content.json 应判 FAIL"
      assert vd.check(str(_good_draft(tmp_path)))["fails"] == []  # 冻结版同进程第二次调用不能带着上一次的 FAIL


  def test_run_inprocess_propagates_validation_fail(tmp_path):
      bad = tmp_path / "bad"; bad.mkdir()
      code, out = proc.run_inprocess("research.validate_draft", [str(bad)])
      assert code == 1 and "FAIL" in out
  ```
  RED 预期：`AttributeError: module has no attribute 'check'`；第二个用例在 Task 1 前会是 0。
  > `_good_draft` 已在 scratchpad 用现有 CLI 验证：`OK=9 WARN=2 FAIL=0 => PASS`。
- **IMPLEMENT**:
  ```python
  DEFAULT_REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "base_template_11.0.json")


  def check(draft_dir: str, ref_schema: str = DEFAULT_REF) -> dict:
      """校验一个草稿目录，返回 {"fails", "warns", "oks"}（不打印）。

      模块级列表在冻结版里会被同进程重复调用累积，所以每次先清空。
      """
      fails.clear(); warns.clear(); oks.clear()
      d = os.path.abspath(draft_dir)
      ...  # 原 main() 第 56 行起的全部检查逻辑原样搬入；
           # 两处 `report(d); return 1` 改为 `return _result()`；
           # `args.ref_schema` 改为参数 `ref_schema`
      return _result()


  def _result() -> dict:
      return {"fails": list(fails), "warns": list(warns), "oks": list(oks)}


  def main() -> int:
      ap = argparse.ArgumentParser()
      ap.add_argument("draft_dir")
      ap.add_argument("--ref-schema", default=DEFAULT_REF)
      args = ap.parse_args()
      res = check(args.draft_dir, args.ref_schema)
      report(os.path.abspath(args.draft_dir))
      return 1 if res["fails"] else 0
  ```
- **MIRROR**: 现有 `ok/warn/fail` 帮助函数与 `report()` 原样保留。
- **IMPORTS**: 无新增。
- **GOTCHA**: 校验逻辑一行都不要改（只搬家）；`report()` 读的是模块级列表，必须在 `check()` 之后调用。并发调用仍不安全（GL-17 再说），本计划只保证串行重复调用正确。
- **VALIDATE**: `uv run pytest tests/test_validate_draft.py -q`；手工 `uv run python research/validate_draft.py "<任一已有草稿>"` 输出格式与改前一致（改前实测 `九月一号_v4` → `OK=65 WARN=0 FAIL=0 => PASS`）。

### Task 3: GL-10 —— 字幕卡不与字幕同轨、不产生负时长
- **ACTION**: 改 `pipeline/build_documentary.py:102-108`（抽 `card_entries`）、`aicut.py:512-517`（复用）、`pipeline/to_jianying.py:71-75, 99-113`（分轨 + 防御过滤）。
- **先写的回归测试**：
  `tests/test_build_documentary.py`（新建）：
  ```python
  from pipeline import build_documentary as bd


  def test_card_entries_drops_card_starting_after_total():
      cards = [{"at": 0.0, "dur": 4.5, "text": "片头"}, {"at": 170.0, "dur": 5.5, "text": "片尾"}]
      out = bd.card_entries(cards, total=150.0, size=6.8)
      assert [c["text"] for c in out] == ["片头"]
      assert all(c["end"] > c["start"] for c in out)


  def test_card_entries_clips_end_to_total():
      out = bd.card_entries([{"at": 2.0, "dur": 10.0, "text": "x"}], total=5.0, size=6.8)
      assert out[0]["end"] == 5.0 and out[0]["style"]["align"] == 5
  ```
  `tests/test_aicut_build.py` 追加：
  ```python
  PRESET_JISHI = {"subtitle": {"max_chars": 14, "size": 6.5}, "card": {"size": 6.8},
                  "cards": [{"at": 0.0, "dur": 4.5, "text": "片头"},
                            {"at": 170.0, "dur": 5.5, "text": "片尾"}]}


  def test_compose_timeline_has_no_nonpositive_text(tmp_path):
      shots = [{"id": "S01", "in": 0.0, "out": 150.0, "sub": "你好，世界。"}]
      tl = aicut.compose_timeline({"title": "t"}, PRESET_JISHI, shots, tmp_path, {"S01": 150.0})
      assert all(t["end"] > t["start"] for t in tl["text"])
      assert "片尾" not in [t["text"] for t in tl["text"]]
  ```
  `tests/test_to_jianying.py`（新建，本 Task 先放这几条）：
  ```python
  import json

  from pipeline import to_jianying as tj

  SUB = {"style": {"align": 2}}
  CARD = {"style": {"align": 5}}


  def text_timeline(texts):
      return {"project": {"width": 1080, "height": 1920, "fps": 30},
              "video": [], "audio": [], "text": texts}


  def test_build_staging_card_overlapping_subtitle_does_not_crash(tmp_path):
      tl = text_timeline([{"text": "第一句", "start": 0.0, "end": 2.0, **SUB},
                          {"text": "片头卡", "start": 0.0, "end": 4.5, **CARD}])
      d = tj.build_staging(tl, tmp_path / "stg", "N")  # 改前：SegmentOverlap
      content = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
      text_tracks = [t for t in content["tracks"] if t["type"] == "text"]
      assert len(text_tracks) == 2


  def test_build_staging_skips_nonpositive_text(tmp_path):
      tl = text_timeline([{"text": "坏卡", "start": 5.0, "end": 3.0, **CARD},
                          {"text": "好字幕", "start": 0.0, "end": 1.0, **SUB}])
      d = tj.build_staging(tl, tmp_path / "stg", "N")
      content = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
      durs = [s["target_timerange"]["duration"] for t in content["tracks"] for s in t["segments"]]
      assert durs and all(x > 0 for x in durs)


  def test_layout_texts_trims_same_track_overlap():
      out = tj.layout_texts([{"text": "a", "start": 0.0, "end": 2.0, **SUB},
                             {"text": "b", "start": 1.5, "end": 3.0, **SUB}])
      assert out[tj.SUBTITLE_TRACK][1]["start"] == 2.0
      assert out[tj.CARD_TRACK] == []
  ```
  RED 预期：`SegmentOverlap`；负时长用例 `durs` 含负数；`card_entries`/`layout_texts` 不存在。
- **IMPLEMENT**:
  `pipeline/build_documentary.py`（替换 102-108 的循环，新增函数放在 `cut_shot` 之后）：
  ```python
  CARD_SIZE = 6.8
  CARD_ALIGN = 5          # 时间轴约定：5=居中字幕卡（见 to_jianying / render_preview）


  def card_entries(cards: list[dict], total: float, size: float = CARD_SIZE) -> list[dict]:
      """片头/片尾字幕卡 → 时间轴文字项；超出成片时长的卡跳过，结尾截到 total（GL-10）。"""
      out = []
      for card in cards:
          start = float(card["at"])
          end = min(start + float(card["dur"]), total)
          if end <= start:
              print(f"[warn] 字幕卡 {card['text']!r} 在 {start:.1f}s，超出成片时长 {total:.1f}s，已跳过")
              continue
          out.append({"id": f"card_{card['at']}", "text": card["text"],
                      "start": start, "end": round(end, 3),
                      "style": {"size": size, "color": [1, 1, 1], "bold": True,
                                "align": CARD_ALIGN}})
      return out
  ```
  `main()` 里：`timeline["text"] += card_entries(spec.get("cards", []), t)`。
  `aicut.py:512-517` 替换为：
  ```python
      tl["text"] += build_documentary.card_entries(
          preset.get("cards", []), t, size=preset.get("card", {}).get("size", 6.8))
  ```
  并在 `aicut.py:34-36` 的 import 列表加 `build_documentary`。
  `pipeline/to_jianying.py`：
  ```python
  SUBTITLE_TRACK, CARD_TRACK = "subtitle", "card"
  CARD_ALIGN = 5
  MIN_TEXT_SECONDS = 0.001


  def layout_texts(items: list[dict]) -> dict[str, list[dict]]:
      """字幕与字幕卡分两条文本轨；丢弃非正时长；同轨重叠时把后者起点推到前者终点（GL-10）。"""
      out: dict[str, list[dict]] = {SUBTITLE_TRACK: [], CARD_TRACK: []}
      for t in sorted(items, key=lambda x: (float(x["start"]), float(x["end"]))):
          align = int(t.get("style", {}).get("align", 1))
          track = CARD_TRACK if align == CARD_ALIGN else SUBTITLE_TRACK
          prev_end = out[track][-1]["end"] if out[track] else float("-inf")
          start = max(float(t["start"]), prev_end)
          if float(t["end"]) - start < MIN_TEXT_SECONDS:
              print(f"[warn] 跳过时长无效的文字 {t['text'][:20]!r}（{t['start']}–{t['end']}s）")
              continue
          out[track] = [*out[track], {**t, "start": start, "end": float(t["end"])}]
      return out
  ```
  `build_staging` 中：删除 `if tl.get("text"): script.append_track(TrackSpec(TrackType.text))`，改为
  ```python
      texts = layout_texts(tl.get("text", []))
      for track_name in (SUBTITLE_TRACK, CARD_TRACK):   # 后追加的在上层：卡片压在字幕上方
          if texts[track_name]:
              script.append_track(draft.TrackSpec(draft.TrackType.text, name=track_name))
  ```
  文字循环改为遍历 `texts.items()`，`trange(us(t["start"]), us(t["end"] - t["start"]))` 改 `trange_seconds(t["start"], end=t["end"])`，`script.add_segment(draft.TextSegment(...), track_name)`；`style`/`clip_settings` 原样。import 行 `from pyJianYingDraft import trange` 改为 `from pyJianYingDraft import trange, trange_seconds`。
- **MIRROR**: LOGGING_PATTERN（`[warn]`）；`pos_y = {2: -0.72, 5: 0.10}` 原样保留。
- **IMPORTS**: `aicut.py`: `from pipeline import (..., build_documentary, ...)`。
- **GOTCHA**:
  - 存在两条文本轨后，`add_segment` **必须**传轨名，否则 `NameError`（`_script_file_tracks.py:43-45`）。
  - 视频轨仍是唯一的 `TrackType.video`，视频/音频 `add_segment` 不用改。
  - 字幕全部为空时不要建空文本轨（与原 `if tl.get("text")` 语义一致）。
  - `build_documentary` 被 aicut 导入后，Task 6 给它加的 `sys.path.append` 也会在 aicut 进程里执行一次——幂等、无害。
- **VALIDATE**: `uv run pytest tests/test_to_jianying.py tests/test_build_documentary.py tests/test_aicut_build.py -q`；scratchpad 已验证「subtitle + card 两轨 → `normalize/bundle_media/align_with_template/macify` → validate_draft」为 `OK=13 WARN=0 FAIL=0 => PASS`。

### Task 4: GL-13 + GL-11(c) —— 草稿根定位、原子安装、校验门、回滚
- **ACTION**: 重写 `pipeline/to_jianying.py:30-32`（常量 → 函数）、`190-241`（`macify` 增加 `root` 参数）、`244-282`（`register` → `build_entry` + `with_entry`）、`285-317`（`main` + 新 `install`）；`aicut.py:43, 131-140, 584` 删除 `DRAFT_ROOT` 与 `_validate_draft`。
- **先写的回归测试**（`tests/test_to_jianying.py` 追加）：
  ```python
  import pytest

  from pipeline import proc


  @pytest.fixture
  def jy_root(tmp_path, monkeypatch):
      root = tmp_path / "draft_root"
      root.mkdir()
      (root / "root_meta_info.json").write_text(json.dumps(
          {"all_draft_store": [], "draft_ids": 1, "root_path": str(root)}), encoding="utf-8")
      monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(root))
      monkeypatch.setattr(tj, "jianying_running", lambda: False)  # 开发机上剪映可能真在跑
      return root


  def staged(tmp_path, root, name="T"):
      d = tj.build_staging(text_timeline([{"text": "字幕", "start": 0.0, "end": 1.0, **SUB}]),
                           tmp_path / "stg", name)
      draft_id = tj.normalize(d)
      size = tj.bundle_media(d, root / name)
      info = tj.macify(d, name, size, draft_id, root)
      return d, info, size


  def registry(root):
      return json.loads((root / "root_meta_info.json").read_text(encoding="utf-8"))


  def test_install_registers_validated_draft(tmp_path, jy_root):
      d, info, size = staged(tmp_path, jy_root)
      target = tj.install(d, jy_root, "T", info, size)
      assert (target / "draft_info.json").exists()
      assert not (target / tj.INSTALL_MARKER).exists()
      assert registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"


  def test_install_rolls_back_when_register_fails(tmp_path, jy_root, monkeypatch):
      before = (jy_root / "root_meta_info.json").read_bytes()
      d, info, size = staged(tmp_path, jy_root)
      real = tj.write_json

      def flaky(path, obj):
          if path.name == "root_meta_info.json":
              raise OSError("disk full")
          real(path, obj)
      monkeypatch.setattr(tj, "write_json", flaky)
      with pytest.raises(OSError):
          tj.install(d, jy_root, "T", info, size)
      assert not (jy_root / "T").exists()  # 不留孤儿
      assert (jy_root / "root_meta_info.json").read_bytes() == before
      monkeypatch.setattr(tj, "write_json", real)
      tj.install(d, jy_root, "T", info, size)  # 重试不报「已存在」


  def test_install_rejects_draft_failing_validation(tmp_path, jy_root):
      d, info, size = staged(tmp_path, jy_root)
      (d / "draft_meta_info.json").unlink()  # 校验 A 段 FAIL
      with pytest.raises(tj.InstallError, match="校验未通过"):
          tj.install(d, jy_root, "T", info, size)
      assert not (jy_root / "T").exists()
      assert registry(jy_root)["all_draft_store"] == []
      assert d.exists(), "未通过校验的草稿应挪回暂存目录供排查"


  def test_install_clears_own_orphan_from_crash(tmp_path, jy_root):
      orphan = jy_root / "T"; orphan.mkdir()
      (orphan / tj.INSTALL_MARKER).write_text("T", encoding="utf-8")
      d, info, size = staged(tmp_path, jy_root)
      tj.install(d, jy_root, "T", info, size)
      assert registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"


  def test_install_never_touches_user_folder_with_same_name(tmp_path, jy_root):
      mine = jy_root / "T"; mine.mkdir(); (mine / "keep.txt").write_text("x")
      d, info, size = staged(tmp_path, jy_root)
      with pytest.raises(tj.InstallError, match="已存在"):
          tj.install(d, jy_root, "T", info, size)
      assert (mine / "keep.txt").exists()


  @pytest.mark.parametrize("setup", ["no_root", "no_meta", "bad_json"])
  def test_load_registry_clear_error_when_jianying_missing(tmp_path, setup):
      root = tmp_path / "r"
      if setup != "no_root":
          root.mkdir()
      if setup == "bad_json":
          (root / "root_meta_info.json").write_text("{坏", encoding="utf-8")
      with pytest.raises(tj.InstallError, match="剪映"):
          tj.load_registry(root)


  def test_resolve_draft_root_prefers_env(monkeypatch, tmp_path):
      monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(tmp_path / "x"))
      assert tj.resolve_draft_root(home=tmp_path) == tmp_path / "x"


  def test_resolve_draft_root_reads_jianying_custom_path(monkeypatch, tmp_path):
      monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
      setting = tmp_path / tj.JY_SETTING
      setting.parent.mkdir(parents=True)
      setting.write_text("[General]\ncurrentCustomDraftPath=/Volumes/外接盘/drafts\n", encoding="utf-8")
      assert tj.resolve_draft_root(home=tmp_path) == Path("/Volumes/外接盘/drafts")


  def test_resolve_draft_root_decodes_qt_escapes(monkeypatch, tmp_path):
      monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
      setting = tmp_path / tj.JY_SETTING
      setting.parent.mkdir(parents=True)
      setting.write_text("[General]\ncurrentCustomDraftPath=/Volumes/\\x5916\\x63a5/d\n", encoding="utf-8")
      assert tj.resolve_draft_root(home=tmp_path) == Path("/Volumes/外接/d")


  def test_resolve_draft_root_default(monkeypatch, tmp_path):
      monkeypatch.delenv("AI_CUT_DRAFT_ROOT", raising=False)
      assert tj.resolve_draft_root(home=tmp_path) == tmp_path / tj.DEFAULT_DRAFT_ROOT


  def test_frozen_path_reports_missing_jianying(tmp_path, monkeypatch):
      tl = tmp_path / "timeline.json"
      tl.write_text(json.dumps(text_timeline([{"text": "a", "start": 0.0, "end": 1.0, **SUB}])),
                    encoding="utf-8")
      monkeypatch.setattr(tj, "jianying_running", lambda: False)
      code, out = proc.run_inprocess("pipeline.to_jianying",
                                     [str(tl), "--name", "T", "--staging", str(tmp_path / "stg")])
      assert code == 1 and "找不到剪映草稿库" in out  # GL-12 + GL-13：conftest 指向的根不存在


  def test_main_installs_end_to_end(tmp_path, jy_root, monkeypatch):
      tl = tmp_path / "timeline.json"
      tl.write_text(json.dumps(text_timeline([{"text": "a", "start": 0.0, "end": 1.0, **SUB},
                                              {"text": "卡", "start": 0.0, "end": 0.8, **CARD}])),
                    encoding="utf-8")
      code, out = proc.run_inprocess("pipeline.to_jianying",
                                     [str(tl), "--name", "T", "--staging", str(tmp_path / "stg")])
      assert code == 0, out
      assert "校验通过" in out and registry(jy_root)["all_draft_store"][0]["draft_name"] == "T"


  def test_dry_run_does_not_require_jianying(tmp_path, monkeypatch):
      # Windows 导出（export_draft）走 --dry-run + 不存在的临时根，必须继续可用
      tl = tmp_path / "timeline.json"
      tl.write_text(json.dumps(text_timeline([{"text": "a", "start": 0.0, "end": 1.0, **SUB}])),
                    encoding="utf-8")
      code, out = proc.run_inprocess("pipeline.to_jianying",
                                     [str(tl), "--name", "T", "--staging", str(tmp_path / "stg"), "--dry-run"])
      assert code == 0, out
  ```
  RED 预期：`macify()` 参数个数不符 / `install`、`InstallError`、`resolve_draft_root` 不存在；冻结路径用例在 Task 1 前抛 `ValueError`。
- **IMPLEMENT**（`pipeline/to_jianying.py`）：
  ```python
  ROOT = Path(__file__).resolve().parent.parent
  if str(ROOT) not in sys.path:
      sys.path.append(str(ROOT))  # 脚本方式运行时让 research.validate_draft 可导入；append 防遮蔽三方包

  DEFAULT_DRAFT_ROOT = Path("Movies/JianyingPro/User Data/Projects/com.lveditor.draft")  # 相对 home
  JY_SETTING = Path("Movies/JianyingPro/User Data/Config/globalSetting")                  # 相对 home
  ROOT_META_NAME = "root_meta_info.json"
  INSTALL_MARKER = ".aicut_installing"
  VALIDATION_FAIL_LINES = 10


  class InstallError(RuntimeError):
      """安装进剪映失败；已回滚，剪映草稿库保持原样。"""


  def _custom_draft_path(home: Path) -> Path | None:
      """读剪映「全局设置 → 草稿位置」（Qt INI 的 currentCustomDraftPath）。"""
      try:
          text = (home / JY_SETTING).read_text(encoding="utf-8", errors="replace")
      except OSError:
          return None
      m = re.search(r"^currentCustomDraftPath=(.*)$", text, re.M)
      if not m:
          return None
      raw = m.group(1).strip().strip('"')
      raw = re.sub(r"\\x([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), raw)
      return Path(raw) if raw.startswith("/") else None


  def resolve_draft_root(env=None, home: Path | None = None) -> Path:
      """草稿根：AI_CUT_DRAFT_ROOT > 剪映自定义草稿位置 > 默认位置。只算路径，不做存在性检查。"""
      env = os.environ if env is None else env
      home = Path.home() if home is None else home
      if env.get("AI_CUT_DRAFT_ROOT"):
          return Path(env["AI_CUT_DRAFT_ROOT"]).expanduser()
      return _custom_draft_path(home) or home / DEFAULT_DRAFT_ROOT


  def load_registry(root: Path) -> dict:
      meta = root / ROOT_META_NAME
      if not root.is_dir() or not meta.is_file():
          raise InstallError(
              f"找不到剪映草稿库：{meta}\n"
              "请确认已安装剪映专业版并至少打开过一次；如果在剪映「全局设置 → 草稿位置」"
              "改过目录，请确认该目录（含外接盘）当前可以访问。")
      try:
          reg = json.loads(meta.read_text(encoding="utf-8"))
      except (OSError, json.JSONDecodeError) as exc:
          raise InstallError(f"剪映草稿注册表读不了（{exc}）：{meta}；未做任何改动") from exc
      if not isinstance(reg, dict) or not isinstance(reg.get("all_draft_store"), list):
          raise InstallError(f"剪映草稿注册表格式不认识：{meta}；未做任何改动")
      return reg


  def jianying_running() -> bool:
      return subprocess.run(["pgrep", "-f", "MacOS/VideoFusion-macOS"],
                            capture_output=True).returncode == 0


  def _is_registered(registry: dict, target: Path) -> bool:
      return any(e.get("draft_fold_path") == str(target) for e in registry["all_draft_store"])


  def _clear_own_orphan(target: Path, registry: dict) -> None:
      """上次安装被强杀留下的目录（带安装中标记且未注册）可以安全清掉。"""
      if (target / INSTALL_MARKER).exists() and not _is_registered(registry, target):
          print(f"[warn] 清理上次未完成的安装：{target}")
          shutil.rmtree(target)


  def _validate_or_raise(target: Path) -> None:
      from research import validate_draft  # 冻结版为 hiddenimport（ai-cut.spec:23）
      res = validate_draft.check(str(target))
      if res["fails"]:
          lines = "\n".join(f"  [FAIL] {m}" for m in res["fails"][:VALIDATION_FAIL_LINES])
          raise InstallError(f"草稿静态校验未通过，已撤销安装：\n{lines}")
      print(f"校验通过：OK={len(res['oks'])} WARN={len(res['warns'])} FAIL=0")


  def _move_back(target: Path, draft_dir: Path) -> None:
      try:
          shutil.move(str(target), str(draft_dir))
          (draft_dir / INSTALL_MARKER).unlink(missing_ok=True)
          print(f"未通过的草稿保留在暂存目录：{draft_dir}")
      except OSError:
          shutil.rmtree(target, ignore_errors=True)


  def install(draft_dir: Path, root: Path, name: str, info: dict, size: int) -> Path:
      """move → 校验 → 注册，任何一步失败都回滚到安装前（GL-13 / GL-11）。"""
      registry = load_registry(root)
      target = root / name
      _clear_own_orphan(target, registry)
      if target.exists():
          raise InstallError(f"草稿已存在：{target}（换名字，或先在剪映里删除）")
      meta = root / ROOT_META_NAME
      bak = meta.with_suffix(meta.suffix + f".{time.strftime('%Y%m%d-%H%M%S')}.bak")
      shutil.copy2(meta, bak)
      (draft_dir / INSTALL_MARKER).write_text(name, encoding="utf-8")
      moved = registered = False
      try:
          shutil.move(str(draft_dir), str(target))
          moved = True
          _validate_or_raise(target)
          new_registry = with_entry(registry, build_entry(info, name, root, size))
          registered = True
          write_json(meta, new_registry)
          (target / INSTALL_MARKER).unlink()
      except BaseException:
          if registered:
              shutil.copy2(bak, meta)
          if moved:
              _move_back(target, draft_dir)
          else:
              (draft_dir / INSTALL_MARKER).unlink(missing_ok=True)
              if (target / INSTALL_MARKER).exists():  # 跨卷 move 半拷：标记随目录过去了
                  shutil.rmtree(target, ignore_errors=True)
          raise
      print(f"已注册；注册表备份：{bak}")
      return target
  ```
  `register()` 拆为：
  ```python
  def build_entry(info: dict, name: str, root: Path, materials_size: int = 0) -> dict:
      ...  # 原 register 第 249-273 行的 entry 字面量，DRAFT_ROOT → root


  def with_entry(registry: dict, entry: dict) -> dict:
      """返回新注册表：同名旧条目去掉，新条目放最前（不改入参）。"""
      rest = [e for e in registry["all_draft_store"] if e.get("draft_name") != entry["draft_name"]]
      return {**registry, "all_draft_store": [entry, *rest]}
  ```
  `macify(draft_dir, name, materials_size, draft_id, root)`：第 211-212 行 `DRAFT_ROOT` → `root`。
  `main()`：
  ```python
      name = safe_name(args.name)
      root = resolve_draft_root()
      if not args.dry_run:
          if jianying_running():
              sys.exit("剪映正在运行，请先完全退出（Cmd+Q）再安装")
          try:
              load_registry(root)  # 先确认剪映在，再花几分钟拷媒体
          except InstallError as exc:
              sys.exit(str(exc))
      tl = json.loads(Path(args.timeline).read_text(encoding="utf-8"))
      draft_dir = build_staging(tl, Path(args.staging), name)
      draft_id = normalize(draft_dir)
      size = bundle_media(draft_dir, root / name)
      align_with_template(draft_dir, ROOT / "research/base_template_11.0.json")
      info = macify(draft_dir, name, size, draft_id, root)
      print(f"草稿已生成：{draft_dir}（{info['duration'] / 1e6:.2f}s，媒体 {size / 1e6:.1f}MB）")
      if args.dry_run:
          print("dry-run：未安装进剪映")
          return
      try:
          install(draft_dir, root, name, info, size)
      except InstallError as exc:
          sys.exit(str(exc))
      print(f"完成。打开剪映 → 本地草稿 → {name}")
  ```
  删除模块级 `DRAFT_ROOT`、`ROOT_META`；文件头 import 加 `re`。
  `aicut.py`：删除第 43 行 `DRAFT_ROOT`、第 131-140 行 `_validate_draft`、第 584 行调用；第 583 行改 `ok(f"剪映草稿：{draft_name}（已通过静态校验）")`；第 567 行 `info("生成剪映草稿（安装前静态校验，FAIL 不交付）…")`。
- **MIRROR**: ERROR_HANDLING（`XxxError` + `sys.exit(str(exc))`）、REPOSITORY_PATTERN（`write_json` 原子替换 + 备份）、SERVICE_PATTERN（`home`/`env` 注入）。
- **IMPORTS**: `to_jianying.py` 新增 `import re`；函数内 `from research import validate_draft`。
- **GOTCHA**:
  - **不要**在模块导入时解析草稿根（原 `DRAFT_ROOT` 常量在冻结版同进程只算一次、测试无法隔离）；每次 `main()` 调 `resolve_draft_root()`。
  - `sys.path.append`（不是 `insert(0)`）：仓库根有本地 `packaging/` 目录，`insert(0)` 会遮蔽 PyPI 的 `packaging`；`research` 不与任何三方包重名，append 即可。
  - 开发模式 to_jianying 跑在 `~/.aicut/venv` 的 Python 里（`aicut.py:98-112`）；`research/validate_draft.py` 只用标准库，可在该 venv 导入。
  - `export_draft.build_windows_package` 用 `AI_CUT_DRAFT_ROOT=<tmp>/draft_root`（不存在）+ `--dry-run`：dry-run 分支**不得**调 `load_registry`。
  - 回滚把草稿挪回 `draft_dir`（暂存），下次 `build_staging(..., allow_replace=True)` 会覆盖，无残留。
  - `_clear_own_orphan` 只删「有标记 + 未注册」的目录；用户自己的同名目录永不删除。
  - 自定义草稿位置在外接盘：`shutil.move` 跨卷是「复制 + 删除」，中途失败时 `moved=False`，暂存原件仍在；`target` 可能半拷——上面 `else` 分支只在 `target` 带 `INSTALL_MARKER`（标记随目录一起被拷过去）时才删，前面已确认 `target` 原本不存在，所以不会误删用户目录。
  - 测试里 `staged()` 不跑 `align_with_template` 也能过校验（H 段只出 WARN）；`main` 端到端用例会跑它。
- **VALIDATE**: `uv run pytest tests/test_to_jianying.py -q` 全绿；`uv run pytest tests/test_export_draft.py -q` 仍绿；`grep -n "DRAFT_ROOT\|_validate_draft" aicut.py` 无结果。

### Task 5: GL-15(a) —— `pipeline/media_io.py` 原语
- **ACTION**: 新建模块 + `tests/test_media_io.py`。
- **先写的回归测试**：
  ```python
  import subprocess
  import shutil

  import pytest

  from pipeline import media_io as mio


  class FakeProc:
      def __init__(self, code=0, err=""):
          self.returncode, self.stdout, self.stderr = code, "", err


  def test_atomic_output_commits_and_marks(tmp_path):
      dst = tmp_path / "proxy.mp4"
      with mio.atomic_output(dst) as tmp:
          assert tmp.suffix == ".mp4" and tmp.parent == dst.parent  # ffmpeg 靠扩展名选封装
          tmp.write_bytes(b"data")
      assert dst.read_bytes() == b"data" and mio.is_complete(dst)
      assert list(tmp_path.glob(".proxy.partial-*")) == []


  @pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt(), SystemExit(1)])
  def test_interrupted_write_leaves_no_final_file(tmp_path, exc):
      dst = tmp_path / "asr.wav"
      with pytest.raises(type(exc)):
          with mio.atomic_output(dst) as tmp:
              tmp.write_bytes(b"half")
              raise exc
      assert not dst.exists() and not mio.is_complete(dst)
      assert list(tmp_path.iterdir()) == []


  def test_regeneration_interrupted_invalidates_old_file(tmp_path):
      dst = tmp_path / "S01.mp4"
      with mio.atomic_output(dst) as tmp:
          tmp.write_bytes(b"old")
      with pytest.raises(RuntimeError):
          with mio.atomic_output(dst) as tmp:
              raise RuntimeError("killed")
      assert not mio.is_complete(dst)  # 决定重做就先作废旧标记


  def test_legacy_file_without_marker_is_not_complete(tmp_path):
      dst = tmp_path / "asr.wav"; dst.write_bytes(b"half-from-old-version")
      assert not mio.is_complete(dst)


  def test_size_mismatch_is_not_complete(tmp_path):
      dst = tmp_path / "a.wav"
      with mio.atomic_output(dst) as tmp:
          tmp.write_bytes(b"1234")
      dst.write_bytes(b"12")
      assert not mio.is_complete(dst)


  def test_empty_output_is_rejected(tmp_path):
      dst = tmp_path / "a.wav"
      with pytest.raises(mio.MediaError):
          with mio.atomic_output(dst):
              pass
      assert not dst.exists()


  def test_stale_partials_from_killed_run_are_cleaned(tmp_path):
      stale = tmp_path / ".proxy.partial-deadbeef.mp4"; stale.write_bytes(b"x")
      with mio.atomic_output(tmp_path / "proxy.mp4") as tmp:
          tmp.write_bytes(b"ok")
      assert not stale.exists()


  def test_run_ffmpeg_raises_with_stderr_tail():
      runner = lambda args, **kw: FakeProc(1, "No such file or directory")
      with pytest.raises(mio.MediaError, match="No such file"):
          mio.run_ffmpeg(["-i", "x"], runner=runner)


  def test_ffmpeg_to_passes_partial_path_as_last_arg(tmp_path):
      seen = []

      def runner(args, **kw):
          seen.append(args)
          Path(args[-1]).write_bytes(b"ok")
          return FakeProc(0)
      dst = tmp_path / "S01.mp4"
      mio.ffmpeg_to(dst, ["-i", "src.mov"], runner=runner)
      assert seen[0][0] == "ffmpeg" and seen[0][-1] != str(dst)
      assert mio.is_complete(dst)


  @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="本机无 ffmpeg")
  def test_ffmpeg_to_real_ffmpeg(tmp_path):
      dst = tmp_path / "a.wav"
      mio.ffmpeg_to(dst, ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "0.2",
                          "-c:a", "pcm_s16le"])
      assert mio.is_complete(dst)
  ```
  （文件头补 `from pathlib import Path`。）
- **IMPLEMENT**:
  ```python
  # -*- coding: utf-8 -*-
  """媒体产物的「临时文件 → 原子改名 → 完成标记」（GL-15）。

  规则：ffmpeg 永远写到同目录、同扩展名的临时文件，成功后 os.replace 到最终路径，
  再写 `<文件名>.done`；判断"已完成"只认标记且大小一致，不认 exists()。
  编码参数由调用方给（GL-04 会把 libx264 换成 h264_videotoolbox），本模块不关心。
  """
  from __future__ import annotations

  import contextlib
  import glob
  import json
  import os
  import subprocess
  import uuid
  from pathlib import Path
  from typing import Iterator

  PARTIAL_TAG = ".partial-"
  DONE_SUFFIX = ".done"
  STDERR_TAIL = 800
  FFMPEG_BASE = ["ffmpeg", "-y", "-loglevel", "error"]


  class MediaError(RuntimeError):
      """ffmpeg 产物生成失败（临时文件已清理）。"""


  def done_marker(dst: Path) -> Path:
      return dst.with_name(dst.name + DONE_SUFFIX)


  def is_complete(dst: Path) -> bool:
      dst = Path(dst)
      marker = done_marker(dst)
      if not dst.is_file() or not marker.is_file():
          return False
      try:
          meta = json.loads(marker.read_text(encoding="utf-8"))
      except (OSError, json.JSONDecodeError):
          return False
      return isinstance(meta, dict) and meta.get("size") == dst.stat().st_size


  def _partial_path(dst: Path) -> Path:
      return dst.with_name(f".{dst.stem}{PARTIAL_TAG}{uuid.uuid4().hex[:8]}{dst.suffix}")


  def _clear_stale_partials(dst: Path) -> None:
      pattern = f".{glob.escape(dst.stem)}{PARTIAL_TAG}*{glob.escape(dst.suffix)}"
      for p in dst.parent.glob(pattern):
          p.unlink(missing_ok=True)


  def _write_marker(dst: Path) -> None:
      marker = done_marker(dst)
      tmp = marker.with_name(f".{marker.name}.{uuid.uuid4().hex[:8]}")
      tmp.write_text(json.dumps({"size": dst.stat().st_size}), encoding="utf-8")
      os.replace(tmp, marker)


  @contextlib.contextmanager
  def atomic_output(dst: Path) -> Iterator[Path]:
      """yield 一个临时路径；块正常结束才改名到 dst 并写完成标记，任何异常（含中断）都不留半成品。"""
      dst = Path(dst)
      dst.parent.mkdir(parents=True, exist_ok=True)
      done_marker(dst).unlink(missing_ok=True)
      _clear_stale_partials(dst)
      tmp = _partial_path(dst)
      try:
          yield tmp
          if not tmp.is_file() or tmp.stat().st_size == 0:
              raise MediaError(f"没有产出有效文件：{dst.name}")
          os.replace(tmp, dst)
          _write_marker(dst)
      finally:
          tmp.unlink(missing_ok=True)


  def run_ffmpeg(args: list[str], *, runner=subprocess.run) -> None:
      r = runner([*FFMPEG_BASE, *args], capture_output=True, text=True,
                 encoding="utf-8", errors="replace")
      if r.returncode != 0:
          tail = (r.stderr or "").strip()[-STDERR_TAIL:]
          raise MediaError(f"ffmpeg 失败（退出码 {r.returncode}）：{tail}")


  def ffmpeg_to(dst: Path, args: list[str], *, runner=subprocess.run) -> Path:
      """ffmpeg <args> <临时文件> → 原子落到 dst。args 不含 `ffmpeg -y -loglevel` 与输出路径。"""
      with atomic_output(dst) as tmp:
          run_ffmpeg([*args, str(tmp)], runner=runner)
      return Path(dst)
  ```
- **MIRROR**: NAMING_CONVENTION、SERVICE_PATTERN（`runner` 注入）、REPOSITORY_PATTERN（随机临时名 + `os.replace`）。
- **IMPORTS**: 仅标准库。
- **GOTCHA**:
  - `ffmpeg_to` 内部按**模块全局名**调 `run_ffmpeg`，测试可 `monkeypatch.setattr(media_io, "run_ffmpeg", fake)`。
  - `glob.escape`：镜头 id/文件名可能含 `[`（GL-06/GL-23 未修前）。
  - 临时名以 `.` 开头、带 `.partial-`，`*.mp4` 型 glob 会匹配到——当前仓库没有对 clips 目录做 `*.mp4` glob（已查 `gui/server.py`），若以后要加需排除隐藏文件。
  - `.done` 标记写在产物旁；`work/clips/` 下会多出 `S01.mp4.done`，不影响 `to_jianying`（只按 timeline 里的 `source` 路径取文件）。
- **VALIDATE**: `uv run pytest tests/test_media_io.py -q`。

### Task 6: GL-15(b) —— 把所有输出点接到 `media_io`
- **ACTION**: 改 `aicut.py:199-221, 224-235, 279-291, 294-321, 429-454, 527-564, 687-714`；`pipeline/build_documentary.py:48-57, 77-81`；`pipeline/cloud.py:180-184`；`packaging/ai-cut.spec:15-24`。
- **覆盖清单（必须全部改到）**：

  | # | 位置 | 产物 | 改法 |
  |---|---|---|---|
  | 1 | `aicut.py:205-209` | `work/audio/asr.wav` | `is_complete` 判定 + `ffmpeg_to` |
  | 2 | `aicut.py:284-289` | `work/proxy.mp4` | 同上 |
  | 3 | `aicut.py:438-449` | `work/clips/<id>.mp4` | `manifest 键一致 and is_complete` + `ffmpeg_to`；每切完一镜立即存 manifest |
  | 4 | `aicut.py:557-563` | `output/vN/preview.mp4` | 抽 `ensure_preview()`；`atomic_output` 包住 `_run_pipeline(render_preview, -o <tmp>)` |
  | 5 | `pipeline/build_documentary.py:48-57, 80` | `clips/<id>.mp4` | `is_complete` + `ffmpeg_to`（保留 `-movflags +faststart`） |
  | 6 | `pipeline/cloud.py:181-183` + `aicut.py:210` | `work/transcript_raw.json` | 随机临时名 + `os.replace`（aicut 仍以存在判完成，此时存在即完整） |
  | 7 | `aicut.py:229, 299, 312` | 下游门槛 | `wav.exists()`/`proxy.exists()` → `media_io.is_complete(...)` |
  | 8 | `aicut.py:690-712` | `status` 显示 | `.wav/.mp4` 用 `is_complete`，其余仍 `exists()` |

  不改：`to_jianying.macify` 的 `draft_cover.jpg`（写在暂存目录、每次重建）；`render_preview.py` 本身（由 aicut 传临时路径）。
- **先写的回归测试**（`tests/test_aicut_build.py` 追加）：
  ```python
  import argparse
  import json
  from pathlib import Path

  import pytest

  from pipeline import media_io, schema


  @pytest.fixture
  def project(tmp_path, monkeypatch):
      monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
      pdir = tmp_path / "p"
      schema.save(pdir / "project.json", schema.default_project("p", str(tmp_path / "src.mov")))
      return pdir


  def fake_ffmpeg(calls, fail_on=None, interrupt=False):
      def run(args, **kw):
          calls.append(args)
          out = Path(args[-1])
          out.write_bytes(b"half" if interrupt else b"full")
          if interrupt:
              raise KeyboardInterrupt
          if fail_on and fail_on in str(args):
              raise media_io.MediaError("ffmpeg 失败：boom")
      return run


  def test_interrupted_audio_extract_is_not_reused(project, monkeypatch):
      calls = []
      monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls, interrupt=True))
      monkeypatch.setattr(aicut.secrets, "get", lambda p: None)
      with pytest.raises(KeyboardInterrupt):
          aicut.cmd_transcribe(argparse.Namespace(name="p"))
      wav = project / "work/audio/asr.wav"
      assert not wav.exists()                      # 改前：半截 wav 留在最终路径
      monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
      with pytest.raises(SystemExit):              # 没配 key → die，但 wav 已完整
          aicut.cmd_transcribe(argparse.Namespace(name="p"))
      assert media_io.is_complete(wav) and len(calls) == 2


  def test_legacy_wav_without_marker_is_regenerated(project, monkeypatch):
      wav = project / "work/audio/asr.wav"
      wav.parent.mkdir(parents=True); wav.write_bytes(b"half-from-old-version")
      calls = []
      monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
      monkeypatch.setattr(aicut.secrets, "get", lambda p: None)
      with pytest.raises(SystemExit):
          aicut.cmd_transcribe(argparse.Namespace(name="p"))
      assert len(calls) == 1


  def test_proxy_failure_leaves_no_proxy(project, monkeypatch):
      monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg([], fail_on="scale=-2:540"))
      monkeypatch.setattr(aicut, "_run_pipeline", lambda *a: None)
      with pytest.raises(SystemExit):
          aicut.cmd_junk(argparse.Namespace(name="p"))
      assert not (project / "work/proxy.mp4").exists()


  def test_clips_resume_after_failure(project, monkeypatch):
      shots = [{"id": "S01", "in": 0.0, "out": 1.0}, {"id": "S02", "in": 5.0, "out": 6.0}]
      c = aicut.cfg(project)
      calls = []
      monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls, fail_on="5.000"))
      with pytest.raises(SystemExit):
          aicut.ensure_clips(project, c, shots)
      clips = project / "work/clips"
      assert media_io.is_complete(clips / "S01.mp4") and not (clips / "S02.mp4").exists()
      calls.clear()
      monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg(calls))
      aicut.ensure_clips(project, c, shots)
      assert len(calls) == 1  # 只重切 S02


  def test_preview_without_marker_is_rerendered(tmp_path, monkeypatch):
      vdir = tmp_path / "v1"; vdir.mkdir()
      (vdir / "preview.mp4").write_bytes(b"half"); (vdir / ".timeline.sha").write_text("h")
      rendered = []

      def fake_pipeline(module, argv):
          rendered.append(argv[-1]); Path(argv[-1]).write_bytes(b"full")
      monkeypatch.setattr(aicut, "_run_pipeline", fake_pipeline)
      aicut.ensure_preview(vdir, "h")
      assert rendered and rendered[0] != str(vdir / "preview.mp4")
      assert media_io.is_complete(vdir / "preview.mp4")
      aicut.ensure_preview(vdir, "h")
      assert len(rendered) == 1  # 有标记 + 哈希一致 → 跳过


  def test_preview_render_failure_keeps_stamp(tmp_path, monkeypatch):
      vdir = tmp_path / "v1"; vdir.mkdir()

      def boom(module, argv):
          Path(argv[-1]).write_bytes(b"half"); aicut.die("render_preview 执行失败")
      monkeypatch.setattr(aicut, "_run_pipeline", boom)
      with pytest.raises(SystemExit):
          aicut.ensure_preview(vdir, "h")
      assert not (vdir / "preview.mp4").exists() and not (vdir / ".timeline.sha").exists()
  ```
  `tests/test_build_documentary.py` 追加：
  ```python
  def test_cut_shot_goes_through_atomic_output(tmp_path, monkeypatch):
      from pipeline import media_io
      seen = []

      def run(args, **kw):
          seen.append(args); Path(args[-1]).write_bytes(b"ok")
      monkeypatch.setattr(media_io, "run_ffmpeg", run)
      dst = tmp_path / "S01.mp4"
      bd.cut_shot(tmp_path / "src.mov", dst, 0.0, 1.0)
      assert media_io.is_complete(dst) and "+faststart" in seen[0]
  ```
  `tests/test_cloud.py` 追加：
  ```python
  def test_transcript_raw_written_atomically(tmp_path, monkeypatch):
      c, _ = client([FakeProc(out=json.dumps({"task_id": "t1"}))])
      monkeypatch.setattr(c, "wait_task", lambda *a, **k: {"utterances": []})  # 签名见 cloud.py:120
      monkeypatch.setattr(cloud.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("killed")))
      with pytest.raises(OSError):
          c.transcribe(tmp_path / "a.wav", tmp_path)
      assert not (tmp_path / "transcript_raw.json").exists()
      assert not list(tmp_path.glob("*.tmp"))
  ```
- **IMPLEMENT**:
  `aicut.py` import 列表加 `media_io`。
  ```python
  # cmd_transcribe（替换 205-209）
      if not media_io.is_complete(wav):
          info("抽音轨…")
          try:
              media_io.ffmpeg_to(wav, ["-i", c["material"], "-vn", "-ac", "1", "-ar", "16000",
                                       "-c:a", "pcm_s16le"])
          except media_io.MediaError as exc:
              die(f"抽音轨失败：{exc}")
  ```
  ```python
  # cmd_junk（替换 284-289）
      if not media_io.is_complete(proxy):
          info("生成 540p 分析代理…")
          try:
              media_io.ffmpeg_to(proxy, ["-i", c["material"], "-vf", "scale=-2:540,fps=30",
                                         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                                         "-c:a", "aac", "-b:a", "64k"])
          except media_io.MediaError as exc:
              die(f"生成分析代理失败：{exc}")
  ```
  ```python
  # ensure_clips（替换 433-452）
      manifest_path = clips_dir / "manifest.json"
      manifest = load_json(manifest_path, {})
      ...
          if manifest.get(sh["id"]) == key and media_io.is_complete(dst):
              continue
          info(f"切镜头 {sh['id']}（{sh['out'] - sh['in']:.1f}s）")
          try:
              media_io.ffmpeg_to(dst, ["-ss", f"{sh['in']:.3f}", "-t", f"{sh['out'] - sh['in']:.3f}",
                                       "-i", str(src), "-vf", CLIP_VF,
                                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"])
          except media_io.MediaError as exc:
              die(f"切镜头 {sh['id']} 失败：{exc}")
          manifest = {**manifest, sh["id"]: key}
          save_json(manifest_path, manifest)  # 每镜落盘：中断后已切好的不重切
          changed += 1
  ```
  其中 `CLIP_VF = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"` 提为模块常量（原 445-446 行字面量）。
  ```python
  def ensure_preview(vdir: Path, tl_hash: str) -> Path:
      """预览片：哈希一致且有完成标记才复用；渲染写临时文件，成功才改名（GL-15）。"""
      preview, stamp = vdir / "preview.mp4", vdir / ".timeline.sha"
      if stamp.exists() and stamp.read_text().strip() == tl_hash and media_io.is_complete(preview):
          info("预览片无变化，跳过渲染")
          return preview
      info("渲染预览片…")
      try:
          with media_io.atomic_output(preview) as tmp:
              _run_pipeline("pipeline.render_preview", [str(vdir / "timeline.json"), "-o", str(tmp)])
      except media_io.MediaError as exc:
          die(f"预览片渲染失败：{exc}")
      stamp.write_text(tl_hash)
      return preview
  ```
  `cmd_build` 第 552-564 行改为 `ensure_preview(vdir, tl_hash)` + `ok(f"预览片：{vdir / 'preview.mp4'}")`。
  下游门槛：`cmd_analyze` 第 229 行 `if not media_io.is_complete(wav) or not segs.exists()`；`cmd_scenes` 第 299 行、`cmd_quality` 第 312 行同理换 `proxy`。
  `cmd_status`：`mark = "✓" if (media_io.is_complete(p) if p.suffix in (".wav", ".mp4") else p.exists()) else "·"`。
  `pipeline/build_documentary.py` 顶部：
  ```python
  ROOT = Path(__file__).resolve().parent.parent
  if str(ROOT) not in sys.path:
      sys.path.append(str(ROOT))  # 脚本方式运行时可导入 pipeline.media_io

  from pipeline import media_io  # noqa: E402
  ```
  `cut_shot` 改为 `media_io.ffmpeg_to(dst, ["-ss", ..., "-movflags", "+faststart"])`（去掉 `"ffmpeg", "-y", "-loglevel", "error"` 前缀与输出路径）；第 80 行改 `if not media_io.is_complete(clip):`。
  `pipeline/cloud.py:181-183`：
  ```python
          raw = Path(workdir) / "transcript_raw.json"
          raw.parent.mkdir(parents=True, exist_ok=True)
          tmp = raw.with_name(f".{raw.name}.{uuid.uuid4().hex[:8]}.tmp")
          tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
          os.replace(tmp, raw)  # aicut 以"存在"判转写完成，必须原子（GL-15）
  ```
  （`cloud.py` 顶部加 `import os`；`uuid` 已导入。）
  `packaging/ai-cut.spec` hiddenimports 增加 `"pipeline.media_io"`、`"pipeline.build_documentary"`。
- **MIRROR**: ERROR_HANDLING（`except media_io.MediaError as exc: die(...)`）、LOGGING_PATTERN（`info/ok`）。
- **IMPORTS**: `aicut.py` → `media_io`；`build_documentary.py` → `from pipeline import media_io`；`cloud.py` → `import os`。
- **GOTCHA**:
  - `_run_pipeline` 失败走 `die()` → `SystemExit`（`BaseException`），`atomic_output` 的 `finally` 照样清临时文件——测试 `test_preview_render_failure_keeps_stamp` 锁定这一点。
  - `stamp.write_text` 必须在 `atomic_output` 成功退出**之后**。
  - 编码参数（`libx264`、`-crf`、`-preset`）**原样**搬到调用点，GL-04 只需替换这些参数，不碰 `media_io`。
  - `cmd_transcribe` 第 210 行 `raw.exists()` 保持不变（原子写后存在即完整）；不要顺手清 `asr_task.json`（GL-16）。
  - `build_documentary` 被 aicut 导入（Task 3），其顶部 `from pipeline import media_io` 在 aicut 进程里本来就能解析。
- **VALIDATE**: `uv run pytest -q` 全绿；`grep -n '"ffmpeg"' aicut.py pipeline/build_documentary.py` 只剩 0 处（aicut 的 ffprobe 调用不算）；`grep -n "proxy.exists()\|wav.exists()" aicut.py` 无结果。

### Task 7: 收尾验证与登记
- **ACTION**: 全量测试、手工验证（见下）、打包冒烟；提交后在 `docs/go-live-blockers.md` 把 GL-10/11/12/13/15 状态列由 `open` 改为提交号。
- **IMPLEMENT**: 无新代码。
- **MIRROR**: 登记册约定（`docs/go-live-blockers.md` 第 3 行：「关闭时在「状态」填提交号」）。
- **GOTCHA**: 仓库无 CI（无 `.github/`），本地 `uv run pytest` 即最终门；冻结路径必须用打包版冒烟一次（`run_inprocess` 的行为只有打包版走）。
- **VALIDATE**: 见 Validation Commands 与 Manual Validation。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_run_inprocess_keeps_text_of_sys_exit_string` | `sys.exit("找不到剪映草稿库")` | `code=1`，文字在 out | 是（GL-12 原崩溃点） |
| `test_run_inprocess_honors_main_return_value` | `main()` 返回 None/0/1/3 | 0/0/1/3 | 是 |
| `test_run_inprocess_int_exit_codes` | `sys.exit(None/0/2/True)` | 0/0/2/1 | 是（bool） |
| `test_run_cli_keeps_text_of_sys_exit_string` | `aicut.main` 抛 `SystemExit("…")` | 返回 1 且打印文字 | 是 |
| `test_check_does_not_carry_fails_between_calls` | 坏草稿后接好草稿 | 第二次 `fails == []` | 是（同进程累积） |
| `test_run_inprocess_propagates_validation_fail` | 空目录 | `code == 1` | |
| `test_card_entries_*` | `at=170`、`total=150` | 跳过；`end` 截断 | 是 |
| `test_compose_timeline_has_no_nonpositive_text` | 纪实3min 卡片 + 150s | 无 `end<=start` | 是 |
| `test_build_staging_card_overlapping_subtitle_does_not_crash` | 卡 0–4.5s + 字幕 0–2s | 不抛 `SegmentOverlap`；2 条文本轨 | 是（GL-10 必现） |
| `test_build_staging_skips_nonpositive_text` | start 5 end 3 | 所有 target duration > 0 | 是 |
| `test_layout_texts_trims_same_track_overlap` | 同轨重叠 | 后者起点推到前者终点 | 是 |
| `test_install_registers_validated_draft` | 正常暂存草稿 | 已注册、无安装中标记 | |
| `test_install_rolls_back_when_register_fails` | 写注册表抛 OSError | 无孤儿、注册表字节不变、可重试 | 是 |
| `test_install_rejects_draft_failing_validation` | 删掉 meta 文件 | `InstallError`，未注册，暂存保留 | 是（GL-11） |
| `test_install_clears_own_orphan_from_crash` | 带标记的未注册目录 | 自动清理后安装成功 | 是 |
| `test_install_never_touches_user_folder_with_same_name` | 用户同名目录 | `已存在`，用户文件不动 | 是 |
| `test_load_registry_clear_error_when_jianying_missing` | 无根/无注册表/坏 JSON | `InstallError` 含「剪映」 | 是 |
| `test_resolve_draft_root_*` | env / globalSetting / Qt 转义 / 缺省 | 对应路径 | 是 |
| `test_frozen_path_reports_missing_jianying` | 冻结路径 + 根不存在 | `code=1`、可读文字 | 是 |
| `test_main_installs_end_to_end` | 冻结路径全流程 | `code=0`、「校验通过」、已注册 | |
| `test_dry_run_does_not_require_jianying` | `--dry-run` + 根不存在 | `code=0` | 是（Windows 导出回归） |
| `test_atomic_output_*` / `test_interrupted_write_*` | 正常/异常/中断/SystemExit | 只有成功才有最终文件 + 标记 | 是 |
| `test_legacy_file_without_marker_is_not_complete` | 旧版半成品 | `False` | 是 |
| `test_size_mismatch_is_not_complete` / `test_empty_output_is_rejected` / `test_stale_partials_*` | | | 是 |
| `test_run_ffmpeg_raises_with_stderr_tail` | 非零退出 | `MediaError` 含 stderr | |
| `test_ffmpeg_to_real_ffmpeg` | 真 ffmpeg（无则 skip） | 完整 wav | |
| `test_interrupted_audio_extract_is_not_reused` | 抽音轨被中断 | 无 wav；重跑重新抽 | 是（GL-15 主症状） |
| `test_legacy_wav_without_marker_is_regenerated` | 旧版 wav 无标记 | 重新抽 | 是 |
| `test_proxy_failure_leaves_no_proxy` | ffmpeg 失败 | 无 proxy，`die` | |
| `test_clips_resume_after_failure` | 第 2 镜失败 | 第 1 镜保留，重跑只切第 2 镜 | 是 |
| `test_preview_without_marker_is_rerendered` / `test_preview_render_failure_keeps_stamp` | | | 是 |
| `test_cut_shot_goes_through_atomic_output` | build_documentary 切片 | 有标记、保留 faststart | |
| `test_transcript_raw_written_atomically` | `os.replace` 失败 | 无 `transcript_raw.json`、无 `.tmp` | 是 |

### Edge Cases Checklist
- [x] Empty input（空文字列表不建文本轨；ffmpeg 空产出被拒）
- [ ] Maximum size input（54 分钟素材的 proxy/wav：手工验证，见下）
- [x] Invalid types（注册表非 dict / `all_draft_store` 非 list）
- [ ] Concurrent access（GL-17 范围；`atomic_output` 用随机临时名，不会像 GL-18 那样互踩，但同一目标并发生成仍可能重复劳动）
- [x] 中断 / 强杀（KeyboardInterrupt、SystemExit、安装中标记）
- [x] Permission denied / 外接盘不可访问（`load_registry` 明确报错）
- [x] 剪映未安装 / 自定义草稿目录

---

## Validation Commands

### Static Analysis
```bash
# 项目未配置 lint / typecheck（CLAUDE.md「Lint / 类型检查：未配置」）；做语法级检查
uv run python -m compileall -q aicut.py pipeline research
```
EXPECT: 无输出、退出码 0

### Unit Tests
```bash
uv run pytest tests/test_proc.py tests/test_validate_draft.py tests/test_to_jianying.py \
              tests/test_media_io.py tests/test_aicut_build.py tests/test_build_documentary.py \
              tests/test_cloud.py tests/test_export_draft.py -q
```
EXPECT: 全部通过

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 基线 112 + 新增用例全部通过，无回归

### 测试不触碰真实剪映目录
```bash
stat -f "%Sm" "$HOME/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/root_meta_info.json"
uv run pytest -q
stat -f "%Sm" "$HOME/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/root_meta_info.json"
```
EXPECT: 前后 mtime 一致；`ls ".../com.lveditor.draft" | grep '\.bak'` 不新增

### 范围自检
```bash
grep -n "DRAFT_ROOT\|_validate_draft" aicut.py               # EXPECT: 无
grep -n "int(exc.code" aicut.py pipeline/proc.py              # EXPECT: 无
grep -n '"ffmpeg", "-y"' aicut.py pipeline/build_documentary.py   # EXPECT: 无（均经 media_io）
grep -n "proxy.exists()\|wav.exists()" aicut.py               # EXPECT: 无
```

### Browser Validation
N/A（不改 GUI 前端；GUI 行为通过退出码间接变化）

### Manual Validation
- [ ] 开发模式：`纪实3min` 预设项目 `uv run python aicut.py build <项目> --version vX`（成片 < 170s）→ 出现 `[warn] 字幕卡 … 已跳过`、`校验通过`、`[✓] 剪映草稿：…（已通过静态校验）`；剪映打开草稿，可见 `subtitle` / `card` 两条文本轨，片头卡显示正常。
- [ ] 同一命令再跑一次（同版本名）→ 报「草稿已存在」，剪映草稿库无变化。
- [ ] 校验 FAIL 路径由 `test_install_rejects_draft_failing_validation` 覆盖（端到端很难人为造出能过 `layout_texts` 的坏草稿），手工不另测。
- [ ] `AI_CUT_DRAFT_ROOT=/tmp/不存在 uv run python aicut.py build <项目>` → 在拷媒体**之前**失败，提示「找不到剪映草稿库…」。
- [ ] 抽音轨 / 生成代理时 Ctrl+C → `ls work/audio work/` 无 `asr.wav`/`proxy.mp4`、无 `.partial-` 残留；重跑重新生成。
- [ ] `aicut.py export <项目>`（Windows 包）仍成功（`--dry-run` 分支未受影响）。
- [ ] 打包冒烟：`./packaging/build_app.sh` → 打开 `dist/AI粗剪.app`，剪映运行中点导出 → 任务日志出现「剪映正在运行，请先完全退出（Cmd+Q）再安装」，任务状态 failed（改前：`[错误] invalid literal for int()`）。

---

## Acceptance Criteria
- [ ] GL-10：`纪实3min` 预设 + 任意成片时长，草稿导出不抛 `SegmentOverlap`，无非正时长文字段
- [ ] GL-11：校验 FAIL → 非零退出、不注册、不打印 `[✓]`；冻结版 `main()` 返回值生效
- [ ] GL-12：冻结版 `sys.exit("文字")` → 退出码 1 且文字进日志
- [ ] GL-13：move/校验/注册任一步失败均回滚（无孤儿、注册表原样、可直接重试）；剪映未装 / 自定义目录不可访问给出中文说明；自定义草稿目录被识别
- [ ] GL-15：wav / proxy / clips / preview / transcript_raw 中断后都不会被当作完成复用
- [ ] 全部验证命令通过；新测试按 TDD 先红后绿
- [ ] 无 lint/typecheck（未配置）——`compileall` 通过

## Completion Checklist
- [ ] 代码沿用 `[·]/[✓]/[x]/[warn]` 输出与 `XxxError → die/sys.exit` 的错误风格
- [ ] 新测试沿用 `tests/` 风格：模块级函数、`tmp_path`、`monkeypatch`、中文意图注释
- [ ] 无硬编码魔法数（`MIN_TEXT_SECONDS`、`VALIDATION_FAIL_LINES`、`STDERR_TAIL`、`CARD_ALIGN` 等为常量）
- [ ] 新注册表用 `with_entry` 返回新 dict，不原地改
- [ ] `packaging/ai-cut.spec` 已登记新模块
- [ ] `docs/go-live-blockers.md` 对应 5 行状态填提交号
- [ ] 未实现任何「NOT Building」里的条目
- [ ] 自包含：实现过程中无需再搜索代码库

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 校验门误杀剪映其实能打开的草稿 | 低 | 高 | 改前实测 `九月一号_v3/v4` 均 `FAIL=0`；FAIL 明细进日志，草稿保留在暂存目录可排查 |
| 剪映 `globalSetting` 对非 ASCII 路径的编码与假设不同 | 中 | 中 | 解析失败回退默认路径；`load_registry` 给出含实际路径的错误；手工在中文自定义目录上验证一次 |
| 剪映升级改了 `currentCustomDraftPath` 键名 | 低 | 中 | 回退默认路径 + `AI_CUT_DRAFT_ROOT` 兜底 |
| 自定义草稿目录在外接盘，跨卷 move 慢且可能半拷 | 中 | 中 | 安装中标记随目录拷贝；回滚分支按标记清理半拷目录；下次运行 `_clear_own_orphan` 兜底 |
| 旧项目无 `.done` 标记 → 首次重跑会重新抽音轨 / 重做代理片（54 分钟素材约数分钟） | 高（仅开发机旧项目） | 低 | 一次性成本；不触发 ASR 重新计费（`transcript_raw.json` 仍按存在判定） |
| 冻结版 `run_inprocess` 多线程仍互踩 `sys.argv`/stdout | 中 | 中 | GL-17 处理；本计划不扩大范围 |
| 卡片单独成轨，剪辑师习惯改变 | 低 | 低 | FR-9 要求「字幕独立可编辑」，独立卡片轨更易整体删改；见 D1/D2 |

## Notes
- **与其它条目的交互**
  - **KI-11**：`build_documentary.py:80` 与 KI-11 同一行；本计划只把 `exists()` 换成 `is_complete()`，不引入 in/out 缓存键。`.done` 是 JSON，KI-11 可在其中加 `key` 字段做「完成且参数一致」判定。
  - **KI-18**：`align_with_template` 的 `[warn]` 仍可能被吞；Windows 导出（`--dry-run`）不经过校验门，KI-18 处理导出后 `inspect_package` 时可复用 `validate_draft.check()`（届时需解决 F 段路径指向安装后位置的问题）。
  - **KI-20**：`media_io.run_ffmpeg` 已带 stderr 尾巴；`aicut.run(check=True)` 其余调用点不动。
  - **GL-04**：所有 libx264 参数仍在调用点（aicut 代理/切片、render_preview、build_documentary），`media_io` 与编码器无关；GL-04 只替换参数列表。建议 GL-04 届时把编码参数提为共享常量。
  - **GL-16**：未处理 wav ↔ ASR 任务/转写的绑定；旧项目若已有「半截 wav 对应的半截转写」，需手动删 `work/transcript_raw.json` 与 `work/asr_task.json` 后重跑，GL-16 引入音频指纹后可自动识别。
  - **GL-17**：`atomic_output` 的「清理陈旧临时文件」在同一目标被并发生成时可能删掉另一个任务的临时文件 → 那个任务以 `MediaError` 失败而非产出坏文件（失败安全）；任务互斥由 GL-17 解决。
- **为什么删掉 aicut 的 `_validate_draft` 而不是修它**：它在安装**之后**校验（来不及阻止交付），且用自己写死的 `DRAFT_ROOT`（不认 `AI_CUT_DRAFT_ROOT`、不认剪映自定义目录），在自定义目录下会校验错地方。校验移进 `to_jianying.install()` 后只有一处真源。
- **为什么完成标记 + 原子改名两样都要**：原子改名保证最终路径上永远不是半成品；`.done` 标记让「旧版本留下的半成品」（没有标记）也被识别为未完成，并让「决定重做时」先作废旧结果。
- 本计划生成时仅只读执行了：`validate_draft` 跑两个现有草稿、在 scratchpad 里复现 `SegmentOverlap` 与验证双文本轨方案、只读查看剪映 `globalSetting`。

## 需用户决策
- **D1（产品）片尾字幕卡超出成片时长怎么处理**：`纪实3min` 的片尾卡 `at=170s`，成片若短于 170s：
  - A. 跳过并 `[warn]`（本计划默认；与当前预览片的实际效果一致——预览里这张卡本来就不会出现）
  - B. 自动挪到成片最后 `dur` 秒显示（更贴近「片尾卡」的意图）
  改成 B 只需改 `card_entries()` 一处。
- **D2（产品，低影响）剪映里字幕卡单独一条文本轨**（轨名 `subtitle` / `card`）。这是修 GL-10 最直接的做法；若希望轨名显示中文（如「字幕」「字幕卡」）请告知，技术上无差别。
