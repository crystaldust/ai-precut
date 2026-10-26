# -*- coding: utf-8 -*-
"""每个编码路径（代理 / 切片 / 纪录片切镜 / 预览）都用「预检验证过」的编码器，而不是未验证的首个候选。
切片和预览可能跑在独立子进程里（没经过 cmd_prepare 的预检），所以 encode.encoder() 自己懒预检。"""
import argparse
import threading
from pathlib import Path

import pytest

from pipeline import build_documentary, clips, encode, media_io, plat
from pipeline import render_preview as rp
from platform_marks import WIN_ONLY


@pytest.fixture
def second_candidate(monkeypatch):
    """Windows 候选：h264_mf 失败、libopenh264 成功；缓存清空（模拟全新进程）。返回预检探测记录。"""
    monkeypatch.setattr(encode.sys, "platform", "win32")
    monkeypatch.setattr(encode, "_PREFLIGHT", {})
    probed = []

    def fake_try(enc, runner):
        probed.append(enc)
        return "no h264_mf" if enc == "h264_mf" else None
    monkeypatch.setattr(encode, "_try", fake_try)
    return probed


def _capture_ffmpeg(monkeypatch):
    seen = []

    def run(args, **kw):
        seen.append(list(args))
        Path(args[-1]).write_bytes(b"full")
    monkeypatch.setattr(media_io, "run_ffmpeg", run)
    return seen


def _codec(args):
    return args[args.index("-c:v") + 1]


def test_cut_clip_uses_verified_encoder(second_candidate, monkeypatch, tmp_path):
    seen = _capture_ffmpeg(monkeypatch)
    clips.cut_clip(tmp_path / "c.mp4", tmp_path / "s.mp4", {"in": 0.0, "out": 1.0})
    assert _codec(seen[0]) == "libopenh264" and second_candidate == ["h264_mf", "libopenh264"]


def test_cut_shot_uses_verified_encoder(second_candidate, monkeypatch, tmp_path):
    seen = _capture_ffmpeg(monkeypatch)
    build_documentary.cut_shot(tmp_path / "s.mp4", tmp_path / "c.mp4", 0.0, 1.0)
    assert _codec(seen[0]) == "libopenh264"


def test_render_preview_uses_verified_encoder(second_candidate, monkeypatch, tmp_path):
    import json
    from test_render_preview import tl
    seen = _capture_ffmpeg(monkeypatch)
    monkeypatch.setattr(media_io, "has_audio", lambda p, **kw: True)
    tl_file = tmp_path / "t.json"
    tl_file.write_text(json.dumps(tl()), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["render_preview", str(tl_file), "-o", str(tmp_path / "o.mp4")])
    rp.main()
    assert _codec(seen[0]) == "libopenh264"


def test_proxy_uses_verified_encoder(second_candidate, monkeypatch, tmp_path):
    import aicut
    from test_aicut_cli import _project
    seen = _capture_ffmpeg(monkeypatch)
    monkeypatch.setattr(aicut, "PROJECTS", tmp_path)
    monkeypatch.setattr(aicut, "_run_pipeline", lambda *a: None)
    _project(tmp_path)
    aicut.cmd_junk(argparse.Namespace(name="p1"))
    assert _codec(seen[0]) == "libopenh264"


def test_probe_runs_once_per_process(second_candidate):
    encode.h264_args("clip")
    encode.h264_args("proxy")
    assert second_candidate == ["h264_mf", "libopenh264"]


def test_unavailable_encoder_raises_media_error_with_platform_text(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "win32")
    monkeypatch.setattr(encode, "_PREFLIGHT", {})
    monkeypatch.setattr(encode, "_try", lambda enc, runner: "boom")
    with pytest.raises(media_io.MediaError) as exc:
        encode.h264_args("clip")
    assert str(exc.value) == encode.ENCODER_UNAVAILABLE_WIN.format(detail="boom")


def test_failure_is_not_cached_and_success_is(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "darwin")
    monkeypatch.setattr(encode, "_PREFLIGHT", {})
    results = iter(["boom", None])
    calls = []
    monkeypatch.setattr(encode, "_try", lambda enc, runner: calls.append(enc) or next(results))
    assert encode.preflight().startswith("本机无法使用 VideoToolbox")
    assert encode.preflight() is None and encode.preflight() is None
    assert calls == ["h264_videotoolbox"] * 2 and encode.encoder() == "h264_videotoolbox"


def test_preflight_is_thread_safe(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "darwin")
    monkeypatch.setattr(encode, "_PREFLIGHT", {})
    calls = []
    monkeypatch.setattr(encode, "_try", lambda enc, runner: calls.append(enc))
    threads = [threading.Thread(target=encode.encoder) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert calls == ["h264_videotoolbox"]


def test_mac_lazy_probe_does_not_change_command_line(monkeypatch):
    monkeypatch.setattr(encode.sys, "platform", "darwin")
    monkeypatch.setattr(encode, "_PREFLIGHT", {})
    monkeypatch.setattr(encode, "_try", lambda enc, runner: None)
    assert encode.h264_args("clip") == ["-c:v", "h264_videotoolbox", "-b:v", "12M", "-profile:v", "high",
                                        "-allow_sw", "1", "-pix_fmt", "yuv420p"]


# ---------------------------------------------------------------- Windows CI：真 ffmpeg + 带空格的临时目录
@WIN_ONLY
def test_real_render_with_chinese_text_in_temp_dir_with_space(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess
    if shutil.which("ffmpeg") is None:
        pytest.skip("本机无 ffmpeg")
    spaced = tmp_path / "a b"
    spaced.mkdir()
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: str(spaced))
    monkeypatch.setenv("PUBLIC", str(tmp_path / "Public"))
    base = Path(rp.text_dir_base())
    assert base != spaced and base.is_dir()  # 带空格 → 退回 %PUBLIC%\Documents\aicut-tmp
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x240:r=30:d=1", "-t", "1", "-c:v", "mpeg4", str(src)], check=True)
    timeline = {"project": {"width": 320, "height": 240, "fps": 30},
                "video": [{"source": str(src), "in": 0.0, "out": 1.0, "timeline_in": 0.0}],
                "text": [{"text": "中文字幕测试", "start": 0.0, "end": 1.0, "style": {"align": 2}}]}
    tl_file = tmp_path / "t.json"
    tl_file.write_text(json.dumps(timeline, ensure_ascii=False), encoding="utf-8")
    from pipeline import proc
    out = tmp_path / "o.mp4"
    code, log = proc.run_inprocess("pipeline.render_preview", [str(tl_file), "-o", str(out)])
    assert code == 0, log
    assert out.stat().st_size > 0
