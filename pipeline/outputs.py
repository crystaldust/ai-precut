# -*- coding: utf-8 -*-
"""出片产物（M14）：预览片暂存、晋升为版本、每版导出记录、Windows 剪映包。

预览片先渲染到 output/preview/（不是版本，E1）；导出时把同一份时间线与预览片用硬链接「晋升」为
output/vN（E4，FR-8：预览与最终剪映工程是同一份 timeline），再装 Mac 草稿或打 Windows 包。
输出函数由调用方注入，本模块不 import aicut。
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pipeline import exclusions, export_draft, fingerprints, media_io, project_lock, schema, shots_store

PACKAGING = "生成草稿并打包（媒体要拷一遍，几分钟）…"
PREVIEW_DIR = "preview"                     # output/preview：当前分镜表的预览片暂存（不是版本）
STAMP_FILE = "preview.json"                 # {inputs, shots, duration, at}
EXPORT_FILE = "export.json"                 # {mac: {draft, at} | null, windows: {zip, at} | null}
PREVIEW_FILE = "preview.mp4"
PROMOTED = ("timeline.json", "shots_snapshot.json", PREVIEW_FILE, ".timeline.sha", STAMP_FILE)
EXPORT_KINDS = ("mac", "windows")
PREVIEW_STALE = "分镜表在生成预览片之后改过了：先在「⑤ 看结果」重新生成预览片，再导出"
PREVIEW_NONE = "还没有当前分镜表的预览片：先在「⑤ 看结果」生成预览片"
ALREADY_IN_JIANYING = "这一版已经在 Mac 剪映里：{draft}"  # 剪映不允许同名草稿（KI-59）
MANUAL_REPLACED = "已用新的 AI 选段覆盖手动分镜表，原表备份在 work/shots_backups/{path}"
MANUAL_BUSY = "选段已更新，但分镜表正忙，没能覆盖手动分镜表（你的修改还在）；请稍后再选一次"
MANUAL_BACKUP_FAILED = "手动分镜表备份失败（{exc}），没有覆盖它（你的修改还在）；选段本身已更新"
BAD_TARGET = "导出目标只能是 mac 或 windows"
NEED_TARGET = "缺少导出目标：mac 或 windows"
BAD_EXPORT_KIND = "导出类型只能是 mac 或 windows：{kind}"
ZIP_TITLE_MAX_CHARS = 60     # 片名在 zip 文件名里最多保留的字数（中文 3 字节/字，远低于 255 字节）
# 路径字符、控制字符，以及能把文件名显示成别的样子的零宽 / 双向控制字符
UNSAFE_FILENAME = re.compile(
    r'[\\/:*?"<>|\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]')


class PackageFailed(Exception):
    """Windows 包打不出来；消息直接给用户看。"""


def package_windows(timeline: Path, name: str, out: Path, *, info: Callable[[str], None],
                    warn: Callable[[str], None]) -> dict:
    """时间线 → Windows 可双击导入的剪映包；子进程成功时的警告逐条转给 warn（KI-18）。"""
    info(PACKAGING)
    try:
        res = export_draft.build_windows_package(timeline, name, out)
    except (RuntimeError, FileNotFoundError) as exc:
        raise PackageFailed(str(exc)) from exc
    for w in res.get("warnings", []):
        warn(w)
    return res


class PreviewMissing(Exception):
    """暂存里没有一份完整的预览片，不能晋升。"""


class PreviewStale(Exception):
    """暂存的预览片不是调用方要的那一份（被别的预览换掉了），不能晋升。"""


VERSION_NAME = re.compile(r"v(\d+)")
STAGING_TMP_GLOB = ".v*.tmp"          # output/.vN.tmp：晋升时的组装目录，崩溃后可能残留
LEFTOVER_FILE_GLOB = "*.promote.tmp"  # 旧写法残留的单文件临时名
ZIP_GLOB = "*_Windows.zip"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def staging_dir(pdir: Path) -> Path:
    return Path(pdir) / "output" / PREVIEW_DIR


def write_stamp(d: Path, inputs: dict, shots: int, duration: float) -> None:
    """预览片戳：必须在预览片落盘之后写（失败时旧戳保持）。"""
    schema.write_json(Path(d) / STAMP_FILE,
                      {"inputs": inputs, "shots": shots, "duration": duration, "at": _now()})


def read_stamp(d: Path) -> dict | None:
    """读不出 / 形状不对 → None（当作没有戳）。"""
    try:
        data = schema.read_json(Path(d) / STAMP_FILE, default=None)
    except schema.CorruptJSON:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("inputs"), dict) else None


def preview_state(pdir: Path, cfg: dict, now: dict | None = None) -> dict:
    """暂存预览片相对「当前分镜表」的状态：none / fresh / outdated（outdated 带变了的分项名）。

    只读：不用 complete_or_adopt（状态判定不能写盘）。now：调用方已算好的 preview_inputs。
    """
    d = staging_dir(pdir)
    stamp = read_stamp(d)
    now = now if now is not None else fingerprints.preview_inputs(pdir, cfg)
    meta = {"at": None, "duration": None, "shots": None}
    if stamp is None or not media_io.is_complete(d / PREVIEW_FILE) or not now["table"]:
        return {"status": "none", "reasons": [], **meta}
    meta = {"at": stamp.get("at"), "duration": stamp.get("duration"), "shots": stamp.get("shots")}
    reasons = fingerprints.changed(stamp["inputs"], now)
    if stamp["inputs"] == now:
        return {"status": "fresh", "reasons": [], **meta}
    return {"status": "outdated", "reasons": reasons, **meta}


def version_dirs(pdir: Path) -> list[Path]:
    """已完成的版本目录 output/v<数字>（按版本号升序）：忽略点开头的临时目录、暂存目录和还没有时间线的残目录。"""
    found = [(int(m.group(1)), d) for d in (Path(pdir) / "output").glob("v*")
             if d.is_dir() and (m := VERSION_NAME.fullmatch(d.name)) and (d / "timeline.json").is_file()]
    return [d for _, d in sorted(found)]


def next_version(pdir: Path) -> str:
    """下一个版本号。残目录（没有时间线）也占着号：绝不覆盖它。"""
    nums = [int(m.group(1)) for d in (Path(pdir) / "output").glob("v*")
            if d.is_dir() and (m := VERSION_NAME.fullmatch(d.name))]
    return f"v{max(nums, default=0) + 1}"


def _link_or_copy(src: Path, dst: Path) -> None:
    """大文件（预览片）硬链接，失败退回复制；其余小文件一律复制。

    小文件（.timeline.sha、预览戳、时间线等）会被暂存目录原地改写，共用 inode 会连已晋升的版本一起改掉。
    """
    if src.name == PREVIEW_FILE:
        try:
            os.link(src, dst)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def clean_leftovers(output_dir: Path) -> None:
    """清掉上次崩溃留下的组装目录 .vN.tmp 与单文件临时名（调用方已持 build_section）。"""
    out = Path(output_dir)
    for d in out.glob(STAGING_TMP_GLOB):
        shutil.rmtree(d, ignore_errors=True)
    for f in out.glob(f"v*/{LEFTOVER_FILE_GLOB}"):
        f.unlink(missing_ok=True)


def _empty_exports() -> dict:
    return {k: None for k in EXPORT_KINDS}


def promote(staging: Path, vdir: Path, *, expect_inputs: dict | None = None) -> dict:
    """把暂存的预览片（6 个文件：5 个产物 + 预览片完成标记）原子地放进版本目录；调用方已持 build_section。

    先在 output/.vN.tmp 里组装齐（含 export.json），新版本再整体改名为 vN，崩溃不会留下半个 vN。
    覆盖已有版本：同一张表（预览戳一致）→ 什么都不动、保留导出记录（⚑Q1）；内容不同 → 先重置 export.json、
    删掉旧的 Windows 包，再逐个换文件。expect_inputs：调用方认定的预览戳，不一致 → PreviewStale。
    返回 {"replaced": 是否覆盖了内容不同的旧版本, "old_mac": 被覆盖的旧版本记录过的剪映草稿名或 None}。
    """
    staging, vdir = Path(staging), Path(vdir)
    names = [*PROMOTED, media_io.done_marker(staging / PREVIEW_FILE).name]
    if not media_io.is_complete(staging / PREVIEW_FILE) or any(not (staging / n).is_file() for n in names):
        raise PreviewMissing(PREVIEW_NONE)
    stamp = read_stamp(staging)
    if expect_inputs is not None and (stamp is None or stamp["inputs"] != expect_inputs):
        raise PreviewStale(PREVIEW_STALE)
    clean_leftovers(vdir.parent)
    tmp = vdir.parent / f".{vdir.name}.tmp"
    tmp.mkdir(parents=True)
    try:
        for name in names:
            _link_or_copy(staging / name, tmp / name)
        schema.write_json(tmp / EXPORT_FILE, _empty_exports())
        if not vdir.exists():
            schema.rename_no_overwrite(tmp, vdir)
            schema.fsync_dir(vdir.parent)
            return {"replaced": False, "old_mac": None}
        return _replace_into(tmp, vdir, names, stamp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _replace_into(tmp: Path, vdir: Path, names: list[str], stamp: dict | None) -> dict:
    old_stamp, exports = read_stamp(vdir), read_exports(vdir)
    if old_stamp and stamp and old_stamp["inputs"] == stamp["inputs"] and all((vdir / n).is_file() for n in names):
        if exports is None:  # 改版前的版本：补一份记录
            schema.write_json(vdir / EXPORT_FILE, _empty_exports())
        return {"replaced": False, "old_mac": None}
    mac = (exports or {}).get("mac")
    schema.write_json(vdir / EXPORT_FILE, _empty_exports())  # 先重置：中途失败也不会把旧导出记录挂在新内容上
    for old_zip in vdir.glob(ZIP_GLOB):
        old_zip.unlink(missing_ok=True)
    for name in names:
        schema.atomic_replace(tmp / name, vdir / name)
    return {"replaced": True, "old_mac": mac.get("draft") if mac else None}


def read_exports(vdir: Path) -> dict | None:
    """这一版真正导出过什么；没有 export.json（改版前生成）或读不出 → None（= legacy）。"""
    try:
        data = schema.read_json(Path(vdir) / EXPORT_FILE, default=None)
    except schema.CorruptJSON:
        return None
    if not isinstance(data, dict):
        return None
    return {kind: data.get(kind) if isinstance(data.get(kind), dict) else None for kind in EXPORT_KINDS}


def mark_export(vdir: Path, kind: str, **info: object) -> None:
    """读改写 export.json（原子写）；装草稿 / 打包成功之后才调用。"""
    if kind not in EXPORT_KINDS:
        raise ValueError(BAD_EXPORT_KIND.format(kind=kind))
    vdir = Path(vdir)
    with project_lock.build_section(vdir.parent.parent):  # 读改写在出片锁内，并发的导出不互相覆盖；调用方不得已持有它
        cur = read_exports(vdir) or _empty_exports()
        schema.write_json(vdir / EXPORT_FILE, {**cur, kind: {**info, "at": _now()}})


def matching_version(pdir: Path, inputs: dict) -> str | None:
    """最大的 vN 使 vN/preview.json 的输入指纹等于 inputs；没有 → None（⚑Q1：同一张表补另一种导出物）。"""
    for d in reversed(version_dirs(pdir)):
        stamp = read_stamp(d)
        if stamp is not None and stamp["inputs"] == inputs:
            return d.name
    return None


def windows_zip(pdir: Path, version: str, title: str | None) -> Path:
    """<项目>/output/vN/<片名>_vN_Windows.zip；片名里的路径字符一律换成 _。"""
    raw = title if isinstance(title, str) and title.strip() else Path(pdir).name
    name = UNSAFE_FILENAME.sub("_", raw).lstrip(".-")[:ZIP_TITLE_MAX_CHARS] or Path(pdir).name
    return Path(pdir) / "output" / version / f"{name}_{version}_Windows.zip"


def replace_manual(pdir: Path) -> Path | None:
    """`select --manual=replace`：选段成功之后，在分镜表锁内备份并删除手动分镜表与基线；没有手动表 → None。"""
    with shots_store.locked(pdir):
        return shots_store.drop_manual(pdir, "replace")


def build_args(pdir: Path, body: dict, cfg: dict) -> list[str]:
    """界面的「导出」请求 → `aicut build` 的参数（调用方已过白名单以外的校验）。

    target（mac | windows）必填：只晋升当前分镜表的预览片（--require-preview）；
    已有一版就是这张表（⚑Q1）就往这一版里补另一种导出物。命令行 `aicut build` 不走这里。
    """
    target = body.get("target")
    if target is None:
        raise ValueError(NEED_TARGET)
    if target not in EXPORT_KINDS:
        raise ValueError(BAD_TARGET)
    status = preview_state(pdir, cfg)["status"]
    if status != "fresh":
        raise ValueError(PREVIEW_STALE if status == "outdated" else PREVIEW_NONE)
    extra = ["--require-preview"]
    if version := matching_version(pdir, fingerprints.preview_inputs(pdir, cfg)):
        mac = (read_exports(Path(pdir) / "output" / version) or {}).get("mac")
        if target == "mac" and mac:
            raise ValueError(ALREADY_IN_JIANYING.format(draft=mac.get("draft", version)))
        extra += ["--version", version]
    return [*extra, *(["--windows", "--no-draft"] if target == "windows" else [])]


def version_facts(vdir: Path) -> tuple[int, float]:
    """版本卡片 / 对比用：(镜头数, 总时长秒)，从时间线读；读不出当作空（只用于显示）。"""
    tl = schema.read_json_lenient(Path(vdir) / "timeline.json", {})
    video = tl.get("video") if isinstance(tl, dict) else None
    if not isinstance(video, list) or not video:
        return 0, 0.0
    try:
        total = max(s["timeline_in"] + s["out"] - s["in"] for s in video)
    except (KeyError, TypeError):
        return len(video), 0.0
    return len(video), round(total, 1)


def export_block(pdir: Path, version: str, marked: list | None = None) -> tuple[int | None, str | None]:
    """这一版能不能生成 / 定位 Windows 包（KI-100，⚑Q3）→ (含不可用片段的镜头数 | None, 拦截原因 | None)。

    没有任何不可用标记时不读快照（/api/state 每次轮询都会问）；有标记而无法确认（快照缺失 / 损坏）→ (None, 原因)。
    marked：调用方已读好的不可用片段（exclusions.spans），省得每个版本重读一遍分析结果。
    """
    try:
        hits = exclusions.timeline_hits(Path(pdir) / "work", Path(pdir) / "output" / version, marked)
    except exclusions.ExclusionError as exc:
        return None, str(exc)
    return hits, (exclusions.EXPORT_BLOCKED.format(n=hits) if hits else None)
