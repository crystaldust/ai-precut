# -*- coding: utf-8 -*-
"""一键诊断包（PRD FR-13，GL-19）：版本、阶段耗时、错误栈（日志）、Key 是否已配置。

保证（白名单 + 脱敏）：
  * 不带的文件：转写文本、分镜 / 选段、音视频、剪辑偏好与片名（project.json 只留白名单字段）；
  * 不带 Key：既不带明文也不带掩码，只有「是否已配置 + 来源」；已登记的 Key 与 Bearer/Basic/sk-/AKLT 令牌一律打码；
  * 绝对路径只留文件名；failed.json 只留 stage / error / at。
尽力而为、不保证：日志只记任务起止与 [错误]/[x]/[!]/Traceback 行，但这些行和云端返回的错误文案里
仍可能夹带少量用户内容（例如报错里引用的文件名）。界面在导出前会提示用户自己过目再发送。
"""
from __future__ import annotations

import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
import zipfile
from pathlib import Path

from pipeline import applog, consent, plat, proc, schema, secrets

BUNDLE_PREFIX = "剪辑台诊断-"
SAFE_WORK_FILES = ("timings.json", "failed.json", "asr_task.json")
PROJECT_KEYS = ("name", "preset", "platform", "target_duration", "created",
                "schema_version")  # project.json 只带这些（title / calibration / brief 是用户填写的内容）
MIN_HOME_LEN = 2  # 主目录是 "/" 时不做替换，否则整份文本都被改坏
FAILED_FIELDS = ("stage", "error", "at")  # failed.json 只带这些（context 里可能有路径）
BUNDLE_MODE = 0o600
FFMPEG_TIMEOUT_S = 5
BUILD_INFO_FILE = "build_info.json"  # 打包时写入（version / build / commit）
MAX_NAME_TRIES = 100


def app_version() -> str:
    """打包版读 Info.plist（Windows：build_info.json），开发版读 pyproject.toml；都失败 → unknown。"""
    try:
        if proc.FROZEN and plat.IS_WIN:
            info = json.loads(proc.resource_path(BUILD_INFO_FILE).read_text(encoding="utf-8"))
            return str(info["version"])
        if proc.FROZEN:
            plist = Path(sys.executable).resolve().parents[1] / "Info.plist"
            with open(plist, "rb") as f:
                return str(plistlib.load(f)["CFBundleShortVersionString"])
        data = tomllib.loads((proc.app_root() / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, ValueError, IndexError):
        return "unknown"


def ffmpeg_info() -> dict | None:
    """当前 PATH 上的 ffmpeg：路径、版本行、是否 LGPL；没有或跑不起来 → None。"""
    ff = shutil.which("ffmpeg")
    if ff is None:
        return None
    try:
        version = subprocess.run([ff, "-hide_banner", "-version"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace",
                                 timeout=FFMPEG_TIMEOUT_S, **plat.NO_WINDOW).stdout
        license_text = subprocess.run([ff, "-hide_banner", "-L"], capture_output=True,
                                      text=True, encoding="utf-8", errors="replace",
                                      timeout=FFMPEG_TIMEOUT_S, **plat.NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return {"path": ff, "version": (version.splitlines() or [""])[0],
            "lgpl": "Lesser General Public" in license_text}


def default_out_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home() / "Desktop"


def _scrub(text: str) -> str:
    """脱敏 + 用户主目录（含 resolve 后的真实路径）换成 ~。"""
    text = applog.redact(text)
    text = applog.strip_paths(text)  # 绝对路径 → 文件名
    home = Path.home()
    for h in sorted({str(home), str(home.resolve())}, key=len, reverse=True):
        if len(h.rstrip("/")) >= MIN_HOME_LEN:
            text = text.replace(h, "~")
    return text


def _credentials() -> dict:
    try:
        st = secrets.status()  # 可能触发钥匙串授权（用户点了导出才会走到这里）
        return {k: {"configured": bool(v.get("configured")), "source": v.get("source", "")}
                for k, v in st.items()}  # 掩码也不带
    except Exception as exc:  # noqa: BLE001 - 钥匙串被锁也要能导出诊断包
        return {"error": _scrub(f"{type(exc).__name__}: {exc}")}


def _meta(project_dir: Path | None) -> dict:
    return {
        "created": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "app_version": app_version(),
        "frozen": proc.FROZEN,
        "macos": platform.mac_ver()[0] or platform.platform(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "ffmpeg": ffmpeg_info(),
        "log_dir": str(applog.log_dir()),
        "consent": consent.accepted(),
        "credentials": _credentials(),
        "project": project_dir.name if project_dir else None,
    }


def _project_json(project_dir: Path) -> str | None:
    try:
        cfg = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cfg, dict):
        return None
    out = {k: cfg[k] for k in PROJECT_KEYS if k in cfg}
    if isinstance(cfg.get("material"), str):
        out["material"] = Path(cfg["material"]).name
    return json.dumps(out, ensure_ascii=False, indent=2)


def _failed_summary(text: str) -> str:
    try:
        items = json.loads(text)
    except ValueError:
        return "[]"
    kept = [{k: x[k] for k in FAILED_FIELDS if k in x}
            for x in (items if isinstance(items, list) else []) if isinstance(x, dict)]
    return json.dumps(kept, ensure_ascii=False, indent=2)


def _file_listing(work: Path) -> str:
    """work/ 下的相对路径 + 字节数；不跟随符号链接（防止把别处的目录列进来）。"""
    lines = []
    for dirpath, dirnames, filenames in os.walk(work, followlinks=False):
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                size = p.lstat().st_size
            except OSError:
                continue
            lines.append(f"{p.relative_to(work.parent).as_posix()}\t{size}")
        dirnames.sort()
    return "\n".join(sorted(lines)) + "\n"


def _write_project(z: zipfile.ZipFile, project_dir: Path) -> None:
    if (text := _project_json(project_dir)) is not None:
        z.writestr("project/project.json", _scrub(text))
    work = project_dir / "work"
    if work.is_symlink():  # work 本身是链接：不跟过去
        return
    for name in SAFE_WORK_FILES:
        f = work / name
        if f.is_file() and not f.is_symlink():
            text = f.read_text(encoding="utf-8", errors="replace")
            if name == "failed.json":
                text = _failed_summary(text)
            z.writestr(f"project/work/{name}", _scrub(text))
    if work.is_dir():
        z.writestr("project/files.txt", _scrub(_file_listing(work)))


def _target(out_dir: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for n in range(1, MAX_NAME_TRIES + 1):
        suffix = "" if n == 1 else f"-{n}"
        path = out_dir / f"{BUNDLE_PREFIX}{stamp}{suffix}.zip"
        if not path.exists():
            return path
    raise OSError("诊断包重名过多")


def build_bundle(out_dir: Path, project_dir: Path | None = None) -> Path:
    """生成诊断 zip 并返回路径；先写 .part 再原子改名，失败不留半截文件。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = _target(out_dir)
    part = out_dir / f".{target.name}.{uuid.uuid4().hex[:8]}.part"
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("meta.json", _scrub(json.dumps(_meta(project_dir), ensure_ascii=False,
                                                      indent=2)))
            for log in sorted(applog.log_dir().glob("*.log*")):
                if log.is_file() and not log.is_symlink():
                    z.writestr(f"logs/{log.name}",
                               _scrub(log.read_text(encoding="utf-8", errors="replace")))
            if project_dir is not None:
                _write_project(z, Path(project_dir))
        os.chmod(part, BUNDLE_MODE)  # 只有自己能读
        schema.atomic_replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    applog.get("diagnostics").info("诊断包已生成：%s", target.name)
    return target
