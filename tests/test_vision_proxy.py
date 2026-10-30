"""画面理解第 3 阶段：画面代理切段（pipeline/vision_proxy.py）。不跑真 ffmpeg。"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import media_io, vision, vision_proxy


def test_plan_chunks_hour_is_twelve_contiguous_chunks():
    chunks = vision_proxy.plan_chunks(3600)
    assert len(chunks) == 12
    assert chunks[0] == {"index": 0, "start": 0.0, "end": 300.0}
    assert chunks[-1]["end"] == 3600
    assert all(a["end"] == b["start"] for a, b in zip(chunks, chunks[1:]))
    assert [c["index"] for c in chunks] == list(range(12))


def test_plan_chunks_short_tail_merges_into_previous():
    assert vision_proxy.plan_chunks(610) == [{"index": 0, "start": 0.0, "end": 300.0},
                                             {"index": 1, "start": 300.0, "end": 610.0}]


def test_plan_chunks_long_enough_tail_is_its_own_chunk():
    chunks = vision_proxy.plan_chunks(330)
    assert [(c["start"], c["end"]) for c in chunks] == [(0.0, 300.0), (300.0, 330.0)]


def test_plan_chunks_very_short_material_is_one_chunk():
    assert vision_proxy.plan_chunks(12.5) == [{"index": 0, "start": 0.0, "end": 12.5}]


def test_plan_chunks_three_hours():
    chunks = vision_proxy.plan_chunks(3 * 3600)
    assert len(chunks) == 36
    assert max(c["end"] - c["start"] for c in chunks) <= vision.CHUNK_S + vision.MIN_TAIL_S


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_plan_chunks_rejects_bad_duration(bad):
    with pytest.raises(ValueError):
        vision_proxy.plan_chunks(bad)


def test_chunk_path_is_zero_padded(tmp_path):
    assert vision_proxy.chunk_path(tmp_path, 3).name == "chunk_003.mp4"


def test_encode_chunk_args_and_atomic_marker(tmp_path, monkeypatch):
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"p")
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        Path(cmd[-1]).write_bytes(b"clip")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(vision_proxy.encode, "encoder", lambda: "h264_videotoolbox")
    dst = vision_proxy.chunk_path(tmp_path / "vision", 1)
    out = vision_proxy.encode_chunk(proxy, {"index": 1, "start": 300.0, "end": 610.0}, dst,
                                    runner=runner)
    assert out == dst and dst.read_bytes() == b"clip"
    assert media_io.is_complete(dst, source=proxy)
    cmd, kw = calls[0]
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "300.000" and cmd[cmd.index("-t") + 1] == "310.000"
    assert "fps=5" in cmd and "-an" in cmd and "300k" in cmd
    assert cmd[cmd.index("-map_metadata") + 1] == "-1" and "-map_chapters" in cmd
    assert kw["timeout"] >= media_io.FFMPEG_MIN_TIMEOUT_S


def test_encode_chunk_failure_leaves_no_output(tmp_path, monkeypatch):
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"p")

    def runner(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"half")
        return SimpleNamespace(returncode=1, stderr="boom")

    monkeypatch.setattr(vision_proxy.encode, "encoder", lambda: "h264_videotoolbox")
    dst = vision_proxy.chunk_path(tmp_path, 0)
    with pytest.raises(media_io.MediaError):
        vision_proxy.encode_chunk(proxy, {"index": 0, "start": 0.0, "end": 10.0}, dst, runner=runner)
    assert not dst.exists() and not media_io.is_complete(dst)
