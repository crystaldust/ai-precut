#!/bin/bash
# 双击这个文件启动「剪辑台」。关掉终端窗口就退出。
# 一律走 uv（KI-34）：用 uv.lock 锁定的依赖和 Python 3.12，不回落到系统自带的 Python。
cd "$(dirname "$0")" || exit 1

UV="$(command -v uv || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
fi
if [ -z "$UV" ]; then
  echo "找不到 uv：请先安装 uv（https://docs.astral.sh/uv/ ，终端里运行"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "），装好后再双击本文件。"
  read -r -p "按回车关闭…" _
  exit 1
fi

echo "正在启动剪辑台…（第一次启动要准备环境，稍慢）"
exec "$UV" run --locked --python 3.12 python gui/server.py --open
