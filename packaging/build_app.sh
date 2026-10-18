#!/usr/bin/env bash
# 构建 macOS App：AI粗剪.app
#   ./packaging/build_app.sh
# 产物：dist/AI粗剪.app
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p vendor/bin
if [[ ! -x vendor/bin/ffmpeg ]]; then
  echo "→ 下载 ffmpeg/ffprobe（arm64 静态版，约 60MB）"
  curl -sL -o /tmp/ffmpeg.zip  https://www.osxexperts.net/ffmpeg7arm.zip
  curl -sL -o /tmp/ffprobe.zip https://www.osxexperts.net/ffprobe7arm.zip
  unzip -o -q /tmp/ffmpeg.zip  -d vendor/bin
  unzip -o -q /tmp/ffprobe.zip -d vendor/bin
  chmod +x vendor/bin/ffmpeg vendor/bin/ffprobe
fi

echo "→ PyInstaller 构建"
uv run pyinstaller packaging/ai-cut.spec --noconfirm --clean

echo
echo "完成：$ROOT/dist/AI粗剪.app"
echo "打开：open \"$ROOT/dist/AI粗剪.app\""
