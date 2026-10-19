# Plan: M10 测试达标（KI-38 / KI-39）

## Summary
把「覆盖率 ≥ 80%」从一句口号变成一条**可执行、会失败的门槛**：引入 `pytest-cov`，在 `pyproject.toml` 固定统计范围（`aicut.py` + `pipeline/` + `gui/` + `app/` + 随包的 `research/validate_draft.py`）与 `fail_under = 80`，让 PRD 指标命令 `uv run pytest --cov` 真能跑、跌破 80% 就红。
同时补上**素材 → 剪映草稿的端到端测试**：用 ffmpeg 现做 8 秒测试素材，云端 ASR 与 DeepSeek 只在传输层打桩，其余（ffmpeg 抽音轨 / 代理 / 切片 / 预览、三路分析、分档、选段、时间线、草稿生成、静态校验、注册、Windows 导出包）全部真跑；并把 4 个 0% 的文件补到有意义的单测、修掉 `tests/test_proc.py` 两条恒真断言。
**不改任何产品代码**：本里程碑只动测试、测试配置与文档。

## User Story
As 维护 ai-cut 的开发者（以及之后跑 M6–M9 修复的 agent），
I want 一条命令就能证明「从一段素材到剪映里能打开的草稿」整条链路还是通的，且覆盖率掉到 80% 以下会直接失败，
So that 后续每个修复都有回归网兜底，不会再出现「单测全绿、真实素材一跑就断」。

## Problem → Solution
- **现状（2026-10-19 实测，987 passed）**：仓库没有 `pytest-cov` / `coverage`（`uv run python -c "import coverage"` → ModuleNotFoundError），PRD 指标命令 `uv run pytest --cov` 跑不了，也没有任何门槛；
  用临时叠加环境（`uv run --with pytest-cov`，不改项目依赖）实测 coverage.py 7.16.2：**TOTAL 82%**（aicut.py 已纳入，69%），但
  `pipeline/format_transcript.py`、`pipeline/junk_detect.py`、`pipeline/render_preview.py`、`app/main.py` 仍是 **0%**，`pipeline/build_documentary.py` 35%。
  → 依赖 + 配置 + 门槛；为 0% 文件写行为测试（不钉住任何 open KI 的错误行为）。
- **现状**：没有任何「素材 → 剪映草稿」测试。`tests/test_to_jianying.py` 只从现成 1 秒片段 + 手写 timeline 开始；`tests/test_export_draft.py` 只用假草稿目录与假子进程；`tests/test_proc.py:20-22, 31-33` 两条断言恒真。
  → 新增 `tests/test_e2e_draft.py`（打包版同进程路径 + 开发版子进程路径 + Windows 导出包），已在 scratchpad 原型里跑通（2 passed，合计约 5 秒）；重写两条恒真断言。

## Metadata
- **Complexity**: Medium（只加测试与配置；E2E 需要协调 ffmpeg、冻结/开发两种运行方式与多处打桩）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 10「测试达标」（KI-38 KI-39）
- **Estimated Files**: 12（5 新建测试 / 7 修改：`pyproject.toml`、`uv.lock`、`.gitignore`、`tests/test_proc.py`、`tests/test_build_documentary.py`、`tests/test_packaging.py`、`CLAUDE.md`；收尾另改 `docs/known-issues.md`）

---

## 登记项现状核对（在当前代码上重新定位）

| KI | 登记时描述 | 当前代码实测 | 结论 |
|---|---|---|---|
| KI-38 | 覆盖率 51%（aicut.py 未纳入，实际约 40%）；`gui/server.py`、`to_jianying.py`、`junk_detect.py`、`format_transcript.py`、`build_documentary.py`、`render_preview.py` 为 0% | coverage.py 实测 TOTAL **82%**（含 aicut.py 69%）；`gui/server.py` 77%、`to_jianying.py` 96% **已不再是 0%**（M1–M5 补测带上来的）；`junk_detect.py` / `format_transcript.py` / `render_preview.py` 仍 **0%**（开发模式下它们只以子进程脚本运行，`aicut.py:144-157`），`build_documentary.py` 35%，另有 `app/main.py` 0%（登记时未列）。**仓库内无 pytest-cov，指标命令跑不了、无门槛** | **still-present（部分过时）**：总量数字已过时，但「无法测量 + 无门槛 + 4 个 0% 文件」仍在 |
| KI-39 | 无端到端测试（素材 → 剪映草稿）；`test_proc.py` 断言近乎恒真 | `grep` 全 `tests/`：没有任何测试从媒体文件出发走到草稿；`tests/test_proc.py` 当前第 20-22 行（`assert root.is_absolute()`）与第 31-33 行（`is None or isinstance(..., Path)`）原样存在（登记的 19-28 行号因文件增长偏移）；`tests/test_export_draft.py` 仍只用 `fake_draft` + 假 `subprocess.run` | **still-present** |

---

## UX Design

### Before
N/A — internal change（开发者视角：`uv run pytest --cov` → `error: unrecognized arguments: --cov`）

### After
N/A — internal change（开发者视角：`uv run pytest --cov` → 覆盖率表 + `Required test coverage of 80.0% reached. Total coverage: ~90%`；低于 80% 退出码非 0）

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| `uv run pytest` | 987 passed，~20 s | ≈1030 passed，~26 s | 不带 `--cov` 时行为不变，不做门槛（单文件调试不受影响） |
| `uv run pytest --cov` | 参数不认识 | 打印覆盖率并按 `fail_under=80` 判定 | PRD Success Metrics 表的测量命令 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `tests/conftest.py` | 13-60 | autouse 隔离：草稿根、凭证、日志、编码预检；`consented` fixture。E2E 依赖全部这些 |
| P0 | `aicut.py` | 144-157, 229-254, 323-337, 587-600, 609-673, 676-696, 838-849 | `_run_pipeline` 冻结/开发分支、转写、废片、预览、build、`install_draft`、`cmd_prepare`、`run_cli` |
| P0 | `pipeline/proc.py` | 24, 45-69, 81-105, 111-124 | `FROZEN`、`user_data_root`/`bundled_bin`/`ensure_bundled_path`、`run_inprocess`、`module_cmd` |
| P0 | `pipeline/to_jianying.py` | 444-469, 519-533, 656-697 | 草稿根解析、`jianying_running`（pgrep）、校验门、`main()` 与 `--staging` 默认值（写 `~/.aicut/staging`） |
| P0 | `tests/test_to_jianying.py` | 91-123, 415-461 | `clip` fixture（VideoToolbox 探测）、`jy_root` 注册表 fixture、`run_inprocess` 跑 main 的写法 |
| P1 | `pipeline/cloud.py` | 182-207, 404-429 | `CloudClient` 构造参数（`transport`/`uploader`/`sleep` 可注入）、`transcribe` 落 `transcript_raw.json` |
| P1 | `pipeline/llm.py` | 81-103 | `DeepSeekClient`；`understand_text`/`summarize`/`questions` 都是 `client or DeepSeekClient()` |
| P1 | `pipeline/understand_text.py` | 45-62, 298-336 | 话题 prompt 含「归并成」，标注 prompt 以「给下面每句话标注」开头；漏 id → `AnnotationIncomplete` |
| P1 | `pipeline/review.py` | 64-71 | `set_must(workdir, sid, True)`：E2E 用它保证某句必进片 |
| P1 | `pipeline/export_draft.py` | 80-104 | Windows 包：`proc.module_cmd` 子进程 + `--dry-run`（不查剪映是否在跑） |
| P1 | `pipeline/format_transcript.py` / `junk_detect.py` / `render_preview.py` / `build_documentary.py` | 全文 | 0% 文件；写测试前必须对照下方「不要钉住的 open KI」 |
| P2 | `app/main.py` | 全文（51 行） | 入口：dispatch 先于 `import webview`；`finally` 里 `jobs.shutdown_all()` + `srv.shutdown()` |
| P2 | `tests/test_cloud.py` | 30-75 | `FakeHttp` / `make()`：云端打桩的既有写法 |
| P2 | `tests/test_understand_text.py` | 9-41 | `_no_backoff` + `FakeClient`：LLM 打桩的既有写法 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| pytest-cov / coverage.py 配置 | coverage.py 7.x 文档「Configuration reference」 | `[tool.coverage.run] source` 可写目录或**可导入名**（`"aicut"` 这种单文件模块可用）；`source` 与 `include` 同时给时 `include` 被忽略；`[tool.coverage.report] fail_under` 由 pytest-cov 在带 `--cov` 时执行 |

```
KEY_INSIGHT: `--cov` 不带值时用 [tool.coverage.run] source；已用 uv run --with pytest-cov 在本仓实测：
             source=["aicut","app","gui","pipeline"] + source_pkgs=["research.validate_draft"] → 5306 stmts，82.38%，"Required test coverage of 80.0% reached"
APPLIES_TO: Task 1
GOTCHA: 不要把 "packaging.build_package" 放进 source_pkgs —— 仓库根 packaging/ 与 PyPI 的 packaging 同名（见 pipeline/to_jianying.py:38 注释），
        coverage 解析可导入名时可能命中三方包；该文件由 test_export_draft 间接覆盖，不纳入统计。
GOTCHA: 只有 include 而没有 source 时，从未 import 的文件不会以 0% 出现在报告里 —— 必须用 source。
GOTCHA: 子进程不计入覆盖率（未配 subprocess patch）；开发模式下 _run_pipeline / install_draft / export 都是子进程，
        这正是三个脚本 0% 的原因。E2E 的「打包版」变体把 proc.FROZEN 置 True，脚本改为同进程 run_inprocess，才会被统计。
```

---

## Patterns to Mirror

### NAMING_CONVENTION（测试文件 / 用例命名）
```python
# SOURCE: tests/test_build_documentary.py:1-5
"""pipeline/build_documentary：字幕卡（GL-10）与切片原子落盘（GL-15）。"""
from pipeline import build_documentary as bd


def test_card_entries_drops_card_starting_after_total(capsys):
```
- 文件 `tests/test_<模块>.py`，首行中文 docstring 写「模块：测什么（登记号）」；用例名英文蛇形、描述行为；分节用 `# ---------------------------------------------------------------- KI-39` 注释条。

### ERROR_HANDLING（脚本出错 = sys.exit("中文")，同进程用 run_inprocess 断言）
```python
# SOURCE: tests/test_to_jianying.py:421-431
def _run_main(tmp_path, tl_file, *extra):
    return proc.run_inprocess("pipeline.to_jianying",
                              [str(tl_file), "--name", "T", "--staging", str(tmp_path / "stg"),
                               *extra])


def test_frozen_path_reports_missing_jianying(tmp_path, monkeypatch):
    ...
    code, out = _run_main(tmp_path, tl)
    assert code == 1 and "找不到剪映草稿库" in out  # GL-12 + GL-13：conftest 指向的根不存在
```
- 三个 0% 脚本的 `main()` 一律用 `proc.run_inprocess("pipeline.xxx", argv)` 跑，断言 `(code, out)`；`sys.exit("文字")` → `code == 1` 且文字在 `out` 里（`pipeline/proc.py:70-78`）。

### LOGGING_PATTERN（CLI 输出前缀，E2E 用它断言阶段结果）
```python
# SOURCE: aicut.py:49-64
def die(msg: str) -> None:
    LOG.error(msg)
    print(f"[x] {msg}")
    sys.exit(1)

def ok(msg: str) -> None:
    print(f"[✓] {msg}")
```
- E2E 失败时把 `capsys.readouterr().out` 带进断言消息（`assert code == 0, out`），定位到哪一步 `[x]`。

### REPOSITORY_PATTERN（假 ffmpeg：写出最后一个参数路径）
```python
# SOURCE: tests/test_aicut_build.py:42-51
def fake_ffmpeg(calls, fail_on=None, interrupt=False):
    def run(args, **kw):
        calls.append(args)
        out = Path(args[-1])
        out.write_bytes(b"half" if interrupt else b"full")
        ...
    return run
```
- `build_documentary.main` 的单测用同样手法 `monkeypatch.setattr(media_io, "run_ffmpeg", run)`（`tests/test_build_documentary.py:20-33` 已有先例）。

### SERVICE_PATTERN（外部服务只在传输层/构造处打桩）
```python
# SOURCE: tests/test_cloud.py:57-71
def make(routes, uploads=None, **kw):
    http = FakeHttp(routes)
    ...
    c = cloud.CloudClient(sleep=lambda _: None, transport=http.transport,
                          uploader=uploader, **kw)
```
```python
# SOURCE: tests/test_understand_text.py:9-41
@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(ut, "_sleep", lambda _s: None)

class FakeClient:
    model = "fake"
    def chat_json(self, system, user, **kw):
        ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
        if "归并成" in user:  # 话题分段
            ...
```
- E2E：`cloud.CloudClient` 换成 `functools.partial(cloud.CloudClient, transport=…, uploader=…, sleep=…)`（**不能**改默认参数——默认值在 def 时已绑定）；`understand_text` / `summarize` / `questions` 三个模块各自的 `DeepSeekClient` 名字换成返回 FakeLLM 的工厂。

### TEST_STRUCTURE（ffmpeg / VideoToolbox 可用性守卫 + 草稿根 fixture）
```python
# SOURCE: tests/test_to_jianying.py:91-99, 114-123
@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("本机无 ffmpeg")
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                              text=True).stdout
    codec = encode.h264_args("clip") if " h264_videotoolbox " in encoders \
        else ["-c:v", "mpeg4", "-pix_fmt", "yuv420p"]
...
@pytest.fixture
def jy_root(tmp_path, monkeypatch):
    root = tmp_path / "draft_root"
    root.mkdir()
    (root / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [], "draft_ids": 1, "root_path": str(root)}), encoding="utf-8")
    monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(root))
    monkeypatch.setattr(tj, "jianying_running", lambda: False)  # 开发机上剪映可能真在跑
    return root
```
- E2E 里 aicut 的代理/切片/预览**写死** `encode.h264_args`（VideoToolbox），预览还在子进程/同进程的 `render_preview` 里各自取参数，无法统一替换 → **没有 h264_videotoolbox 就 `pytest.skip`**，不要尝试打桩编码参数。

---

## Unified Discovery Table

| Category | File:Lines | Pattern | Key Snippet |
|---|---|---|---|
| 运行方式 | `aicut.py:144-157` | 冻结→`run_inprocess`，开发→子进程脚本 | `if proc.FROZEN: code, out = proc.run_inprocess(module, argv)` |
| 运行方式 | `aicut.py:657-662` | 草稿：冻结同进程；开发 `ensure_jy_python()` 子进程 | `r = subprocess.run([ensure_jy_python(), str(PIPELINE / "to_jianying.py"), *argv], …)` |
| 危险点 | `aicut.py:127-141` | 开发模式首次会建 `~/.aicut/venv` 并 **pip 联网安装** | `run([str(py), "-m", "pip", "install", "-q", "pyJianYingDraft"])` |
| 危险点 | `pipeline/to_jianying.py:667-668` | `--staging` 默认 `~/.aicut/staging`（真实 HOME） | `ap.add_argument("--staging", default=str(Path.home() / ".aicut/staging"))` |
| 危险点 | `pipeline/to_jianying.py:467-469` | 是否在跑剪映用真实 `pgrep`，只能同进程打桩 | `subprocess.run(["pgrep", "-f", "MacOS/VideoFusion-macOS"], …)` |
| 危险点 | `pipeline/proc.py:111-124` | 冻结时 `module_cmd` 产出 `sys.executable --aicut-module`：测试里 python 不认 → 导出必须在非冻结变体里测 | `return [sys.executable, MODULE_FLAG, module_name, *args]` |
| 就绪 | `pipeline/readiness.py:15-17, 20-27` | prepare 依次跑 12 步；缺 Key 一开始就停 | `PREPARE_STEPS = ("ingest", "transcribe", "analyze", "text", "junk", …)` |
| 凭证 | `pipeline/secrets.py:110-113` | `get()` 先读环境变量 `ENV_KEYS[provider]` | `env = os.environ.get(ENV_KEYS[provider])` |
| 隔离 | `tests/conftest.py:13-46` | autouse：草稿根→不存在目录、凭证→tmp 文件、日志→tmp、编码预检→通过 | `monkeypatch.setattr(encode, "_PREFLIGHT", {"result": None})` |
| 依赖 | `pyproject.toml:15-19` | dev 组只有 pytest、pyinstaller | `dev = ["pytest>=8", "pyinstaller>=6.10"]` |
| 配置 | `pyproject.toml:25-28` | pytest 配置 | `pythonpath = ["."]`、`testpaths = ["tests"]`、`addopts = "-q"` |

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pyproject.toml` | UPDATE | dev 组加 `pytest-cov`；新增 `[tool.coverage.run]` / `[tool.coverage.report]`（KI-38） |
| `uv.lock` | UPDATE | 由 `uv add --dev` 生成，不手改 |
| `.gitignore` | UPDATE | 加 `.coverage`、`.coverage.*`、`htmlcov/`（仓库卫生） |
| `tests/test_packaging.py` | UPDATE | 守卫：覆盖率门槛与统计范围写在 pyproject 里且不被调低（KI-38，先写，RED） |
| `tests/test_e2e_draft.py` | CREATE | 素材 → 剪映草稿 / Windows 包端到端（KI-39） |
| `tests/test_format_transcript.py` | CREATE | 0% → 行为测试（KI-38） |
| `tests/test_junk_detect.py` | CREATE | 0% → 行为测试 + 新缺陷钉住（KI-38 / 新登记 KI-77） |
| `tests/test_render_preview.py` | CREATE | 0% → 行为测试（KI-38） |
| `tests/test_build_documentary.py` | UPDATE | 补 `split_sub` 与 `main()`（35% → ≥80%，KI-38） |
| `tests/test_app_main.py` | CREATE | 入口 0% → 行为测试（KI-38） |
| `tests/test_proc.py` | UPDATE | 两条恒真断言改成真断言，补 `ensure_bundled_path`（KI-39） |
| `CLAUDE.md` | UPDATE | 「命令」节加覆盖率命令 |
| `docs/known-issues.md` | UPDATE（收尾单独 docs 提交） | KI-38/KI-39 → `fixed <commit>`；新增 KI-77 |

## NOT Building

- **不改任何产品代码**（`aicut.py`、`pipeline/`、`gui/`、`app/`、`research/`、`packaging/`）。写测试时发现的缺陷只登记、钉住，不修。
- 不为 open KI 的现有错误行为写「正向」断言（会让 M6–M9 的修复把本里程碑的测试打红）：
  `KI-13`（`esc` 单引号）、`KI-76`（`esc` 的 `%`）、`KI-73`（字体首选 PingFang）、`KI-14`（无音轨预览）、`KI-19`（ffmpeg 不查返回码、`duration==0` 除零：`junk_detect.py:174`）、`KI-24`（`format_transcript` 时间缺省 0 / end 回退 / `tc(59.999)`）、`KI-27`（未闭合静音冻帧、重叠重复、`--scene` 丢弃）、`KI-11`（`build_documentary` 切片缓存只看存在）。
- 不做 GUI 层（`/api/*` + 任务子进程）的端到端：KI-39 要的是「素材 → 剪映草稿」，GUI 任务本质是以子进程跑同一组 `aicut` 命令（已有 `tests/test_server_jobs.py` 覆盖任务机制）。
- 不追 `gui/server.py`（77%）的单文件覆盖率：它在 800 行软上限上，拆分是 KI-54（M9）的事；总量门槛已满足。
- 不配置子进程覆盖率（`COVERAGE_PROCESS_START` / `.pth`）：增加环境耦合，收益已由 E2E 冻结变体拿到。
- 不在默认 `uv run pytest` 上强制门槛（不改 `addopts`），只在 `--cov` 时判定。
- 不新建 CI（仓库目前没有 `.github/`；建 CI 不在 KI-38/39 范围）。
- 不把 `packaging/build_package.py`、`research/` 其他研究脚本、`docs/`、`prototype/`、`windows-spike/` 纳入统计。

---

## Step-by-Step Tasks

> 本里程碑大部分是**刻画测试**（characterization）：被测代码已存在，新测试写完通常直接绿。为证明它们不是新的「恒真断言」，每个任务的 VALIDATE 里都有一次**变异自检**：临时改坏被测代码的一行 → 确认该测试变红 → `git checkout -- <file>` 还原（只在本地，不提交）。真正的 RED 只出现在 Task 1（门槛守卫）与 Task 2（test_proc 重写前后对比）。

### Task 1: 覆盖率工具与门槛（KI-38）
- **ACTION**: 先写守卫测试（RED），再加依赖与配置（GREEN）。
- **IMPLEMENT**:
  1. `tests/test_packaging.py` 末尾新增（沿用该文件 `tomllib` + `_read` 风格）：
     ```python
     # ---------------------------------------------------------------- KI-38：覆盖率门槛
     COVERAGE_FLOOR = 80  # PRD Success Metrics：测试覆盖率 ≥ 80%


     def test_coverage_gate_is_configured():
         cfg = tomllib.loads(_read("pyproject.toml"))
         dev = cfg["dependency-groups"]["dev"]
         assert any(d.startswith("pytest-cov") for d in dev)
         cov = cfg["tool"]["coverage"]
         assert cov["report"]["fail_under"] >= COVERAGE_FLOOR
         # aicut.py 必须在统计里（KI-38：登记时它没被统计，真实覆盖率被高估）
         assert {"aicut", "pipeline", "gui", "app"} <= set(cov["run"]["source"])
         assert "research.validate_draft" in cov["run"]["source_pkgs"]
     ```
     运行 → KeyError / AssertionError（RED）。
  2. 依赖（**需用户确认，见 Notes 决策 1**）：`uv add --dev "pytest-cov>=6"`（会同时更新 `pyproject.toml` 与 `uv.lock`；实测解析到 coverage 7.16.2）。
  3. `pyproject.toml` 追加：
     ```toml
     [tool.coverage.run]
     # 产品代码：CLI、流水线、剪辑台、桌面入口，以及随包分发的草稿校验器（ai-cut.spec hiddenimports）
     source = ["aicut", "app", "gui", "pipeline"]
     source_pkgs = ["research.validate_draft"]
     # packaging/build_package.py 不列：仓库根 packaging/ 与 PyPI packaging 同名，按名解析会串

     [tool.coverage.report]
     fail_under = 80          # PRD：测试覆盖率 ≥ 80%（KI-38）
     skip_covered = true
     show_missing = true
     ```
  4. `.gitignore` 「生成物」段追加 `.coverage`、`.coverage.*`、`htmlcov/`。
- **MIRROR**: `tests/test_packaging.py:1-12`（只读仓库文本的守卫测试）。
- **IMPORTS**: `tomllib`（文件已 import）。
- **GOTCHA**: 不要把 `--cov` 写进 `addopts`（单文件调试会因总量不足被判失败）；不要用 `include` 代替 `source`（未 import 的文件不会以 0% 出现）；`uv add` 属于改依赖，执行前按用户全局规则确认。
- **VALIDATE**: `uv run pytest tests/test_packaging.py -q` 绿；`uv run pytest --cov` 末尾出现 `Required test coverage of 80.0% reached`（此时约 82%）；`git status` 不出现 `.coverage`。

### Task 2: 去掉 test_proc 的恒真断言（KI-39 第二部分）
- **ACTION**: 改写 `tests/test_proc.py:20-22` 与 `:31-33`，并补 `ensure_bundled_path`（`pipeline/proc.py:61-69` 当前未覆盖）。
- **IMPLEMENT**:
  ```python
  def test_user_data_root_dev_default_is_repo_projects(monkeypatch):
      monkeypatch.delenv("AI_CUT_PROJECTS", raising=False)
      monkeypatch.setattr(proc, "FROZEN", False)
      assert proc.user_data_root() == proc.app_root() / "projects"


  def test_user_data_root_frozen_default_is_documents(monkeypatch, tmp_path):
      monkeypatch.delenv("AI_CUT_PROJECTS", raising=False)
      monkeypatch.setattr(proc, "FROZEN", True)
      monkeypatch.setenv("HOME", str(tmp_path))
      assert proc.user_data_root() == tmp_path / "Documents" / "AI粗剪"  # 不能写进 .app


  def test_bundled_bin_none_without_ffmpeg(monkeypatch, tmp_path):
      monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))  # app_root() 指向假的 App 资源目录
      assert proc.bundled_bin() is None


  def test_bundled_bin_found_and_prepended_once(monkeypatch, tmp_path):
      monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))
      (tmp_path / "bin").mkdir()
      (tmp_path / "bin" / "ffmpeg").write_bytes(b"")
      monkeypatch.setenv("PATH", "/usr/bin")
      assert proc.bundled_bin() == tmp_path / "bin"
      proc.ensure_bundled_path()
      proc.ensure_bundled_path()  # 幂等：不重复插入
      assert os.environ["PATH"].split(os.pathsep) == [str(tmp_path / "bin"), "/usr/bin"]


  def test_ensure_bundled_path_noop_without_bin(monkeypatch, tmp_path):
      monkeypatch.setattr(proc, "MEIPASS", str(tmp_path))
      monkeypatch.setenv("PATH", "/usr/bin")
      proc.ensure_bundled_path()
      assert os.environ["PATH"] == "/usr/bin"
  ```
  删除原 `test_user_data_root_default_is_writable`、`test_bundled_bin_none_when_missing`。
- **MIRROR**: `tests/test_proc.py:15-17`（`monkeypatch.setenv` + 精确相等断言）。
- **IMPORTS**: 文件顶部加 `import os`（目前只有 `sys/textwrap/Path/pytest`）。
- **GOTCHA**: `app_root()` 每次读模块全局 `MEIPASS`（`pipeline/proc.py:35-39`），monkeypatch 模块属性即可；不要 patch `sys._MEIPASS`。`Path.home()` 在 posix 读 `HOME` 环境变量。
- **VALIDATE**: `uv run pytest tests/test_proc.py -q` 绿；变异自检：把 `proc.py:52` 的 `"AI粗剪"` 临时改成别的 → `test_user_data_root_frozen_default_is_documents` 必须红（原恒真断言改不红）。

### Task 3: 端到端 —— 素材 → 剪映草稿 / Windows 包（KI-39 主体）
- **ACTION**: 新建 `tests/test_e2e_draft.py`。代码已在 scratchpad 原型跑通（2 passed，约 5 s），照抄并按下列断言收紧。
- **IMPLEMENT**:
  ```python
  """端到端（KI-39）：一段真实编码的测试素材 → 处理素材 → 出片 → 剪映草稿 / Windows 导出包。

  只在网络边界打桩：MediaKit 走假 transport/uploader，DeepSeek 换成按 prompt 应答的假客户端。
  ffmpeg 抽音轨 / 代理 / 切片 / 预览、三路分析、分档、选段、时间线、草稿生成、静态校验、注册全部真跑。
  草稿根、HOME、项目目录、凭证、日志全部在 tmp_path 下。
  """
  import functools
  import json
  import re
  import shutil
  import subprocess
  import zipfile

  import pytest

  import aicut
  from pipeline import (cloud, export_draft, media_io, proc, questions, review, secrets,
                        summarize, understand_text)
  from pipeline import to_jianying as tj
  from pipeline.llm import LLMError
  from research import validate_draft

  NAME = "e2e"
  MUST_SID, MUST_TEXT = "S002", "九千八"   # 剪辑师标★的那句：必须出现在交付的草稿里
  # 同一说话人、句间停顿 1.4s > 1.2s（format_transcript.GAP_SAME_SPEAKER）→ 切成 3 段 S001–S003
  SUBS = [("大家好，今天来看合同。", 0.2, 1.6), ("学费一共九千八。", 3.0, 4.4),
          ("可以分两期缴费。", 5.8, 7.6)]
  MATERIAL_SECONDS = 8


  def _has_videotoolbox() -> bool:
      if shutil.which("ffmpeg") is None:
          return False
      out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                           text=True).stdout
      return " h264_videotoolbox " in out


  pytestmark = pytest.mark.skipif(not _has_videotoolbox(),
                                  reason="需要带 h264_videotoolbox 的 ffmpeg（产品只用 VideoToolbox 编码）")


  class FakeLLM:
      model = "fake-e2e"

      def __init__(self):
          self.calls = 0

      def chat_json(self, system, user, **kw):
          self.calls += 1
          ids = re.findall(r"^(S\d{3}) ", user, flags=re.M)
          if "归并成" in user:                       # understand_text.TOPIC_USER
              return {"topics": [{"name": "讲解合同", "segment_ids": ids}]}
          if user.startswith("给下面每句话标注"):    # understand_text.ANNOTATE_USER
              return {"segments": [{"id": i, "info_type": "金额价格", "key_info": True,
                                    "entities": [MUST_TEXT], "reason": "含金额"} for i in ids]}
          raise LLMError("e2e：摘要 / 决策问题走兜底")   # summarize / questions 任何异常都兜底


  class FakeMediaKit:
      """上传 → 提交 → 轮询一次即完成；记录调用以证明没有真实请求。"""

      def __init__(self):
          self.paths = []

      def transport(self, method, url, headers, body, timeout):
          path = url[len(cloud.DEFAULT_ENDPOINT):]
          self.paths.append((method, path))
          if path == cloud.UPLOAD_PATH:
              return 200, json.dumps({"success": True, "result": {
                  "file_id": "mediakit://F1", "method": "PUT",
                  "upload_url": "https://tos.example.com/o"}})
          if path == cloud.SUBMIT_PATH:
              return 200, json.dumps({"success": True, "task_id": "t1"})
          return 200, json.dumps({"task_id": "t1", "status": "completed", "result": {
              "duration": float(MATERIAL_SECONDS),
              "subtitles": [{"subtitle_text": t, "start_time": s, "end_time": e, "speaker": "1"}
                            for t, s, e in SUBS]}})

      def upload(self, method, url, headers, path, timeout):
          return 200, ""


  @pytest.fixture
  def material(tmp_path):
      out = tmp_path / "素材" / "现场.mp4"   # 中文路径：真实用户素材就是这样
      out.parent.mkdir()
      subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                      "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={MATERIAL_SECONDS}",
                      "-f", "lavfi", "-i", f"sine=frequency=440:duration={MATERIAL_SECONDS}",
                      "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(out)], check=True)
      return out


  @pytest.fixture
  def jy_root(tmp_path, monkeypatch):
      root = tmp_path / "jy_root"
      root.mkdir()
      (root / tj.ROOT_META_NAME).write_text(json.dumps(
          {"all_draft_store": [], "draft_ids": 1, "root_path": str(root)}), encoding="utf-8")
      monkeypatch.setenv("AI_CUT_DRAFT_ROOT", str(root))
      return root


  @pytest.fixture
  def world(tmp_path, monkeypatch, consented, jy_root):
      """除网络外一切真实；返回打桩对象供断言。"""
      monkeypatch.setenv("HOME", str(tmp_path / "home"))  # to_jianying --staging 默认 ~/.aicut/staging
      monkeypatch.setenv(secrets.ENV_KEYS["mediakit"], "AK-e2e")
      monkeypatch.setenv(secrets.ENV_KEYS["deepseek"], "sk-e2e")
      monkeypatch.setattr(aicut, "PROJECTS", tmp_path / "projects")
      monkeypatch.setattr(understand_text, "_sleep", lambda _s: None)
      llm, mk = FakeLLM(), FakeMediaKit()
      for mod in (understand_text, summarize, questions):
          monkeypatch.setattr(mod, "DeepSeekClient", lambda *a, **k: llm)
      monkeypatch.setattr(cloud, "CloudClient", functools.partial(
          cloud.CloudClient, sleep=lambda _s: None, transport=mk.transport, uploader=mk.upload))
      return {"llm": llm, "mediakit": mk, "pdir": tmp_path / "projects" / NAME, "root": jy_root}


  def _prepare(material, world, capsys):
      assert aicut.run_cli(["new", NAME, "--material", str(material),
                            "--target", "30", "--no-input"]) == 0, capsys.readouterr().out
      review.set_must(world["pdir"] / "work", MUST_SID, True)   # 剪辑师先标★（浏览素材）
      assert aicut.run_cli(["prepare", NAME]) == 0, capsys.readouterr().out
      assert world["mediakit"].paths and world["llm"].calls      # 确实走的是桩，不是网络


  def test_material_to_installed_jianying_draft(material, world, monkeypatch, tmp_path, capsys):
      """打包版路径（proc.FROZEN）：流水线脚本与 to_jianying 同进程运行。"""
      monkeypatch.setattr(proc, "FROZEN", True)
      monkeypatch.setattr(tj, "jianying_running", lambda: False)  # 开发机上剪映可能开着
      _prepare(material, world, capsys)

      assert aicut.run_cli(["build", NAME]) == 0, capsys.readouterr().out

      pdir, root = world["pdir"], world["root"]
      tl = json.loads((pdir / "output/v1/timeline.json").read_text(encoding="utf-8"))
      assert media_io.is_complete(pdir / "output/v1/preview.mp4")
      assert all(media_io.is_complete(v["source"]) for v in tl["video"])
      entries = json.loads((root / tj.ROOT_META_NAME).read_text(encoding="utf-8"))["all_draft_store"]
      assert [e["draft_name"] for e in entries] == [f"{NAME}_v1"]
      draft = root / f"{NAME}_v1"
      assert entries[0]["draft_fold_path"] == str(draft)
      res = validate_draft.check(str(draft), expect=tj.expected(tl))
      assert res["fails"] == [], res["fails"]
      assert MUST_TEXT in (draft / "draft_content.json").read_text(encoding="utf-8")  # 必留进片
      assert not (tmp_path / "home/.aicut/staging" / f"{NAME}_v1").exists()  # 安装成功后暂存不保留


  def test_material_to_windows_package_dev_mode(material, world, monkeypatch, tmp_path, capsys):
      """开发版路径：流水线脚本以子进程运行；Windows 包走 module_cmd 子进程 + --dry-run。"""
      monkeypatch.setattr(proc, "FROZEN", False)
      _prepare(material, world, capsys)

      # --no-draft：开发模式装草稿会调 ensure_jy_python()，首次要建 ~/.aicut/venv 并联网 pip
      assert aicut.run_cli(["build", NAME, "--no-draft"]) == 0, capsys.readouterr().out
      assert media_io.is_complete(world["pdir"] / "output/v1/preview.mp4")

      out = tmp_path / "exports"
      assert aicut.run_cli(["export", NAME, "-o", str(out)]) == 0, capsys.readouterr().out
      pkg = out / f"{NAME}_v1.zip"
      info = export_draft.inspect_package(pkg)
      assert info["install"] and info["fix_paths"] and info["placeholder"]
      with zipfile.ZipFile(pkg) as z:
          assert MUST_TEXT in z.read(info["drafts"][0]).decode("utf-8")
      assert [p.name for p in out.iterdir()] == [pkg.name]          # 不留 .partial 残片
      assert json.loads((world["root"] / tj.ROOT_META_NAME).read_text(
          encoding="utf-8"))["all_draft_store"] == []               # 导出不碰剪映草稿库
  ```
- **MIRROR**: `tests/test_to_jianying.py:91-123`（ffmpeg 守卫、草稿根 fixture）、`tests/test_cloud.py:57-71`（云端注入）、`tests/test_understand_text.py:9-41`（LLM 假客户端）、`tests/test_aicut_build.py:35-39`（`aicut.PROJECTS` 改到 tmp）。
- **IMPORTS**: 如上；`consented` 是 `tests/conftest.py:53-58` 的 fixture。
- **GOTCHA**:
  - **冻结变体里不能测导出**：`proc.module_cmd` 在 `FROZEN=True` 时产出 `python --aicut-module …`（`pipeline/proc.py:120-121`），测试解释器不认 → 导出放在开发变体。
  - **开发变体必须 `--no-draft`**：否则 `install_draft` → `ensure_jy_python()`（`aicut.py:127-141`）会在真实 HOME 建 venv 并联网 pip；且子进程里的 `jianying_running`（真实 `pgrep`）无法打桩。
  - `HOME` 必须指到 tmp：`to_jianying` 的 `--staging` 默认值在 `main()` 调用时用 `Path.home()` 计算（`pipeline/to_jianying.py:667-668`）。
  - `cloud.CloudClient` 的默认参数在定义时绑定，monkeypatch `cloud.default_transport` 无效 → 用 `functools.partial` 替换类名（`aicut.py:247` 是 `cloud.CloudClient()`）。
  - 8 秒素材 + 30 秒目标时选段只挑部分段（原型里不标★时只选 1 镜）——**不要断言镜头数**，用★必留段 `S002` 断言「九千八」进片，这正是产品的核心承诺（FR-7）。
  - FakeLLM 标注必须覆盖 prompt 里的全部 id，否则 `AnnotationIncomplete` 让 `prepare` 退出 1。
  - 预览用 `render_preview` 自己的 `encode.h264_args`（同进程/子进程都一样）——这就是只能 skip、不能打桩编码器的原因。
  - 字幕卡来自真实预设 `presets/纪实3min.json`，会打印两条 `[warn] 字幕卡 …` 属预期（GL-10 D1 行为），不要断言没有 warn。
- **VALIDATE**: `uv run pytest tests/test_e2e_draft.py -q` → 2 passed（本机约 5 s）；变异自检：临时把 `pipeline/select.py` 的必留保证跳过（例如让 `missing_must_keep` 返回 `[]` 并在选段里丢掉 must_keep 段）或把 `review.set_must` 那行注释掉 → 「九千八」断言必须红；`uv run pytest --cov` 中 `format_transcript.py` / `render_preview.py` / `junk_detect.py` 不再是 0%。

### Task 4: `format_transcript` 行为测试（0% → ≥90%）
- **ACTION**: 新建 `tests/test_format_transcript.py`。
- **IMPLEMENT**（期望值已在当前代码上实算）：
  - `load_subs` 三种输入形状：`[...]`、`{"subtitles": [...], "duration": 9}`、`{"result": {"subtitles": [...], "duration": 9}}` → 同样的 `subs`（按 start 排序、`subtitle_text`/`text` 二选一、空文本被丢弃），duration 分别为 0.0 / 9 / 9。
  - `is_noise`：`"嗯。"` → True；`"嗯，对"` → False；`"啊啊啊"` → False（3 个字，超过 2）。
  - `build_segments`：
    ```python
    subs = [{"start": 0.0, "end": 1.0, "text": "你好", "speaker": "1"},
            {"start": 1.5, "end": 2.5, "text": "今天看合同", "speaker": "1"},
            {"start": 4.0, "end": 5.0, "text": "学费九千八", "speaker": "1"},   # 同人停顿 1.5 > 1.2 → 断
            {"start": 5.2, "end": 6.0, "text": "能退吗", "speaker": "2"},       # 换人停顿 0.2 < 2.5 → 同段
            {"start": 9.0, "end": 10.0, "text": "不能", "speaker": "1"}]        # 换人停顿 3.0 > 2.5 → 断
    # 期望：[("S001", 0.0, 2.5, "你好今天看合同"), ("S002", 4.0, 6.0, "学费九千八能退吗"), ("S003", 9.0, 10.0, "不能")]
    ```
    另加一条：同一说话人连续多句、跨度超过 `MAX_SEG`(35s) → 断段；检查 `duration`、`chars`（去空白计数）。
  - `main()` 经 `proc.run_inprocess("pipeline.format_transcript", [raw, "-o", out])`：退出码 0；`segments.json` 的 `count` 与段数一致、语气词行被过滤；`transcript.md` 首行含「段」「句」；字幕全空 → 退出码 1 且输出含「没有解析到字幕」。
  - `tc(75.5) == "01:15.50"`（**不要**测 59.999 —— KI-24）。
- **MIRROR**: `tests/test_to_jianying.py:421-431`（`run_inprocess` 跑 main）。
- **IMPORTS**: `json`、`from pipeline import format_transcript as ft, proc`。
- **GOTCHA**: 不测「时间字段缺失默认 0」「包含句使 end 回退」（KI-24，M8 会改）。
- **VALIDATE**: 单文件绿；变异自检：`GAP_SAME_SPEAKER` 改成 2.0 → `build_segments` 用例红。

### Task 5: `junk_detect` 行为测试 + 钉住新缺陷（0% → ≥85%）
- **ACTION**: 新建 `tests/test_junk_detect.py`。
- **IMPLEMENT**:
  - `ts(3725.5) == "01:02:05.500"`；`merge([(0,1,"black"),(1.2,2,"black"),(5,6,"black")]) == [(0,2,"black"),(5,6,"black")]`（间隔 ≤0.3 合并）。
  - `detect` 解析：`monkeypatch.setattr(jd.subprocess, "run", lambda cmd, **kw: SimpleNamespace(stderr=LOG, returncode=0))`，其中
    ```python
    LOG = """  Duration: 00:01:40.00, start: 0
    [blackdetect @ 0x1] black_start:10 black_end:11 black_duration:1
    [freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 20
    [silencedetect @ 0x3] silence_start: 20
    [freezedetect @ 0x2] lavfi.freezedetect.freeze_end: 25
    [silencedetect @ 0x3] silence_end: 25 | silence_duration: 5
    """
    # 期望：([(10.0, 11.0, "black"), (20.0, 25.0, "freeze"), (20.0, 25.0, "silence")], 100.0)
    ```
    同时断言命令里带 `blackdetect`、`freezedetect`、`silencedetect`，`scene=True` 时带 `scdet`。
  - `judge`：黑场 1s → `score 0.95 / suggest "删"`；`silence < 3s`、`freeze < 2s` 被跳过；单独静音 4s → `0.55 / "参考"`；冻帧与静音重叠 → 冻帧条目 `0.7 / "待定"`、原因含「同期静音」；`coverage_pct` = 长度/总长×100。
  - `main()`：`monkeypatch.setattr(jd, "detect", lambda *a: ([(10.0, 11.0, "black")], 100.0))` 后经 `run_inprocess` 跑 → 退出码 0，`junk_report.json` 的 `items` 1 条、`junk_report.csv` 表头为 `start_tc,end_tc,duration,type,reason,score,suggest`（utf-8-sig 读）；媒体不存在 → 退出码 1 且输出含「找不到媒体」（这一步不需要打桩 detect）。
  - **新缺陷钉住（KI-77，见 Notes）**：
    ```python
    @pytest.mark.xfail(strict=True, reason="KI-77：冻帧+静音重叠的强废片信号分支对冻帧/静音条目永远不成立")
    def test_freeze_with_silence_is_strong_junk_signal():
        rows = jd.judge([(20.0, 25.0, "freeze"), (20.0, 25.0, "silence")], 100.0, -35.0)
        assert any(r["score"] == 0.97 and r["suggest"] == "删" for r in rows)
    ```
- **MIRROR**: `tests/test_export_draft.py:93-101`（patch 模块内 `subprocess.run`）。
- **IMPORTS**: `csv`、`json`、`from types import SimpleNamespace`、`from pipeline import junk_detect as jd, proc`。
- **GOTCHA**: 不测 `duration == 0`（`junk_detect.py:174` 除零，KI-19）、未闭合区间、重叠区间重复出行、`--scene` 结果被丢（KI-27）——这些是 M8 要改的行为。`detect` 的 `subprocess.run` 打桩仅限本测试（monkeypatch 自动还原）。
- **VALIDATE**: 单文件绿（xfail 记为 xfailed）；变异自检：把 `judge` 里黑场 `score = 0.95` 改 0.5 → 黑场用例红。

### Task 6: `render_preview` 行为测试（0% → ≥90%）
- **ACTION**: 新建 `tests/test_render_preview.py`。
- **IMPLEMENT**:
  - `build(tl)`：两段视频（`timeline_in` 乱序：`b.mp4` 在 0、`a.mp4` 在 2）→ 返回 `n == 2`；按 `timeline_in` 排序后 `[0:v]trim=start=1:duration=2` 属于 `b.mp4`；concat 必须交替：图里含 `"[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac]"`；两条文字 → 两个 `drawtext`，`align 2` → `y=h*0.74`、`align 5` → `y=h*0.42`；`size 6.5` → `fontsize=58`；`color [1,0,0]` → `fontcolor=0xFF0000`；`enable='between(t,0,1)'`；最后一段以 `format=yuv420p[vout]` 结尾。
  - `esc`：只测反斜杠与冒号：`esc("a:b\\c") == "a\\:b\\\\c"`（**不测单引号、`%`**：KI-13 / KI-76）。
  - `pick_font`：`monkeypatch.setattr(rp, "FONT_CANDIDATES", [str(missing), str(present)])` → 返回 present；全不存在 → `SystemExit`，消息「找不到可用中文字体」（**不测具体系统字体**：KI-73）。
  - `main()`：`monkeypatch.setattr(rp.subprocess, "run", fake)` 记录 cmd → 经 `run_inprocess` 跑；断言每段 `-i <source>` 按 `timeline_in` 顺序、`-map [vout] -map [ac]`、包含 `encode.h264_args("preview")` 子序列、`-movflags +faststart`、末项为 `-o` 给的路径；输出含「渲染 2 个镜头」。
- **MIRROR**: `tests/test_encode.py`（断言命令行含 `encode.h264_args(...)`）；`tests/test_to_jianying.py:421-431`。
- **IMPORTS**: `json`、`from pipeline import encode, proc, render_preview as rp`。
- **GOTCHA**: `pick_font()` 在 `build` 内被调用 —— `build` 的用例先 monkeypatch `FONT_CANDIDATES` 指向 tmp 下一个存在的假文件，避免依赖本机字体（KI-73 会改字体策略）。真实渲染已由 Task 3 覆盖。
- **VALIDATE**: 单文件绿；变异自检：把 interleaved 改回「先列完视频标签」→ concat 用例红。

### Task 7: `build_documentary` 补 `split_sub` 与 `main()`（35% → ≥85%）
- **ACTION**: `tests/test_build_documentary.py` 末尾追加。
- **IMPLEMENT**:
  - `split_sub("你好，世界。今天天气很好，我们去看合同吧！", max_chars=8)`：每张 ≤8 字、拼接后等于原文；无标点超长 `"一"*20`（max 14）→ `["一"*14, "一"*6]`；空串 → `[""]`。
  - `main()`：`fake = fake_ffmpeg` 风格写 `args[-1]`，`monkeypatch.setattr(media_io, "run_ffmpeg", run)`；写 `shots.json`：`{"project": "P", "source": <tmp 下存在的文件>, "shots": [{"id": "S01", "in": 0, "out": 3, "sub": "你好，世界。"}, {"id": "S02", "in": 5, "out": 7, "sub": ""}], "cards": [{"at": 0, "dur": 1, "text": "片头"}]}` → `run_inprocess("pipeline.build_documentary", [shots, "-o", out])` 退出码 0；`timeline.json` 两段视频 `timeline_in` 为 0 / 3、`role` 为 speech / broll；字幕卡 + 片头卡都在 `text`；`分镜表.md` 含「镜头数：2」；切片 `clips/S01.mp4` `is_complete`。
  - 原片不存在 → 退出码 1，输出含「原片不存在」；`run_ffmpeg` 抛 `MediaError` → 退出码 1，输出含「切镜头 S01 失败」。
- **MIRROR**: `tests/test_build_documentary.py:20-33`。
- **IMPORTS**: `json`、`from pipeline import media_io, proc`。
- **GOTCHA**: 不测「切片已存在就复用」（KI-11）。
- **VALIDATE**: 单文件绿；变异自检：`role` 的 `broll/speech` 判断取反 → 红。

### Task 8: `app/main.py` 入口测试（0% → ≥90%）
- **ACTION**: 新建 `tests/test_app_main.py`（已在 scratchpad 原型跑通，3 passed）。
- **IMPLEMENT**:
  ```python
  """app/main：桌面入口先分发子任务、再起窗口；窗口关掉（含异常）一定停任务、关服务（KI-38）。"""
  import runpy
  import sys
  import types

  import pytest

  from pipeline import proc

  MAIN = proc.app_root() / "app" / "main.py"


  class FakeWindow:
      def create_file_dialog(self, kind, **kw):
          return ("/v/a.mov",)


  def fake_webview(start_exc=None):
      wv = types.ModuleType("webview")
      wv.OPEN_DIALOG, wv.calls = 10, []

      def create_window(title, url, **kw):
          wv.calls.append(("create", title, url))
          return FakeWindow()

      def start():
          wv.calls.append(("start",))
          if start_exc:
              raise start_exc

      wv.create_window, wv.start = create_window, start
      return wv


  @pytest.fixture
  def entry(monkeypatch):
      monkeypatch.setattr(sys, "path", list(sys.path))  # main.py 开发模式会 sys.path.insert
      monkeypatch.setattr(sys, "argv", ["app"])


  @pytest.mark.parametrize("start_exc", [None, RuntimeError("cocoa")])
  def test_main_wires_window_and_always_cleans_up(entry, monkeypatch, start_exc):
      from gui import jobs, server
      wv = fake_webview(start_exc)
      monkeypatch.setitem(sys.modules, "webview", wv)
      seen = []
      srv = types.SimpleNamespace(shutdown=lambda: seen.append("srv.shutdown"))
      monkeypatch.setattr(server, "serve_in_background", lambda: (srv, "http://127.0.0.1:9/"))
      monkeypatch.setattr(server, "set_picker", lambda fn: seen.append(("picker", fn())))
      monkeypatch.setattr(server, "report_stale_job", lambda: seen.append("stale"))
      monkeypatch.setattr(jobs, "shutdown_all", lambda *a, **k: seen.append("jobs.shutdown"))
      ns = runpy.run_path(str(MAIN), run_name="app_main_under_test")
      if start_exc:
          with pytest.raises(RuntimeError):
              ns["main"]()
      else:
          ns["main"]()
      assert wv.calls[0] == ("create", "AI 粗剪", "http://127.0.0.1:9/")
      assert ("picker", ["/v/a.mov"]) in seen and "stale" in seen
      assert seen[-2:] == ["jobs.shutdown", "srv.shutdown"]  # 关窗口 = 停任务，不留孤儿进程


  def test_task_flag_exits_before_importing_webview(entry, monkeypatch):
      monkeypatch.setitem(sys.modules, "webview", None)  # 一旦 import webview 就 ImportError
      monkeypatch.setattr(sys, "argv", ["app", "--aicut-cli", "list"])
      monkeypatch.setattr(proc, "dispatch", lambda argv: 7)
      with pytest.raises(SystemExit) as exc:
          runpy.run_path(str(MAIN), run_name="app_main_under_test")
      assert exc.value.code == 7
  ```
- **MIRROR**: `tests/test_proc.py`（`test_app_entry_dispatches_before_webview_import` 目前只做源码文本检查，本任务补行为验证，保留原用例）。
- **IMPORTS**: 如上。
- **GOTCHA**: `run_name` 不能是 `"__main__"`（否则直接执行 `main()`）；`applog.setup("app")` 会装 handler 与 excepthook，由 conftest `_isolate_logs` 收尾还原；用 `runpy.run_path` 而不是 `import app.main`（`app/` 没有 `__init__.py`）。
- **VALIDATE**: 单文件绿；变异自检：删掉 `app/main.py` 的 `finally` 块中 `jobs.shutdown_all()` → 第二个参数化用例红。

### Task 9: 全量验证与收尾文档
- **ACTION**: 跑全量与覆盖率；更新 `CLAUDE.md`；收尾单独 docs 提交登记册。
- **IMPLEMENT**:
  - `CLAUDE.md`「命令」节，在「测试」行后加：`- 覆盖率：\`uv run pytest --cov\`（门槛 80%，配置在 pyproject 的 [tool.coverage]）`。
  - `docs/known-issues.md`：KI-38、KI-39 状态 `open` → `fixed <commit>`；在「2026-10-19 实施中新发现」表追加
    `| KI-77 | 废片检测「无语音 + 画面静止」强信号（0.97/删）只对黑场条目可达：冻帧/静音条目的 overlapping 永远不含自身类型，冻帧+静音重叠只给 0.7/待定 与 0.55/参考 | \`pipeline/junk_detect.py:113-128\`（\`judge\`）；钉住：\`tests/test_junk_detect.py::test_freeze_with_silence_is_strong_junk_signal\`（xfail strict） | open |`
  - PRD 里程碑 10 状态与 plan 链接由主流程更新（本计划步骤不改 PRD）。
- **VALIDATE**: 见 Validation Commands。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_coverage_gate_is_configured` | `pyproject.toml` | 含 pytest-cov、`fail_under ≥ 80`、source 含 aicut/app/gui/pipeline | 否 |
| `test_user_data_root_frozen_default_is_documents` | FROZEN=True，HOME=tmp | `tmp/Documents/AI粗剪` | 是（打包路径） |
| `test_bundled_bin_found_and_prepended_once` | 假 `_MEIPASS/bin/ffmpeg` | PATH 只插入一次 | 是（幂等） |
| `test_material_to_installed_jianying_draft` | 8 s 测试素材、★S002 | 草稿注册、校验 0 FAIL、含「九千八」、预览完整 | 是（中文路径） |
| `test_material_to_windows_package_dev_mode` | 同上，开发模式 | zip 含 INSTALL.bat/fix_paths.ps1/占位符/「九千八」，不碰草稿库 | 是（子进程路径） |
| `build_segments` 断段 | 同人停顿 1.5 / 换人 0.2 / 换人 3.0 | S001–S003 | 是（三种断段规则） |
| `load_subs` 三形状 | list / 顶层 / result 嵌套 | 同样的 subs | 是 |
| `format_transcript.main` 空字幕 | 全空文本 | 退出 1「没有解析到字幕」 | 是 |
| `junk_detect.detect` | 预制 stderr | 3 个区间 + 100 s | 否 |
| `junk_detect.judge` | 黑场/短静音/短冻帧/重叠 | 0.95 删 / 跳过 / 跳过 / 0.7 待定 | 是（阈值） |
| `junk_detect.main` 缺媒体 | 不存在路径 | 退出 1「找不到媒体」 | 是 |
| KI-77 pin | 冻帧+静音重叠 | xfail(strict) | 是 |
| `render_preview.build` | 乱序两段 + 两条文字 | 交替 concat、y 位置、字号、颜色 | 是（乱序） |
| `render_preview.pick_font` | 全不存在 | SystemExit「找不到可用中文字体」 | 是 |
| `render_preview.main` | 假 subprocess | 命令行含 preview 编码参数与 faststart | 否 |
| `build_documentary.main` | 2 镜 + 片头卡 | timeline/分镜表/切片完成标记 | 是（无字幕镜头） |
| `build_documentary.main` 失败 | 原片缺失 / ffmpeg 失败 | 退出 1 + 中文原因 | 是 |
| `app.main` | 假 webview，start 抛错 | 仍 `jobs.shutdown_all` + `srv.shutdown` | 是 |
| `app.main` 任务标记 | `--aicut-cli` | 不 import webview，退出码透传 | 是 |

### Edge Cases Checklist
- [x] Empty input（空字幕、无字幕镜头、空 split_sub）
- [ ] Maximum size input（不做：长素材性能不在 KI-38/39 范围）
- [x] Invalid types / 缺失文件（原片 / 媒体不存在）
- [x] Concurrent access —— N/A（E2E 串行；GUI 并发已有 `test_server_jobs.py`）
- [x] Network failure —— N/A（网络全打桩；失败路径已有 `test_cloud.py` / `test_llm.py`）
- [x] Permission / 环境：无 ffmpeg 或无 VideoToolbox → E2E skip；剪映在跑 → 同进程打桩；真实 HOME / 草稿库不被触碰

---

## Validation Commands

### Static Analysis
```bash
# 本仓未配置 lint / typecheck（CLAUDE.md「Lint / 类型检查：未配置」）
uv run python -m compileall -q tests
```
EXPECT: 无输出

### Unit Tests
```bash
uv run pytest tests/test_packaging.py tests/test_proc.py tests/test_format_transcript.py \
  tests/test_junk_detect.py tests/test_render_preview.py tests/test_build_documentary.py \
  tests/test_app_main.py tests/test_e2e_draft.py
```
EXPECT: 全绿（1 xfailed：KI-77）

### Full Test Suite + Coverage Gate
```bash
uv run pytest            # 基线 987 passed → 约 1030 passed, 1 xfailed
uv run pytest --cov      # Required test coverage of 80.0% reached；预计 TOTAL ≈ 90%
```
EXPECT: 无回归；四个原 0% 文件均 ≥ 85%，`build_documentary.py` ≥ 85%，`aicut.py` ≥ 80%；`git status` 不出现 `.coverage`

### Database Validation
N/A

### Browser Validation
N/A

### Manual Validation
- [ ] `uv run pytest --cov` 输出里能看到 `aicut.py` 与 `research/validate_draft.py` 两行（证明统计范围正确）
- [ ] 临时把 `fail_under` 改成 99 → `uv run pytest --cov` 退出码非 0（门槛真的会失败）→ 改回
- [ ] 跑完 E2E 后 `ls ~/.aicut/staging ~/Movies/JianyingPro` 时间戳无变化（没碰真实目录）
- [ ] 各任务的变异自检均已做过并还原（`git diff -- aicut.py pipeline app` 为空）

---

## Acceptance Criteria
- [ ] `uv run pytest --cov` 可运行，`fail_under = 80` 生效，TOTAL ≥ 80%（预计 ≈ 90%）
- [ ] KI-38 列出的文件与 `app/main.py` 都不再是 0%
- [ ] 存在素材 → 已安装剪映草稿（冻结路径）与素材 → Windows 导出包（开发路径）两条 E2E，并断言必留内容进片
- [ ] `tests/test_proc.py` 不再有恒真断言
- [ ] 产品代码零改动；新发现缺陷已登记 KI-77 并以 strict xfail 钉住
- [ ] 全量测试无回归

## Completion Checklist
- [ ] 测试文件命名、首行 docstring、分节注释与现有 tests 一致
- [ ] 所有外部依赖（网络、剪映、HOME、钥匙串）在测试里都被隔离
- [ ] 没有为 open KI（11/13/14/19/24/27/73/76）的错误行为写正向断言
- [ ] 无硬编码绝对路径（全部 tmp_path / `proc.app_root()`）
- [ ] CLAUDE.md 与 known-issues 已同步
- [ ] 无范围外改动

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| E2E 在没有 VideoToolbox 的机器上 skip，覆盖率下降 | 中（Linux CI / 虚拟机） | 中 | 0% 文件另有不依赖 ffmpeg 的单测；实测不含 E2E 时总量也 ≥ 82%，门槛取 80 留余量（见决策 2） |
| E2E 变慢 / 偶发（硬件编码会话被占） | 低 | 中 | 素材 320×180×8 s，本机约 5 s；`encode.h264_args` 已带 `-allow_sw 1` 软件回退 |
| M6–M9 修复改变选段 / 字幕卡行为导致 E2E 红 | 中 | 低 | E2E 只断言产品承诺（必留进片、草稿注册且 0 FAIL、包结构），不断言镜头数、字幕卡、warn 文案 |
| 预设 `纪实3min` 被改名 | 低 | 中 | `new` 默认预设即此名（`aicut.py:856`）；若改名，E2E 与 CLI 默认值一起改 |
| coverage 按名解析 `research.validate_draft` 失败 | 低 | 低 | 已在本仓用 coverage 7.16.2 实测通过 |

## Notes

### 需用户决策
1. **引入 `pytest-cov`（改依赖）**：按全局规则改依赖需确认。推荐默认：`uv add --dev "pytest-cov>=6"`（只进 dev 组，不进 App 包；`ai-cut.spec` 不受影响）。不同意的话 KI-38 无法按 PRD 的 `uv run pytest --cov` 验收。
2. **门槛数值**：推荐默认 `fail_under = 80`（PRD 字面目标）。可选「棘轮」到 85（完成后预计 ≈ 90%），但无 VideoToolbox 的机器上 E2E 会 skip、总量回落约 4–5 个点，85 有误报风险。实施按 80 执行，除非你改。

### 设计取舍（工程决定，不需确认）
- 门槛只在 `--cov` 时判定，不进 `addopts`：单文件调试不受影响，PRD 指标命令就是验收命令。
- E2E 分「冻结同进程」与「开发子进程」两条：前者覆盖打包 App 真实运行方式并把三个脚本纳入统计；后者覆盖开发者日常 `uv run python aicut.py` 与 Windows 导出（冻结变体里 `module_cmd` 无法在测试解释器中自启）。
- 网络只在最外层打桩（MediaKit transport/uploader、DeepSeek 客户端），不 mock aicut 的任何步骤函数，保证「端到端」名副其实。
- 摘要与决策问题走兜底（FakeLLM 对它们抛 `LLMError`）：两者的正常路径已有 `test_summarize.py` / `test_questions.py`，E2E 只需证明兜底不阻断出片。

### 新发现缺陷（按约定登记 + 钉住，不修）
- **KI-77**（建议编号，接 KI-76；其他里程碑并行登记时取登记当下的下一个空号，并同步改 Task 5 的 xfail reason 与 Task 9 的登记行）：`pipeline/junk_detect.py:114-128` `judge()` 里 `overlapping` 排除了自身类型，于是 `"freeze" in overlapping and "silence" in overlapping` 对冻帧条目（缺 freeze）和静音条目（缺 silence）永远为假；文档化的强信号「无语音 + 画面静止 0.97/删」只在黑场条目上可达。实测：冻帧与静音完全重叠 → 冻帧 0.7「待定」、静音 0.55「参考」。影响：废片表与策划分派单里本该「建议删」的段只给参考。可与 KI-27（同函数）在 M8 一起修。钉住方式见 Task 5（`xfail(strict=True)`，修好后会 XPASS→失败，提醒去掉标记）。

### 其他观察
- KI-38 登记的 `gui/server.py`、`to_jianying.py` 「0%」已过时（77% / 96%）；总量已 82%，本里程碑的实质工作是「可测量 + 门槛 + 补 0% 文件 + E2E」。
- 基线测量方法：`uv run --with pytest-cov pytest --cov=… `（临时叠加环境，未改 `pyproject.toml` / `uv.lock`；数据文件写在 scratchpad）。原型 E2E 叠加后 TOTAL 88%。
- `build_documentary.main()` 与 `aicut.compose_timeline` 存在重复的字幕拆分/时间线逻辑（DRY 问题），不在本里程碑范围，不登记为缺陷（行为正确）。
