# -*- coding: utf-8 -*-
"""剪映版本的唯一来源（KI-17）：已验证版本、对应的草稿骨架模板、读取本机已装剪映的版本。

pyJianYingDraft 0.3.1 只声明支持到剪映 10.8；我们用剪映 11.0 自己写出的空草稿做骨架（align_with_template），
并由 tests/test_jianying_golden.py 固定生成结果的结构。本机剪映跨大版本时只提醒、不阻断（产品决策 D2）；
写进草稿的 platform.app_version 固定为已验证版本，不写探测值（产品决策 D3）。
"""
from __future__ import annotations

import plistlib
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 冻结版里是 _MEIPASS，spec 把模板放在 research/ 下
VERIFIED_VERSION = "11.0.0"     # 模板来源，也是写进草稿的 platform.app_version
VERIFIED_SERIES = "11.0"
TEMPLATE = ROOT / "research" / f"base_template_{VERIFIED_SERIES}.json"
APP_CANDIDATES = (Path("/Applications/VideoFusion-macOS.app"),
                  Path.home() / "Applications/VideoFusion-macOS.app")
BUNDLE_ID = "com.lemon.lvpro"   # 剪映专业版 Mac 的 bundle id（与 to_jianying 一致）
MDFIND_TIMEOUT_S = 3            # Spotlight 查询最多等几秒，超时当作没找到
MDFIND_QUERY = f"kMDItemCFBundleIdentifier == '{BUNDLE_ID}'"
APP_SUFFIX = ".app"
TRASH_DIR = ".Trash"            # 废纸篓里的旧安装不算「已安装」
APP_ROOTS = (Path("/Applications"), Path.home() / "Applications", Path("/System/Applications"))
# 只信任这些目录（按优先级）：Spotlight 也会返回 /Volumes、/private、下载目录里的同名 .app，不能拿去 open
BUNDLE_ID_KEY = "CFBundleIdentifier"
CACHE_S = 60                    # 检测结果缓存多少秒（每个 /api/state 轮询都会问，不能每次跑 mdfind）
INFO_PLIST = Path("Contents/Info.plist")
VERSION_KEY = "CFBundleShortVersionString"
TEMPLATE_MISSING = ("找不到剪映 {series} 草稿骨架模板：{path}"
                    "（安装包不完整，请重新安装；开发环境请检查 research/）")
MAJOR_MISMATCH = ("本机剪映版本 {found} 与已验证的 {major}.x 不同：草稿已通过静态校验，"
                  "若打开异常请导出诊断包反馈")


def _spotlight_apps(runner) -> list[Path]:
    """Spotlight 按 bundle id 找剪映（系统自带、只读、仅本机）；任何失败都当作没找到。"""
    try:
        res = runner(["mdfind", MDFIND_QUERY], capture_output=True, text=True,
                     timeout=MDFIND_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):  # 含超时、没有 mdfind、无权限
        return []
    if getattr(res, "returncode", 1) != 0:
        return []
    paths = (Path(line.strip()) for line in (res.stdout or "").splitlines() if line.strip())
    return [p for p in paths if p.suffix == APP_SUFFIX and TRASH_DIR not in p.parts]


def _root_rank(app: Path, roots) -> int | None:
    """app 解析符号链接后位于第几个可信目录；不在任何可信目录里 → None。"""
    try:
        real = Path(app).resolve()
    except (OSError, RuntimeError):
        return None
    for rank, root in enumerate(roots):
        try:
            if Path(root).resolve() in real.parents:
                return rank
        except (OSError, RuntimeError):
            continue
    return None


def _is_jianying(app: Path) -> bool:
    """真实目录，且 Info.plist 的 CFBundleIdentifier 就是剪映专业版。"""
    try:
        if not Path(app).is_dir():
            return False
        with open(Path(app) / INFO_PLIST, "rb") as f:
            return plistlib.load(f).get(BUNDLE_ID_KEY) == BUNDLE_ID
    except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
        return False


def _best(apps, roots) -> Path | None:
    ranked = [(rank, Path(a)) for a in apps if (rank := _root_rank(a, roots)) is not None and _is_jianying(a)]
    return min(ranked, key=lambda x: x[0])[1] if ranked else None  # min 稳定：同级取先出现的


def find_app(candidates=APP_CANDIDATES, runner=subprocess.run, roots=APP_ROOTS) -> Path | None:
    """本机剪映专业版的 .app 路径（KI-98）：先看固定位置，再用 Spotlight 按 bundle id 找；都没有 → None。

    不写死单一路径，但任何来源的路径都必须：解析符号链接后位于 roots（/Applications、~/Applications、
    /System/Applications）之内、是真实目录、Info.plist 的 bundle id 对得上；多个时优先靠前的目录。
    runner 可注入，测试不会碰真实系统。
    """
    return _best(candidates, roots) or _best(_spotlight_apps(runner), roots)


_CACHE: dict[str, object] = {"at": None, "value": None}


def reset_cache() -> None:
    _CACHE.update(at=None, value=None)


def cached_find(*, refresh: bool = False, now=time.monotonic) -> Path | None:
    """find_app() 的进程内缓存（含「没装」）CACHE_S 秒；refresh=True 强制重新检测（用户明确操作时用）。"""
    t = now()
    at = _CACHE["at"]
    if not refresh and at is not None and t - at < CACHE_S:
        return _CACHE["value"]
    value = find_app()
    _CACHE.update(at=t, value=value)
    return value


def installed_version(candidates=None) -> str | None:
    """读剪映 App 的 Info.plist；没装 / 读不了返回 None（剪映在不在由注册表检查负责）。

    不传 candidates：用 cached_find() 的结果（含 Spotlight，有缓存）；显式传候选路径时只看这些路径。
    """
    if candidates is None:
        located = cached_find()
        candidates = [located] if located else []
    for app in candidates:
        try:
            with open(Path(app) / INFO_PLIST, "rb") as f:
                v = plistlib.load(f).get(VERSION_KEY)
        except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
            continue
        if isinstance(v, str) and v:
            return v
    return None


def _major(v: str) -> int | None:
    head = v.split(".", 1)[0]
    return int(head) if head.isdigit() else None


def compat_warning(found: str | None) -> str | None:
    """本机剪映大版本与已验证版本不同 → 一条警告文案；相同 / 读不到 / 不认识 → None。"""
    if not found:
        return None
    major = _major(found)
    verified = _major(VERIFIED_VERSION)
    if major is None or major == verified:
        return None
    return MAJOR_MISMATCH.format(found=found, major=verified)
