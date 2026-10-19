# Plan: M11 文档一致（KI-40 / KI-41 / KI-42 / KI-43 / KI-44）

## Summary
把 PRD、PLAN、产品设计、选段改进方案、PROGRESS、TECH-STACK 六份文档对齐到**同一套口径**，并与代码现状一致：
① 成功指标与验收可检验（样本 + 测量方法；FR-5 验收样本不再违反自身上限；人工时间预算只有一张表）；
② c 路画面范围与代码一致（景别/人脸/OCR/道具降为 P2，须本地实现）；
③ PLAN 对 PRD 有逐条追溯表，PRD 补入已实现的「剪辑偏好」(FR-14)，PLAN 的排期/风险/DoD 不再陈旧；
④ PRD §12 成为唯一术语表（档位、必留段/必留话题/指定原话、闸门 A/B、分类），其它文档引用它；
⑤ 非功能需求补「成本」「断网与服务失败」，DoD 量化。
新增一个只读文本的守卫测试 `tests/test_docs_consistency.py`，把这些口径钉住（同 `tests/test_packaging.py` 的写法）。

## User Story
As 产品负责人 / 开发 / 验收剪辑师，
I want PRD、PLAN 与设计文档对同一件事只有一种说法、每个指标都写清楚「样本多少、怎么量」，
So that 验收时不会因为文档互相矛盾而争论「到底算不算达标」，后续里程碑也不会按过期的计划施工。

## Problem → Solution
- FR-5 验收「裁决 41 段待定」违反同节「≤40 段」上限；§10 满意度等指标没有样本和方法；时间预算 PRD 20 分钟（5+3+3+6+余量）、PLAN M2「≤10 分钟」、产品设计「15–20 分钟」三种
  → PRD §3.3 一张预算表（合计 20，S2+S3 = 11）；FR-5 改写为与代码一致的上限（总段数 × 28%，≈40 段/60 分钟）和合法样本；§10 四列表（指标/目标/样本/测量方法）；PLAN M2 验收改「≤ 11 分钟」；产品设计引用 PRD。
- PRD FR-2 c 路要求景别/人脸/OCR/道具，代码 `pipeline/understand_visual.py` 只做镜头切分 + 画面质量
  → PRD 把这四项降为 P2，并写明须本地实现（§7 画面帧不上云）；PLAN 1.3、TECH-STACK、改进方案、`understand_visual.py` docstring 同步。
- PLAN 没有 Brief，FR-10..13 只有任务行没有验收/状态，排期与风险表停在 M0 之前；PRD 不知道已上线的「剪辑偏好三问 / schema v2」
  → PLAN 新增 §1.1「PRD 需求追溯」表（FR-1..FR-14 + Brief + 未关闭登记项），排期改为指向上线里程碑，风险表/外部配合/DoD 更新；PRD 新增 FR-14、§6 写清 Brief 的承载方式与 `schema_version`。
- 术语三套（废片/待定/可用、L1–L3、必留/可选/可删），「必留」一词三义，闸门位置、分类名是否已定互相冲突
  → PRD §12 扩成「术语 / 含义 / 代码里 / 旧说法」四列表；产品设计与改进方案加引用横幅并替换旧词；闸门以 PRD §4 为准；分类名改为「AI 按素材生成、可改，表内为示例」。
- PRD §7 无成本上限、无断网/服务失败降级；PLAN DoD 无量化门槛和测试策略；TECH-STACK 降级表仍写「DeepSeek 失败退回规则模板」（GL-09 后逐句标注失败是**报错**）
  → PRD §7 增「成本」「断网与服务失败」两行；PLAN §8 DoD 改量化表；TECH-STACK §4 降级列与隐私边界按代码改写。

## Metadata
- **Complexity**: Medium（7 个文档 + 1 个 docstring + 1 个新测试文件；不改任何运行时行为）
- **Source PRD**: `.claude/prds/ai-cut-go-live.prd.md`
- **PRD Phase**: Milestone 11「文档一致」（KI-40..KI-44）
- **Estimated Files**: 9（CREATE 1 / UPDATE 8）

---

## 缺陷复核（对当前代码与文档逐条重新定位）

| KI | 登记位置 | 当前实际位置 | 结论 |
|---|---|---|---|
| KI-40 | PRD §5 §10；PLAN:102 | PRD `docs/PRD-AI粗剪工具.md:175-176`（FR-5「≤40 段」与「裁决 41 段」）、`:298-306`（§10 无样本/方法）、`:95`（20 分钟 = 5+3+3+6+余量）；PLAN `docs/PLAN-AI粗剪工具.md:104`（登记的 :102 已漂移 2 行，「裁决 41 段 → 答 5 题 ≤ 10 分钟」，而 PRD 同口径为 5+3+3 = 11）；产品设计 `:160`「15–20 分钟」、`:73`「30 秒能清空」与 `:91`「约 1–2 分钟」自相矛盾 | **still-present** |
| KI-41 | PRD FR-2；`understand_visual.py:5` | PRD `:136`（c 路：景别/人脸数/OCR/道具）；代码 `pipeline/understand_visual.py:1-9` 只承诺镜头切分，`:82-199` 实际还做了画面质量（亮度/运动/清晰度）；没有任何景别/人脸/OCR/道具实现；TECH-STACK `:20,93` 写「MediaKit 视频理解/OCR 可选」且 `:96` 隐私边界写「上传抽帧图」，与 PRD §3.3/§7「画面帧不上云」冲突 | **still-present** |
| KI-42 | PLAN | PLAN 确有 4.2（FR-10）、4.3（FR-11）、5.1（FR-12）、5.2（FR-13）任务行（`:129-130,142-143`），所以「漏 FR-10..13」**部分不准确**：真正缺的是这些需求的验收标准与追溯（M4/M5 验收 `:132-134,149-151` 不含它们）；**Brief 在 PLAN 里完全没有**；PRD 无「剪辑偏好 / schema v2」（PROGRESS `:77-84` 自称「待补入 PRD」）；排期 `:155-166`、风险表 `:186-195`、已有资产 `:37`、外部配合 `:223-230` 仍停在 M0 前；PLAN `:4` 自认未更新。另：FR-13 已由 GL-19（`ac3f15c`）实现、FR-12 由 GL-15/GL-16 部分覆盖，PLAN 未体现 | **still-present**（描述需按上面修正） |
| KI-43 | PRD §12；产品设计；改进方案 | 产品设计 `:28,75,114,127` 用 L2/L3；改进方案 `:88` 用「必留/可选/可删」；「必留」三义：`must_keep`（`pipeline/select.py:98`，人标的段）、`topics[].must`（`pipeline/classify.py:21-27,82-90`，必留话题）、`calibration.must_lines`（`pipeline/style.py:7,21`，指定原话）；闸门：PRD `:112-115`（A=S3 结束、B=S4 结束）vs 改进方案 `:104-120`（A=切之前内容清单、B=渲染前选段表）；分类名：产品设计 `:166-168`「已定 12 个」vs PRD `:312`「未决、需访谈」vs 代码（话题名由 LLM 按素材生成，`pipeline/`、`presets/` 无固定分类表）；快捷筛选：PRD `:163` 4 项 vs GUI `gui/static/browse.html:68-72` 5 项（多「废片」）vs 产品设计 `:75`「只看 L3/未用/必留」 | **still-present** |
| KI-44 | PRD §7；PLAN DoD | PRD `:259-271` 无成本、无断网/服务失败行；PLAN `:233-240` DoD 四条均无数值、无测试要求；TECH-STACK `:93-94` 降级列过期（GL-09 `ebabfcc` 起逐句标注失败 = 任务失败，不再「退回规则模板」） | **still-present** |

> 无一项已被 M1–M5 修复：M1–M5 只改代码与 PACKAGING/交付形态文档，没碰上述段落（`git log -- docs` 中 `ac3f15c`/`8149069` 等仅改 GL/KI 状态与 PACKAGING）。

---

## UX Design

### Before
```
┌───────────────────────────────────────────────────────────────┐
│ 验收会上：                                                    │
│  PRD：待定 ≤40 段；验收样本「裁决 41 段」 → 先违规再验收？    │
│  PLAN：浏览+裁决+答题 ≤10 分钟；PRD：5+3+3 = 11；设计：15–20  │
│  「满意度 ≥80%」——问谁？问几条？怎么算？                     │
│  「必留」= ★ 标的段？必留话题？剪辑偏好里贴的原话？           │
│  闸门 B 在渲染前还是看完预览后？分类名定了还是没定？          │
└───────────────────────────────────────────────────────────────┘
```

### After
```
┌───────────────────────────────────────────────────────────────┐
│ PRD §3.3 一张预算表（合计 20；S2+S3 = 11 = PLAN M2 验收）     │
│ PRD §10 每个指标：目标 | 样本 | 测量方法（数据从哪来）        │
│ PRD §12 唯一术语表：必留段 / 必留话题 / 指定原话 / 闸门 A·B   │
│ PLAN §1.1 FR-1..FR-14 + Brief 逐条 → 计划项 → 未关闭 GL/KI     │
│ tests/test_docs_consistency.py：口径再漂移，pytest 直接红     │
└───────────────────────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 剪辑台界面 | — | 不变 | 本里程碑不改 GUI；「必留」分组标签改名见 Notes 需用户决策 D6 |
| 文档读者 | 6 份文档各说各话 | PRD 为准，其它文档顶部横幅指向 PRD §12 | |
| 开发者 | 改文档无护栏 | `uv run pytest` 含 20 条文档一致性用例 | |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `docs/PRD-AI粗剪工具.md` | 1-338（全文） | 主改对象；§3.3/FR-2/FR-4/FR-5/§6/§7/§10/§11/§12/§13 |
| P0 | `docs/PLAN-AI粗剪工具.md` | 1-252（全文） | 主改对象；头注 :4、§1 :27-40、M1 :79、M2 :103-105、M4/M5 验收、§3 排期、§5 风险、§7、§8 DoD |
| P0 | `tests/test_packaging.py` | 1-11 | 「只读仓库文本」测试的写法（`ROOT` / `_read`） |
| P0 | `pipeline/classify.py` | 21-27, 82-90, 105-111 | 待定上限 `MAX_PENDING_RATIO = 0.28`、`limit = max(10, int(len*ratio))`、必留话题判定、保护段超限只警告 |
| P1 | `docs/产品设计-AI粗剪工作流.md` | 1-169 | L2/L3、时间预算、分类名、筛选 |
| P1 | `docs/选段与理解-改进方案.md` | 63-120 | 「必留/可选/可删」、闸门 A/B、画面一路 |
| P1 | `gui/static/browse.html` | 65-72, 180, 225-227 | GUI 快捷筛选实际 5 项；分类视图「必留」标签 = 必留话题；`S` 键标必留段 |
| P1 | `pipeline/style.py` | 1-22 | 剪辑偏好三问 = tone / audience / must_lines |
| P1 | `pipeline/schema.py` | 19-36 | `CURRENT_SCHEMA = 2`；`brief: {}`（无写入方）、`calibration: {}` |
| P1 | `docs/TECH-STACK.md` | 20, 88-96 | 视频理解/OCR 行、外部服务降级表、隐私边界 |
| P1 | `docs/PROGRESS.md` | 27, 77-84 | KI-41 注记、「运行时校准（待补入 PRD）」 |
| P2 | `pipeline/understand_visual.py` | 1-9, 82-199 | docstring 与实际功能 |
| P2 | `pipeline/understand_text.py` | 300-335 | 逐句标注失败 → 落盘 partial 再抛 `AnnotationIncomplete`（降级口径依据） |
| P2 | `pipeline/summarize.py` / `pipeline/questions.py` | 63-72,111 / 86-93,132 | 摘要/提问失败兜底并标 `fallback` |
| P2 | `pipeline/review.py` | 18, 50-70 | `LEVELS = {1:"废片",2:"待定",3:"可用"}`；每次裁决写 `at` 时间戳（裁决时长的测量来源） |
| P2 | `pipeline/applog.py` | 34, 268 | `work/timings.json` 阶段耗时（分析时长的测量来源） |
| P2 | `pipeline/select.py` | 98, 112-127, 438 | `must_keep`、`must_topics`/`exclude_topics`、`selection["unused"]` |

## External Documentation

No external research needed — feature uses established internal patterns（纯文档 + 读文本的 pytest 守卫）。

---

## Patterns to Mirror

### NAMING_CONVENTION（测试）
```python
# SOURCE: tests/test_packaging.py:1-10
"""打包与合规守卫（GL-01 / GL-04）：只读仓库文本，不构建、不联网。"""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")
```
测试函数名 `test_<被守卫的口径>`，模块 docstring 写「XXX 守卫（KI-xx）：只读仓库文本」。

### ERROR_HANDLING
N/A — 不改运行时代码。测试里找不到段落时让 `assert` 失败（不要让 `next()` 抛 `StopIteration` 当失败信号以外的东西，见 Task 1 `_section` 的实现）。

### LOGGING_PATTERN
N/A — 不涉及日志。

### 代码常量是事实来源（文档向代码对齐，测试从代码取值）
```python
# SOURCE: pipeline/classify.py:26
MAX_PENDING_RATIO = 0.28  # 待定不超过总段数的 28%（60 分钟约 40 段）
# SOURCE: pipeline/classify.py:107
    limit = max(10, int(len(scored) * MAX_PENDING_RATIO))
```
```python
# SOURCE: tests/test_classify.py:5
from pipeline import classify
```

### 文档横幅写法
```markdown
<!-- SOURCE: docs/PLAN-AI粗剪工具.md:3-5 -->
> 依据：[PRD v1.1](PRD-AI粗剪工具.md)
> 状态以 [PROGRESS](PROGRESS.md) 为准；……
> 2026-10-19 起的整改项见 [go-live-blockers](go-live-blockers.md) 与 [known-issues](known-issues.md)。
```

### PRD 需求条目写法
```markdown
<!-- SOURCE: docs/PRD-AI粗剪工具.md:224-228 -->
### FR-11 "不可用"标记（P1）

- 隐私/未授权片段标记后**永不进入候选**
- 导出时自动排除
- **验收**：标记后所有版本均不出现该片段
```

### TEST_STRUCTURE（读文本 + 结构断言）
```python
# SOURCE: tests/test_packaging.py:52-56
def test_notices_mention_ffmpeg_lgpl_freetype_and_python():
    text = _read(NOTICES)
    assert "FFmpeg" in text and "LGPL" in text and "ffmpeg-8.1.3.tar.xz" in text
```

---

## Unified Discovery Table

| Category | File:Lines | Pattern | Key Snippet |
|---|---|---|---|
| 测试命名/路径 | `tests/test_packaging.py:1-10` | `ROOT` + `_read(rel)`，只读文本 | `ROOT = Path(__file__).resolve().parent.parent` |
| 档位常量 | `pipeline/review.py:18` | 代码用 1/2/3 | `LEVELS = {1: "废片", 2: "待定", 3: "可用"}` |
| 待定上限 | `pipeline/classify.py:26,107` | 按段数比例，最少 10 | `max(10, int(len(scored) * MAX_PENDING_RATIO))` |
| 必留话题 | `pipeline/classify.py:21-27,82-90` | 关键词或关键信息占比 ≥30% | `KEY_RATIO_MUST = 0.30` |
| 必留段 | `pipeline/select.py:98,178-195` | `must_keep` 整段进片 | `if seg.get("must_keep"):` |
| 指定原话 | `pipeline/style.py:7,21` | `calibration.must_lines` | `("must_lines", "有哪 2–3 句必须保留的原话？…")` |
| 决策答案 | `pipeline/select.py:112-127`；`gui/server.py:672` | `brief_answers.json` → `must_topics` / `exclude_topics` / `ending` | `rules = {"must_topics": [], "exclude_topics": [], "ending": None, …}` |
| 未采用清单 | `pipeline/select.py:438` | `selection["unused"]` | `"unused": unused,` |
| 快捷筛选 | `gui/static/browse.html:68-72` | 5 个按钮 | `全部 / 待判断 / 可用 / 废片 / 未用` |
| 画面一路 | `pipeline/understand_visual.py:30-38,83-199` | 本地 ffmpeg：scdet 切点 + 1fps 灰度质量 | `def quality(video, segments, *, fps=1.0)` |
| 失败口径 | `pipeline/understand_text.py:327-330` | 先落 partial 再抛 | `raise AnnotationIncomplete(sorted(failed))` |
| 兜底口径 | `pipeline/summarize.py:111-113`；`pipeline/questions.py:132-133` | 摘要/提问失败兜底 `fallback: True` | `result = fallback(segments, topics)` |
| 测量来源 | `pipeline/review.py:55-58`；`pipeline/applog.py:34,268` | 裁决 `at` 时间戳；`work/timings.json` | `item["at"] = _now()` |
| schema | `pipeline/schema.py:19-36` | v2；`brief: {}` 目前无人写入 | `CURRENT_SCHEMA = 2` |

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `tests/test_docs_consistency.py` | CREATE | 20 条文档一致性守卫（先红后绿） |
| `docs/PRD-AI粗剪工具.md` | UPDATE | v1.2：§3.3 预算表、FR-2 c 路、FR-4 筛选、FR-5、FR-14、§6、§7、§10、§11、§12、§13 |
| `docs/PLAN-AI粗剪工具.md` | UPDATE | 头注、§0、§1、新 §1.1 追溯表、1.3、M2/M4/M5 验收、§3 排期、§4、§5 风险、§7、§8 DoD、§9 |
| `docs/产品设计-AI粗剪工作流.md` | UPDATE | 横幅；L2/L3 → 档位名；筛选；时间预算；分类名改「示例」；数据模型注释 |
| `docs/选段与理解-改进方案.md` | UPDATE | 横幅；§3.1 画面行；§3.2 三档；§3.3 第 4 步；§3.4 闸门 |
| `docs/PROGRESS.md` | UPDATE | :27 KI-41 注记；:77 小节标题 |
| `docs/TECH-STACK.md` | UPDATE | :20 视频理解行；§4 降级列与隐私边界 |
| `pipeline/understand_visual.py` | UPDATE | 仅 docstring（:1-9），行为不变 |

> 不改：`docs/known-issues.md`、`docs/go-live-blockers.md`、`.claude/prds/ai-cut-go-live.prd.md`（登记册与里程碑状态由编排方更新）。

## NOT Building

- 不实现景别/人脸/OCR/道具（KI-41 默认降级为 P2）。
- 不实现成本统计/预算上限（KI-32，M9）、摘要/提问兜底的界面提示（KI-22，M8）——PRD 只写需求并标注登记号。
- 不实现 FR-10 对比/回退、FR-11「不可用」标记——只在追溯表里如实写「未做」，不新开登记项、不排期。
- 不写指标采集脚本 / 埋点；测量方法只引用已有数据（`overrides.json` 的 `at`、`work/timings.json`、`output/vN/`、人工记录）。
- 不改 GUI 文案（含分类视图里的「必留」标签，见 D6）。
- 不更新 PROGRESS 的测试数「112」、SOP 里的旧 Key 路径等登记册以外的陈旧点（不扩范围；如需请另行登记）。
- 不改 `project.json` 里无人写入的 `brief: {}` 字段（只在 Notes 记录）。

---

## Step-by-Step Tasks

### Task 1：写失败的文档一致性测试（RED）
- **ACTION**: CREATE `tests/test_docs_consistency.py`，内容如下（全文照抄）。
- **IMPLEMENT**:
```python
"""文档一致性守卫（KI-40..KI-44）：只读仓库文本，断言 PRD / PLAN / 设计文档口径一致。"""
import re
from pathlib import Path

from pipeline import classify

ROOT = Path(__file__).resolve().parent.parent
PRD = "docs/PRD-AI粗剪工具.md"
PLAN = "docs/PLAN-AI粗剪工具.md"
DESIGN = "docs/产品设计-AI粗剪工作流.md"
IMPROVE = "docs/选段与理解-改进方案.md"
PROGRESS = "docs/PROGRESS.md"
TECH_STACK = "docs/TECH-STACK.md"
BROWSE = "gui/static/browse.html"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """从以 heading 开头的标题行起，到下一个同级或更高级标题为止；找不到返回空串。"""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(heading)]
    if not starts:
        return ""
    start = starts[0]
    level = len(heading) - len(heading.lstrip("#"))
    end = next((j for j in range(start + 1, len(lines))
                if re.match(rf"#{{1,{level}}} ", lines[j])), len(lines))
    return "\n".join(lines[start:end])


def _table_rows(section: str) -> list[list[str]]:
    """Markdown 表格的数据行（去掉表头与分隔行），每行拆成单元格。"""
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows[2:]]


# ---------------------------------------------------------------- KI-40 指标可检验
def test_fr5_acceptance_sample_respects_pending_cap():
    fr5 = _section(_read(PRD), "### FR-5")
    cap = re.search(r"≤\s*(\d+)\s*段/60 分钟", fr5)
    samples = [int(n) for n in re.findall(r"裁决\s*(\d+)\s*段", fr5)]
    assert cap and samples and all(n <= int(cap.group(1)) for n in samples)
    assert "41 段" not in _read(PLAN)


def test_fr5_pending_cap_matches_code_ratio():
    fr5 = _section(_read(PRD), "### FR-5")
    assert f"{round(classify.MAX_PENDING_RATIO * 100)}%" in fr5


def test_time_budget_sums_and_plan_m2_matches():
    s33 = _section(_read(PRD), "### 3.3")
    rows = re.findall(r"^\| (S\d[^|]*?|余量) \| [^|]* \| (\d+) 分钟", s33, re.M)
    assert sum(int(m) for _, m in rows) == 20 and "**≤ 20 分钟**" in s33
    before_preview = sum(int(m) for name, m in rows if name.startswith(("S2", "S3")))
    assert f"≤ {before_preview} 分钟" in _section(_read(PLAN), "### M2")


def test_design_doc_time_budget_defers_to_prd():
    design = _read(DESIGN)
    assert "15–20 分钟" not in design and "30 秒能清空" not in design
    assert "PRD §3.3" in design


def test_success_metrics_define_sample_and_method():
    s10 = _section(_read(PRD), "## 10.")
    header = next((l for l in s10.splitlines() if l.startswith("| 指标")), "")
    assert "样本" in header and "测量方法" in header
    rows = _table_rows(s10)
    assert len(rows) >= 5
    assert all(len(r) == 4 and all(r) for r in rows), rows


# ---------------------------------------------------------------- KI-41 c 路范围
def test_visual_route_scope_matches_implementation():
    fr2 = _section(_read(PRD), "### FR-2")
    c_row = next((l for l in fr2.splitlines() if l.startswith("| c 画面")), "")
    assert "亮度" in c_row and "清晰度" in c_row
    assert not any(w in c_row for w in ("景别", "人脸", "OCR", "道具"))
    p2 = [l for l in fr2.splitlines() if "景别" in l]
    assert p2 and all("P2" in l for l in p2)
    assert "可选云端" not in _read(PLAN)


def test_data_model_marks_visual_signals_p2_and_schema_version():
    s6 = _section(_read(PRD), "## 6.")
    assert "schema_version" in s6 and "calibration" in s6
    ocr_lines = [l for l in s6.splitlines() if "ocr" in l]
    assert ocr_lines and all("P2" in l for l in ocr_lines)


def test_tech_stack_matches_privacy_and_fail_loud():
    s4 = _section(_read(TECH_STACK), "## 4.")
    assert "抽帧图" not in s4
    assert "退回规则模板（分类名、提问可为空）" not in s4
    assert "画面帧" in s4


# ---------------------------------------------------------------- KI-42 PLAN ↔ PRD
def test_plan_traces_every_prd_requirement():
    ids = sorted(set(re.findall(r"^### (FR-\d+)", _read(PRD), re.M)),
                 key=lambda s: int(s[3:]))
    trace = _section(_read(PLAN), "## 1.1")
    assert ids and all(re.search(rf"^\| {fr} ", trace, re.M) for fr in ids), ids
    assert "Brief" in trace and "剪辑偏好" in trace


def test_prd_covers_calibration_as_fr14():
    fr14 = _section(_read(PRD), "### FR-14")
    assert "剪辑偏好" in fr14 and "must_lines" in fr14 and "**验收**" in fr14


def test_plan_not_stale():
    plan = _read(PLAN)
    assert "M0 测试包下发" not in plan
    assert "未随实际更新（KI-42）" not in plan
    assert "Windows 剪映不认明文草稿" not in _section(plan, "## 5. 风险")


def test_progress_no_pending_prd_backfill():
    assert "待补入 PRD" not in _read(PROGRESS)


# ---------------------------------------------------------------- KI-43 术语
CANON = ("档位", "必留段", "必留话题", "指定原话", "必须记住的信息",
         "分类（话题）", "闸门 A", "闸门 B")


def test_glossary_defines_canonical_terms():
    s12 = _section(_read(PRD), "## 12.")
    missing = [t for t in CANON if f"| {t} |" not in s12]
    assert missing == []


def test_design_docs_use_canonical_level_names():
    for rel in (DESIGN, IMPROVE):
        assert not re.search(r"\bL[1-3]\b", _read(rel)), rel
    improve = _read(IMPROVE)
    assert "可删" not in improve and "`可选`" not in improve


def test_design_docs_point_to_prd_glossary():
    for rel in (DESIGN, IMPROVE):
        assert "PRD §12" in _read(rel)[:600], rel


def test_category_names_are_examples_not_fixed():
    s7 = _section(_read(DESIGN), "## 七")
    line = next((l for l in s7.splitlines() if "分类名" in l), "")
    assert "示例" in line
    assert "分类名" in _section(_read(PRD), "## 11.")


def test_gate_definitions_follow_prd():
    gates = _section(_read(IMPROVE), "### 3.4")
    assert "PRD §4" in gates and "渲染前" not in gates


def test_quick_filters_match_gui():
    labels = re.findall(r'<button id="f(?:All|Un|\d)"[^>]*>([^<]+)</button>', _read(BROWSE))
    fr4 = _section(_read(PRD), "### FR-4")
    line = next((l for l in fr4.splitlines() if "快捷筛选" in l), "：")
    assert labels and line.split("：", 1)[1].strip().split(" / ") == labels


# ---------------------------------------------------------------- KI-44 非功能 / DoD
def test_nfr_covers_cost_and_outage():
    s7 = _section(_read(PRD), "## 7.")
    assert re.search(r"^\| 成本 \|", s7, re.M)
    assert re.search(r"^\| 断网与服务失败 \|", s7, re.M)


def test_plan_dod_is_quantified():
    dod = _section(_read(PLAN), "## 8.")
    for must in ("uv run pytest", "80%", "回归测试", "CRITICAL", "PROGRESS"):
        assert must in dod, must
```
- **MIRROR**: TEST_STRUCTURE、NAMING_CONVENTION。
- **IMPORTS**: `re`、`pathlib.Path`、`from pipeline import classify`（同 `tests/test_classify.py:5`）。
- **GOTCHA**:
  - `_section` 的标题前缀要足够唯一：PRD 用 `"## 1."`…`"## 13."` 时，`"## 1."` 不会匹配 `"## 10."`（第 4 个字符是 `0` 不是 `.`）；`"### 3.3"`、`"### FR-5"`、`"### M2"`、`"## 5. 风险"`、`"## 七"`、`"### 3.4"` 都已核对唯一。
  - `_table_rows` 按 `|` 拆单元格：§10 新表格的单元格内**不能出现半角 `|`**（用「/」或「、」）。
  - `\bL[1-3]\b` 会扫产品设计与改进方案全文——横幅里也不能写「L3」「可删」这些旧词（写「旧编号」「旧三档」即可）。旧词对照只放在 PRD §12 的「不再使用的旧说法」列（PRD 不在扫描范围）。
  - 快捷筛选用例从 `browse.html` 的 `<button id="fAll|f1|f2|f3|fUn">` 取标签（当前顺序：全部 / 待判断 / 可用 / 废片 / 未用），不要匹配 `pendBadge` 那个 `<span>`。
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py` → 预期 **20 failed**（逐条确认是断言失败而非导入错误；`test_fr5_*` 两条、`test_quick_filters_match_gui` 等都应因文档旧口径失败）。

### Task 2：PRD 头部、§3.3 时间预算、FR-4/FR-5（KI-40、KI-43）
- **ACTION**: UPDATE `docs/PRD-AI粗剪工具.md`。
- **IMPLEMENT**:
  1. `:5-7` 版本表：`v1.1` → `v1.2`；状态 → `已定稿（§13 决策记录）；M11 文档一致校订`；日期 → 实施当天（`date +%F`）。
  2. `:95` 整行替换为：
```markdown
- 全流程人工操作时间 **≤ 20 分钟**，按下表分配（PLAN 验收、产品设计均以此表为准）：

| 环节 | 闸门 | 预算 |
|---|---|---|
| S2 浏览素材与片段 | — | 5 分钟 |
| S3 确认分析 + 裁决待定 | 闸门 A | 3 分钟（其中裁决待定 ≤ 2 分钟，见 FR-5） |
| S3 回答决策问题 | 闸门 A | 3 分钟（FR-6） |
| S4 看预览 + 核对未采用清单 | 闸门 B | 6 分钟 |
| 余量 | — | 3 分钟 |
```
     （表后保留原 `:96-97` 两条红线。注意表格前后各留一空行，否则不是表格。）
  3. FR-4 `:163`：`- 快捷筛选：全部 / 待判断 / 可用 / 未用` → `- 快捷筛选：全部 / 待判断 / 可用 / 废片 / 未用`（与 `gui/static/browse.html:68-72` 一致，D5）。
  4. FR-5 `:175-176` 两行替换为：
```markdown
- "待定"数量上限：总段数 × 28%（最少 10 段），约合 **≤ 40 段/60 分钟素材**，否则人会被淹没（代码 `pipeline/classify.py` `MAX_PENDING_RATIO`）
- 超限时先把非保护段里信息最弱的降为废片；**必留话题段与 AI 标注失败段不自动降级**，超限只给警告、由人逐条裁决
- **验收**：PLAN §4 的 3 条验收素材上，每条待定 ≤ 上限；剪辑师裁决 40 段待定的耗时 ≤ 2 分钟（人工计时）
```
- **MIRROR**: PRD 需求条目写法。
- **GOTCHA**: 验收句必须保留「裁决 40 段」字样（用例按 `裁决\s*(\d+)\s*段` 取样本）和「≤ 40 段/60 分钟」（取上限）；「28%」必须是半角 `%`。
- **VALIDATE**: `uv run pytest tests/test_docs_consistency.py -k "fr5 or quick_filters"` → 3 passed（`test_time_budget_*` 要等 Task 6 改完 PLAN 才绿）。

### Task 3：PRD FR-2 c 路降级 + 新增 FR-14 + §6 数据模型（KI-41、KI-42）
- **ACTION**: UPDATE `docs/PRD-AI粗剪工具.md`。
- **IMPLEMENT**:
  1. FR-2 表 `:136` 替换为：
```markdown
| c 画面 | 540p 代理片本地 1fps 抽帧（不上云） | 逐句画面质量：亮度、运动、清晰度 → 过暗 / 静止 / 抖动 / 虚焦标记；多镜头素材的镜头切点 |
```
     并在 `:138`（「三路按时间对齐…」）之前插入一条：
```markdown
- 景别、人脸数、OCR 文本、道具标签（合同/印章/手机）：**P2**。须本地实现（§7：画面帧不出本机），一期不做
```
  2. 在 FR-13 小节（`:235-239`）之后、`---`（`:241`）之前插入：
```markdown
### FR-14 剪辑偏好（P1，已实现）

- 处理素材前可回答三问：更想保留信息还是情绪（`tone`）/ 片子给谁看（`audience`）/ 2–3 句指定原话（`must_lines`）
- 回答注入 b 路标注与内容摘要的提示词，并调整选段权重（信息优先 / 情绪优先）
- 存进 `project.json` 的 `calibration`（schema v2），随时可改、可重置；CLI `aicut.py calibrate`，GUI「剪辑偏好」页
- **验收**：改偏好后重新处理，标注提示词与选段权重随之变化；指定原话进片（KI-03 修复后）
```
  3. §6 代码块 `:246-254` 替换为：
```
Project   { id, title, material, preset, platform, target_duration, created,
            schema_version, calibration{tone, audience, must_lines} }
Segment   { id, start, end, dur, category, level:废片|待定|可用, level_reason,
            summary, text, speaker, signals{energy, rate, overlap},
            visual{bright, motion, blur, flags},
            ocr, props（P2，见 FR-2）,
            must_keep: bool, usable: bool, used_in: [v1,v2] }
Category  { id, name, segments[], material_duration, usable_duration, budget }
Brief     一期不单独建模，由三处承载：
            calibration{tone, audience, must_lines}（FR-14）
            决策答案 → must_include / must_exclude / ending（FR-6，work/brief_answers.json）
            target_duration / platform / preset（Project）
          one_message、structure：P2
Review    { analysis_confirmed, answers{question_id: option}, overrides[] }
Version   { name, timeline_path, preview_path, draft_name, created }
```
- **MIRROR**: PRD 需求条目写法（FR-11 的形状）。
- **GOTCHA**:
  - 用例要求 §6 里**每一行**含小写 `ocr` 的都带 `P2`——上面只有一行含 `ocr`，别在别的行写 `ocr`。
  - FR-2 里所有含「景别」的行都要带 `P2`；c 画面行不能出现「景别/人脸/OCR/道具」。
  - FR-14 标题必须以 `### FR-14` 开头（追溯用例按 `^### (FR-\d+)` 取全部 FR）。
- **VALIDATE**: `-k "visual_route or data_model or fr14"` 中 `test_data_model_*`、`test_prd_covers_calibration_as_fr14` 绿；`test_visual_route_*` 等 Task 6 去掉 PLAN 的「可选云端」后绿。

### Task 4：PRD §7 非功能、§10 指标、§11、§12 术语、§13 决策（KI-40、KI-43、KI-44）
- **ACTION**: UPDATE `docs/PRD-AI粗剪工具.md`。
- **IMPLEMENT**:
  1. §7 表在「可靠性」行（`:267`）之后插入两行：
```markdown
| 成本 | 同一素材云端转写只计费一次（`work/transcript_raw.json` 已在即跳过）；输入未变时重跑处理不重复调用 LLM；每次处理在任务日志与诊断包里给出本次转写时长与 LLM token 用量（KI-32）。金额上限：KI-32 用量统计落地后，按 PLAN §4 三条验收素材实测均值 × 1.5 回填本行 |
| 断网与服务失败 | 只有转写与 AI 标注 / 摘要 / 提问需要联网；浏览、裁决、改分镜、预览、导出全部离线可用。云端失败时任务明确失败（中文原因 + 重试入口），不产生半成品、不静默降级：已提交的转写任务可续查（绑定音频指纹）；逐句标注失败的句子先落盘，重试只补失败句；内容摘要与决策问题失败时退回兜底，并在界面标明是兜底结果（KI-22）。不做离线转写（PLAN §6） |
```
  2. §10 标题与表（`:298-306`）替换为：
```markdown
## 10. 成功指标（上线后 4 周）

样本默认：上线后 4 周内首批剪辑师交付的**全部**成片，且不少于 10 条（不足则顺延统计期）。记录汇总到 PROGRESS「上线后指标」表。

| 指标 | 目标 | 样本 | 测量方法 |
|---|---|---|---|
| 单条 3 分钟成片的人工时间 | ≤ 20 分钟 | 全部成片，≥ 10 条 | 剪辑师用计时器记 S2–S4 的操作时间（不含等机器），每条一行 |
| 「重要内容是否丢失」满意度 | ≥ 80% | 全部成片，≥ 10 条 | 每条精剪完后问一题：没丢 / 丢了但不重要 / 丢了重要内容；满意 = 未选「丢了重要内容」；满意度 = 满意条数 ÷ 总条数 |
| 剪映工程打开成功率 | ≥ 95% | 全部导出（Mac、Windows 分别计） | 每次导出后记录「能打开并播放：是 / 否」；成功率 = 是 ÷ 总次数（放行检查样本须 100%，见 FR-9） |
| 平均返工轮次 | ≤ 1.5 | 全部项目 | 每个项目返工轮次 = `output/` 下版本数 − 1（每次生成一个 vN，SOP §六）；取平均 |
| 待定队列平均裁决时长 | ≤ 2 分钟 | 验收：PLAN §4 三条素材；上线后：全部项目 | 验收期人工计时；上线后用 `work/overrides.json` 中档位裁决的 `at` 时间戳，取同一次会话首条到末条的跨度作代理值 |
```
  3. §11 第 1 条（`:312`）替换为：
```markdown
1. 分类名：一期由 AI 按素材生成话题名、剪辑师可在确认页改（见 §12「分类（话题）」）；是否另提供剪辑师行话词表（接待 / 谈单 / 签约…）作为命名提示——需一次访谈确认（P2）。
```
  4. §12 表（`:321-327`）替换为：
```markdown
| 术语 | 含义 | 代码里 | 不再使用的旧说法 |
|---|---|---|---|
| 内容单元 | 一句话（2–15 秒）及其三路特征 | `segments` 的一项 | — |
| 档位 | 废片 / 待定 / 可用，是处置状态不是分数 | `level` = 1 / 2 / 3 | L1 / L2 / L3；必留 / 可选 / 可删 |
| 必留段 | 剪辑师在片段浏览器里按 ★ 或 `S` 标记的片段；进片率 100%（FR-7） | `must_keep` | 单说「必留」 |
| 必留话题 | 名称命中关键词、或话题内关键信息句占比 ≥ 30% 的话题；拿保底预算，段落不被自动降为废片 | `topics[].must` | 单说「必留」 |
| 指定原话 | 剪辑偏好第 3 问里剪辑师贴的原话（FR-14） | `calibration.must_lines` | 必留原话 |
| 必须记住的信息 | 决策问题里勾选的话题；覆盖率 ≥ 90%（FR-7） | `brief_answers.json` → `must_topics` | — |
| 分类（话题） | AI 按素材生成的逻辑话题，不是固定表；剪辑师可改 | `topic` | — |
| 闸门 | 必须由人确认才能继续的节点 | — | — |
| 闸门 A | S3 结束：确认分析、裁决待定、回答决策问题 | — | 内容清单（切之前） |
| 闸门 B | S4 结束：看过预览片、核对未采用清单 | — | 选段表（渲染前） |
| 覆盖式选段 | 先满足话题覆盖，再在话题内择优 | `pipeline/select.py` | 排序取前 N |
| 未采用清单 | 可用但本版未进片的片段及原因 | `selection.json` 的 `unused` | — |
```
  5. §13 表末尾追加（日期 = 实施当天）：
```markdown
| <实施日> | c 路景别 / 人脸 / OCR / 道具降为 P2，须本地实现 | FR-2、§6；PLAN 1.3；TECH-STACK（KI-41） |
| <实施日> | 待定上限按总段数 28%（≈ 40 段/60 分钟），必留话题段与标注失败段超限只警告 | FR-5（KI-40） |
| <实施日> | 人工时间预算统一为 §3.3 表；成功指标补样本与测量方法 | §3.3、§10；PLAN M2 / §4（KI-40） |
| <实施日> | 剪辑偏好补入 PRD（FR-14）；Brief 由偏好 + 决策答案 + 项目设置承载 | §5、§6；PLAN §1.1（KI-42） |
| <实施日> | §12 为唯一术语表；闸门以 §4 为准；分类名不固定 | §11、§12；产品设计、改进方案（KI-43） |
| <实施日> | 非功能补成本与断网 / 服务失败；DoD 量化 | §7；PLAN §8（KI-44） |
```
- **MIRROR**: 现有 PRD 表格风格（`| 项 | 内容 |`）。
- **GOTCHA**:
  - §10 单元格里禁止半角 `|`（用例按 `|` 拆格，必须恰好 4 格且非空）。
  - §12 每个规范术语必须写成 `| 术语 |` 的独立单元格（用例找 `| 必留段 |` 等字面量）。
  - §7 两个新行的首格必须正好是 `成本`、`断网与服务失败`。
  - §11 第 1 条保留「分类名」三字（`test_category_names_are_examples_not_fixed` 同时检查 PRD §11）。
- **VALIDATE**: `-k "metrics or glossary or nfr"` → 3 passed。

### Task 5：PROGRESS 与 TECH-STACK（KI-41、KI-42、KI-44）
- **ACTION**: UPDATE `docs/PROGRESS.md`、`docs/TECH-STACK.md`。
- **IMPLEMENT**:
  1. `docs/PROGRESS.md:27` 说明列：`…；景别/人脸/OCR/道具未做（KI-41）` → `…；景别/人脸/OCR/道具已降为 P2（PRD FR-2，KI-41）`。
  2. `docs/PROGRESS.md:77`：`## 运行时校准（PLAN 外新增，待补入 PRD，见 KI-42）` → `## 运行时校准（PRD FR-14 剪辑偏好）`。
  3. `docs/TECH-STACK.md:20`：`| 视频理解 / OCR | MediaKit（可选，未接入） | — | 按需启用，默认关闭以控成本 |` → `| 视频理解 / OCR | 未接入 | — | PRD FR-2 列为 P2；画面帧不出本机（PRD §7），如做须本地实现 |`。
  4. `docs/TECH-STACK.md` §4 表与隐私行（`:90-96`）替换为：
```markdown
| 服务 | 调用方式 | 凭证 | 失败时怎么办（PRD §7「断网与服务失败」） |
|---|---|---|---|
| MediaKit ASR | HTTPS：申请上传地址 → PUT 音轨 → `POST /api/v1/tools/asr-subtitles` → 轮询 `GET /api/v1/tasks/{id}` | `MEDIAKIT_API_KEY`（Keychain，Bearer） | 缺 Key：处理前拦截并引导去设置（GL-02）；网络 / 服务失败：任务失败给中文原因，可重试；已提交任务续查（GL-16） |
| DeepSeek API | HTTPS `POST /chat/completions` | `DEEPSEEK_API_KEY`（Keychain） | 话题分段 / 逐句标注失败：任务失败，已标注部分落盘，重试只补失败句（GL-09）；内容摘要 / 决策问题失败：退回兜底并标记 `fallback` |

**隐私边界**：只上传 16k 单声道音轨（→ 火山引擎 ASR）与转写文本（→ DeepSeek）；原片与画面帧永不出本机（PRD §7）。
```
     （删掉原「MediaKit 视频理解 / OCR」那一行。）
- **MIRROR**: 原表列结构。
- **GOTCHA**: `_section(TECH_STACK, "## 4.")` 依赖原标题 `## 4. 外部服务` 不变；新文本要含「画面帧」、不含「抽帧图」。
- **VALIDATE**: `-k "progress or tech_stack"` → 2 passed。

### Task 6：PLAN 校订（KI-40、KI-41、KI-42、KI-44）
- **ACTION**: UPDATE `docs/PLAN-AI粗剪工具.md`。
- **IMPLEMENT**:
  1. 头注 `:3-6` 替换为：
```markdown
> 依据：[PRD v1.2](PRD-AI粗剪工具.md)（口径冲突以 PRD 为准，术语见 PRD §12）
> 状态以 [PROGRESS](PROGRESS.md) 为准；本文件只保留计划与需求追溯（§1.1），不记录完成状态。
> §2 的 M0–M5 是 2026-10 初的原始计划，保留作历史；当前执行顺序见 [上线 PRD](../.claude/prds/ai-cut-go-live.prd.md) 的上线里程碑 1–11（编号与 M0–M5 无关）。
> 整改项见 [go-live-blockers](go-live-blockers.md) 与 [known-issues](known-issues.md)。
```
  2. `:16`：`**MediaKit（ASR/理解）+ DeepSeek API（LLM）**` → `**MediaKit（ASR）+ DeepSeek API（LLM）**`。
  3. `:37`：`| Windows 导入包（A/B 双格式） | 已交付待测 | FR-9、§9 |` → `| Windows 导入包（A/B 双格式） | 2026-10-18 实测通过；GUI 导出入口已有（GL-14） | FR-9、§9 |`；`:40`「**缺口**：…」→ `**缺口与进度**：见 §1.1 追溯表与 [PROGRESS](PROGRESS.md)。`
  4. 在 `:42`（`---`）之后、`## 2. 里程碑` 之前插入：
```markdown
## 1.1 PRD 需求追溯

每条 PRD 需求 → 计划项 → 尚未关闭的登记项。状态不在这里写，见 PROGRESS。

| 需求 | 优先级 | 计划项 | 未关闭登记项 / 说明 |
|---|---|---|---|
| FR-1 项目与素材导入 | P0 | 已有资产 | KI-66 |
| FR-2 abc 三路分析 | P0 | 1.1 / 1.2 / 1.3 | KI-09、KI-19；c 路景别 / 人脸 / OCR / 道具为 P2 |
| FR-3 内容摘要 | P0 | 1.5 | KI-22 |
| FR-4 片段浏览器 | P0 | 2.1 | KI-35、KI-36 |
| FR-5 档位判定 | P0 | 1.4 / 2.2 | KI-07、KI-08、KI-58 |
| FR-6 确认与提问 | P0 | 2.3 / 2.4 | KI-04、KI-05、KI-49 |
| FR-7 选段与分镜表 | P0 | 3.1 / 3.2 | KI-01、KI-02、KI-03、KI-06、KI-23 |
| FR-8 预览片 | P0 | 3.3 | KI-13、KI-14、KI-73、KI-76；「一键加回」未做 |
| FR-9 剪映工程导出 | P0 | 4.1 | KI-17、KI-18、KI-59 |
| FR-10 版本与回退 | P1 | 4.2 | 只有 vN 递增；对比、回退未做（不在登记册，排期由产品决定） |
| FR-11 "不可用"标记 | P1 | 4.3 | 未开始（不在登记册，排期由产品决定） |
| FR-12 断点续做 | P1 | 5.1 | 半成品与转写续查已修（GL-15、GL-16）；KI-32、KI-62 |
| FR-13 诊断与日志 | P1 | 5.2 | 已实现（GL-19，`ac3f15c`），待放行检查 |
| FR-14 剪辑偏好 | P1 | 运行时校准（PROGRESS） | KI-03、KI-06 |
| Brief（PRD §6） | — | 由 FR-14 + FR-6 决策答案 + 项目设置承载 | one_message、structure 为 P2 |
| 非功能（PRD §7） | — | 5.3–5.6、M1.0 | 成本 KI-32；断网与服务失败 KI-22；测试 KI-38、KI-39 |

---
```
  5. M1.1 表 `:79`：`| 1.3 | c 路：画面质量检测 + 关键帧抽检 + OCR/道具（可选云端）；镜头切分仅用于多镜头素材 | FR-2 | 1.5 | — |` → `| 1.3 | c 路：画面质量检测（亮度 / 运动 / 清晰度，本地）；镜头切分仅用于多镜头素材；景别 / 人脸 / OCR / 道具为 P2（PRD FR-2，须本地实现） | FR-2 | 1.5 | — |`。
  6. M1 验收 `:84`：`- 三档分布合理：待定 ≤ 40 段/60 分钟` → `- 三档分布合理：待定 ≤ 上限（总段数 × 28%，≈ 40 段/60 分钟，PRD FR-5）`。
  7. M2 验收 `:104`：`- 剪辑师独立完成：浏览 → 裁决 41 段待定 → 答 5 题，总时长 ≤ 10 分钟` → `- 剪辑师独立完成：浏览 → 裁决待定（≤ 40 段）→ 答 5 题，总时长 ≤ 11 分钟（PRD §3.3：5 + 3 + 3）`；`:94` 目标「10 分钟内」→「11 分钟内」。
  8. M4 验收 `:132-134` 替换为：
```markdown
- macOS 与 Windows 剪映打开成功率 100%（放行检查样本，PRD FR-9）
- FR-10：连续 5 版互不影响、旧版仍可打开；两版预览可对比、可回退
- FR-11：标记「不可用」后所有版本均不出现该片段
```
  9. M5 验收 `:149-151` 替换为：
```markdown
- 在一台"没装过 Python/ffmpeg"的机器上双击可用（放行检查）
- FR-12：强杀进程后重启，已完成阶段不重跑
- FR-13：出问题能在 1 分钟内导出诊断包
```
  10. §3 `:155-166` 整节替换为：
```markdown
## 3. 排期

原 4 周单线程排期（W1–W5）已执行完毕，不再维护。当前排期与状态见 [上线 PRD](../.claude/prds/ai-cut-go-live.prd.md) 的「Delivery Milestones」（上线里程碑 1–11）。
```
  11. §4 表 `:178`：`| "重要内容是否丢失" | 无严重遗漏 |` → `| "重要内容是否丢失" | 未选「丢了重要内容」（口径同 PRD §10） |`；`:180` `| 剪映工程可打开 | 是 |` → `| 剪映工程可打开 | Mac 与 Windows 均是 |`。
  12. §5 风险表 `:188-195` 替换为：
```markdown
| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 剪映升级改格式 | 中 | 高 | 导出前静态校验门禁（GL-11）；黄金草稿回归（KI-17）。Windows 兼容已于 2026-10-18 实测解除，不再保留降级路径（PRD §9） |
| 远场收音导致 ASR 质量差 | 中 | 中 | 先验 30 秒样音；必要时做人声分离；浏览器里可改文本 |
| LLM 话题分段不稳 / 成本高 | 中 | 中 | 规则切分打底，LLM 只命名归类；结果缓存；成本见 PRD §7（KI-32） |
| 云端服务失败或断网 | 中 | 中 | 明确失败 + 可重试 + 续查，不静默降级（PRD §7「断网与服务失败」） |
| 只对一条素材调优，换素材就崩 | 高 | 高 | 验收必须用 3 条新素材（§4） |
| 界面信息过载，剪辑师不用 | 中 | 高 | 待定 ≤ 上限（PRD FR-5）；默认视图「待判断」；3 人可用性测试 |
```
  13. §7 `:223-230` 第 1 条前加 `~~` 删除线并注「✅ 2026-10-18 已完成」；第 2 条末尾加「（结论回填 PRD §11）」。
  14. §8 DoD `:233-240` 整节替换为：
```markdown
## 8. 完成定义（DoD）

每个里程碑（含上线里程碑 1–11）必须同时满足：

| 维度 | 门槛 | 怎么验 |
|---|---|---|
| 功能 | 对应 PRD 验收项逐条有记录（素材、数值、日期） | 记入 PROGRESS 对应行 |
| 回归测试 | 每个缺陷 / 新行为先写失败的回归测试，再改代码（TDD） | 提交里同时含测试 |
| 测试套件 | `uv run pytest` 全绿，用例数不减少 | 本地与提交前各跑一次 |
| 覆盖率 | ≥ 80%（KI-38 落地 `--cov` 前，以用例数不减少为棘轮） | `uv run pytest --cov`（KI-38） |
| 代码审查 | 无 CRITICAL / HIGH 未决项 | `/ecc:code-review` 或 `/ecc:python-review` |
| 失败路径 | 失败有中文提示且不产生半成品（PRD §7 可靠性） | 对应回归测试 |
| 可用性 | 剪辑师不看文档完成该阶段操作 | 放行检查 / §4 验收 |
| 文档 | 登记册（GL / KI）状态填提交号；PRD / PLAN 口径冲突以 PRD 为准并同步 | `tests/test_docs_consistency.py` |
```
  15. §9 标题 `:244` → `## 9. 如果只做三件事（最小可交付，历史：M0 已完成）`。
- **MIRROR**: 文档横幅写法；PLAN 原表列结构。
- **GOTCHA**:
  - 追溯表每行必须以 `| FR-n ` 开头（用例 `^\| FR-n ` 多行匹配），FR-1..FR-14 一行不少；表内要出现「Brief」「剪辑偏好」。
  - M2 小节内必须出现字面量 `≤ 11 分钟`（半角空格、全角「≤」与 PRD §3.3 一致）；全文件不能再有 `41 段`、`可选云端`、`M0 测试包下发`、`未随实际更新（KI-42）`。
  - `_section(plan, "## 5. 风险")` 与 `"## 8."`、`"## 1.1"` 依赖标题前缀——别改成别的编号。
  - 相对链接：PLAN 在 `docs/`，上线 PRD 在 `.claude/prds/`，链接写 `../.claude/prds/ai-cut-go-live.prd.md`。
- **VALIDATE**: `-k "plan or time_budget or visual_route or fr5"` 全绿。

### Task 7：产品设计文档（KI-40、KI-43）
- **ACTION**: UPDATE `docs/产品设计-AI粗剪工作流.md`。
- **IMPLEMENT**:
  1. `:4` 之后插入横幅：`> 术语以 [PRD §12](PRD-AI粗剪工具.md#12-附录术语) 为准（档位 = 废片 / 待定 / 可用；「必留段」「必留话题」「指定原话」是三件不同的事）；人工时间预算以 PRD §3.3 为准。`
  2. `:28`：`被标为 L3 却没进片的片段` → `档位为可用却没进片的片段`。
  3. `:72-73`：`界面默认给它一个队列（约 20–40 段），…30 秒能清空` → `界面默认给它一个队列（上限约 40 段/60 分钟，PRD FR-5），她按 A/D 过一遍，≤ 2 分钟清空`。
  4. `:75`：→ `- 快捷筛选：全部 / 待判断 / 可用 / 废片 / 未用（同 PRD FR-4）；必留段在列表里以 ★ 显示。`
  5. `:84`：`30 秒清空` → `≤ 2 分钟清空`；`:88`：`（20–40 段）` → `（≤ 40 段/60 分钟，PRD FR-5）`。
  6. `:90-91` 末尾加注：`（当时规则的实测；现由待定上限约束，超出部分按 PRD FR-5 处理）`。
  7. `:114`：`勾选项对应的 L2/L3 片段强制进候选` → `勾选项对应话题的待定 / 可用片段强制进候选`；`:127`：`被标 L3 但没进片的片段` → `可用但没进片的片段`。
  8. `:139`：`level: 1|2|3,` → `level: 1|2|3,      // 1 废片 · 2 待定 · 3 可用（PRD §12）`；`:143` 行尾加 `  // ocr_text、props[]：P2（PRD FR-2）`。
  9. `:160`：`整个流程她的操作时间控制在 **15–20 分钟**（浏览 5 分钟 + 确认 3 分钟 + 答题 3 分钟 + 看预览 6 分钟）` → `整个流程她的操作时间控制在 **≤ 20 分钟**（分配见 PRD §3.3）`。
  10. `:166`：`1. **Level 三档**：…` 保留；`:167-168` 替换为：`2. **分类名**：不固定，由 AI 按素材生成、可在确认页改；以下为《九月一号》生成结果示例（接待与寒暄 / 参观教室 / 讲合同 / 课程与费用 / 就业承诺 /` + 原第二行保持。另在 `:41` 分类行末加「（示例）」。
- **MIRROR**: 原文风格（口语化中文）。
- **GOTCHA**: 横幅必须在文件前 600 个字符内（`:1-4` 很短，插在 `:4` 后即可）；全文件不能残留 `L1/L2/L3`（用 `rg -n "\bL[1-3]\b" docs/产品设计-AI粗剪工作流.md` 自查）；「分类名」与「示例」须在**同一行**。
- **VALIDATE**: `-k "design or category"` 全绿。

### Task 8：选段改进方案（KI-41、KI-43）
- **ACTION**: UPDATE `docs/选段与理解-改进方案.md`。
- **IMPLEMENT**:
  1. `:4` 之后插入横幅：`> 本文是 2026-10-18 的复盘与改版提案，保留作历史。术语、闸门、范围以 [PRD §12](PRD-AI粗剪工具.md#12-附录术语) 与 PRD §4 为准：§3.2 原提的旧三档打分已落地为档位「废片 / 待定 / 可用」+「必留段 / 必留话题」；画面一路的景别 / 人脸 / OCR / 道具为 P2（PRD FR-2）。`
  2. §3.1 画面行 `:71` 末格 `按抽帧量计费，0.2 fps 粗扫` → `P2（PRD FR-2）：须本地实现，画面帧不出本机；一期只做本地画面质量`。
  3. `:88`：``每条打三档：`必留`（brief 指定或信息关键）/ `可选` / `可删`。`` → `每条落到一个档位：废片 / 待定 / 可用（PRD §12）；信息关键的话题记为「必留话题」，剪辑师亲手标的是「必留段」。`
  4. `:98`：`剩余时长用可选段落填充` → `剩余时长用可用段落填充`。
  5. §3.4 `:104-120`：标题下插入 `> 与 PRD §4 对齐：闸门 A = S3 结束（确认分析、裁决待定、回答决策问题，含下面的内容清单）；闸门 B = S4 结束（看预览、核对未采用清单；原提案的选段表检查并入这里）。`；`:118` `**闸门 B · 选段表**（渲染前）` → `**闸门 B · 预览 + 未采用清单**（S4 结束）`。
- **MIRROR**: 文档横幅写法。
- **GOTCHA**: 横幅与正文都不能出现「可删」「`可选`」「L1/L2/L3」；§3.4 内不能再出现「渲染前」三字（横幅在 §3.4 之外，且也没写）。
- **VALIDATE**: `-k "canonical_level or point_to_prd or gate"` 全绿。

### Task 9：`understand_visual.py` docstring（KI-41，行为不变）
- **ACTION**: UPDATE `pipeline/understand_visual.py:1-9`（只改模块 docstring）。
- **IMPLEMENT**:
```python
# -*- coding: utf-8 -*-
"""c 路：画面（PRD FR-2）。

一期只做两件确定的事，全部在本地 540p 代理片上跑，画面帧不出本机（PRD §7）：
  1. 镜头切分（ffmpeg scdet）：只对多镜头 / 剪辑过的素材有意义，一镜到底素材几乎没有切点；
  2. 画面质量（sample_frames / quality）：1fps 灰度小图算亮度、运动、清晰度，标出过暗 / 静止 / 抖动 / 虚焦。
景别、人脸、OCR、道具识别是 P2（PRD FR-2），须本地实现，不送云端视觉模型。
"""
```
- **MIRROR**: 原 docstring 风格。
- **GOTCHA**: 第 1 行 coding 声明与 `from __future__ import annotations`（:10）保持不动。
- **VALIDATE**: `uv run pytest tests/test_understand_visual.py` 原样通过。

### Task 10：全量验证
- **ACTION**: 跑全量测试并自查残留旧词。
- **IMPLEMENT**: 见 Validation Commands。
- **VALIDATE**: 987 + 20 = **1007 passed**。

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_fr5_acceptance_sample_respects_pending_cap` | PRD FR-5、PLAN | 「裁决 N 段」全部 ≤「≤ M 段/60 分钟」；PLAN 无「41 段」 | 是（原 41 > 40） |
| `test_fr5_pending_cap_matches_code_ratio` | PRD FR-5 + `classify.MAX_PENDING_RATIO` | FR-5 含「28%」 | 代码改比例时文档必须跟 |
| `test_time_budget_sums_and_plan_m2_matches` | PRD §3.3 表、PLAN M2 | 合计 20；PLAN M2 含「≤ 11 分钟」 | |
| `test_design_doc_time_budget_defers_to_prd` | 产品设计 | 无「15–20 分钟」「30 秒能清空」，引用 PRD §3.3 | |
| `test_success_metrics_define_sample_and_method` | PRD §10 | 表头含样本 / 测量方法，≥5 行且每行 4 格非空 | 单元格含 `|` 会失败 |
| `test_visual_route_scope_matches_implementation` | PRD FR-2、PLAN | c 行只写画质；含景别的行带 P2；PLAN 无「可选云端」 | |
| `test_data_model_marks_visual_signals_p2_and_schema_version` | PRD §6 | 有 schema_version、calibration；ocr 行带 P2 | |
| `test_tech_stack_matches_privacy_and_fail_loud` | TECH-STACK §4 | 无「抽帧图」、无旧降级文案，有「画面帧」 | |
| `test_plan_traces_every_prd_requirement` | PRD 所有 `### FR-n`、PLAN §1.1 | 每个 FR 一行，含 Brief、剪辑偏好 | 新增 FR 时自动要求追溯 |
| `test_prd_covers_calibration_as_fr14` | PRD FR-14 | 含剪辑偏好、must_lines、验收 | |
| `test_plan_not_stale` | PLAN | 无陈旧排期 / 自认过期注记 / 已解除风险 | |
| `test_progress_no_pending_prd_backfill` | PROGRESS | 无「待补入 PRD」 | |
| `test_glossary_defines_canonical_terms` | PRD §12 | 8 个规范术语各有一行 | |
| `test_design_docs_use_canonical_level_names` | 产品设计、改进方案 | 无 L1–L3、无「可删」「`可选`」 | |
| `test_design_docs_point_to_prd_glossary` | 两份设计文档 | 前 600 字符内引用 PRD §12 | |
| `test_category_names_are_examples_not_fixed` | 产品设计 §七、PRD §11 | 分类名行含「示例」；PRD §11 仍讨论分类名 | |
| `test_gate_definitions_follow_prd` | 改进方案 §3.4 | 引用 PRD §4，无「渲染前」 | |
| `test_quick_filters_match_gui` | PRD FR-4 + `browse.html` 按钮 | 列表逐项相等（含顺序） | GUI 加减按钮时文档必须跟 |
| `test_nfr_covers_cost_and_outage` | PRD §7 | 有「成本」「断网与服务失败」行 | |
| `test_plan_dod_is_quantified` | PLAN §8 | 含 uv run pytest / 80% / 回归测试 / CRITICAL / PROGRESS | |

### Edge Cases Checklist
- [x] 标题不存在 → `_section` 返回空串，断言失败而不是 `StopIteration` 报错
- [x] 表格单元格里出现 `|` → §10 用例失败（GOTCHA 已提示）
- [x] 新增 FR → 追溯用例自动要求 PLAN 补行
- [x] 代码改待定比例 / GUI 改筛选按钮 → 文档用例变红
- [ ] Empty input / Concurrent access / Network failure / Permission denied — N/A（只读仓库文本）

---

## Validation Commands

### Static Analysis
```bash
# 未配置 lint / typecheck；只做编译检查（docstring 改动）
uv run python -m compileall -q pipeline/understand_visual.py tests/test_docs_consistency.py
```
EXPECT: 退出码 0

### Unit Tests
```bash
uv run pytest tests/test_docs_consistency.py tests/test_understand_visual.py
```
EXPECT: Task 1 后 20 failed；Task 2–9 后全部通过

### Full Test Suite
```bash
uv run pytest
```
EXPECT: 1007 passed（基线 987 + 20），无回归

### 残留旧词自查
```bash
rg -n "\bL[1-3]\b|可删|15–20 分钟|41 段|可选云端|待补入 PRD|抽帧图" docs/ --glob '!known-issues.md' --glob '!go-live-blockers.md'
```
EXPECT: 只剩 PRD §12「不再使用的旧说法」列与 §13 决策记录里的引用（如有），以及产品设计 `:90` 的历史实测「待定 41」

### Database / Browser Validation
N/A — 无数据库；不改界面。

### Manual Validation
- [ ] 在编辑器 Markdown 预览里打开 PRD：§3.3 预算表、§10 四列表、§12 四列表都渲染为表格（表格前后有空行）
- [ ] PLAN 里指向 `../.claude/prds/ai-cut-go-live.prd.md` 与 PRD §12 锚点的链接可点开
- [ ] 通读 PRD §4 / §12 与改进方案 §3.4：闸门 A/B 位置一致
- [ ] PLAN §1.1 的每个 KI 编号在 `docs/known-issues.md` 中存在且仍为 open（`rg -n "KI-66|KI-09|…" docs/known-issues.md`）

---

## Acceptance Criteria
- [ ] Task 1–10 完成
- [ ] `uv run pytest` 1007 passed
- [ ] 20 条文档用例先红（Task 1）后绿
- [ ] KI-40：FR-5 样本 ≤ 上限且与代码比例一致；§10 每个指标有样本和方法；时间预算只有 PRD §3.3 一张表
- [ ] KI-41：PRD / PLAN / TECH-STACK / 改进方案 / docstring 对 c 路范围一致（景别等 = P2，本地）
- [ ] KI-42：PLAN §1.1 追溯 FR-1..FR-14 + Brief；PRD 有 FR-14；排期 / 风险 / 外部配合不再陈旧
- [ ] KI-43：PRD §12 为唯一术语表，两份设计文档引用它且无旧词；闸门与 PRD §4 一致；分类名为示例
- [ ] KI-44：PRD §7 有成本与断网 / 服务失败；PLAN DoD 量化

## Completion Checklist
- [ ] 测试沿用 `tests/test_packaging.py` 的只读文本写法
- [ ] 文档以代码常量为准（28%、5 个筛选按钮、`must_keep` / `topics[].must` / `calibration.must_lines`）
- [ ] 不改运行时行为（只有 docstring）
- [ ] 不改登记册与上线 PRD（编排方负责）
- [ ] 无范围外新增（无脚本、无界面改动）
- [ ] 计划自包含，实施时无需再搜代码

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 文档用例过于依赖字面量，后续正常改文档时误报 | 中 | 低 | 只钉结构性口径（上限、合计、追溯、术语行）；文案细节不测；报错信息指明文件 |
| 用户推翻默认决策（如 KI-41 改为要实现） | 中 | 中 | 决策集中在 PRD §13 与 Notes D1–D7；推翻时只改对应段落和 1–2 条用例，实现另开里程碑 |
| PRD §7「成本」金额上限暂为回填规则，不是数字 | 高 | 低 | 明确回填时机（KI-32 落地后）与算法（实测均值 × 1.5），可检验 |
| PLAN §1.1 的 KI 归属写错 | 低 | 低 | Manual Validation 最后一条逐个核对 known-issues |
| 上线里程碑编号（1–11）与 PLAN M0–M5 混淆 | 中 | 低 | PLAN 头注明确「编号无关」；文中引用上线里程碑一律写「上线里程碑 N」 |

## Notes

### 需用户决策（实现按「推荐默认」执行，除非用户另行指定）

| # | 决策点 | 推荐默认 | 备选 |
|---|---|---|---|
| D1（KI-41） | c 路景别 / 人脸 / OCR / 道具：实现还是降级 | **降为 P2**，并写明须本地实现（OCR 走云端会违反 §3.3/§7「画面帧不上云」） | 实现：需本地 OCR / 人脸模型（新依赖、包体积），应另开里程碑 |
| D2（KI-40） | 满意度的样本与口径 | 4 周内全部成片且 ≥ 10 条；每条问一题三选一；「满意」= 未选「丢了重要内容」 | 「满意」只算「没丢」（更严） |
| D3（KI-40） | FR-5 上限与验收样本 | 上限按代码：总段数 × 28%（最少 10），≈ 40 段/60 分钟；验收改为 3 条验收素材、「裁决 40 段 ≤ 2 分钟」 | 保持「≤ 40 段/60 分钟」按时长计，并改代码（属 M6，非本里程碑） |
| D4（KI-44） | 成本上限金额 | 先写「不重复计费 / 不重复调 LLM / 显示用量」三条可检验规则；金额在 KI-32 落地后按 3 条验收素材实测均值 × 1.5 回填 | 现在直接给一个金额（需用户提供数字） |
| D5（KI-43） | 快捷筛选以谁为准 | PRD 跟 GUI：全部 / 待判断 / 可用 / 废片 / 未用 | GUI 去掉「废片」按钮（改界面，属 UI 决策） |
| D6（KI-43） | 分类视图分组头的「必留」标签（`gui/static/browse.html:180`，实为「必留话题」） | **本里程碑不改界面**，只在 PRD §12 定义 | 改为「必留话题」（一行文案改动 + `tests/test_static_pages.py` 视情况补断言） |
| D7（KI-43） | 分类名是否「已定」 | 不固定：AI 按素材生成、可改；产品设计里那 12 个为示例；行话词表作为 P2 访谈问题留在 PRD §11 | 固定一张分类表（需改 `understand_text` 提示词，属 M6） |
| D8（KI-43） | 闸门 B 位置 | 以 PRD §4 为准：S4 结束（看完预览 + 未采用清单） | 改进方案的「渲染前选段表」 |

### 其它观察
- `project.json` 的 `brief: {}`（`pipeline/schema.py:34`）从未被写入；`aicut.py brief` 命令产出的是 `work/brief.md`（策划分派单），`brief_answers.json` 是决策答案——「brief」一词在代码里也有三种用法。本里程碑只在 PRD §6 写清 Brief 的承载方式，不动代码与字段。
- KI-42 登记描述「PLAN 漏 FR-10..13」不完全准确（PLAN 有 4.2/4.3/5.1/5.2 任务行），缺的是验收与追溯；关闭 KI-42 时建议在登记册备注这一点（由编排方处理）。
- 上线 PRD（`.claude/prds/ai-cut-go-live.prd.md`）Open Questions 里 KI-40、KI-41 两条，待用户确认 D1–D3 后由编排方勾掉。
- `docs/PROGRESS.md:8`「112 个用例」等陈旧点不在 KI-40..44 范围内，未纳入。
