"""文档一致性守卫（KI-40..KI-44）：只读仓库文本，断言 PRD / PLAN / 设计文档口径一致、与代码常量一致。"""
import re
from pathlib import Path

import pytest

from pipeline import classify, usage

ROOT = Path(__file__).resolve().parent.parent
PRD = "docs/PRD-AI粗剪工具.md"
PLAN = "docs/PLAN-AI粗剪工具.md"
DESIGN = "docs/产品设计-AI粗剪工作流.md"
IMPROVE = "docs/选段与理解-改进方案.md"
PROGRESS = "docs/PROGRESS.md"
TECH_STACK = "docs/TECH-STACK.md"
BROWSE = "gui/static/step-browse.js"
VISUAL = "pipeline/understand_visual.py"


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
    assert "MAX_PENDING_RATIO" in fr5


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
    header = next((line for line in s10.splitlines() if line.startswith("| 指标")), "")
    assert "样本" in header and "测量方法" in header
    rows = _table_rows(s10)
    assert len(rows) >= 5
    assert all(len(r) == 4 and all(r) for r in rows), rows


# ---------------------------------------------------------------- KI-41 c 路范围
def test_visual_route_scope_matches_implementation():
    fr2 = _section(_read(PRD), "### FR-2")
    c_row = next((line for line in fr2.splitlines() if line.startswith("| c 画面")), "")
    assert "亮度" in c_row and "清晰度" in c_row
    assert not any(w in c_row for w in ("景别", "人脸", "OCR", "道具"))
    p2 = [line for line in fr2.splitlines() if "景别" in line]
    assert p2 and all("P2" in line and "本地" in line for line in p2)
    assert "可选云端" not in _read(PLAN)


def test_visual_module_docstring_matches_scope():
    head = _read(VISUAL)[:800]
    assert "画面质量" in head and "P2" in head and "本地" in head
    assert "按需再上" not in head


def test_data_model_marks_visual_signals_p2_and_schema_version():
    s6 = _section(_read(PRD), "## 6.")
    assert "schema_version" in s6 and "calibration" in s6
    ocr_lines = [line for line in s6.splitlines() if "ocr" in line]
    assert ocr_lines and all("P2" in line for line in ocr_lines)


def test_tech_stack_matches_privacy_and_fail_loud():
    s4 = _section(_read(TECH_STACK), "## 4.")
    assert "抽帧图" not in s4
    assert "退回规则模板（分类名、提问可为空）" not in s4
    assert "画面帧" in s4
    assert "MediaKit 视频理解" not in s4


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


def test_prd_states_target_duration_is_editor_choice():
    prd = _read(PRD)
    assert "--target" in _section(prd, "### FR-1") and "--target" in _section(prd, "### FR-7")


def test_plan_not_stale():
    plan = _read(PLAN)
    assert "M0 测试包下发" not in plan
    assert "未随实际更新（KI-42）" not in plan
    assert "Windows 剪映不认明文草稿" not in _section(plan, "## 5. 风险")


def test_progress_no_pending_prd_backfill():
    progress = _read(PROGRESS)
    assert "待补入 PRD" not in progress
    assert "未开始（FR-13 / GL-19）" not in progress


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
    line = next((line for line in s7.splitlines() if "分类名" in line), "")
    assert "示例" in line
    assert "分类名" in _section(_read(PRD), "## 11.")


def test_gate_definitions_follow_prd():
    gates = _section(_read(IMPROVE), "### 3.4")
    assert "PRD §4" in gates and "渲染前" not in gates


def test_quick_filters_match_gui():
    """step-browse.js 里 FILTERS 常量的中文标签序列 == FR-4「快捷筛选：」行在「（」之前的部分。"""
    block = re.search(r"const FILTERS = \[(.*?)\];", _read(BROWSE), re.S)
    labels = re.findall(r"\['\w+',\s*'([^']+)'\]", block.group(1)) if block else []
    fr4 = _section(_read(PRD), "### FR-4")
    line = next((line for line in fr4.splitlines() if "快捷筛选" in line), "：")
    expected = line.split("：", 1)[1].split("（")[0].strip().split(" / ")
    assert labels and labels == expected


# ---------------------------------------------------------------- KI-44 非功能 / DoD
def test_nfr_covers_cost_and_outage():
    s7 = _section(_read(PRD), "## 7.")
    assert re.search(r"^\| 断网与服务失败 \|", s7, re.M)
    cost = next((line for line in s7.splitlines() if line.startswith("| 成本 |")), "")
    assert usage.BUDGET_ENV in cost
    assert f"{usage.DEFAULT_BUDGET_TOKENS // 10_000} 万 tokens" in cost


def test_plan_dod_is_quantified():
    dod = _section(_read(PLAN), "## 8.")
    for must in ("uv run pytest", "80%", "回归测试", "CRITICAL", "PROGRESS"):
        assert must in dod, must
