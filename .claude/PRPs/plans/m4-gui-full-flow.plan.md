# Plan: M4 · GUI 独立完成全流程

## Summary
让剪辑师不碰命令行就能走完「填 Key（含外发告知）→ 处理素材 → 生成成片（Mac 草稿）→ 导出 Windows 剪映包」，任务全局互斥、可取消、失败可关闭可重试。
核心手段：所有任务（含打包版）统一改为**子进程执行**（打包版自启 `ai-cut --aicut-cli …`），从根上消除冻结模式的 `redirect_stdout` / `sys.argv` 多线程互踩，并让取消变得可实现；ASR 断点状态改为绑定音频指纹、终态失败自动清除。
本里程碑覆盖 GL-02 / GL-14 / GL-16 / GL-17 / GL-20 / GL-22。

## User Story
作为不懂命令行的剪辑师，我想在剪辑台窗口里配置 Key、处理素材、导出 Mac 和 Windows 两种剪映工程，并在出错时能关掉弹窗、重试或取消，这样我能独立交付成片，不必找开发者。

## Problem → Solution
- GUI 无 Key 入口、无外发告知；没 DeepSeek Key 时 prepare 静默跳过 b 路 → GUI「设置」+ 首次使用告知；prepare 缺 Key 直接失败并指向设置页（GL-02）
- GUI 只能出 Mac 草稿 → 版本卡片上「导出 Windows 剪映包」，复用 `aicut export`（GL-14）
- `asr_task.json` 失败后不清、不绑定音频 → 新 `pipeline/asr_state.py`：schema 版本 + backend + 音频 sha256，终态失败清除（GL-16）
- 任务可并发、不可取消、冻结模式线程互踩、未知任务留幽灵 → 子进程统一执行 + 全局互斥 + 进程组取消 + 先校验后登记（GL-17）
- GUI 新建项目卡在 `input()`、留空目录 → `new --no-input` + 子进程 `stdin=DEVNULL` + 空目录可复用/失败清理（GL-20）
- 字幕框点不进、失败模态关不掉 → 选中行不重绘、任务弹窗常驻「取消 / 关闭 / 重试」（GL-22）

## Metadata
- **Complexity**: Large
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 4 · GUI 独立完成全流程（GL-02 GL-14 GL-16 GL-17 GL-20 GL-22）
- **Estimated Files**: 19（改 10 + 新建 9，含测试）

### 前置依赖（必须先合入）
- **M1**（GL-05/06/07/18/21/23）会改 `gui/server.py` 与 `gui/static/index.html`：加请求 token 校验、Host/Origin 校验、Content-Type 校验、项目名/版本号校验 helper、`_read_body` 坏 JSON 报错、`escapeHtml` 全覆盖、原子保存。**本计划所有新端点都假设 M1 已提供：**
  1. 请求 token 校验（统一在 `do_GET`/`do_POST` 入口，新端点自动受保护，不需单独处理）；
  2. 项目名校验 helper（下文写作 `require_project(name) -> Path`，实际以 M1 的命名为准；若 M1 只是加强了现有 `project_path()`，就用它）；
  3. 版本号校验 helper（下文写作 `require_version(v) -> str`，`^v\d{1,4}$`）；**若 M1 没有提供，就在 server.py 里加 `VERSION_RE = re.compile(r"^v\d{1,4}$")` 并在 Task 9 里补测试**；
  4. 前端 `api()` 自动带 token 头。新加的 fetch **一律走 `api()`**，不要裸 `fetch`。
- **M3**（GL-11/12/13/15）：取消任务（SIGTERM 杀进程组）依赖 GL-15「中断后不复用半成品」才是安全的。若 M3 尚未合入，取消后可能留下半成品——见 Risks。
- 行号均为 2026-10-19 `ae7f417` 的位置；M1/M3 合入后会偏移，**按函数名/文本锚点定位，不要按行号硬改**。

---

## UX Design

### Before
```
┌ 侧栏 ───────┐┌ 主区 ─────────────────────────────────────────┐
│ ＋新建项目   ││ ①处理素材  ②生成成片  浏览  偏好  文件夹  剪映   │
│ 项目列表     ││ [版本] v3  预览片  剪映草稿名：片名_v3          │
│             ││   （没有 Windows 导出）                         │
│ （无设置）   ││ 分镜表：点字幕框 → 整表重绘 → 光标丢失           │
└─────────────┘└────────────────────────────────────────────────┘
任务弹窗：只有日志；失败后没有任何按钮，遮罩关不掉 → 只能杀 App
新建项目（.command 启动）：转圈不返回（子进程卡在 input()）
没 Key：prepare 跑到转写才报错；没 DeepSeek Key 时静默跳过文本分析
```

### After
```
首次打开 ──► ┌ 使用前请知悉：哪些数据会发到云端 ─────────────┐
             │ · 原片和画面不会离开这台电脑                    │
             │ · 音轨（16kHz 单声道）→ 火山引擎语音识别（转写）│
             │ · 转写出的文字 → DeepSeek（理解内容、找重点）    │
             │ · API Key 只存本机钥匙串，不写进日志和项目文件  │
             │            [暂不使用]  [我知道了，继续]         │
             └─────────────────────────────────────────────────┘
                      │ 继续 → 若缺 Key 自动打开「设置」
┌ 侧栏 ───────┐      ▼
│ ＋新建项目   │  ┌ 设置 · API Key ─────────────────────────────┐
│ 项目列表     │  │ 语音转写（火山引擎）  已配置 AKLT****9f2a [清除]│
│ …           │  │   [••••••••••••] [保存]                       │
│ ⚙ 设置      │  │ 文本分析（DeepSeek）   未配置                  │
└─────────────┘  │   [••••••••••••] [保存]                       │
                 │ Key 只保存在本机钥匙串。  [查看数据外发说明]   │
                 └──────────────────────────────────────────────┘
[版本] v3  预览片  剪映草稿名：片名_v3
       [导出 Windows 剪映包]   已导出 片名_v3_Windows.zip（412 MB）[在访达中显示]

任务弹窗：
  运行中：日志 + [取消任务]
  失败/已取消：日志 + [重试] [关闭]
  已有任务在跑（409）：提示「XX 项目正在处理素材」+ [查看进度] [关闭]
分镜表：点字幕框直接能输入；选中行只切高亮，不重绘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 首次打开 | 无 | 外发告知弹窗，确认后写 `~/.config/ai-cut/consent.json` | 未确认时「处理素材」被服务端 409 拦截 |
| 侧栏 | 只有新建项目 | 底部「⚙ 设置」 | 打开 Key 配置 |
| Key 配置 | 只能 CLI `config set` | GUI 输入（password 框），只回显掩码 | 来源为 env 时只读提示 |
| ① 处理素材 | 缺 Key 跑一半才失败 / 静默跳过 b 路 | 起任务前服务端检查告知+Key，缺什么弹什么 | aicut prepare 同样前置检查 |
| 版本卡片 | 只有预览 + Mac 草稿名 | +「导出 Windows 剪映包」+ 已导出状态 + 在访达中显示 | 复用 `aicut export` |
| 任务弹窗 | 失败后无按钮 | 运行中「取消任务」，结束后「重试 / 关闭」 | 409 时可查看正在跑的任务 |
| 同时点两个任务 | 都跑（重复计费、互相覆盖） | 第二个 409「已有任务在运行」 | 全局一次一个（需用户决策 #3） |
| 分镜表点字幕框 | 整表重绘，光标丢失 | 只切 `.sel` 高亮 | |
| 新建项目 | `.command` 启动时卡死 | 秒回；失败可直接重试同名 | |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `gui/server.py` | 42-70, 214-295, 299-331, 464-471, 488-559, 608-622 | 任务执行/路由/请求体，几乎所有改动在这里 |
| P0 | `pipeline/proc.py` | 1-75 | FROZEN 判定、`run_inprocess`；新增自启子进程 helper |
| P0 | `pipeline/cloud.py` | 28-30, 120-184 | ASR 续跑状态，GL-16 |
| P0 | `aicut.py` | 151-179, 375-393, 588-598, 610-622, 725-748 | new / export / prepare / run_cli / 参数定义 |
| P0 | `gui/static/index.html` | 107-150, 162-167, 340-409, 423-484, 538-542 | 侧栏、`api()`、分镜表、版本卡片、任务弹窗 |
| P1 | `pipeline/secrets.py` | 1-60, 77-172 | Key 存取、掩码、`status()`，`set` 遮蔽内置名 |
| P1 | `pipeline/export_draft.py` | 55-75 | Windows 包生成：冻结模式下 `sys.executable` 子进程会拉起 App 自身 |
| P1 | `app/main.py` | 1-42 | 自启子进程的分发必须在 `import webview` 之前 |
| P1 | `pipeline/to_jianying.py` | 30-32, 285-305 | `DRAFT_ROOT` 在 import 时读环境变量 |
| P2 | `tests/test_cloud.py` | 1-120 | FakeProc / runner 注入模式 |
| P2 | `tests/test_secrets.py` | 15-23 | 隔离钥匙串的 fixture（测试绝不能碰真钥匙串） |
| P2 | `docs/GUI.md` | 49-95 | 接口一览、「GUI 不实现业务逻辑」原则、要同步更新 |
| P2 | `docs/PRD-AI粗剪工具.md` | §7 隐私行、§13 | 告知文案的事实依据 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| PyInstaller 自启子进程 | https://pyinstaller.org/en/stable/runtime-information.html ；https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html （multiprocessing 一节） | 冻结后 `sys.executable` 是 bootloader 本身；multiprocessing 就是靠「带特殊参数重启自己」实现的，同理可用自定义参数分发 |
| subprocess 进程组 | https://docs.python.org/3.12/library/subprocess.html#subprocess.Popen （`start_new_session`）；`os.killpg` | `start_new_session=True` 让子进程自成进程组，`os.killpg(pid, SIGTERM)` 能连带杀掉它拉起的 ffmpeg |
| http.server 测试 | https://docs.python.org/3.12/library/http.server.html | `ThreadingHTTPServer(("127.0.0.1", 0), Handler)` 绑随机端口，`server_address[1]` 取端口 |

```
KEY_INSIGHT: 冻结 App 的 sys.executable 可以带参数重启自己，只要入口在 import webview 之前分发
APPLIES_TO: Task 1（proc.cli_cmd / module_cmd / dispatch）、Task 2、Task 3
GOTCHA: 窗口化（console=False）构建的子进程 stdout 可能是块缓冲或为 None；dispatch 里必须 reconfigure/兜底，否则 GUI 看不到实时日志
```
```
KEY_INSIGHT: pipeline/to_jianying.py 的 DRAFT_ROOT 在 import 时从环境变量计算
APPLIES_TO: Task 2（Windows 导出在冻结模式下）
GOTCHA: 不能在已 import 过 to_jianying 的进程里用 run_inprocess + 改 os.environ 来切换草稿根；必须起新进程
```

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: gui/server.py:42, 88, 95, 215
def run_aicut(args: list[str]) -> tuple[int, str]:
def project_path(name: str) -> Path:
def safe_name(name: str) -> str:
def start_job(name: str, task: str, extra: list[str] | None = None) -> str:
```
```python
# SOURCE: pipeline/secrets.py:19-24  —— 模块级常量大写，元组/字典
SERVICE = "ai-cut"
PROVIDERS = ("mediakit", "deepseek")
ENV_KEYS = {
    "mediakit": "MEDIAKIT_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
```
- 文件头 `# -*- coding: utf-8 -*-` + 中文模块 docstring（`pipeline/proc.py:1-6`、`pipeline/secrets.py:1-11`）；`from __future__ import annotations`。
- CLI 子命令 `cmd_<name>(args)`；私有 helper 前缀 `_`。

### ERROR_HANDLING
```python
# SOURCE: gui/server.py:555-559 —— 业务异常 → 400 JSON {"error": 中文}
            try:
                job_id = start_job(name, task, extra)
            except (ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"job_id": job_id})
```
```python
# SOURCE: aicut.py:48-50 —— CLI 失败统一 die() → 打印 [x] 并 sys.exit(1)
def die(msg: str) -> None:
    print(f"[x] {msg}")
    sys.exit(1)
```
```python
# SOURCE: pipeline/cloud.py:28-29 —— 领域异常继承 RuntimeError
class CloudError(RuntimeError):
    """云端调用的终态失败。"""
```

### LOGGING_PATTERN
仓库没有 `logging`（GL-19 属 M5）。任务日志是内存里的行列表，前缀约定：
```python
# SOURCE: gui/server.py:285-292
        except Exception as e:  # noqa: BLE001
            code = -1
            with JOBS_LOCK:
                JOBS[job_id]["log"].append(f"[错误] {e}")
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "done" if code == 0 else "failed"
            JOBS[job_id]["exit"] = code
            JOBS[job_id]["log"].append(f"[退出码] {code}")
```
CLI 输出：`[·]` info / `[✓]` ok / `[x]` die（`aicut.py:48-58`）。新增日志行沿用 `[错误]` `[取消]` `[退出码]`。**任何日志/响应都不得含 Key 明文，只用 `secrets.mask()`。**

### REPOSITORY_PATTERN（文件即存储，原子写）
```python
# SOURCE: pipeline/secrets.py:67-74
def _write_file(data: dict) -> None:
    path = _cred_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, stat.S_IRWXU)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)
```
> 固定 `.tmp` 名并发不安全（GL-18 的教训）。新文件写入用 M1 提供的原子写 helper；若 M1 的 helper 不在可 import 的位置，用 `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` + `os.replace`。

### SERVICE_PATTERN（依赖可注入，便于测试）
```python
# SOURCE: pipeline/cloud.py:36-56
class CloudClient:
    def __init__(self, cli: str = "mediakit-cli", *, retries: int = 3,
                 backoff: tuple[float, ...] = (1.0, 3.0, 9.0), sleep=time.sleep,
                 timeout_submit: float = 30.0, timeout_poll: float = 20.0,
                 runner=subprocess.run, env: dict | None = None) -> None:
```
新代码同样把「会 fork 进程 / 读时钟」的点做成可替换的模块级函数（如 `server.job_command`），测试 monkeypatch。

### TEST_STRUCTURE
```python
# SOURCE: tests/test_secrets.py:15-23 —— 隔离钥匙串与真实 Key
@pytest.fixture
def file_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CUT_SECRETS", "file")
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "cfg"))
    for var in secrets.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(secrets, "LEGACY_FILES", {}, raising=False)
    return tmp_path / "cfg"
```
```python
# SOURCE: tests/test_cloud.py:10-31 —— 假进程 + 注入 runner
class FakeProc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err

def client(sequence, **kw):
    runner, calls = make_runner(sequence)
    c = cloud.CloudClient(env={}, runner=runner, sleep=lambda _: None, **kw)
    return c, calls
```
- 测试文件 `tests/test_<module>.py`，函数式 `def test_<行为>()`，`tmp_path` + `monkeypatch`，中文断言消息可选；`pyproject.toml` 已设 `pythonpath = ["."]`，可直接 `from gui import server`、`import aicut`。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `tests/conftest.py` | CREATE（若 M1 已建则 UPDATE） | GUI 服务测试 harness：随机端口起服务、隔离项目目录与钥匙串、带 M1 token |
| `pipeline/proc.py` | UPDATE | `cli_cmd` / `module_cmd` / `dispatch`：冻结版自启子进程（GL-17、GL-14） |
| `app/main.py` | UPDATE | 在 `import webview` 前调用 `proc.dispatch` |
| `pipeline/export_draft.py` | UPDATE | 草稿生成子进程改用 `proc.module_cmd`，冻结版不再拉起 GUI（GL-14） |
| `gui/server.py` | UPDATE | 任务执行重写（互斥/取消/先校验）、`/api/new` 子进程化、Key/告知端点、export 任务、版本 Windows 状态 |
| `aicut.py` | UPDATE | `new --no-input` + 空目录复用/失败清理（GL-20）；prepare 前置 Key 检查、不再静默跳过 b 路（GL-02） |
| `pipeline/asr_state.py` | CREATE | ASR 续跑状态：schema 版本 + backend + 音频指纹 + 清除（GL-16，独立于 mediakit-cli，GL-01 换 HTTP 后照用） |
| `pipeline/cloud.py` | UPDATE | 用 `asr_state`；`CloudError.retryable`；终态失败清状态 |
| `pipeline/consent.py` | CREATE | 首次使用外发告知的确认记录（存配置目录，不进项目文件） |
| `pipeline/secrets.py` | UPDATE | 公开 `config_dir()`；`PROVIDER_LABELS` 供界面渲染 |
| `gui/static/index.html` | UPDATE | 设置/告知弹窗、版本卡 Windows 导出、任务弹窗按钮、分镜表选中不重绘 |
| `tests/test_proc.py` | UPDATE | cli_cmd / module_cmd / dispatch |
| `tests/test_export_draft.py` | UPDATE | 冻结模式命令构造 |
| `tests/test_server_jobs.py` | CREATE | 互斥、取消、未知任务无幽灵、stdin DEVNULL、冻结命令 |
| `tests/test_server_config.py` | CREATE | Key 配置、告知、prepare 前置拦截、Key 不外泄 |
| `tests/test_server_export.py` | CREATE | export 任务参数、版本校验、版本 Windows 状态 |
| `tests/test_asr_state.py` | CREATE | 指纹/backend/过期/清除 |
| `tests/test_cloud.py` | UPDATE | transcribe 失败清状态、超时保留、换音频重提 |
| `tests/test_aicut_cli.py` | CREATE | `new --no-input`、空目录重试、失败清理；prepare 缺 Key 前置失败 |
| `tests/test_consent.py` | CREATE | accept / accepted / 版本变化 |
| `docs/GUI.md` | UPDATE | 接口一览、「一次只跑一个任务」改为实情、部署段落去掉 `~/.mediakit/api_key` 指引 |
| `docs/go-live-blockers.md` | UPDATE | 关闭 GL-02/14/16/17/20/22 时填提交号 |

## NOT Building

- 不做 GL-01（mediakit-cli → HTTP 直连）；只保证 `asr_state` 与 Key 设置页在换实现后不用重写（backend 字段 + 数据驱动的 provider 列表）。
- 不做 KI-33（退出 App 时停后台任务、磁盘预检）。本里程碑的 `cancel_job` 让它以后一行可接，但这次**不接**。
- 不做 KI-35（前端切项目竞态、出片前 flush 防抖保存）、KI-36（`window.open` 在 pywebview 无效）。
- 不做 KI-28/29（密钥文件权限、`failed.json` 脱敏）。
- 不做任务排队（第二个任务直接 409，不入队）、不做任务历史持久化（重启 App 任务记录丢失可接受）。
- 不加前端 JS 测试框架（仓库没有；不扩范围）。前端改动靠浏览器验证清单。
- 不改 Windows 包内部结构 / 草稿名规则（`export_draft._api_name` 照旧）。
- 不做写端点（shots/calibrate/level）在任务运行期间的加锁。

---

## Step-by-Step Tasks

> 每个 Task 都按 **RED（先写测试并看它失败）→ GREEN → 全量 `uv run pytest`** 走。commit 粒度建议「一个 GL 一次提交」，提交信息 `fix(gui): … (GL-xx)`。

### Task 0: GUI 服务测试 harness
- **ACTION**: 新建 `tests/conftest.py`（若 M1 已建了 server fixture，就在它上面补下面缺的部分，不要建第二套）。
- **IMPLEMENT**:
```python
# tests/conftest.py
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """项目目录、钥匙串、告知记录全部指向 tmp；绝不碰本机真实 Key。"""
    from pipeline import secrets
    monkeypatch.setenv("AI_CUT_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("AI_CUT_SECRETS", "file")
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "cfg"))
    for var in secrets.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(secrets, "LEGACY_FILES", {}, raising=False)
    (tmp_path / "projects").mkdir()
    return tmp_path


@pytest.fixture
def gui(isolated_env, monkeypatch):
    """随机端口起剪辑台服务；返回 call(method, path, body=None) -> (status, json)。"""
    from gui import server
    monkeypatch.setattr(server, "PROJECTS", isolated_env / "projects")
    with server.JOBS_LOCK:
        server.JOBS.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        # M1：按 M1 实际实现加 token 头，例如：
        # req.add_header(server.TOKEN_HEADER, server.TOKEN)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    call.server = server
    call.projects = isolated_env / "projects"
    yield call
    srv.shutdown()
    srv.server_close()


def make_project(projects, name="p1", title="测试片"):
    """最小可用项目：project.json + 一个带 timeline 的版本目录。"""
    pdir = projects / name
    (pdir / "output/v1").mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps(
        {"name": name, "title": title, "material": "/tmp/x.mp4", "preset": "纪实3min",
         "platform": "douyin", "target_duration": 180}, ensure_ascii=False), encoding="utf-8")
    (pdir / "output/v1/timeline.json").write_text(json.dumps({"video": []}), encoding="utf-8")
    return pdir
```
- **MIRROR**: TEST_STRUCTURE（`tests/test_secrets.py:15-23` 的隔离方式）。
- **IMPORTS**: 标准库 only。
- **GOTCHA**:
  - `gui/server.py:35` 在 **import 时**算 `PROJECTS`，所以必须 `monkeypatch.setattr(server, "PROJECTS", …)`，光设环境变量不够；`AI_CUT_PROJECTS` 仍要设，因为子进程（aicut）靠它。
  - M1 的 Host 校验：urllib 自动发 `Host: 127.0.0.1:<port>`，应能通过；若 M1 白名单写死 8765 端口，需让它接受实际监听端口（在 M1 里修，不在这里绕）。
  - `make_project` 放 conftest 里供各测试 `from tests.conftest import make_project`？——`tests/` 无 `__init__.py`，改为把它做成 fixture `project_factory` 更稳：`@pytest.fixture def project_factory(gui): return lambda **kw: make_project(gui.projects, **kw)`。
- **VALIDATE**: 写一个冒烟测试 `GET /api/projects` → `200 {"projects": []}`，`uv run pytest tests/test_server_jobs.py -k smoke`。

### Task 1: 自启子进程基础设施（GL-17 根因、GL-14 冻结导出前置）
- **ACTION**: `pipeline/proc.py` 新增 `cli_cmd` / `module_cmd` / `dispatch`；`app/main.py` 在 `import webview` 之前分发。
- **IMPLEMENT**:
```python
# pipeline/proc.py（追加；需 import runpy）
CLI_FLAG = "--aicut-cli"        # 冻结 App 自启：跑 aicut 子命令
MODULE_FLAG = "--aicut-module"  # 冻结 App 自启：以 __main__ 跑某个 pipeline 模块


def cli_cmd(args: list[str]) -> list[str]:
    """一条 aicut 命令的子进程 argv：开发=解释器+aicut.py，打包=App 自身+标记。"""
    if FROZEN:
        return [sys.executable, CLI_FLAG, *args]
    return [sys.executable, str(app_root() / "aicut.py"), *args]


def module_cmd(module_name: str, args: list[str]) -> list[str]:
    if FROZEN:
        return [sys.executable, MODULE_FLAG, module_name, *args]
    script = app_root().joinpath(*module_name.split(".")).with_suffix(".py")
    return [sys.executable, str(script), *args]


def _line_buffered_stdio() -> None:
    """窗口化构建下 stdout 可能是块缓冲或 None；GUI 要逐行看日志。"""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(fd, "w", encoding="utf-8", buffering=1, closefd=False))
        else:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def dispatch(argv: list[str]) -> int | None:
    """App 入口最先调用：带标记就当子任务跑完并返回退出码，否则返回 None 继续开窗口。"""
    if len(argv) < 2 or argv[1] not in (CLI_FLAG, MODULE_FLAG):
        return None
    _line_buffered_stdio()
    ensure_bundled_path()
    if argv[1] == CLI_FLAG:
        from aicut import run_cli
        return run_cli(argv[2:])
    module_name, rest = argv[2], argv[3:]
    sys.argv = [module_name, *rest]
    try:
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        if exc.code is None or isinstance(exc.code, int):
            return exc.code or 0
        print(exc.code, file=sys.stderr)   # sys.exit("文字")：文字不能丢（GL-12 同类）
        return 1
    return 0
```
```python
# app/main.py：把 12-18 行改成先分发再 import webview
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import proc  # noqa: E402

if (_code := proc.dispatch(sys.argv)) is not None:
    sys.exit(_code)

import webview  # noqa: E402
from gui import server  # noqa: E402
```
- **MIRROR**: `pipeline/proc.py:58-75` 的风格（docstring 中文、FROZEN 分支）。
- **IMPORTS**: `import runpy`（proc.py）。
- **GOTCHA**:
  - `aicut.run_cli` 的 `int(exc.code)` 遇字符串会抛（GL-12，M3 修）；`dispatch` 只透传 `run_cli` 的返回值，不重复修。
  - `sys.exit(str)` 的文字原本由解释器退出时打印；`dispatch` 捕获了 SystemExit，所以必须像上面那样自己打印再返回 1（已写入代码）。
  - 冻结子进程里 `aicut._run_pipeline` 仍用 `run_inprocess`——子进程单线程，安全，不要改。
  - 不能在 `dispatch` 之前 import `webview` 或 `gui.server`（后者 import 时会 `proc.ensure_bundled_path()`，无害，但 webview 会初始化 Cocoa → 出现第二个 Dock 图标）。
- **VALIDATE**（tests/test_proc.py 追加，先 RED）:
  - `test_cli_cmd_dev_uses_aicut_py`：`cmd[1].endswith("aicut.py")`。
  - `test_cli_cmd_frozen_relaunches_self`：`monkeypatch.setattr(proc, "FROZEN", True)` → `cmd[:2] == [sys.executable, "--aicut-cli"]`。
  - `test_module_cmd_frozen_and_dev`：dev → `…/pipeline/to_jianying.py`；frozen → `[exe, "--aicut-module", "pipeline.to_jianying", …]`。
  - `test_dispatch_returns_none_without_flag`。
  - `test_dispatch_runs_module_and_returns_exit_code`：在 `tmp_path` 写 `fake_mod.py`（`import sys; sys.exit(3)`），`monkeypatch.syspath_prepend(tmp_path)`，`dispatch(["x", "--aicut-module", "fake_mod"]) == 3`。
  - 打包验证见 Validation「Build」。

### Task 2: Windows 导出在冻结模式下可用（GL-14 前置）
- **ACTION**: `pipeline/export_draft.py:63-67` 改用 `proc.module_cmd`。
- **IMPLEMENT**:
```python
from pipeline import proc  # noqa: E402  （放在 packaging import 之后）

        cmd = proc.module_cmd("pipeline.to_jianying", [
            str(timeline), "--name", _api_name(name),
            "--staging", str(tmp_root / "staging"), "--dry-run"])
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=env, stdin=subprocess.DEVNULL)
```
（局部变量 `proc` 与模块 `proc` 重名——**把原来的局部变量 `proc` 改名为 `result`**。）
- **MIRROR**: SERVICE_PATTERN；保持 `RuntimeError(f"生成草稿失败：…")` 原样。
- **IMPORTS**: `from pipeline import proc`。
- **GOTCHA**: `AI_CUT_DRAFT_ROOT` 经 `env` 传给**新进程**才生效（`to_jianying.py:30` import 时读取），这正是不能用 `run_inprocess` 的原因。
- **VALIDATE**（tests/test_export_draft.py 追加）：`test_build_uses_module_cmd_when_frozen`：建一个空 timeline 文件，`monkeypatch.setattr(proc, "FROZEN", True)`，`monkeypatch.setattr(ex.subprocess, "run", fake)` 记录 argv 并返回 `returncode=1` 的假对象 → `pytest.raises(RuntimeError)`，断言 `argv[1:3] == ["--aicut-module", "pipeline.to_jianying"]` 且 `kwargs["env"]["AI_CUT_DRAFT_ROOT"]` 在 tmp 下。

### Task 3: 任务执行重写——互斥 / 取消 / 先校验后登记（GL-17）
- **ACTION**: 替换 `gui/server.py:214-295` 的 `start_job`（删除整个 `_JobLog` / `worker_frozen` 冻结分支），新增 `cancel_job`、`active_job`、`job_command`；路由加取消；`/api/state` 带当前任务。
- **IMPLEMENT**:
```python
# gui/server.py（模块级；新增 import contextlib, signal）
JOB_TASKS = ("prepare", "build", "export")
TASK_LABELS = {"prepare": "处理素材", "build": "生成成片", "export": "导出 Windows 剪映包"}
MAX_ACTIVE_JOBS = 1        # 重任务全局串行：ffmpeg/ASR 吃满资源，也避免重复计费
CANCEL_GRACE_S = 5.0       # SIGTERM 后等这么久仍未退出就 SIGKILL


class JobConflict(Exception):
    def __init__(self, job_id: str, project: str, task: str) -> None:
        super().__init__(f"已有任务在运行：{project} · {TASK_LABELS.get(task, task)}")
        self.job_id = job_id


def job_command(task: str, name: str, extra: list[str]) -> list[str]:
    """测试替换点：真实环境下就是一条 aicut 子命令。"""
    return proc.cli_cmd([task, name, *extra])


def _running_jobs_locked() -> list[str]:
    return [jid for jid, j in JOBS.items() if j["status"] == "running"]


def active_job(project: str | None = None) -> str | None:
    with JOBS_LOCK:
        for jid in _running_jobs_locked():
            if project is None or JOBS[jid]["project"] == project:
                return jid
    return None


def start_job(name: str, task: str, extra: list[str] | None = None) -> str:
    if task not in JOB_TASKS:
        raise ValueError("未知任务")          # 先校验：不再留下幽灵 running
    require_project(name)                       # M1 helper；非法名 → ValueError
    cmd = job_command(task, name, extra or [])
    with JOBS_LOCK:
        running = _running_jobs_locked()
        if len(running) >= MAX_ACTIVE_JOBS:
            busy = JOBS[running[0]]
            raise JobConflict(running[0], busy["project"], busy["task"])
        job_id = uuid.uuid4().hex[:8]
        JOBS[job_id] = {"status": "running", "log": [], "exit": None, "started": time.time(),
                        "task": task, "project": name, "popen": None, "cancel": False}
    threading.Thread(target=_run_job, args=(job_id, cmd), daemon=True).start()
    return job_id


def _child_env() -> dict:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if not proc.FROZEN:  # 打包版必须优先用内置 ffmpeg，不能把 brew 的插到前面
        env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    return env


def _run_job(job_id: str, cmd: list[str]) -> None:
    try:
        child = subprocess.Popen(
            cmd, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, env=_child_env(), start_new_session=True)
    except OSError as exc:
        return _finish_job(job_id, -1, f"[错误] 无法启动任务：{exc}")
    with JOBS_LOCK:
        JOBS[job_id]["popen"] = child
        cancel_now = JOBS[job_id]["cancel"]
    if cancel_now:
        _terminate(child)
    for line in child.stdout:
        with JOBS_LOCK:
            JOBS[job_id]["log"].append(line.rstrip())
    _finish_job(job_id, child.wait())


def _finish_job(job_id: str, code: int, note: str | None = None) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        if note:
            job["log"].append(note)
        job["status"] = "cancelled" if job["cancel"] else ("done" if code == 0 else "failed")
        job["exit"] = code
        job["popen"] = None
        job["log"].append(f"[退出码] {code}")


def _terminate(child: subprocess.Popen) -> None:
    """杀整个进程组（含它拉起的 ffmpeg），宽限期后补 SIGKILL。"""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(child.pid, signal.SIGTERM)

    def _force() -> None:
        if child.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)

    threading.Timer(CANCEL_GRACE_S, _force).start()


def cancel_job(job_id: str) -> bool:
    """返回 True=已发出取消；False=任务已结束。未知 id 抛 KeyError。"""
    with JOBS_LOCK:
        job = JOBS[job_id]
        if job["status"] != "running":
            return False
        job["cancel"] = True
        job["log"].append("[取消] 正在停止任务…")
        child = job["popen"]
    if child is not None:
        _terminate(child)
    return True
```
路由：
```python
# do_POST：/api/job 的 except 改为
            except JobConflict as e:
                return self._json({"error": str(e), "job_id": e.job_id}, 409)
            except (ValueError, FileNotFoundError) as e:
                return self._json({"error": str(e)}, 400)

# do_POST 新增
        if p.startswith("/api/job/") and p.endswith("/cancel"):
            job_id = p[len("/api/job/"):-len("/cancel")]
            try:
                return self._json({"ok": cancel_job(job_id)})
            except KeyError:
                return self._json({"error": "job not found"}, 404)

# do_GET /api/job/<id>：返回字段加 "project"（仍然显式挑字段，绝不能把 popen 序列化）
# project_state()：返回 dict 加 "job": active_job(name)
```
- **MIRROR**: ERROR_HANDLING（400/404 JSON）、LOGGING_PATTERN（`[错误]` `[退出码]`）、SERVICE_PATTERN（`job_command` 可替换）。
- **IMPORTS**: `contextlib`, `signal`（server.py 顶部）。
- **GOTCHA**:
  - 现有代码在 `JOBS[...]` 登记**之后**才 `raise ValueError("未知任务")`（`server.py:216-225`）——这就是幽灵 running 的来源，新代码顺序不能反。
  - `start_new_session=True` 是 `os.killpg(child.pid, …)` 能工作的前提（子进程 pgid == pid）。
  - `/api/job/<id>` GET 现在用 `p.startswith("/api/job/")` + `rsplit` 取 id，取消路由是 POST，不会冲突；但 GET 的 id 必须过滤（M1 若加了 id 校验就沿用；否则 `re.fullmatch(r"[0-9a-f]{8}", job_id)`）。
  - 取消后 `asr_task.json` 必须保留（下次续查不重复计费）——Task 5 的「仅终态失败才清」保证这点。
  - `run_aicut()`（`server.py:42-60`）的冻结分支也有同样的 `redirect_stdout` 互踩问题，在 Task 4 一并改掉。
  - `docs/GUI.md:89` 写着「同时点两个会排队」——实际是 409 拒绝，Task 13 改文档。
- **VALIDATE**（`tests/test_server_jobs.py`，先 RED）：
  - `test_unknown_task_rejected_without_ghost_job`：POST `/api/job` `{project:"p1", task:"rm"}` → 400，且 `server.JOBS == {}`。
  - `test_second_job_conflicts_409`：`monkeypatch.setattr(server, "job_command", lambda *a: [sys.executable, "-c", "import time; print('go', flush=True); time.sleep(30)"])`；起第一个 → 200；第二个（同或不同项目）→ 409 且 `job_id` 等于第一个。
  - `test_cancel_kills_process_group`：fake 命令为 `[sys.executable, "-c", "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print('child', flush=True); time.sleep(60)"]`；起任务 → 轮询日志出现 `child` → POST cancel → 10s 内 GET 状态为 `cancelled`；再起一个新任务应 200（互斥已释放）。
  - `test_failed_job_status_and_exit_code`：fake `sys.exit(2)` → `failed`、`exit == 2`、日志末行 `[退出码] 2`。
  - `test_job_command_frozen_uses_self`：`monkeypatch.setattr(proc, "FROZEN", True)` → `server.job_command("prepare","p1",[])[1] == "--aicut-cli"`。
  - `test_child_stdin_is_devnull`：monkeypatch `server.subprocess.Popen` 记录 kwargs → `kwargs["stdin"] is subprocess.DEVNULL` 且 `start_new_session is True`。
  - `test_state_reports_active_job`：起长任务后 `GET /api/state?project=p1` 的 `job` 等于 job_id。

### Task 4: 新建项目不卡死、可重试（GL-20）
- **ACTION**:
  1. `aicut.py` `new` 子命令加 `--no-input`；`cmd_new` 先算好全部内容再建目录，空目录可复用，失败清理自己建的目录。
  2. `gui/server.py:42-60` `run_aicut` 删除冻结分支，统一 `subprocess.run(proc.cli_cmd(args), stdin=DEVNULL, timeout=…)`；`/api/new` 传 `--no-input`。
- **IMPLEMENT**:
```python
# aicut.py main()：new 子命令（742-748 附近）追加
    p.add_argument("--no-input", dest="no_input", action="store_true",
                   help="不交互提问（GUI 调用时使用）")

# aicut.py cmd_new（替换 151-179）
def cmd_new(args) -> None:
    pdir = PROJECTS / args.name
    if (pdir / "project.json").exists():
        die(f"项目已存在：{pdir}")
    src = Path(args.material).expanduser().resolve()
    if not src.exists():
        die(f"原片不存在：{src}")
    preset = load_json(PRESETS / f"{args.preset}.json")
    if preset is None:
        die(f"找不到预设 {args.preset}，可用：{[p.stem for p in PRESETS.glob('*.json')]}")
    given = {"tone": args.tone, "audience": args.audience, "must_lines": args.must_lines}
    given = {k: v for k, v in given.items() if v is not None}
    if given or getattr(args, "no_input", False):
        calibration = style.normalize(given)
    else:
        calibration = ask_calibration({})
    project = schema.default_project(
        args.name, str(src), title=args.title or args.name, preset=args.preset,
        platform=preset.get("platform", "douyin"), target_duration=preset.get("duration"),
        created=time.strftime("%Y-%m-%d %H:%M:%S"), calibration=calibration)
    created = not pdir.exists()
    pdir.mkdir(parents=True, exist_ok=True)   # 上次失败留下的空目录可直接复用
    try:
        schema.save(pdir / "project.json", project)
    except Exception:
        if created:
            shutil.rmtree(pdir, ignore_errors=True)
        raise
    ok(f"项目已创建：{pdir}")
    info(f"下一步：python3 aicut.py run {args.name}")
```
```python
# gui/server.py
NEW_PROJECT_TIMEOUT_S = 60


def run_aicut(args: list[str]) -> tuple[int, str]:
    """执行一条短 aicut 命令（如 new）；一律子进程，stdin 断开，绝不能等终端输入。"""
    try:
        r = subprocess.run(proc.cli_cmd(args), cwd=str(ROOT), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=NEW_PROJECT_TIMEOUT_S, env=_child_env())
    except subprocess.TimeoutExpired:
        return 1, "[错误] 创建项目超时，请重试"
    return r.returncode, (r.stdout or "") + (r.stderr or "")

# /api/new：
            code, out = run_aicut(["new", name, "--material", material, "--preset", preset,
                                   "--title", title, "--no-input"])
```
- **MIRROR**: `die()` 失败风格；`schema.save` 原子写。
- **IMPORTS**: aicut.py 已有 `shutil`；server.py 无新增。
- **GOTCHA**:
  - 原 `style.normalize({…if v is not None})` 与 `ask_calibration` 返回 `style.normalize(existing)` 行为一致——`--no-input` 下等价于「全部用默认」。
  - `ask_calibration` 自己的 `isatty()` 判断保留（CLI 交互仍可用），但 GUI 不再依赖它：.command 启动时服务器继承了终端 stdin，`isatty()` 为真才导致卡死，所以 `stdin=DEVNULL` 与 `--no-input` **两个都要**。
  - `_child_env` 在 Task 3 定义，Task 4 必须在其后实现（或先把 `_child_env` 提前）。
  - `/api/new` 返回的 `out[-500:]` 可能含绝对路径，不含 Key，可以保留。
- **VALIDATE**（`tests/test_aicut_cli.py`，先 RED）：
  - fixture：`monkeypatch.setattr(aicut, "PROJECTS", tmp_path/"projects")`，素材 `tmp_path/"m.mp4"` 写几个字节。
  - `test_new_no_input_never_prompts`：`monkeypatch.setattr(aicut, "ask_calibration", lambda *_: pytest.fail("不应提问"))`；`aicut.main(["new","p1","--material",m,"--no-input"])` → `project.json` 存在。
  - `test_new_reuses_leftover_empty_dir`：先 `mkdir projects/p1` → `new` 成功。
  - `test_new_cleans_up_dir_on_save_failure`：`monkeypatch.setattr(aicut.schema, "save", boom)` → `pytest.raises(RuntimeError)`，`projects/p1` 不存在。
  - `tests/test_server_jobs.py::test_api_new_passes_no_input_and_devnull`：monkeypatch `server.subprocess.run` 记录 argv/kwargs → `"--no-input" in argv`、`kwargs["stdin"] is subprocess.DEVNULL`、`"timeout" in kwargs`。

### Task 5: ASR 续跑状态绑定音频指纹，终态失败清除（GL-16）
- **ACTION**: 新建 `pipeline/asr_state.py`；`pipeline/cloud.py` 改用它，删除 `_task_file/_load_task/_save_task`（144-164）。
- **IMPLEMENT**:
```python
# pipeline/asr_state.py
# -*- coding: utf-8 -*-
"""ASR 断点续查状态：work/asr_task.json。

绑定 (schema 版本, backend, 音频 sha256+大小)。任一不符就作废，避免：
  * 换了音频还去查旧任务；
  * 换了转写实现（GL-01：mediakit-cli → HTTP）后拿旧 task_id 去查新服务。
只有「可重试」的失败（超时 / 网络）保留状态；终态失败一律清除，下次重新提交。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

FILENAME = "asr_task.json"
SCHEMA_VERSION = 1
MAX_AGE_S = 86400 * 3          # 云端任务结果保留期
_CHUNK = 1 << 20


def fingerprint(audio: Path) -> dict:
    h = hashlib.sha256()
    with open(audio, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "size": Path(audio).stat().st_size}


def _path(workdir: Path) -> Path:
    return Path(workdir) / FILENAME


def load(workdir: Path, audio: Path, backend: str, *, now=time.time) -> str | None:
    """返回可续查的 task_id；不匹配/过期/损坏时删除状态文件并返回 None。"""
    path = _path(workdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        clear(workdir)
        return None
    valid = (isinstance(data, dict)
             and data.get("schema") == SCHEMA_VERSION
             and data.get("backend") == backend
             and data.get("audio") == fingerprint(audio)
             and isinstance(data.get("task_id"), str) and data["task_id"]
             and now() - float(data.get("at", 0)) < MAX_AGE_S)
    if not valid:
        clear(workdir)
        return None
    return data["task_id"]


def save(workdir: Path, audio: Path, backend: str, task_id: str, *, now=time.time) -> None:
    path = _path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA_VERSION, "backend": backend, "task_id": task_id,
               "audio": fingerprint(audio), "at": now()}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".asr_task.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clear(workdir: Path) -> None:
    _path(workdir).unlink(missing_ok=True)
```
```python
# pipeline/cloud.py
from pipeline import asr_state, secrets

BACKEND = "mediakit-cli"   # GL-01 换 HTTP 后改成新值，旧状态自动作废


class CloudError(RuntimeError):
    """云端调用失败。retryable=True 表示超时/网络类，重跑可续查。"""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable

# _run() 第 82 行：
        raise CloudError(f"重试 {self.retries} 次仍失败：{last}", retryable=True)
# wait_task() 第 138-140 行超时：加 retryable=True

    def transcribe(self, audio: Path, workdir: Path, *, duration_s: float = 0.0) -> dict:
        total_timeout = max(900.0, duration_s * 3 + 600)
        task_id = asr_state.load(workdir, audio, BACKEND)
        try:
            if task_id is None:
                task_id = self.submit_asr(audio)
                asr_state.save(workdir, audio, BACKEND, task_id)
            else:
                print(f"[·] 续查上次的子任务：{task_id}")
            data = self.wait_task(task_id, total_timeout)
        except CloudError as exc:
            if not exc.retryable:
                asr_state.clear(workdir)   # 终态失败：下次重新提交，而不是 3 天内永远失败
            record_failure(workdir, "asr", str(exc), {"audio": str(audio)})
            raise
        raw = Path(workdir) / "transcript_raw.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        asr_state.clear(workdir)           # 结果已落盘，任务用完即弃
        return data
```
- **MIRROR**: REPOSITORY_PATTERN（原子写，但用唯一临时名）、ERROR_HANDLING（CloudError）。
- **IMPORTS**: `from pipeline import asr_state, secrets`。
- **GOTCHA**:
  - **旧格式状态文件**（无 `schema`）会被判无效 → 删除 → 重新提交一次（一次性计费）。可接受，写进提交说明。
  - `fingerprint` 读整段 wav（54 分钟 16k mono ≈ 100MB）约 0.1–0.3s，只在 transcribe 开头与提交后各算一次，可接受；**不要**改成 mtime（GL-15 的原子重写会改 mtime 但内容相同）。
  - `transcript_raw.json` 写入的原子性属 GL-15（M3），这里不动。
  - `submit_asr` 抛 `CloudError`（业务错，如 Key 无效）时此时还没有状态文件，`clear` 是 no-op，正确。
  - `cmd_transcribe` 里 `raw.exists()` 才跳过 ASR；Task 5 不改它。
- **VALIDATE**（先 RED）：
  - `tests/test_asr_state.py`：`save→load` 往返；改音频内容 → `None` 且文件被删；`backend` 不同 → `None`；`now` 注入超 3 天 → `None`；损坏 JSON → `None` 且删除；旧格式 `{"task_id","at"}` → `None`。
  - `tests/test_cloud.py` 追加：
    - `test_failed_task_clears_state_then_resubmits`：序列 `[submit t1, query failed]` → raises，`asr_task.json` 不存在；第二次 client `[submit t2, query completed]` → 调用里出现 `asr-subtitles`（重新提交）。
    - `test_timeout_keeps_state_for_resume`：用现有 `fake_mono` 手法让 `wait_task` 超时 → 文件仍在且 `task_id == "t1"`。
    - `test_changed_audio_resubmits`：先 save 指纹 A，再把 wav 内容改掉 → transcribe 走 submit。
    - 现有 `test_transcribe_writes_raw_and_failure_record` 需要真实存在的 `a.wav`（`fingerprint` 要读文件）——在测试里先 `write_bytes(b"RIFF")`；这是测试数据修正，不是改断言。

### Task 6: 告知记录与 Key 元数据（GL-02 后端基础）
- **ACTION**: 新建 `pipeline/consent.py`；`pipeline/secrets.py` 加公开 `config_dir()` 与 `PROVIDER_LABELS`。
- **IMPLEMENT**:
```python
# pipeline/secrets.py（PROVIDERS 下方）
# 界面按这个渲染 Key 输入框；GL-01 换实现时只改这里，界面不用动
PROVIDER_LABELS = {
    "mediakit": {"label": "语音转写（火山引擎）",
                 "hint": "用于把素材音轨转成文字"},
    "deepseek": {"label": "文本分析（DeepSeek）",
                 "hint": "用于理解转写内容、找出重要片段"},
}


def config_dir() -> Path:
    return _config_dir()
```
```python
# pipeline/consent.py
# -*- coding: utf-8 -*-
"""首次使用的「外发数据告知」确认记录（PRD §7）。

存在配置目录（与凭证同处），不进项目文件；告知内容变化时提升 CONSENT_VERSION，用户需重新确认。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from pipeline import secrets

CONSENT_VERSION = 1
FILENAME = "consent.json"


def _path():
    return secrets.config_dir() / FILENAME


def accepted() -> bool:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("version") == CONSENT_VERSION


def accept() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": CONSENT_VERSION,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".consent.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)
```
- **MIRROR**: `pipeline/secrets.py` 文件头与常量风格。
- **IMPORTS**: 如上。
- **GOTCHA**: `secrets.py` 内定义了函数 `set`（`secrets.py:112`），**在 secrets.py 里不能再用内置 `set()`**；新增代码不要用。
- **VALIDATE**（`tests/test_consent.py`，用 conftest 的 `isolated_env`）：初始 `accepted() is False`；`accept()` 后 True；手工把文件 version 改成 0 → False；文件落在 `AI_CUT_CONFIG_DIR` 下而非项目目录。

### Task 7: Key 配置与告知端点 + prepare 前置拦截（GL-02 服务端）
- **ACTION**: `gui/server.py` 新增 `/api/config` 系列；`start_job` 对 prepare 先检查告知与 Key。
- **IMPLEMENT**:
```python
# gui/server.py
from pipeline import consent, proc, review, schema, secrets, style  # noqa: E402

KEY_RE = re.compile(r"[\x21-\x7e]{8,512}")   # 可打印 ASCII、无空白


class PrepareBlocked(Exception):
    def __init__(self, need: str, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.need, self.missing = need, missing or []


def config_payload() -> dict:
    st = secrets.status()
    return {"consent": consent.accepted(),
            "providers": [{"key": k, **secrets.PROVIDER_LABELS[k], **st[k]}
                          for k in secrets.PROVIDERS]}


def check_prepare_ready() -> None:
    if not consent.accepted():
        raise PrepareBlocked("consent", "请先阅读并确认数据外发说明")
    missing = [k for k in secrets.PROVIDERS if not secrets.get(k)]
    if missing:
        names = "、".join(secrets.PROVIDER_LABELS[k]["label"] for k in missing)
        raise PrepareBlocked("keys", f"还没有填写 API Key：{names}", missing)

# start_job() 里，任务名校验之后、登记之前：
    if task == "prepare":
        check_prepare_ready()

# do_GET
        if p == "/api/config":
            return self._json(config_payload())

# do_POST
        if p == "/api/config/consent":
            consent.accept()
            return self._json(config_payload())

        if p == "/api/config/key":
            provider = body.get("provider", "")
            value = body.get("value", "")
            if provider not in secrets.PROVIDERS:
                return self._json({"error": "未知的 Key 类型"}, 400)
            if not isinstance(value, str) or not KEY_RE.fullmatch(value.strip()):
                return self._json({"error": "Key 格式不对：应为 8–512 位、不含空格的字符"}, 400)
            try:
                secrets.set(provider, value.strip())
            except Exception:  # noqa: BLE001 - 钥匙串异常信息可能回显输入，不透传
                return self._json({"error": "保存失败：无法写入钥匙串或配置文件"}, 500)
            return self._json(config_payload())

        if p == "/api/config/key/delete":
            provider = body.get("provider", "")
            if provider not in secrets.PROVIDERS:
                return self._json({"error": "未知的 Key 类型"}, 400)
            secrets.delete(provider)
            return self._json(config_payload())

# /api/job 的 except 链加：
            except PrepareBlocked as e:
                return self._json({"error": str(e), "need": e.need, "missing": e.missing}, 409)
```
- **MIRROR**: ERROR_HANDLING；`secrets.status()` 已只含掩码（`secrets.py:144-164`）。
- **IMPORTS**: `consent`, `secrets`。
- **GOTCHA**:
  - **Key 绝不进日志/响应**：`log_message` 已静音（`server.py:302`），保持；错误分支不要 `str(exc)`。
  - env 来源的 Key（`source == "env"`）优先级最高，GUI 保存后仍然不生效——界面要提示「来自环境变量，此处修改不生效」（Task 11）。
  - 冻结 App 里 `keyring` 后端是 macOS Keychain，首次写入可能弹系统授权框；这是正常行为，写进手工验证清单。
  - prepare 前置检查要求两个 Key 都在；已转写过的项目没有 mediakit Key 也会被拦——GUI 首发场景可接受（见需用户决策 #2）。
- **VALIDATE**（`tests/test_server_config.py`，先 RED）：
  - `test_config_initially_unconsented_and_unconfigured`。
  - `test_set_key_returns_masked_only`：POST key `AKLTabcdefghij9f2a` → 200，响应 JSON 文本里**不含**明文，含 `AKLT****9f2a`；`secrets.get("mediakit")` 等于明文。
  - `test_reject_bad_key`：含空格 / 过短 / 非字符串 → 400；未知 provider → 400。
  - `test_delete_key`。
  - `test_prepare_blocked_until_consent_and_keys`：make_project → POST `/api/job` prepare → 409 `need=consent`；POST consent → 409 `need=keys`、`missing==["mediakit","deepseek"]`；两 Key 写入后（monkeypatch `job_command` 为 fake）→ 200。
  - `test_key_never_written_to_project_or_log`：完成上一步后 `grep` 项目目录所有文件与 `JOBS` 日志不含明文。

### Task 8: aicut prepare 不再静默跳过文本分析（GL-02 CLI 侧）
- **ACTION**: `aicut.py:588-598` 加前置 Key 检查，`cmd_text` 无条件执行。
- **IMPLEMENT**:
```python
def _require_prepare_keys(pdir: Path) -> None:
    """处理素材前一次性检查 Key：别跑到一半才失败，更不能静默跳过文本分析。"""
    missing = []
    if not (pdir / "work/transcript_raw.json").exists() and not secrets.get("mediakit"):
        missing.append("语音转写 MEDIAKIT_API_KEY")
    if not secrets.get("deepseek"):
        missing.append("文本分析 DEEPSEEK_API_KEY")
    if missing:
        die("缺少 " + "、".join(missing)
            + "：在剪辑台「设置」里填写，或运行 `uv run python aicut.py config set <mediakit|deepseek>`")


def cmd_prepare(args) -> None:
    """GUI 用：只做前期（不 build），完成后再由人挑镜头。"""
    _require_prepare_keys(project_dir(args.name))
    cmd_ingest(args); cmd_transcribe(args); cmd_analyze(args); cmd_text(args)
    cmd_junk(args); cmd_scenes(args); cmd_quality(args)
    cmd_score(args); cmd_summary(args); cmd_questions(args); cmd_select(args)
    cmd_brief(args)
    ok("前期处理完成，可以去挑镜头了")
```
- **MIRROR**: `die()`；`cmd_text` 自身的检查（`aicut.py:244-245`）保留。
- **IMPORTS**: 无新增。
- **GOTCHA**: `cmd_run`（`aicut.py:601-607`）不走 b 路，不在本范围；不要顺手改。
- **VALIDATE**（`tests/test_aicut_cli.py`）：
  - `test_prepare_fails_fast_without_deepseek_key`：`isolated_env`，写 mediakit Key、不写 deepseek；建最小项目；`monkeypatch.setattr(aicut, "cmd_ingest", lambda a: pytest.fail("不应开始处理"))`；`pytest.raises(SystemExit)` 且 `capsys` 输出含 `DEEPSEEK_API_KEY`。
  - `test_prepare_runs_text_when_key_present`：两 Key 都在，把 `cmd_*` 全部 monkeypatch 成记录调用 → 调用序列含 `cmd_text`。

### Task 9: Windows 导出任务与版本状态（GL-14 服务端）
- **ACTION**: `/api/job` 支持 `task:"export"`；`project_state` 版本条目带 Windows 包状态；`/api/open` 支持 `target:"export"` 在访达中显示。
- **IMPLEMENT**:
```python
# gui/server.py
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def windows_zip(pdir: Path, version: str) -> Path:
    title = (jload(pdir / "project.json", {}) or {}).get("title") or pdir.name
    stem = _UNSAFE_FILENAME.sub("_", f"{title}_{version}_Windows")
    return pdir / "output" / version / f"{stem}.zip"


def export_args(name: str, version: str) -> list[str]:
    pdir = require_project(name)
    version = require_version(version)              # M1 helper；无则 VERSION_RE
    timeline = pdir / "output" / version / "timeline.json"
    if not timeline.exists():
        raise FileNotFoundError("这一版还没有时间线，先生成成片")
    out = windows_zip(pdir, version)
    return ["--timeline", str(timeline), "-o", str(out.parent), "--package-name", out.stem]

# /api/job：
            elif task == "export":
                try:
                    extra = export_args(name, body.get("version", ""))
                except (ValueError, FileNotFoundError) as e:
                    return self._json({"error": str(e)}, 400)

# project_state() 版本循环里（server.py:123-130 的 dict）追加：
        zip_path = windows_zip(pdir, d.name)
        "windows_zip": zip_path.name if zip_path.exists() else None,
        "windows_mb": round(zip_path.stat().st_size / 1e6) if zip_path.exists() else 0,

# /api/open：
            if target == "export":
                try:
                    zip_path = windows_zip(pdir, require_version(body.get("version", "")))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if not zip_path.exists():
                    return self._json({"error": "还没有导出 Windows 包"}, 404)
                subprocess.run(["open", "-R", str(zip_path)], capture_output=True)
                return self._json({"ok": True})
```
- **MIRROR**: `cmd_export`（`aicut.py:375-393`）的参数；ERROR_HANDLING。
- **IMPORTS**: 无新增。
- **GOTCHA**:
  - `cmd_export` 默认 `-o dist` 是相对 cwd 的——冻结 App 的 cwd 不可写，**必须**显式传 `-o`。
  - `cmd_export` 用 `f"{name}.zip"` 拼路径，`title` 里若有 `/` 会变成子目录——所以 `windows_zip` 先过滤非法字符。
  - Windows 剪映里显示的草稿名由 `export_draft._api_name` 只保留 ASCII（中文片名会变成 `v3_Windows` 这类），属既有行为，不在本次修改；写进 Notes。
  - `package_draft` 会在 `output/vN/` 下临时建 `_pkg_*` 目录再删除；`project_state` 只遍历 `output/v*` 一层，不受影响。
  - 导出不依赖 Mac 草稿（只需 timeline.json），`--no-draft` 出的版本也能导 Windows 包。
- **VALIDATE**（`tests/test_server_export.py`，先 RED）：
  - `test_export_job_builds_expected_args`：monkeypatch `job_command` 记录参数并返回 fake 命令 → `extra` 含 `--timeline …/output/v1/timeline.json`、`-o …/output/v1`、`--package-name 测试片_v1_Windows`。
  - `test_export_rejects_bad_version`：`../../x`、`v1/../..`、`` → 400，`JOBS` 为空。
  - `test_export_requires_timeline`：`v9` → 400「先生成成片」。
  - `test_state_reports_windows_zip`：手工写 `output/v1/测试片_v1_Windows.zip` → `/api/state` 的 `versions[0].windows_zip` 等于文件名。
  - `test_title_with_slash_is_sanitized`：title `a/b` → zip 名不含 `/`。
  - 真实链路（不 mock）：`uv run python aicut.py export <项目> --timeline … -o …` 在开发机手工跑一次（见 Manual Validation）。

### Task 10: 任务弹窗——取消 / 关闭 / 重试 / 冲突（GL-22、GL-17 前端）
- **ACTION**: 改 `gui/static/index.html` 的 `api()`、`startJob`、`pollJob`、`showModal` 区域（435-468）。
- **IMPLEMENT**:
```js
/* api()：失败时把响应体挂到 Error 上（在 M1 版本的 api() 上改，保留它加的 token 头） */
  if(!r.ok){ const e = new Error(j.error || ('请求失败 '+r.status)); e.status=r.status; e.data=j; throw e; }

const JOB_TITLES = {prepare:'正在处理素材', build:'正在生成成片', export:'正在导出 Windows 剪映包'};
const JOB_DONE = {prepare:'处理完成', build:'新版本已生成', export:'Windows 剪映包已导出'};
let lastJob = null;   // {task, extra}：给「重试」用
let currentJobId = null;

function jobModal(task){
  showModal(JOB_TITLES[task]||'处理中',
    '<div class="log" id="log">准备中…</div><div id="jobActions" style="display:flex;gap:8px;margin-top:12px"></div>');
}
function setJobActions(kind){
  const a = $('#jobActions'); if(!a) return;
  a.innerHTML = kind==='running'
    ? '<button class="danger" onclick="cancelJob()">取消任务</button>'
    : (kind==='conflict'
        ? '<button class="primary" onclick="attachJob()">查看进行中的任务</button><button class="ghost" onclick="closeModal()">关闭</button>'
        : '<button class="primary" onclick="retryJob()">重试</button><button class="ghost" onclick="closeModal()">关闭</button>');
}
function startJob(task, extra){
  if(!state.project){ toast('先选项目'); return; }
  if(task==='build' && !state.shots.length){ toast('分镜表是空的，先生成镜头'); return; }
  lastJob = {task, extra};
  jobModal(task); setJobActions('running');
  api('/api/job', {method:'POST', headers:{'Content-Type':'application/json'},
                   body: JSON.stringify({project: state.project, task, ...(extra||{})})})
    .then(({job_id})=>{ currentJobId=job_id; pollJob(job_id, task); })
    .catch(e=>{
      if(e.status===409 && e.data?.need==='consent'){ closeModal(); return openConsent(()=>startJob(task, extra)); }
      if(e.status===409 && e.data?.need==='keys'){ closeModal(); return openSettings(()=>startJob(task, extra)); }
      logLine('[错误] '+e.message);
      if(e.status===409 && e.data?.job_id){ currentJobId=e.data.job_id; setJobActions('conflict'); }
      else setJobActions('failed');
    });
}
function attachJob(){ jobModal(lastJob?.task); setJobActions('running'); pollJob(currentJobId, lastJob?.task); }
function retryJob(){ if(lastJob) startJob(lastJob.task, lastJob.extra); }
async function cancelJob(){
  if(!currentJobId) return;
  try{ await api('/api/job/'+currentJobId+'/cancel', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}); logLine('[取消] 已请求停止…'); }
  catch(e){ logLine('[错误] '+e.message); }
}
function pollJob(id, task){
  let misses = 0;
  const tick = async ()=>{
    try{
      const j = await api('/api/job/'+id); misses = 0;
      const el = $('#log'); if(el){ el.textContent = j.log.join('\n') || '…'; el.scrollTop = el.scrollHeight; }
      if(j.status==='running'){ setTimeout(tick, 900); return; }
      if(j.status==='done'){
        logLine('\n[完成]');
        setTimeout(async ()=>{ closeModal(); await refresh(); toast(JOB_DONE[j.task||task]||'完成'); }, 700);
        return;
      }
      logLine(j.status==='cancelled' ? '\n[已取消]' : '\n[失败] 看上面的报错；也可以把这段日志发给开发者');
      setJobActions('failed');
      refresh();
    }catch(e){
      if(++misses < 5){ setTimeout(tick, 1500); return; }
      logLine('[连接中断] '+e.message); setJobActions('failed');
    }
  };
  setTimeout(tick, 500);
}
```
外加 GL-22 字幕框：
```js
/* 选中行只切高亮，不重绘整表 → textarea 不再失焦 */
function pick(i){
  state.sel = i;
  document.querySelectorAll('#body tbody tr').forEach((tr, j)=>tr.classList.toggle('sel', j===i));
  if(state.shots[i]) seekNoSwitch(state.shots[i].in);
}
```
以及 `refresh()` 末尾：`if(d.job && !$('#mask').classList.contains('on')){ currentJobId=d.job; lastJob=lastJob||{task:'prepare'}; jobModal(lastJob.task); setJobActions('running'); pollJob(d.job, lastJob.task); }`（切回正在跑任务的项目时能重新看到进度）。
- **MIRROR**: 现有 `showModal/closeModal/logLine/toast` 风格；按钮 class `primary/ghost/danger`。
- **IMPORTS**: 无。
- **GOTCHA**:
  - `retryJob` 走 `startJob` 会重新做 409/前置检查，不要绕过。
  - `/api/job/<id>` 响应 `task` 字段已有（`server.py:471`），用 `j.task` 而不是闭包 `task`（attach 场景下闭包可能不准）。
  - 409 冲突时**不要**自动 attach，让用户点「查看进行中的任务」，否则误以为自己的任务在跑。
  - 所有服务端字符串插入 innerHTML 前用 M1 的 `escapeHtml`；`logLine` 走 `textContent`，安全。
  - `pick()` 不再 `renderTab()`，但 `move/dup/del/addBlank/sortShots` 仍要重绘（顺序/行数变了），保持原样。
- **VALIDATE**: 浏览器验证清单 1–6（见 Manual Validation）。

### Task 11: 设置弹窗与首次使用告知（GL-02 前端）
- **ACTION**: 侧栏加「⚙ 设置」；新增 `openSettings` / `openConsent` / `checkFirstRun`；页面加载时调用。
- **IMPLEMENT**:
```html
<!-- aside 内，#projects 之后 -->
    <button class="ghost" style="margin-top:10px" onclick="openSettings()">⚙ 设置 · API Key</button>
```
```js
const CONSENT_HTML = `
  <p>原片和画面<b>不会</b>离开这台电脑。为了完成粗剪，会有两类数据发到云端：</p>
  <ul style="line-height:2;padding-left:18px">
    <li>素材的<b>音轨</b>（16kHz 单声道）→ <b>火山引擎</b>语音识别，用于转写</li>
    <li>转写出的<b>文字</b> → <b>DeepSeek</b>，用于理解内容、找出重要片段</li>
  </ul>
  <p class="hint">两个服务的 API Key 只保存在本机钥匙串，不会写进日志或项目文件。</p>`;

function openConsent(then){
  showModal('使用前请知悉：哪些数据会发到云端', CONSENT_HTML + `
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="primary" id="consentOk">我知道了，继续</button>
      <button class="ghost" onclick="closeModal()">暂不使用</button></div>`);
  $('#consentOk').onclick = async ()=>{
    try{
      const cfg = await api('/api/config/consent', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      closeModal();
      if(cfg.providers.some(p=>!p.configured)) openSettings(then); else then && then();
    }catch(e){ toast(e.message); }
  };
}

async function openSettings(then){
  let cfg; try{ cfg = await api('/api/config'); }catch(e){ return toast(e.message); }
  const rows = cfg.providers.map(p=>`
    <div class="field">
      <label>${escapeHtml(p.label)} <span class="hint">· ${escapeHtml(p.hint)}</span></label>
      <div class="hint" style="margin-bottom:4px">${p.configured
        ? `已配置 ${escapeHtml(p.masked)}${p.source==='env' ? '（来自环境变量，此处修改不生效）' : ''}`
        : '未配置'}</div>
      <div style="display:flex;gap:8px">
        <input type="password" autocomplete="off" id="key_${p.key}" placeholder="粘贴 Key">
        <button class="primary" onclick="saveKey('${p.key}')">保存</button>
        ${p.configured && p.source!=='env' ? `<button class="danger" onclick="deleteKey('${p.key}')">清除</button>` : ''}
      </div>
    </div>`).join('');
  showModal('设置 · API Key', rows + `
    <p class="hint">Key 只保存在本机钥匙串。<a href="#" onclick="openConsent();return false">查看数据外发说明</a></p>
    <button class="ghost" onclick="closeModal()">完成</button>`);
  openSettings._then = then;
}
async function saveKey(provider){
  const el = $('#key_'+provider); const value = (el?.value||'').trim();
  if(!value) return toast('先粘贴 Key');
  try{
    const cfg = await api('/api/config/key', {method:'POST', headers:{'Content-Type':'application/json'},
                                             body: JSON.stringify({provider, value})});
    el.value = ''; toast('已保存');
    const then = openSettings._then;
    if(then && cfg.providers.every(p=>p.configured)){ closeModal(); openSettings._then = null; return then(); }
    openSettings(then);
  }catch(e){ toast(e.message); }
}
async function deleteKey(provider){
  try{ await api('/api/config/key/delete', {method:'POST', headers:{'Content-Type':'application/json'},
                                           body: JSON.stringify({provider})}); toast('已清除'); openSettings(openSettings._then); }
  catch(e){ toast(e.message); }
}
async function checkFirstRun(){
  try{
    const cfg = await api('/api/config');
    if(!cfg.consent) return openConsent();
    if(cfg.providers.some(p=>!p.configured)) toast('还没有填写 API Key：点左下角「设置」', 3500);
  }catch(e){ /* 服务未就绪时不打扰 */ }
}
// 末尾 loadProjects().then(...) 之后追加：checkFirstRun();
```
- **MIRROR**: `openNew()`（`index.html:487-502`）的弹窗写法、`.field` 样式。
- **IMPORTS**: 无。
- **GOTCHA**:
  - `p.key` 来自服务端白名单（`secrets.PROVIDERS`），可安全拼进 `onclick`；其它字段一律 `escapeHtml`。
  - 输入框 `type=password` + 保存后立即清空；Key 明文不进 `state`、不进 `toast`。
  - 告知弹窗不能让「暂不使用」后就再也找不到——设置页底部有「查看数据外发说明」入口。
  - `openConsent` 无回调时（从设置页打开）点继续只关闭弹窗。
- **VALIDATE**: 浏览器验证清单 7–10。

### Task 12: 版本卡片的 Windows 导出入口（GL-14 前端）
- **ACTION**: 改 `viewVersions()`（`index.html:423-432`），加 `revealExport()`。
- **IMPLEMENT**:
```js
function viewVersions(){
  const vs = state.data.versions || [];
  if(!vs.length) return `<div class="empty">还没有出过片<br><br>
    <button class="primary" onclick="startJob('build')">生成第一版</button></div>`;
  return vs.map(v=>`<div class="ver">
    <h3>${escapeHtml(v.name)} <span class="hint">${v.shots} 镜 · ${fmtLong(v.duration)} · ${escapeHtml(v.mtime)}</span></h3>
    <div class="m">Mac 剪映草稿名：<b>${escapeHtml(v.draft)}</b></div>
    <div class="m" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="ghost" onclick="startJob('export', {version:'${escapeHtml(v.name)}'})">导出 Windows 剪映包</button>
      ${v.windows_zip ? `<span class="hint">已导出 ${escapeHtml(v.windows_zip)}（${v.windows_mb} MB）</span>
        <button class="ghost" onclick="revealExport('${escapeHtml(v.name)}')">在访达中显示</button>` : ''}
    </div>
    ${v.preview? `<video src="/media/${encodeURIComponent(state.project)}/preview/${encodeURIComponent(v.name)}" controls preload="metadata"></video>` : '<p class="hint">这一版只有工程，没有预览片</p>'}
  </div>`).join('');
}
async function revealExport(version){
  try{ await api('/api/open', {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify({project: state.project, target:'export', version})}); }
  catch(e){ toast(e.message); }
}
```
- **MIRROR**: 原 `viewVersions`；M1 的 escape 约定（若 M1 已把这段改成 DOM 构建，按 M1 的写法加按钮）。
- **GOTCHA**: `v.name` 服务端只会是 `v\d+`，但仍 escape（防 M1 之外的路径）。导出耗时数分钟（拷媒体），用任务弹窗而非同步请求。
- **VALIDATE**: 浏览器验证清单 11–12；Windows 实机：把 zip 拷到 Windows → 双击 `INSTALL.bat` → 剪映打开并播放（放行检查项）。

### Task 13: 文档与登记册
- **ACTION**:
  - `docs/GUI.md`「接口一览」加：`GET /api/config`、`POST /api/config/consent`、`POST /api/config/key`、`POST /api/config/key/delete`、`POST /api/job/<id>/cancel`、`/api/job` 的 `task:'export'` + `version`、`/api/open` 的 `target:'export'`；「已知限制」第 89 行改为「一次只跑一个任务；再点会提示已有任务在运行，可取消」；「部署到另一台 Mac」中 `API Key | 写到 ~/.mediakit/api_key` 改为「首次打开后在 ⚙ 设置 里填」。
  - 「一、剪辑师怎么用」步骤 2 前插入「第一次打开：读外发说明 → ⚙ 设置里填两个 Key」，步骤 5 后加「需要在 Windows 上精修：版本 → 导出 Windows 剪映包」。
  - `docs/go-live-blockers.md`：每个 GL 关闭时在「状态」列填提交号。
- **VALIDATE**: 文档里的接口与 `gui/server.py` 路由一一对应（`grep -n '"/api/' gui/server.py` 对照）。

---

## Testing Strategy

### Unit / Integration Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| test_cli_cmd_frozen_relaunches_self | FROZEN=True, `["prepare","p1"]` | `[exe, "--aicut-cli", "prepare", "p1"]` | |
| test_dispatch_runs_module_and_returns_exit_code | 临时模块 `sys.exit(3)` | 3 | 是 |
| test_build_uses_module_cmd_when_frozen | FROZEN=True | to_jianying 经 `--aicut-module` 调起，env 带 DRAFT_ROOT | |
| test_unknown_task_rejected_without_ghost_job | task="rm" | 400，JOBS 为空 | 是 |
| test_second_job_conflicts_409 | 两次起任务 | 第二次 409 + 第一次的 job_id | 并发 |
| test_cancel_kills_process_group | 子进程再拉孙进程 | `cancelled`，互斥释放 | 是 |
| test_failed_job_status_and_exit_code | exit 2 | `failed`, exit 2 | |
| test_child_stdin_is_devnull | — | Popen 收到 DEVNULL + new session | GL-20 |
| test_api_new_passes_no_input_and_devnull | POST /api/new | argv 含 `--no-input`、stdin DEVNULL、有 timeout | GL-20 |
| test_new_no_input_never_prompts | `new --no-input` | 不调 ask_calibration | |
| test_new_reuses_leftover_empty_dir | 预先存在空目录 | 创建成功 | 是 |
| test_new_cleans_up_dir_on_save_failure | schema.save 抛错 | 目录被删 | 是 |
| test_asr_state_* | 指纹/backend/过期/损坏/旧格式 | 返回 None 且删文件 | 是 |
| test_failed_task_clears_state_then_resubmits | 云端 failed | 状态清除，下次重新 submit | GL-16 |
| test_timeout_keeps_state_for_resume | 超时 | 状态保留 | |
| test_changed_audio_resubmits | wav 内容变化 | 重新 submit | |
| test_consent_* | accept / 版本变化 | True / False | |
| test_set_key_returns_masked_only | 明文 Key | 响应只含掩码 | 安全 |
| test_reject_bad_key | 空格/过短/非字符串/未知 provider | 400 | 是 |
| test_prepare_blocked_until_consent_and_keys | 逐步满足 | 409 consent → 409 keys → 200 | |
| test_key_never_written_to_project_or_log | 全流程后扫描 | 项目文件与任务日志无明文 | 安全 |
| test_prepare_fails_fast_without_deepseek_key | 缺 deepseek | SystemExit，未开始 ingest | GL-02 |
| test_export_job_builds_expected_args | version=v1 | 正确的 --timeline/-o/--package-name | |
| test_export_rejects_bad_version | `../../x` 等 | 400 | 路径穿越 |
| test_state_reports_windows_zip | zip 已存在 | windows_zip 字段 | |

### Edge Cases Checklist
- [x] 空输入：空 Key、空版本号、空项目名 → 400
- [x] 最大输入：Key > 512 字符 → 400
- [x] 非法类型：`value` 非字符串、`version` 非 `v\d+`
- [x] 并发：两个任务同时起 → 409；取消与结束竞争（`cancel` 标志在锁内）
- [x] 网络失败：ASR 超时/网络重试耗尽 → 保留续查；终态失败 → 清状态
- [x] 权限：钥匙串写失败 → 500 且不回显输入
- [ ] 磁盘满（导出 Windows 包拷媒体）→ 任务 failed，日志可见（不新增预检，KI-33）

---

## Validation Commands

### Static Analysis
```bash
# 仓库未配置 lint / typecheck；最低限度做语法编译检查
uv run python -m py_compile aicut.py app/main.py gui/server.py pipeline/*.py
```
EXPECT: 无输出、退出码 0

### Unit Tests
```bash
uv run pytest tests/test_proc.py tests/test_export_draft.py tests/test_asr_state.py \
  tests/test_cloud.py tests/test_consent.py tests/test_aicut_cli.py \
  tests/test_server_jobs.py tests/test_server_config.py tests/test_server_export.py
```
EXPECT: 全部通过

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 无回归（基线 2026-10-19：112 passed）

### Database Validation
N/A — 无数据库。

### Build Validation（打包版自启子进程是本里程碑最大风险，必须验）
```bash
./packaging/build_app.sh
"dist/AI粗剪.app/Contents/MacOS/ai-cut" --aicut-cli list            # 应打印项目列表并退出，不弹窗、Dock 不出第二个图标
"dist/AI粗剪.app/Contents/MacOS/ai-cut" --aicut-module pipeline.to_jianying --help   # 应打印 argparse 帮助
```
EXPECT: 两条命令都即时返回、输出逐行可见；然后双击 App 走 Manual Validation 全流程。

### Browser Validation
```bash
uv run python app/main.py          # 桌面壳
python3 gui/server.py --open       # 或浏览器版（.command 同路径，复现 GL-20）
```

### Manual Validation
1. 分镜表：点任一行的字幕框 → 光标停留可连续输入；该行高亮（GL-22）。
2. 起「处理素材」→ 弹窗出现「取消任务」→ 点取消 → 数秒内显示 `[已取消]` + 「重试 / 关闭」，`ps aux | grep ffmpeg` 无残留（GL-17）。
3. 用不存在的素材路径造一次失败 → 弹窗出现「重试 / 关闭」，「关闭」能关掉遮罩（GL-22）。
4. 一个任务运行中，再点「生成成片」→ 提示「已有任务在运行…」+「查看进行中的任务」（GL-17）。
5. 任务运行中切到别的项目再切回来 → 重新看到进度弹窗。
6. 杀掉服务（Ctrl+C）期间轮询 → 5 次失败后显示「连接中断」+ 按钮，不再死等。
7. 删除 `~/.config/ai-cut/consent.json`（或换新用户）→ 打开 App 先出外发告知；点「暂不使用」后「处理素材」被拦并重新弹告知（GL-02）。
8. ⚙ 设置：保存 Key 后只显示掩码；清除后显示未配置；`grep -r <Key 片段> ~/Documents/AI粗剪 projects/` 无结果（PRD §7）。
9. 设置 `export DEEPSEEK_API_KEY=…` 后启动 → 设置页显示「来自环境变量，此处修改不生效」、无清除按钮。
10. 不填 DeepSeek Key 用 CLI 跑 `uv run python aicut.py prepare <项目>` → 立即 `[x] 缺少 文本分析 DEEPSEEK_API_KEY…`，不再静默跳过。
11. 版本 → 「导出 Windows 剪映包」→ 任务完成后卡片显示「已导出 …_Windows.zip（N MB）」→「在访达中显示」选中该 zip（GL-14）。
12. 拷 zip 到 Windows → `INSTALL.bat` → 剪映打开并播放（放行检查项）。
13. 用 `启动剪辑台.command` 启动 → 新建项目秒回；手动建一个同名空目录后再新建 → 成功（GL-20）。
14. ASR：在 `work/asr_task.json` 写一个已失败的 task_id（或断网让云端判失败）→ 重跑 prepare 应重新提交而不是一直失败；换一条素材复用同名 work 目录 → 重新提交（GL-16）。

---

## Acceptance Criteria
- [ ] GL-02：GUI 可配置/清除两种 Key，只回显掩码；首次使用告知两条外发数据流并记录确认；未确认或缺 Key 时 prepare 被拦；CLI prepare 缺 DeepSeek Key 直接失败
- [ ] GL-14：GUI 每个版本可导出 Windows 剪映包，打包版同样可用，可在访达中定位
- [ ] GL-16：ASR 终态失败后重跑会重新提交；状态绑定音频指纹与 backend；超时/取消后仍可续查
- [ ] GL-17：同时只有一个任务；可取消（连同 ffmpeg）；打包版不再多线程 `redirect_stdout`；未知任务不留幽灵
- [ ] GL-20：开发/`.command` 启动下新建项目不卡；失败后同名重试成功
- [ ] GL-22：字幕框可输入；任务失败/取消后弹窗可关闭、可重试
- [ ] 所有新测试通过，`uv run pytest` 无回归
- [ ] 打包版 Build Validation 两条命令通过

## Completion Checklist
- [ ] 新代码遵循 `proc`/`secrets`/`cloud` 的命名、docstring、可注入风格
- [ ] 错误处理沿用 `{"error": 中文}` + 4xx/5xx；CLI 用 `die()`
- [ ] 任务日志前缀 `[错误]` `[取消]` `[退出码]`；无 Key 明文
- [ ] 测试用 `isolated_env`，绝不碰真实钥匙串/项目目录
- [ ] 无硬编码魔法数（`MAX_ACTIVE_JOBS`、`CANCEL_GRACE_S`、`NEW_PROJECT_TIMEOUT_S`、`MAX_AGE_S`、`KEY_RE` 均为命名常量）
- [ ] `docs/GUI.md` 与登记册已更新
- [ ] 未实现登记册以外的东西（KI-33/35/36 未碰）
- [ ] 自包含：实现时无需再查代码库

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 打包版自启子进程行为异常（第二个 Dock 图标、stdout 缓冲、启动慢） | 中 | 高 | `dispatch` 在 import webview 前；`_line_buffered_stdio`；Build Validation 两条命令；onedir 构建启动 <1s。若仍不可行：回退方案 = 保留同进程执行但加全局锁串行化 + 打包版隐藏「取消」按钮，并登记 KI |
| M3（GL-15）未先合入时取消任务留下半成品被当完成 | 中 | 高 | 硬性排期 M3 在 M4 之前；取消测试在 M3 合入后跑真实 prepare 验证 |
| M1 的 token/校验 helper 命名与本计划假设不同 | 高 | 低 | 计划用占位名 `require_project` / `require_version`，实现时按 M1 实际替换；新端点不自行实现鉴权 |
| 旧版 `asr_task.json`（无 schema）被作废导致一次重复计费 | 低 | 低 | 只影响升级当下正在转写的项目；提交说明写明 |
| macOS 钥匙串首次写入弹授权框，剪辑师误点拒绝 | 中 | 中 | 写入失败自动降级到 0600 文件（`secrets.set` 现有逻辑）；手工验证清单覆盖 |
| `killpg` 杀不到脱离进程组的孙进程 | 低 | 中 | aicut 内 ffmpeg/mediakit-cli 都是普通 `subprocess.run`，不 `setsid`；测试覆盖孙进程 |
| 全局互斥让剪辑师在 15 分钟 prepare 期间无法给另一项目出片 | 中 | 低 | 常量 `MAX_ACTIVE_JOBS` 可调；见需用户决策 #3 |

## Notes

### 关键设计决定
- **为什么统一子进程而不是加锁**：GL-17 要求「可取消」，而同进程线程无法中断阻塞中的 ffmpeg / HTTP；`redirect_stdout` 是进程全局的，加锁只能串行化不能取消。自启子进程是 PyInstaller 下 multiprocessing 的同款机制，顺带修好冻结版 Windows 导出（`export_draft` 原本用 `sys.executable` 跑脚本，打包后会拉起 App 自身）。
- **ASR 状态独立成 `asr_state.py`**：GL-01（M5）换 HTTP 客户端时只需 `BACKEND = "volc-http"` 并调用同一组 `load/save/clear`，旧状态自动作废。
- **Key 设置页数据驱动**：前端只渲染 `/api/config` 返回的 providers；GL-01 若需要不同凭证（例如 AppID + Token），只改 `secrets.PROVIDERS/PROVIDER_LABELS`。
- 「GUI 不实现业务逻辑」（`docs/GUI.md`）：Key 存取直接调 `pipeline.secrets`，与现有 `review.set_level` 等直接调用 pipeline 的先例一致，不经 `aicut config`（后者读 stdin、输出是给人看的文本）。
- Windows 包里的草稿名仍由 `_api_name` 只保留 ASCII（中文片名在 Windows 剪映里会显示成 `v3_Windows`）——既有行为，不在本范围。

### 需用户决策（均已给推荐默认，实现按默认走，不阻塞）
1. **外发告知文案与位置**（GL-02，产品/UI）
   - 推荐默认：首次打开即弹窗（标题「使用前请知悉：哪些数据会发到云端」，正文见 Task 11 `CONSENT_HTML`），按钮「我知道了，继续」/「暂不使用」；设置页底部可再次查看。
   - 备选：只在第一次点「处理素材」时弹。
2. **缺 DeepSeek Key 时的行为**（GL-02）
   - 推荐默认：prepare 直接失败并指向设置页（不允许跳过文本分析，避免必留内容判断退化）。
   - 备选：提供「跳过文本分析（不推荐）」显式选项。
3. **任务互斥粒度**（GL-17）
   - 推荐默认：全局一次只跑一个任务（`MAX_ACTIVE_JOBS = 1`，与 `docs/GUI.md` 原意一致，避免 ffmpeg 争 CPU、重复计费）。
   - 备选：每个项目一个任务，不同项目可并行。
4. **设置入口与 Key 输入框文案**（GL-02，UI）
   - 推荐默认：侧栏底部「⚙ 设置 · API Key」；字段名「语音转写（火山引擎）」「文本分析（DeepSeek）」，状态「已配置 AKLT****9f2a / 未配置」，按钮「保存 / 清除」。
5. **Windows 包文件名与存放位置**（GL-14）
   - 推荐默认：`<项目>/output/vN/<片名>_vN_Windows.zip`，版本卡片提供「在访达中显示」。
   - 备选：导出时弹系统保存对话框让用户选位置（需要 pywebview SAVE_DIALOG，改动更大）。
