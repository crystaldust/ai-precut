# -*- coding: utf-8 -*-
"""剪映版本的唯一来源（KI-17）：已验证版本、对应的草稿骨架模板、读取本机已装剪映的版本。

pyJianYingDraft 0.3.1 只声明支持到剪映 10.8；我们用剪映 11.0 自己写出的空草稿做骨架（align_with_template），
并由 tests/test_jianying_golden.py 固定生成结果的结构。本机剪映跨大版本时只提醒、不阻断（产品决策 D2）；
写进草稿的 platform.app_version 固定为已验证版本，不写探测值（产品决策 D3）。
"""
from __future__ import annotations

import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # 冻结版里是 _MEIPASS，spec 把模板放在 research/ 下
VERIFIED_VERSION = "11.0.0"     # 模板来源，也是写进草稿的 platform.app_version
VERIFIED_SERIES = "11.0"
TEMPLATE = ROOT / "research" / f"base_template_{VERIFIED_SERIES}.json"
APP_CANDIDATES = (Path("/Applications/VideoFusion-macOS.app"),
                  Path.home() / "Applications/VideoFusion-macOS.app")
INFO_PLIST = Path("Contents/Info.plist")
VERSION_KEY = "CFBundleShortVersionString"
TEMPLATE_MISSING = ("找不到剪映 {series} 草稿骨架模板：{path}"
                    "（安装包不完整，请重新安装；开发环境请检查 research/）")
MAJOR_MISMATCH = ("本机剪映版本 {found} 与已验证的 {major}.x 不同：草稿已通过静态校验，"
                  "若打开异常请导出诊断包反馈")


def installed_version(candidates=APP_CANDIDATES) -> str | None:
    """读剪映 App 的 Info.plist；没装 / 读不了返回 None（剪映在不在由注册表检查负责）。"""
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
