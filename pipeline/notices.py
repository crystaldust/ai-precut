# -*- coding: utf-8 -*-
"""把各环节落在 work/ 里的警告收拢成一张清单，给剪辑台常驻显示（M2）。

只读、不抛异常：任何文件缺失或读不出来都不能让界面打不开；但读不出来的文件要逐个点名（KI-21）。
"""
from __future__ import annotations

from pathlib import Path

from pipeline import schema, understand_text

TEXT_INCOMPLETE_NOTICE = "上次逐句标注没有完成，部分句子还没有 AI 标注：在「② 分析」点「重新分析」只会补跑这些句子"
MISSING_TOPICS_NOTICE = "这些必留话题在成片里没有镜头：{topics}"
SUMMARY_FALLBACK_NOTICE = "内容摘要是兜底生成的（AI 调用失败：{error}）：在「② 分析」点「重新分析」会再试"
QUESTIONS_FALLBACK_NOTICE = ("决策问题是兜底模板生成的（AI 调用失败：{error}）："
                             "还没作答时在「② 分析」点「重新分析」会重新生成")
UNKNOWN_REASON = "原因未记录"
CORRUPT_FILE_NOTICE = "{label}（{rel}）损坏、读不出来，界面上按「没有」显示：{remedy}"
REMEDY_REBUILD = "在「② 分析」点「重新分析」会重建"
REMEDY_RESELECT = "在「⑤ 看结果」改目标时长或重新选段会重建"
REMEDY_REANSWER = "到「④ 定标准」重新作答"
REMEDY_REBUILD_VERSION = "在「⑥ 导出」生成新版本会重建这一版"
CORRUPT_SHOTS_NOTICE = ("分镜表（shots.json）损坏、读不出来，界面上显示的是自动选段结果："
                        "在「分镜表」里重新保存会覆盖它")
TIMELINE_LABEL = "{version} 的时间线"
WATCHED_FILES = (("work/shots-selected.json", "自动选段的分镜表", REMEDY_RESELECT),
                 ("work/selection.json", "选段结果", REMEDY_RESELECT),
                 ("work/segments.json", "分段文稿", REMEDY_REBUILD),
                 ("work/segments_scored.json", "三档判定", REMEDY_REBUILD),
                 ("work/junk_report.json", "废片表", REMEDY_REBUILD),
                 ("work/materials.json", "素材台账", REMEDY_REBUILD),
                 ("work/content_summary.json", "内容摘要", REMEDY_REBUILD),
                 ("work/questions.json", "决策问题", REMEDY_REBUILD),
                 ("work/brief_answers.json", "决策答案", REMEDY_REANSWER))
FALLBACK_FILES = (("content_summary.json", SUMMARY_FALLBACK_NOTICE),
                  ("questions.json", QUESTIONS_FALLBACK_NOTICE))


def _read(path: Path) -> dict:
    return schema.read_json_lenient(path, {})


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
    out += [CORRUPT_FILE_NOTICE.format(label=label, rel=rel, remedy=remedy)
            for rel, label, remedy in WATCHED_FILES if _corrupt(pdir / rel)]
    out += [CORRUPT_FILE_NOTICE.format(label=TIMELINE_LABEL.format(version=t.parent.name),
                                       rel=t.relative_to(pdir).as_posix(), remedy=REMEDY_REBUILD_VERSION)
            for t in sorted(pdir.glob("output/v*/timeline.json")) if _corrupt(t)]
    return out


def _texts(values) -> list[str]:
    return [str(v) for v in values or [] if v] if isinstance(values, list) else []


def fallback_notice(notice: str, data: dict) -> str:
    """LLM 兜底结果的提示：带上当时记录的失败原因（KI-22）。"""
    return notice.format(error=data.get("error") or UNKNOWN_REASON)


def project_warnings(workdir: Path) -> list[str]:
    """标注未完成 → 分档警告 → 选段警告（超目标、其他、未覆盖的必留话题）→ LLM 兜底 → 损坏文件。"""
    workdir = Path(workdir)
    out: list[str] = []
    if understand_text.is_incomplete(workdir / "segments_text.json"):
        out.append(TEXT_INCOMPLETE_NOTICE)
    items = _read(workdir / "materials.json").get("items")
    out += [w for it in (items if isinstance(items, list) else []) if isinstance(it, dict)
            for w in _texts(it.get("warnings"))]  # 素材台账（容器没有时长）
    out += _texts(_read(workdir / "segments.json").get("warnings"))  # 转写整理（KI-24 跳句）
    out += _texts(_read(workdir / "segments_scored.json").get("warnings"))
    sel = _read(workdir / "selection.json")
    out += _texts([sel.get("over_target_warning")]) + _texts(sel.get("warnings"))
    topics = _texts(sel.get("missing_must_topics"))
    if topics:
        out.append(MISSING_TOPICS_NOTICE.format(topics="、".join(topics)))
    for name, notice in FALLBACK_FILES:
        data = _read(workdir / name)
        if data.get("fallback"):
            out.append(fallback_notice(notice, data))
    return out + corrupt_files(workdir.parent)
