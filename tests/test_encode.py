"""H.264 编码参数（GL-04）：Mac VideoToolbox / Windows h264_mf、libopenh264，码率显式，全仓不再出现 libx264。"""
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
def test_h264_args_use_platform_encoder_with_explicit_bitrate(kind, rate):
    args = encode.h264_args(kind)
    assert args[args.index("-c:v") + 1] == encode.candidates()[0]
    assert args[args.index("-b:v") + 1] == rate
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "-crf" not in args and "-preset" not in args


@pytest.mark.parametrize("kind,rate", [("proxy", "1500k"), ("clip", "12M"), ("preview", "8M")])
def test_mac_command_line_is_byte_identical(monkeypatch, kind, rate):
    monkeypatch.setattr(encode.sys, "platform", "darwin")
    assert encode.h264_args(kind) == ["-c:v", "h264_videotoolbox", "-b:v", rate, "-profile:v", "high",
                                      "-allow_sw", "1", "-pix_fmt", "yuv420p"]


def test_windows_encoder_args(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "win32")
    assert encode.ENCODERS["win32"] == ["h264_mf", "libopenh264"]
    assert encode.h264_args("clip") == ["-c:v", "h264_mf", "-b:v", "12M", "-profile:v", "100",
                                        "-pix_fmt", "yuv420p"]
    assert encode.h264_args("clip", "libopenh264") == ["-c:v", "libopenh264", "-b:v", "12M",
                                                       "-profile:v", "high", "-pix_fmt", "yuv420p"]


def test_linux_falls_back_to_mac_candidates(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "linux")
    assert encode.candidates() == ["h264_videotoolbox"]


def test_chosen_encoder_is_used_by_h264_args(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "win32")
    monkeypatch.setattr(encode, "_PREFLIGHT", {"result": None, "encoder": "libopenh264"})
    assert encode.h264_args("proxy")[1] == "libopenh264"


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


def _available_encoder() -> str | None:
    """本平台候选里 ffmpeg -encoders 能看到的第一个。"""
    if shutil.which("ffmpeg") is None:
        return None
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                         text=True).stdout
    return next((e for e in encode.candidates() if f" {e} " in out), None)


@pytest.mark.skipif(_available_encoder() is None, reason="需要带本平台候选 H.264 编码器的 ffmpeg")
def test_real_encode_one_second_through_media_io(tmp_path, monkeypatch):
    monkeypatch.setitem(encode._PREFLIGHT, "encoder", _available_encoder())
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
