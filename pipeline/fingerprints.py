# -*- coding: utf-8 -*-
"""输入指纹（M13 D3）：判断「某一步的结果是不是基于当前输入做出来的」，不看 mtime。

mtime 会被「切换两次 = 原样」、复制项目、时区误报；指纹只取会改变结果的内容，
忽略 at / anchor 等易变字段。所有指纹取 sha1 前 DIGEST_LEN 位；文件缺失记 ""，读不出记 CORRUPT，
任何情况下都不抛（项目列表、状态判定不能因为一个坏文件整体失败）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline import media_io, mode as run_mode, proc, review, schema, shots_store, style, vision

DIGEST_LEN = 12
CORRUPT = "corrupt"
DEFAULT_TARGET_S = 175  # 与 aicut.cmd_select 传给 select.run 的默认目标时长同源
SELECTION_KEYS = ("scored", "overrides", "answers", "target", "lines")
PREVIEW_KEYS = ("table", "unusable", "preset", "title", "platform", "material")  # M14 E2：预览片的分项输入（都进 compose_timeline）
PRESETS_DIR = proc.resource_path("presets")
# 分析戳里后来才加的分项：旧戳缺这一项时按这里的值比较（改版前的项目没开画面理解，不能因此全部变「需要更新」）
ANALYSIS_STAMP_DEFAULTS = {"vision": vision.OFF}


def _sha(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:DIGEST_LEN]


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")


def file_digest(path: Path) -> str:
    try:
        return _sha(Path(path).read_bytes())
    except FileNotFoundError:
        return ""
    except OSError:
        return CORRUPT


def overrides_digest(workdir: Path) -> str:
    """每段只取 level / must_keep is True / unusable is True；False 与缺省等价，按 id 排序。

    手改的起止（有效时）追加在行尾：没改起止的项目指纹与以前逐字节相同。
    """
    try:
        data = review.load(workdir)
    except review.OverridesCorrupt:
        return CORRUPT
    rows = []
    for sid in sorted(data):
        item = data[sid] if isinstance(data[sid], dict) else {}
        row = [sid, item.get("level"), item.get("must_keep") is True, item.get("unusable") is True]
        edited = review.edited_bounds(item)
        if edited:
            row = [*row, *edited]
        if row[1] is not None or row[2] or row[3] or edited:
            rows.append(row)
    return _sha(_canonical(rows))


def answers_digest(workdir: Path) -> str:
    path = Path(workdir) / "brief_answers.json"
    try:
        data = schema.read_json(path, default=None)
    except schema.CorruptJSON:
        return CORRUPT
    if data is None:
        return ""
    custom = data.get("custom") or {}
    if not custom:  # 没填自定义：和以前同一个指纹，老项目不误报「需要更新」
        return _sha(_canonical(data.get("answers") or {}))
    return _sha(_canonical({"answers": data.get("answers") or {}, "custom": custom}))


def target_of(cfg: dict) -> int:
    """与 aicut.cmd_select 同源：int(target_duration or 175)。"""
    try:
        return int(float(cfg.get("target_duration") or DEFAULT_TARGET_S))
    except (TypeError, ValueError, OverflowError):  # OverflowError：JSON 里的 Infinity
        return DEFAULT_TARGET_S


def selection_inputs(workdir: Path, cfg: dict) -> dict[str, str]:
    """选段的分项输入指纹，键序固定为 SELECTION_KEYS（横幅按这个顺序拼原因）。"""
    work = Path(workdir)
    if run_mode.is_simple(cfg):  # 简单模式只看分析结果、剪辑列表（素材标记）和模式：答案 / 目标 / 偏好都不影响结果
        return {"scored": file_digest(work / "segments_scored.json"), "overrides": overrides_digest(work),
                "mode": run_mode.SIMPLE}
    calib = style.normalize(cfg.get("calibration"))
    return {
        "scored": file_digest(work / "segments_scored.json"),
        "overrides": overrides_digest(work),
        "answers": answers_digest(work),
        "target": str(target_of(cfg)),
        "lines": _sha(_canonical([calib["tone"], calib["must_lines"]])),
    }


def analysis_inputs(cfg: dict) -> dict[str, str]:
    """AI 理解及之后各环节的输入：剪辑偏好指令 + 预设 + 画面理解设置。"""
    return {"directive": style.directive(cfg.get("calibration")), "preset": cfg.get("preset") or "",
            "vision": vision.fingerprint(vision.normalize(cfg.get("vision")))}


def changed(saved: object, now: dict) -> list[str]:
    """两份分项指纹里不同的分项名（按 now 的顺序）；saved 不是对象 / 缺这一项 → 不判（旧数据没有戳）。"""
    if not isinstance(saved, dict):
        return []
    out = [k for k, v in now.items() if k in saved and saved[k] != v and k != "mode"]
    # 出片模式只在简单模式时才记：任一边缺 mode = 完整模式，所以要按「缺省 full」比，不能照「缺键不判」
    if saved.get("mode", run_mode.FULL) != now.get("mode", run_mode.FULL):
        out.append("mode")
    return out


def table_digest(shots: list[dict]) -> str:
    """分镜表指纹：只看每镜 [id, in, out, sub]（note 等不影响成片）；空表 ""。"""
    if not shots:
        return ""
    return _sha(_canonical([[s.get("id"), s.get("in"), s.get("out"), s.get("sub") or ""] for s in shots]))


def unusable_digest(workdir: Path) -> str:
    """被标为「不可用」的片段 id 集合的指纹（出片会按它剔镜头）；overrides 读不出记 CORRUPT。"""
    try:
        data = review.load(workdir)
    except review.OverridesCorrupt:
        return CORRUPT
    ids = sorted(sid for sid, item in data.items() if isinstance(item, dict) and item.get("unusable") is True)
    return _sha(_canonical(ids))


def _material_digest(cfg: dict) -> str:
    fp = media_io.source_fingerprint(cfg.get("material"))
    return _sha(_canonical(fp)) if fp else ""


def _preset_digest(cfg: dict) -> str:
    """预设名 + 预设文件内容：名字没变但文件被改了（升级 / 手改）也算变。"""
    name = cfg.get("preset") or ""
    return _sha(_canonical([name, file_digest(PRESETS_DIR / f"{name}.json") if name else ""]))


def preview_inputs(pdir: Path, cfg: dict) -> dict[str, str]:
    """预览片的分项输入指纹（键序固定为 PREVIEW_KEYS）：当前分镜表（手动优先）、不可用集合、预设、素材。

    读表失败（损坏）记 CORRUPT，不抛：状态判定与项目列表不能因为一个坏文件整体失败。
    """
    try:
        shots, _source = shots_store.current(pdir)
        table = table_digest(shots)
    except (schema.CorruptJSON, ValueError, OSError):
        table = CORRUPT
    return {
        "table": table,
        "unusable": unusable_digest(Path(pdir) / "work"),
        "preset": _preset_digest(cfg),
        "title": _sha(_canonical(cfg.get("title") or "")),
        "platform": _sha(_canonical(cfg.get("platform") or "")),
        "material": _material_digest(cfg),
    }
