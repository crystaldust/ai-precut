"""pipeline/media_io：临时文件 → 原子改名 → 完成标记（GL-15）。"""
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import media_io as mio


class FakeProc:
    def __init__(self, code=0, err=""):
        self.returncode, self.stdout, self.stderr = code, "", err


def test_atomic_output_commits_and_marks(tmp_path):
    dst = tmp_path / "proxy.mp4"
    with mio.atomic_output(dst) as tmp:
        assert tmp.suffix == ".mp4" and tmp.parent == dst.parent  # ffmpeg 靠扩展名选封装
        tmp.write_bytes(b"data")
    assert dst.read_bytes() == b"data" and mio.is_complete(dst)
    assert list(tmp_path.glob(".proxy.partial-*")) == []


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyboardInterrupt(), SystemExit(1)])
def test_interrupted_write_leaves_no_final_file(tmp_path, exc):
    dst = tmp_path / "asr.wav"
    with pytest.raises(type(exc)):
        with mio.atomic_output(dst) as tmp:
            tmp.write_bytes(b"half")
            raise exc
    assert not dst.exists() and not mio.is_complete(dst)
    assert list(tmp_path.iterdir()) == []


def test_regeneration_interrupted_invalidates_old_file(tmp_path):
    dst = tmp_path / "S01.mp4"
    with mio.atomic_output(dst) as tmp:
        tmp.write_bytes(b"old")
    with pytest.raises(RuntimeError):
        with mio.atomic_output(dst):
            raise RuntimeError("killed")
    assert not mio.is_complete(dst)  # 决定重做就先作废旧标记


def test_legacy_file_without_marker_is_not_complete(tmp_path):
    dst = tmp_path / "asr.wav"
    dst.write_bytes(b"half-from-old-version")
    assert not mio.is_complete(dst)


def test_size_mismatch_is_not_complete(tmp_path):
    dst = tmp_path / "a.wav"
    with mio.atomic_output(dst) as tmp:
        tmp.write_bytes(b"1234")
    dst.write_bytes(b"12")
    assert not mio.is_complete(dst)


def test_corrupt_marker_is_not_complete(tmp_path):
    dst = tmp_path / "a.wav"
    with mio.atomic_output(dst) as tmp:
        tmp.write_bytes(b"1234")
    mio.done_marker(dst).write_text("{坏", encoding="utf-8")
    assert not mio.is_complete(dst)


def test_empty_output_is_rejected(tmp_path):
    dst = tmp_path / "a.wav"
    with pytest.raises(mio.MediaError):
        with mio.atomic_output(dst):
            pass
    assert not dst.exists()


def test_stale_partials_from_killed_run_are_cleaned(tmp_path):
    stale = tmp_path / ".proxy.partial-deadbeef.mp4"
    stale.write_bytes(b"x")
    with mio.atomic_output(tmp_path / "proxy.mp4") as tmp:
        tmp.write_bytes(b"ok")
    assert not stale.exists()


def test_stale_partial_cleanup_handles_glob_metachars(tmp_path):
    other = tmp_path / ".S1.partial-deadbeef.mp4"  # 别的镜头的临时文件不能被误删
    other.write_bytes(b"x")
    with mio.atomic_output(tmp_path / "S[1].mp4") as tmp:
        tmp.write_bytes(b"ok")
    assert other.exists()


def test_run_ffmpeg_raises_with_stderr_tail():
    def runner(args, **kw):
        return FakeProc(1, "No such file or directory")
    with pytest.raises(mio.MediaError, match="No such file"):
        mio.run_ffmpeg(["-i", "x"], runner=runner)


def test_ffmpeg_to_passes_partial_path_as_last_arg(tmp_path):
    seen = []

    def runner(args, **kw):
        seen.append(args)
        Path(args[-1]).write_bytes(b"ok")
        return FakeProc(0)
    dst = tmp_path / "S01.mp4"
    mio.ffmpeg_to(dst, ["-i", "src.mov"], runner=runner)
    assert seen[0][0] == "ffmpeg" and seen[0][-1] != str(dst)
    assert mio.is_complete(dst)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="本机无 ffmpeg")
def test_ffmpeg_to_real_ffmpeg(tmp_path):
    dst = tmp_path / "a.wav"
    mio.ffmpeg_to(dst, ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "0.2",
                        "-c:a", "pcm_s16le"])
    assert mio.is_complete(dst)


def test_run_ffmpeg_missing_binary_is_media_error():
    def runner(args, **kw):
        raise FileNotFoundError("ffmpeg")
    with pytest.raises(mio.MediaError, match="ffmpeg"):
        mio.run_ffmpeg(["-i", "x"], runner=runner)


# ---------------------------------------------------------------- 审查修复 7：旧项目产物认领
def _probe(duration):
    def runner(args, **kw):
        if duration is None:
            return FakeProc(1, "Invalid data found when processing input")
        p = FakeProc(0)
        p.stdout = f"{duration}\n"
        return p
    return runner


def test_complete_or_adopt_adopts_legacy_file_with_positive_duration(tmp_path):
    dst = tmp_path / "proxy.mp4"
    dst.write_bytes(b"legacy-full")
    assert mio.complete_or_adopt(dst, runner=_probe(12.5))
    assert mio.is_complete(dst)  # 写了标记，下次不用再探测


@pytest.mark.parametrize("duration", [None, 0.0, "N/A"])
def test_complete_or_adopt_rejects_unreadable_legacy_file(tmp_path, duration):
    dst = tmp_path / "asr.wav"
    dst.write_bytes(b"half")
    assert not mio.complete_or_adopt(dst, runner=_probe(duration))
    assert not mio.done_marker(dst).exists()


def test_complete_or_adopt_rejects_empty_or_missing(tmp_path):
    empty = tmp_path / "a.wav"
    empty.write_bytes(b"")
    assert not mio.complete_or_adopt(empty, runner=_probe(3.0))
    assert not mio.complete_or_adopt(tmp_path / "missing.wav", runner=_probe(3.0))


def test_complete_or_adopt_missing_ffprobe_is_not_adopted(tmp_path):
    dst = tmp_path / "a.wav"
    dst.write_bytes(b"x")

    def runner(args, **kw):
        raise FileNotFoundError("ffprobe")
    assert not mio.complete_or_adopt(dst, runner=runner)


def test_complete_or_adopt_does_not_probe_when_marked(tmp_path):
    dst = tmp_path / "a.wav"
    with mio.atomic_output(dst) as tmp:
        tmp.write_bytes(b"ok")

    def runner(args, **kw):
        raise AssertionError("已有标记不该再探测")
    assert mio.complete_or_adopt(dst, runner=runner)


def test_complete_or_adopt_ignores_stale_marker_of_other_size(tmp_path):
    # 有标记但大小不符 = 被改动过的产物，不能被"认领"洗白
    dst = tmp_path / "a.wav"
    with mio.atomic_output(dst) as tmp:
        tmp.write_bytes(b"1234")
    dst.write_bytes(b"12")
    assert not mio.complete_or_adopt(dst, runner=_probe(3.0))


# ---------------------------------------------------------------- KI-14：素材有没有音轨
def _streams(stdout, code=0):
    def runner(args, **kw):
        assert "-select_streams" in args and "a" in args
        p = FakeProc(code, "boom" if code else "")
        p.stdout = stdout
        return p
    return runner


def test_has_audio_true_when_ffprobe_lists_stream(tmp_path):
    assert mio.has_audio(tmp_path / "a.mp4", runner=_streams("1\n"))


def test_has_audio_false_when_no_audio_stream(tmp_path):
    assert not mio.has_audio(tmp_path / "a.mp4", runner=_streams(""))


def test_has_audio_unreadable_is_media_error(tmp_path):
    with pytest.raises(mio.MediaError, match="读不了素材"):
        mio.has_audio(tmp_path / "a.mp4", runner=_streams("", code=1))


def test_has_audio_without_ffprobe_is_media_error(tmp_path):
    def runner(args, **kw):
        raise FileNotFoundError("ffprobe")
    with pytest.raises(mio.MediaError, match="ffprobe"):
        mio.has_audio(tmp_path / "a.mp4", runner=runner)


def test_atomic_output_without_marker(tmp_path):
    dst = tmp_path / "o.mp4"
    with mio.atomic_output(dst, mark=False) as tmp:
        tmp.write_bytes(b"data")
    assert dst.read_bytes() == b"data" and not mio.done_marker(dst).exists()
    assert [p.name for p in tmp_path.iterdir()] == ["o.mp4"]


# ---------------------------------------------------------------- M8：KI-19 / KI-66 严格原语
class FakeOut:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def _runner(result, seen=None):
    def run(cmd, **kw):
        if seen is not None:
            seen.append((cmd, kw))
        if isinstance(result, BaseException):
            raise result
        return result
    return run


def test_run_analysis_returns_stderr_log():
    seen = []
    log = mio.run_analysis(["-i", "x.mp4", "-f", "null", "-"],
                           runner=_runner(FakeProc(0, err="silence_start: 1"), seen))
    assert log == "silence_start: 1"
    cmd = seen[0][0]
    assert cmd[:3] == ["ffmpeg", "-hide_banner", "-nostats"]
    assert "-loglevel" not in cmd  # filter 日志在 info 级


def test_run_analysis_nonzero_raises_with_tail():
    with pytest.raises(mio.MediaError) as exc:
        mio.run_analysis(["-i", "x"], runner=_runner(FakeProc(1, err="x" * 2000 + "Invalid data found")))
    msg = str(exc.value)
    assert "退出码 1" in msg and "Invalid data found" in msg
    assert len(msg) < mio.STDERR_TAIL + 100


def test_run_analysis_missing_binary():
    with pytest.raises(mio.MediaError, match="无法运行 ffmpeg"):
        mio.run_analysis(["-i", "x"], runner=_runner(FileNotFoundError("ffmpeg")))


def test_run_analysis_timeout():
    with pytest.raises(mio.MediaError, match="秒"):
        mio.run_analysis(["-i", "x"], runner=_runner(subprocess.TimeoutExpired(["ffmpeg"], 5)),
                         timeout=5)


def test_probe_duration_strict_ok():
    assert mio.probe_duration(Path("a.mp4"), runner=_runner(FakeOut(0, "12.5\n"))) == 12.5


@pytest.mark.parametrize("result", [FakeOut(1, "", "moov atom not found"), FakeOut(0, ""),
                                    FakeOut(0, "N/A"), FakeOut(0, "0"), FakeOut(0, "-1"),
                                    FakeOut(0, "nan"), FileNotFoundError("ffprobe")])
def test_probe_duration_strict_failures(result):
    with pytest.raises(mio.MediaError, match="读不到时长"):
        mio.probe_duration(Path("a.mp4"), runner=_runner(result))


def test_probe_duration_strict_carries_reason():
    with pytest.raises(mio.MediaError, match="moov atom not found"):
        mio.probe_duration(Path("a.mp4"), runner=_runner(FakeOut(1, "", "moov atom not found")))


def test_probe_material_ok():
    out = '{"format":{"duration":"12.5"},"streams":[{"codec_type":"video"}]}'
    assert mio.probe_material(Path("a.mp4"), runner=_runner(FakeOut(0, out))) == {
        "duration": 12.5, "streams": [{"codec_type": "video"}], "warnings": []}


@pytest.mark.parametrize("result", [
    FakeOut(1, "", "Invalid data found when processing input"), FakeOut(0, ""),
    FakeOut(0, "{}"), FakeOut(0, "[]"),  # 容器里只是没写时长的情况见 test_m8_review（警告不拒绝）
    FileNotFoundError("ffprobe")])
def test_probe_material_unrecognized(result):
    prefix = mio.MATERIAL_UNREADABLE.split("（")[0]
    with pytest.raises(mio.MediaError, match=prefix):
        mio.probe_material(Path("a.mp4"), runner=_runner(result))


def test_probe_material_reason_from_stderr():
    with pytest.raises(mio.MediaError, match="Invalid data found"):
        mio.probe_material(Path("a.mp4"),
                           runner=_runner(FakeOut(1, "", "Invalid data found when processing input")))
