# -*- coding: utf-8 -*-
"""剪辑台 · 只读视图（从 gui/server.py 拆出，KI-54）。

不读 server.PROJECTS / PRESETS：调用方把解析好的目录传进来（测试只打桩 server 上的名字）。
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from gui import jobs, wizard
from pipeline import media_io, notices, proc, schema, select, usage

PRESET_CORRUPT_MSG = "已跳过预设「{name}」：{reason}"
FFMPEG_VERSION_TIMEOUT_S = 5
FFMPEG_VERSION_MAX = 60


def jload(p: Path, default=None):
    """只用于显示：缺失或损坏都给 default；损坏的由 notices.corrupt_files 在警告栏点名（KI-21）。"""
    return schema.read_json_lenient(p, default)


def _version_sort_key(d: Path) -> int:
    return int(d.name[1:]) if d.name[1:].isdigit() else 0


def _versions(pdir: Path, cfg: dict, name: str) -> list[dict]:
    versions = []
    for d in sorted((pdir / "output").glob("v*"), key=_version_sort_key):
        if not d.is_dir():
            continue
        tl = jload(d / "timeline.json", {})
        total = 0.0
        if tl.get("video"):
            total = max((s["timeline_in"] + s["out"] - s["in"]) for s in tl["video"])
        versions.append({
            "name": d.name,
            "preview": media_io.complete_or_adopt(d / "preview.mp4"),
            "shots": len(tl.get("video", [])),
            "duration": round(total, 1),
            "draft": f"{cfg.get('title', name)}_{d.name}",
            "mtime": time.strftime("%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
            **jobs.windows_export_state(pdir, d.name, cfg.get("title")),
        })
    return list(reversed(versions))


def project_state(pdir: Path, name: str) -> dict:
    cfg = schema.read_json(pdir / "project.json", default=None)  # 损坏 → CorruptJSON → 409（KI-21）
    if not cfg:
        raise FileNotFoundError(name)
    schema.ensure_supported(cfg)  # 新版程序建的项目不能让旧界面去改
    work = pdir / "work"
    material = cfg.get("material") or None  # KI-62：素材换过的音轨 / 代理不算完成
    manual = jload(pdir / "shots.json", {}).get("shots", [])
    selected = jload(work / "shots-selected.json", {}).get("shots", [])
    return {
        "project": cfg,
        "versions": _versions(pdir, cfg, name),
        "segments": jload(work / "segments.json", {}).get("segments", []),
        # 没有手存分镜表时用选段结果预填；有就不覆盖（M2）
        "shots": manual or selected,
        "shots_from_selection": not manual and bool(selected),
        "selection": select.summary(jload(work / "selection.json")),
        "warnings": notices.project_warnings(work),
        "material_duration": (jload(work / "materials.json", {}).get("items") or [{}])[0].get("duration", 0),
        "has_proxy": media_io.complete_or_adopt(work / "proxy.mp4", source=material),
        "has_transcript": (work / "transcript.md").exists(),
        "llm_usage": usage.summary(work),  # KI-32：项目信息行显示已用 tokens
        "job": jobs.project_job(name),  # 切回正在跑任务的项目时，界面据此重新显示进度
        "wizard": wizard.derive(wizard.collect(pdir, cfg, name)),  # M13：六步向导的步骤状态
        "busy": jobs.busy_view(),  # 全局正在跑的任务（任务胶囊）
    }


def _step_of(pdir: Path, cfg: dict) -> dict | None:
    """项目栏的「当前步骤」；project.json 损坏 / 读不出 → None（列表不能因为一个坏项目失败）。"""
    if not cfg:
        return None
    try:
        facts = wizard.collect(pdir, cfg, cfg.get("name", pdir.name), digests=False)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):  # 坏数据族：列表不能 500
        return None
    return wizard.step_label(wizard.derive(facts))


def projects_list(root: Path) -> list[dict]:
    items = []
    for f in sorted(root.glob("*/project.json")):
        c = jload(f, {})
        pdir = f.parent
        vs = sorted([d.name for d in (pdir / "output").glob("v*") if d.is_dir()])
        items.append({"name": c.get("name", pdir.name), "title": c.get("title", ""),
                      "preset": c.get("preset", ""), "versions": vs, "step": _step_of(pdir, c)})
    return items


def presets_payload(presets: Path) -> dict:
    out, bad = [], []
    for f in sorted(presets.glob("*.json")):
        try:
            c = schema.read_json(f)
        except schema.CorruptJSON as exc:  # 坏预设跳过，但要说出来（新建弹窗里显示）
            bad.append(PRESET_CORRUPT_MSG.format(name=f.stem, reason=exc))
            continue
        out.append({"key": f.stem, "name": c.get("name", f.stem),
                    "platform": c.get("platform"), "duration": c.get("duration")})
    return {"presets": out, "warnings": bad}


def health_payload() -> dict:
    ff = shutil.which("ffmpeg")
    ver = ""
    if ff:
        try:
            ver = subprocess.run([ff, "-version"], capture_output=True, text=True,
                                 timeout=FFMPEG_VERSION_TIMEOUT_S).stdout.splitlines()[0][:FFMPEG_VERSION_MAX]
        except Exception:  # noqa: BLE001 - 只是展示用的版本号
            ver = "?"
    return {"frozen": proc.FROZEN, "app_root": str(proc.app_root()),
            "projects_root": str(proc.user_data_root()),
            "ffmpeg": ff, "ffmpeg_version": ver, "ffprobe": shutil.which("ffprobe")}
