# -*- coding: utf-8 -*-
"""M4 Windows 导出：时间线 → 可双击导入的剪映草稿包。

链路：
    timeline.json
      → to_jianying.py --dry-run（媒体打进 Resources，路径指向临时草稿根）
      → 改写成 __DRAFT_DIR__ 占位符 + platform=windows
      → 加 INSTALL.bat / fix_paths.ps1 / README
      → zip

Windows 侧实测（2026-10-18）：明文草稿可直接被剪映打开识别，所以不再需要降级方案。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packaging.build_package import (  # noqa: E402
    rewrite_for_windows, write_installer, zip_pkg,
)


def _api_name(name: str) -> str:
    """包内草稿名走 ASCII，避免 cmd 的 GBK/UTF-8 差异。"""
    import re
    keep = [c if (c.isascii() and (c.isalnum() or c in "-_")) else "_" for c in name]
    out = re.sub(r"_+", "_", "".join(keep)).strip("_")
    return out or "JianYing_Draft"


def package_draft(draft_dir: Path, name: str, out_zip: Path) -> Path:
    """把一个（Mac 生成的）草稿目录打包成 Windows 导入包。"""
    name = _api_name(name)
    out_zip = Path(out_zip)
    pkg = out_zip.parent / f"_pkg_{name}"
    if pkg.exists():
        shutil.rmtree(pkg)
    target = pkg / "drafts" / name
    shutil.copytree(draft_dir, target)
    rewrite_for_windows(target)
    write_installer(pkg)
    zip_pkg(pkg, out_zip)
    shutil.rmtree(pkg, ignore_errors=True)
    return out_zip


def build_windows_package(timeline: Path, name: str, out_zip: Path) -> dict:
    """跑一遍草稿生成（不安装进剪映），再打包。"""
    timeline = Path(timeline)
    if not timeline.exists():
        raise FileNotFoundError(f"时间线不存在：{timeline}")
    with tempfile.TemporaryDirectory(prefix="aicut-export-") as tmp:
        tmp_root = Path(tmp)
        env = dict(os.environ, AI_CUT_DRAFT_ROOT=str(tmp_root / "draft_root"))
        proc = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/to_jianying.py"), str(timeline),
             "--name", _api_name(name), "--staging", str(tmp_root / "staging"),
             "--dry-run"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"生成草稿失败：{proc.stdout[-800:]} {proc.stderr[-800:]}")
        draft_dir = tmp_root / "staging" / _api_name(name)
        if not draft_dir.exists():
            raise RuntimeError(f"没找到草稿目录：{draft_dir}")
        package_draft(draft_dir, name, out_zip)

    return {"zip": str(out_zip), "size": Path(out_zip).stat().st_size}


def inspect_package(zip_path: Path) -> dict:
    """解包检查：文件数、占位符、安装脚本是否齐全。"""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        has_install = "INSTALL.bat" in names
        has_fix = "fix_paths.ps1" in names
        contents = [n for n in names if n.endswith("draft_content.json")]
        placeholder = False
        for n in contents:
            raw = z.read(n).decode("utf-8", "replace")
            if "__DRAFT_DIR__" in raw:
                placeholder = True
    return {"files": len(names), "install": has_install, "fix_paths": has_fix,
            "drafts": contents, "placeholder": placeholder}


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) < 4:
        raise SystemExit("用法：export_draft.py <timeline.json> <名字> <输出.zip>")
    print(build_windows_package(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])))
