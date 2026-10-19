#!/usr/bin/env bash
# 从源码构建 LGPL 静态 ffmpeg/ffprobe（arm64），供 build_app.sh 打包（GL-04）。
#   ./packaging/build_ffmpeg.sh               下载（SHA256 钉死）→ 编译 → 自检
#   ./packaging/build_ffmpeg.sh --verify-only 只对已有产物跑自检（版本 / LGPL / 链接库 / 编码器 / 滤镜）
#   ./packaging/build_ffmpeg.sh --verify-sources 只核对 sources/ 下的源码包齐全且哈希正确（打 dist 前用）
# 不启用 GPL / nonfree；H.264 编码只用 VideoToolbox；drawtext 需要 FreeType（选 FTL 许可）
# 与 HarfBuzz（Old MIT，FFmpeg 8.x 起为 drawtext 硬依赖，经 hb-ft.h 使用 FreeType）。
# 产物目录可用 AICUT_FFMPEG_OUT 覆盖（默认 vendor/：bin/ licenses/ sources/），
# 中间目录可用 AICUT_FFMPEG_WORK 覆盖（默认 build/ffmpeg）。
# 构建机需要 Xcode Command Line Tools（clang/make/otool）、pkg-config 与 cmake；用户机器不需要。
set -euo pipefail

FFMPEG_VER=8.1.3
FFMPEG_SHA256=7138d28c96d9d3e3af4ee3d8cad72741f8ffb40da90c1112235dea3ecd3178a3
FREETYPE_VER=2.14.3
FREETYPE_SHA256=36bc4f1cc413335368ee656c42afca65c5a3987e8768cc28cf11ba775e785a5f
# HarfBuzz：GitHub 官方 release 资产；哈希与 GitHub 发布的 asset digest 一致（2026-10-19 核对）
HARFBUZZ_VER=14.6.0
HARFBUZZ_SHA256=d07a007327277708a2a73ae437887cdbaf282937f6d03ca5467723e9099af586
FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz"
FREETYPE_URL="https://download.savannah.gnu.org/releases/freetype/freetype-$FREETYPE_VER.tar.xz"
HARFBUZZ_URL="https://github.com/harfbuzz/harfbuzz/releases/download/$HARFBUZZ_VER/harfbuzz-$HARFBUZZ_VER.tar.xz"
# 代码里用到的能力（aicut.py / pipeline/*.py）；少一个就不让打包
REQUIRED_ENCODERS="h264_videotoolbox aac pcm_s16le rawvideo"
REQUIRED_LIBS="libfreetype libharfbuzz"        # buildconf 里必须出现的 --enable-<lib>
REQUIRED_FILTERS="drawtext scdet blackdetect freezedetect silencedetect concat scale pad setsar fps trim setpts atrim asetpts aresample format anullsrc aformat"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${AICUT_FFMPEG_OUT:-$ROOT/vendor}"
WORK="${AICUT_FFMPEG_WORK:-$ROOT/build/ffmpeg}"
SRC="$OUT/sources"; BIN="$OUT/bin"; LIC="$OUT/licenses"; PREFIX="$WORK/prefix"
export MACOSX_DEPLOYMENT_TARGET=11.0          # 与 ai-cut.spec 的 LSMinimumSystemVersion 一致

die() { echo "✗ $*" >&2; exit 1; }

verify() {  # 收集全部问题一次报完；有任何一条不过就 exit 1
  local ff="$BIN/ffmpeg" fp="$BIN/ffprobe" bad=0 b x
  [[ -x "$ff" && -x "$fp" ]] || die "缺少 ${ff} 或 ${fp}"
  # 先收进变量再 grep：管道里 grep -q 提前退出会让 ffmpeg 吃 SIGPIPE，pipefail 下误判失败
  local license buildconf encoders filters version links
  version="$("$ff" -hide_banner -version | head -n 1 || true)"
  [[ "$version" == "ffmpeg version $FFMPEG_VER "* ]] \
    || { echo "✗ 版本不符：期望 ${FFMPEG_VER}，实际「${version}」（与随包源码 / NOTICES 不一致）"; bad=1; }
  license="$("$ff" -hide_banner -L)"            # 原文 "GNU Lesser General Public\nLicense" 跨行
  buildconf="$("$ff" -hide_banner -buildconf)"
  grep -q "GNU Lesser General Public" <<<"$license" || { echo "✗ 不是 LGPL 构建"; bad=1; }
  if grep -Eq "enable-gpl|enable-nonfree|libx26[45]" <<<"$buildconf"; then
    echo "✗ 含 GPL/nonfree 组件"; bad=1
  fi
  for x in $REQUIRED_LIBS; do
    grep -q -- "--enable-$x" <<<"$buildconf" || { echo "✗ 未启用 ${x}"; bad=1; }
  done
  encoders="$("$ff" -hide_banner -encoders)"
  filters="$("$ff" -hide_banner -filters)"
  for x in $REQUIRED_ENCODERS; do
    grep -Eq "^ [A-Z.]{6} $x " <<<"$encoders" || { echo "✗ 缺编码器 ${x}"; bad=1; }
  done
  for x in $REQUIRED_FILTERS; do
    grep -Eq "^ [A-Z.]{2,3} +$x " <<<"$filters" || { echo "✗ 缺滤镜 ${x}"; bad=1; }
  done
  for b in "$ff" "$fp"; do
    if ! links="$(otool -L "$b")"; then           # otool 失败不能当作「没有非系统库」
      echo "✗ 无法检查 ${b} 的链接库"; bad=1
    elif tail -n +2 <<<"$links" | grep -vE "^[[:space:]]+(/System/Library/|/usr/lib/)"; then
      echo "✗ ${b} 链接了非系统库（见上）"; bad=1
    fi
  done
  [[ $bad -eq 0 ]] || die "自检未通过"
  mkdir -p "$LIC"
  # 随包的 configure 行去掉构建机绝对路径
  sed -E 's#--prefix=[^[:space:]]+#--prefix=<build-prefix>#' <<<"$buildconf" > "$LIC/ffmpeg-buildconf.txt"
  echo "✓ 自检通过：LGPL、仅系统库、FreeType + HarfBuzz、h264_videotoolbox 与所需滤镜齐全"
}

verify_sources() {  # dist/sources 必须与 NOTICES、二进制同一版本：缺包或哈希不符都不许打包
  local bad=0 name sum
  while read -r name sum; do
    if [[ ! -f "$SRC/$name" ]]; then echo "✗ 缺源码包 ${name}"; bad=1; continue; fi
    echo "$sum  $SRC/$name" | shasum -a 256 -c - >/dev/null 2>&1 \
      || { echo "✗ 源码包哈希不符：${name}"; bad=1; }
  done <<EOF_SOURCES
ffmpeg-$FFMPEG_VER.tar.xz $FFMPEG_SHA256
freetype-$FREETYPE_VER.tar.xz $FREETYPE_SHA256
harfbuzz-$HARFBUZZ_VER.tar.xz $HARFBUZZ_SHA256
EOF_SOURCES
  [[ $bad -eq 0 ]] || die "源码包核对未通过（${SRC}）"
  echo "✓ 源码包齐全且哈希正确"
}

if [[ "${1:-}" == "--verify-only" ]]; then verify; exit 0; fi
if [[ "${1:-}" == "--verify-sources" ]]; then verify_sources; exit 0; fi

for tool in clang make pkg-config cmake curl shasum tar otool; do
  command -v "$tool" >/dev/null || die "构建机缺少 ${tool}（Xcode CLT：xcode-select --install；pkg-config / cmake：brew install pkg-config cmake）"
done

mkdir -p "$SRC" "$WORK" "$BIN" "$LIC"

fetch() {  # url file sha256 —— 哈希不符即删文件退出
  local url=$1 out="$SRC/$2" sum=$3
  if [[ ! -f "$out" ]]; then
    echo "→ 下载 ${2}"
    curl -fsSL --retry 3 -o "$out.part" "$url"   # 失败时 set -e 在这里停，退出码就是 curl 的
    mv "$out.part" "$out"
  fi
  echo "$sum  $out" | shasum -a 256 -c - >/dev/null || { rm -f "$out"; die "校验失败：${2}"; }
}
fetch "$FFMPEG_URL" "ffmpeg-$FFMPEG_VER.tar.xz" "$FFMPEG_SHA256"
fetch "$FREETYPE_URL" "freetype-$FREETYPE_VER.tar.xz" "$FREETYPE_SHA256"
fetch "$HARFBUZZ_URL" "harfbuzz-$HARFBUZZ_VER.tar.xz" "$HARFBUZZ_SHA256"

rm -rf "$WORK/src" "$WORK/harfbuzz-build" "$PREFIX"
mkdir -p "$WORK/src"
tar -xf "$SRC/freetype-$FREETYPE_VER.tar.xz" -C "$WORK/src"
tar -xf "$SRC/harfbuzz-$HARFBUZZ_VER.tar.xz" -C "$WORK/src"
tar -xf "$SRC/ffmpeg-$FFMPEG_VER.tar.xz" -C "$WORK/src"
JOBS="$(sysctl -n hw.ncpu)"

echo "→ 编译 FreeType ${FREETYPE_VER}（静态，不带 png/harfbuzz/brotli/bzip2，用内置 zlib）"
( cd "$WORK/src/freetype-$FREETYPE_VER"
  ./configure --prefix="$PREFIX" --enable-static --disable-shared \
    --with-png=no --with-harfbuzz=no --with-brotli=no --with-bzip2=no --with-zlib=no
  make -j"$JOBS"
  make install )

echo "→ 编译 HarfBuzz ${HARFBUZZ_VER}（静态，只接自建 FreeType；glib/icu/cairo/graphite/CoreText 全关）"
cmake -S "$WORK/src/harfbuzz-$HARFBUZZ_VER" -B "$WORK/harfbuzz-build" -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET="$MACOSX_DEPLOYMENT_TARGET" \
  -DCMAKE_IGNORE_PREFIX_PATH="/opt/homebrew;/usr/local" -DCMAKE_FIND_FRAMEWORK=NEVER \
  -DBUILD_SHARED_LIBS=OFF -DHB_HAVE_FREETYPE=ON \
  -DFREETYPE_LIBRARY="$PREFIX/lib/libfreetype.a" \
  -DFREETYPE_INCLUDE_DIR_ft2build="$PREFIX/include/freetype2" \
  -DFREETYPE_INCLUDE_DIR_freetype2="$PREFIX/include/freetype2" \
  -DHB_HAVE_GLIB=OFF -DHB_HAVE_ICU=OFF -DHB_HAVE_CAIRO=OFF -DHB_HAVE_GRAPHITE2=OFF \
  -DHB_HAVE_GOBJECT=OFF -DHB_HAVE_INTROSPECTION=OFF -DHB_HAVE_CORETEXT=OFF \
  -DHB_BUILD_UTILS=OFF -DHB_BUILD_SUBSET=OFF -DHB_BUILD_RASTER=OFF -DHB_BUILD_VECTOR=OFF \
  -DHB_BUILD_GPU=OFF
cmake --build "$WORK/harfbuzz-build" -j"$JOBS"
cmake --install "$WORK/harfbuzz-build"

echo "→ 编译 FFmpeg ${FFMPEG_VER}（LGPL，--disable-autodetect 防止链接 Homebrew 动态库）"
( cd "$WORK/src/ffmpeg-$FFMPEG_VER"
  PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig" PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig" \
  ./configure --prefix="$PREFIX" \
    --arch=arm64 --cc=clang --pkg-config-flags=--static \
    --enable-static --disable-shared --disable-debug --disable-doc --disable-ffplay \
    --disable-network --disable-autodetect \
    --enable-videotoolbox --enable-audiotoolbox --enable-zlib --enable-libfreetype --enable-libharfbuzz
  make -j"$JOBS"
  make install )

cp "$WORK/src/ffmpeg-$FFMPEG_VER/COPYING.LGPLv2.1" "$LIC/FFmpeg-COPYING.LGPLv2.1"
cp "$WORK/src/freetype-$FREETYPE_VER/docs/FTL.TXT" "$LIC/FreeType-FTL.TXT"
cp "$WORK/src/harfbuzz-$HARFBUZZ_VER/COPYING" "$LIC/HarfBuzz-COPYING"
install -m 755 "$PREFIX/bin/ffmpeg" "$PREFIX/bin/ffprobe" "$BIN/"
verify
