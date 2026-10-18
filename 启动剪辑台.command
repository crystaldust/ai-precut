#!/bin/bash
# 双击这个文件启动「剪辑台」。关掉终端窗口就退出。
cd "$(dirname "$0")" || exit 1

PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "找不到 python3，请先安装 Python 3（或联系开发者）。"
  read -r -p "按回车关闭…" _
  exit 1
fi

echo "正在启动剪辑台…（第一次启动稍慢）"
exec "$PY" gui/server.py --open
