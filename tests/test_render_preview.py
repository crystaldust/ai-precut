"""pipeline/render_preview：特殊字幕（KI-13/KI-76）、无音轨与声道统一（KI-14）。"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import encode, plat, proc
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
    monkeypatch.setattr(rp.plat, "IS_WIN", False)
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "/var/x:y")
    assert rp.text_dir_base() == rp.FALLBACK_TMP


def test_text_dir_keeps_safe_tmp(monkeypatch):
    monkeypatch.setattr(rp.plat, "IS_WIN", False)
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "/var/folders/ab/T")
    assert rp.text_dir_base() == "/var/folders/ab/T"


def test_windows_text_dir_keeps_ascii_temp(monkeypatch):
    monkeypatch.setattr(rp.plat, "IS_WIN", True)
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "C:\\Temp\\aicut")
    assert rp.text_dir_base() == "C:\\Temp\\aicut"


@pytest.mark.parametrize("temp", ["C:\\Users\\张三\\AppData\\Local\\Temp",
                                  "C:\\Users\\a b\\Temp"])
def test_windows_text_dir_falls_back_to_public_documents(monkeypatch, tmp_path, temp):
    monkeypatch.setattr(rp.plat, "IS_WIN", True)
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: temp)
    monkeypatch.setenv("PUBLIC", str(tmp_path / "Public"))
    got = Path(rp.text_dir_base())
    assert got == tmp_path / "Public" / "Documents" / "aicut-tmp" and got.is_dir()
    assert rp.text_dir_base() != rp.FALLBACK_TMP


def test_filter_path_windows_user_path():
    assert rp._filter_path("C:\\Users\\a b\\t.txt") == "C\\:/Users/a b/t.txt"


def test_filter_path_escapes_single_quote():
    assert rp._filter_path("/x/it's.ttc") == "/x/it'\\''s.ttc"


@pytest.mark.parametrize("path", ["/System/Library/Fonts/Hiragino Sans GB.ttc",
                                  "/var/folders/ab/T/aicut-preview-x/0.txt", "/tmp/0.txt"])
def test_filter_path_leaves_safe_posix_paths_untouched(path):
    assert rp._filter_path(path) == path


def test_build_escapes_windows_paths_in_drawtext(monkeypatch):
    monkeypatch.setattr(rp, "pick_font", lambda: "C:\\Windows\\Fonts\\msyh.ttc")
    t = tl(["一"])
    fc, _ = rp.build(t, text_paths=[Path("C:\\Users\\a b\\0.txt")], has_audio=[True])
    assert "fontfile='C\\:/Windows/Fonts/msyh.ttc':textfile='C\\:/Users/a b/0.txt'" in fc


def test_windows_font_candidates(tmp_path):
    got = rp.win_font_candidates({"SystemRoot": str(tmp_path)})
    assert [Path(g).name for g in got] == ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"]
    assert all(Path(g).parent == tmp_path / "Fonts" for g in got)


def test_pick_font_on_windows_uses_windir_msyh(win_platform, tmp_path, monkeypatch):
    fonts = tmp_path / "Win" / "Fonts"
    fonts.mkdir(parents=True)
    (fonts / "msyh.ttc").write_bytes(b"x")
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Win"))
    assert rp.pick_font() == str(fonts / "msyh.ttc")


def test_pick_font_on_mac_uses_mac_list(mac_platform):
    assert rp.font_candidates() is rp.MAC_FONT_CANDIDATES


def test_windows_text_dir_mkdir_failure_falls_back_to_temp(monkeypatch, tmp_path):
    monkeypatch.setattr(rp.plat, "IS_WIN", True)
    monkeypatch.setattr(rp.tempfile, "gettempdir", lambda: "C:\\Users\\张三\\Temp")
    blocker = tmp_path / "Public"
    blocker.write_text("file, not dir")  # mkdir 必然失败
    monkeypatch.setenv("PUBLIC", str(blocker))
    assert rp.text_dir_base() == "C:\\Users\\张三\\Temp"


# ---------------------------------------------------------------- 集成：真 ffmpeg
def _ffmpeg_ready() -> bool:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return False
    enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                         text=True).stdout
    flt = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True,
                         text=True).stdout
    return (any(f" {e} " in enc for e in encode.candidates())
            and " drawtext " in flt and " anullsrc " in flt)


@pytest.fixture(autouse=True)
def _real_encoder(monkeypatch):
    """真 ffmpeg 用例：选本机 ffmpeg 里实际有的那个候选编码器（没有就保持首选，用例本身会被 skip）。"""
    if shutil.which("ffmpeg"):
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                             text=True).stdout
        found = next((e for e in encode.candidates() if f" {e} " in enc), None)
        monkeypatch.setitem(encode._PREFLIGHT, "encoder", found)


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


@pytest.mark.skipif(not _ffmpeg_ready(), reason="需要带本平台 H.264 编码器 / drawtext / anullsrc 的 ffmpeg")
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


# ---------------------------------------------------------------- Windows 命令行 32767 字符上限（WinError 206）
WIN_CMDLINE_LIMIT = 32767


def _capture_main(tmp_path, monkeypatch, n_text, shots=29, text_base=None):
    """跑 main()，假 run_ffmpeg 抓 argv，并在调用期间读取 -/filter_complex 指向的文件。"""
    import sys
    longdir = tmp_path / ("很长的目录名" * 8)
    longdir.mkdir()
    sources = [longdir / f"素材_{'x' * 40}_{i}.mp4" for i in range(shots)]
    t = tl([f"字幕 {i} 内容" for i in range(n_text)], sources=sources)
    tl_file = tmp_path / "timeline.json"
    tl_file.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    texts = tmp_path / "texts"
    texts.mkdir()
    monkeypatch.setattr(rp, "text_dir_base", lambda: str(text_base or texts))
    monkeypatch.setattr(rp, "pick_font", lambda: "/Fonts/Hiragino Sans GB.ttc")
    monkeypatch.setattr(rp.media_io, "has_audio", lambda p, **kw: True)
    got = {}
    real_build = rp.build

    def spy_build(*a, **kw):
        res = real_build(*a, **kw)
        got["built"] = res[0]
        return res
    monkeypatch.setattr(rp, "build", spy_build)

    def run(args, **kw):
        got["argv"] = list(args)
        if "-/filter_complex" in args:
            f = Path(args[args.index("-/filter_complex") + 1])
            got["file"] = f
            got["raw"] = f.read_bytes()
        Path(args[-1]).write_bytes(b"full")
    monkeypatch.setattr(rp.media_io, "run_ffmpeg", run)
    monkeypatch.setattr(sys, "argv", ["render_preview", str(tl_file), "-o", str(tmp_path / "o.mp4")])
    rp.main()
    return t, got


def test_filter_graph_goes_through_file_not_argv(tmp_path, monkeypatch):
    t, got = _capture_main(tmp_path, monkeypatch, 400)
    argv = got["argv"]
    assert len(got["built"]) > WIN_CMDLINE_LIMIT                  # 前提：内联确实会超 Windows 上限
    assert "-filter_complex" not in argv and "-/filter_complex" in argv
    assert len(" ".join(argv)) < WIN_CMDLINE_LIMIT // 2         # 与字幕条数无关
    raw = got["raw"]
    assert raw == got["built"].encode("utf-8")                     # 恰为 build() 输出
    assert not raw.startswith(b"\xef\xbb\xbf")                    # 无 BOM
    text = raw.decode("utf-8")
    assert text.count("drawtext=") == 400 and text.endswith("[vout]")
    assert ";\n" in text and "\r" not in text
    assert text.split(";\n")[-1] == "[vt399]format=yuv420p[vout]"


def test_argv_length_independent_of_subtitle_count(tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    _, few = _capture_main(a, monkeypatch, 1)
    b = tmp_path / "b"
    b.mkdir()
    _, many = _capture_main(b, monkeypatch, 400)
    assert len(" ".join(many["argv"])) - len(" ".join(few["argv"])) < 200   # 仅临时目录名长度差异


def test_filter_file_lives_in_text_dir_and_is_cleaned(tmp_path, monkeypatch):
    _, got = _capture_main(tmp_path, monkeypatch, 3)
    assert got["file"].parent.name.startswith(rp.TEXT_DIR_PREFIX)
    assert got["file"].parent.parent == tmp_path / "texts"
    assert not got["file"].exists() and list((tmp_path / "texts").iterdir()) == []


def test_filter_file_path_is_passed_verbatim_for_windows_style_dir(tmp_path, monkeypatch):
    """text_dir_base 返回含反斜杠 / 盘符 / 中文 / 空格的 Windows 风格路径：argv 原样给出，不做滤镜转义。"""
    monkeypatch.setattr(rp.plat, "IS_WIN", True)
    win_base = tmp_path / "C:\\Users\\中文 dir\\Temp" if os.name != "nt" else tmp_path / "中文 dir"
    win_base.mkdir()
    _, got = _capture_main(tmp_path, monkeypatch, 2, text_base=win_base)
    arg = got["argv"][got["argv"].index("-/filter_complex") + 1]
    assert arg == str(got["file"])
    assert str(win_base) in arg and "\\:" not in arg and "'\\''" not in arg
    assert arg.endswith(rp.FILTER_FILE_NAME)


def _fail_with(monkeypatch, tmp_path, message):
    import sys
    t = tl(["一"])
    tl_file = tmp_path / "timeline.json"
    tl_file.write_text(json.dumps(t), encoding="utf-8")
    texts = tmp_path / "texts"
    texts.mkdir()
    monkeypatch.setattr(rp, "text_dir_base", lambda: str(texts))
    monkeypatch.setattr(rp, "pick_font", lambda: "/Fonts/x.ttc")
    monkeypatch.setattr(rp.media_io, "has_audio", lambda p, **kw: True)
    monkeypatch.setattr(sys, "argv", ["render_preview", str(tl_file), "-o", str(tmp_path / "o.mp4")])

    def run(args, runner=None, **kw):
        raise rp.media_io.MediaError(message)
    monkeypatch.setattr(rp.media_io, "run_ffmpeg", run)


def test_old_ffmpeg_gets_friendly_version_message(tmp_path, monkeypatch):
    _fail_with(monkeypatch, tmp_path,
               "ffmpeg 失败（退出码 8）：Unrecognized option '/filter_complex'.\nError splitting the argument list")
    with pytest.raises(SystemExit) as e:
        rp.main()
    assert str(e.value) == "预览片渲染失败：需要 ffmpeg 7.0 或更高版本（打包版自带 8.1.3）；请升级本机 ffmpeg"


def test_other_ffmpeg_failure_keeps_original_message(tmp_path, monkeypatch):
    _fail_with(monkeypatch, tmp_path, "ffmpeg 失败（退出码 1）：boom")
    with pytest.raises(SystemExit) as e:
        rp.main()
    assert "boom" in str(e.value) and "7.0" not in str(e.value)


def test_temp_write_oserror_becomes_friendly_exit(tmp_path, monkeypatch):
    _fail_with(monkeypatch, tmp_path, "unused")

    def boom(*a, **kw):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(rp, "subtitle_files", boom)
    with pytest.raises(SystemExit) as e:
        rp.main()
    assert str(e.value).startswith("预览片渲染失败：") and "No space left" in str(e.value)


def test_filter_file_write_oserror_becomes_friendly_exit(tmp_path, monkeypatch):
    _fail_with(monkeypatch, tmp_path, "unused")
    monkeypatch.setattr(rp, "FILTER_FILE_NAME", "no/such/dir/filter.txt")
    with pytest.raises(SystemExit) as e:
        rp.main()
    assert str(e.value).startswith("预览片渲染失败：")


def _ffmpeg_major() -> int | None:
    """`ffmpeg -version` 首行的主版本号；git 构建（N-…）等无法解析时返回 None。"""
    if shutil.which("ffmpeg") is None:
        return None
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    m = re.match(r"ffmpeg version n?(\d+)\.", out)
    return int(m.group(1)) if m else None


@pytest.mark.skipif(not _ffmpeg_ready() or (_ffmpeg_major() or 99) < 7,
                    reason="需要 ffmpeg ≥ 7.0（-/filter_complex）且带 drawtext / anullsrc")
def test_real_ffmpeg_accepts_filter_complex_file(tmp_path):
    f = tmp_path / "filter.txt"
    f.write_text("color=c=blue:s=64x48:r=10:d=0.5[v];\nanullsrc=r=48000:cl=stereo,atrim=duration=0.5[a]",
                 encoding="utf-8")
    out = tmp_path / "o.mkv"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-/filter_complex", str(f),
                        "-map", "[v]", "-map", "[a]", "-c:v", "mpeg4", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out.stat().st_size > 0


# ---------------------------------------------------------------- M6 · KI-73 预览字幕字体
def test_prefers_hiragino_sans_gb(tmp_path, monkeypatch):
    assert rp.MAC_FONT_CANDIDATES[0] == "/System/Library/Fonts/Hiragino Sans GB.ttc"
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
