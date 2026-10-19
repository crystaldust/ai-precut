"""打包与合规守卫（GL-01 / GL-04）：只读仓库文本，不构建、不联网。"""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_mediakit_cli_subprocess():
    src = _read("pipeline/cloud.py") + _read("aicut.py") + _read("pipeline/secrets.py")
    # 文档字符串里可以提协议出处，但不能再把它当命令名（字符串字面量）去调用
    assert not re.search(r"""["']mediakit-cli["']""", src)
    assert "import subprocess" not in _read("pipeline/cloud.py")
    assert "env_with_secret" not in src
    assert "mediakit_env" not in src and "MEDIAKIT_SURFACE" not in src


# ---------------------------------------------------------------- GL-04：第三方许可与 LGPL ffmpeg
NOT_ON_MAC = {"pythonnet", "pywin32-ctypes", "uiautomation", "comtypes", "clr-loader",
              "secretstorage", "jeepney", "cffi", "cryptography", "pycparser", "qtpy",
              "backports-tarfile", "importlib-metadata"}
NOTICES = "packaging/THIRD-PARTY-NOTICES.txt"


def _norm(s: str) -> str:
    return re.sub(r"[-_.]+", "-", s.lower())


def runtime_closure() -> set[str]:
    """uv.lock 里 ai-cut 运行时依赖在 macOS / Python 3.12 下的闭包（按名单排除别的平台）。"""
    lock = tomllib.loads(_read("uv.lock"))
    pk = {p["name"]: p for p in lock["package"]}
    todo = [d["name"] for d in pk["ai-cut"].get("dependencies", [])]
    seen: set[str] = set()
    while todo:
        n = todo.pop()
        if n in seen or n in NOT_ON_MAC:
            continue
        seen.add(n)
        todo += [d["name"] for d in pk[n].get("dependencies", [])]
    return seen


def test_runtime_closure_is_not_trivial():
    assert {"pywebview", "keyring", "pyjianyingdraft", "pymediainfo"} <= runtime_closure()


def test_notices_cover_every_runtime_dependency():
    text = _norm(_read(NOTICES))
    missing = sorted(n for n in runtime_closure() if _norm(n) not in text)
    assert missing == []


def test_notices_mention_ffmpeg_lgpl_freetype_and_python():
    text = _read(NOTICES)
    assert "FFmpeg" in text and "LGPL" in text and "ffmpeg-8.1.3.tar.xz" in text
    assert "The FreeType Project (www.freetype.org)" in text
    assert "Python Software Foundation" in text and "PyInstaller" in text


def test_ffmpeg_build_is_lgpl_and_pinned():
    sh = _read("packaging/build_ffmpeg.sh")
    assert "--enable-gpl" not in sh.replace('grep -Eq "enable-gpl', "")
    assert "--enable-nonfree" not in sh
    assert not re.search(r"--enable-libx26[45]", sh)
    assert "--disable-autodetect" in sh and "--enable-videotoolbox" in sh
    assert re.search(r"FFMPEG_SHA256=[0-9a-f]{64}\n", sh)
    assert re.search(r"FREETYPE_SHA256=[0-9a-f]{64}\n", sh)
    assert "shasum -a 256 -c" in sh and "curl -fsSL" in sh
    assert "--verify-only" in sh and "otool -L" in sh


def test_ffmpeg_build_checks_every_filter_and_encoder_the_code_uses():
    sh = _read("packaging/build_ffmpeg.sh")
    filters = re.search(r'REQUIRED_FILTERS="([^"]+)"', sh).group(1).split()
    encoders = re.search(r'REQUIRED_ENCODERS="([^"]+)"', sh).group(1).split()
    for f in ("drawtext", "scdet", "blackdetect", "freezedetect", "silencedetect", "concat"):
        assert f in filters
    assert {"h264_videotoolbox", "aac", "pcm_s16le"} <= set(encoders)


def test_build_app_has_no_unverified_download_and_ships_compliance_files():
    sh = _read("packaging/build_app.sh")
    assert "osxexperts" not in sh and "curl -sL" not in sh
    assert "build_ffmpeg.sh --verify-only" in sh
    assert "THIRD-PARTY-NOTICES.txt" in sh and "首次打开说明-macOS.txt" in sh
    assert "dist/sources" in sh


def test_spec_includes_new_modules_and_licenses():
    spec = _read("packaging/ai-cut.spec")
    for mod in ("pipeline.encode", "pipeline.applog", "pipeline.diagnostics"):
        assert f'"{mod}"' in spec
    assert "THIRD-PARTY-NOTICES.txt" in spec and '"licenses"' in spec


# ---------------------------------------------------------------- drawtext 需要 HarfBuzz（FFmpeg 8.x configure）
def test_ffmpeg_build_pins_and_enables_harfbuzz_statically():
    sh = _read("packaging/build_ffmpeg.sh")
    assert re.search(r"HARFBUZZ_SHA256=[0-9a-f]{64}\n", sh)
    assert "https://github.com/harfbuzz/harfbuzz/releases/download/" in sh
    assert "--enable-libharfbuzz" in sh and "--enable-libfreetype" in sh
    assert "-DBUILD_SHARED_LIBS=OFF" in sh
    for off in ("HB_HAVE_GLIB", "HB_HAVE_ICU", "HB_HAVE_CAIRO", "HB_HAVE_GRAPHITE2"):
        assert f"-D{off}=OFF" in sh
    assert "-DHB_HAVE_FREETYPE=ON" in sh  # vf_drawtext 用 hb-ft.h
    assert re.search(r"for tool in [^;]*cmake", sh)
    assert "HarfBuzz-COPYING" in sh


def test_notices_cover_harfbuzz_mit():
    text = _read(NOTICES)
    assert "HarfBuzz" in text and "Old MIT" in text and "harfbuzz-14.6.0.tar.xz" in text
    sh = _read("packaging/build_ffmpeg.sh")
    sha = re.search(r"HARFBUZZ_SHA256=([0-9a-f]{64})", sh).group(1)
    assert sha in text


# ---------------------------------------------------------------- M7：预览补静音轨用到的滤镜（KI-14）
def test_ffmpeg_build_checks_preview_audio_filters():
    sh = _read("packaging/build_ffmpeg.sh")
    filters = re.search(r'REQUIRED_FILTERS="([^"]+)"', sh).group(1).split()
    assert {"anullsrc", "aformat"} <= set(filters)


def test_spec_includes_jy_version():
    spec = _read("packaging/ai-cut.spec")
    for mod in ("pipeline.jy_version", "pipeline.jy_env", "pipeline.pyver"):
        assert f'"{mod}"' in spec, mod


def test_spec_ships_the_template_jy_version_expects():
    from pipeline import jy_version
    assert f'"{jy_version.TEMPLATE.name}"' in _read("packaging/ai-cut.spec")   # 版本常量漂移守卫（KI-17）
