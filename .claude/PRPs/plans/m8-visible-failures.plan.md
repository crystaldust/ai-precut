# Plan: 里程碑 8「失败可见」（KI-19..KI-27 / KI-48 / KI-49 / KI-56 / KI-66）

## Summary
让 ffmpeg / ffprobe / LLM / JSON 的失败不再伪装成成功：分析类 ffmpeg 调用一律检查退出码并带回 stderr 末尾（KI-19 / KI-20）；损坏的 JSON 不再被当成「没有」或抛 traceback，而是给出带文件名的人话（KI-21 / KI-48 / KI-56 / KI-66）；LLM 兜底结果与匹配不上的必留原话 / 话题 / 答案进入常驻警告栏（KI-22 / KI-23）；转写时间码、废片区间、项目默认值的数据错误修正（KI-24 / KI-26 / KI-27）；确认页答案类型容错（KI-49）。KI-25 已在 `ebabfcc` / `ac3f15c` 修掉，本里程碑只补回归测试锁住。

## User Story
作为剪辑师，我希望任何一步失败时 App 都直接告诉我「哪一步、为什么、怎么补救」，而不是给我一个空的废片表、一个镜头的切分结果、一套兜底问题或者一屏 traceback，这样我不会在错误的分析结果上继续剪。

## Problem → Solution
- **现状**：`junk_detect` / `understand_visual` 不看 ffmpeg 退出码，坏素材得到「0 条废片 / 1 个镜头 / 无明显异常」；`render_preview` 用 `check=True` 让 traceback 盖住 ffmpeg 原因；`cmd_ingest` 遇到认不出的素材抛 `KeyError: 'format'`；GUI `jload` 把损坏 JSON 当默认值（project.json 坏了显示「项目不存在」、三档判定坏了显示「还没有三档判定」）；shots.json 缺 `shots` 键 `KeyError`；overrides.json 损坏时 `select`/`prepare` 打 traceback；兜底的决策问题被缓存固化、LLM 错误只写文件；指定原话 / 必留话题 / 答案匹配不上静默跳过；转写缺时间码默认 0、包含句让段尾回退、`59.999` 显示 `00:60.00`；`default_project` 共享 DEFAULTS 里的可变 dict；废片检测丢掉文件末尾未闭合区间、重叠区间重复计数、`--scene` 白算；确认页磁盘上多选答案不是数组时整页渲染失败。
- **目标**：新增 `media_io.run_analysis / probe_duration / probe_material`（严格版，失败抛 `MediaError`）；新增 `schema.read_json` + `schema.CorruptJSON`（缺失→默认值，损坏→带文件名的异常）；`aicut.main` 统一把 `CorruptJSON` / `OverridesCorrupt` 变成 `die()`；`notices.project_warnings` 汇总损坏文件与 LLM 兜底；`select` 把匹配不上的东西写进 `warnings`；数据层 bug 逐个修正并以单测钉住。

## Metadata
- **Complexity**: Large（13 个源文件 + 2 个前端页 + 1 个新 gui 模块，约 14 个测试文件；无新依赖）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: 里程碑 8「失败可见」（KI-19..KI-27 KI-48 KI-49 KI-56 KI-66）
- **Estimated Files**: 30（源 16：新建 1 / 修改 15；测试 14：新建 4 / 修改 10）

---

## 各 KI 现状核对（以当前 HEAD `963374c` 代码为准）

| KI | 结论 | 当前位置 | 说明 |
|---|---|---|---|
| KI-19 | **仍存在** | `pipeline/junk_detect.py:68-69, 99-105, 174`；`pipeline/understand_visual.py:19-38, 96-125`；`aicut.py:216-224` | GL-15 只把「产出文件」的 ffmpeg 接到了 `media_io`；三个**分析类**调用（filter 日志 / 抽帧管道 / ffprobe）仍不看退出码。原登记 `aicut.py:186-194` 已漂移到 `cmd_ingest`（与 KI-66 同处）。 |
| KI-20 | **大部分已修，剩余仍存在** | 已修：`media_io.run_ffmpeg`（`pipeline/media_io.py:87-96`，`ef3899f`）带回 stderr 末尾，抽音轨 / 代理 / 切片都走它。剩余：`pipeline/render_preview.py:107` `subprocess.run(cmd, check=True)`；`aicut.py:136` 建 venv `check=True`；`pipeline/to_jianying.py:120-121` 死代码 `run(..., check=True, capture_output=True)` | 打包版 `render_preview` 在进程内跑，ffmpeg 子进程的 stderr 直接写到 fd 2，不进 `run_inprocess` 的缓冲，用户只看到 `CalledProcessError`；开发版 `_run_pipeline` 只打印 stderr 末尾 600 字，被 traceback 占满。 |
| KI-21 | **仍存在**（位置漂移） | `gui/server.py:77-81`（`jload`）、`:119-123`（project.json 坏→404「项目不存在」）、`:180-182`（三档判定坏→「还没有三档判定」）、`:231-235`（决策问题坏→「还没有决策问题」）、`:151-164`（shots / segments / junk / materials 坏→空）；`aicut.py:88-91`（`load_json` 缺失→默认、损坏→traceback）、`:612/:467`（预设缺失静默用 `{}`） | 登记的 `pipeline/classify.py:116-121` 已漂移（当前该处是 `_cap_pending`），对应现在 `classify.run:227-233`：给了 `segments_audio.json` / `visual_quality.json` 路径但文件不存在时静默当空，损坏时 traceback。按此解释处理。 |
| KI-22 | **仍存在** | `pipeline/questions.py:132-134`；`aicut.py:392-394`（`questions.json` 存在即跳过，兜底被固化）；`pipeline/summarize.py:111-113`；`aicut.py:381`（只打「（兜底）」不打原因） | |
| KI-23 | **仍存在** | `pipeline/select.py:119-124`（答案标签对不上 `continue`）、`:82-88` + `:301`（必留话题对不上丢弃）、`:280-286`（指定原话找不到 / 太短 `continue`） | |
| KI-24 | **仍存在** | `pipeline/format_transcript.py:48-49`（缺时间码→0）、`:80`（`cur["end"] = s["end"]` 包含句回退）、`:28-30`（`tc(59.999)`→`00:60.00`） | |
| KI-25 | **已修复**（`ebabfcc` + `ac3f15c`） | `pipeline/llm.py:77`（`except (OSError, http.client.HTTPException)`：`RemoteDisconnected` 同时是 `ConnectionResetError` 与 `HTTPException`）；`:122-126`（200 非 JSON → 重试） | 缺 `RemoteDisconnected` / `ConnectionResetError` 走真实 `default_transport` 的回归测试 → 本计划只补测试（Task 2）。 |
| KI-26 | **仍存在** | `pipeline/schema.py:41-45`（`{**DEFAULTS}` 浅拷贝，`brief` / `calibration` 共享）、`:81-83`（`migrate` 补字段同样共享） | |
| KI-27 | **仍存在** | `pipeline/junk_detect.py:84-97`（未配对的 open 丢弃）、`:104-105`（`scenes` 算了不返回）、`:172`（「删」行重叠时重复累加） | |
| KI-48 | **仍存在** | `aicut.py:621-622`（`spec["shots"]`） | `load_json` 损坏时还会 traceback。 |
| KI-49 | **仍存在** | `gui/static/confirm.html:92`（`(chosen||[]).includes`）、`:99-101`（`arr.splice/push`） | 服务端 `confirm_payload`（`gui/server.py:228-238`）原样透传。 |
| KI-56 | **仍存在** | `aicut.py:415-423`（`cmd_select` 只接 `SelectionError`）；`pipeline/select.py:535`（`review.load`） | `cmd_build` 已在 GL-25 接住（`aicut.py:625-628`）；`prepare` 经 `cmd_select` 同样中招。 |
| KI-66 | **仍存在** | `aicut.py:216-224` | ffprobe 失败时 stdout 为空 → `json.loads("")` 抛 `JSONDecodeError`；stdout 为 `{}` → `KeyError: 'format'`。 |

---

## UX Design

### Before
```
┌──────────────────────────────────────────────────────────────┐
│ 处理素材（坏素材 / 网络盘掉线）                                │
│  [✓] 废片检测完成 → work/junk_report.csv        ← 实际 0 条    │
│  [✓] 镜头 1 个（切点 0）                          ← ffmpeg 已失败│
│  [✓] 画面质量：0 帧 · 无明显异常                                │
│ 素材认不出：Traceback … KeyError: 'format'                       │
│ overrides.json 坏：Traceback … OverridesCorrupt                 │
│ 内容摘要：[✓] （兜底）素材包含：…        ← 不说为什么           │
│ 决策问题：已存在，跳过                   ← 兜底问题永远不重试   │
│ 指定原话「退费」写错一个字 → 静默没进片                          │
│ 剪辑台：project.json 坏 → 「项目不存在」 ；三档判定坏 → 「还没有」│
│ 确认页：答案文件里多选是字符串 → 整页空白                        │
└──────────────────────────────────────────────────────────────┘
```

### After
```
┌──────────────────────────────────────────────────────────────┐
│ 处理素材（坏素材）                                              │
│  [x] 废片检测失败：ffmpeg 失败（退出码 1）：…Invalid data found…│
│      （任务停在这一步，任务弹窗可「导出诊断包」）                │
│ 素材认不出：[x] 素材读不出来：ffprobe 认不出这个文件（…）：…     │
│ overrides.json 坏：[x] 人工裁决文件损坏，未做任何修改：…        │
│ 内容摘要：[!] 内容摘要是兜底生成的（AI 调用失败：HTTP 402 …）   │
│ 决策问题：上次是兜底模板且还没作答 → 这次重新让 AI 生成           │
│ 选段：[!] 指定必须保留的原话「推费」在转写里找不到，没能进片      │
│ 剪辑台警告栏：                                                  │
│   · 分镜表（shots.json）损坏、读不出来：在「分镜表」重新保存会覆盖 │
│   · 内容摘要是兜底生成的（…）                                    │
│ project.json 坏 → 「项目配置（project.json）损坏、读不出来…」    │
│ 确认页：多选答案不是数组 → 当作未选，页面正常                    │
└──────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| CLI / 任务日志：废片检测、镜头切分、画面质量 | ffmpeg 失败也 `[✓]` | `[x] <步骤>失败：<ffmpeg stderr 末尾>`，退出码 1 | GUI 任务失败弹窗已有（M4） |
| CLI：ingest | `KeyError` traceback | `[x] 素材读不出来：…` | |
| CLI：build | shots.json 缺键 / 损坏 → traceback | `[x] 分镜表 shots.json 不能用：…` | |
| CLI：select / prepare | overrides 损坏 → traceback | `[x] 人工裁决文件损坏，未做任何修改：…` | 所有命令统一 |
| CLI：summary / questions | 只有「（兜底）」 | `[!] … 是兜底生成的（AI 调用失败：原因）` | |
| CLI：select | 匹配不上静默 | `[!]` 逐条列出 | 同时进 selection.json `warnings` → 警告栏 |
| 剪辑台常驻警告栏 | 只含分档 / 选段警告 | + 损坏文件、摘要 / 问题兜底 | 复用 `renderWarnbar`，无新 UI 组件 |
| 剪辑台切项目 | `/api/state` 失败无任何提示 | 警告栏显示错误 + toast | `index.html` `selectProject` |
| 浏览素材 / 确认页 | 损坏 → 「还没有…」 | 409 + 「…损坏、读不出来」 | 页面已有错误显示位 |
| 确认页 | 多选答案非数组 → 整页失败 | 当作未选 | `asList()` + 服务端规整 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/media_io.py` | 1-137 | `MediaError` / `run_ffmpeg` / `_probe_duration` 是 KI-19/20 新函数的同胞，风格照抄 |
| P0 | `pipeline/junk_detect.py` | 58-175 | KI-19/27 改动主体（当前 0% 覆盖，无测试） |
| P0 | `pipeline/understand_visual.py` | 19-63, 84-125 | KI-19：切点 / 抽帧 |
| P0 | `aicut.py` | 84-125, 212-226, 340-401, 403-427, 609-650, 830-834, 924-925 | 所有接线点 |
| P0 | `pipeline/schema.py` | 22-45, 81-99, 114-124 | `read_json` 放在 `write_json` 旁；KI-26 |
| P0 | `gui/server.py` | 77-81, 119-168, 172-238, 482-524, 656-673 | KI-21/49 的 GUI 读路径 |
| P0 | `pipeline/notices.py` | 1-41 | 警告栏数据源，KI-21/22 的展示通道 |
| P1 | `pipeline/select.py` | 82-136, 276-298, 298-443, 520-563 | KI-23 |
| P1 | `pipeline/questions.py` / `pipeline/summarize.py` | 115-139 / 94-119 | KI-22 |
| P1 | `pipeline/format_transcript.py` | 28-89 | KI-24 |
| P1 | `pipeline/review.py` | 23-41 | `OverridesCorrupt` 的人话格式是 `CorruptJSON` 的模板 |
| P1 | `pipeline/proc.py` | 71-105 | `run_inprocess`：打包版 `sys.exit("文字")` 如何变成任务日志（GL-12） |
| P1 | `gui/static/confirm.html` / `common.js` | 66-112 / 1-30 | KI-49 |
| P2 | `tests/conftest.py` | all | `gui_server` / `call` / `make_project` |
| P2 | `tests/test_aicut_build.py` | 33-110 | `project` fixture、`fake_ffmpeg`、CLI die 断言风格 |
| P2 | `tests/test_media_io.py` | 1-50 | `FakeProc` runner 打桩 |
| P2 | `tests/test_frontend_js.py` | 1-60 | node vm 跑 common.js |
| P2 | `tests/test_server_target.py` | 160-188 | 警告栏测试；**`test_state_survives_corrupt_scored_file` 需按新行为更新** |

## External Documentation

No external research needed — feature uses established internal patterns.（只用标准库 `subprocess` / `json` / `copy` / `tempfile`；ffmpeg 行为以本机实测与现有测试为准。）

KEY_INSIGHT: `http.client.RemoteDisconnected` 继承 `ConnectionResetError`（⊂ `OSError`）与 `BadStatusLine`（⊂ `HTTPException`）。
APPLIES_TO: Task 2（KI-25 回归测试）。
GOTCHA: 测试里直接 `raise http.client.RemoteDisconnected("x")` 即可，不需要真 socket。

KEY_INSIGHT: `contextlib.redirect_stderr` 只换 `sys.stderr`，子进程继承的是真实 fd 2。
APPLIES_TO: Task 4（render_preview）。
GOTCHA: 打包版里 `subprocess.run(cmd)`（不 capture）的 ffmpeg 报错进不了任务日志；必须 capture 后放进 `MediaError` 文本再 `sys.exit`。

KEY_INSIGHT: ffmpeg 的 `freezedetect` 在文件末尾不会补发 `freeze_end`；`silencedetect` 的 `silence_start` 可能是负数（`-0.0213`）。
APPLIES_TO: Task 5（KI-27）。
GOTCHA: 收尾闭合用解析出的 `Duration`，起点 `max(0, x)`。

---

## Patterns to Mirror

### NAMING_CONVENTION（用户可见文案是模块级常量，全大写，`{占位符}` + `.format`）
```python
# SOURCE: aicut.py:67-81
TARGET_PROMPT = "想剪成多长的片子？（秒，回车用预设 {default} 秒）"
TEXT_PARTIAL_WARNING = ("上次逐句标注没有完成（work/segments_text.partial.json），"
                        "这次分档用的是上一次完整的标注结果；重新运行「处理素材」可补齐")
DRAFT_NOT_INSTALLED = "草稿未安装（已回滚，剪映草稿库保持原样）"
```
```python
# SOURCE: pipeline/select.py:27-33
MUST_KEEP_OVER_WARNING = "必留内容共 {must}，超过目标 {target}：已全部保留，请重新设定成片时长"
BUDGET_LEGACY_WARNING = "话题数据是旧版本，没能按新目标重新分配话题时长；重新运行 score（或「处理素材」）后再选段"
```

### ERROR_HANDLING（领域异常 → 调用方 `die()`；异常文本即给人看的中文）
```python
# SOURCE: pipeline/media_io.py:25-26, 87-96
class MediaError(RuntimeError):
    """ffmpeg 产物生成失败（临时文件已清理）。"""

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
# SOURCE: aicut.py:235-241（调用方）
    if not media_io.complete_or_adopt(wav):
        info("抽音轨…")
        try:
            media_io.ffmpeg_to(wav, ["-i", c["material"], "-vn", "-ac", "1", "-ar", "16000",
                                     "-c:a", "pcm_s16le"])
        except media_io.MediaError as exc:
            die(f"抽音轨失败：{exc}")
```
```python
# SOURCE: pipeline/review.py:23-41（损坏文件：带路径、说清楚「没做修改」，是 ValueError 子类）
class OverridesCorrupt(ValueError):
    """overrides.json 读不出来：不能当空，否则下一次裁决会把人工结果全部覆盖。"""
...
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverridesCorrupt(f"人工裁决文件损坏，未做任何修改：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise OverridesCorrupt(f"人工裁决文件格式不对（应为对象）：{path}")
```
```python
# SOURCE: gui/server.py:482-491（路由：特定异常在 ValueError 之前接）
        if p == "/api/browse":
            name = q.get("project", [""])[0]
            try:
                return self._json(browse_payload(name))
            except FileNotFoundError as exc:
                return self._json({"error": str(exc)}, 404)
            except review.OverridesCorrupt as exc:  # 必须在 ValueError 之前
                return self._json({"error": str(exc)}, 409)
            except (ValueError, OSError) as exc:
                return self._json({"error": str(exc)}, 400)
```

### LOGGING_PATTERN（CLI 用 info/ok/warn/die；die 同时进日志）
```python
# SOURCE: aicut.py:49-64
def die(msg: str) -> None:
    LOG.error(msg)
    print(f"[x] {msg}")
    sys.exit(1)
...
def warn(msg: str) -> None:
    print(f"[!] {msg}")
```
```python
# SOURCE: aicut.py:319-320（下游警告逐条 warn）
    for w in res.get("warnings") or []:
        warn(w)
```
pipeline 脚本（以子进程 / 进程内 `main()` 方式运行）失败用 `sys.exit("中文原因")`（`pipeline/format_transcript.py:99-100`、`pipeline/render_preview.py:34`），由 `proc.exit_code`（`pipeline/proc.py:71-80`）转成任务日志文字。

### REPOSITORY_PATTERN（JSON 原子写；读侧本计划新增 `read_json` 与之对称）
```python
# SOURCE: pipeline/schema.py:114-124
def write_json(path: Path, obj: Any, *, indent: int | None = 2) -> None:
    """原子写：每次用唯一临时文件，并发写同一路径不会互相踩。indent=None 写紧凑 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    ...
```
```python
# SOURCE: pipeline/notices.py:17-22（「只读、不抛异常」的读取）
def _read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
```

### SERVICE_PATTERN（gui 子模块：不依赖 server，路由在 server 里接线）
```python
# SOURCE: gui/support.py:1-6
"""剪辑台 · 支持：一键导出诊断包（GL-19）与「关于 / 第三方许可」（GL-04，FFmpeg 合规清单第 10 条）。

路由入口 handle_get / handle_post 返回 (状态码, JSON)，不是本模块的路径返回 None；
访问控制（Host / Origin / token）在 server._deny_reason 里统一做完才会走到这里。
"""
```
```python
# SOURCE: gui/server.py:461-462
        if (hit := settings.handle_get(p) or support.handle_get(p)) is not None:
            return self._json(hit[1], hit[0])
```

### TEST_STRUCTURE
```python
# SOURCE: tests/test_media_io.py:10-12（runner 打桩）
class FakeProc:
    def __init__(self, code=0, err=""):
        self.returncode, self.stdout, self.stderr = code, "", err
```
```python
# SOURCE: tests/test_aicut_build.py:33-39, 81-86（CLI：project fixture + die 文案断言）
@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    pdir = tmp_path / "p"
    schema.save(pdir / "project.json", schema.default_project("p", str(tmp_path / "src.mov")))
    return pdir
...
def test_audio_extract_failure_dies_with_reason(project, monkeypatch, capsys):
    monkeypatch.setattr(media_io, "run_ffmpeg", fake_ffmpeg([], fail_on="pcm_s16le"))
    with pytest.raises(SystemExit):
        aicut.cmd_transcribe(argparse.Namespace(name="p"))
    assert "抽音轨失败" in capsys.readouterr().out
```
```python
# SOURCE: tests/test_server_target.py:161-175（GUI：make_project + call + 警告栏断言）
def test_state_collects_warnings(gui_server):
    ...
    make_project(gui_server.root, **{
        "work/selection.json": json.dumps(sel, ensure_ascii=False),
        "work/segments_scored.json": json.dumps(scored, ensure_ascii=False),
        "work/segments_text.partial.json": "{}"})
    _, body, _ = call(gui_server, "GET", "/api/state?project=p1")
    data = json.loads(body)
    text = "\n".join(data["warnings"])
```
```python
# SOURCE: tests/test_frontend_js.py:37-41（node vm 里执行 common.js）
def run_js(script: str, extra_src: str = ""):
    args = json.dumps([str(STATIC / "common.js"), extra_src, script])
    r = subprocess.run([NODE, "-e", HARNESS, args], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/media_io.py` | UPDATE | KI-19/66：`run_analysis`、`probe_duration`（严格）、`probe_material` |
| `pipeline/junk_detect.py` | UPDATE | KI-19/27：退出码、时长 0、收尾闭合、重叠去重、`scenes` 输出 |
| `pipeline/understand_visual.py` | UPDATE | KI-19：切点 / 抽帧 / 时长 检查失败 |
| `pipeline/render_preview.py` | UPDATE | KI-20：改用 `media_io.run_ffmpeg`（只改第 96-108 行的执行方式） |
| `pipeline/to_jianying.py` | UPDATE | KI-20：删掉无人调用的 `run()`（120-121） |
| `pipeline/schema.py` | UPDATE | KI-21：`CorruptJSON` + `read_json`，`load()` 走它；KI-26：深拷贝默认值 |
| `pipeline/notices.py` | UPDATE | KI-21/22：损坏文件、摘要 / 问题兜底进警告栏 |
| `pipeline/classify.py` | UPDATE | KI-21：可选输入缺失给警告、损坏抛 `CorruptJSON` |
| `pipeline/questions.py` | UPDATE | KI-22：`reusable()`；KI-49：`normalize_answers()` |
| `pipeline/select.py` | UPDATE | KI-23：匹配不上的原话 / 话题 / 答案进 `warnings` |
| `pipeline/format_transcript.py` | UPDATE | KI-24 |
| `aicut.py` | UPDATE | 接线：`main()` 统一接损坏异常；ingest / build / scenes / quality / summary / questions / list；venv 失败带原因（净增 ≤ 25 行，逻辑都在 pipeline） |
| `gui/payloads.py` | CREATE | 从 `server.py` 原样搬出 `browse_payload` / `confirm_payload`（server.py 已 789 行），再在新位置改 KI-21/49 |
| `gui/server.py` | UPDATE | 委托 payloads；`/api/state` 等接 `CorruptJSON`→409；`/api/confirm/answers` 规整答案 |
| `gui/static/common.js` | UPDATE | KI-49：`asList()` |
| `gui/static/confirm.html` | UPDATE | KI-49：用 `asList()`，不原地改数组；答案读不出时提示 |
| `gui/static/index.html` | UPDATE | KI-21：`/api/state` 失败显示在警告栏 |
| `tests/test_junk_detect.py` | CREATE | KI-19/27 |
| `tests/test_format_transcript.py` | CREATE | KI-24 |
| `tests/test_m8_cli_failures.py` | CREATE | aicut 接线（KI-19/21/22/48/56/66） |
| `tests/test_server_corrupt.py` | CREATE | GUI 损坏文件（KI-21/49） |
| `tests/test_media_io.py` | UPDATE | 新函数 |
| `tests/test_understand_visual.py` | UPDATE | 假 runner / 假 Popen 失败用例 |
| `tests/test_schema.py` | UPDATE | KI-21/26 |
| `tests/test_llm.py` | UPDATE | KI-25 回归 |
| `tests/test_select.py` | UPDATE | KI-23 |
| `tests/test_questions.py` | UPDATE | KI-22/49 |
| `tests/test_classify.py` | UPDATE | KI-21 |
| `tests/test_frontend_js.py` / `tests/test_static_pages.py` | UPDATE | KI-49 / KI-21 前端 |
| `tests/test_server_target.py` | UPDATE | `test_state_survives_corrupt_scored_file` 改断言（行为按 KI-21 有意改变：仍 200，但警告栏要说出损坏） |
| `tests/test_aicut_build.py` | UPDATE | render_preview 失败原因可见 |

收尾（实现方在提交后按惯例做，不在本计划代码范围）：`docs/known-issues.md` 状态列、PRD 里程碑 8 状态。

## NOT Building

- 不把所有 pipeline 模块里的 `json.loads(...read_text())`（`summarize.run:96-97`、`questions.run:117-118`、`select.run:524-532`、`understand_*.run` 等）统一换成 `read_json`；这些是上一步刚写出的中间产物，损坏时 traceback 不是「静默当默认值」，不属于 KI-21。只换「缺失/损坏被当默认值」与登记点。
- 不给 ffmpeg 加超时 / 取消（KI-61，里程碑 9）；`sample_frames` 现有 `timeout` 参数未生效的问题照旧，不在本里程碑。
- 不做 JSON 写入的 `fsync` / 读改写锁（KI-51），不改 `classify` / `select` / `summarize` 的非原子 `write_text`。
- 不改错误文本的脱敏（KI-70）；LLM 错误本就只含 `error.message` 或长度摘要（`pipeline/llm.py:40-55`）。
- 不改 `must_lines` 的切分规则、必留话题关键词、答题规则语义（KI-03 / KI-04 / KI-07，里程碑 6）——KI-23 只「把匹配不上的说出来」。
- 不处理 KI-13/14/76 等预览渲染内容问题（里程碑 7）；`render_preview.py` 只改「怎么执行 ffmpeg」。
- 不新增 UI 组件：一律复用现有警告栏、页面错误位、toast。
- 不改 `/api/projects` 列表（损坏项目仍列出，点开后 409 说清楚）。

---

## Step-by-Step Tasks

> 每个 Task：先写测试并确认 RED（`uv run pytest <文件> -q` 看到预期失败），再实现到 GREEN，再跑全量。全量基线：`uv run pytest` = 987 passed。

### Task 1: KI-26 + KI-21 基础 —— `schema.read_json` / `CorruptJSON` / 深拷贝默认值
- **ACTION**: 在 `pipeline/schema.py` 增加读侧原语，`load()` 改用它；修 `default_project` / `migrate` 共享可变默认值。
- **TESTS FIRST**（`tests/test_schema.py` 追加）:
  - `test_default_project_does_not_share_mutable_defaults`：`a = default_project("a","/x"); a["calibration"]["tone"]="t"; a["brief"]["k"]=1; b = default_project("b","/y")` → `b["calibration"] == {}`、`b["brief"] == {}`、`schema.DEFAULTS["calibration"] == {}`。
  - `test_migrate_fills_defaults_with_fresh_copies`：`cfg, _ = migrate({"name":"n","material":"m","schema_version":2})`（缺 brief/calibration）→ `cfg["brief"] is not schema.DEFAULTS["brief"]`。
  - `test_read_json_missing_returns_default` / `test_read_json_missing_without_default_raises_file_not_found`。
  - `test_read_json_corrupt_raises_with_file_name`（写 `"{坏"`）→ `pytest.raises(schema.CorruptJSON, match="shots.json")`，且 `issubclass(schema.CorruptJSON, ValueError)`。
  - `test_read_json_wrong_top_level_type`（写 `[]`，`expect=dict`）→ `CorruptJSON`。
  - `test_read_json_bad_utf8`（写 `b"\xff\xfe"`）→ `CorruptJSON`。
  - `test_load_corrupt_project_raises_corrupt_json`：`schema.load(p)` 对 `"{坏"` 抛 `CorruptJSON`（原来是裸 `JSONDecodeError`；`JSONDecodeError` 也是 `ValueError`，现有 `except ValueError` 调用方不受影响）。
- **IMPLEMENT**:
  ```python
  import copy
  ...
  class CorruptJSON(ValueError):
      """JSON 文件读不出来或顶层类型不对：不能当成「没有」继续（KI-21）。"""

  CORRUPT_JSON_MSG = "{name} 损坏、读不出来（{detail}），程序没有用它继续：{path}"
  _MISSING = object()

  def read_json(path: Path, *, default: Any = _MISSING, expect: type | None = dict) -> Any:
      """缺失 → default（没给 default 抛 FileNotFoundError）；损坏 / 不是 UTF-8 / 顶层类型不对 → CorruptJSON。"""
      path = Path(path)
      try:
          text = path.read_text(encoding="utf-8")
      except FileNotFoundError:
          if default is _MISSING:
              raise
          return default
      except (OSError, UnicodeDecodeError) as exc:
          raise CorruptJSON(CORRUPT_JSON_MSG.format(name=path.name, detail=type(exc).__name__, path=path)) from exc
      try:
          data = json.loads(text)
      except json.JSONDecodeError as exc:
          raise CorruptJSON(CORRUPT_JSON_MSG.format(name=path.name, detail=f"第 {exc.lineno} 行 {exc.msg}", path=path)) from exc
      if expect is not None and not isinstance(data, expect):
          raise CorruptJSON(CORRUPT_JSON_MSG.format(name=path.name, detail=f"顶层应为{'对象' if expect is dict else expect.__name__}", path=path))
      return data
  ```
  - `default_project`：`cfg = {"name": name, "material": str(material), **copy.deepcopy(DEFAULTS)}`。
  - `migrate` 第 81-84 行：`out[key] = copy.deepcopy(value)`。
  - `load()`：`data = read_json(path)`；保留后面的 `if not isinstance(data, dict)` 删除（`expect=dict` 已覆盖），`migrate` 不变。
- **MIRROR**: ERROR_HANDLING（`review.OverridesCorrupt` 的文案结构）、REPOSITORY_PATTERN（与 `write_json` 并列）。
- **IMPORTS**: `import copy`（schema.py 顶部）。
- **GOTCHA**: `default=None` 是合法默认值，所以哨兵必须是 `_MISSING`；`detail` 不能带文件内容（可能是转写原文），只给行号 / 异常名。`SchemaTooNew` 不动（仍继承 `Exception`，KI-45 已按此修过路由）。
- **VALIDATE**: `uv run pytest tests/test_schema.py -q` 全绿；全量无回归。

### Task 2: KI-25 —— 只补回归测试（代码已修）
- **ACTION**: 在 `tests/test_llm.py` 末尾加「真实 `default_transport` + 打桩 `_open`」的用例，证明 `RemoteDisconnected` / `ConnectionResetError` / 200 非 JSON 都会重试并最终成功。
- **TESTS**（预期直接 GREEN；若 RED 说明回退，按失败修 `pipeline/llm.py:62-78`）:
  ```python
  class _Resp:
      def __init__(self, body): self.status, self._b = 200, body.encode()
      def read(self, n=-1): return self._b
      def __enter__(self): return self
      def __exit__(self, *a): return False

  @pytest.mark.parametrize("exc", [http.client.RemoteDisconnected("closed"), ConnectionResetError(54, "reset"),
                                   http.client.IncompleteRead(b"")])
  def test_default_transport_retries_dropped_connection(monkeypatch, exc):
      seq = [exc, _Resp(json.dumps({"choices": [{"message": {"content": '{"ok": 1}'}}]}))]
      def fake_open(req, timeout):
          item = seq.pop(0)
          if isinstance(item, BaseException):
              raise item
          return item
      monkeypatch.setattr(llm, "_open", fake_open)
      c = llm.DeepSeekClient(api_key="k", sleep=lambda _: None, transport=llm.default_transport)
      assert c.chat_json("s", "u") == {"ok": 1} and seq == []
  ```
  另加 `test_default_transport_200_html_then_json_retries`（第一次 `_Resp("<html>")`）。
- **MIRROR**: TEST_STRUCTURE（`tests/test_llm.py:82-91` 的 retry 计数断言）。
- **IMPORTS**: `import http.client`。
- **GOTCHA**: `safe_http.read_capped(resp)` 调 `resp.read(MAX+1)`，假响应的 `read` 要接受参数。
- **VALIDATE**: `uv run pytest tests/test_llm.py -q`。

### Task 3: KI-19 / KI-66 原语 —— `media_io.run_analysis` / `probe_duration` / `probe_material`
- **ACTION**: 在 `pipeline/media_io.py` 增加三个严格函数；`_probe_duration`（认领用，返回 0.0）保留不变。
- **TESTS FIRST**（`tests/test_media_io.py` 追加，全部用 `FakeProc` runner，不依赖 ffmpeg）:
  - `test_run_analysis_returns_stderr_log`：`FakeProc(0, err="silence_start: 1")` → 返回该文本；断言 argv 以 `["ffmpeg", "-hide_banner", "-nostats"]` 开头且**不含** `-loglevel`（filter 日志在 info 级）。
  - `test_run_analysis_nonzero_raises_with_tail`：`FakeProc(1, err="x"*2000 + "Invalid data found")` → `MediaError`，消息含 `"退出码 1"` 与 `"Invalid data found"`，长度受 `STDERR_TAIL` 约束。
  - `test_run_analysis_missing_binary`：runner 抛 `FileNotFoundError` → `MediaError("无法运行 ffmpeg…")`。
  - `test_run_analysis_timeout`：runner 抛 `subprocess.TimeoutExpired(cmd, 5)` → `MediaError`，消息含「秒」。
  - `test_probe_duration_strict_ok` / `test_probe_duration_strict_failures`（参数化：退出码 1 / stdout `""` / `"N/A"` / `"0"` / `"-1"`）→ 后者均 `MediaError`。
  - `test_probe_material_ok`：stdout `{"format":{"duration":"12.5"},"streams":[{"codec_type":"video"}]}` → `{"duration": 12.5, "streams": [...]}`。
  - `test_probe_material_unrecognized`（参数化：退出码 1 + stderr `"Invalid data found when processing input"` / stdout `""` / stdout `"{}"` / `{"format":{}}`）→ `MediaError`，消息含 `MATERIAL_UNREADABLE` 的固定前缀。
- **IMPLEMENT**:
  ```python
  ANALYSIS_BASE = ["ffmpeg", "-hide_banner", "-nostats"]  # 分析滤镜的结果在 info 级日志里，不能加 -loglevel error
  FFPROBE_MATERIAL = ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate",
                      "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
                      "-of", "json"]
  MATERIAL_UNREADABLE = "ffprobe 认不出这个文件（{detail}）：确认它是完整的视频文件、没有损坏、不是还在拷贝中"
  DURATION_UNREADABLE = "读不到时长：{name}（{detail}）"

  def _tail(text: str | None) -> str:
      return (text or "").strip()[-STDERR_TAIL:]

  def run_analysis(args: list[str], *, runner=subprocess.run, timeout: float | None = None) -> str:
      """ffmpeg 分析（blackdetect / scdet 等，输出到 null）；返回 stderr 日志。失败抛 MediaError（KI-19）。"""
      try:
          r = runner([*ANALYSIS_BASE, *args], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=timeout)
      except OSError as exc:
          raise MediaError(f"无法运行 ffmpeg：{exc}") from exc
      except subprocess.TimeoutExpired as exc:
          raise MediaError(f"ffmpeg 超过 {exc.timeout:.0f} 秒没有结束") from exc
      if r.returncode != 0:
          raise MediaError(f"ffmpeg 失败（退出码 {r.returncode}）：{_tail(r.stderr)}")
      return r.stderr or ""

  def probe_duration(path: Path, *, runner=subprocess.run) -> float:
      """严格版：读不出正时长抛 MediaError（带 ffprobe 原因）。认领旧产物仍用宽松的 _probe_duration。"""
      ...  # 复用 FFPROBE_DURATION；OSError / 非零 / 非数 / ≤0 → MediaError(DURATION_UNREADABLE.format(...))

  def probe_material(path: Path, *, runner=subprocess.run) -> dict:
      """素材台账用（KI-66）：→ {"duration": 秒(>0), "streams": [...]}；认不出抛 MediaError。"""
      ...  # 非零 → MATERIAL_UNREADABLE.format(detail=_tail(stderr) or f"退出码 {code}")
           # json 失败 / 没有 format / duration 非正 → 同一文案，detail 说明哪一项
  ```
  并把 `run_ffmpeg` 第 95 行改用 `_tail()`（行为不变）。
- **MIRROR**: ERROR_HANDLING（`run_ffmpeg`）。
- **IMPORTS**: 无新增（`subprocess`、`json` 已导入）。
- **GOTCHA**: `subprocess.TimeoutExpired` 不是 `OSError`，要单独接；`float("nan")` 可解析，判 `math.isfinite`（加 `import math`）。`probe_material` 只返回 `duration` / `streams`，`size` 仍由 `cmd_ingest` 用 `src.stat()` 取（与现在一致）。
- **VALIDATE**: `uv run pytest tests/test_media_io.py -q`。

### Task 4: KI-19 / KI-20 接线 —— understand_visual、render_preview、aicut 分析步骤
- **ACTION**:
  1. `pipeline/understand_visual.py`：`probe_duration` → `media_io.probe_duration`；`detect_cuts` → `media_io.run_analysis`；`sample_frames` 检查退出码、零帧报错；`analyze` 不再自抛 `ValueError`。
  2. `pipeline/render_preview.py:96-108`：ffmpeg 改由 `media_io.run_ffmpeg` 执行，失败 `sys.exit(f"预览渲染失败：{exc}")`。
  3. `pipeline/to_jianying.py:120-121`：删除无调用方的 `run()`。
  4. `aicut.py`：`cmd_scenes` / `cmd_quality` 接 `MediaError` → `die`；`ensure_jy_python` 建 venv 失败带 stderr。
- **TESTS FIRST**:
  - `tests/test_understand_visual.py`（不依赖 ffmpeg 的新用例放在**新文件段落**并用 `@pytest.mark.usefixtures()`，注意该文件顶部 `pytestmark` 是「需要 ffmpeg」→ 新增用例放到 `tests/test_m8_cli_failures.py` 里，避免被 skip）:
    - `test_detect_cuts_raises_when_ffmpeg_fails`：`monkeypatch.setattr(media_io, "run_analysis", 抛 MediaError)` → `pytest.raises(media_io.MediaError)`。
    - `test_sample_frames_nonzero_exit_raises`：假 `popen` 返回对象 `stdout=io.BytesIO(b"")`、`wait()→1`、`poll()→1` → `MediaError`。
    - `test_sample_frames_zero_frames_raises`：`wait()→0`、无数据 → `MediaError("…一帧画面也没读到")`。
    - `test_scenes_dies_with_reason` / `test_quality_dies_with_reason`：`project` fixture + 完整 proxy（`media_io.atomic_output` 写）+ 打桩 → `SystemExit`，stdout 含「镜头切分失败」/「画面质量分析失败」与 ffmpeg 原因；`work/shots_visual.json` / `visual_quality.json` 不存在。
    - `test_render_preview_failure_reason_visible`（放 `tests/test_aicut_build.py`）：timeline 只含 1 个 video、无 text；`monkeypatch.setattr(media_io, "run_ffmpeg", 抛 MediaError("ffmpeg 失败（退出码 1）：No such filter"))`；`monkeypatch.setattr(sys, "argv", [...])` 调 `render_preview.main()` → `SystemExit` 的 `code` 文本含「预览渲染失败」与「No such filter」。
    - `test_render_preview_uses_media_io`（静态）：`"subprocess.run(cmd, check=True)" not in render_preview.py`。
    - 现有 `tests/test_understand_visual.py` 的真 ffmpeg 用例必须继续绿（`analyze` / `sample_frames` 行为不变）。
- **IMPLEMENT**（要点）:
  ```python
  # pipeline/understand_visual.py
  from pipeline import media_io
  FRAMES_EMPTY = "抽帧失败：一帧画面也没读到"
  FRAMES_EXIT_WAIT_S = 30

  def probe_duration(path: Path) -> float:
      return media_io.probe_duration(path)   # 失败抛 MediaError（KI-19）

  def detect_cuts(video, *, threshold=8.0, timeout=1800) -> list[float]:
      log = media_io.run_analysis(["-i", str(video), "-vf", f"scdet=threshold={threshold}",
                                   "-an", "-f", "null", "-"], timeout=timeout)
      return sorted(float(x) for x in CUT_RE.findall(log))

  def sample_frames(video, *, fps=1.0, width=160, height=90, timeout=1800, popen=None):
      popen = popen or sp.Popen
      with tempfile.TemporaryFile() as err:          # stderr 不走 PIPE：避免和 stdout 互相堵塞
          proc = popen(cmd, stdout=sp.PIPE, stderr=err)
          code = None
          try:
              ... 现有循环不变 ...
              code = proc.wait(timeout=FRAMES_EXIT_WAIT_S)
          finally:
              if proc.poll() is None:
                  proc.kill()
                  proc.wait()
          if code != 0:
              err.seek(0)
              tail = err.read().decode("utf-8", "replace").strip()[-media_io.STDERR_TAIL:]
              raise media_io.MediaError(f"抽帧失败（退出码 {code}）：{tail}")
      if not out:
          raise media_io.MediaError(FRAMES_EMPTY)
      return out
  ```
  ```python
  # pipeline/render_preview.py（第 96-107 行）
  from pipeline import encode, media_io  # noqa: E402
  ...
      args_ff = []
      for s in segs:
          args_ff += ["-i", s["source"]]
      args_ff += ["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[ac]",
                  *encode.h264_args("preview"), "-c:a", "aac", "-b:a", "192k",
                  "-movflags", "+faststart", args.out]
      print(f"渲染 {n} 个镜头 → {args.out}")
      try:
          media_io.run_ffmpeg(args_ff)        # = ffmpeg -y -loglevel error <args>，与原命令一致
      except media_io.MediaError as exc:      # KI-20：打包版里 ffmpeg 的 stderr 进不了任务日志，必须放进退出文字
          sys.exit(f"预览渲染失败：{exc}")
  ```
  ```python
  # aicut.py cmd_scenes / cmd_quality
      try:
          res = understand_visual.run(proxy, work / "shots_visual.json",
                                      threshold=getattr(args, "threshold", 8.0))
      except media_io.MediaError as exc:
          die(f"镜头切分失败：{exc}")
  ...
      try:
          res = understand_visual.run_quality(proxy, segs, work / "visual_quality.json")
      except media_io.MediaError as exc:
          die(f"画面质量分析失败：{exc}")
  # aicut.py ensure_jy_python（第 136 行）
      r = run([sys.executable, "-m", "venv", str(JY_VENV)])
      if r.returncode != 0:
          die(f"创建 ~/.aicut/venv 失败：{(r.stderr or '')[-300:]}")
  ```
- **MIRROR**: ERROR_HANDLING（`cmd_transcribe` 的 try/die）。
- **IMPORTS**: understand_visual：`import tempfile`、`from pipeline import media_io`（模块顶部；该模块被 aicut 直接 import，不是脚本方式运行）。render_preview：沿用第 19-23 行的 `sys.path.append(ROOT)` 机制。
- **GOTCHA**:
  - `tests/test_encode.py:48-49` 要求 `render_preview.py` 里仍出现 `encode.h264_args(`——保留。
  - `render_preview` 原命令以 `["ffmpeg", "-y", "-loglevel", "error"]` 开头，正好等于 `media_io.FFMPEG_BASE`，所以 `args_ff` 不能再带这四项。
  - `run_quality` 里 `segments.json` 读失败不在本 Task 范围。
  - `sample_frames` 正常读到 EOF 后先 `wait()` 再判 `poll()`，否则 `finally` 的 `kill()` 会把正常退出的进程记成 -9。
- **VALIDATE**: `uv run pytest tests/test_understand_visual.py tests/test_m8_cli_failures.py tests/test_aicut_build.py tests/test_encode.py -q`。

### Task 5: KI-19 / KI-27 —— 废片检测
- **ACTION**: 重写 `pipeline/junk_detect.py` 的 `detect` / `main` 局部，`judge` 不变。
- **TESTS FIRST**（新建 `tests/test_junk_detect.py`，用固定日志文本，不跑 ffmpeg）:
  ```python
  LOG = """  Duration: 00:00:20.00, start: 0.000000, bitrate: 1 kb/s
  [silencedetect @ 0x1] silence_start: -0.02
  [silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 4.02
  [freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 15.0
  [silencedetect @ 0x1] silence_start: 14.5
  [scdet @ 0x3] lavfi.scd.score: 30.1, lavfi.scd.time: 8.5
  [blackdetect @ 0x4] black_start:2.0 black_end:3.5 black_duration:1.5
  """
  ```
  - `test_unclosed_tail_intervals_closed_at_duration`：`detect(..., runner=fake(0, LOG))` → 含 `(15.0, 20.0, "freeze")` 与 `(14.5, 20.0, "silence")`。
  - `test_negative_silence_start_clamped`：首段静音起点 `0.0`。
  - `test_scenes_returned_when_requested`：`scenes == [8.5]`；`scene=False` 时为 `[]`。
  - `test_detect_raises_on_ffmpeg_failure`：runner 退出码 1 → `media_io.MediaError`。
  - `test_union_seconds_counts_overlap_once`：`[{"start":2,"end":3.5,"suggest":"删"},{"start":3,"end":4,"suggest":"删"},{"start":10,"end":12,"suggest":"参考"}]` → `2.0`。
  - `test_main_exits_with_reason_on_failure` / `test_main_exits_when_duration_unknown`：`monkeypatch.setattr(junk_detect, "detect", ...)`，`sys.argv` 打桩 → `SystemExit` 文本含「废片检测失败」/「读不到」，且未写出 `junk_report.json`。
  - `test_main_writes_scenes`：`--scene` → `junk_report.json` 含 `"scenes": [8.5]`；百分比用去重后的秒数。
- **IMPLEMENT**:
  ```python
  ROOT = Path(__file__).resolve().parent.parent
  if str(ROOT) not in sys.path:
      sys.path.append(str(ROOT))  # 脚本方式运行时可导入 pipeline（同 render_preview.py:19-21）
  from pipeline import media_io  # noqa: E402
  JUNK_FAILED = "废片检测失败：{reason}"
  DURATION_UNKNOWN = "读不到 {name} 的时长"

  def detect(media, silence_db, freeze_sec, black_sec, scene, *, runner=subprocess.run
             ) -> tuple[list, float, list[float]]:
      ...vf / af 不变...
      log = media_io.run_analysis(["-i", str(media), "-vf", vf, "-af", af, "-f", "null", "-"],
                                  runner=runner)               # KI-19：非零退出抛 MediaError
      duration = _duration(log)                                 # 先解析时长：收尾闭合要用
      ...
      def pair(open_kind, close_kind, name):
          opens, items = [], []
          for start, _end, kind in sorted(raw, key=lambda x: x[0]):
              if kind == open_kind:
                  opens.append(max(0.0, start))
              elif kind == close_kind and opens:
                  items.append((opens.pop(0), start, name))
          # KI-27：文件末尾没等到 *_end 的区间，以时长收尾
          items += [(s, duration, name) for s in opens if duration > s]
          return items
      ...
      scenes = [float(x) for x in RE_SCENE.findall(log)] if scene else []
      return merge(intervals), duration, scenes

  def union_seconds(rows: list[dict], action: str = "删") -> float:
      """KI-27：同一时间段被黑场 + 静音同时命中只算一次。"""
      spans = sorted((r["start"], r["end"]) for r in rows if r["suggest"] == action)
      total, cur_s, cur_e = 0.0, None, None
      ...  # 标准区间合并
      return round(total, 3)
  ```
  `main()`：`try: intervals, duration, scenes = detect(...) except media_io.MediaError as exc: sys.exit(JUNK_FAILED.format(reason=exc))`；`if duration <= 0: sys.exit(JUNK_FAILED.format(reason=DURATION_UNKNOWN.format(name=media.name)))`；JSON 增加 `"scenes": scenes`（仅 `--scene` 时非空）；`total = union_seconds(rows)`。
- **MIRROR**: NAMING_CONVENTION、`format_transcript.py:99-100` 的 `sys.exit("中文")`。
- **IMPORTS**: 如上。
- **GOTCHA**:
  - **`junk_detect` 以脚本方式（`python pipeline/junk_detect.py`）运行时 `sys.path[0]` 是 `pipeline/`**：`import subprocess` 会间接 `import select`，可能被 `pipeline/select.py` 遮蔽——这是 KI-15（里程碑 7）。本 Task 只用 `append` 不用 `insert(0, …)`，不加重该问题；**不要**在本里程碑改 KI-15。
  - `run_analysis` 不带 `-loglevel`，info 级日志对 1 小时素材可达数 MB，与原来 `capture_output` 一致，不新增风险。
  - `merge()` 原地 `sort` 入参（第 48 行）——不改，范围外。
- **VALIDATE**: `uv run pytest tests/test_junk_detect.py -q`。

### Task 6: KI-24 —— 转写时间码
- **ACTION**: 修 `pipeline/format_transcript.py` 的 `tc` / `load_subs` / `build_segments` / `main`。
- **TESTS FIRST**（新建 `tests/test_format_transcript.py`）:
  - 参数化 `test_tc_rounds_before_carry`：`59.999→"01:00.00"`、`0→"00:00.00"`、`61.234→"01:01.23"`、`-1→"00:00.00"`、`119.995→"02:00.00"`。
  - `test_subs_missing_time_are_dropped_and_counted`：`load_subs` 输入含缺 `start_time`、`end_time:"abc"`、`end<start` 各一条 + 1 条正常 → 返回 1 条，`dropped == 3`。
  - `test_contained_sentence_does_not_move_end_backwards`：`[(0,10,"A"),(2,3,"A")]` → 段 `end == 10`、`duration == 10`。
  - `test_main_warns_dropped` / `test_main_exits_when_all_dropped`：写 raw json，`sys.argv` 打桩；前者 stdout 含 `"3 句缺少有效时间码"`，后者 `SystemExit` 文本含「没有可用的时间码」。
- **IMPLEMENT**:
  ```python
  SUBS_DROPPED_WARNING = "[!] {n} 句缺少有效时间码，已跳过（检查 ASR 返回结构）"
  NO_TIMED_SUBS = "所有句子都没有可用的时间码，检查 ASR 返回结构"

  def tc(sec: float) -> str:
      cs = int(round(max(0.0, sec) * 100))     # 先按显示精度取整再进位：59.999 → 01:00.00（KI-24）
      m, cs = divmod(cs, 6000)
      return f"{m:02d}:{cs // 100:02d}.{cs % 100:02d}"

  def _time(raw) -> float | None:
      if isinstance(raw, bool):
          return None
      try:
          value = float(raw)
      except (TypeError, ValueError):
          return None
      return value if math.isfinite(value) and value >= 0 else None

  def load_subs(path) -> tuple[list[dict], float, int]:   # 第三项：丢弃条数
      ...
      start, end = _time(s.get("start_time")), _time(s.get("end_time"))
      if start is None or end is None or end < start:
          dropped += 1
          continue
  ...
  # build_segments 第 80 行
          cur["end"] = max(cur["end"], s["end"])   # 包含句不能让段尾回退（KI-24）
  ```
  `main()`：`subs, duration, dropped = load_subs(...)`；`dropped` 且 `subs` 非空 → `print(SUBS_DROPPED_WARNING...)`；`subs` 为空且 `dropped` → `sys.exit(NO_TIMED_SUBS)`；原「没有解析到字幕」分支保留。
- **MIRROR**: NAMING_CONVENTION；`schema._shot_time`（`pipeline/schema.py:190-200`）的数值校验写法。
- **IMPORTS**: `import math`。
- **GOTCHA**: `load_subs` 返回值从 2 元组变 3 元组——全仓只有 `main()` 调用（已 grep 确认），无其它调用方；`tc` 的 `m` 超过 99 分钟时宽度自然变 3 位，与原行为一致。`{n}` 文案前缀 `[!]` 与 aicut `warn()` 一致，`_run_pipeline` 成功时不打印子进程输出——这条警告只在 CLI 直接运行与日志里可见；**是否要让 aicut 转述它见 Notes「需用户决策 4」**（默认：不转述）。
- **VALIDATE**: `uv run pytest tests/test_format_transcript.py -q`。

### Task 7: KI-23 —— 选段把「匹配不上」说出来
- **ACTION**: `pipeline/select.py` 三处静默跳过改为收集警告，进 `result["warnings"]`（自动进入 selection.json → 警告栏 + `_report_selection` 的 `warn`）。
- **TESTS FIRST**（`tests/test_select.py` 追加）:
  - `test_unmatched_must_line_warned`：`rules={"must_lines": ["不存在的原话"]}` → `any("不存在的原话" in w and "找不到" in w for w in res["warnings"])`。
  - `test_too_short_must_line_warned`：唯一命中句时长 1.0（< `MIN_SHOT`）→ 警告含「不足」。
  - `test_matched_must_line_no_warning`：命中且够长 → 无该类警告（且镜头进片）。
  - `test_unmatched_must_topic_warned`：`rules={"must_topics": ["完全无关的内容"]}` → 警告含该词；`["讲合同"]` 无警告。
  - `test_unknown_answer_label_reported`：`select._rules({"q1": "旧选项"}, questions)` → `rules["ignored_answers"] == ["旧选项"]`；空串 / `None` 不计入。
  - `test_ignored_answers_become_warnings`：`select.select(..., {"ignored_answers": ["旧选项"]}, ...)` → 警告含「旧选项」。
  - 现有 `test_rules_from_question_answers` 不改（只断言 `must_topics` / `ending`）。
- **IMPLEMENT**:
  ```python
  MUST_LINE_UNMATCHED = "指定必须保留的原话「{line}」在转写里找不到，没能进片：检查是否和原话一字不差"
  MUST_LINE_TOO_SHORT = "指定必须保留的原话「{line}」所在的句子不足 {min} 秒，没能单独成镜"
  MUST_TOPIC_UNMATCHED = "必留话题「{topic}」对不上任何话题，已忽略"
  ANSWER_UNMATCHED = "答案「{label}」不在当前的决策问题里（问题可能已重新生成），已忽略：请到「确认与提问」重新作答"
  ```
  - `_rules`：`if not rule: if isinstance(v, str) and v: ignored.append(v); continue`；末尾 `rules["ignored_answers"] = ignored`。
  - `_force_lines` 返回 `(shots, problems)`：`hits = [seg for seg in segments if line in text]`；无命中 → `MUST_LINE_UNMATCHED`；有命中但全部 `< MIN_SHOT` 且都未入选 → `MUST_LINE_TOO_SHORT`；已在 `used` 里的命中算成功（不报）。
  - `select()`：开头 `unmatched = [str(v) for v in rules.get("must_topics") or [] if not _best_topic(str(v), names)]`；第 415 行改 `shots, line_problems = _force_lines(...)`；返回前 `warnings = [*report["warnings"], *[MUST_TOPIC_UNMATCHED.format(topic=t) for t in unmatched], *line_problems, *[ANSWER_UNMATCHED.format(label=x) for x in rules.get("ignored_answers") or []]]`，`return {**report, "warnings": warnings, ...}`（注意 `**report` 在前、`warnings` 覆盖在后）。
- **MIRROR**: NAMING_CONVENTION（`select.py:27-33`）。
- **IMPORTS**: 无。
- **GOTCHA**: `line in text` 的匹配语义（逐字、按逗号切分）不改——那是 KI-03（里程碑 6）。`stored_rules`（`brief_answers.json` 里旧版本存的规则）没有 `ignored_answers` 键 → `.get(...) or []`，不报错。`run()` 第 553 行的 `extra_warnings` 拼接保持在后。
- **VALIDATE**: `uv run pytest tests/test_select.py tests/test_aicut_must_keep.py -q`。

### Task 8: KI-22 —— LLM 兜底不固化、原因可见
- **ACTION**: `pipeline/questions.py` 加 `reusable()`；`pipeline/notices.py` 加兜底提示；`aicut.cmd_summary` / `cmd_questions` 打印原因、按新规则决定是否复用。
- **TESTS FIRST**:
  - `tests/test_questions.py`：
    - `test_reusable_ai_questions`：`{"fallback": False, "questions": [...]}` → `True`。
    - `test_fallback_without_answers_not_reusable`：`fallback: True` 且无 `brief_answers.json` → `False`。
    - `test_fallback_with_answers_kept`：存在 `brief_answers.json`（`{"answers": {"q1": "群像"}}`）→ `True`。
    - `test_corrupt_questions_not_reusable`：`"{坏"` → `False`（不抛）。
  - `tests/test_m8_cli_failures.py`：
    - `test_questions_regenerates_cached_fallback`：放置兜底 `questions.json`、无答案；`monkeypatch.setattr(aicut.questions, "run", 记录调用并返回 {"questions": [...3 个...], "fallback": False})`；`consented` fixture → `cmd_questions` 调用了 `run`。
    - `test_questions_keeps_answered_fallback_and_warns`：有答案 → 不调用 `run`，stdout 含「兜底」。
    - `test_summary_fallback_prints_reason`：`monkeypatch.setattr(aicut.summarize, "run", lambda *a, **k: {"summary": "s", "fallback": True, "error": "HTTP 402: Insufficient Balance"})` → stdout 含 `"[!]"` 与 `"HTTP 402"`。
  - `tests/test_server_corrupt.py`：
    - `test_state_warns_summary_and_questions_fallback`：`work/content_summary.json` = `{"fallback": true, "error": "超时"}`、`work/questions.json` = `{"fallback": true, "questions": []}` → `/api/state` 的 `warnings` 同时含「内容摘要」「决策问题」「超时」。
- **IMPLEMENT**:
  ```python
  # pipeline/notices.py
  SUMMARY_FALLBACK_NOTICE = "内容摘要是兜底生成的（AI 调用失败：{error}）：重新点「① 处理素材」会再试"
  QUESTIONS_FALLBACK_NOTICE = "决策问题是兜底模板生成的（AI 调用失败：{error}）：还没作答时重新点「① 处理素材」会重新生成"
  UNKNOWN_REASON = "原因未记录"

  def _fallback_reason(data: dict) -> str:
      return str(data.get("error") or UNKNOWN_REASON)
  ...
  # project_warnings() 末尾追加（顺序：标注 → 分档 → 选段 → 兜底 → 损坏文件(Task 9)）
      for name, notice in (("content_summary.json", SUMMARY_FALLBACK_NOTICE),
                           ("questions.json", QUESTIONS_FALLBACK_NOTICE)):
          data = _read(workdir / name)
          if data.get("fallback"):
              out.append(notice.format(error=_fallback_reason(data)))
  ```
  ```python
  # pipeline/questions.py
  ANSWERS_FILE = "brief_answers.json"

  def reusable(out_path: Path) -> bool:
      """已有决策问题能否直接复用（KI-22）：AI 生成的复用；兜底的只在剪辑师已作答时保留（换题会让答案失效）；读不出来的重新生成。"""
      try:
          data = schema.read_json(out_path, default=None)
      except schema.CorruptJSON:
          return False
      if not data:
          return False
      return not data.get("fallback") or (Path(out_path).parent / ANSWERS_FILE).exists()
  ```
  ```python
  # aicut.py cmd_questions（第 391-398 行）
      out = work / "questions.json"
      if out.exists() and not getattr(args, "force", False) and questions.reusable(out):
          info("决策问题已存在，跳过（--force 可重新生成，但会让已保存答案失效）")
          return
      require_consent()
      res = questions.run(summary, scored, out)
      if res["fallback"]:
          warn(notices.QUESTIONS_FALLBACK_NOTICE.format(error=res.get("error") or notices.UNKNOWN_REASON))
      ok(f"决策问题 {len(res['questions'])} 个")
  # aicut.py cmd_summary（第 380-381 行）
      res = summarize.run(text, scored, work / "content_summary.json", style=pref)
      if res["fallback"]:
          warn(notices.SUMMARY_FALLBACK_NOTICE.format(error=res.get("error") or notices.UNKNOWN_REASON))
      ok(res["summary"])
  ```
  已作答的兜底被保留时：`warn(notices.QUESTIONS_FALLBACK_NOTICE.format(...))` 再 `info(跳过)`（读一次 `out`，用 `notices._read` 风格的宽松读取即可；或让 `reusable` 只判断，这里另读）。
- **MIRROR**: `notices.py:29-41` 的追加风格；LOGGING_PATTERN。
- **IMPORTS**: questions.py：`from pipeline import schema`；aicut.py：`from pipeline import notices`（加到第 34-36 行的 import 列表）。
- **GOTCHA**: `questions.run` / `summarize.run` 的兜底逻辑本身**不改**（仍兜底、仍写文件）——用户要的是「看得见」，不是「失败就停」。`notices` 已在 `gui/server.py:34` 导入，不会产生循环导入（`notices` 只依赖 `understand_text`）。
- **VALIDATE**: `uv run pytest tests/test_questions.py tests/test_m8_cli_failures.py tests/test_server_corrupt.py -q`。

### Task 9: KI-21 / KI-48 / KI-56 / KI-66 —— aicut 接线
- **ACTION**:
  1. `aicut.load_json` 改用 `schema.read_json`（缺失→默认、损坏→`CorruptJSON`）。
  2. `aicut.main()` 统一把 `CorruptJSON` / `OverridesCorrupt` 变成 `die()`（覆盖 select / prepare / build / score 等所有命令，KI-56）。
  3. `cmd_ingest` 用 `media_io.probe_material`（KI-66 / KI-19）。
  4. `cmd_build`：分镜表结构校验（KI-48）；预设缺失明确报错（KI-21）。
  5. `cmd_list`：单个项目坏了不影响列表。
  6. `classify.run`：给了路径但文件不存在 → 警告；损坏 → `CorruptJSON`。
- **TESTS FIRST**（`tests/test_m8_cli_failures.py`，`project` fixture 同 `tests/test_aicut_build.py:33-39`）:
  - `test_ingest_unrecognized_material_dies_without_traceback`：素材文件写 `b"not a video"`，`monkeypatch.setattr(media_io, "probe_material", 抛 MediaError(MATERIAL_UNREADABLE...))` → `SystemExit`，stdout 含「素材读不出来」，不含 `Traceback` / `KeyError`；`work/materials.json` 不存在。
  - `test_ingest_missing_material_dies`：素材路径不存在 → 「原片不存在」。
  - `test_ingest_records_probe_result`：打桩返回 `{"duration": 60.0, "streams": []}` → `materials.json` 的 `duration == 60.0`。
  - 参数化 `test_build_rejects_bad_shots_file`：`shots.json` 内容为 `{}` / `{"shots": {}}` / `{"shots": [{"id": "sh01", "in": 5, "out": 1}]}` / `"{坏"` / `[]` → `aicut.main(["build", "p", "--no-draft"])` → `SystemExit`，stdout 含「分镜表」或「shots.json」，不含 `Traceback`；`ensure_clips` 打桩为 `_fail`（见 `tests/test_aicut_guards.py:11-12`）。
  - `test_build_missing_preset_dies`：`project.json` 的 `preset` 指向不存在的预设 → 「找不到预设」。
  - `test_select_corrupt_overrides_dies_with_message`（KI-56）：`work/segments_scored.json` 合法、`work/overrides.json` = `"{坏"` → `aicut.run_cli(["select", "p"]) == 1`，stdout 含「人工裁决文件损坏」，**不含** `Traceback`。
  - `test_corrupt_project_json_dies_with_file_name`：`project.json` = `"{坏"` → `aicut.run_cli(["status", "p"]) == 1`，stdout 含 `project.json` 与「损坏」。
  - `test_list_skips_corrupt_project`：两个项目，其一 `project.json` 损坏 → `cmd_list` 不抛，输出含另一项目名与「损坏」。
  - `tests/test_classify.py`：`test_run_warns_when_audio_file_missing`（`classify.run(tp, tmp_path/"none.json", out)` → `warnings` 含「声音特征」）；`test_run_corrupt_audio_raises_corrupt_json`；`audio_path=None` 时无该警告（现有用例已覆盖）。
- **IMPLEMENT**:
  ```python
  # aicut.py
  INGEST_FAILED = "素材读不出来：{reason}"
  SHOTS_INVALID = "分镜表 {name} 不能用：{detail}"
  PRESET_MISSING = "找不到预设 {preset}（presets/{preset}.json），换一个预设或把文件放回去"
  LIST_CORRUPT = "（project.json 损坏）"

  def load_json(p: Path, default=None):
      return schema.read_json(p, default=default)   # 损坏抛 CorruptJSON，由 main() 统一变成人话（KI-21）

  def load_preset(name: str) -> dict:
      preset = load_json(PRESETS / f"{name}.json")
      if preset is None:
          die(PRESET_MISSING.format(preset=name))
      return preset

  def cmd_ingest(args) -> None:
      pdir = project_dir(args.name)
      src = Path(cfg(pdir)["material"])
      if not src.is_file():
          die(f"原片不存在：{src}")
      try:
          probed = media_io.probe_material(src)
      except media_io.MediaError as exc:
          die(INGEST_FAILED.format(reason=exc))
      entry = {"path": str(src), "name": src.name, "size": src.stat().st_size, **probed}
      ...

  # cmd_build（第 612、621-622 行）
      preset = load_preset(c["preset"])
      ...
      spec = load_json(shots_file)
      try:
          shots = schema.clean_shots(spec.get("shots"))   # KI-48：缺键 / 非列表 / 入出点不对都在切片前拒绝
      except ValueError as exc:
          die(SHOTS_INVALID.format(name=shots_file.name, detail=exc))

  # main() 末尾
      args = ap.parse_args(argv)
      try:
          args.fn(args)
      except (schema.CorruptJSON, review.OverridesCorrupt) as exc:  # KI-21 / KI-56：损坏文件给人话，不给 traceback
          die(str(exc))

  # cmd_list
      for p in sorted(PROJECTS.glob("*/project.json")):
          try:
              c = load_json(p)
          except schema.CorruptJSON:
              print(f"{p.parent.name:28s} {LIST_CORRUPT}")
              continue
  ```
  `cmd_brief`（第 467 行）同样改 `load_preset(c["preset"])`。
  ```python
  # pipeline/classify.py run()（第 227-233 行）
  AUDIO_MISSING_WARNING = "没有声音特征（segments_audio.json）：本次分档没用上音量 / 语速 / 抢话，重新点「① 处理素材」可补上"
  VISUAL_MISSING_WARNING = "没有画面质量结果（visual_quality.json）：本次分档没有识别过暗画面"
  ...
      missing = []
      audio_by_id: dict[str, dict] = {}
      if audio_path:
          audio = schema.read_json(audio_path, default=None)
          if audio is None:
              missing.append(AUDIO_MISSING_WARNING)
          else:
              audio_by_id = {s["id"]: s.get("signals", {}) for s in audio["segments"]}
      visual_by_id: dict[str, dict] = {}
      if visual_path:
          visual = schema.read_json(visual_path, default=None)
          if visual is None:
              missing.append(VISUAL_MISSING_WARNING)
          else:
              visual_by_id = visual["segments"]
      ...
      result = {**result, "warnings": [*missing, *result["warnings"]]}   # 与 legacy 警告合并处理
  ```
- **MIRROR**: ERROR_HANDLING；`check_or_die`（`aicut.py:98-103`）。
- **IMPORTS**: classify.py：`from pipeline import schema`（确认无循环：schema 不导入 classify）。
- **GOTCHA**:
  - **`schema.clean_shots` 会把 `in/out` 规整成 3 位小数的 float 并丢掉多余字段**：手写 `shots.json` 里的整数入出点（`0` vs `0.0`）会让 `clip_key`（`aicut.py:491-494`）变化 → 这类镜头**重切一次**。选段结果（`select.to_shot_list`）与 GUI 保存（`/api/shots` 已 `clean_shots`）不受影响。在 Risks 里登记。
  - `spec` 不是 dict 的情况已由 `read_json(expect=dict)` 抛 `CorruptJSON` 覆盖，所以 `spec.get` 安全。
  - `die()` 在 `except` 块里抛 `SystemExit`，`run_cli`（`aicut.py:838-849`）按 `proc.exit_code` 返回 1，GUI 任务日志里是 `[x] …`。
  - `cmd_new` 第 177 行的 `load_json(PRESETS…)` 保持「缺失→列出可用预设」的现有提示，不换成 `load_preset`。
  - 现有测试 `tests/test_aicut_guards.py:15-22` 的 `_make_project` 没有 `preset` 字段 → `cfg()` 经 `migrate` 补成「纪实3min」，仓库 `presets/纪实3min.json` 存在，`load_preset` 不会 die；跑一遍确认。
- **VALIDATE**: `uv run pytest tests/test_m8_cli_failures.py tests/test_aicut_*.py tests/test_classify.py -q`。

### Task 10: KI-21 / KI-49 —— 剪辑台读路径
- **ACTION**:
  1. **先做纯搬家（行为不变，全量绿后再改）**：新建 `gui/payloads.py`，把 `gui/server.py:171-238` 的 `browse_payload` / `confirm_payload` 原样搬过去，签名改为接 `pdir`（避免反向 import server）；server 里 `/api/browse` / `/api/confirm` 改调 `payloads.browse(project_path(name), name)` / `payloads.confirm(project_path(name))`。
  2. `project_state`：`project.json` 用 `schema.read_json(..., default=None)`；损坏 → `CorruptJSON` → 路由 409（不再是「项目不存在」）。
  3. `notices.project_warnings` 增加「损坏文件」清单（自动进入 `/api/state` 的 `warnings`，server 不用改这一处）。
  4. `payloads.browse`：三档判定损坏 → `CorruptJSON`（409），缺失仍 404「还没有三档判定」。
  5. `payloads.confirm`：决策问题损坏 → 409；答案文件损坏 → 当空答案并带 `answers_unreadable: true`；答案经 `questions.normalize_answers` 规整。
  6. `/api/confirm/answers`：先 `normalize_answers` 再 `_rules`。
  7. 前端：`common.js` 加 `asList`；`confirm.html` 用它且不原地改数组、显示「答案读不出来」；`index.html` 的 `selectProject` 接住 `/api/state` 失败。
- **TESTS FIRST**（新建 `tests/test_server_corrupt.py`，用 `gui_server` / `call` / `make_project`）:
  - `test_state_corrupt_project_json_is_409_not_404`：`make_project` 后把 `project.json` 覆盖为 `"{坏"` → 409，`error` 含 `project.json` 与「损坏」。
  - `test_state_lists_corrupt_files_in_warnings`：`shots.json`=`"{坏"`、`work/segments.json`=`"[]"`（顶层类型错）→ 200，`warnings` 含「分镜表」「分段文稿」；`shots` 字段仍可用（来自 `shots-selected.json` 或空）。
  - `test_browse_corrupt_scored_is_409`：`work/segments_scored.json`=`"{坏"` → 409，`error` 不含「还没有三档判定」；缺失时仍 404。
  - `test_confirm_corrupt_questions_is_409`；`test_confirm_corrupt_answers_reported`：`brief_answers.json`=`"[1]"` → 200，`answers == {}`、`answers_unreadable is True`。
  - `test_confirm_multi_answer_coerced_to_list`（KI-49）：questions 中 `q2` 为 multi，磁盘答案 `{"q2": "合同条款", "q1": ["a"]}`（q1 是 single）→ GET 返回 `{"q2": ["合同条款"]}`（q1 非字符串被丢）。
  - `test_confirm_answers_post_normalized`：POST `answers={"q2": "合同条款"}` → 磁盘 `brief_answers.json` 的 `answers.q2 == ["合同条款"]` 且 `rules.must_topics` 正确。
  - `tests/test_questions.py`：`test_normalize_answers_*` 参数化（非 dict → `{}`；multi: str→[str]、list 过滤非 str / 空串、其它→[]；single: 非 str 丢弃；未知 id 丢弃）。
  - `tests/test_frontend_js.py`：`test_as_list`：`asList(["a"])→["a"]`、`asList("a")→["a"]`、`asList(null)→[]`、`asList({})→[]`、`asList(3)→[]`。
  - `tests/test_static_pages.py`：`test_confirm_uses_as_list`（`confirm.html` 含 `asList(` 且不含 `(chosen||[]).includes`）；`test_index_shows_state_load_error`（`index.html` 的 `selectProject` 段落含 `catch` 与 `renderWarnbar(`）。
  - **更新** `tests/test_server_target.py:184-187` `test_state_survives_corrupt_scored_file`：仍断言 `status == 200`，把 `warnings == []` 改成「`warnings` 恰好 1 条且含『三档判定』」（KI-21 的有意行为变化）。
- **IMPLEMENT**:
  ```python
  # pipeline/notices.py
  from pipeline import schema, understand_text
  CORRUPT_FILE_NOTICE = "{label}（{rel}）损坏、读不出来，界面上按「没有」显示：重新点「① 处理素材」会重建"
  CORRUPT_SHOTS_NOTICE = "分镜表（shots.json）损坏、读不出来，界面上显示的是自动选段结果：在「分镜表」里重新保存会覆盖它"
  WATCHED_FILES = (("work/shots-selected.json", "自动选段的分镜表"), ("work/selection.json", "选段结果"),
                   ("work/segments.json", "分段文稿"), ("work/segments_scored.json", "三档判定"),
                   ("work/junk_report.json", "废片表"), ("work/materials.json", "素材台账"),
                   ("work/content_summary.json", "内容摘要"), ("work/questions.json", "决策问题"),
                   ("work/brief_answers.json", "决策答案"))

  def _corrupt(path: Path) -> bool:
      try:
          schema.read_json(path, default=None)
      except schema.CorruptJSON:
          return True
      return False

  def corrupt_files(pdir: Path) -> list[str]:
      """KI-21：读得到但读不懂的文件逐个点名；不存在的不算。"""
      pdir = Path(pdir)
      out = [CORRUPT_SHOTS_NOTICE] if _corrupt(pdir / "shots.json") else []
      out += [CORRUPT_FILE_NOTICE.format(label=label, rel=rel)
              for rel, label in WATCHED_FILES if _corrupt(pdir / rel)]
      out += [CORRUPT_FILE_NOTICE.format(label=f"{d.parent.name} 的时间线", rel=f"output/{d.parent.name}/timeline.json")
              for d in sorted(pdir.glob("output/v*/timeline.json")) if _corrupt(d)]
      return out
  # project_warnings(workdir) 末尾：out += corrupt_files(Path(workdir).parent)
  ```
  ```python
  # pipeline/questions.py
  def normalize_answers(qs: dict | None, answers) -> dict:
      """磁盘 / 请求里的答案 → {问题 id: str | list[str]}：多选必为列表、单选必为文字，对不上问题的丢掉（KI-49）。"""
      if not isinstance(answers, dict):
          return {}
      out: dict = {}
      for q in (qs or {}).get("questions") or []:
          qid, value = q.get("id"), answers.get(q.get("id"))
          if q.get("type") == "multi":
              values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
              out[qid] = [v for v in values if isinstance(v, str) and v]
          elif isinstance(value, str) and value:
              out[qid] = value
      return out
  ```
  ```python
  # gui/payloads.py（搬家后修改的关键处）
  """剪辑台 · 浏览素材 / 确认与提问 两页的数据（从 server.py 拆出，KI-21 / KI-49）。

  读不出来的文件不能当「没有」：主数据损坏抛 schema.CorruptJSON，由 server 路由回 409。
  """
  NO_SCORED_MSG = "还没有三档判定，先跑 analyze/text/score"
  NO_QUESTIONS_MSG = "还没有决策问题，先跑 questions"

  def browse(pdir: Path, name: str) -> dict:
      ...
      scored = schema.read_json(work / "segments_scored.json", default=None)  # 损坏 → CorruptJSON
      if not scored:
          raise FileNotFoundError(NO_SCORED_MSG)
      ...

  def confirm(pdir: Path) -> dict:
      work = pdir / "work"
      q = schema.read_json(work / "questions.json", default=None)
      if q is None:
          raise FileNotFoundError(NO_QUESTIONS_MSG)
      summary = notices_read(work / "content_summary.json")  # 显示用，坏了当空（已在警告栏点名）
      try:
          stored = schema.read_json(work / "brief_answers.json", default={})
          unreadable = False
      except schema.CorruptJSON:
          stored, unreadable = {}, True
      return {"questions": q["questions"], "fallback": q.get("fallback", False), "summary": summary,
              "answers": questions.normalize_answers(q, stored.get("answers")),
              "confirmed": stored.get("confirmed", False), "answers_unreadable": unreadable}
  ```
  ```python
  # gui/server.py
  from gui import jobs, payloads, settings, support
  ...
  def project_state(name: str) -> dict:
      pdir = project_path(name)
      cfg = schema.read_json(pdir / "project.json", default=None)   # 损坏 → CorruptJSON → 409（KI-21）
      if not cfg:
          raise FileNotFoundError(name)
  ...
  # /api/state、/api/browse、/api/confirm 三处：在 `except ValueError` 之前加
              except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
                  return self._json({"error": str(exc)}, 409)
  # /api/confirm/answers
              try:
                  questions_def = schema.read_json(work / "questions.json", default=None)
              except schema.CorruptJSON as exc:
                  return self._json({"error": str(exc)}, 409)
              answers = questions.normalize_answers(questions_def, body.get("answers"))
              rules = select._rules(answers, questions_def)
  ```
  ```javascript
  // gui/static/common.js（IIFE 内，紧跟 window.num）
  // 磁盘上的答案可能是旧版本 / 手改的：多选值统一成数组再用（KI-49）
  window.asList = v => Array.isArray(v) ? v : (typeof v === 'string' && v ? [v] : []);
  ```
  ```javascript
  // gui/static/confirm.html
  const sel = q.type==='multi' ? asList(chosen).includes(o.label) : chosen===o.label;
  ...
  function pick(qi, oi){
    const q = DATA.questions[qi], label = q.options[oi].label;
    if(q.type==='multi'){
      const arr = asList(ANSWERS[q.id]);
      ANSWERS = {...ANSWERS, [q.id]: arr.includes(label) ? arr.filter(x=>x!==label) : [...arr, label]};
    } else {
      ANSWERS = {...ANSWERS, [q.id]: label};
    }
    renderQuestions();
  }
  // load() 里：if(DATA.answers_unreadable) document.getElementById('status').textContent = COPY_ANSWERS_UNREADABLE;
  const COPY_ANSWERS_UNREADABLE = '上次保存的答案读不出来，请重新作答';
  ```
  ```javascript
  // gui/static/index.html selectProject
  async function selectProject(name){
    state.project = name; state.sel = null;
    try { await refresh(); }
    catch(e){ renderWarnbar([e.message]); toast(e.message); return; }  // KI-21：项目打不开要说清原因
    ...
  }
  ```
- **MIRROR**: SERVICE_PATTERN（gui 子模块不依赖 server）；ERROR_HANDLING（「必须在 ValueError 之前」注释）；`renderWarnbar`（`index.html:261-266`）。
- **IMPORTS**: server.py：`from gui import jobs, payloads, settings, support`、`from pipeline import questions`（已有 `select`）；payloads.py：`from pipeline import notices, questions, review, schema`；notices.py：`from pipeline import schema`。
- **GOTCHA**:
  - 搬家第一步必须**单独**跑全量确认绿，再改行为；`tests/test_server_hardening.py:91` 打桩的是 `server.project_state`——`project_state` **留在 server.py**，不要搬。
  - `notices` 的模块注释写着「只读、不抛异常」——`corrupt_files` 只接 `CorruptJSON`，`read_json` 对缺失返回默认，OSError（权限）也归入 `CorruptJSON`，满足约定。
  - 每次 `/api/state` 会多解析约 10 个小 JSON（`segments.json` 可达数百 KB）；与现在 `jload` 的读取量同级，可接受。
  - `pick()` 改为不可变更新（`rules/ecc/common/coding-style.md`），原来的 `splice/push` 会原地改磁盘读来的对象。
  - CSP 不变：`asList` 在 `common.js` 里，不新增内联事件。
  - `/api/confirm` 的 `summary` 读取仍宽松（坏了当 `{}`），因为警告栏已点名；不要因为摘要坏了让确认页整页 409。
- **VALIDATE**: `uv run pytest tests/test_server_corrupt.py tests/test_server_*.py tests/test_frontend_js.py tests/test_static_pages.py tests/test_questions.py -q`；`wc -l gui/server.py` ≤ 789（搬出约 65 行、加回约 15 行）。

### Task 11: 收尾验证
- **ACTION**: 全量测试；行数检查；手动冒烟（见 Manual Validation）。
- **VALIDATE**: `uv run pytest`（预期 ≥ 987 + 新增，0 failed）；`wc -l aicut.py gui/server.py`（aicut ≤ 956，server ≤ 789）；`grep -n "check=True" pipeline/*.py aicut.py` 只剩测试外无（`render_preview` / `to_jianying` / aicut venv 均已去掉）。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_run_analysis_nonzero_raises_with_tail` | 退出码 1 + 长 stderr | `MediaError` 含退出码与末尾原因 | 是 |
| `test_probe_material_unrecognized` | ffprobe 退出码 1 / 空 / `{}` | `MediaError`（不再 `KeyError`） | 是 |
| `test_sample_frames_zero_frames_raises` | 退出 0、无数据 | `MediaError` | 是 |
| `test_unclosed_tail_intervals_closed_at_duration` | 末尾只有 `freeze_start` | 区间以时长收尾 | 是 |
| `test_union_seconds_counts_overlap_once` | 黑场 + 静音重叠 | 只计一次 | 是 |
| `test_tc_rounds_before_carry` | 59.999 | `01:00.00` | 是 |
| `test_contained_sentence_does_not_move_end_backwards` | 包含句 | 段尾不回退 | 是 |
| `test_default_project_does_not_share_mutable_defaults` | 两个项目 | 互不影响 | 是 |
| `test_read_json_*` | 缺失 / 损坏 / 非 UTF-8 / 顶层类型错 | 默认值 / `CorruptJSON` | 是 |
| `test_default_transport_retries_dropped_connection` | `RemoteDisconnected` 等 | 重试后成功 | 是 |
| `test_unmatched_must_line_warned` 等 | 对不上的原话 / 话题 / 答案 | `warnings` 点名 | 是 |
| `test_fallback_without_answers_not_reusable` | 兜底且未作答 | 重新生成 | 是 |
| `test_select_corrupt_overrides_dies_with_message` | overrides 损坏 | 退出码 1 + 人话 | 是 |
| `test_build_rejects_bad_shots_file` | 缺 shots / 非列表 / out≤in / 损坏 | `die` 不切片 | 是 |
| `test_state_corrupt_project_json_is_409_not_404` | project.json 损坏 | 409 | 是 |
| `test_confirm_multi_answer_coerced_to_list` | 多选是字符串 | 数组 | 是 |
| `test_as_list` | 各种类型 | 数组 | 是 |

### Edge Cases Checklist
- [x] Empty input：空 stdout 的 ffprobe、零帧抽帧、空字幕、空答案
- [x] Maximum size input：长 stderr 只取末尾 `STDERR_TAIL`
- [x] Invalid types：顶层 JSON 类型错、答案类型错、时间码非数、`shots` 非列表
- [ ] Concurrent access：不涉及（KI-51 在里程碑 9）
- [x] Network failure：KI-25 回归（连接被断 / 重置 / 截断）
- [x] Permission denied：`read_json` 把 `OSError` 归入 `CorruptJSON`（有文件但读不了）

---

## Validation Commands

### Static Analysis
```bash
# 本仓库未配置 lint / typecheck（CLAUDE.md）；做语法级检查即可
uv run python -m compileall -q aicut.py pipeline gui
```
EXPECT: 无输出、退出码 0

### Unit Tests
```bash
uv run pytest tests/test_media_io.py tests/test_junk_detect.py tests/test_format_transcript.py \
  tests/test_schema.py tests/test_llm.py tests/test_select.py tests/test_questions.py \
  tests/test_classify.py tests/test_m8_cli_failures.py tests/test_server_corrupt.py \
  tests/test_frontend_js.py tests/test_static_pages.py -q
```
EXPECT: All tests pass

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 基线 987 passed + 本里程碑新增，0 failed（`test_state_survives_corrupt_scored_file` 已按 Task 10 更新）

### Database Validation (if applicable)
N/A

### Browser Validation (if applicable)
```bash
python3 gui/server.py --open
```
EXPECT: 见下方手动清单

### Manual Validation
- [ ] 把一个测试项目的 `project.json` 改坏 → 剪辑台点该项目，警告栏 / toast 显示「项目配置（project.json）损坏…」而不是「项目不存在」。
- [ ] 把 `shots.json` 改坏 → 警告栏出现「分镜表（shots.json）损坏…」；`uv run python aicut.py build <项目> --no-draft` 输出 `[x] … shots.json …`，无 traceback。
- [ ] 把 `work/overrides.json` 改坏 → `aicut.py select <项目>` 输出「人工裁决文件损坏，未做任何修改」，无 traceback。
- [ ] 用一个 0 字节 / 改名的 `.mp4` 新建项目跑 ingest → `[x] 素材读不出来：ffprobe 认不出这个文件…`。
- [ ] 把 `work/proxy.mp4` 截断一半后跑 `junk` / `scenes` / `quality` → 三者都 `[x] …失败：…`，不再 `[✓]`。
- [ ] 断网跑 `summary` → `[!] 内容摘要是兜底生成的（AI 调用失败：网络错误…）`，剪辑台警告栏同样出现。
- [ ] 确认页：手改 `brief_answers.json` 把多选答案写成字符串 → 页面正常、该题显示已选。

---

## Acceptance Criteria
- [ ] Task 1–11 全部完成
- [ ] 全部验证命令通过
- [ ] 每个 Task 先 RED 后 GREEN
- [ ] 无语法错误（compileall）
- [ ] `aicut.py` 净增 ≤ 25 行；`gui/server.py` 不超过 789 行
- [ ] UX 与上方 After 一致
- [ ] KI-25 有走真实 `default_transport` 的回归测试

## Completion Checklist
- [ ] 新文案全部是命名常量（`*_MSG` / `*_WARNING` / `*_NOTICE` / `COPY_*`）
- [ ] 异常处理沿用「领域异常 → 调用方 die / 路由 4xx」
- [ ] `CorruptJSON` 在所有路由里都排在 `ValueError` 之前
- [ ] 测试沿用 `conftest` fixture 与 `FakeProc` 打桩
- [ ] 无硬编码魔数（新增 `FRAMES_EXIT_WAIT_S` 等常量）
- [ ] 不可变更新（`pick()`、`select` 的 warnings 拼接用新列表）
- [ ] 无范围外改动（NOT Building）
- [ ] 计划自洽：实现时无需再搜代码

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 以前「看起来成功」的坏素材现在会让「处理素材」停在 junk / scenes / quality | 中 | 中 | 这正是 KI-19 的目标；报错带 ffmpeg 原因 + 已有「导出诊断包」；手动清单第 5 条验证文案 |
| `clean_shots` 规整入出点导致手写 `shots.json` 的整数入出点镜头重切一次 | 中 | 低 | 只影响手写分镜表、一次性；Task 9 GOTCHA 已注明 |
| `sample_frames` 改 stderr 到临时文件后行为差异 | 低 | 中 | 现有真 ffmpeg 用例（`tests/test_understand_visual.py:75-90`）必须保持绿 |
| `notices.corrupt_files` 每次 `/api/state` 多读文件，大项目变慢 | 低 | 低 | 与现有 `jload` 读取量同级；必要时后续加 mtime 缓存（不在本里程碑） |
| junk_detect 脚本方式导入 `pipeline.media_io` 触发 KI-15 同名遮蔽 | 低 | 中 | 用 `sys.path.append`（同 render_preview 已验证路径）；开发机跑 `aicut.py junk` 冒烟 |
| 兜底问题被重新生成后，已有（未确认的）答案对不上 | 低 | 低 | 只有「未作答」才重新生成；作答过的保留并在警告栏提示；对不上的答案由 KI-23 点名 |

## Notes

- 里程碑 1–5 新增的模块已被复用：`media_io`（GL-15）承载 KI-19 新原语；`schema.write_json`（GL-18）旁新增 `read_json`；`notices`（M2）是 KI-21/22 的展示通道；`proc.exit_code`（GL-12）保证 `sys.exit("文字")` 在打包版任务日志里可见。
- `aicut.py`（931 行）与 `gui/server.py`（789 行）都在软上限附近：所有判断逻辑放在 `pipeline/media_io.py`、`pipeline/schema.py`、`pipeline/notices.py`、`pipeline/questions.py`、`gui/payloads.py`；aicut 只加 try/die 接线，server 通过搬出 `browse/confirm` 两个 payload 抵消新增行数。
- KI-25 已修复，关闭时状态列写「fixed `ebabfcc`/`ac3f15c`（本里程碑补回归测试 `<提交号>`）」。
- KI-20 的「`check=True`+`capture_output`」形态在仓库里只剩 `to_jianying.run` 死代码；关闭时注明主体已由 `ef3899f`（GL-15 `media_io.run_ffmpeg`）修掉。
- KI-21 登记位置 `pipeline/classify.py:116-121` 已漂移，本计划按当前 `classify.run:227-233` 的可选输入处理解释，关闭时在状态列说明。

### 需用户决策（实现默认采用推荐项，除非你改）

1. **KI-22 兜底决策问题何时重新生成**
   - 推荐（默认）：缓存是兜底**且还没保存过答案** → 下次「处理素材」重新让 AI 生成；已经作答 → 保留，只在警告栏提示，要换题用 `aicut questions --force`。
   - 备选：只要是兜底就重新生成（可能让已填答案对不上）。
2. **KI-21 剪辑台遇到损坏文件的展示方式**
   - 推荐（默认）：`project.json`、浏览页的三档判定、确认页的决策问题损坏 → 页面直接报「…损坏、读不出来」（409）；其它文件损坏 → 页面照常打开、按「没有」显示，常驻警告栏逐个点名；切项目失败时把原因放进警告栏 + toast。
   - 备选：任何文件损坏都整页报错（更保守，但一个废片表坏了就整个项目打不开）。
3. **KI-27 `--scene` 镜头切点**
   - 推荐（默认）：保留参数，把切点写进 `junk_report.json` 的 `scenes`（现在白算的结果不再丢）。
   - 备选：`cmd_junk` 不再传 `--scene`（镜头切分已由 `scenes` 步骤单独做，可省一次 scdet 计算），并删掉该参数。
4. **KI-24 缺时间码的句子**
   - 推荐（默认）：跳过并在转写整理输出里写「N 句缺少有效时间码，已跳过」；全部缺失则转写步骤失败。aicut 不额外转述这条提示（成功时子进程输出不打印，保持现状）。
   - 备选：只要有一句缺时间码就让转写步骤失败。
5. **KI-49 答案文件读不出来时**
   - 推荐（默认）：确认页照常打开、答案清空，状态行写「上次保存的答案读不出来，请重新作答」。
   - 备选：确认页整页报错（409），需要先处理文件。
6. **新增文案**：本计划所有面向剪辑师的中文提示都是命名常量（见各 Task 的 `*_MSG / *_WARNING / *_NOTICE / COPY_*`），措辞可在实现前或实现后直接改常量，不影响结构。
