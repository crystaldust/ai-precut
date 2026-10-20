# -*- coding: utf-8 -*-
"""剪辑台 · 项目内容类接口：浏览素材、确认与提问、剪辑偏好（从 gui/server.py 搬出，行为不变）。

路由模块范式同 gui/maintenance.py：返回 (状态码, JSON) 或 None（不是本模块的路径）；
项目解析由 server 传入。ProjectCorrupt 不在这里捕获，由 server 统一回 409。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from gui import analysis, confirm, jobs, payloads, wizard
from pipeline import (
    applog, exclusions, review, schema, select_rules, shots_store, style, topic_names,
)

LOG = applog.get("gui")
Lookup = Callable[[str], Path]
SAVED_BUT_STALE_MSG = "已保存，但没能读回最新状态，已重新读取"
RESTORE_SHOTS_MAX = 500  # 撤销不可用时一次最多放回的镜头数（请求体上限；实际还要和备份核对）
BAD_RESTORE_MSG = "restore_shots 必须是镜头列表（最多 {max} 镜）"
MISSING_ID_MSG = "缺少 id"
BAD_PARAM_MSG = "参数不对：id 必须是文本，{flag} 必须是 true 或 false"
SHOTS_BACKUP = "shots.before-unusable.json"  # work/ 下最近一次移除镜头前的分镜表备份（供以后撤销）
UNKNOWN_SEGMENT_MSG = "找不到片段 {id}：先完成分析，或刷新后重试"
DEFAULT_TARGET_S = payloads.DEFAULT_TARGET_S
MUST_LINES_MAX = 3  # 剪辑偏好里「必须保留的原话」最多几句
MUST_LINES_TOO_MANY_MSG = "指定原话最多 3 句，现在有 {n} 句"
CALIBRATION_NOT_OBJECT_MSG = "calibration 必须是对象（tone / audience / must_lines）"
BAD_TONE_MSG = "剪辑偏好 tone 只能是：{allowed}"
BAD_CALIBRATION_FIELD_MSG = "剪辑偏好里的 {field} 必须是文字，且不能含控制字符"
UNKNOWN_PRESET_MSG = "未知预设：{preset}"
NOTHING_TO_CHANGE_MSG = "没有要修改的内容"
TOPIC_ARGS_MSG = "name 和 display 都必须是文字"
TOPIC_NOT_FOUND_MSG = "找不到话题「{name}」：先完成分析"
TOPIC_DISPLAY_TOO_LONG_MSG = "话题名最多 {max} 个字"
TOPIC_DISPLAY_BAD_MSG = "话题名不能含换行等控制字符"
TOPIC_DISPLAY_TAKEN_MSG = "已经有叫「{name}」的话题"
# 不可见 / 能改变显示方向的字符：C1 控制符、零宽与方向标记、行分隔符、双向控制、BOM
_INVISIBLE = "\x80-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff"
_CONTROL_CHARS = re.compile(rf"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f{_INVISIBLE}]")  # 允许 \t \n \r（原话可以多行）
_ANY_CONTROL_CHARS = re.compile(rf"[\x00-\x1f\x7f{_INVISIBLE}]")  # 单行文字：连换行也不要
AUDIENCE_TOO_LONG_MSG = "观众描述最多 {max} 个字，现在有 {n} 个字"
MUST_LINES_TOO_LONG_MSG = "指定原话合计最多 {max} 个字，现在有 {n} 个字"
PRESET_BAD_PLATFORM_MSG = "预设「{preset}」的 platform 必须是文字"
SAVE_NOT_OBJECT_MSG = "预设「{preset}」的内容不是对象"


def _get_browse(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        return 200, payloads.browse(lookup(name), name)
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}


def _get_calibrate(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        cfg = schema.load(existing(name) / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.SchemaTooNew as exc:
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}
    return 200, {"calibration": style.normalize(cfg.get("calibration")),
                 "directive": style.directive(cfg.get("calibration"))}


def _get_confirm(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    name = q.get("project", [""])[0]
    try:
        return 200, payloads.confirm(lookup(name))
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}


def _get_analysis(q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict]:
    """M13 ②：分析进度。项目损坏（ProjectCorrupt / CorruptJSON）统一 409。"""
    name = q.get("project", [""])[0]
    try:
        pdir = existing(name)
        cfg = schema.read_json(pdir / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    job = jobs.project_job_detail(name, analysis.PREPARE_TASK)
    return 200, analysis.progress(analysis.facts(pdir, cfg, job))


GET_ROUTES = {
    "/api/analysis": _get_analysis,
    "/api/browse": _get_browse,
    "/api/calibrate": _get_calibrate,
    "/api/confirm": _get_confirm,
}


def handle_get(path: str, q: dict, lookup: Lookup, existing: Lookup) -> tuple[int, dict] | None:
    route = GET_ROUTES.get(path)
    return route(q, lookup, existing) if route else None


def check_calibration(raw: object) -> dict:
    """校验请求里的剪辑偏好，只返回给出的字段（None / 缺省 = 没给）；不合法抛 ValueError（人话）。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(CALIBRATION_NOT_OBJECT_MSG)
    given = {k: raw[k] for k in ("tone", "audience", "must_lines") if raw.get(k) is not None}  # null = 没给
    if "tone" in given and (not isinstance(given["tone"], str) or given["tone"] not in style.TONES):
        raise ValueError(BAD_TONE_MSG.format(allowed=" / ".join(style.TONES)))
    for field in ("audience", "must_lines"):
        value = given.get(field, "")
        pattern = _CONTROL_CHARS if field == "must_lines" else _ANY_CONTROL_CHARS
        if not isinstance(value, str) or pattern.search(value):
            raise ValueError(BAD_CALIBRATION_FIELD_MSG.format(field=field))
    if len(given.get("audience", "").strip()) > style.AUDIENCE_MAX:  # 不静默截断
        raise ValueError(AUDIENCE_TOO_LONG_MSG.format(max=style.AUDIENCE_MAX,
                                                      n=len(given["audience"].strip())))
    if len(given.get("must_lines", "").strip()) > style.MUST_LINES_MAX_CHARS:
        raise ValueError(MUST_LINES_TOO_LONG_MSG.format(max=style.MUST_LINES_MAX_CHARS,
                                                        n=len(given["must_lines"].strip())))
    lines = select_rules.parse_must_lines(given.get("must_lines"))
    if len(lines) > MUST_LINES_MAX:
        raise ValueError(MUST_LINES_TOO_MANY_MSG.format(n=len(lines)))
    return given


def new_project_args(raw: object) -> list[str]:
    """/api/new 的剪辑偏好 → aicut new 的参数。--x=value 形式：以 - 开头的值不会被 argparse 当成选项。"""
    given = check_calibration(raw)
    flags = {"tone": "--tone", "audience": "--audience", "must_lines": "--must-lines"}
    return [f"{flags[k]}={v}" for k, v in given.items()]


def _project_for_write(body: dict, existing: Lookup) -> tuple[int, dict] | tuple[Path, dict]:
    """写类接口公共前置：项目存在、读得懂、不是新版程序建的 → (pdir, cfg)；否则 (状态码, JSON)。"""
    try:
        pdir = existing(body.get("project", ""))
        return pdir, schema.load(pdir / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.SchemaTooNew as exc:
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}


def _post_project_settings(body: dict, existing: Lookup, presets: Path) -> tuple[int, dict]:
    """项目设置：片名 / 预设 / 剪辑偏好。不动 target_duration（KI-92：目标时长在 ⑤ 里改）。"""
    got = _project_for_write(body, existing)
    if isinstance(got[0], int):
        return got
    pdir, _ = got
    changes, platform = {}, None
    try:
        if "title" in body:
            title = body["title"]
            changes["title"] = schema.check_title(title.strip() if isinstance(title, str) else title)
        if "preset" in body:
            preset = body["preset"]
            if not isinstance(preset, str) or preset not in {f.stem for f in presets.glob("*.json")}:
                raise ValueError(UNKNOWN_PRESET_MSG.format(preset=preset))  # 白名单：不拼路径
            changes["preset"] = preset
            data = schema.read_json(presets / f"{preset}.json")  # 非对象 → CorruptJSON → 409
            platform = data.get("platform", "douyin")
            if platform is None:
                platform = "douyin"
            if not isinstance(platform, str):
                raise ValueError(PRESET_BAD_PLATFORM_MSG.format(preset=preset))
        given = check_calibration(body.get("calibration")) if "calibration" in body else None
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    if not changes and given is None:
        return 400, {"error": NOTHING_TO_CHANGE_MSG}

    def mutate(cur: dict) -> dict:
        out = {**cur, **changes, **({"platform": platform} if platform else {})}
        if given is not None:  # 只改给出的字段，其余沿用
            out["calibration"] = style.normalize({**(cur.get("calibration") or {}), **given})
        return out

    cfg = schema.update_project(pdir / "project.json", mutate)
    name = body["project"]
    return 200, {"ok": True, "project": cfg,
                 "wizard": wizard.derive(wizard.collect(pdir, cfg, name))}


def _post_topic_rename(body: dict, existing: Lookup) -> tuple[int, dict]:
    """P3：只改话题的显示名；选段 / 答案 / 规则仍按原名匹配。display 为空 = 恢复原名。"""
    try:
        pdir = existing(body.get("project", ""))
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    raw, display = body.get("name"), body.get("display")
    if not isinstance(raw, str) or not isinstance(display, str):
        return 400, {"error": TOPIC_ARGS_MSG}
    display = display.strip()
    if len(display) > topic_names.DISPLAY_MAX:
        return 400, {"error": TOPIC_DISPLAY_TOO_LONG_MSG.format(max=topic_names.DISPLAY_MAX)}
    if _ANY_CONTROL_CHARS.search(display):
        return 400, {"error": TOPIC_DISPLAY_BAD_MSG}
    work = pdir / "work"
    try:
        scored = schema.read_json(work / "segments_scored.json", default={})
        listed = scored.get("topics")
        raws = [t["name"] for t in (listed if isinstance(listed, list) else [])
                if isinstance(t, dict) and isinstance(t.get("name"), str)]
        if raw not in raws:
            return 400, {"error": TOPIC_NOT_FOUND_MSG.format(name=raw)}
        if display == raw:
            display = ""
        others = tuple(r for r in raws if r != raw)
        return 200, {"ok": True, "topic_names": topic_names.rename(work, raw, display,
                                                                   other_topics=others)}
    except topic_names.NameTaken:
        return 400, {"error": TOPIC_DISPLAY_TAKEN_MSG.format(name=display)}
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}


def _post_calibrate(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    try:
        pdir = existing(body.get("project", ""))
        schema.load(pdir / "project.json")
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except schema.SchemaTooNew as exc:
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}
    calibration = style.normalize(body.get("calibration") or {})
    schema.update_project(pdir / "project.json", lambda c: {**c, "calibration": calibration})
    return 200, {"ok": True, "directive": style.directive(calibration)}


def _post_confirm_answers(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    try:  # KI-05：「保存并确认」后服务端自动起重新选段任务
        return 200, confirm.save_answers(existing(body.get("project", "")),
                                         body.get("project", ""), body)
    except schema.CorruptJSON as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}


def _mark_target(body: dict, existing: Lookup, flag: str | None = None) -> tuple[int, dict] | Path:
    """标记类接口的公共前置：解析项目、校验 id（文本）与开关（真正的布尔）。"""
    try:
        pdir = existing(body.get("project", ""))
    except FileNotFoundError as exc:
        return 404, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    sid = body.get("id")
    if sid is None or sid == "":
        return 400, {"error": MISSING_ID_MSG}
    if not isinstance(sid, str) or (flag and not isinstance(body.get(flag), bool)):
        return 400, {"error": BAD_PARAM_MSG.format(flag=flag or "id")}
    return pdir


def _mark_response(pdir: Path, name: str, sid: str, cleared: str | None) -> dict:
    """标记成功后的统一响应：该段最新状态、剪辑列表合计、向导步骤（⑤ 可能变「需要更新」）。

    还没有分析结果（纯手工流程）时 segment / clip_list 为 None，只有 wizard。
    """
    work = pdir / "work"
    cfg = schema.read_json(pdir / "project.json", default={})
    scored = schema.read_json(work / "segments_scored.json", default=None)
    segment = clip = None
    if scored:
        segments = review.apply(schema.require_key(scored, "segments", work / "segments_scored.json"),
                                review.load(work))
        segment = next((s for s in segments if s["id"] == sid), None)
        clip = payloads.clip_list(segments, float(cfg.get("target_duration") or DEFAULT_TARGET_S))
    return {"ok": True, "cleared": cleared, "segment": segment, "clip_list": clip,
            "wizard": wizard.derive(wizard.collect(pdir, cfg, name))}


def _saved_response(pdir: Path, name: str, sid: str, cleared: str | None, **extra) -> dict:
    """写已经成功之后才拼响应：拼不出来（读文件失败等）也是 200 + warning，前端当已保存并重新读取。"""
    try:
        return {**_mark_response(pdir, name, sid, cleared), **extra}
    except Exception:  # noqa: BLE001 - 写已落盘，响应拼装失败不能让界面回滚
        LOG.exception("标记已保存，但拼响应失败：%s", sid)
        return {"ok": True, "cleared": cleared, "segment": None, "clip_list": None, "wizard": None,
                "warning": SAVED_BUT_STALE_MSG, **extra}


def _post_browse_mark(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    is_level = path.endswith("level")
    target = _mark_target(body, existing, None if is_level else "must")
    if isinstance(target, tuple):
        return target
    sid, work, cleared = body["id"], target / "work", None
    try:
        if is_level and "level" in body and body["level"] is None:  # 撤销人工档位（③ 的 Z）
            review.unset_level(work, sid)
        elif is_level:
            review.set_level(work, sid, int(body.get("level")))
        else:
            _, cleared = review.set_must_reporting(work, sid, body["must"])
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, TypeError, OSError) as exc:
        return 400, {"error": str(exc)}
    return 200, _saved_response(target, body["project"], sid, cleared)


def _remove_manual_shots(pdir: Path, marked: list) -> list[dict]:
    """D12：手动分镜表里与不可用片段重叠的镜头整镜移除；没有分镜表不新建。返回被移除的完整镜头。

    读-改-写在 shots_store.LOCK 内（与「保存分镜表」互斥）；真正移除之前先把原文件备份到 work/ 下。
    """
    shots_path = pdir / "shots.json"
    with shots_store.LOCK:
        if not shots_path.exists():
            return []
        raw = schema.read_json(shots_path)
        shots = schema.read_shots(shots_path)
        kept, dropped = exclusions.drop_overlapping(shots, marked)
        if not dropped:
            return []
        schema.write_json(pdir / "work" / SHOTS_BACKUP, raw)
        schema.write_json(shots_path, {**raw, "shots": kept})
        gone = set(dropped)
        return [sh for sh in shots if sh["id"] in gone]


def _backup_shots(pdir: Path) -> dict:
    """work/shots.before-unusable.json（最近一次 X 移除镜头前的分镜表）里的镜头 → {(id, 入, 出, 字幕): 镜头}。
    没有 / 读不懂 → 空：撤销只信这份备份，不信客户端发来的内容。"""
    try:
        data = schema.read_json(pdir / "work" / SHOTS_BACKUP, default=None)
        shots = schema.clean_shots(data.get("shots")) if isinstance(data, dict) else []
    except (schema.CorruptJSON, ValueError, OSError):
        return {}
    return {(s["id"], s["in"], s["out"], s["sub"]): s for s in shots}


def _restore_manual_shots(pdir: Path, clean: list[dict]) -> tuple[int, int]:
    """撤销「不可用」时把当时被移除的镜头放回手动分镜表。

    只放回备份里确有其镜（id、入出点、字幕都一致）且现在不在表里的；合并后总数不得超过 schema.SHOTS_MAX；
    其余都算没放回。按入点插回原来的位置。没有手动分镜表就不新建（用户可能已「恢复为 AI 选段」）；表读不懂抛 CorruptJSON。
    → (放回几镜, 没放回几镜)
    """
    path = pdir / "shots.json"
    with shots_store.LOCK:  # 与「保存分镜表」「标记不可用」互斥
        if not path.exists() or not clean:
            return 0, len(clean)
        raw = schema.read_json(path)
        shots = schema.read_shots(path)
        trusted, have = _backup_shots(pdir), {s["id"] for s in shots}
        added = []
        for s in clean:
            ok = (s["id"], s["in"], s["out"], s["sub"]) in trusted and s["id"] not in have \
                and len(shots) + len(added) < schema.SHOTS_MAX
            if ok:
                added.append(trusted[(s["id"], s["in"], s["out"], s["sub"])])
                have.add(s["id"])
        for shot in sorted(added, key=lambda s: (s["in"], s["out"])):
            at = next((i for i, cur in enumerate(shots) if cur["in"] > shot["in"]), len(shots))
            shots = [*shots[:at], shot, *shots[at:]]
        if added:
            schema.write_json(path, {**raw, "shots": shots})
        return len(added), len(clean) - len(added)


def _clean_restore(raw: object) -> list[dict]:
    """校验请求里要放回的镜头（与 /api/shots 同一套：id 合法唯一、入出点有限非负且出晚于入）；不合法抛 ValueError。"""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > RESTORE_SHOTS_MAX:
        raise ValueError(BAD_RESTORE_MSG.format(max=RESTORE_SHOTS_MAX))
    return schema.clean_shots(raw)


def _post_browse_unusable(path: str, body: dict, existing: Lookup) -> tuple[int, dict]:
    """KI-93：标 / 取消「不可用」；标记时顺带移出剪辑列表、移除手动分镜表里重叠的镜头。

    取消时可带 restore_shots（撤销 X：把当时移除的镜头放回）。先把会失败的读与校验全做完，再写 overrides：
    失败时不留半截状态；写成功之后拼响应失败也回 200（_saved_response）。
    """
    target = _mark_target(body, existing, "unusable")
    if isinstance(target, tuple):
        return target
    pdir, sid, work, flag = target, body["id"], target / "work", body["unusable"]
    try:
        scored = schema.read_json(work / "segments_scored.json", default=None)
        known = {s.get("id") for s in (scored or {}).get("segments", []) if isinstance(s, dict)}
        if sid not in known:
            return 400, {"error": UNKNOWN_SEGMENT_MSG.format(id=sid)}
        schema.require_key(scored, "segments", work / "segments_scored.json")
        restore = [] if flag else _clean_restore(body.get("restore_shots"))
        if (flag or restore) and (pdir / "shots.json").exists():
            schema.read_shots(pdir / "shots.json")  # 手动分镜表读不懂就别动 overrides
        _, cleared = review.set_unusable(work, sid, flag)
        removed = _remove_manual_shots(pdir, exclusions.spans(work)) if flag else []
        restored, skipped = _restore_manual_shots(pdir, restore) if restore else (0, 0)
    except (review.OverridesCorrupt, schema.CorruptJSON) as exc:  # 必须在 ValueError 之前
        return 409, {"error": str(exc)}
    except (ValueError, OSError) as exc:
        return 400, {"error": str(exc)}
    extra = {"removed_shots": removed, "restored": restored, "not_restored": skipped}
    return 200, _saved_response(pdir, body["project"], sid, cleared, **extra)


POST_ROUTES = {
    "/api/calibrate": _post_calibrate,
    "/api/confirm/answers": _post_confirm_answers,
    "/api/browse/level": _post_browse_mark,
    "/api/browse/must": _post_browse_mark,
    "/api/browse/unusable": _post_browse_unusable,
}


def handle_post(path: str, body: dict, existing: Lookup,
                presets: Path | None = None) -> tuple[int, dict] | None:
    """presets：预设目录（项目设置要校验预设并取平台）；由 server 在调用时传入，测试可打桩 server.PRESETS。"""
    if path == "/api/project/settings" and presets is not None:
        return _post_project_settings(body, existing, presets)
    if path == "/api/topics/rename":
        return _post_topic_rename(body, existing)
    route = POST_ROUTES.get(path)
    return route(path, body, existing) if route else None
