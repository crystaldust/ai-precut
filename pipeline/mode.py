# -*- coding: utf-8 -*-
"""出片模式（简单模式）：按项目存进 project.json 的 mode 字段。

full  = 完整流程（①–⑥，④ 定标准决定选段）；
simple = 简单模式：③ 放进剪辑列表的片段就是成片，跳过 ④，⑤ 的分镜表只含剪辑列表里的片段。
读到不认识的值一律按 full（和 vision.normalize 同一思路）；改模式让 ⑤ 标「需要更新」（进选段输入指纹）。
"""
from __future__ import annotations

FULL = "full"
SIMPLE = "simple"
MODES = (FULL, SIMPLE)
DEFAULT = FULL  # 与 schema.DEFAULTS["mode"] 一致（测试锁定）
BAD_MODE_MSG = "出片模式不对：只能是完整（full）或简单（simple）"


def normalize(raw: object) -> str:
    return raw if isinstance(raw, str) and raw in MODES else DEFAULT


def is_simple(cfg: object) -> bool:
    return isinstance(cfg, dict) and normalize(cfg.get("mode")) == SIMPLE


def check(raw: object) -> str:
    """接口 / 命令行入参校验：必须恰好是 MODES 里的字符串；不合法抛 ValueError。"""
    if not isinstance(raw, str) or raw not in MODES:
        raise ValueError(BAD_MODE_MSG)
    return raw
