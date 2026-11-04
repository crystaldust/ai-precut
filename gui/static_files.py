# -*- coding: utf-8 -*-
"""剪辑台对外提供的静态文件白名单（KI-52）与安装完整性自检。仅用标准库（pathlib）：server 与 packaging/ai-cut.spec 共用。

不在名单里的（如 prototype 生成物、编辑器临时文件）一律 404，打包时也不带。
M13：主页拆成多个聚焦脚本（每个 ≤ 400 行，tests/test_static_pages.py 守卫）；剪辑偏好并入新建 / 项目设置，
calibrate 页面删除。
missing_static：启动与发页面时核对白名单文件是否都在磁盘上（解压不完整时给出明确提示）。
"""
from pathlib import Path

STATIC_FILES = frozenset({
    "index.html", "app.css",
    "common.js", "platform.js", "base.js", "jobs.js", "settings.js", "support.js", "sidebar.js", "wizard.js",
    "shortcuts.js", "cliplist.js",
    "project-form.js", "step-analyze.js", "step-browse.js", "batch-select.js", "segment-edit.js", "step-criteria.js",
    "criteria-analysis.js", "criteria-pending.js",
    "reselect.js", "result-table.js", "result-unused.js", "step-result.js", "step-export.js", "export-compare.js", "simple-mode.js", "app.js", "main.js",
})


def missing_static(root: Path) -> list[str]:
    """白名单里在 root 下不是普通文件的名字（缺失或被同名目录占位），按字母序。"""
    return sorted(name for name in STATIC_FILES if not (root / name).is_file())
