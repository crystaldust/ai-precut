# -*- coding: utf-8 -*-
"""话题显示名（M13 P3 / D19）：只改界面上看到的名字，不影响剪法。

话题名同时是决策问题选项、must_topics / exclude_topics 规则的匹配键（select 模糊匹配），
所以改名只存 work/topic_names.json {原名: 新名}，③④⑤ 显示新名；选段、答案、规则仍按原名匹配，
segments_scored.json 等算法输入一律不动。
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from pipeline import schema

FILENAME = "topic_names.json"
DISPLAY_MAX = 20  # 显示名最多这么多字


def _path(workdir: Path) -> Path:
    return Path(workdir) / FILENAME


def load(workdir: Path) -> dict[str, str]:
    """只用于显示：缺失 / 损坏 / 条目不是文字都当没有（损坏时改名接口会 409，不会覆盖）。"""
    data = schema.read_json_lenient(_path(workdir), {})
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


class NameTaken(ValueError):
    """显示名和别的话题（原名或显示名）重名。"""


def _key(text: str) -> str:
    """重名比较用：NFKC 归一（全角 / 半角、兼容字符视为同一个），再去掉大小写差异。"""
    return unicodedata.normalize("NFKC", text).casefold()


def rename(workdir: Path, raw: str, display: str, *, other_topics: tuple[str, ...] = ()) -> dict[str, str]:
    """加锁读改写；display 为空 = 恢复原名。损坏的文件抛 CorruptJSON（不覆盖）。返回新的映射。

    重名检查在锁内的回调里做（other_topics = 其它话题的原名），与写入之间不会被别人插队。
    """
    def mutate(current: dict) -> dict:
        kept = {k: v for k, v in current.items() if k != raw and isinstance(v, str)}
        taken = {_key(x) for x in (*other_topics, *kept.values())}
        if display and _key(display) in taken:
            raise NameTaken(display)
        return {**kept, raw: display} if display else kept

    return schema.update(_path(workdir), mutate)


def display(name: str | None, mapping: dict[str, str]) -> str | None:
    return mapping.get(name, name) if name else name
