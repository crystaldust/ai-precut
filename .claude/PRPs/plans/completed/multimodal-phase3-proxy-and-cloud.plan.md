# Plan: 画面理解 · 第 3 阶段 —— 代理素材与云端理解

## Summary
开启画面理解时，分析流程在「画面检查」之后多跑一个 `vision` 阶段：从 `work/proxy.mp4` 切出 5 分钟一段、去掉音轨的低清画面代理，逐段经 MediaKit 本地上传，调用 `video-understand-router`（默认手动 2 fps），解析模型返回的 JSON 事件、换算成全片时间，合并成 `work/visual_timeline.json`。按段缓存、可中断续跑；tokens 记进单独账本 `work/vision_usage.json`（不占 DeepSeek 预算）。② 进度在开启时多出「生成画面代理」「云端画面理解」两项。本阶段**只产出时间轴**，不改标注、档位、③（第 4、5 阶段）。

## User Story
As a 剪辑师, I want 开了画面理解后点「开始分析」就能得到整条素材的画面时间轴, so that 后续步骤能用上「画面里发生了什么」，而且长素材中途停了也不用从头再花钱。

## Problem → Solution
第 2 阶段开关打开后没有任何效果 → 开关打开时分析多出画面代理 + 云端理解两步，产出带全片时间的画面事件；关闭时与现在完全一致。

## Metadata
- **Complexity**: Large（新增 3 个模块 + 外部接口 + 流程 / 进度 / 账本 / CLI 改动）
- **Source PRD**: `.claude/PRPs/prds/multimodal-video-understanding.prd.md`
- **PRD Phase**: Phase 3 代理素材与云端理解
- **Estimated Files**: 约 20（新建 3 模块 + 3 测试；改约 14）

---

## UX Design

### Before
```
② 开关打开 → 开始分析 → 11 项进度，与关闭时完全一样（开关没效果）
```

### After
```
② 开关打开 → 开始分析 → 13 项进度：
   读取素材 → 生成浏览小样 → 抽音轨 → 云端转写 → 声音分析 → 画面检查
   → 生成画面代理 → 云端画面理解 → AI 理解对话 → …
   云端画面理解失败：「「云端画面理解」失败：<原因>」+ 重试；也可以关掉画面理解再重试
② 开关关闭 → 仍是 11 项，行为与现在一致
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| ② 进度列表 | 固定 11 项 | 开启时 13 项（多「生成画面代理」「云端画面理解」） | `progress()` 按 facts 里的开关决定 |
| ② 失败卡片 | — | 云端画面理解失败的原因 + 重试 | 不静默降级；失败时开关可改，关掉再重试即「出口」 |
| 缺 Key | 已转写过的项目不再要 MediaKit Key | 开启画面理解且时间轴未完成时仍要 MediaKit Key | `readiness.needed_keys` |
| CLI | `aicut new` 无开关 | `aicut new … --vision economy|balanced|quality`（默认 off）；`aicut vision <name>` 单跑这一步 | |
| `aicut status` | LLM 用量一行 | 另加「画面理解用量」一行与「画面时间轴」产物 | |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `.claude/PRPs/reports/multimodal-phase1-spike.report.md` | all | 参数结论：手动 2 fps、5 分钟一段、约 4,500 tokens/分钟、JSON 9/9 稳定、模型自评「可用」不可信 |
| P0 | `.claude/PRPs/spikes/multimodal/spike.py` | all | 已验证可用的调用方式（上传 `tool_name`、payload、轮询） |
| P0 | `pipeline/cloud.py` | 187-450 | `CloudClient`：`_request` 重试 / 脱敏、`_upload_target`（**写死 ASR_TOOL**）、`_upload`、`wait_task`、`transcribe` 的续跑 / 终态范式 |
| P0 | `aicut.py` | 243-271, 343-358, 649-664 | `cmd_transcribe`（云端步骤范式）、`cmd_junk`（代理转码）、`cmd_prepare`（按 `PREPARE_STEPS` 跑、开始时取指纹） |
| P0 | `gui/analysis.py` | all | 进度步骤表、`INTRA_STAGE_STEPS`、`_owner_of_seconds`、`facts()` |
| P1 | `pipeline/readiness.py` | all | `PREPARE_STEPS`、`needed_keys`、`STATUS_ARTIFACTS` |
| P1 | `pipeline/usage.py` | 60-90 | `load` / `record`（账本格式与加锁） |
| P1 | `pipeline/media_io.py` | 52-160, 199-205 | `ffmpeg_to` 原子落盘、`source_fingerprint`、`timeout_for` |
| P1 | `pipeline/encode.py` | 18-53 | `h264_args(kind)`、`BITRATES`（加 `vision`） |
| P1 | `pipeline/vision.py` | all | 第 2 阶段的设置模型，本阶段加档位参数 |
| P1 | `gui/settings.py` | 43-52 | `check_prepare_ready` 调 `missing_keys` |
| P2 | `tests/test_cloud.py` | 1-84 | `FakeHttp` / `make()` 假传输层 |
| P2 | `tests/test_analysis_progress.py` | all | 进度纯函数测试写法 |
| P2 | `tests/test_aicut_cli.py` | 140-190 | prepare 写戳的测试写法 |
| P2 | `pipeline/cli_args.py` | all | 子命令注册 |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| 视频理解智能策略 | [docs 6448/2551133](https://docs.volcengine.com/docs/6448/2551133?lang=zh) | `POST /api/v1/tools/video-understand-router`，`video_urls`（≤10）、`prompt`、`level`、`manual_option{fps 0.2–5, max_snapshot_number, need_audio}`；单视频 ≤2 小时、≤1000 帧；结果 `contents[]`（每个视频一段文本）+ `token_usage{input_tokens,output_tokens,total_tokens}` |
| 第 1 阶段实测返回形状 | spike `out/*.json`（本机，不入库） | 完成后顶层：`status: "completed"`、`contents: [str]`、`duration`、`token_usage`；13 次结果 `contents[0]` 全是裸 JSON（无 ``` 包裹），但仍要容错 |

KEY_INSIGHT: 上传地址申请时 `tool_name` 必须换成 `video-understand-router`（spike 已验证）
APPLIES_TO: Task 2
GOTCHA: `cloud._upload_target` 写死了 `ASR_TOOL`，且 `_upload` 会写 ASR 的上传缓存 `asr_upload.json` —— 画面上传必须传 `workdir=None`，自己管缓存

KEY_INSIGHT: 返回结果没有模型名；tokens 由服务端策略决定（2 fps 反而比 1 fps 便宜），只能按 `token_usage` 记账
APPLIES_TO: Task 7
GOTCHA: 不能事先估费用；界面上的「约 27 万 tokens / 小时」只是参考

KEY_INSIGHT: 未验证：`level` 与 `manual_option` 能否同时传、`client_token` 是否被接受
APPLIES_TO: Task 1（先实测再定 `TIER_PARAMS`）
GOTCHA: 传了接口不认识的字段可能被拒；未验证前不传 `client_token`

---

## Patterns to Mirror

### CLOUD_STEP（云端步骤：续跑、终态、失败落盘）
// SOURCE: pipeline/cloud.py:422-448
```python
task_id = asr_state.load(workdir, audio, BACKEND)
try:
    if task_id is None:
        token = _submit_token(workdir, audio)
        task_id = self.submit_asr(audio, workdir=workdir, client_token=token)
        _remember_task(workdir, audio, task_id)
    ...
    data = self.wait_task(task_id, total_timeout)
except CloudError as exc:
    if exc.terminal:  # 云端判任务终态失败：下次重新提交（连同上传缓存，KI-75）
        asr_state.clear(workdir); _forget_upload(workdir)
    record_failure(workdir, "asr", str(exc), {"audio": Path(audio).name})
    raise
schema.write_json(Path(workdir) / "transcript_raw.json", data)  # 原子写
```

### CLI_STEP（aicut 步骤命令）
// SOURCE: aicut.py:262-271
```python
require_consent()
if not secrets.get("mediakit"):
    die("未配置 MEDIAKIT_API_KEY：运行 `uv run python aicut.py config set mediakit`")
info("获取云端转写结果（长素材要几分钟，中断后重跑会接着查）…")
client = cloud.CloudClient()
try:
    client.transcribe(wav, work, duration_s=media_io.duration_or_zero(wav))
except cloud.CloudError as exc:
    die(f"转写失败：{exc}")
```

### PROXY_ENCODE
// SOURCE: aicut.py:349-355
```python
media_io.ffmpeg_to(proxy, ["-i", c["material"], "-vf", "scale=-2:540,fps=30",
                           *encode.h264_args("proxy"), "-c:a", "aac", "-b:a", "64k"],
                   timeout=material_timeout(pdir), source=c["material"])
```

### PROGRESS_STEPS
// SOURCE: gui/analysis.py:20-45
```python
ANALYSIS_STEPS = (("ingest", "读取素材", ("ingest",), "materials"), ...)
INTRA_STAGE_STEPS = frozenset({"audio"})  # 同一阶段中途就产出文件的步骤
```

### USAGE_LEDGER
// SOURCE: pipeline/usage.py:70-82
```python
with schema.locked(path):
    led = load(workdir)
    ...
    schema.write_json(path, {...})
```

### TEST_STRUCTURE（云端假传输）
// SOURCE: tests/test_cloud.py:31-72
```python
c, http, up_calls = make({UPLOAD: [(200, UP_TARGET)], SUBMIT: [ok_task()], TASK("t1"): [DONE]})
assert http.count(SUBMIT) == 1 and http.bodies(UPLOAD)[0] == {"tool_name": ...}
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/vision.py` | UPDATE | `TIER_PARAMS`（档位 → 接口参数）、`CHUNK_S = 300`、`MAX_FRAMES = 1000`、`PROMPT_VERSION`；`is_on(cfg)` |
| `pipeline/encode.py` | UPDATE | `BITRATES["vision"] = "300k"` |
| `pipeline/cloud.py` | UPDATE | `_upload_target(tool=ASR_TOOL)`；公开 `upload(path, *, tool, label)`（不写 ASR 缓存）；`submit_tool(tool, payload) -> task_id`；上传提示 / 失败文案按 label |
| `pipeline/vision_proxy.py` | CREATE | `plan_chunks(duration_s)`（纯函数）；`encode_chunk(proxy, chunk, dst, *, timeout, runner)`：`-ss/-t` + `fps=5` + `-an` + `h264_args("vision")`，原子落盘 |
| `pipeline/vision_timeline.py` | CREATE | 纯函数：`PROMPT`、`parse_contents`、`to_global`、`build` |
| `pipeline/vision_run.py` | CREATE | 编排：状态、逐段 编码 → 上传 → 提交 → 轮询 → 解析 → 落盘、并发、重提、记账、合并、清理；`timeline_current(work, cfg)` |
| `pipeline/usage.py` | UPDATE | `VISION_USAGE_FILE`；`load` / `record` / `summary` 加 `file=`；`record_vision` |
| `pipeline/readiness.py` | UPDATE | `PREPARE_STEPS` 在 `quality` 后加 `"vision"`；`needed_keys(work, vision_on=False)`；`STATUS_ARTIFACTS` 加「画面时间轴」 |
| `pipeline/diskspace.py` | UPDATE | `need_for_prepare(..., vision=False)` 加画面代理（300k，无音轨） |
| `aicut.py` | UPDATE | `cmd_vision`；`cmd_prepare` / `prepare_need` 传开关；`cmd_new` 读 `--vision` |
| `pipeline/cli_args.py` | UPDATE | `new --vision {off,economy,balanced,quality}`；`vision` 加入 `NAME_ONLY` |
| `pipeline/project_cli.py` | UPDATE | `status` 打印画面理解用量 |
| `gui/settings.py` | UPDATE | `check_prepare_ready` 读 project.json 的开关传给 `missing_keys` |
| `gui/analysis.py` | UPDATE | 开启时插入 `VISION_STEPS`；`facts()` 带开关与两个产物；`INTRA_STAGE_STEPS` 加 `vision_proxy` |
| `packaging/ai-cut.spec` | UPDATE | hiddenimports 加 3 个新模块（`test_structure` 守着） |
| `tests/test_vision_proxy.py`、`tests/test_vision_timeline.py`、`tests/test_vision_run.py` | CREATE | 见 Testing Strategy |
| `tests/test_cloud.py`、`test_analysis_progress.py`、`test_usage.py`、`test_cli_helpers.py`、`test_aicut_cli.py`、`test_diskspace.py`、`test_vision_setting.py` | UPDATE | 新参数 / 新步骤 / 新命令 |
| `docs/GUI.md`、`docs/PRD-AI粗剪工具.md`（FR-2）、`docs/PROGRESS.md`（#33 补实测项）、`docs/TECH-STACK.md`、PRD 第 3 阶段状态 | UPDATE | 去掉「第 2 阶段只保存设置」；进度 13 项；CLI 参数；账本 |

## NOT Building
- 画面事件挂到片段、画面片段、DeepSeek 画面判断、档位规则（第 4 阶段）
- ③ 显示画面描述（第 5 阶段）；②「整合画面与对白」进度项（第 4 阶段随真实步骤加）
- 用模型转写替代 ASR；语义切片
- 费用上限（只记账）
- 画面理解与转写并行跑（先串行，见 Notes）

---

## Step-by-Step Tasks

### Task 1: 实测档位参数（一次性，少量 tokens，执行前需用户同意）
- **ACTION**: 用 spike 脚本在第 1 阶段已有的片段 B 上各跑一次：`{"level":"Balanced","manual_option":{"fps":2,"need_audio":false}}`、`{"level":"Quality","manual_option":{"fps":3,"need_audio":false}}`，以及 economy payload 带 `client_token` 一次。
- **IMPLEMENT**: 记录是否被接受、tokens、事件边界误差；结论追加进第 1 阶段报告。
- **GOTCHA**: 上传的是第 1 阶段同一批片段（已在用户自己的账号里），约 8–12 万 tokens；结果不入库。
- **DECIDE**: 组合被拒 → `TIER_PARAMS` 只用 fps：省钱 2、均衡 2.5、精细 3；`client_token` 被拒 → 不传（丢响应重提的极小概率重复计费，写进 Notes）。
- **VALIDATE**: 报告里有三档实测表

### Task 2: cloud.py 通用上传与提交
- **ACTION**: `_upload_target(self, tool: str = ASR_TOOL)`；新增 `upload(self, path, *, tool, label) -> file_id`（复用 `_upload` 的重试，不写 ASR 缓存；提示 `f"[·] 上传{label}（{mb} MB）…"`，ASR 仍是「音轨」）；新增 `submit_tool(self, tool, payload) -> str`（`_request` + 取 task_id，缺 task_id 同 `submit_asr` 报错）。
- **MIRROR**: CLOUD_STEP；不改 `transcribe` 行为
- **GOTCHA**: `UPLOAD_FAILED`「上传音轨失败」改为按 label；已有测试断言的 ASR 字符串保持不变
- **VALIDATE**: `uv run pytest tests/test_cloud.py`（新增：上传申请带画面 tool_name、不写 asr_upload.json、submit_tool 路径与 body）

### Task 3: 设置 → 接口参数、码率
- **ACTION**: `vision.py` 加 `TIER_PARAMS = {"economy": {"manual_option": {"fps": 2, "need_audio": False}}, ...}`（Task 1 定稿）、`CHUNK_S = 300`、`MAX_FRAMES = 1000`、`PROMPT_VERSION = 1`、`is_on(cfg) -> bool`。`encode.BITRATES["vision"] = "300k"`。
- **VALIDATE**: `tests/test_vision_setting.py` 加：每档最大 fps × (CHUNK_S + MIN_TAIL_S) ≤ MAX_FRAMES

### Task 4: 画面代理 `vision_proxy.py`
- **ACTION**: `plan_chunks(duration_s, chunk_s=CHUNK_S)` → `[{"index", "start", "end"}]`，最后一段不足 `MIN_TAIL_S = 20` 秒并入前一段；`duration <= 0` 抛 `ValueError`。`encode_chunk(...)`：`["-ss", start, "-i", proxy, "-t", end-start, "-vf", "fps=5", "-an", *encode.h264_args("vision")]` 经 `media_io.ffmpeg_to`（原子、`.done` 绑定 proxy）。
- **MIRROR**: PROXY_ENCODE
- **GOTCHA**: 尾段并入后最长 CHUNK_S + 20 秒，3 fps 时 960 帧 < 1000；`-ss` 放 `-i` 前（快速定位，重编码从准确时间开始）
- **VALIDATE**: `tests/test_vision_proxy.py`

### Task 5: 时间轴解析 `vision_timeline.py`（纯函数）
- **ACTION**:
  - `PROMPT`：沿用 spike 版式，**不再要求「可用 / 不可用」**，改为客观字段 `{"start","end","shot","people","action","objects":[],"text_on_screen","issues":[]}`，`issues` 只能从 `ISSUES = ("背对镜头","人物出画","遮挡","画面晃动","过暗","模糊")` 里选；要求首尾相接覆盖整段。
  - `parse_contents(text)`：去 ``` 包裹 / 取第一个 `{` 到最后一个 `}` → `json.loads` → 必须有 `events` 列表；start/end 能转成有限 float 且 `end > start`；字符串字段截断 `FIELD_MAX = 300`；`objects` 只留字符串（≤ 12 个）；`issues` 只留白名单；坏事件丢弃；一个合法事件都没有 → `TimelineParseError`。
  - `to_global(events, chunk)`：加 `chunk.start`、夹到段内、丢掉夹完 < 0.5 秒的、按 start 排序。
  - `build(chunk_results, duration, setting)` → `schema.stamp({"setting", "prompt_version", "duration", "events", "chunks": [{"index","start","end","tokens"}], "usage": {"total_tokens"}})`。
- **GOTCHA**: 模型秒数可能超过段长（300 秒段给 305）——夹取，不报错
- **VALIDATE**: `tests/test_vision_timeline.py`

### Task 6: 编排 `vision_run.py`
- **ACTION**: `run(work, cfg, proxy, *, client_factory, runner=subprocess.run, parallel=PARALLEL) -> dict`：
  1. 未开启 → 返回 `{"skipped": True}`，不建 client、不写文件。
  2. `key = sha(素材指纹, tier, PROMPT_VERSION, CHUNK_S)`；`work/vision/state.json` 的 key 不同 → 只删 `work/vision/` 下自己的文件后重来。
  3. `plan_chunks(duration_or_zero(proxy))`；读不出时长 → `VisionError`。
  4. 每段（线程池 `PARALLEL = 3`）：已有 `chunk_NNN.json` → 跳过；否则 编码（缺才编）→ 上传（state 里有未过期 `file_id` 就复用，TTL = `cloud.UPLOAD_TTL_S`）→ 有 `task_id` 就续查，否则 `submit_tool` 后**立即**写 state → `wait_task(total_timeout=VISION_TASK_TIMEOUT_S = 900)` → 记账 → `parse_contents` → 原子写 `chunk_NNN.json`。解析失败：清 task_id、重提一次；再失败 → `VisionError("第 N 段（mm:ss–mm:ss）的画面理解结果看不懂…")`。`CloudError.terminal` → 清这段 task_id / file_id 后抛出。
  5. 全部完成 → `build` → 原子写 `work/visual_timeline.json` → 删 `work/vision/*.mp4` 与 `.done`（保留 state 与段结果）。
  6. 失败 `cloud.record_failure(work, "vision", ..., {"chunk": n})`（不含路径 / 画面内容）。
  - `timeline_current(work, cfg) -> bool`：文件可读、`setting.tier` 与当前一致、`prompt_version` 一致。
  - state 读改写用 `schema.locked(state_path)`（多线程）。
  - `future.result()` 统一收集：先让其它段跑完并落盘，再抛第一个错误。
- **MIRROR**: CLOUD_STEP；USAGE_LEDGER
- **GOTCHA**: 「停止分析」会直接杀进程 → **每一步结果先落盘再进行下一步**，不能在主线程最后统一写
- **GOTCHA**: 不碰 `asr_task.json` / `asr_upload.json`；诊断包（`diagnostics.SAFE_WORK_FILES`）不带画面结果
- **VALIDATE**: `tests/test_vision_run.py`

### Task 7: 账本
- **ACTION**: `usage.load/record/summary` 加 `file: str = USAGE_FILE`；`record_vision(workdir, tu)` → `record(..., "vision", {"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": total_tokens}, file=VISION_USAGE_FILE)`。`check()` 只看 LLM 账本，不动。`project_cli.status` 有画面账本时多一行「画面理解用量：N tokens（不计入 LLM 预算）」。
- **VALIDATE**: `uv run pytest tests/test_usage.py`（画面记账不影响 `check()`）

### Task 8: 流程接入（CLI / 就绪 / 磁盘）
- **ACTION**: `PREPARE_STEPS` 加 `"vision"`（`quality` 后、`text` 前）；`cmd_vision`（未开启：一句 info 后返回；开启：告知 + Key 检查 + `vision_run.run`，`VisionError` / `CloudError` → `die("画面理解失败：…（可以重试，或在「② 分析」关掉画面理解后继续）")`）；`readiness.needed_keys(work, vision_on=False)`；`aicut.cmd_prepare` 与 `gui/settings.check_prepare_ready` 传 `vision.is_on(cfg)`；`prepare_need` 加画面代理字节；`new --vision`、`vision` 子命令。
- **GOTCHA**: 分析戳在**开始时**取（已含 vision），不改
- **GOTCHA**: 关闭时 `cmd_vision` 也会计时（几毫秒、ok）——进度里关闭时不显示这两项，不受影响
- **VALIDATE**: `uv run pytest tests/test_aicut_cli.py tests/test_cli_helpers.py tests/test_diskspace.py tests/test_m8_cli_failures.py`

### Task 9: ② 进度
- **ACTION**: `facts()` 加 `vision_on` 与产物 `vision_chunks`（state 记录全部段已编码，或时间轴已是当前的）、`vision_timeline`（`timeline_current`）；`progress()` 开启时把 `VISION_STEPS = (("vision_proxy","生成画面代理",("vision",),"vision_chunks"), ("vision_cloud","云端画面理解",("vision",),"vision_timeline"))` 插在 `visual` 后；`INTRA_STAGE_STEPS` 加 `vision_proxy`。
- **GOTCHA**: `progress()` 是纯函数，开关从 facts 传入；`total` 变 13，前端用返回的 `total`
- **VALIDATE**: `uv run pytest tests/test_analysis_progress.py tests/test_frontend_analysis.py`

### Task 10: 打包与文档
- **ACTION**: spec hiddenimports；GUI.md（② 进度 13 项、删掉「第 2 阶段只保存设置」、失败时可关开关重试）；主 PRD FR-2 加「可选云端画面理解：产出 `visual_timeline.json`」；TECH-STACK 改「已接入（第 3 阶段）」；PROGRESS #33 补「真账号 60 分钟素材：完整时间轴、停止后重跑只补未完成段、`vision_usage.json` 有记录」；PRD 第 3 阶段状态。
- **VALIDATE**: `uv run pytest tests/test_structure.py tests/test_docs_consistency.py tests/test_terms.py`

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| plan_chunks | 3600 s | 12 段，首尾相接 | |
| plan_chunks 尾巴 | 610 s | 2 段（第 2 段 300–610） | ✓ |
| plan_chunks | 0 / 负数 | ValueError | ✓ |
| 帧数上限 | 最大 fps × (CHUNK_S + MIN_TAIL_S) | ≤ 1000 | ✓ |
| encode_chunk 参数 | 假 runner | 含 -ss/-t/fps=5/-an/300k | |
| parse_contents | ```json 包裹 / 前后杂字 / 字符串数字 | 正常解析 | ✓ |
| parse_contents | 非 JSON / 无 events / 全部坏事件 | TimelineParseError | ✓ |
| parse_contents | issues 白名单外、objects 含数字 | 被过滤 | ✓ |
| to_global | 段 300–600，事件 0–305 | 300–600，排序 | ✓ |
| run 全流程 | 2 段，假 client | 两次上传（画面 tool_name）、两次提交、时间轴、账本、段视频删除 | |
| run 续跑 | 段 0 已有结果 | 只处理段 1 | ✓ |
| run 续查 | state 有 task_id | 不提交，直接轮询 | ✓ |
| run key 变化 | 换档位 | 旧段结果作废、重跑 | ✓ |
| run 解析失败一次 | 乱码 → 正常 | 提交 2 次、成功、记账 2 次 | ✓ |
| run 两次乱码 | | VisionError 含段号与时间 | ✓ |
| run 终态失败 | wait_task terminal | 清该段 task_id、failed.json 有 vision、抛出 | ✓ |
| run 一段失败另一段成功 | | 成功段已落盘，再抛错 | ✓ |
| run 关闭 | enabled False | 不建 client、不写文件 | |
| timeline_current | 档位不同 / 文件坏 | False | ✓ |
| cloud.upload | tool=video-understand-router | 申请 body 正确、不写 asr_upload.json | |
| needed_keys | 已转写 + 开启 + 无时间轴 | 要 mediakit | ✓ |
| progress | vision_on | 13 项、两项在「画面检查」后 | |
| progress | vision 阶段运行中 | 「生成画面代理」running | |
| CLI new --vision balanced | | project.json 开启、均衡 | |
| usage 画面账本 | 记一次 | 不影响 check() | ✓ |

### Edge Cases Checklist
- [x] 极短素材（< 20 秒：1 段）
- [x] 超长素材（3 小时：36 段，线程池 3）
- [x] 模型输出格式异常
- [x] 中途停止 / 进程被杀（每步先落盘）
- [x] 网络失败（`_request` 重试；耗尽后可重试错误，下次续跑）
- [x] 上传地址过期（state 的 file_id 按 TTL 作废）
- [ ] 真账号 60 分钟（Manual Validation）

---

## Validation Commands

### Static Analysis
项目未配置 lint / 类型检查。

### Unit Tests
```bash
uv run pytest tests/test_vision_proxy.py tests/test_vision_timeline.py tests/test_vision_run.py tests/test_cloud.py tests/test_analysis_progress.py tests/test_usage.py tests/test_aicut_cli.py
```
EXPECT: All pass

### Full Test Suite
```bash
uv run pytest --cov
```
EXPECT: 无回归，覆盖率 ≥ 80%

### Manual Validation（真账号，执行前需用户确认）
- [ ] 在用户自己的一个项目上开启画面理解（省钱）→ 开始分析：② 出现两项新进度，完成后 `work/visual_timeline.json` 覆盖全片、事件时间单调
- [ ] 「云端画面理解」进行中点停止 → 再开始：已完成的段不重传、不重提
- [ ] `work/vision_usage.json` 有记录；`aicut status` 显示画面理解用量
- [ ] 关闭画面理解重新分析：进度回到 11 项，没有任何画面上传
- [ ] 完成后段视频已删除；`work/vision/` 只剩 state 与段结果

---

## Acceptance Criteria
- [ ] All tasks completed
- [ ] All validation commands pass
- [ ] 开关关闭时行为与现在一致（已有测试不改语义地通过）
- [ ] 60 分钟素材产出完整时间轴；停止后重跑只补未完成的段（PRD 第 3 阶段成功信号）

## Completion Checklist
- [ ] 云端调用都走 `CloudClient`（脱敏、重试、不跟随重定向）
- [ ] 每个云端状态变化先落盘
- [ ] 失败写 `failed.json`，不含路径和画面内容
- [ ] 画面结果不进诊断包
- [ ] 文案常量化（`*_MSG`）
- [ ] 无费用上限，只记账

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `level` + `manual_option` 组合 / `client_token` 未验证 | M | M | Task 1 先实测；退化方案已定 |
| 并发提交被限流（429） | M | L | `_request` 已对 429 退避；`PARALLEL` 是常量 |
| 线程异常被吞 / 进程被杀丢状态 | M | H | 每段结果原子落盘；统一收集 future 后抛第一个错误 |
| 模型时间超段长 / 乱序 | H | L | 夹取 + 排序（测试覆盖） |
| 长素材耗时 | M | M | 并发 3 段；与转写串行（见 Notes） |
| 关闭开关 / 旧项目回归 | L | H | 关闭时 `cmd_vision` 立即返回、进度不加项；全量测试兜底 |

## Notes
- 画面代理去掉音轨（`-an`）：v1 不做模型转写，少传数据也更贴合隐私告知；以后做 ASR 替代再加回。
- 画面理解放在「画面检查」之后、「AI 理解对话」之前：第 4 阶段的标注要用时间轴；和转写并行能省几分钟，但进度、取消、失败处理会复杂很多，先串行。
- 失败策略（PRD Open Question）：报错停下，与「不静默降级」一致；② 失败时开关可改，关掉再重试就是出口，不另做按钮。
- 段视频完成后自动删除；上传缓存只记在 state 里、按 12 小时 TTL；不新增 `aicut clean` 规则。
- 本阶段与第 2 阶段一起发版（PROGRESS #33 已注明）。
