# -*- coding: utf-8 -*-
"""测试平台标记（M16）：只有确属某平台语义的用例才用，并且必须写明理由，不许拿 skip 掩盖产品缺陷。"""
import sys

import pytest

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX 语义（进程组 / 信号 / ps）")
WIN_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows 语义（Job Object / kernel32）")


def posix_only(reason: str):
    """带具体理由的 POSIX_ONLY。"""
    return pytest.mark.skipif(sys.platform == "win32", reason=f"POSIX 语义：{reason}")


def win_only(reason: str):
    """带具体理由的 WIN_ONLY。"""
    return pytest.mark.skipif(sys.platform != "win32", reason=f"Windows 语义：{reason}")
