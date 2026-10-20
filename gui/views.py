# -*- coding: utf-8 -*-
"""剪辑台 · 只读视图（从 gui/server.py 拆出，KI-54）。

不读 server.PROJECTS / PRESETS：调用方把解析好的目录传进来（测试只打桩 server 上的名字）。
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from gui import jianying, jobs, wizard
from pipeline import (
    exclusions, fingerprints, media_io, notices, outputs, proc, review, schema, select, shots_store, usage,
)

PRESET_CORRUPT_MSG = "已跳过预设「{name}」：{reason}"
FFMPEG_VERSION_TIMEOUT_S = 5
FFMPEG_VERSION_MAX = 60


def jload(p: Path, default=None):
    """只用于显示：缺失或损坏都给 default；损坏的由 notices.corrupt_files 在警告栏点名（KI-21）。"""
    return schema.read_json_lenient(p, default)


def _version_card(pdir: Path, cfg: dict, name: str, d: Path, now_inputs: dict, marked: list | None) -> dict:
    """一张版本卡片的数据；全部宽松读（坏文件只让对应字段变空，不能让 /api/state 失败）。"""
    shots, duration = outputs.version_facts(d)
    exports = outputs.read_exports(d)
    legacy = exports is None  # 改版前生成的版本没有 export.json：照旧显示草稿名，界面注明「改版前生成」
    stamp = outputs.read_stamp(d)
    hits, blocked = outputs.export_block(pdir, d.name, marked)  # KI-100：含不可用片段（或无法确认）
    return {
        "name": d.name,
        "preview": media_io.complete_or_adopt(d / "preview.mp4"),
        "shots": shots,
        "duration": duration,
        # KI-102：只有真的装进过 Mac 剪映（export.json.mac）才给草稿名；--no-draft 的新版本剪映里没有这份草稿
        "draft": f"{cfg.get('title', name)}_{d.name}" if legacy or exports.get("mac") else None,
        "mtime": time.strftime("%m-%d %H:%M", time.localtime(d.stat().st_mtime)),
        "exports": exports,
        "legacy": legacy,
        "current": stamp is not None and stamp["inputs"] == now_inputs,  # E6：这一版就是当前分镜表
        "has_snapshot": (d / "shots_snapshot.json").is_file(),
        "unusable_hits": hits,
        "blocked": blocked,
        **jobs.windows_export_state(pdir, d.name, cfg.get("title")),
    }


def _marked_spans(pdir: Path) -> list | None:
    """标为不可用的片段（所有版本卡片共用一次读取）；读不出 → None，让每张卡片自己报「无法确认」。"""
    try:
        return exclusions.spans(pdir / "work")
    except (review.OverridesCorrupt, schema.CorruptJSON, KeyError, TypeError, ValueError):
        return None


def _versions(pdir: Path, cfg: dict, name: str, now_inputs: dict | None = None) -> list[dict]:
    dirs = outputs.version_dirs(pdir)  # 已完成的 v<数字>；不含暂存 / 点目录 / 没有时间线的残目录
    if not dirs:
        return []
    if now_inputs is None:
        now_inputs = fingerprints.preview_inputs(pdir, cfg)
    marked = _marked_spans(pdir)
    return [_version_card(pdir, cfg, name, d, now_inputs, marked) for d in reversed(dirs)]


def project_state(pdir: Path, name: str) -> dict:
    cfg = schema.read_json(pdir / "project.json", default=None)  # 损坏 → CorruptJSON → 409（KI-21）
    if not cfg:
        raise FileNotFoundError(name)
    schema.ensure_supported(cfg)  # 新版程序建的项目不能让旧界面去改
    work = pdir / "work"
    material = cfg.get("material") or None  # KI-62：素材换过的音轨 / 代理不算完成
    manual = jload(pdir / "shots.json", {}).get("shots", [])
    selected = jload(work / "shots-selected.json", {}).get("shots", [])
    inputs = fingerprints.preview_inputs(pdir, cfg)  # 一次请求只算一遍：版本卡片、预览状态、步骤状态共用
    return {
        "project": cfg,
        "versions": _versions(pdir, cfg, name, inputs),
        "segments": jload(work / "segments.json", {}).get("segments", []),
        # 没有手存分镜表时用选段结果预填；有就不覆盖（M2）
        "shots": manual or selected,
        "shots_from_selection": not manual and bool(selected),
        "selection_digest": fingerprints.file_digest(work / "shots-selected.json"),  # 保存分镜表时带回，防止存进被「覆盖」换掉的选段
        "selection": select.summary(jload(work / "selection.json")),
        "warnings": notices.project_warnings(work),
        "material_duration": (jload(work / "materials.json", {}).get("items") or [{}])[0].get("duration", 0),
        "has_proxy": media_io.complete_or_adopt(work / "proxy.mp4", source=material),
        "has_transcript": (work / "transcript.md").exists(),
        "llm_usage": usage.summary(work),  # KI-32：项目信息行显示已用 tokens
        "job": jobs.project_job(name),  # 切回正在跑任务的项目时，界面据此重新显示进度
        "wizard": wizard.derive(wizard.collect(pdir, cfg, name, preview_inputs=inputs)),  # M13：六步向导的步骤状态
        "busy": jobs.busy_view(),  # 全局正在跑的任务（任务胶囊）
        "manual": shots_store.manual_changes(pdir),  # M14：手动改了几处（不抛）
        "preview": {"status": outputs.preview_state(pdir, cfg, inputs)["status"]},  # 暂存预览片是不是当前分镜表的
        "jianying": {"installed": jianying.installed()},  # KI-98：没装就不显示「打开剪映」
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
        vs = [d.name for d in outputs.version_dirs(pdir)]
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
