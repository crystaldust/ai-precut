# -*- coding: utf-8 -*-
"""媒体产物的「临时文件 → 原子改名 → 完成标记」（GL-15）。

规则：ffmpeg 永远写到同目录、同扩展名的临时文件，成功后 os.replace 到最终路径，
再写 `<文件名>.done`；判断"已完成"只认标记且大小一致，不认 exists()。
编码参数由调用方给（GL-04：见 pipeline/encode.py，统一 h264_videotoolbox），本模块不关心。
"""
from __future__ import annotations

import contextlib
import glob
import json
import math
import os
import subprocess
import uuid
from pathlib import Path
from typing import Iterator

from pipeline import schema

PARTIAL_TAG = ".partial-"
DONE_SUFFIX = ".done"
STDERR_TAIL = 800       # 失败时带回的 ffmpeg stderr 末尾字符数
FFMPEG_BASE = ["ffmpeg", "-y", "-loglevel", "error"]
ANALYSIS_BASE = ["ffmpeg", "-hide_banner", "-nostats"]  # 分析滤镜的结果在 info 级日志里，不能加 -loglevel error
FFPROBE_MATERIAL = ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate",
                    "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,duration",
                    "-of", "json"]
MATERIAL_UNREADABLE = "ffprobe 认不出这个文件（{detail}）：确认它是完整的视频文件、没有损坏、不是还在拷贝中"
DURATION_UNREADABLE = "读不到时长：{name}（{detail}）"
NO_CONTAINER_DURATION = ("{name}：容器里没有时长信息（常见于录制中断或管道写出的文件），"
                         "素材台账时长记为 0；文件本身可以读，后续步骤照常进行")
CACHE_RESET = "[!] 切片缓存记录损坏，按空缓存处理，全部镜头重新切：{reason}"


class MediaError(RuntimeError):
    """ffmpeg 产物生成失败（临时文件已清理）。"""


def done_marker(dst: Path) -> Path:
    dst = Path(dst)
    return dst.with_name(dst.name + DONE_SUFFIX)


def is_complete(dst: Path) -> bool:
    """产物存在、有完成标记且大小与标记一致才算完成；旧版本留下的无标记文件不算。"""
    dst = Path(dst)
    marker = done_marker(dst)
    if not dst.is_file() or not marker.is_file():
        return False
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(meta, dict) and meta.get("size") == dst.stat().st_size


def _partial_path(dst: Path) -> Path:
    # 保留原扩展名：ffmpeg 按输出扩展名推断封装格式
    return dst.with_name(f".{dst.stem}{PARTIAL_TAG}{uuid.uuid4().hex[:8]}{dst.suffix}")


def _clear_stale_partials(dst: Path) -> None:
    """清掉上次被强杀留下的临时文件（文件名可能含 glob 元字符，必须转义）。"""
    pattern = f".{glob.escape(dst.stem)}{PARTIAL_TAG}*{glob.escape(dst.suffix)}"
    for p in dst.parent.glob(pattern):
        p.unlink(missing_ok=True)


def _write_marker(dst: Path) -> None:
    marker = done_marker(dst)
    tmp = marker.with_name(f".{marker.name}.{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(json.dumps({"size": dst.stat().st_size}), encoding="utf-8")
        os.replace(tmp, marker)
    finally:
        tmp.unlink(missing_ok=True)


@contextlib.contextmanager
def atomic_output(dst: Path, *, mark: bool = True) -> Iterator[Path]:
    """yield 一个临时路径；块正常结束才改名到 dst 并写完成标记，任何异常（含中断）都不留半成品。

    mark=False：只做原子改名、不写标记（例如 dst 本身就是调用方 atomic_output 给的临时路径）。
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mark:
        done_marker(dst).unlink(missing_ok=True)  # 决定重做就先作废旧结果
    _clear_stale_partials(dst)
    tmp = _partial_path(dst)
    try:
        yield tmp
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise MediaError(f"没有产出有效文件：{dst.name}")
        os.replace(tmp, dst)
        if mark:
            _write_marker(dst)
    finally:
        tmp.unlink(missing_ok=True)


def _tail(text: str | None) -> str:
    return (text or "").strip()[-STDERR_TAIL:]


def run_ffmpeg(args: list[str], *, runner=subprocess.run) -> None:
    """ffmpeg <args>；非零退出抛 MediaError 并带上 stderr 末尾。"""
    try:
        r = runner([*FFMPEG_BASE, *args], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError as exc:  # 没装 ffmpeg / 不可执行
        raise MediaError(f"无法运行 ffmpeg：{exc}") from exc
    if r.returncode != 0:
        raise MediaError(f"ffmpeg 失败（退出码 {r.returncode}）：{_tail(r.stderr)}")


def run_analysis(args: list[str], *, runner=subprocess.run, timeout: float | None = None) -> str:
    """ffmpeg 分析（blackdetect / scdet 等，输出到 null）；返回 stderr 日志。失败抛 MediaError（KI-19）。"""
    try:
        r = runner([*ANALYSIS_BASE, *args], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=timeout)
    except OSError as exc:
        raise MediaError(f"无法运行 ffmpeg：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg 超过 {exc.timeout:.0f} 秒没有结束") from exc
    if r.returncode != 0:
        raise MediaError(f"ffmpeg 失败（退出码 {r.returncode}）：{_tail(r.stderr)}")
    return r.stderr or ""


def ffmpeg_to(dst: Path, args: list[str], *, runner=subprocess.run) -> Path:
    """ffmpeg <args> <临时文件> → 原子落到 dst。args 不含 `ffmpeg -y -loglevel` 与输出路径。"""
    with atomic_output(dst) as tmp:
        run_ffmpeg([*args, str(tmp)], runner=runner)
    return Path(dst)


FFPROBE_DURATION = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "csv=p=0"]


def _probe_duration(path: Path, runner) -> float:
    try:
        r = runner([*FFPROBE_DURATION, str(path)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError:
        return 0.0
    if r.returncode != 0:
        return 0.0
    try:
        return float((r.stdout or "").strip())
    except ValueError:
        return 0.0


def duration_or_zero(path: Path, *, runner=subprocess.run) -> float:
    """宽松版：读不出时长给 0.0（调用方自有兜底，例如切片按请求时长）。"""
    return _probe_duration(path, runner)


def _positive_seconds(raw) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _run_probe(cmd: list[str], runner) -> tuple[int, str, str]:
    """跑 ffprobe → (退出码, stdout, stderr)；跑不起来抛 OSError 由调用方转人话。"""
    r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout or "", r.stderr or ""


def probe_duration(path: Path, *, runner=subprocess.run) -> float:
    """严格版：读不出正时长抛 MediaError（带 ffprobe 原因，KI-19）。认领旧产物仍用宽松的 _probe_duration。"""
    name = Path(path).name
    try:
        code, out, err = _run_probe([*FFPROBE_DURATION, str(path)], runner)
    except OSError as exc:
        raise MediaError(DURATION_UNREADABLE.format(name=name, detail=f"无法运行 ffprobe：{exc}")) from exc
    if code != 0:
        raise MediaError(DURATION_UNREADABLE.format(name=name, detail=_tail(err) or f"退出码 {code}"))
    value = _positive_seconds(out.strip())
    if value is None:
        raise MediaError(DURATION_UNREADABLE.format(name=name, detail=f"ffprobe 给出 {out.strip()[:40]!r}"))
    return value


def probe_material(path: Path, *, runner=subprocess.run) -> dict:
    """素材台账用（KI-66）：→ {"duration": 秒, "streams": [...], "warnings": [...]}。

    ffprobe 读不了（非零 / 没输出 / 没有容器信息）才抛 MediaError；容器没写时长时退回各路流里最长的时长，
    流也没有时长 → duration 0 + 警告（文件能读，不能当坏文件拒绝）。
    """
    def unreadable(detail: str) -> MediaError:
        return MediaError(MATERIAL_UNREADABLE.format(detail=detail))

    try:
        code, out, err = _run_probe([*FFPROBE_MATERIAL, str(path)], runner)
    except OSError as exc:
        raise unreadable(f"无法运行 ffprobe：{exc}") from exc
    if code != 0:
        raise unreadable(_tail(err) or f"退出码 {code}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise unreadable("ffprobe 没有输出可读的结果") from exc
    fmt = data.get("format") if isinstance(data, dict) else None
    if not isinstance(fmt, dict):
        raise unreadable("没有容器信息")
    streams = data.get("streams") if isinstance(data.get("streams"), list) else []
    stream_durations = [d for s in streams if isinstance(s, dict)
                        if (d := _positive_seconds(s.get("duration"))) is not None]
    duration = _positive_seconds(fmt.get("duration")) or max(stream_durations, default=0.0)
    warnings = [] if duration else [NO_CONTAINER_DURATION.format(name=Path(path).name)]
    return {"duration": duration, "streams": streams, "warnings": warnings}


def material_entry(src: Path, *, runner=subprocess.run) -> dict:
    """素材台账的一条：路径 / 名称 / 大小 + probe_material；文件不在或认不出抛 MediaError（KI-66）。"""
    src = Path(src)
    if not src.is_file():
        raise MediaError(f"原片不存在：{src}")
    entry = {"path": str(src), "name": src.name, "size": src.stat().st_size,
             **probe_material(src, runner=runner)}
    for w in entry.get("warnings") or []:  # 同时记在 materials.json 里，剪辑台警告栏常驻显示
        print(f"[!] {w}")
    return entry


def read_manifest(path: Path) -> dict:
    """切片缓存清单：缺失 → {}；损坏只是缓存，不能挡住出片 → 提示后当空缓存（全部重切）。"""
    try:
        return schema.read_json(path, default={})
    except schema.CorruptJSON as exc:
        print(CACHE_RESET.format(reason=exc))
        return {}


def complete_or_adopt(dst: Path, *, runner=subprocess.run) -> bool:
    """已完成，或是旧版本（无标记）留下且 ffprobe 读得出正时长的产物 → 补写标记并认领。

    只认领"完全没有标记"的旧文件；标记存在但大小不符说明被改动过，不认领。
    """
    dst = Path(dst)
    if is_complete(dst):
        return True
    if done_marker(dst).exists() or not dst.is_file() or dst.stat().st_size == 0:
        return False
    if _probe_duration(dst, runner) <= 0:
        return False
    _write_marker(dst)
    return True


FFPROBE_AUDIO = ["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0"]


def has_audio(path: Path, *, runner=subprocess.run) -> bool:
    """素材有没有音轨（KI-14）；ffprobe 读不了 → MediaError（不当作「没音轨」糊过去）。"""
    try:
        r = runner([*FFPROBE_AUDIO, str(path)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    except OSError as exc:  # 没装 ffprobe / 不可执行
        raise MediaError(f"无法运行 ffprobe：{exc}") from exc
    if r.returncode != 0:
        raise MediaError(f"读不了素材 {Path(path).name}：{_tail(r.stderr)}")
    return bool((r.stdout or "").strip())
