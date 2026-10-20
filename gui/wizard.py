# -*- coding: utf-8 -*-
"""六步向导的步骤状态（M13 D1–D4）：`collect` 读盘得到 facts，`derive` 纯函数判定每一步。

四态：locked（未到）/ available（可进入、未完成）/ done / stale（需要更新）。
「需要更新」靠输入指纹（pipeline/fingerprints.py）判断，不用 mtime；每步只看自己的输入，不连锁（D4）。
旧项目没有戳 → 不判过期。collect 里所有读盘都「坏了也不抛」：项目列表不能因一个项目坏掉而 500。
"""
from __future__ import annotations

from pathlib import Path

from gui import analysis, jobs
from pipeline import fingerprints, media_io, outputs, questions, readiness, schema

STEPS = (("new", 1, "新建"), ("analyze", 2, "分析"), ("browse", 3, "看素材"),
         ("criteria", 4, "定标准"), ("result", 5, "看结果"), ("export", 6, "导出"))
CIRCLED = "①②③④⑤⑥"
LOCKED_HINT = "先完成「{n} {label}」"
STALE_ANALYZE = "剪辑偏好或预设改过了 · 重新分析（只重跑 AI 理解及之后的环节，会重新调用 AI）"
STALE_CRITERIA = "决策问题重新生成过 · 请重新作答并确认"
STALE_RESULT_REASONS = {"scored": "分析结果更新了", "overrides": "素材标记改过了",
                        "answers": "答案改过了", "target": "目标时长改过了",
                        "lines": "剪辑偏好里的指定原话改过了"}
STALE_RESULT_ACTION = " · 重新选段"
LEGACY_NOTE = "这个项目在改版前已出过片，没经过定标准；需要时可以在这里确认一次"
ACTION_REANALYZE = "reanalyze"
ACTION_RESELECT = "reselect"
DONE, AVAILABLE, LOCKED, STALE = "done", "available", "locked", "stale"


def _lenient_dict(path: Path) -> dict | None:
    data = schema.read_json_lenient(path, None)
    return data if isinstance(data, dict) else None


def _has_versions(pdir: Path) -> bool:
    return any(d.is_dir() for d in (pdir / "output").glob("v*"))


def is_legacy(pdir: Path, confirmed: bool) -> bool:
    """⚑P2：改版前已出过片 / 有分镜表、但没经过定标准的旧项目。"""
    return not confirmed and (_has_versions(Path(pdir)) or (Path(pdir) / "shots.json").exists())


PREVIEW_FACTS_OFF = {"preview_inputs_now": None, "preview_saved": None, "preview_complete": False,
                     "preview_fresh": False, "exported_current": False}  # 读不出时的保守取值：都当作没有


def _preview_facts(pdir: Path, cfg: dict, now: dict | None = None) -> dict:
    """⑤⑥ 的事实（M14 T7；derive 先不读，规则在 M14b / M14c 启用）。只读：不认领旧文件、不写盘；坏了都当没有。"""
    try:
        now = now if now is not None else fingerprints.preview_inputs(pdir, cfg)
        stamp = outputs.read_stamp(outputs.staging_dir(pdir))
        saved = stamp["inputs"] if stamp else None
        complete = media_io.is_complete(outputs.staging_dir(pdir) / outputs.PREVIEW_FILE)
        has_table = now["table"] not in ("", fingerprints.CORRUPT)  # 空表 / 读不出的表永远不算「预览片是最新的」
        return {"preview_inputs_now": now, "preview_saved": saved, "preview_complete": complete,
                "preview_fresh": bool(has_table and saved is not None and saved == now and complete),
                "exported_current": bool(has_table and outputs.matching_version(pdir, now) is not None)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):  # 坏数据族：项目列表不能 500
        return dict(PREVIEW_FACTS_OFF)


def collect(pdir: Path, cfg: dict, name: str, *, digests: bool = True,
            preview_inputs: dict | None = None) -> dict:
    """读盘得到 facts（只读；任何文件坏了都当没有）。digests=False 跳过所有指纹（项目列表用，预览事实取保守值）。

    preview_inputs：调用方已算好的预览输入指纹（一次 /api/state 请求只算一遍）。"""
    pdir = Path(pdir)
    work = pdir / "work"
    job = jobs.project_job(name)
    art = analysis.facts(pdir, cfg, None)  # 只读：不认领旧版无标记文件（状态判定不能有写盘副作用）
    done = analysis.is_complete(art["artifacts"])
    running = bool(job and job.get("task") == analysis.PREPARE_TASK)
    answers = _lenient_dict(work / questions.ANSWERS_FILE) or {}
    confirmed = answers.get("confirmed") is True
    selection = _lenient_dict(work / "selection.json") or {}
    saved_inputs = selection.get("inputs")
    stamp = _lenient_dict(work / readiness.ANALYSIS_STAMP)
    return {
        "analysis_done": done, "analysis_running": running,
        "analysis_stamp": stamp,
        "analysis_inputs": fingerprints.analysis_inputs(cfg) if digests else None,
        "answers_confirmed": confirmed,
        "answers_questions_digest": answers.get("questions_digest") or None,
        "questions_digest": fingerprints.file_digest(work / "questions.json") if digests else None,
        "legacy": is_legacy(pdir, confirmed),
        "selection_inputs_saved": saved_inputs if isinstance(saved_inputs, dict) else None,
        "selection_inputs_now": fingerprints.selection_inputs(work, cfg) if digests else None,
        "has_versions": _has_versions(pdir),
        **(_preview_facts(pdir, cfg, preview_inputs) if digests else PREVIEW_FACTS_OFF),
    }


def _step(key: str, status: str, *, hint: str | None = None, banner: str | None = None,
          action: str | None = None, reasons: list[str] | None = None) -> dict:
    n, label = next((n, label) for k, n, label in STEPS if k == key)
    return {"key": key, "n": n, "label": label, "status": status, "hint": hint,
            "banner": banner, "action": action, "reasons": reasons or []}


def _locked(key: str, needs: str) -> dict:
    n, label = next((n, label) for k, n, label in STEPS if k == needs)
    return _step(key, LOCKED, hint=LOCKED_HINT.format(n=CIRCLED[n - 1], label=label))


def _analyze_step(f: dict) -> dict:
    if not f["analysis_done"]:
        return _step("analyze", AVAILABLE)
    stamp, now = f["analysis_stamp"], f["analysis_inputs"]
    if stamp and now and stamp != now:  # 无戳（旧项目）→ 不判过期
        return _step("analyze", STALE, banner=STALE_ANALYZE, action=ACTION_REANALYZE,
                     reasons=fingerprints.changed(stamp, now))
    return _step("analyze", DONE)


def _criteria_step(f: dict) -> dict:
    if not f["analysis_done"]:
        return _locked("criteria", "analyze")
    saved, now = f["answers_questions_digest"], f["questions_digest"]
    if f["answers_confirmed"]:
        if saved and now and saved != now:
            return _step("criteria", STALE, banner=STALE_CRITERIA)
        return _step("criteria", DONE)
    if f["legacy"]:
        return _step("criteria", DONE, banner=LEGACY_NOTE)
    return _step("criteria", AVAILABLE)


def _result_step(f: dict) -> dict:
    reasons = fingerprints.changed(f["selection_inputs_saved"], f["selection_inputs_now"] or {})
    if not reasons:
        return _step("result", AVAILABLE)
    text = "、".join(STALE_RESULT_REASONS.get(r, r) for r in reasons)
    return _step("result", STALE, banner=text + STALE_RESULT_ACTION, action=ACTION_RESELECT,
                 reasons=reasons)


def derive(f: dict) -> dict:
    """纯函数：facts → {"steps": [...], "next": key, "legacy": bool}。"""
    analyze = _analyze_step(f)
    browse = _step("browse", DONE) if f["analysis_done"] else _locked("browse", "analyze")
    criteria = _criteria_step(f)
    if criteria["status"] in (DONE, STALE):
        result, export = _result_step(f), _step("export", AVAILABLE)
    else:
        result, export = _locked("result", "criteria"), _locked("export", "criteria")
    steps = [_step("new", DONE), analyze, browse, criteria, result, export]
    if f["analysis_running"] or not f["analysis_done"]:
        nxt = "analyze"
    else:
        nxt = next((s["key"] for s in (criteria, result, export)
                    if s["status"] in (STALE, AVAILABLE)), "export")
    return {"steps": steps, "next": nxt, "legacy": bool(f["legacy"])}


def step_label(derived: dict) -> dict:
    """项目栏「当前步骤」：下一步的 {n, label}。"""
    n, label = next((n, label) for k, n, label in STEPS if k == derived["next"])
    return {"n": n, "label": label}
