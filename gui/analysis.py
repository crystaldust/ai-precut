# -*- coding: utf-8 -*-
"""② 分析页的人话进度（M13 D11）：11 项，完成看产物，耗时 / 失败看 work/timings.json。

`progress(facts)` 是纯函数（只吃 dict，不碰盘）；`facts()` 负责读盘。
「正在跑哪一步」= 本次任务开始后第一个还没有计时记录的 PREPARE_STEPS 阶段（applog.stage 只在阶段
结束时写计时，据此推当前步骤，不改 aicut 的输出格式）。timings.json 的 `started` 是 UTC ISO 字符串，
任务的 `started` 是 time.time()：统一转 epoch 再比较。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pipeline import media_io, readiness, schema

NOTICE = "分析大约 10–15 分钟，可以关掉窗口，回来接着跑"
PREPARE_TASK = "prepare"

# (key, 人话, 依赖的 PREPARE_STEPS, 完成判据)；顺序 = D10 执行顺序 = 规格顺序
ANALYSIS_STEPS = (
    ("ingest", "读取素材", ("ingest",), "materials"),
    ("proxy", "生成浏览小样", ("junk",), "proxy"),
    ("audio", "抽音轨", ("transcribe",), "wav"),
    ("asr", "云端转写", ("transcribe",), "segments"),
    ("voice", "声音分析", ("analyze",), "audio_json"),
    ("visual", "画面检查", ("scenes", "quality"), "visual"),
    ("text", "AI 理解对话", ("text",), "text_json"),
    ("score", "判定档位", ("score",), "scored"),
    ("summary", "写内容摘要", ("summary",), "summary"),
    ("questions", "准备决策问题", ("questions",), "questions"),
    ("select", "初步选段", ("select", "brief"), "selection"),
)
ARTIFACT_FILES = {  # 完成判据 → 相对 work/ 的文件（proxy / wav 另有完整性检查，绑定当前素材）
    "materials": "materials.json", "segments": "segments.json", "audio_json": "segments_audio.json",
    "visual": "shots_visual.json", "text_json": "segments_text.json",
    "scored": "segments_scored.json", "summary": "content_summary.json",
    "questions": "questions.json", "selection": "selection.json",
}
ARTIFACT_KEYS = ("materials", "proxy", "wav", "segments", "audio_json", "visual", "text_json",
                 "scored", "summary", "questions", "selection")
# 整个「分析」算完成的判据，与 gui/wizard.py 的 analysis_done 同一份（旧项目没有戳也适用）
COMPLETE_KEYS = ("proxy", "scored", "summary", "questions", "selection")
# 画面质量检查失败只是警告、不产出文件：这些步骤的依赖阶段全部 ok 也算完成
TIMINGS_DONE_STEPS = frozenset({"visual"})
# 同一个阶段里中途就产出文件的步骤：转写阶段先抽音轨再转写，抽完音轨就算「抽音轨」完成
INTRA_STAGE_STEPS = frozenset({"audio"})
# timings 的时间戳截断到秒，任务开始是小数秒：同一秒内记录的阶段不能被当成「上一轮」的
FRESH_TOLERANCE_S = 1.0


def is_complete(artifacts: dict) -> bool:
    return all(bool(artifacts.get(k)) for k in COMPLETE_KEYS)


def facts(pdir: Path, cfg: dict, job: dict | None) -> dict:
    """读盘：产物布尔 + timings + 任务快照（jobs.project_job_detail）。读不出的当没有。"""
    work = Path(pdir) / "work"
    material = cfg.get("material") or None  # KI-62：素材换过的音轨 / 代理不算完成
    artifacts = {k: (work / name).exists() for k, name in ARTIFACT_FILES.items()}
    # 只读判断：不认领旧版无标记文件（会跑 ffprobe 并写标记）。认领留给 prepare / 项目打开时的 has_proxy
    artifacts["proxy"] = media_io.is_complete(work / "proxy.mp4", source=material)
    artifacts["wav"] = media_io.is_complete(work / "audio/asr.wav", source=material)
    timings = schema.read_json_lenient(work / "timings.json", {})
    return {"artifacts": artifacts, "timings": timings if isinstance(timings, dict) else {},
            "job": job}


def _epoch(iso: object) -> float | None:
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _entry(timings: dict, key: str) -> dict:
    item = timings.get(key)
    return item if isinstance(item, dict) else {}


def _seconds(entry: dict) -> float | None:
    value = entry.get("seconds")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _fresh(entry: dict, since: float) -> bool:
    """这个阶段在本次任务开始后跑过（真正执行或被跳过）。"""
    return any((t := _epoch(entry.get(k))) is not None and t >= since - FRESH_TOLERANCE_S
               for k in ("started", "last_skipped"))


def _running_stage(timings: dict, since: float) -> str | None:
    for key in readiness.PREPARE_STEPS:
        if not _fresh(_entry(timings, key), since):
            return key
    return None


def _ran_this_time(key: str, deps: tuple, stage: str | None, timings: dict, since: float) -> bool:
    """重新分析进行中：这一步的依赖阶段在本次任务里都跑过（或被跳过）才算完成，上一轮的产物 / 计时不算。"""
    if all(_fresh(_entry(timings, d), since) for d in deps):
        return True
    return key in INTRA_STAGE_STEPS and stage in deps


def _owner_of_seconds() -> dict[str, str]:
    """阶段 → 显示它耗时的步骤：同一个阶段被多个步骤依赖时（转写 = 抽音轨 + 云端转写）只记在最后一个上。"""
    return {dep: key for key, _, deps, _ in ANALYSIS_STEPS for dep in deps}


def _step_status(key: str, deps: tuple, artifact: str, f: dict, run: dict | None) -> str:
    """run：分析正在跑时 {"since", "stage"}；没在跑为 None。"""
    timings = f["timings"]
    entries = [_entry(timings, d) for d in deps]
    has_result = bool(f["artifacts"].get(artifact)) or (
        key in TIMINGS_DONE_STEPS and all(e.get("ok") is True for e in entries))
    if has_result and (run is None or _ran_this_time(key, deps, run["stage"], timings, run["since"])):
        return "done"
    running = run is not None
    if not running and any(e.get("ok") is False for e in entries):
        return "failed"
    return "waiting"


def progress(f: dict) -> dict:
    job = f.get("job") or {}
    running = job.get("task") == PREPARE_TASK and job.get("status") == "running"
    owner = _owner_of_seconds()
    since = float(job.get("started") or 0)
    run = {"since": since, "stage": _running_stage(f["timings"], since)} if running else None
    steps = []
    for key, label, deps, artifact in ANALYSIS_STEPS:
        sec = [s for d in deps if owner[d] == key and (s := _seconds(_entry(f["timings"], d))) is not None]
        steps.append({"key": key, "label": label,
                      "status": _step_status(key, deps, artifact, f, run),
                      "seconds": round(sum(sec), 2) if sec else None})
    current = None
    if running:
        stage = run["stage"]
        pending = [(s, d) for s, (_, _, d, _) in zip(steps, ANALYSIS_STEPS) if s["status"] == "waiting"]
        current = next((s["key"] for s, d in pending if stage in d),
                       pending[0][0]["key"] if pending else None)
        steps = [{**s, "status": "running"} if s["key"] == current else s for s in steps]
    failed = next((s for s in steps if s["status"] == "failed"), None)
    return {
        "steps": steps, "done": sum(s["status"] == "done" for s in steps), "total": len(steps),
        "complete": is_complete(f["artifacts"]), "running": current, "notice": NOTICE,
        "failed": ({"key": failed["key"], "label": failed["label"], "reason": job.get("last_error")}
                   if failed else None),
    }
