# -*- coding: utf-8 -*-
"""下载并自检 Windows 版 LGPL ffmpeg/ffprobe（里程碑 16；对应 Mac 侧 build_ffmpeg.sh）。

    python packaging/fetch_ffmpeg_win.py               下载（SHA256 钉死）→ 解压 → 自检
    python packaging/fetch_ffmpeg_win.py --verify-only 只对已有 vendor/bin/*.exe 跑自检

来源：BtbN/FFmpeg-Builds 的 win64-lgpl 静态构建（无 x264/x265），钉在日期 tag 的资产上——
绝不用会漂移的 latest。同时下载对应 FFmpeg 源码与 BtbN 构建脚本（LGPL 要求随包提供源码）。
产物目录可用 AICUT_FFMPEG_OUT 覆盖（默认 vendor/：bin/ licenses/ sources/）。
只用标准库；自检只在 Windows 上能真正执行 exe。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

# ---- 钉死的版本（2026-10-22 选定：最近的月末构建，月末 tag 保留两年） ----
RELEASE_TAG = "autobuild-2026-09-30-13-08"
FFMPEG_COMMIT = "29e619e767cde9045a75c29bc9a8278ae7b3a98b"
BUILD_SCRIPTS_COMMIT = "6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b"  # RELEASE_TAG 指向的 BtbN 提交
ZIP_NAME = "ffmpeg-n8.1.3-9-g29e619e767-win64-lgpl-8.1.zip"
FFMPEG_VERSION_PREFIX = "ffmpeg version n8.1.3-9-g29e619e767"
FFMPEG_ZIP_URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE_TAG}/{ZIP_NAME}"
FFMPEG_ZIP_SHA256 = "4a7642b2264c03e8a0ce8a3825b933ee5580656f45695a086fe7e294045ffc0a"
FFMPEG_SRC_NAME = f"ffmpeg-{FFMPEG_COMMIT}.tar.gz"
FFMPEG_SRC_URL = f"https://github.com/FFmpeg/FFmpeg/archive/{FFMPEG_COMMIT}.tar.gz"
FFMPEG_SRC_SHA256 = "8e4699bcb6a311772e8f513cc72ce27328891b82a598b82e7cff3dfe580875a0"
BUILD_SCRIPTS_NAME = f"ffmpeg-builds-{BUILD_SCRIPTS_COMMIT}.tar.gz"
BUILD_SCRIPTS_URL = f"https://github.com/BtbN/FFmpeg-Builds/archive/{BUILD_SCRIPTS_COMMIT}.tar.gz"
BUILD_SCRIPTS_SHA256 = "81da4f7c878dc0f60e6b8d0049a112e32178e20f025d468fe4e99e77b2dfe0ec"

TIMEOUT_S = 60
CHUNK = 1 << 20
PROBE_TIMEOUT_S = 60

# 代码里用到的能力；与 build_ffmpeg.sh 的 REQUIRED_* 对应（滤镜清单由测试保证两边一致）
BASE_ENCODERS = ("aac", "pcm_s16le", "rawvideo")
H264_ENCODERS = ("h264_mf", "libopenh264")  # Windows 上至少要有一个（Task 5 决定顺序）
REQUIRED_LIBS = ("libfreetype", "libharfbuzz")
REQUIRED_FILTERS = ("drawtext", "scdet", "blackdetect", "freezedetect", "silencedetect", "concat", "scale",
                    "pad", "setsar", "fps", "trim", "setpts", "atrim", "asetpts", "aresample", "format",
                    "anullsrc", "aformat")
# configure 里出现任何一个就不是干净的 LGPL 构建（按 token 精确匹配，--disable-gpl 不算）
FORBIDDEN_ENABLES = frozenset(f"--enable-{n}" for n in (
    "gpl", "nonfree", "libx264", "libx265", "libxvid", "libvidstab", "libfdk-aac"))
# BtbN 的 win64-lgpl 变体用 defaults-lgpl.sh 配置：FF_CONFIGURE="--enable-version3 --disable-debug"（已核对
# 构建脚本包），所以随包许可证是 LGPLv3（文本里还会引用 GPLv3），不是 LGPLv2.1。
VERSION3_FLAG = "--enable-version3"
LICENSE_NAME = "LGPL-3.0-or-later（FFmpeg --enable-version3）"
LICENSE_FILES = ("COPYING.LGPLv3", "COPYING.GPLv3")  # 从 FFmpeg 源码包取，落到 vendor/licenses/FFmpeg-<名>

MAX_ZIP_BYTES = 300 * 1024 * 1024   # 实际约 170MB
MAX_SRC_BYTES = 100 * 1024 * 1024   # 源码包实际约 17MB
MAX_LICENSE_BYTES = 1024 * 1024

ROOT = Path(__file__).resolve().parent.parent


# ---------- 纯逻辑：输入是命令输出文本，便于在 Mac 上单测 ----------

def parse_buildconf(buildconf: str) -> list[str]:
    """-buildconf 输出 → configure 参数 token 列表（只留以 -- 开头的）。"""
    return [t for t in buildconf.split() if t.startswith("--")]


def check_outputs(*, version: str, license_text: str, buildconf: str, encoders: str, filters: str) -> list[str]:
    """返回全部问题（空列表 = 通过）；一次报完，不在第一条就停。"""
    problems: list[str] = []
    if not version.startswith(FFMPEG_VERSION_PREFIX):
        problems.append(f"版本不符：期望「{FFMPEG_VERSION_PREFIX}…」，实际「{version.strip()}」（与随包源码 / NOTICES 不一致）")
    if "GNU Lesser General Public" not in license_text:
        problems.append("不是 LGPL 构建")
    elif not re.search(r"version\s+3", license_text):
        problems.append(f"许可证不是 v3，与随包的 {LICENSE_NAME} 不符")
    tokens = parse_buildconf(buildconf)
    bad = sorted(FORBIDDEN_ENABLES.intersection(tokens))
    if bad:
        problems.append(f"含 GPL/nonfree 组件：{' '.join(bad)}")
    if VERSION3_FLAG not in tokens:
        problems.append(f"configure 没有 {VERSION3_FLAG}，与随包的 {LICENSE_NAME} 许可证文本不符")
    for lib in REQUIRED_LIBS:
        if f"--enable-{lib}" not in tokens:
            problems.append(f"未启用 {lib}")
    for name in BASE_ENCODERS:
        if not _has_encoder(encoders, name):
            problems.append(f"缺编码器 {name}")
    if not any(_has_encoder(encoders, name) for name in H264_ENCODERS):
        problems.append(f"缺 H.264 编码器：{' / '.join(H264_ENCODERS)} 一个都没有")
    for name in REQUIRED_FILTERS:
        if not re.search(rf"^ [A-Z.]{{2,3}} +{re.escape(name)} ", filters, re.M):
            problems.append(f"缺滤镜 {name}")
    return problems


def _has_encoder(encoders: str, name: str) -> bool:
    return re.search(rf"^ [A-Z.]{{6}} {re.escape(name)} ", encoders, re.M) is not None


def sanitize_buildconf(buildconf: str) -> str:
    """随包的 configure 行去掉构建机绝对路径。"""
    return re.sub(r"--prefix=\S+", "--prefix=<build-prefix>", buildconf)


# ---------- 边缘：下载 / 解压 / 执行 ----------

def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str, *, opener=urllib.request.urlopen,
             max_bytes: int = MAX_ZIP_BYTES) -> None:
    """下载到 dest 并校验；已有且哈希对就复用。任何失败（状态码、超限、哈希、IO）都清掉文件并抛 RuntimeError。"""
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    try:
        part.unlink(missing_ok=True)  # 上次中断留下的半成品
        if dest.is_file():
            if _sha256_of(dest) == sha256:
                return
            dest.unlink()
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"→ 下载 {dest.name}")
        total = 0
        with opener(url, timeout=TIMEOUT_S) as resp, open(part, "wb") as out:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            while chunk := resp.read(CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"超过大小上限 {max_bytes} 字节")
                out.write(chunk)
        if _sha256_of(part) != sha256:
            raise RuntimeError(f"校验失败：{dest.name}（SHA256 与脚本里钉死的不符，已删除）")
        os.replace(part, dest)
    except (OSError, ValueError, RuntimeError) as exc:
        _discard(part, dest)
        if isinstance(exc, RuntimeError) and str(exc).startswith("校验失败"):
            raise
        raise RuntimeError(f"下载失败：{dest.name}（{exc}）") from exc


def _discard(*paths: Path) -> None:
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass  # 清理失败不能盖住原始错误


def _exe_member(names: list[str], exe: str) -> str | None:
    """只认恰好是 <顶层目录>/bin/<exe> 的成员（3 段、第二段是 bin、无 ..），多于或少于一个返回 None。"""
    hits = []
    for n in names:
        parts = n.split("/")
        if len(parts) == 3 and parts[0] and parts[1] == "bin" and parts[2] == exe and ".." not in parts:
            hits.append(n)
    return hits[0] if len(hits) == 1 else None


def extract_binaries(zip_path: Path, bin_dir: Path) -> None:
    """取 <顶层>/bin/ffmpeg.exe 与 ffprobe.exe；先写 .tmp 再 os.replace，中途失败不留半成品。"""
    bin_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        for exe in ("ffmpeg.exe", "ffprobe.exe"):
            member = _exe_member(names, exe)
            if member is None:
                raise RuntimeError(f"压缩包里找不到唯一的 <顶层>/bin/{exe}（{zip_path.name}）")
            target = bin_dir / exe
            tmp = bin_dir / (exe + ".tmp")
            try:
                with z.open(member) as src, open(tmp, "wb") as out:
                    while chunk := src.read(CHUNK):
                        out.write(chunk)
                os.replace(tmp, target)
            except BaseException:
                _discard(tmp)
                raise


def extract_license(src_tar: Path, lic_dir: Path) -> None:
    """从 FFmpeg 源码包取随包许可证文本（LICENSE_FILES）。"""
    lic_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(src_tar) as t:
        for name in LICENSE_FILES:
            wanted = f"FFmpeg-{FFMPEG_COMMIT}/{name}"
            try:
                member = t.getmember(wanted)
            except KeyError as exc:
                raise RuntimeError(f"源码包里找不到 {wanted}") from exc
            if not member.isreg() or member.size > MAX_LICENSE_BYTES:
                raise RuntimeError(f"{wanted} 不是正常大小的普通文件")
            f = t.extractfile(member)
            if f is None:
                raise RuntimeError(f"{wanted} 无法读取")
            (lic_dir / f"FFmpeg-{name}").write_bytes(f.read(MAX_LICENSE_BYTES))


def _run(exe: Path, *args: str) -> str:
    r = subprocess.run([str(exe), "-hide_banner", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=PROBE_TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(f"{exe.name} {' '.join(args)} 退出码 {r.returncode}：{(r.stderr or '').strip()[:200]}")
    return r.stdout


def verify(out_dir: Path) -> None:
    """对 out_dir/bin 下的 exe 跑自检；任何一条不过抛 RuntimeError；通过则写 licenses/ffmpeg-buildconf.txt。"""
    ff, fp = out_dir / "bin" / "ffmpeg.exe", out_dir / "bin" / "ffprobe.exe"
    if not (ff.is_file() and fp.is_file()):
        raise RuntimeError(f"缺少 {ff} 或 {fp}")
    version = (_run(ff, "-version").splitlines() or [""])[0]
    probe_version = (_run(fp, "-version").splitlines() or [""])[0].replace("ffprobe", "ffmpeg", 1)
    buildconf = _run(ff, "-buildconf")
    problems = check_outputs(version=version, license_text=_run(ff, "-L"), buildconf=buildconf,
                             encoders=_run(ff, "-encoders"), filters=_run(ff, "-filters"))
    if not probe_version.startswith(FFMPEG_VERSION_PREFIX):
        problems.append(f"ffprobe 版本不符：「{probe_version.strip()}」")
    if problems:
        raise RuntimeError("自检未通过：\n" + "\n".join(f"✗ {p}" for p in problems))
    lic = out_dir / "licenses"
    lic.mkdir(parents=True, exist_ok=True)
    (lic / "ffmpeg-buildconf.txt").write_text(sanitize_buildconf(buildconf), encoding="utf-8")
    print("✓ 自检通过：LGPL、FreeType + HarfBuzz、H.264 编码器与所需滤镜齐全")


def fetch(out_dir: Path) -> None:
    src, bin_dir, lic = out_dir / "sources", out_dir / "bin", out_dir / "licenses"
    cache = out_dir / "cache"  # 二进制 zip 不放 sources/（那里只放随包分发的源码）
    download(FFMPEG_ZIP_URL, cache / ZIP_NAME, FFMPEG_ZIP_SHA256)
    download(FFMPEG_SRC_URL, src / FFMPEG_SRC_NAME, FFMPEG_SRC_SHA256, max_bytes=MAX_SRC_BYTES)
    download(BUILD_SCRIPTS_URL, src / BUILD_SCRIPTS_NAME, BUILD_SCRIPTS_SHA256, max_bytes=MAX_SRC_BYTES)
    extract_binaries(cache / ZIP_NAME, bin_dir)
    extract_license(src / FFMPEG_SRC_NAME, lic)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out_dir = Path(os.environ.get("AICUT_FFMPEG_OUT") or ROOT / "vendor")
    try:
        if "--verify-only" not in args:
            fetch(out_dir)
        verify(out_dir)
    except (RuntimeError, OSError, subprocess.SubprocessError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
