"""pipeline/render_preview：特殊字幕（KI-13/KI-76）、无音轨与声道统一（KI-14）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import proc
from pipeline import render_preview as rp

NASTY = ["it's, ok", "don't: stop 100%", "他说'好'%{pts}", "x\\y [a];b"]
STEREO_48K = "48000"


def tl(texts=(), n=1, sources=None):
    srcs = sources or [f"/m/{i}.mp4" for i in range(n)]
    return {"project": {"width": 320, "height": 240, "fps": 30},
            "video": [{"source": str(s), "in": 0.0, "out": 1.0, "timeline_in": float(i)}
                      for i, s in enumerate(srcs)],
            "text": [{"text": t, "start": 0.0, "end": 1.0, "style": {"align": 2}} for t in texts]}


# ---------------------------------------------------------------- 单元：滤镜图
def test_subtitle_files_keep_text_verbatim(tmp_path):
    paths = rp.subtitle_files(tl(NASTY)["text"], tmp_path)
    assert [p.read_text(encoding="utf-8") for p in paths] == NASTY   # 原样，无转义、无换行


def test_subtitle_files_empty_when_no_text(tmp_path):
    assert rp.subtitle_files([], tmp_path) == []


def test_build_uses_textfile_without_expansion(tmp_path):
    t = tl(NASTY)
    fc, _ = rp.build(t, text_paths=rp.subtitle_files(t["text"], tmp_path), has_audio=[True])
    assert "text='" not in fc and fc.count("expansion=none") == len(NASTY)
    assert all(s not in fc for s in NASTY)                          # 文字不进滤镜图


def test_build_without_text_has_no_drawtext():
    fc, n = rp.build(tl(n=2), text_paths=[], has_audio=[True, True])
    assert n == 2 and "drawtext" not in fc


def test_build_fills_silence_for_input_without_audio():
    fc, _ = rp.build(tl(n=2), text_paths=[], has_audio=[False, True])
    assert "[0:a]" not in fc and "anullsrc=r=48000:cl=stereo" in fc and "[1:a]" in fc
    assert fc.count("aformat=sample_rates=48000:channel_layouts=stereo") == 2


def test_text_dir_falls_back_when_tmp_has_filter_metachars(monkeypatch):
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "/var/x:y")
    assert rp.text_dir_base() == rp.FALLBACK_TMP


def test_text_dir_keeps_safe_tmp(monkeypatch):
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "/var/folders/ab/T")
    assert rp.text_dir_base() == "/var/folders/ab/T"


# ---------------------------------------------------------------- 集成：真 ffmpeg
def _ffmpeg_ready() -> bool:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return False
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                         text=True).stdout
    flt = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True,
                         text=True).stdout
    return "h264_videotoolbox" in enc and " drawtext " in flt and " anullsrc " in flt


def _make(path: Path, audio: list[str]) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30:d=1", *audio,
                    "-t", "1", "-c:v", "mpeg4", "-c:a", "aac", str(path)], check=True)
    return path


def _audio_streams(path: Path) -> list[str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=channel_layout,sample_rate",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def _private_text_dir(tmp_path, monkeypatch):
    d = tmp_path / "texts"
    d.mkdir()
    monkeypatch.setattr(rp, "text_dir_base", lambda: str(d))
    return d


@pytest.mark.skipif(not _ffmpeg_ready(), reason="需要带 VideoToolbox / drawtext / anullsrc 的 ffmpeg")
def test_real_render_with_nasty_text_and_mixed_audio(tmp_path, monkeypatch):
    silent = _make(tmp_path / "silent.mp4", [])
    mono = _make(tmp_path / "mono.mp4",
                 ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
                  "-ac", "1"])
    surround = _make(tmp_path / "surround.mp4",
                     ["-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                      "-af", "pan=5.1|c0=c0"])
    tl_file = tmp_path / "timeline.json"
    tl_file.write_text(json.dumps(tl(NASTY, sources=[silent, mono, surround]),
                                  ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "preview.mp4"
    texts = _private_text_dir(tmp_path, monkeypatch)
    code, log = proc.run_inprocess("pipeline.render_preview", [str(tl_file), "-o", str(out)])
    assert code == 0, log
    assert list(texts.iterdir()) == []                    # 字幕临时目录用完即删
    assert _audio_streams(out) == [f"stereo,{STEREO_48K}"] or \
        _audio_streams(out) == [f"{STEREO_48K},stereo"]


def test_missing_source_reports_render_failure(tmp_path):
    tl_file = tmp_path / "timeline.json"
    tl_file.write_text(json.dumps(tl(sources=[tmp_path / "nope.mp4"])), encoding="utf-8")
    code, log = proc.run_inprocess("pipeline.render_preview",
                                   [str(tl_file), "-o", str(tmp_path / "o.mp4")])
    assert code == 1 and "预览片渲染失败" in log


# ---------------------------------------------------------------- 审查修复 5 / 6：独立运行也原子写出；临时目录不残留
def _fake_media(monkeypatch, *, fail):
    seen = []

    def run(args, **kw):
        seen.append(args[-1])
        Path(args[-1]).write_bytes(b"half" if fail else b"full")
        if fail:
            raise rp.media_io.MediaError("ffmpeg 失败：boom")
    monkeypatch.setattr(rp.media_io, "has_audio", lambda p, **kw: True)
    monkeypatch.setattr(rp.media_io, "run_ffmpeg", run)
    return seen


def _render(tmp_path):
    tl_file = tmp_path / "timeline.json"
    tl_file.write_text(json.dumps(tl(NASTY)), encoding="utf-8")
    out = tmp_path / "out" / "o.mp4"
    out.parent.mkdir()
    return out, proc.run_inprocess("pipeline.render_preview", [str(tl_file), "-o", str(out)])


def _visible(d):
    """目录里的文件；空的 .aicut-partial/ 不算（审查修复 M4：atomic_output 不再 rmdir 它）。"""
    from pipeline import media_io
    part = d / media_io.PARTIAL_DIR
    assert not part.exists() or list(part.iterdir()) == []
    return sorted(p.name for p in d.iterdir() if p.name != media_io.PARTIAL_DIR)


def test_cli_writes_output_atomically(tmp_path, monkeypatch):
    seen = _fake_media(monkeypatch, fail=False)
    texts = _private_text_dir(tmp_path, monkeypatch)
    out, (code, log) = _render(tmp_path)
    assert code == 0, log
    assert seen[0] != str(out) and out.read_bytes() == b"full"
    assert _visible(out.parent) == ["o.mp4"]   # 无临时文件、无多余标记
    assert list(texts.iterdir()) == []


def test_cli_failure_leaves_no_half_file_or_temp_dir(tmp_path, monkeypatch):
    _fake_media(monkeypatch, fail=True)
    texts = _private_text_dir(tmp_path, monkeypatch)
    out, (code, log) = _render(tmp_path)
    assert code == 1 and "预览片渲染失败" in log
    assert _visible(out.parent) == [] and list(texts.iterdir()) == []


# ---------------------------------------------------------------- M6 · KI-73 预览字幕字体
def test_prefers_hiragino_sans_gb(tmp_path, monkeypatch):
    assert rp.FONT_CANDIDATES[0] == "/System/Library/Fonts/Hiragino Sans GB.ttc"
    second = tmp_path / "b.ttc"
    second.write_bytes(b"x")
    monkeypatch.setattr(rp, "FONT_CANDIDATES", [str(tmp_path / "missing.ttc"), str(second)])
    assert rp.pick_font() == str(second)


def test_build_uses_one_font_for_all_text(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rp, "pick_font", lambda: calls.append(1) or "/Fonts/Hiragino Sans GB.ttc")
    t = tl(["一", "二", "三"])
    fc, _ = rp.build(t, text_paths=rp.subtitle_files(t["text"], tmp_path), has_audio=[True])
    assert len(calls) == 1
    assert fc.count("fontfile='/Fonts/Hiragino Sans GB.ttc'") == 3


def test_no_font_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "FONT_CANDIDATES", [str(tmp_path / "none.ttc")])
    with pytest.raises(SystemExit):
        rp.pick_font()
