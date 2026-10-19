#!/usr/bin/env bash
# 构建 macOS App：AI粗剪.app
#   ./packaging/build_app.sh
# 产物：dist/AI粗剪.app + dist/THIRD-PARTY-NOTICES.txt + dist/首次打开说明-macOS.txt + dist/sources/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ffmpeg/ffprobe：从钉死 SHA256 的源码自建 LGPL 版（GL-04）；已有产物也要过自检才复用
if [[ ! -x vendor/bin/ffmpeg ]] || ! ./packaging/build_ffmpeg.sh --verify-only; then
  echo "→ 构建 LGPL ffmpeg/ffprobe（首次约 5–10 分钟，需要 Xcode CLT 与 pkg-config）"
  rm -f vendor/bin/ffmpeg vendor/bin/ffprobe
  ./packaging/build_ffmpeg.sh
fi

echo "→ PyInstaller 构建"
uv run pyinstaller packaging/ai-cut.spec --noconfirm --clean

echo "→ 随包交付：第三方许可、首次打开说明、LGPL 对应源码"
cp packaging/THIRD-PARTY-NOTICES.txt "dist/THIRD-PARTY-NOTICES.txt"
cp "packaging/首次打开说明-macOS.txt" "dist/首次打开说明-macOS.txt"
./packaging/build_ffmpeg.sh --verify-sources   # 随包源码必须与内置二进制、NOTICES 同一版本
rm -rf dist/sources && mkdir -p dist/sources
cp vendor/sources/*.tar.xz packaging/build_ffmpeg.sh dist/sources/

echo
echo "完成：$ROOT/dist/AI粗剪.app"
echo "打开：open \"$ROOT/dist/AI粗剪.app\""
