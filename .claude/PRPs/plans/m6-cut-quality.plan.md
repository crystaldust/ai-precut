# Plan: M6 · 成片质量

## Summary
让选段与理解的各项「设计上该生效」的规则真正生效：成片字幕是整句且随镜头裁剪；hook 不被挪走、结尾按偏好正确落位；必留原话精确命中；确认页答案（含 focus / pacing）能改变剪法且在 GUI 里有入口；情绪信号进入打分；必留话题口径统一、词表外置；抢话代理收紧；长素材话题分段不再因 JSON 截断而崩；`--model` 真正传给客户端；预览/切片缓存绑定出入点；人工裁决不再套到错误句子上；预览字幕不再回落宋体。
本里程碑覆盖 KI-01..KI-12、KI-58、KI-73。全部按 TDD：先写失败测试，再改实现。

## User Story
作为剪辑师，我希望 AI 粗剪出的成片字幕完整、开场和结尾符合我的选择、我指定的原话和确认页答案真的影响剪法，这样我拿到的粗剪不用再逐镜返工。

## Problem → Solution
| KI | 现状（当前代码，HEAD `963374c`） | 目标 |
|---|---|---|
| KI-01 | 镜头 `sub` 一律 `text[:28]`（`pipeline/select.py:173,289,350,385`）；镜头被预算截短时字幕仍是整句开头 | 选段最后统一按镜头 `[start,end]` 生成字幕：整句；截短时只留落在镜头内的分句（用 `work/segments.json` 的 `lines` 时间码），无分句时按时长比例截 |
| KI-02 | `_fix_ending` 可能把 `role=hook` 的开场镜头移到片尾；取第一个命中；关键词「走/谢/信/钱」过宽（`select.py:35-39,464-484`）；兜底题 `ending=info` 被 `_norm_ending` 归成 None | 结尾候选排除 hook；取时间上最后一个命中；收紧词表；emotion 只看音量；支持 `info`；`silence` 给警告 |
| KI-03 | 必留原话按 `，；` 切碎（`select.py:547-550`），碎片命中任何包含它的句子都强制入选（`select.py:276-295`） | 先按换行/；切成「原话」，整句（去标点）匹配；整句找不到才退回逗号碎片（≥4 字）；每条只强制 1 段；没找到给警告 |
| KI-04 | `focus`/`pacing` 只解析不用；`pacing` 按 label 文字猜而不看 value；兜底「关键信息」选项绑 `must_topics: []`；label 截 12 字后跨题同名互相覆盖（`select.py:110-136`、`questions.py:59,91-92`） | 规则按「题 id → label」查；focus→说话最多的人加分 / 无法映射时警告；pacing=tight→单镜上限 12s；兜底关键信息选项改绑 `must_lines`；同题 label 去重 |
| KI-05 | GUI 没有确认页入口（`gui/static/index.html:142-149`）；保存答案不触发选段（`gui/server.py:656-673`）；prepare 在确认前已选完段。**部分已修**：M4 已有 `select` 任务（`gui/jobs.py:29-31`），但只被「改目标时长」使用 | 主界面加「确认与提问」入口；「保存并确认」后服务端自动起 `select` 任务，确认页显示进度/结果 |
| KI-06 | `classify` 生成 scored 段时没并入 `signals`（`classify.py:138-144`），`_score` 的情绪项与 emotion 结尾恒为 0 | scored 段带 `signals`；旧项目在 select 时从 `segments_audio.json` 回填 |
| KI-07 | 必留话题词表写死且过宽（`classify.py:21-23`），真实项目 19 话题判 14 个必留 | 词表 / 关键信息占比阈值 / 最少关键句数外置到预设 `must_topic`；代码兜底收窄 |
| KI-08 | 抢话代理 = 换人且停顿 <0.25s（`understand_audio.py:86-91`），`classify` 见到就判可用（`classify.py:62-63`）。样本项目 9/140 句命中，全部是 35s 长度上限切出来的假边界 | 真重叠→可用；代理信号需「本句 <30s 且音量 ≥ 中位+1dB」才算 |
| KI-09 | **部分已修**：逐句标注已在 M2 做了形状校验与重试。仍存在：话题分段一次调用、`max_tokens=3000`（`understand_text.py:158-160`）；`key_info: "false"` 被 `bool()` 判成 True（`:189`）；`_merge_topics_via_llm` 对非 dict 输出崩（`:110-115`）；`segment_topics` 对非 dict / 非 list 输出崩（`:161-170`） | 话题分段按 120 句分窗、逐窗校验+重试；`key_info` 严格布尔；`info_type` 不在枚举时归「事实陈述」；合并输出校验 |
| KI-10 | `understand_text.run` / `summarize.run` 收到 `model` 只写进结果，客户端仍是默认 `deepseek-chat`（`understand_text.py:304-305`、`summarize.py:101,115`） | 构造 `DeepSeekClient(model=model)` |
| KI-11 | **部分已修**：预览有完成标记（GL-15）且默认每次新版本目录。仍存在：预览哈希只算 timeline（`aicut.py:641-642`），出入点平移但时长不变时 timeline 完全相同 → `--version vN` 重出复用旧预览；`build_documentary.py:108` 切片只看文件完整 | 预览指纹 = timeline + 每镜 `clip_key`（含 src/in/out/id）；`build_documentary` 切片也用 manifest |
| KI-12 | overrides 只按 segment id 存（`review.py:52-100`），重新分段后套到别的句子 | 写入时带锚点（原文哈希 + 起点）；读取时校验，不符则按原文重定位，找不到就不套用并警告 |
| KI-58 | `_level_of` 只按名字判必留话题（`classify.py:141`），按关键信息占比判出的必留话题内句子拿不到「→待定」保护，与 `topics[].must` 不一致 | 先算 `must_names`（只依赖 topic/key_info），再判档位，全程同一口径 |
| KI-73 | 首选字体 `/System/Library/Fonts/PingFang.ttc` 不存在（本机 macOS 26.3.1 实测），回落宋体（`render_preview.py:25-29`） | 首选 `Hiragino Sans GB.ttc`（简体字形 W3），只选一次 |

## Metadata
- **Complexity**: Large
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 6 · 成片质量（KI-01..KI-12 KI-58 KI-73）
- **Estimated Files**: 31（新建 3 源文件 + 4 测试文件；修改 14 源/静态/预设文件 + 10 既有测试文件追加用例）
- **前置**：M1–M5 已合入（`624e979`、`ebabfcc`、`ef3899f`、`6f8ba02`、`ac3f15c`）。行号以 HEAD `963374c` 为准；实施中按函数名/文本锚点定位，不要硬按行号。
- **基线**：`uv run pytest` → 987 passed（2026-10-19 本机实测）。

---

## UX Design

### Before
```
┌ 主界面 ──────────────────────────────────────────────────────┐
│ ①处理素材  ②生成成片  浏览素材  改目标时长  剪辑偏好  …       │
│   （没有「确认与提问」入口；confirm.html 只能手敲 URL）        │
│ 分镜表：字幕只有前 28 字；镜头截短了字幕还是整句开头           │
│ 预览片：字幕是宋体                                             │
└──────────────────────────────────────────────────────────────┘
确认页：「保存并确认」→ 只写 brief_answers.json，成片不变
剪辑偏好：原话「嗯，对，就九千八」→ 碎片「嗯」「对」命中几十句全被强制进片
```

### After
```
┌ 主界面 ──────────────────────────────────────────────────────┐
│ ①处理素材  ②生成成片  确认与提问  浏览素材  改目标时长  …     │
│ 分镜表：字幕是整句；截短的镜头只含镜头内说完的分句             │
│ 预览片：字幕是冬青黑体简体（Hiragino Sans GB）                 │
│ 黄条（需要你留意）：「指定原话『…』在文稿里没找到」/          │
│   「主角『老师』无法对应到说话人，未生效」/                    │
│   「3 条人工裁决对应的句子重新分析后变了，已不套用：S012…」     │
└──────────────────────────────────────────────────────────────┘
确认页：「保存并确认」→ 已保存 · 正在按你的答案重新选段… → 选段完成（或失败原因）
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 主界面按钮栏 | 无确认页入口 | 新按钮「确认与提问」（新标签页打开 confirm.html） | D1 |
| 确认页「保存并确认」 | 只保存 | 保存 + 服务端起 `select` 任务；页面轮询显示「正在重新选段 / 完成 / 失败：…」；已有任务在跑时显示冲突原因（答案已保存） | D1 |
| 确认页「只保存」 | 只保存 | 不变（不触发选段） | |
| 剪辑偏好「必留原话」提示 | 「用逗号分隔」 | 「每句一行（也可以用逗号分隔）」 | D5，文案在 calibrate.html |
| 黄条警告 | 无对应提示 | 原话没找到、focus 无法映射、silence 结尾不支持、人工裁决失效 | 走现有 `selection.json.warnings` → `notices.project_warnings`，前端无改动 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `pipeline/select.py` | 1-563 | KI-01/02/03/04/06 主战场；`select()` 各阶段顺序、`_ensure_must_keep`（GL-08）不可破坏 |
| P0 | `pipeline/classify.py` | 1-242 | KI-06/07/08/58；`_protected`/`_cap_pending`（GL-09/24）不可破坏 |
| P0 | `tests/test_select.py` | 1-389 | `seg()` 助手、必留随机不变量测试 `test_must_keep_invariant_randomized` |
| P0 | `tests/test_classify.py` | 1-211 | `seg()` 助手、保护段断言 |
| P1 | `pipeline/understand_text.py` | 102-191, 298-336 | KI-09/10 |
| P1 | `pipeline/review.py` | 1-100 | KI-12；`_LOCK` 与 `OverridesCorrupt`（GL-18）不可破坏 |
| P1 | `pipeline/questions.py` | 1-139 | KI-04 |
| P1 | `gui/server.py` | 119-238, 404-420, 656-673 | KI-05；server 789 行，新增逻辑必须放 `gui/confirm.py` |
| P1 | `gui/jobs.py` | 29-31, 152-178, 391-403 | `start_job` / `JobConflict` / `select` 任务 |
| P1 | `aicut.py` | 296-321, 491-494, 587-600, 609-650 | KI-07 预设传入、KI-11；aicut 931 行，**净行数不得增加** |
| P2 | `pipeline/understand_audio.py` | 59-108 | KI-08 信号含义 |
| P2 | `pipeline/build_documentary.py` | 88-131 | KI-11 独立脚本切片 |
| P2 | `pipeline/render_preview.py` | 25-36 | KI-73 |
| P2 | `pipeline/notices.py` | 29-41 | 选段警告如何到黄条 |
| P2 | `gui/static/confirm.html`、`gui/static/index.html:142-149,609-617`、`gui/static/jobs.js:56-69` | | KI-05 前端 |
| P2 | `tests/conftest.py` | 1-132 | `gui_server`、`call`、`make_project` |
| P2 | `tests/test_server_jobs.py` | 19-55 | `fake_command`、`wait_for`、`get_job` |
| P2 | `tests/test_understand_text.py` | 1-48, 260-300 | `FakeClient`（靠「归并成」识别话题分段调用） |

## External Documentation
No external research needed — feature uses established internal patterns.
本机实测事实（替代外部调研）：
```
KEY_INSIGHT: ffmpeg drawtext 只有 fontfile / font 选项，没有 face index；.ttc 只能用第 0 个字形。
  fc-query 实测：Hiragino Sans GB.ttc #0 = HiraginoSansGB-W3（简体）；
  STHeiti Medium.ttc #0 = STHeitiTC-Medium（繁体字形）；
  AssetsV2/.../PingFang.ttc #0 = PingFangHK-Regular（港繁字形），路径为哈希目录、会随系统更新变化。
APPLIES_TO: Task 12（KI-73）
GOTCHA: 路径含空格，drawtext 里已用单引号包住 fontfile='…'，空格安全；不要改成 font= 名称（LGPL 构建是否带 fontconfig 未知）。
```
```
KEY_INSIGHT: 样本项目 projects/2026-09-01_活动（140 句 / 19 话题 / 56 句关键信息）：
  抢话代理命中 9 句，全部是 31.9–34.9s 的句子（format_transcript.MAX_SEG=35 切出的假边界，停顿 0.0s）；
  必留话题：现词表 14/19；收窄词表 13；收窄 + min_key_hits=2 → 12；全文关键信息占比 40%，所以 0.30 阈值本身偏宽。
APPLIES_TO: Task 2（KI-07/08）、Notes D6/D7
```

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: pipeline/select.py:19-39
HARD_TYPES = {"金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑"}
MIN_SHOT = 1.5      # 最短镜头
MAX_SHOT = 25.0     # 最长镜头，超过就截断（访谈镜头可以长一点）
MUST_KEEP_REASON = "剪辑师标记必留"
MUST_KEEP_OVER_WARNING = "必留内容共 {must}，超过目标 {target}：已全部保留，请重新设定成片时长"
```
- 阈值/文案一律模块级大写常量，中文文案带 `{占位}` 用 `.format()`；私有函数 `_snake`，公开函数无下划线；模块 docstring 中文说明「为什么」。

### ERROR_HANDLING
```python
# SOURCE: pipeline/understand_text.py:182-191
def _normalize(item: dict) -> dict:
    """模型给的形状不对（如 entities 是数字）→ LLMError，让这一批重试，而不是让整个任务崩掉。"""
    entities = item.get("entities") or []
    if not isinstance(entities, list):
        raise LLMError(ANNOTATION_SHAPE_ERROR.format(
            detail=f"entities 是 {type(entities).__name__}"))
```
```python
# SOURCE: aicut.py:289-290（CLI 边界：领域异常 → die(人话)）
    except LLMError as exc:  # GL-09：含 AnnotationIncomplete；不能当成功往下走
        die(str(exc))
```
- 模型输出形状不对 → `LLMError`（可重试）；业务约束被破坏 → 领域异常（如 `select.SelectionError`）；CLI 用 `die()`；**不静默降级**，降级必须进 `warnings`。

### LOGGING_PATTERN
```python
# SOURCE: pipeline/select.py:262-273（pipeline 层不打日志，警告随结果返回）
    warnings = [MUST_KEEP_EMPTY_WARNING.format(ids="、".join(skipped))] if skipped else []
    ...
    return {"must_keep_ids": must_ids, ..., "warnings": warnings}
```
```python
# SOURCE: pipeline/notices.py:35-37（warnings 自动进剪辑台黄条）
    out += _texts(_read(workdir / "segments_scored.json").get("warnings"))
    sel = _read(workdir / "selection.json")
    out += _texts([sel.get("over_target_warning")]) + _texts(sel.get("warnings"))
```
- 本里程碑所有新提示都放进 `selection.json["warnings"]` 或 `segments_scored.json["warnings"]`，CLI 由 `_report_selection` / `cmd_score` 逐条 `warn()`，GUI 自动显示，**不新增日志调用**。

### REPOSITORY_PATTERN
```python
# SOURCE: pipeline/review.py:52-61（读改写串行 + 原子写）
def set_level(workdir: Path, segment_id: str, level: int) -> dict:
    if level not in LEVELS:
        raise ValueError(f"非法档位：{level}")
    with _LOCK:
        data = load(workdir)
        item = data.setdefault(segment_id, {})
        item["level"] = level
        item["at"] = _now()
        _save(workdir, data)
        return data
```
```python
# SOURCE: pipeline/schema.py:114-124
def write_json(path: Path, obj: Any, *, indent: int | None = 2) -> None:
    """原子写：每次用唯一临时文件，并发写同一路径不会互相踩。indent=None 写紧凑 JSON。"""
```

### SERVICE_PATTERN
```python
# SOURCE: pipeline/select.py:178-184（新列表、不改输入）
def _ensure_must_keep(segments: list[dict], shots: list[dict],
                      weights: dict | None) -> list[dict]:
    """GL-08：必留段无视档位/话题/预算/exclude/镜头长度，一律整段进片；已入选但被截短的恢复整段。"""
    must = {s["id"]: s for s in segments if s.get("must_keep")}
    kept = [x for x in shots if x["segment_id"] not in must]
    restored = [_must_keep_shot(seg, weights) for seg in must.values() if _has_length(seg)]
    return sorted(kept + restored, key=lambda x: x["start"])
```
```python
# SOURCE: gui/jobs.py:391-403（界面请求 → 子命令参数，先过白名单）
def job_extra(pdir: Path, task: str, body: dict, title: str | None) -> list[str]:
    extra: list[str] = []
    ...
    elif task == "select" and body.get("target") is not None:
        extra += ["--target", str(schema.check_target_duration(body["target"]))]
```
```python
# SOURCE: gui/server.py:404-420（任务启动的错误映射）
        except JobConflict as e:  # 含 StaleJob（job_id 为 None：上次留下的进程，界面无法接管）
            return self._json({"error": str(e), "job_id": e.job_id, "task": e.task,
                               "project": e.project}, 409)
```

### TEST_STRUCTURE
```python
# SOURCE: tests/test_select.py:9-12
def seg(i, start, dur, topic, *, level=3, key=False, must=False, text="", info=""):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur, "topic": topic,
            "level": level, "key_info": key, "must_keep": must,
            "info_type": info, "text": text or f"第{i}句", "signals": {}}
```
```python
# SOURCE: tests/test_classify.py:8-10
def seg(i, start, dur=6.0, **kw):
    return {"id": f"S{i:03d}", "start": start, "end": start + dur,
            "text": kw.pop("text", "这是一句话"), **kw}
```
```python
# SOURCE: tests/test_server_jobs.py:24-33
def fake_command(monkeypatch, jobs, argv):
    seen = []
    def job_command(task, name, extra):
        seen.append((task, name, list(extra)))
        return argv
    monkeypatch.setattr(jobs, "job_command", job_command)
    return seen
```
```python
# SOURCE: tests/conftest.py:119-132
def make_project(root, name="p1", shots=None, **files):
    """建一个最小项目；files 的键是相对路径，例：make_project(root, **{"work/proxy.mp4": b"..."})。"""
```
- 测试名用 `test_<行为>`，注释用 `# KI-xx：…` 标明来源；断言用 AAA，不打真实网络（LLM 一律假客户端）。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `pipeline/select_rules.py` | CREATE | KI-03/04/02：答案→规则（按题 id 查）、ending/pacing/focus 归一、必留原话解析与命中。从 select.py 搬出 `_rules`/`_norm_ending`，避免 select.py 膨胀 |
| `pipeline/shot_sub.py` | CREATE | KI-01：按镜头区间生成字幕文本 |
| `gui/confirm.py` | CREATE | KI-05：确认页数据 / 保存答案 / 确认后起 select 任务（server.py 已 789 行） |
| `pipeline/select.py` | UPDATE | KI-01/02/03/04/06/12 接入；删 `[:28]`；hook/结尾修正；warnings 汇总 |
| `pipeline/classify.py` | UPDATE | KI-06/07/08/58 |
| `pipeline/questions.py` | UPDATE | KI-04：同题 label 去重；兜底关键信息选项改 `must_lines`；focus value 限定 |
| `pipeline/understand_text.py` | UPDATE | KI-09/10 |
| `pipeline/summarize.py` | UPDATE | KI-10 |
| `pipeline/review.py` | UPDATE | KI-12 锚点 |
| `pipeline/build_documentary.py` | UPDATE | KI-11：`clip_key`、`preview_fingerprint`、切片 manifest |
| `pipeline/render_preview.py` | UPDATE | KI-73 |
| `aicut.py` | UPDATE | KI-07 传预设 `must_topic`；KI-11 改用 `build_documentary.clip_key/preview_fingerprint`（删本地 `clip_key`，净行数 ≤ 931） |
| `gui/server.py` | UPDATE | KI-05：`/api/confirm`、`/api/confirm/answers` 委托 `gui/confirm.py`（净行数减少） |
| `gui/static/index.html` | UPDATE | KI-05：按钮「确认与提问」+ `openConfirm()` |
| `gui/static/confirm.html` | UPDATE | KI-05：确认后显示选段任务进度 |
| `gui/static/calibrate.html` | UPDATE | KI-03：原话提示文案（D5） |
| `presets/纪实3min.json` | UPDATE | KI-07：`must_topic` 配置 |
| `tests/test_select_rules.py` | CREATE | KI-02/03/04 |
| `tests/test_shot_sub.py` | CREATE | KI-01 |
| `tests/test_confirm_flow.py` | CREATE | KI-05（server + 静态页） |
| `tests/test_render_preview.py` | CREATE | KI-73 |
| `tests/test_select.py` / `test_classify.py` / `test_questions.py` / `test_understand_text.py` / `test_summarize.py` / `test_review.py` / `test_build_documentary.py` / `test_aicut_build.py` / `test_understand_audio.py`（不改）/ `test_static_pages.py` | UPDATE | 各 KI 的回归用例 |
| `docs/known-issues.md` | UPDATE（实施完成时） | 各 KI 状态填提交号（按登记册约定；不是本计划阶段改） |

## NOT Building

- 不做 c 路画面（景别/人脸/OCR）、不做说话人命名/声纹识别（focus 只能映射到「说话最多的人」）。
- 不做「留白/空镜」结尾的自动 B-roll 插入（只给警告）。
- 不改 `format_transcript` 的切段规则（35s 上限）——KI-08 只在判档侧收紧。
- 不改 `_split_large` 的「(n/m)」拆分与必留占比逐块计算方式（D6 只外置参数）。
- 不碰 M7–M9 的条目：`%` 转义（KI-76，注意 `render_preview.esc()` 当前已转义 `%`，留给 M7 核实）、ffmpeg 超时、`.done` 输入指纹（KI-62）、`select.run` 的非原子 `write_text`、`confirm.html` 多选答案非数组（KI-49）。
- 不改 `/api/job` 的协议；确认页不复用 `jobs.js`（它依赖 index.html 的 `state`/弹窗）。
- 不新增 lint/typecheck 配置。

---

## Step-by-Step Tasks

> 每个任务：先写列出的失败测试 → `uv run pytest <文件> -q` 看到 RED → 实现 → GREEN → 跑全量。

### Task 1: `pipeline/select_rules.py` —— 答案→规则（KI-04 规则部分 + KI-02 归一）
- **ACTION**: 新建模块，把 `select._rules`、`select._norm_ending` 搬过来并修正；`select.py` 保留别名 `_rules = select_rules.rules_from_answers`、`_norm_ending = select_rules.norm_ending`（既有测试 `test_rules_from_question_answers`、`test_ending_value_normalized_from_label` 不改也要过）。
- **TESTS FIRST**（`tests/test_select_rules.py`）:
  - `test_same_label_in_two_questions_uses_own_rule`：q1、q2 都有 label「全部」，q1 绑 `must_topics:["讲合同"]`、q2 绑 `exclude:["聊吃饭"]`；answers `{"q1":"全部"}` → `must_topics==["讲合同"]` 且 `exclude_topics==[]`。
  - `test_pacing_uses_rule_value_not_label`：label「慢慢来」、rule `{"kind":"pacing","value":"tight"}` → `pacing=="tight"`；label「紧凑」、value `"normal"` → `"normal"`。
  - `test_focus_value_kept`：→ `rules["focus"]=="main"`。
  - `test_must_lines_kind_collected`：rule `{"kind":"must_lines","value":["九千八包含所有耗材"]}` → `rules["must_lines"]==["九千八包含所有耗材"]`。
  - `test_norm_ending_info`：`norm_ending("info")=="info"`、`norm_ending("最后一个关键信息")=="info"`、`norm_ending("情绪收尾")=="emotion"`。
  - `test_answers_for_unknown_question_ignored`、`test_non_list_multi_answer_tolerated`（answers 值是数字/None 不抛）。
- **IMPLEMENT**:
```python
KINDS = ("must_topics", "exclude", "ending", "focus", "pacing", "must_lines")
ENDINGS = {"sign", "leave", "emotion", "silence", "info"}
PACINGS = {"tight", "normal"}

def rules_from_answers(answers: dict, questions: dict | None) -> dict:
    """答案 → 选段规则。按「题 id → label」查规则：不同题截断后同名的 label 不再互相覆盖（KI-04）。"""
    rules = {"must_topics": [], "exclude_topics": [], "ending": None,
             "focus": None, "pacing": "normal", "must_lines": []}
    by_q = {q.get("id"): {o.get("label"): o.get("rule") or {} for o in q.get("options") or []}
            for q in (questions or {}).get("questions") or [] if isinstance(q, dict)}
    for qid, value in (answers or {}).items():
        options = by_q.get(qid) or {}
        for label in (value if isinstance(value, list) else [value]):
            rules = _apply_rule(rules, options.get(label) or {})
    return rules
```
  `_apply_rule` 返回新 dict（不就地改）：`must_topics`/`exclude`→extend；`ending`→`norm_ending`；`focus`→`str(val)`；`pacing`→`norm_pacing(val)`（val in PACINGS 直接用；含「紧/快」→tight；否则 normal）；`must_lines`→extend 非空字符串。
  `norm_ending`：在原 `_norm_ending`（`select.py:52-64`）基础上加 `"info"` 与关键词 `("信息",)→info`，放在 emotion 之前判断（「情绪」不含「信息」，无冲突）。
- **MIRROR**: NAMING_CONVENTION；SERVICE_PATTERN（返回新对象）。
- **IMPORTS**: `from __future__ import annotations`；select.py 加 `from pipeline import classify, review, select_rules, shot_sub`。
- **GOTCHA**: 旧版 `_rules` 对没有 questions 的情况「退化为按标签猜」实际上什么也不做（labels 为空）——新实现同样返回默认规则，保持一致。`select.run` 里的 `stored_rules` 优先级见 Task 6。
- **VALIDATE**: `uv run pytest tests/test_select_rules.py tests/test_select.py -q`。

### Task 2: classify —— 信号并入 / 必留口径统一 / 词表外置 / 抢话收紧（KI-06、KI-58、KI-07、KI-08）
- **ACTION**: 修改 `pipeline/classify.py`；`aicut.cmd_score` 传预设配置；`presets/纪实3min.json` 加字段。
- **TESTS FIRST**（`tests/test_classify.py` 追加）:
  - KI-06 `test_scored_segments_carry_audio_signals`：`classify([seg(1,0)], {"S001":{"rel_db":3.0}})` → `segments[0]["signals"]["rel_db"]==3.0`；无音频时 `signals=={}`。
  - KI-06 `test_attach_signals_backfills_without_mutation`：`classify.attach_signals(segs, {"S001":{...}})` 返回新列表，原段无 `signals` 键。
  - KI-58 `test_ratio_must_topic_protects_short_plain_segment`：话题「安排宿舍」4 句关键信息 + 1 句 `dur=4, info_type="事实陈述"`（名字不含词）→ 该句 `level==2` 且理由含「必留话题」；且 `topics` 中该话题 `must is True`。（修前会因 `dur<6` 判 1）
  - KI-07 `test_must_topic_words_from_config`：`classify(..., must_topic={"words":["宿舍"]})` 时「安排宿舍」名字命中；默认配置下「建议选养生美体课程」名字**不再**因「课程」命中（占比低于阈值时 `must is False`）。
  - KI-07 `test_min_key_hits_required_for_ratio_rule`：话题 1 句且是关键信息（占比 100%）→ 默认 `min_key_hits=2` 下不是必留。
  - KI-07 `test_run_passes_must_topic_config(tmp_path)`：`run(..., must_topic={"words":["宿舍"], "key_ratio":0.9, "min_key_hits":1})` 生效。
  - KI-08 `test_interrupt_proxy_on_long_split_segment_not_usable`：audio `{"interrupt":True,"duration":34.5,"rel_db":0.5}`、`dur=34.5`、无关键信息 → `level != 3`。
  - KI-08 `test_interrupt_proxy_with_raised_voice_usable`：`{"interrupt":True,"duration":8,"rel_db":1.5}` → `level==3`，理由「出现抢话/被打断」。
  - KI-08 `test_real_overlap_usable`：`{"overlap":True}` → `level==3`。
  - 既有 `test_must_topic_becomes_pending`（「讲解合同条款」）、`test_key_ratio_must_topic_also_protected`（20/60 = 33%、key_hits 20）必须仍然通过。
- **IMPLEMENT**:
```python
# 必留话题判定参数：预设 presets/<名>.json 的 "must_topic" 可覆盖（KI-07）
DEFAULT_MUST_TOPIC = {"words": ("合同", "退费", "价格", "就业", "工资", "资格", "签约", "缴费"),
                      "key_ratio": 0.30, "min_key_hits": 2}
INTERRUPT_MAX_DUR = 30.0      # 秒：≥30s 的句子多半是 35s 长度上限切出来的假边界（KI-08）
INTERRUPT_MIN_REL_DB = 1.0    # 代理信号还要求音量高于中位 1dB

def must_topic_config(raw: dict | None) -> dict:
    """预设里的 must_topic → 规整后的配置；缺省/类型不对的字段用默认值。"""

def attach_signals(segments: list[dict], audio_by_id: dict) -> list[dict]:
    """KI-06：把 a 路信号并入每句（新列表），选段打分与情绪结尾才拿得到 rel_db。"""
    return [{**s, "signals": dict(audio_by_id.get(s["id"]) or {})} for s in segments]

def _is_interrupt(audio: dict) -> bool:
    if audio.get("overlap"):
        return True
    return (bool(audio.get("interrupt"))
            and float(audio.get("duration") or 0) < INTERRUPT_MAX_DUR
            and float(audio.get("rel_db") or 0) >= INTERRUPT_MIN_REL_DB)
```
  - `_level_of(seg, audio, must_topic: bool)` 中 `interrupt = (audio or {}).get("interrupt", False)` 改为 `interrupt = _is_interrupt(audio or {})`。
  - `_topic_must(name)` → `_topic_must(name, words)`；`_must_topic_names(scored, cfg)`：`n for n in count if _topic_must(n, cfg["words"]) or (keys[n] >= cfg["min_key_hits"] and keys[n] / count[n] >= cfg["key_ratio"])`。删除 `MUST_TOPIC_WORDS`、`KEY_RATIO_MUST`（先 `grep -rn "MUST_TOPIC_WORDS\|KEY_RATIO_MUST"` 确认没有外部引用）。
  - `classify(...)` 新增关键字参数 `must_topic: dict | None = None`；流程改为：
```python
    cfg = must_topic_config(must_topic)
    topical = [{**seg, "topic": seg.get("topic") or topic_of.get(seg["id"], "")} for seg in segments]
    must_names = _must_topic_names(topical, cfg)            # KI-58：先定口径，只依赖 topic / key_info
    base = []
    for seg in attach_signals(topical, audio_by_id):
        lv, why = _level_of(seg, seg["signals"], (seg["topic"] or "未归类") in must_names)
        flags = visual_by_id.get(seg["id"], {}).get("flags") or []
        base.append({**seg, "level": lv, "level_reason": why, "visual_flags": flags})
```
    之后 `_apply_dark`、`_cap_pending`、`_assemble(scored, total_target, must_names)` 不变（同一个 `must_names`）。
  - `run(..., must_topic: dict | None = None)` 透传。
  - `aicut.cmd_score`：`preset = load_json(PRESETS / f"{c['preset']}.json", {})`（同 `cmd_brief` 的写法，`aicut.py:467`），`classify.run(..., must_topic=preset.get("must_topic"))`——用把现有多行参数合并的方式保持净行数不增。
  - `presets/纪实3min.json` 加：`"must_topic": {"words": ["合同","退费","价格","就业","工资","资格","签约","缴费"], "key_ratio": 0.3, "min_key_hits": 2}`。
- **MIRROR**: SERVICE_PATTERN；NAMING_CONVENTION。
- **IMPORTS**: 无新增。
- **GOTCHA**: `_assemble` 的默认参数 `must_names=None` 时会调用 `_must_topic_names(scored)`——改签名后给它传 `cfg`（默认 `must_topic_config(None)`）。`test_classify_does_not_mutate_input` 必须仍过：所有新步骤返回新 dict。scored 文件会多出 `signals` 字段（约 6 个数字/句），`gui/server.browse_payload` 只透传，不受影响。
- **VALIDATE**: `uv run pytest tests/test_classify.py tests/test_aicut_cli.py -q`；手工：`uv run python -c "from pipeline import classify; import json; ..."` 对样本项目 `segments_text.json` 重跑（写到 scratchpad）应得 12/19 必留、抢话 0。

### Task 3: 成片字幕整句 + 随镜头裁剪（KI-01）
- **ACTION**: 新建 `pipeline/shot_sub.py`；`select.py` 去掉 4 处 `[:28]`，在 `select()` 最后统一生成 `sub`；`select.run` 从 `work/segments.json` 取分句 `lines`。
- **TESTS FIRST**:
  - `tests/test_shot_sub.py`：
    - `test_full_text_when_shot_covers_segment`：35 字整句、镜头覆盖全段 → 原文全文。
    - `test_lines_inside_shot_only`：lines `[(0,3,"第一句"),(3,6,"第二句"),(6,9,"第三句")]`，镜头 `[0,6]` → `"第一句第二句"`。
    - `test_line_counted_when_mostly_inside`：镜头 `[0,4.6]` → 第二句覆盖 1.6/3 < 50% 不算 → `"第一句"`；镜头 `[0,4.6]` 但第二句 `(3,4.8)` → 算。
    - `test_proportional_cut_without_lines`：20 字、段 10s、镜头前 5s → 前 10 字。
    - `test_empty_or_zero_length_segment`：空文本 → `""`；零长段 → 原文。
  - `tests/test_select.py` 追加：
    - `test_sub_is_full_sentence_not_28_chars`：40 字 must_keep 段 → `sub` 长度 40。
    - `test_budget_clipped_shot_sub_trimmed`：话题预算 10s、段 20s（非必留、有 lines）→ 镜头 `end` 被截且 `sub` 只含镜头内分句。
    - `test_extended_shot_sub_recomputed`：经「延伸已有镜头」阶段延长后 `sub` 覆盖到新出点。
    - `test_run_reads_lines_from_segments_json(tmp_path)`：`tmp_path/"segments.json"` 含 lines，`select.run` 输出 `shots-selected.json` 的 `sub` 已裁剪。
- **IMPLEMENT**（`pipeline/shot_sub.py`）:
```python
LINE_INSIDE_RATIO = 0.5   # 分句至少一半落在镜头里才算这镜的字幕

def sub_for(seg: dict, start: float, end: float) -> str:
    """镜头 [start, end] 的字幕：整句；截短时只留镜头内的分句（KI-01）。"""
    text = seg.get("text") or ""
    s0, s1 = float(seg["start"]), float(seg["end"])
    if not text or s1 <= s0 or (start <= s0 + _EPS and end >= s1 - _EPS):
        return text
    lines = [l for l in seg.get("lines") or [] if isinstance(l, dict)]
    if lines:
        return "".join(str(l.get("text") or "") for l in lines if _inside(l, start, end))
    keep = round(len(text) * (min(end, s1) - max(start, s0)) / (s1 - s0))
    return text[:keep] if start <= s0 + _EPS else text[-keep:] if keep else ""
```
  `select.py`：删除各处 `"sub": ...`；`select()` 在 `_fix_ending` 之后、编号之前：
```python
    by_id = {s["id"]: s for s in segments}
    shots = [{**s, "sub": shot_sub.sub_for(by_id[s["segment_id"]], s["start"], s["end"])}
             for s in shots]
```
  `select.run`：`lines_by_id = {s["id"]: s.get("lines") or [] for s in _read_segments(out_dir / "segments.json")}`（文件不存在/坏 → `{}`），`segments = [{**s, "lines": lines_by_id.get(s["id"], [])} for s in review.apply(...)]`。
- **MIRROR**: SERVICE_PATTERN；TEST_STRUCTURE（`seg()` 助手加 `lines=` 关键字参数时用 `**kw` 方式扩展，不改既有调用）。
- **IMPORTS**: `shot_sub` 里只用标准库。
- **GOTCHA**: `selection.json` 会因 lines 变大——**`lines` 只放在内存里的 segments 上，不能写进 shots/selection**（shot 构造只取 id/start/end/…）。`compose_timeline`（`aicut.py:535-584`）按 `max_chars` 自动拆卡，整句字幕会变成多张卡，属预期。`markdown()` 表格用全文，不截断。
- **VALIDATE**: `uv run pytest tests/test_shot_sub.py tests/test_select.py -q`。

### Task 4: hook 与结尾（KI-02）
- **ACTION**: 改 `select._fix_ending` 与 `END_KEYWORDS`；`_fix_ending` 返回 `(shots, warnings)`。
- **TESTS FIRST**（`tests/test_select.py` 追加；既有 `test_ending_moves_matching_shot_last` 必须仍过）:
  - `test_ending_never_moves_hook`：hook 镜头（关键信息最高分）文本含「缴费」、另一镜也含「签字」→ 片头仍是 hook，片尾是另一镜；若只有 hook 命中 → 顺序不变。
  - `test_ending_picks_last_match_in_time`：两镜都含「签合同」，取时间更晚的那镜。
  - `test_ending_keywords_not_too_broad`：文本「我们走进教室」「谢谢老师」在 `sign/leave` 下都不触发移动。
  - `test_emotion_ending_uses_loudest_non_hook`：`signals.rel_db` 分别 0.5/3.2/1.1 → 3.2 那镜到最后；全部 <1.0 → 不移动。
  - `test_info_ending_moves_last_key_info_shot`：`ending="info"` → 时间上最后一个 `key_info` 镜头到最后。
  - `test_silence_ending_warns`：`ending="silence"` → 顺序不变，`res["warnings"]` 含 `ENDING_SILENCE_WARNING`。
- **IMPLEMENT**:
```python
END_KEYWORDS = {
    "sign": ("签合同", "签字", "签约", "签了", "缴费", "交钱", "转账", "付款", "刷卡"),
    "leave": ("走了", "离开", "出门", "下楼", "再见", "拜拜"),
}
EMOTION_MIN_REL_DB = 1.0   # 情绪结尾：音量至少高于中位 1dB 才算「有力」
ENDING_SILENCE_WARNING = "结尾选了「留白」：程序不会自动加空镜，请在剪映里手动补"

def _fix_ending(shots, segments, ending) -> tuple[list[dict], list[str]]:
    """按结尾偏好把最合适的镜头放到最后；开场 hook 永远不动（KI-02）。"""
    if not shots or not ending:
        return shots, []
    if ending == "silence":
        return shots, [ENDING_SILENCE_WARNING]
    by_id = {s["id"]: s for s in segments}
    pool = sorted((s for s in shots if s.get("role") != "hook"), key=lambda s: s["start"])
    best = _ending_pick(pool, by_id, ending)
    if best is None or shots[-1] is best:
        return shots, []
    return [s for s in shots if s is not best] + [best], []
```
  `_ending_pick`：sign/leave → `[s for s in pool if any(k in text for k in keys)][-1]`；info → 最后一个 `by_id[...]["key_info"]`；emotion → `max(pool, key=rel_db)` 且 `rel_db >= EMOTION_MIN_REL_DB`。
  `select()` 收集 `ending_notes`，最后 `"warnings": [*report["warnings"], *notes]`（notes 汇总 Task 4/5/6 的提示）。
- **MIRROR**: SERVICE_PATTERN（新列表，不 `remove/append` 原列表）。
- **GOTCHA**: `_build_hook`（`select.py:446-461`）目前 `shots.remove(hook)` 就地修改——顺手改成返回新列表（不改行为）。随机不变量测试 `test_must_keep_invariant_randomized` 会带 `ending` 跑 300 轮，必须仍过。
- **VALIDATE**: `uv run pytest tests/test_select.py -q`。

### Task 5: 必留原话精确命中（KI-03）
- **ACTION**: `select_rules` 增加 `parse_must_lines(raw)`、`resolve_must_lines(quotes, segments)`；`select._force_lines` 改为按「已解析的段 id」强制；`select.run` 改用 `parse_must_lines`。
- **TESTS FIRST**:
  - `tests/test_select_rules.py`：
    - `test_parse_splits_on_newline_and_semicolon_keeps_commas`：`"嗯，对，就九千八\n找不到工作不白学吗；包吃住"` → `["嗯，对，就九千八", "找不到工作不白学吗", "包吃住"]`。
    - `test_resolve_whole_quote_ignoring_punctuation`：段文本「嗯对就九千八包含耗材」（ASR 无标点）、原话「嗯，对，就九千八」→ 命中该段，且只命中 1 段（另有 10 句含「对」「嗯」）。
    - `test_resolve_falls_back_to_comma_fragments`：`"找不到工作不白学吗，九千八包含所有耗材"`（两段各含一半）→ 两段都命中。
    - `test_short_fragments_ignored_with_warning`：碎片 `<4` 字被忽略并产生 `MUST_LINE_TOO_SHORT` 警告。
    - `test_quote_hits_only_first_segment_in_time`：两句都含该原话 → 只命中较早的一句。
    - `test_unmatched_quote_warns`：→ `MUST_LINE_NOT_FOUND` 含原话前 12 字。
  - `tests/test_select.py`：
    - `test_must_line_fragment_does_not_flood_cut`：calibration `"嗯，对，就九千八"`，30 句含「对」→ 强制镜头只有 1 个。
    - 既有 `test_must_lines_force_segment_into_cut`、`test_forced_shot_survives_trim` 仍过（「不白学吗」恰好 4 字）。
- **IMPLEMENT**:
```python
MUST_LINE_MIN_CHARS = 4
MUST_LINE_NOT_FOUND = "指定原话「{line}」在文稿里没找到（可能被分成了两句），没有强制保留"
MUST_LINE_TOO_SHORT = "指定原话片段「{line}」太短（少于 {n} 字），已忽略"
_QUOTE_SPLIT = re.compile(r"[\n\r；;]+")
_FRAGMENT_SPLIT = re.compile(r"[，,、]+")
_PUNCT = re.compile(r"[\s，。！？、,.!?；;：:“”\"'‘’…（）()]+")

def parse_must_lines(raw) -> list[str]:
def resolve_must_lines(quotes: list[str], segments: list[dict]) -> tuple[list[str], list[str]]:
    """原话 → 要强制进片的段 id（每条原话/碎片只取时间上最早的一段）+ 警告。"""
```
  `select._force_lines(segments, shots, seg_ids, target, weights, max_shot)`：只对 `seg_ids` 中未入选的段追加强制镜头（保留现有 `_clip`/`MIN_SHOT` 逻辑与 reason「剪辑员指定必须保留」）。`select()` 中：
```python
    forced_ids, line_notes = select_rules.resolve_must_lines(rules.get("must_lines") or [], segments)
    shots = _force_lines(segments, shots, forced_ids, target, weights, max_shot)
```
  `select.run`：`lines = select_rules.parse_must_lines((calibration or {}).get("must_lines"))`；`rules = {**rules, "must_lines": [*rules.get("must_lines", []), *lines]}`（来自确认页兜底题的原话 + 剪辑偏好）。
- **MIRROR**: NAMING_CONVENTION（文案常量）。
- **GOTCHA**: `style.normalize` 截断到 200 字符且保留换行；CLI `--must-lines` 是单行，仍按逗号兜底可用。`rules` 被写进 `selection.json["rules"]`，`must_lines` 列表照常落盘。
- **VALIDATE**: `uv run pytest tests/test_select_rules.py tests/test_select.py -q`。

### Task 6: focus / pacing 生效 + 答案在 select.run 里重算（KI-04 其余）
- **ACTION**: `select_rules` 增加 `max_shot_for(rules)`、`focus_speakers(segments, focus) -> (set[str], warnings)`；`select()` 使用；`select.run` 规则来源调整；`questions.py` 修正。
- **TESTS FIRST**:
  - `tests/test_select.py`：
    - `test_tight_pacing_caps_shot_length`：非必留段 30s、`pacing="tight"` → 镜头 ≤ 12s；`normal` → ≤ 25s；必留段在 tight 下仍整段（GL-08）。
    - `test_focus_main_prefers_main_speaker`：说话人 "1" 总时长最多；同话题两段同分、预算只够一段 → 选 "1" 的那段。
    - `test_focus_unmappable_warns`：`focus="老师"` → 选段结果与无 focus 相同，`warnings` 含 `FOCUS_UNMAPPED_WARNING`。
    - `test_focus_ensemble_no_bonus`。
    - `test_run_recomputes_rules_when_questions_exist(tmp_path)`：`brief_answers.json` 里存的 `rules` 是旧的（`exclude_topics: []`），答案对应 `exclude`；`questions.json` 存在 → 以重算结果为准。既有 `test_stored_rules_win_over_answers`（没有 questions 文件）仍过。
  - `tests/test_questions.py`：
    - `test_normalize_dedupes_truncated_labels`：同题两个 label 前 12 字相同 → 只留第一个。
    - `test_fallback_info_options_bind_must_lines`：没有话题时，兜底 q2 的选项 rule 为 `{"kind":"must_lines","value":[整句原文]}`，不再是空 `must_topics`。
    - `test_prompt_restricts_focus_values`：`questions.Q_USER` 含 `main` 与 `ensemble`。
- **IMPLEMENT**:
```python
PACING_MAX_SHOT = {"tight": 12.0, "normal": 25.0}
FOCUS_BONUS = 2.0
FOCUS_MAIN = {"main", "narrator"}       # 「出镜最多的人」「讲述者」都映射到说话时长最多的人
FOCUS_UNMAPPED_WARNING = "主角「{focus}」无法对应到说话人，这条偏好没有生效"
```
  - `select()`：`max_shot = select_rules.max_shot_for(rules)`，替换函数体内所有 `MAX_SHOT`（`_clip`、首镜、补齐、延伸、`_force_lines`）为参数 `max_shot`；`MAX_SHOT` 常量保留为 normal 默认值。
  - focus：`speakers, notes = select_rules.focus_speakers(segments, rules.get("focus"))`；`segments = [{**s, "focus": s.get("speaker") in speakers} for s in segments]`；`_score` 加一行 `if seg.get("focus"): s += FOCUS_BONUS`。
  - `select.run`：
```python
    rules = (select_rules.rules_from_answers(answers, questions) if questions
             else stored_rules or select_rules.rules_from_answers(answers, None))
```
  - `questions.py`：`_normalize` 内维护 `seen_labels`，截断后重复的跳过；`fallback()` 中 `info_opts` 改为 `{"label": text[:10], "effect": "强制保留这句原话", "rule": {"kind": "must_lines", "value": [text]}}`；`KINDS` 加 `"must_lines"`；`Q_USER` 中 focus 说明改为「focus（主角：value 只能是 main=说话最多的人 或 ensemble=群像）」。
- **MIRROR**: TEST_STRUCTURE；SERVICE_PATTERN。
- **GOTCHA**: `test_run_reallocates_budget_when_target_changed` monkeypatch 了 `select.select(segments, topics, rules, target, weights=None)`——**`select()` 签名不要改**（max_shot/focus 从 `rules` 推出）。`questions._normalize` 对 `kind == "must_lines"` 的 LLM 输出：value 非 list[str] 时跳过该选项。
- **VALIDATE**: `uv run pytest tests/test_select.py tests/test_select_rules.py tests/test_questions.py -q`。

### Task 7: 旧项目的信号回填与人工裁决失效提示接入 select.run（KI-06 收尾 + KI-12 接线）
- **ACTION**: `select.run` 在 `review.apply` 之后：若段落没有 `signals` 且 `out_dir/"segments_audio.json"` 存在 → `classify.attach_signals`；把 `review.stale_ids(...)` 的结果转成警告（Task 10 实现 `stale_ids`，本任务先写测试，可与 Task 10 合并提交）。
- **TESTS FIRST**（`tests/test_select.py`）:
  - `test_run_backfills_signals_from_audio_file(tmp_path)`：scored 段无 `signals`，`segments_audio.json` 里 S002 `rel_db=6` → `ending="emotion"` 时 S002 在片尾。
  - `test_run_warns_stale_overrides(tmp_path)`：overrides 锚点与当前段原文不符且找不到 → `warnings` 含 `OVERRIDES_STALE_WARNING`。
- **IMPLEMENT**: `OVERRIDES_STALE_WARNING = "{n} 条人工裁决对应的句子在重新分析后变了，已不套用：{ids}；请在「浏览素材」重新标"`（ids 最多列 5 个，同 `MUST_KEEP_MISSING_SHOWN`）。
- **GOTCHA**: `segments_audio.json` 结构是 `{"segments":[{"id":..,"signals":{..}}]}`（见 `classify.run:228-230`），复用那段读取逻辑（抽成 `classify.load_audio_signals(path) -> dict`，`classify.run` 与 `select.run` 共用）。
- **VALIDATE**: `uv run pytest tests/test_select.py -q`。

### Task 8: 话题分段分窗 + 模型脏输出校验（KI-09）
- **ACTION**: 改 `understand_text.segment_topics`、`_normalize`、`_merge_topics_via_llm`。
- **TESTS FIRST**（`tests/test_understand_text.py` 追加；`FakeClient` 靠 `"归并成"` 识别话题调用——新提示词**必须保留「归并成」三个字**）:
  - `test_topic_segmentation_windows_long_input`：300 句 → 话题调用 3 次（120/120/60），每次 `max_tokens >= 4000`（FakeClient 记录 kw），最终话题覆盖全部 300 句。
  - `test_topic_window_retried_on_bad_shape`：第一次返回 `["x"]`、第二次正常 → 成功，不抛。
  - `test_topic_window_persistent_failure_raises_llmerror`：一直返回 `{"topics":"oops"}` → `LLMError`，消息含「话题分段」与窗口序号；不写 `out_path`。
  - `test_topic_items_non_dict_and_non_list_ids_skipped`：`{"topics":[5, {"name":"a","segment_ids":"S001"}, {"name":"b","segment_ids":["S001",7]}]}` → 只有 b（ids `["S001"]`），其余兜底并入。
  - `test_key_info_string_false_is_false`：标注 `key_info: "false"` → False；`"true"`/`True`/`1` → True。
  - `test_unknown_info_type_defaults`：`info_type: "价格"` → `"事实陈述"`。
  - `test_merge_topics_non_dict_returns_none`：`_merge_topics_via_llm` 收到 list / groups 非 list / group 非 dict → 返回 None（走 `_cap_topics`），不抛。
- **IMPLEMENT**:
```python
TOPIC_WINDOW = 120           # 话题分段每次最多送这么多句：输出 id 列表不会被 max_tokens 截断（KI-09）
TOPIC_MAX_TOKENS = 4000
TOPIC_RETRIES = ANNOTATE_RETRIES
TOPIC_FAILED_ERROR = "话题分段失败（第 {k}/{n} 段，已重试 {r} 次）：{error}"
INFO_TYPES = ("金额价格", "条款期限", "承诺保证", "资格限制", "异议质疑", "事实陈述", "个人故事", "闲聊寒暄")

def _as_bool(value) -> bool:
    """模型常把布尔写成字符串：只有真值或 "true"/"是"/1 算 True（KI-09）。"""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "是", "1", "yes")
    return value is True or value == 1
```
  `segment_topics(client, segments, *, sleep=None)`：按 `TOPIC_WINDOW` 切窗；每窗 `_topics_once(client, window, n_hint)`（形状校验，非法 → `LLMError`）；重试 `TOPIC_RETRIES` 次（退避复用 `ANNOTATE_BACKOFF` 与 `_sleep`，不可重试错误立即停）；仍失败 → `raise LLMError(TOPIC_FAILED_ERROR.format(...))`。拼接各窗话题后，沿用现有「漏掉的句子并入最后一个话题」「>15 合并」「_split_large」。提示词把「8–15 个话题」改为参数 `{lo}–{hi}`，单窗时仍是 8–15，多窗时 `hi = max(2, ceil(15 * len(window) / len(all)))`。
  `_normalize`：`"info_type": t if (t := str(item.get("info_type") or "")) in INFO_TYPES else "事实陈述"`，`"key_info": _as_bool(item.get("key_info"))`。
  `run()` 调 `segment_topics(client, usable, sleep=sleep)`。
- **MIRROR**: ERROR_HANDLING（形状不对 → LLMError 重试）。
- **GOTCHA**: `test_batching_splits_calls`（90 句 → 1 次话题 + 3 次标注）必须仍过——90 < 120 只切 1 窗。断点续跑（`_resumable`）复用 partial 里的 topics，不重新分段，保持不变。`cmd_text` 已经 `except LLMError → die`，无需改 aicut。
- **VALIDATE**: `uv run pytest tests/test_understand_text.py -q`。

### Task 9: `--model` 真正生效（KI-10）
- **ACTION**: `understand_text.run`、`summarize.run` 在未注入 client 时用 `DeepSeekClient(model=model)`。
- **TESTS FIRST**:
  - `tests/test_understand_text.py::test_model_passed_to_client(tmp_path, monkeypatch)`：monkeypatch `ut.DeepSeekClient` 为记录 kwargs 的假类（`chat_json` 委托 `FakeClient`）→ `run(..., model="deepseek-reasoner")` 时构造参数 `model=="deepseek-reasoner"`；`model=None` 时用 `DeepSeekClient` 默认（不传 model 键）。
  - `tests/test_summarize.py::test_model_passed_to_client`：同上。
- **IMPLEMENT**:
```python
    client = client or (DeepSeekClient(model=model) if model else DeepSeekClient())
```
- **MIRROR**: `pipeline/llm.py:82-96` 构造参数。
- **GOTCHA**: 两处都在 `try` 之外构造 client（summarize 的 `except Exception` 兜底不能吞掉「没有 Key」之外的构造错误——保持现状位置即可）。
- **VALIDATE**: `uv run pytest tests/test_understand_text.py tests/test_summarize.py -q`。

### Task 10: 人工裁决锚点（KI-12）
- **ACTION**: `review.py`：写入时记锚点；`apply` 校验/重定位；新增 `stale_ids`。
- **TESTS FIRST**（`tests/test_review.py` 追加；既有用例全部仍过——它们没有 scored 文件、overrides 无锚点）:
  - `test_set_level_records_anchor_when_scored_exists(tmp_path)`：写 `segments_scored.json`（S001 文本「九千八」start 12.0）→ `set_level` 后 `data["S001"]["anchor"] == {"text": <sha>, "start": 12.0}`。
  - `test_apply_anchor_match_applies`。
  - `test_apply_relocates_by_text_after_resegmentation`：override 记在 S001（文本 A），新分段里 A 变成 S003、S001 变成文本 B → S003 得到 override，S001 不受影响。
  - `test_apply_relocate_prefers_nearest_start`：两段同文本 → 取起点离锚点最近的一段。
  - `test_apply_stale_override_skipped_and_reported`：文本 A 不存在 → 没有任何段被改；`review.stale_ids(segs, ov) == ["S001"]`。
  - `test_legacy_override_without_anchor_applies_by_id`（兼容，D9）。
  - `test_set_must_records_anchor`、`test_anchor_missing_scored_file_ok`。
- **IMPLEMENT**:
```python
def text_key(text: str) -> str:
    """锚点：去空白后的原文哈希（重新分段后句子 id 会变，原文不会）。"""
    return hashlib.sha1(re.sub(r"\s+", "", text or "").encode("utf-8")).hexdigest()[:12]

def _anchor(workdir: Path, segment_id: str) -> dict | None:
    """从 segments_scored.json 取这句的原文与起点；没有分析结果就不记（纯手工流程）。"""

def resolve(segments: list[dict], overrides: dict) -> tuple[dict[str, dict], list[str]]:
    """overrides → {当前段 id: 裁决}，以及对不上任何句子的旧 id（KI-12）。"""

def stale_ids(segments: list[dict], overrides: dict) -> list[str]:
    return resolve(segments, overrides)[1]
```
  `set_level` / `set_must` 在 `_LOCK` 内 `item["anchor"] = a` （`a = _anchor(workdir, segment_id)`，为 None 时不写）。`apply()` 改为先 `mapping, _ = resolve(...)`，再按原循环用 `mapping.get(seg["id"], {})`。resolve 规则：无锚点 → 按 id；有锚点且同 id 段 `text_key` 相同 → 按 id；否则在 `text_key` 相同、且不被别的「按 id 命中」的裁决占用的段里取 `abs(start - anchor.start)` 最小者；都没有 → stale。
- **MIRROR**: REPOSITORY_PATTERN（`_LOCK` + `_save`）；`OverridesCorrupt` 行为不变。
- **IMPORTS**: `hashlib`、`re`、`json`（已有）。
- **GOTCHA**: `_anchor` 读 scored 失败（缺文件/坏 JSON）一律返回 None，**不能**抛出——否则 `/api/browse/level` 会 500。scored 段的 `start` 用 `round(float, 2)` 存。`gui/server.browse_payload` 通过 `review.apply` 自动受益，无需改。
- **VALIDATE**: `uv run pytest tests/test_review.py tests/test_select.py tests/test_server_media_state.py -q`。

### Task 11: 预览/切片缓存绑定出入点（KI-11）
- **ACTION**: `build_documentary.py` 增 `clip_key`（从 aicut 搬来）、`preview_fingerprint`、manifest 切片；`aicut.py` 改用之。
- **TESTS FIRST**:
  - `tests/test_aicut_build.py::test_preview_fingerprint_changes_when_in_out_shift`：timeline 相同（同 id、同时长）但 `shots` 的 in/out 整体平移 2s → `preview_fingerprint` 不同；完全相同 → 相同。
  - `tests/test_aicut_build.py::test_cmd_build_uses_fingerprint`：monkeypatch `aicut.ensure_preview` 记录 tl_hash，平移出入点两次 `cmd_build --version v1` → 两次哈希不同（参考既有 `test_applog_wiring.py:83` 打桩方式）。
  - `tests/test_build_documentary.py::test_main_recuts_when_in_out_changed(tmp_path, monkeypatch)`：monkeypatch `bd.cut_shot` 记录调用、`media_io.complete_or_adopt` 为 True；第一次 main 切 1 次，改 in/out 后再跑 → 再切 1 次；不改 → 0 次。
- **IMPLEMENT**:
```python
def clip_key(shot: dict, src: Path) -> str:
    """切片缓存键：源文件 + 入出点 + 镜头 id，任一变化就重切（KI-11）。"""
    return hashlib.sha1(f"{src}:{shot['in']}:{shot['out']}:{shot.get('id')}"
                        .encode()).hexdigest()[:12]

def preview_fingerprint(timeline: dict, shots: list[dict], src: Path) -> str:
    """预览哈希：timeline 本身 + 每镜切片键。入出点平移但时长不变时 timeline 一模一样（KI-11）。"""
    payload = {"timeline": timeline, "clips": [clip_key(s, src) for s in shots]}
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True)
                        .encode()).hexdigest()
```
  `build_documentary.main`：`manifest = _load_manifest(clips / "manifest.json")`；`key = clip_key(sh, src)`；`if manifest.get(sh["id"]) != key or not media_io.complete_or_adopt(clip): cut_shot(...); manifest = {**manifest, sh["id"]: key}; schema.write_json(clips / "manifest.json", manifest)`。
  `aicut.py`：删除 `clip_key`（`491-494`），`ensure_clips` 用 `build_documentary.clip_key`；`cmd_build` 中 `tl_hash = build_documentary.preview_fingerprint(tl, shots, Path(c["material"]))`（替换 `641-642` 两行为一行）。
- **MIRROR**: `aicut.ensure_clips`（`aicut.py:497-523`）的 manifest 写法。
- **IMPORTS**: build_documentary 加 `hashlib`、`from pipeline import encode, media_io, schema`。
- **GOTCHA**: 先 `grep -rn "aicut.clip_key"` 确认无测试引用（当前无）。旧 `.timeline.sha` 与新指纹不同 → 升级后第一次 build 会重渲染一次预览，属预期。
- **VALIDATE**: `uv run pytest tests/test_aicut_build.py tests/test_build_documentary.py tests/test_applog_wiring.py -q`；`wc -l aicut.py` ≤ 931。

### Task 12: 预览字幕字体（KI-73）
- **ACTION**: 改 `render_preview.FONT_CANDIDATES` 顺序与 `pick_font` 只解析一次。
- **TESTS FIRST**（`tests/test_render_preview.py` 新建）:
  - `test_prefers_hiragino_sans_gb(monkeypatch)`：monkeypatch `rp.Path.exists` / 或把 `FONT_CANDIDATES` 指向 tmp 文件 → 第一个存在者被选中，且候选首位是 `"/System/Library/Fonts/Hiragino Sans GB.ttc"`。
  - `test_build_uses_one_font_for_all_text`：monkeypatch `pick_font` 计数 → `build()` 3 条文字只调用 1 次；filter 中 `fontfile='<路径>'` 原样出现（路径含空格）。
  - `test_no_font_exits`：全部不存在 → `SystemExit`。
- **IMPLEMENT**:
```python
# 首选简体字形：drawtext 只能取 .ttc 第 0 个字形（KI-73）
#   Hiragino Sans GB #0 = W3 简体；STHeiti Medium #0 = 繁体字形；PingFang 已不在 /System/Library/Fonts
FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",                 # 旧版 macOS
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
]
```
  `build()` 开头 `font = pick_font()`，循环里用 `font`。
- **GOTCHA**: 打包版同进程跑 render_preview，字体路径是系统路径，无需打包字体。
- **VALIDATE**: `uv run pytest tests/test_render_preview.py tests/test_encode.py -q`；手工：对样本项目 `uv run python aicut.py build 2026-09-01_活动 --no-draft`，预览字幕为黑体简体。

### Task 13: 确认页入口与「确认后重新选段」（KI-05）
- **ACTION**: 新建 `gui/confirm.py`；server 两条路由委托；index.html 加入口；confirm.html 加任务进度。
- **TESTS FIRST**（`tests/test_confirm_flow.py`，用 `gui_server`、`call`、`make_project`、`fake_command` 模式）:
  - `test_confirmed_save_starts_select_job`：项目含 `work/questions.json`；POST `/api/confirm/answers {"project":"p1","answers":{"q1":"A"},"confirmed":true}` → 200，`body["job_id"]` 非空，`fake_command` 记录到 `("select","p1",[])`；`brief_answers.json` 的 `rules` 由 `select_rules.rules_from_answers` 计算。
  - `test_plain_save_does_not_start_job`：`confirmed:false` → `job_id is None`，无任务。
  - `test_confirm_save_conflict_keeps_answers`：先起一个 LONG 任务 → 再确认 → 200，`job_id is None`、`job_error` 含「已有任务在运行」，答案文件已写。
  - `test_confirm_answers_must_be_object`：`answers: []` → 400（避免把非对象写盘）。
  - `test_index_has_confirm_entry`：`index.html` 含 `openConfirm()` 与 `/static/confirm.html?project=`。
  - `test_confirm_page_polls_job`：`confirm.html` 含 `/api/job/` 与 `job_id`；`test_static_pages.py` 的 XSS 守卫（`test_no_string_interpolation_in_inline_handlers` 等）自动覆盖新代码。
  - 既有 `test_server_hardening.py::test_write_endpoints_404_and_no_ghost_dir` 对 `/api/confirm/answers` 仍 404。
- **IMPLEMENT**（`gui/confirm.py`）:
```python
"""确认与提问页（KI-05）：读问题、存答案；「保存并确认」后自动按答案重新选段。"""
RESELECT_TASK = "select"

def payload(pdir: Path) -> dict:            # 原 server.confirm_payload 搬来，行为不变
def save_answers(pdir: Path, name: str, body: dict) -> dict:
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        raise ValueError("answers 必须是对象")
    questions = _read(pdir / "work/questions.json")
    confirmed = bool(body.get("confirmed", False))
    schema.write_json(pdir / "work/brief_answers.json", {
        "answers": answers, "rules": select_rules.rules_from_answers(answers, questions),
        "confirmed": confirmed, "at": datetime.now().isoformat(timespec="seconds")})
    if not confirmed:
        return {"ok": True, "job_id": None}
    try:
        return {"ok": True, "job_id": jobs.start_job(name, RESELECT_TASK, [])}
    except jobs.JobConflict as exc:        # 答案已保存；只是选段没能马上开始
        return {"ok": True, "job_id": None, "job_error": str(exc)}
```
  `gui/server.py`：`/api/confirm` 调 `confirm.payload(existing_project(name))`（保持 404/400 映射）；`/api/confirm/answers` 调 `confirm.save_answers(pdir, body["project"], body)`，`ValueError → 400`；删除 `confirm_payload` 函数与 `from pipeline import select as selector` 内联导入（净减行）。`server.confirm_payload` 若有测试引用，保留 `confirm_payload = lambda name: confirm.payload(project_path(name))` 一行别名（先 grep）。
  `gui/static/index.html`：在「浏览素材」按钮前加 `<button class="ghost" onclick="openConfirm()">确认与提问</button>`；`openConfirm()` 照抄 `openBrowse()`（`index.html:614-617`）。文案常量 `COPY_CONFIRM_ENTRY = '确认与提问'`。
  `gui/static/confirm.html`：`save(confirmed)` 成功后若 `j.job_id` → `watchJob(j.job_id)`：每 1s `fetch('/api/job/'+encodeURIComponent(id))`，`status==='running'` 时状态栏显示 `COPY_RESELECT_RUNNING`，结束时显示 `COPY_RESELECT_DONE` 或 `COPY_RESELECT_FAILED + 最后一行 [x]/[!] 日志`（`esc()` 后 `textContent`）；`j.job_error` → 显示 `COPY_RESELECT_BLOCKED + j.job_error`。「下一步」卡片文案改为「点『保存并确认』后会按你的选择自动重新选段；你手动改过的分镜表不会被覆盖」。
- **MIRROR**: SERVICE_PATTERN（`job_extra` / `_start_job` 错误映射）；TEST_STRUCTURE（`fake_command`）。
- **IMPORTS**: `gui/confirm.py`：`from datetime import datetime`、`from pipeline import schema, select_rules`、`from gui import jobs`。
- **GOTCHA**: `jobs.start_job` 是 server 导入的同一个对象（测试 monkeypatch 的是 `jobs.job_command`，所以 `fake_command` 对这里同样生效）。`select` 任务不需要外发告知/Key（本地计算），不要调用 `settings.check_prepare_ready`。确认页是独立标签页，不能用 `jobs.js` 的 `startJob`（依赖 index 的 `state.project`）。手动 `shots.json` 存在时重新选段只更新 `shots-selected.json`（`project_state` 已是「手动优先」，`gui/server.py:150-160`）。`server.py` 改完 `wc -l` 必须 < 789。
- **VALIDATE**: `uv run pytest tests/test_confirm_flow.py tests/test_server_hardening.py tests/test_static_pages.py tests/test_server_security.py -q`；手工见 Manual Validation。

### Task 14: 收尾
- **ACTION**: 跑全量；`calibrate.html` 提示文案（D5）；`docs/known-issues.md` 各 KI 状态填提交号（实施提交时，按登记册约定）。
- **VALIDATE**: `uv run pytest`（预期 987 + 新增约 70 条，全绿）；`wc -l aicut.py gui/server.py pipeline/select.py`（≤931 / ≤789 / <800）。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_sub_is_full_sentence_not_28_chars` | 40 字必留段 | sub 40 字 | |
| `test_budget_clipped_shot_sub_trimmed` | 20s 段、预算 10s、3 个分句 | 只含镜头内分句 | ✓ |
| `test_proportional_cut_without_lines` | 无 lines | 按时长比例截字 | ✓ |
| `test_ending_never_moves_hook` | hook 文本命中结尾词 | hook 仍在片头 | ✓ |
| `test_ending_picks_last_match_in_time` | 两镜命中 | 晚的那镜在最后 | |
| `test_ending_keywords_not_too_broad` | 「走进」「谢谢」 | 不移动 | ✓ |
| `test_must_line_fragment_does_not_flood_cut` | 「嗯，对，就九千八」 | 只强制 1 段 | ✓ |
| `test_same_label_in_two_questions_uses_own_rule` | 跨题同名 label | 各用各的规则 | ✓ |
| `test_tight_pacing_caps_shot_length` | 30s 段、tight | ≤12s；必留整段 | ✓ |
| `test_focus_unmappable_warns` | focus="老师" | 不变 + 警告 | ✓ |
| `test_confirmed_save_starts_select_job` | 确认 | 起 select 任务 | |
| `test_confirm_save_conflict_keeps_answers` | 已有任务 | 答案保存 + job_error | ✓ 并发 |
| `test_scored_segments_carry_audio_signals` | rel_db=3 | scored 段有 signals | |
| `test_ratio_must_topic_protects_short_plain_segment` | 占比必留话题 4s 普通句 | 待定 | ✓ |
| `test_interrupt_proxy_on_long_split_segment_not_usable` | 34.5s 代理抢话 | 不是可用 | ✓ |
| `test_topic_segmentation_windows_long_input` | 300 句 | 3 次调用、全覆盖 | ✓ 最大输入 |
| `test_key_info_string_false_is_false` | `"false"` | False | ✓ 非法类型 |
| `test_model_passed_to_client` | `model="deepseek-reasoner"` | 客户端收到 | |
| `test_preview_fingerprint_changes_when_in_out_shift` | 平移入出点 | 指纹不同 | ✓ |
| `test_apply_relocates_by_text_after_resegmentation` | 重新分段 | 裁决跟着原文走 | ✓ |
| `test_apply_stale_override_skipped_and_reported` | 原文消失 | 不套用 + stale | ✓ |
| `test_prefers_hiragino_sans_gb` | 字体候选 | 首选简体黑体 | |

### Edge Cases Checklist
- [x] Empty input：空文本段字幕、空 must_lines、空 answers、无 questions 文件、无 segments.json / segments_audio.json / scored 文件
- [x] Maximum size input：300 句话题分段分窗
- [x] Invalid types：`key_info:"false"`、`topics:"oops"`、answers 非对象、multi 答案非数组（规则侧容错）
- [x] Concurrent access：确认时已有任务（409 → job_error）；`review._LOCK` 仍串行
- [x] Network failure：话题分段窗口重试后仍失败 → LLMError → `die`
- [ ] Permission denied：不涉及（写盘全走 `schema.write_json`）

---

## Validation Commands

### Static Analysis
```bash
# 本仓库未配置 lint / typecheck；只做语法与导入检查
uv run python -m compileall -q aicut.py pipeline gui
```
EXPECT: 无输出

### Unit Tests
```bash
uv run pytest tests/test_select.py tests/test_select_rules.py tests/test_shot_sub.py tests/test_classify.py \
  tests/test_questions.py tests/test_understand_text.py tests/test_summarize.py tests/test_review.py \
  tests/test_build_documentary.py tests/test_aicut_build.py tests/test_render_preview.py \
  tests/test_confirm_flow.py tests/test_static_pages.py -q
```
EXPECT: All tests pass

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 987 + 新增全部通过，无回归

### Database Validation (if applicable)
N/A（无数据库；JSON 产物结构由单测覆盖）

### Browser Validation (if applicable)
```bash
python3 gui/server.py --open
```
EXPECT: 主界面有「确认与提问」；确认后状态栏显示重新选段进度与结果；黄条出现原话/主角/裁决失效类提示

### Manual Validation
- [ ] 样本项目 `2026-09-01_活动`：`uv run python aicut.py score 2026-09-01_活动` → 输出「废片/待定/可用」，必留话题数 ≤ 12（原 14），无「出现抢话/被打断」理由的 30s+ 句子
- [ ] `uv run python aicut.py select 2026-09-01_活动` → `work/分镜表-选段.md` 字幕列为整句；截短镜头字幕只到镜头出点
- [ ] 剪辑偏好填「嗯，对，就九千八」→ 选段只多 1 个强制镜头；填一句不存在的话 → CLI `[!]` 与 GUI 黄条提示没找到
- [ ] GUI：确认页选「结尾：最有力的句子」→ 保存并确认 → 选段完成 → 新分镜表最后一镜是音量最高的非 hook 镜头
- [ ] `build --version v9` 两次，中间在 shots.json 平移某镜入出点 → 第二次重渲染预览（日志不是「预览片无变化」）
- [ ] 预览片字幕为冬青黑体简体（不是宋体）
- [ ] 浏览页标几条裁决 → 删除 `work/segments.json` 等重新处理素材（或手工改 scored 段 id）→ 黄条出现「N 条人工裁决…已不套用」，没有套到别的句子上
- [ ] `uv run python aicut.py text <项目> --model deepseek-reasoner`（需真实 Key，可选）→ 计费面板显示该模型

---

## Acceptance Criteria
- [ ] Task 1–14 全部完成
- [ ] 所有验证命令通过
- [ ] 每个 KI 至少一条「修前 RED、修后 GREEN」的回归测试
- [ ] `test_must_keep_invariant_randomized`（必留 100% 进片）仍通过
- [ ] `aicut.py` ≤ 931 行、`gui/server.py` ≤ 789 行、`pipeline/select.py` < 800 行
- [ ] 需用户决策项按默认值实现，文案各在一个命名常量里

## Completion Checklist
- [ ] Code follows discovered patterns（常量命名、返回新对象、警告随结果返回）
- [ ] Error handling matches codebase style（LLM 形状错误 → LLMError 重试；CLI die；不静默降级）
- [ ] Logging follows codebase conventions（pipeline 层不新增日志）
- [ ] Tests follow test patterns（`seg()` 助手、`gui_server`/`call`/`fake_command`、假 LLM 客户端）
- [ ] No hardcoded values（阈值/文案/词表全部常量或预设）
- [ ] Documentation updated（`docs/known-issues.md` 状态；`calibrate.html` 提示）
- [ ] No unnecessary scope additions
- [ ] Self-contained — no questions needed during implementation

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 整句字幕让单镜字幕卡数量变多，预览/剪映文字轨更密 | 中 | 低 | `compose_timeline` 已按 `max_chars` 拆卡且按字数分时长；手工看样本预览 |
| 必留话题收窄（D6）后某些真实必留话题不再受「→待定」保护 | 中 | 中 | 关键信息句本身仍是「可用」；参数在预设里可调；样本项目手工核对 12 个必留话题 |
| 抢话收紧（D7）漏掉真实抢话 | 中 | 低 | 抢话只是加分项；真重叠仍判可用；剪辑师可在浏览页手动改档 |
| 话题分窗后跨窗口同一话题被拆成两个 | 中 | 低 | 沿用 >15 合并（LLM 合并 / 相邻最短合并）；窗口话题数按比例给上限 |
| overrides 重定位误配（同一句话出现多次） | 低 | 中 | 取起点最近；对不上就 stale + 警告，不猜 |
| `select()` 内部 `MAX_SHOT` → `max_shot` 参数化遗漏一处 | 中 | 低 | tight 用例覆盖首镜/补齐/延伸/强制四条路径 |
| server/aicut 行数超软上限 | 中 | 低 | 新逻辑放 `gui/confirm.py`、`pipeline/select_rules.py`、`shot_sub.py`、`build_documentary.py` |

## Notes

### 逐条现状核对（HEAD `963374c`）
| KI | 结论 | 当前位置 |
|---|---|---|
| KI-01 | still-present | `pipeline/select.py:173,289,350,385`（`[:28]`）；截短不裁字幕 `:329-342,379-380,395-409` |
| KI-02 | still-present | `pipeline/select.py:35-39,464-484`；`questions.py:107` 的 `ending=info` 无法归一 |
| KI-03 | still-present | `pipeline/select.py:276-295,547-550`；`gui/static/calibrate.html:51` 明确要求「用逗号分隔」 |
| KI-04 | still-present | `pipeline/select.py:110-136`（focus/pacing 无消费方；pacing 看 label）；`questions.py:59,91-92` |
| KI-05 | still-present（部分已修：M4 已有 `select` 任务，`gui/jobs.py:29-31,399-400`） | 无入口 `gui/static/index.html:142-149`；保存不触发 `gui/server.py:656-673`；prepare 顺序 `pipeline/readiness.py:15-16` |
| KI-06 | still-present | `pipeline/classify.py:138-144`；消费方 `select.py:100-101,478-480` |
| KI-07 | still-present | `pipeline/classify.py:21-23,43-44,81-89`（样本 14/19） |
| KI-08 | still-present | `pipeline/understand_audio.py:86-91`；`classify.py:55,62-63`（样本 9 句全是 35s 切点假象） |
| KI-09 | still-present（部分已修：逐句标注的形状校验/重试已在 M2 完成） | `pipeline/understand_text.py:102-126,158-179,189` |
| KI-10 | still-present | `pipeline/understand_text.py:304-305,323`；`pipeline/summarize.py:101,115` |
| KI-11 | still-present（部分已修：GL-15 完成标记、每次 build 默认新版本目录；`aicut.ensure_clips` 已按 in/out 键缓存） | `aicut.py:641-642`（仅 `--version` 重出时触发）；`pipeline/build_documentary.py:107-112` |
| KI-12 | still-present | `pipeline/review.py:52-100` |
| KI-58 | still-present | `pipeline/classify.py:141`（名字）vs `:145`（名字+占比） |
| KI-73 | still-present | `pipeline/render_preview.py:25-29`（本机 macOS 26.3.1：`/System/Library/Fonts/PingFang.ttc` 不存在，回落 Songti） |

### 需用户决策（实现按「默认」做，除非用户另行指定）
- **D1（KI-05）确认流程**：默认——「处理素材」仍自动用默认规则选段（剪辑师可直接出片）；确认页「保存并确认」后服务端自动起「重新选段」任务；主界面新增按钮「确认与提问」。备选：prepare 在 questions 后停下、必须确认才选段（多一步强制操作）。
- **D2（KI-04）focus 映射**：默认——`main`/`narrator` → 说话总时长最多的说话人每段 +2 分；`ensemble` 不加分；LLM 生成的其他值（如「老师」）无法对应 ASR 说话人编号 → 不生效并给警告；提示词限定 focus 只能是 main/ensemble。
- **D3（KI-04）pacing**：默认——`tight` 单镜上限 12 秒，`normal` 保持 25 秒；其他选段逻辑不变。
- **D4（KI-02）结尾规则**：默认——签约词 `签合同/签字/签约/签了/缴费/交钱/转账/付款/刷卡`，离开词 `走了/离开/出门/下楼/再见/拜拜`；情绪结尾只看音量（≥ 中位 +1dB 的最响非 hook 镜头）；「最后一个关键信息」取时间上最后的关键信息镜头；「留白」不自动实现，只提示去剪映补空镜。
- **D5（KI-03）原话格式**：默认——按换行或「；」分句，兼容旧的逗号写法（整句找不到才按逗号拆，碎片少于 4 字忽略）；每条原话只强制 1 段；`calibrate.html` 提示改为「每句一行（也可以用逗号分隔）。这些句子无论档位如何都会进片。」
- **D6（KI-07）必留话题口径**：默认——词表与阈值放进预设 `must_topic`；代码兜底与《纪实3min》均为 `合同/退费/价格/就业/工资/资格/签约/缴费`，关键信息占比 ≥30% 且至少 2 句关键信息；其他三个预设不写（用兜底）。样本项目必留话题 14 → 12（/19）。如需更少，可把占比调到 0.4（→ 11）。
- **D7（KI-08）抢话判定**：默认——真重叠（>0.3s）判可用；「换人且停顿 <0.25s」的代理信号只有在本句 <30 秒且音量 ≥ 中位 +1dB 时才判可用。样本项目 9 → 0。
- **D8（KI-09）话题分段失败**：默认——分窗 + 每窗重试 2 次，仍失败就明确报错停止（与 GL-09「不静默降级」一致），不退回「按时间切话题」。
- **D9（KI-12）旧裁决**：默认——没有锚点的旧裁决照旧按 id 套用（无法判断是否已错位）；新写入的裁决带锚点；锚点对不上时按原文重定位，找不到就不套用并在黄条提示。
- **D10（KI-73）字体**：默认——Hiragino Sans GB（冬青黑体简体 W3）。不用系统资源目录里的 PingFang：路径是哈希目录、随系统更新变化，且 drawtext 只能取第 0 个字形（PingFang HK）。
- **D11（KI-01）字幕截法**：默认——有分句时间码时只保留至少一半落在镜头内的分句；没有时按时长比例截字。

### 其他观察（不在本里程碑范围，不实现）
- `pipeline/render_preview.py:42` 的 `esc()` 当前已经转义 `%`，KI-76（M7）登记的描述可能已过时，M7 规划时核实。
- `select.run` 仍用非原子 `write_text` 写 `selection.json` / `shots-selected.json`（`select.py:556-562`），属 M8/M9 范畴。
- 必留占比按 `_split_large` 拆出的「(n/m)」小块分别计算，同一话题的块可能一块必留一块不必留；本次不改（见 NOT Building）。
