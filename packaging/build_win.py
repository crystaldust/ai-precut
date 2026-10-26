# -*- coding: utf-8 -*-
"""构建 Windows 版：dist/ai-cut-windows-x64-<版本>-<构建号>.zip（里程碑 16；对应 Mac 侧 build_app.sh）。

    uv run python packaging/build_win.py

步骤：fetch_ffmpeg_win（下载 + 自检）→ PyInstaller → 把许可 / 说明 / LGPL 源码放进 dist/ai-cut/ → 打 zip（顶层目录 ai-cut/）。
packaging/ 与 PyPI 的 packaging 同名，本文件及同目录模块一律按文件路径加载。
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR_NAME = "ai-cut"
NOTICES_NAME = "THIRD-PARTY-NOTICES.txt"
README_NAME = "首次打开说明-Windows.txt"
EXTRA_DIRS = ("licenses", "sources")  # vendor/<名> → ai-cut/<名>
ZIP_PREFIX = "ai-cut-windows-x64"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"aicut_{name}", ROOT / "packaging" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 纯逻辑（Mac 上可单测） ----------

def zip_name(short_version: str, build: str) -> str:
    """ASCII 文件名：版本 / 构建号都必须是安全字符。"""
    for part in (short_version, build):
        if not part or not all(c.isascii() and (c.isalnum() or c in ".-+") for c in part):
            raise ValueError(f"版本号含不安全字符：{part!r}")
    return f"{ZIP_PREFIX}-{short_version}-{build}.zip"


def extra_files(root: Path, vendor: Path) -> list[tuple[Path, str]]:
    """要放进 ai-cut/ 的附加文件：(源路径, 相对 ai-cut/ 的 posix 路径)；缺必需文件抛 FileNotFoundError。"""
    out = [(root / "packaging" / NOTICES_NAME, NOTICES_NAME), (root / "packaging" / README_NAME, README_NAME)]
    for d in EXTRA_DIRS:
        src = vendor / d
        # 刻意只取一层：vendor/licenses、vendor/sources 都是平铺文件（fetch_ffmpeg_win 的产物），不含子目录
        files = sorted(p for p in src.glob("*") if p.is_file()) if src.is_dir() else []
        if not files:
            raise FileNotFoundError(f"缺少 {src}（先跑 packaging/fetch_ffmpeg_win.py）：LGPL 许可全文 / 对应源码必须随包")
        out += [(p, f"{d}/{p.name}") for p in files]
    missing = [str(p) for p, _ in out if not p.is_file()]
    if missing:
        raise FileNotFoundError("缺少文件：" + "、".join(missing))
    return out


def stage_extras(app_dir: Path, files: list[tuple[Path, str]]) -> None:
    for src, rel in files:
        dest = app_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)


def make_zip(app_dir: Path, zip_path: Path, top: str = APP_DIR_NAME) -> Path:
    """app_dir 的全部内容 → zip（顶层目录 top/；条目名 UTF-8，中文文件名 Windows 资源管理器可正常解压）。"""
    if not app_dir.is_dir():
        raise FileNotFoundError(f"没有 {app_dir}")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(app_dir.rglob("*")):
            if p.is_file():
                zf.write(p, f"{top}/{p.relative_to(app_dir).as_posix()}")
    return zip_path


# ---------- 边缘 ----------

def main() -> int:
    if sys.platform != "win32":
        print("[!] build_win.py 只在 Windows 上构建（PyInstaller 不能交叉打包）", file=sys.stderr)
        return 1
    fetch = _load("fetch_ffmpeg_win")
    if fetch.main([]) != 0:
        return 1
    version = _load("version")
    print("→ PyInstaller 构建")
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "ai-cut.spec"),
                        "--noconfirm", "--clean"], cwd=ROOT, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        code = getattr(exc, "returncode", 1) or 1
        print(f"✗ PyInstaller 构建失败（{exc}）", file=sys.stderr)
        return code
    app_dir = ROOT / "dist" / APP_DIR_NAME
    if not (app_dir / "ai-cut.exe").is_file():
        print(f"✗ 没有产出 {app_dir / 'ai-cut.exe'}", file=sys.stderr)
        return 1
    print("→ 随包交付：第三方许可、首次打开说明、LGPL 对应源码")
    stage_extras(app_dir, extra_files(ROOT, ROOT / "vendor"))
    name = zip_name(version.short_version(ROOT), version.build_number(ROOT))
    out = make_zip(app_dir, ROOT / "dist" / name)
    print(f"\n完成：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
