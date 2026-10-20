# -*- coding: utf-8 -*-
"""剪辑台对外提供的静态文件白名单（KI-52）。零依赖：server 与 packaging/ai-cut.spec 共用。

不在名单里的（如 prototype 生成物、编辑器临时文件）一律 404，打包时也不带。
M13：主页拆成多个聚焦脚本（每个 ≤ 400 行，tests/test_static_pages.py 守卫）；剪辑偏好并入新建 / 项目设置，
calibrate 页面删除。
"""
STATIC_FILES = frozenset({
    "index.html", "app.css",
    "common.js", "base.js", "jobs.js", "settings.js", "support.js", "sidebar.js", "wizard.js",
    "shortcuts.js", "cliplist.js",
    "project-form.js", "step-analyze.js", "step-browse.js", "step-criteria.js",
    "criteria-analysis.js", "criteria-pending.js",
    "reselect.js", "result-table.js", "result-unused.js", "step-result.js", "step-export.js", "app.js", "main.js",
})
