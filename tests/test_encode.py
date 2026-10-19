"""H.264 编码参数（GL-04）：一律 VideoToolbox，码率显式，全仓不再出现 libx264。"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import encode, media_io

ROOT = Path(__file__).resolve().parent.parent
CODE = [ROOT / "aicut.py", *sorted((ROOT / "pipeline").glob("*.py")),
        *sorted((ROOT / "gui").glob("*.py")), ROOT / "app" / "main.py"]


@pytest.mark.parametrize("kind,rate", [("proxy", "1500k"), ("clip", "12M"), ("preview", "8M")])
def test_h264_args_use_videotoolbox_with_explicit_bitrate(kind, rate):
    args = encode.h264_args(kind)
    assert args[args.index("-c:v") + 1] == "h264_videotoolbox"
    assert args[args.index("-b:v") + 1] == rate
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-allow_sw") + 1] == "1"
    assert "-crf" not in args and "-preset" not in args


def test_bitrates_are_named_constants():
    assert encode.BITRATES == {"proxy": encode.PROXY_BITRATE, "clip": encode.CLIP_BITRATE,
                               "preview": encode.PREVIEW_BITRATE}


def test_h264_args_returns_fresh_list():
    a = encode.h264_args("clip")
    a.append("x")
    assert "x" not in encode.h264_args("clip")


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        encode.h264_args("nope")


def test_no_libx264_anywhere_in_code():
    hits = [str(p) for p in CODE if re.search(r"libx26[45]", p.read_text(encoding="utf-8"))]
    assert hits == []


def test_callers_use_encode_module():
    for rel in ("aicut.py", "pipeline/render_preview.py", "pipeline/build_documentary.py"):
        assert "encode.h264_args(" in (ROOT / rel).read_text(encoding="utf-8"), rel


def _has_vt() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                         text=True).stdout
    return "h264_videotoolbox" in out


@pytest.mark.skipif(not _has_vt(), reason="需要带 h264_videotoolbox 的 ffmpeg")
def test_real_encode_one_second_through_media_io(tmp_path):
    dst = tmp_path / "o.mp4"
    media_io.ffmpeg_to(dst, ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=1",
                             *encode.h264_args("proxy")])
    assert media_io.is_complete(dst) and dst.stat().st_size > 0


def test_test_fixtures_do_not_need_x264():
    # 开发机 / CI 若只有 LGPL ffmpeg（无 x264），夹具也必须能生成样片
    for p in sorted((ROOT / "tests").glob("test_*.py")):
        if p.name in ("test_encode.py", "test_packaging.py"):
            continue  # 这两个文件里的 libx264 是守卫断言本身
        assert not re.search(r"[\"']libx26[45][\"']", p.read_text(encoding="utf-8")), p.name
