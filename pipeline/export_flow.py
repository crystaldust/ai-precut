# -*- coding: utf-8 -*-
"""出片流程（M14 E4）：预览片暂存 → 晋升为 vN → 装 Mac 草稿 / 打 Windows 包（从 aicut.py 拆出）。

`ops` 是 aicut 模块本身：die / info / warn / ok、ensure_clips、compose_timeline、ensure_preview、
install_draft、cmd_export 等都在运行时从它上面取，所以测试对 aicut.<名> 的打桩照样生效，本模块不 import aicut。
暂存目录里的一切（切片 → 时间线 → 预览片 → 戳 → 晋升）都在同一把 build_section 内完成：
并发的预览 / 导出不会在中间换掉暂存里的文件。
"""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

from pipeline import (applog, build_documentary, clips, diskspace, exclusions, fingerprints, outputs,
                      plat, project_lock, review, schema, select)

TABLE_CHANGED_MSG = "分镜表在读取时被修改了，没有生成预览片；请重新点「生成预览片」"
OVERWRITE_WARN = "{version} 已用新内容覆盖：剪映里的「{draft}」是旧内容，不会随之更新"
OVERWRITE_REFUSED = ("{version} 的内容已经变了，不能再往剪映里装同名草稿「{draft}」（剪映不允许同名草稿）；"
                     "请生成新版本再导出到 Mac 剪映")
OVERWRITE_REFUSED_WIN = OVERWRITE_REFUSED.replace("Mac 剪映", "Windows 剪映")
DRAFT_RECORD_FAILED = "草稿已经装进剪映（{draft}），但记录导出信息失败：{exc}。请不要重复导出，到剪映里确认这份草稿即可"
WINDOWS_RECORD_FAILED = "Windows 包已生成（{zip}），但记录导出信息失败：{exc}"
RECORD_ERRORS = (OSError, ValueError, project_lock.Busy)  # ValueError 含 CorruptJSON


def overwrite_refused(version: str, draft: str) -> str:
    return (OVERWRITE_REFUSED_WIN if plat.IS_WIN else OVERWRITE_REFUSED).format(version=version, draft=draft)


def current_shots(ops: Any, pdir: Path) -> list[dict]:
    """取当前分镜表（手动优先，否则覆盖式选段）并过出片护栏：必留段齐全（GL-25）、剔除含不可用片段的镜头（KI-93）。"""
    shots_file = pdir / "shots.json"
    if not shots_file.exists():  # 用覆盖式选段的结果直接出片
        selected = pdir / "work/shots-selected.json"
        if selected.exists():
            shots_file = selected
            ops.info("使用覆盖式选段结果：work/shots-selected.json")
    if not shots_file.exists():
        ops.die(f"缺少分镜表 {shots_file}（先跑 brief，再写 shots.json）")
    shots = schema.read_shots(shots_file)  # KI-48：损坏 / 缺键 / 入出点不对 → CorruptJSON，切片前由 main() 报
    try:  # GL-25：切片（耗时）之前确认分镜表覆盖全部必留段
        missing = select.missing_must_keep(pdir / "work", shots)
    except review.OverridesCorrupt as exc:
        ops.die(str(exc))
    if missing:
        ops.die(select.describe_missing(missing, from_selection=shots_file != pdir / "shots.json"))
    try:  # KI-93：手动 / 旧分镜表里含「不可用」片段的镜头出片前再剔一次
        shots, dropped = exclusions.filter_shots(pdir / "work", shots)
    except exclusions.ExclusionError as exc:
        ops.die(str(exc))
    if dropped:
        ops.warn(exclusions.DROPPED_WARNING.format(n=len(dropped), ids="、".join(dropped[:exclusions.DROPPED_SHOWN])))
        if not shots:
            ops.die(exclusions.ALL_DROPPED)
    return shots


def stage(ops: Any, pdir: Path, c: dict, preset: dict, shots: list[dict]) -> tuple[Path, float]:
    """切片 → 时间线 → 快照 → 预览片，写进暂存目录 output/preview（不是版本，E1）；调用方已持 build_section。"""
    if low := diskspace.shortfall(pdir, ops.build_need(pdir, c, shots, outputs.PREVIEW_DIR)):
        ops.die(low)  # KI-33：切片 / 预览之前确认磁盘够（只算要写的，M5）
    staging = outputs.staging_dir(pdir)
    with applog.stage(pdir / "work", "clips"):
        clip_paths = ops.ensure_clips(pdir, c, shots)
    staging.mkdir(parents=True, exist_ok=True)
    durations = ops.actual_durations(clip_paths, shots)
    tl = ops.compose_timeline(c, preset, shots, clip_paths, durations)
    schema.write_json(staging / "timeline.json", schema.stamp(tl))  # KI-37；指纹仍按未打标的时间线算
    clips.save_snapshot(staging, shots)  # 清理缓存后导出这一版时按它补切（审查修复 H2）
    clips.prune_unreferenced(pdir)  # KI-89：带键切片只留仍被某一版（含暂存）引用的
    tl_hash = build_documentary.preview_fingerprint(tl, shots, Path(c["material"]))  # KI-11
    total = sum(durations.values())
    ops.ok(f"时间线：{len(shots)} 镜，{int(total // 60)}:{total % 60:05.2f}")
    with applog.stage(pdir / "work", "preview"):
        ops.ok(f"预览片：{ops.ensure_preview(staging, tl_hash)}")
    return staging, total


def _preview_locked(ops: Any, pdir: Path, c: dict, preset: dict) -> dict:
    """生成预览片并写戳；返回戳里的输入指纹。调用方已持 build_section。"""
    inputs = fingerprints.preview_inputs(pdir, c)  # 开始时取指纹，成功后才写戳（E2）
    shots = current_shots(ops, pdir)
    if fingerprints.preview_inputs(pdir, c) != inputs:  # 读表的同时有人在改：戳就不能证明渲染的是哪一张表
        ops.die(TABLE_CHANGED_MSG)
    staging, total = stage(ops, pdir, c, preset, shots)
    outputs.write_stamp(staging, inputs, len(shots), round(total, 3))
    ops.ok(f"预览片已生成（不产生版本）：{staging / 'preview.mp4'}")
    return inputs


def preview(ops: Any, pdir: Path, c: dict) -> None:
    """aicut preview：整个暂存过程在 build_section 内（串行化对暂存目录的写）。"""
    preset = ops.load_preset(c["preset"])
    with project_lock.build_section(pdir):
        _preview_locked(ops, pdir, c, preset)


def _require_fresh(ops: Any, pdir: Path, c: dict) -> dict:
    """--require-preview：只晋升用户看过的那一份；暂存不是当前分镜表的就停。返回暂存戳的输入指纹。"""
    status = outputs.preview_state(pdir, c)["status"]
    if status != "fresh":
        ops.die(outputs.PREVIEW_STALE if status == "outdated" else outputs.PREVIEW_NONE)
    current_shots(ops, pdir)  # 必留标记等不在预览指纹里：晋升前再过一遍护栏，不切片
    return outputs.read_stamp(outputs.staging_dir(pdir))["inputs"]


def install_once(ops: Any, vdir: Path, draft_name: str) -> None:
    """这一版已经在 Mac 剪映里就不重装（剪映不允许同名草稿，KI-59）；装成功才记 export.json。"""
    if (outputs.read_exports(vdir) or {}).get("mac"):
        ops.info(outputs.already_in_jianying(draft_name))
        return
    with applog.stage(vdir.parent.parent / "work", "draft"):
        ops.install_draft(vdir, draft_name)
    try:
        outputs.mark_export(vdir, "mac", draft=draft_name)
    except RECORD_ERRORS as exc:
        ops.die(DRAFT_RECORD_FAILED.format(draft=draft_name, exc=exc))


def _package_windows(ops: Any, args: Namespace, pdir: Path, c: dict, version: str, vdir: Path) -> None:
    zip_path = outputs.windows_zip(pdir, version, c.get("title"))
    ops.cmd_export(Namespace(name=args.name, timeline=str(vdir / "timeline.json"),
                             package_name=zip_path.stem, out=str(zip_path.parent)))
    try:
        outputs.mark_export(vdir, "windows", zip=zip_path.name)
    except RECORD_ERRORS as exc:
        ops.die(WINDOWS_RECORD_FAILED.format(zip=zip_path.name, exc=exc))


def build(ops: Any, pdir: Path, c: dict, args: Namespace) -> None:
    """出片 = 暂存预览片（必要时重做）→ 晋升为 vN → 装 Mac 草稿 / 打 Windows 包。"""
    if args.version:
        ops.check_or_die(schema.check_version, args.version)
    require = getattr(args, "require_preview", False)
    preset = None if require else ops.load_preset(c["preset"])
    with project_lock.build_section(pdir):  # 新鲜度检查（或重新暂存）、选版本号、晋升同在一把锁内
        expect = _require_fresh(ops, pdir, c) if require else _preview_locked(ops, pdir, c, preset)
        version = args.version or ops.next_version(pdir)
        vdir = pdir / "output" / version
        try:
            res = outputs.promote(outputs.staging_dir(pdir), vdir, expect_inputs=expect)
            clips.prune_unreferenced(pdir)  # 覆盖已有版本（--version）后，旧时间线引用的切片可以清了（KI-89）
        except (outputs.PreviewMissing, outputs.PreviewStale, OSError) as exc:
            ops.die(str(exc))
    draft = f"{c['title']}_{version}"
    if res["old_mac"]:
        ops.warn(OVERWRITE_WARN.format(version=version, draft=res["old_mac"]))
        if not args.no_draft:
            ops.die(overwrite_refused(version, res["old_mac"]))
    if not args.no_draft:
        install_once(ops, vdir, draft)
    if getattr(args, "windows", False):
        _package_windows(ops, args, pdir, c, version, vdir)
    ops.ok(f"完成 → {vdir}")
