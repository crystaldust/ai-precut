# -*- coding: utf-8 -*-
"""剪辑台对外提供的静态文件白名单（KI-52）。零依赖：server 与 packaging/ai-cut.spec 共用。

不在名单里的（如 prototype 生成物、编辑器临时文件）一律 404，打包时也不带。
"""
STATIC_FILES = frozenset({
    "index.html", "browse.html", "calibrate.html", "confirm.html",
    "common.js", "jobs.js", "settings.js", "support.js",
    "index.js", "browse.js", "confirm.js", "calibrate.js",
})
