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
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packaging.build_package import (  # noqa: E402
    rewrite_for_windows, write_installer, zip_pkg,
)
from pipeline import proc, to_jianying  # noqa: E402


def _api_name(name: str) -> str:
    """包内草稿名走 ASCII，避免 cmd 的 GBK/UTF-8 差异。"""
    import re
    keep = [c if (c.isascii() and (c.isalnum() or c in "-_")) else "_" for c in name]
    out = re.sub(r"_+", "_", "".join(keep)).strip("_")
    return out or "JianYing_Draft"


def check_package(info: dict) -> None:
    """导出包自检：安装脚本、路径修复脚本、草稿、路径占位符缺一不可（审查修复 2）。"""
    problems = []
    if not info["install"]:
        problems.append("缺 INSTALL.bat")
    if not info["fix_paths"]:
        problems.append("缺 fix_paths.ps1")
    if not info["drafts"]:
        problems.append("包里没有 draft_content.json")
    if not info["placeholder"]:
        problems.append("素材路径没有改写成 __DRAFT_DIR__ 占位符")
    if problems:
        raise RuntimeError("导出包自检未通过：" + "；".join(problems))


def package_draft(draft_dir: Path, name: str, out_zip: Path) -> Path:
    """把一个（Mac 生成的）草稿目录打包成 Windows 导入包。

    zip 先写同目录临时文件、自检通过才改名；临时目录无论成败都清掉。
    """
    name = _api_name(name)
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    pkg = out_zip.parent / f"_pkg_{name}"
    tmp_zip = out_zip.with_name(f".{out_zip.stem}.partial-{uuid.uuid4().hex[:8]}.zip")
    try:
        if pkg.exists():
            shutil.rmtree(pkg)
        target = pkg / "drafts" / name
        shutil.copytree(draft_dir, target)
        rewrite_for_windows(target)
        write_installer(pkg)
        zip_pkg(pkg, tmp_zip)
        check_package(inspect_package(tmp_zip))
        os.replace(tmp_zip, out_zip)
    finally:
        shutil.rmtree(pkg, ignore_errors=True)
        tmp_zip.unlink(missing_ok=True)
    return out_zip


def build_windows_package(timeline: Path, name: str, out_zip: Path) -> dict:
    """跑一遍草稿生成（不安装进剪映），再打包。返回 zip、大小与 to_jianying 的警告汇总（KI-18）。"""
    timeline = Path(timeline)
    if not timeline.exists():
        raise FileNotFoundError(f"时间线不存在：{timeline}")
    with tempfile.TemporaryDirectory(prefix="aicut-export-") as tmp:
        tmp_root = Path(tmp)
        env = dict(os.environ, AI_CUT_DRAFT_ROOT=str(tmp_root / "draft_root"))
        # 必须是新进程：to_jianying 在 import 时读 AI_CUT_DRAFT_ROOT；
        # 打包后 sys.executable 是 App 本身，所以走 proc.module_cmd 自启（GL-14）
        cmd = proc.module_cmd("pipeline.to_jianying", [
            str(timeline), "--name", _api_name(name),
            "--staging", str(tmp_root / "staging"), "--dry-run"])
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=env, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            raise RuntimeError(f"生成草稿失败：{result.stdout[-800:]} {result.stderr[-800:]}")
        draft_dir = tmp_root / "staging" / _api_name(name)
        if not draft_dir.exists():
            raise RuntimeError(f"没找到草稿目录：{draft_dir}")
        package_draft(draft_dir, name, out_zip)

    warnings = to_jianying.parse_report(result.stdout)["warnings"]
    return {"zip": str(out_zip), "size": Path(out_zip).stat().st_size, "warnings": warnings}


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
