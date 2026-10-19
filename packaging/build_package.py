#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把剪映草稿打成「Windows 双击导入包」。

产物结构（解压后）：
    双击安装.bat          ← 纯 ASCII，避免中文乱码
    说明.txt              ← UTF-8 BOM，记事本能正常显示
    fix_paths.ps1         ← 只做一件事：把路径占位符替换成本机真实路径
    drafts/<草稿名>/...   ← 草稿本体（含 Resources 素材）

设计取舍：
  * 不依赖 Python / Node，只需要 Windows 自带的 cmd + PowerShell；
  * 路径不写死用户名，用 __DRAFT_DIR__ 占位，装的时候替换；
  * 不碰 root_meta_info.json（剪映启动时会扫描草稿目录，公开的导入教程也是这么做的）；
  * 草稿名用 ASCII，避免 cmd 的 GBK/UTF-8 编码差异把中文路径弄坏。

用法：
    python3 packaging/build_package.py --draft "<剪映库里的草稿目录>" --name JianYing_Test_01 -o dist
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))  # 独立运行时可导入 pipeline；append 防遮蔽三方包

from pipeline import jy_version  # noqa: E402

PH_DRAFT = "__DRAFT_DIR__"
# INSTALL.bat 在延迟扩展下运行：草稿名里有这些字符会被 cmd 改写，回滚时的 rd 可能删到别的目录
BAT_UNSAFE_CHARS = frozenset('!%^&|<>"')
BAD_DRAFT_NAME = "草稿名 {name!r} 含 Windows 安装脚本无法安全处理的字符（{chars}），请换一个名字"
PH_ROOT = "__DRAFT_ROOT__"


# ------------------------------------------------------------------ 草稿处理
def rewrite_for_windows(draft_dir: Path) -> None:
    """把 Mac 绝对路径改成占位符，并把 platform 标记成 windows。"""
    content_path = draft_dir / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    for kind in ("videos", "audios"):
        for m in content["materials"].get(kind, []):
            name = Path(m["path"].replace("\\", "/")).name
            m["path"] = f"{PH_DRAFT}\\Resources\\{name}"
    plat = {"app_id": 0, "app_source": "", "app_version": "", "device_id": "",
            "hard_disk_id": "", "mac_address": "", "os": "windows", "os_version": ""}
    for k in ("platform", "last_modified_platform"):
        base = content.get(k) if isinstance(content.get(k), dict) else {}
        content[k] = {**base, **plat}
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (draft_dir / "draft_info.json").write_text(
        json.dumps(content, ensure_ascii=False), encoding="utf-8")

    meta_path = draft_dir / "draft_meta_info.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    now = int(time.time() * 1_000_000)
    meta.update({
        "draft_id": str(uuid.uuid4()).upper(),
        "draft_name": draft_dir.name,
        "draft_fold_path": PH_DRAFT,
        "draft_root_path": PH_ROOT,
        "tm_draft_create": now,
        "tm_draft_modified": now,
        "tm_duration": content["duration"],
    })
    # 媒体池登记（缺了会提示"媒体丢失"）
    records = []
    for kind, metetype in (("videos", None), ("audios", "music")):
        for m in content["materials"].get(kind, []):
            name = Path(m["path"].replace("\\", "/")).name
            records.append({
                "create_time": now // 1_000_000,
                "duration": m.get("duration", 0),
                "extra_info": Path(name).stem,
                "file_Path": f"{PH_DRAFT}\\Resources\\{name}",
                "height": m.get("height", 0),
                "id": str(uuid.uuid4()),
                "import_time": now // 1_000_000,
                "import_time_ms": now,
                "item_source": 1,
                "md5": "",
                "metetype": metetype or ("photo" if m.get("type") == "photo" else "video"),
                "roughcut_time_range": {"duration": -1, "start": -1},
                "sub_time_range": {"duration": -1, "start": -1},
                "type": 0,
                "width": m.get("width", 0),
            })
    groups = meta.get("draft_materials")
    if not isinstance(groups, list):
        groups = []
    found = False
    for group in groups:
        if isinstance(group, dict) and group.get("type") == 0:
            group["value"] = records
            found = True
    if not found:
        groups.append({"type": 0, "value": records})
    meta["draft_materials"] = groups
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def check_draft_name(name: str) -> None:
    """拒绝 cmd 会改写的草稿名（ValueError）；导出链路的 _api_name 产物天然满足。"""
    bad = sorted(set(name) & BAT_UNSAFE_CHARS)
    if bad:
        raise ValueError(BAD_DRAFT_NAME.format(name=name, chars=" ".join(bad)))


def make_minimal_draft(dst: Path, clips: list[tuple[str, str]]) -> None:
    """用 3 个真实镜头造一个最小草稿（用来先验证能不能导入）。"""
    tpl = jy_version.TEMPLATE   # 缺模板 = 结构不对的草稿，不交付（D1 / KI-81）
    if not tpl.exists():
        sys.exit(jy_version.TEMPLATE_MISSING.format(series=jy_version.VERIFIED_SERIES, path=tpl))
    sys.path.insert(0, str(Path("/tmp/jyvenv/lib/python3.14/site-packages")))
    import pyJianYingDraft as draft

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    staging = dst.parent
    script = draft.DraftFolder(str(staging)).create_draft(
        dst.name, 1080, 1920, fps=30, allow_replace=True)
    script.append_track(draft.TrackSpec(draft.TrackType.video))
    script.append_track(draft.TrackSpec(draft.TrackType.text))

    t = 0
    for clip, sub in clips:
        mat = draft.VideoMaterial(clip)
        dur = mat.duration
        script.add_segment(draft.VideoSegment(
            mat, draft.Timerange(t, dur), source_timerange=draft.Timerange(0, dur)))
        if sub:
            script.add_segment(draft.TextSegment(
                sub, draft.Timerange(t, dur),
                style=draft.TextStyle(size=6.5, color=(1.0, 1.0, 1.0), align=1, bold=True),
                clip_settings=draft.ClipSettings(transform_y=-0.72)))
        t += dur
    script.save()

    # 素材打包进 Resources
    content_path = dst / "draft_content.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    res = dst / "Resources"
    res.mkdir(exist_ok=True)
    for kind in ("videos", "audios"):
        for m in content["materials"].get(kind, []):
            src = Path(m["path"])
            shutil.copy2(src, res / src.name)
    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    # 套用已验证版本的剪映空草稿骨架，字段级同构
    base = json.loads(tpl.read_text(encoding="utf-8"))
    for k, v in content.items():
        if k != "materials":
            base[k] = v
    for k, v in content["materials"].items():
        if v:
            base["materials"][k] = v
    (dst / "draft_content.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ 安装器
BAT = r"""@echo off
setlocal enabledelayedexpansion
title JianYing Draft Import
echo ============================================
echo   JianYing draft import
echo ============================================
echo.

set "ROOT=%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"
if not exist "%ROOT%" (
  echo [X] JianYing draft folder not found:
  echo     !ROOT!
  echo     Open JianYing once, close it, then run this again.
  pause & exit /b 1
)

tasklist /FI "IMAGENAME eq JianyingPro.exe" 2>nul | find /i "JianyingPro.exe" >nul
if not errorlevel 1 (
  echo [X] JianYing is running. Please quit it completely ^(tray icon too^), then run again.
  pause & exit /b 1
)

set "PKG=%~dp0"
set "COUNT=0"
set "CONFLICT=0"
for /d %%D in ("%PKG%drafts\*") do (
  set /a COUNT+=1
  if exist "%ROOT%\%%~nxD" (
    echo [X] A draft with the same name already exists in JianYing:
    echo     !ROOT!\%%~nxD
    set "CONFLICT=1"
  )
)
if "%COUNT%"=="0" (
  echo [X] No draft found in this package. Unzip the whole package first.
  pause & exit /b 1
)
if "%CONFLICT%"=="1" (
  echo     Nothing was installed and your existing drafts were not touched.
  echo     Delete or rename that draft in JianYing first, then run this again.
  pause & exit /b 1
)

set "FAILED=0"
for /d %%D in ("%PKG%drafts\*") do (
  set "NAME=%%~nxD"
  echo [*] Installing !NAME! ...
  xcopy "%%D" "%ROOT%\!NAME!\" /E /I /Y /Q >nul
  if errorlevel 1 (
    echo [X] Copy failed for !NAME!. Try running as administrator.
    set "FAILED=1"
    if exist "%ROOT%\!NAME!" rd /s /q "%ROOT%\!NAME!"
  ) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PKG%fix_paths.ps1" -DraftDir "%ROOT%\!NAME!"
    if errorlevel 1 (
      echo [X] Path fix failed for !NAME! - JianYing would show missing media.
      set "FAILED=1"
      rd /s /q "%ROOT%\!NAME!"
    ) else (
      echo     installed to: !ROOT!\!NAME!
    )
  )
)

if "%FAILED%"=="1" (
  echo.
  echo [X] Some drafts were NOT installed correctly. See the messages above.
  echo     The incomplete copies were removed. Send a screenshot of this window to the developer.
  pause & exit /b 1
)
echo.
echo [OK] Done.
echo      1. Start JianYing
echo      2. Open the draft from the list
echo      3. Check: video clips on the timeline, subtitles visible
echo.
echo If the draft does not appear, tell the developer the draft name above.
pause
"""

PS1 = r"""param([Parameter(Mandatory=$true)][string]$DraftDir)
$ErrorActionPreference = 'Stop'
try {
  $draft = $DraftDir.TrimEnd('\')
  $root  = Split-Path $draft -Parent
  $dEsc  = $draft.Replace('\','\\')
  $rEsc  = $root.Replace('\','\\')
  Get-ChildItem -LiteralPath $draft -Filter *.json | ForEach-Object {
    $t = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8)
    if ($t.Contains('__DRAFT_DIR__') -or $t.Contains('__DRAFT_ROOT__')) {
      $n = $t.Replace('__DRAFT_DIR__', $dEsc).Replace('__DRAFT_ROOT__', $rEsc)
      [IO.File]::WriteAllText($_.FullName, $n, (New-Object Text.UTF8Encoding($false)))
    }
  }
} catch {
  Write-Host "[X] fix_paths failed: $($_.Exception.Message)"
  exit 1
}
exit 0
"""

NOTES = """剪映草稿导入说明（Windows）

一、这是什么
  这是用程序生成的剪映工程（时间线 + 字幕 + 素材），用来验证剪映能不能直接打开。
  不需要安装 Python 或任何软件，双击一个 bat 就行。

二、怎么装
  1. 先把压缩包完整解压（不要直接在压缩包里双击）。
  2. 确保剪映已经启动过一次并完全退出（右下角托盘图标也要退出）。
  3. 双击 INSTALL.bat（Windows 可能会弹一次安全提示，点“仍要运行”）。
  4. 看到 [OK] Done 后，打开剪映 → 本地草稿，找安装时打印的草稿名。

三、装了什么
  - 草稿本体复制到：%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\<草稿名>
  - 素材在该草稿的 Resources 文件夹里，程序已经自动改成本机路径。
  - 不会动你已有的任何草稿：剪映里已有同名草稿时，安装会直接停下并提示（[X] ... already exists），
    什么都不装；请先在剪映里删除或改名那个草稿，再双击 INSTALL.bat。
  - 安装中途失败会显示 [X] 并自动删掉这次装了一半的副本（不会出现 [OK] Done），
    请把窗口截图发给开发者。

四、看什么（这是验证重点）
  1. 草稿列表里有没有出现？
  2. 双击能不能打开？
  3. 时间线上有没有片段？时间码对不对？
  4. 画面能不能预览（不是黑屏/不是「媒体丢失」）？
  5. 字幕在不在？

五、如果出问题，请回传
  - 第几步失败的截图
  - 剪映版本号（设置 → 关于）
  - 草稿目录截图（%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft）
  - 如果提示「媒体丢失」，把草稿文件夹里的 draft_content.json 发回来

六、怎么卸载
  在剪映里右键删除该草稿，或直接删掉上面那个草稿文件夹。
"""


def write_installer(pkg: Path) -> None:
    """写 INSTALL.bat / fix_paths.ps1 / README.txt；草稿名不安全就什么都不写（ValueError）。"""
    for d in sorted((pkg / "drafts").glob("*")):
        check_draft_name(d.name)
    (pkg / "INSTALL.bat").write_text(BAT.replace("\n", "\r\n"), encoding="ascii", errors="replace")
    (pkg / "fix_paths.ps1").write_text(PS1.replace("\n", "\r\n"), encoding="utf-8-sig")
    (pkg / "README.txt").write_text(NOTES.replace("\n", "\r\n"), encoding="utf-8-sig")


def zip_pkg(pkg: Path, out_zip: Path) -> int:
    """打 zip，返回字节数；不打印（调用方可能传的是临时路径，KI-64）。"""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(pkg))
    return out_zip.stat().st_size


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", help="现成的草稿目录（完整版）")
    ap.add_argument("--name", required=True, help="包里的草稿名（建议 ASCII）")
    ap.add_argument("--minimal", action="store_true", help="生成 3 镜头最小测试草稿")
    ap.add_argument("-o", "--out", default="dist")
    args = ap.parse_args()
    try:
        check_draft_name(args.name)
    except ValueError as exc:
        sys.exit(str(exc))

    pkg = ROOT / args.out / f"_pkg_{args.name}"
    if pkg.exists():
        shutil.rmtree(pkg)
    drafts = pkg / "drafts"
    target = drafts / args.name
    target.mkdir(parents=True)

    if args.minimal:
        clips = []
        clips_dir = ROOT / "projects/2026-09-01_活动/work/clips"
        picks = [("sh27.mp4", "甲方签字日期，写上二零二六年九月一号。"),
                 ("sh28.mp4", ""),
                 ("sh35.mp4", "")]
        for fn, sub in picks:
            p = clips_dir / fn
            if p.exists():
                clips.append((str(p), sub))
        if not clips:
            sys.exit("找不到测试镜头，检查 projects/.../work/clips")
        make_minimal_draft(target, clips)
        rewrite_for_windows(target)
        print(f"最小草稿：{len(clips)} 镜")
    else:
        src = Path(args.draft).expanduser()
        if not src.exists():
            sys.exit(f"草稿不存在：{src}")
        shutil.rmtree(target)
        shutil.copytree(src, target)
        # 去掉剪映自己产生的缓存文件，减小体积
        for junk in (".backup", "draft.extra", "adjust_mask", "matting", "smart_crop"):
            p = target / junk
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        for f in target.glob("draft_cover.jpg"):
            f.unlink(missing_ok=True)
        rewrite_for_windows(target)
        size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1e6
        print(f"完整草稿：{size:.0f} MB")

    write_installer(pkg)
    out_zip = ROOT / args.out / f"{args.name}.zip"
    size = zip_pkg(pkg, out_zip)
    print(f"打包完成：{out_zip}  ({size / 1e6:.1f} MB)")
    shutil.rmtree(pkg)


if __name__ == "__main__":
    main()
