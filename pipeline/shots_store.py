# -*- coding: utf-8 -*-
"""手动分镜表 shots.json 的读改写互斥。

剪辑台是多线程服务：「保存分镜表」和「标记不可用时移除重叠镜头」都会整体重写 shots.json，
不串行的话后写的会丢掉先写的修改（丢更新）。两条路径都必须在 LOCK 内完成读-改-写。
"""
from __future__ import annotations

import threading

LOCK = threading.Lock()
