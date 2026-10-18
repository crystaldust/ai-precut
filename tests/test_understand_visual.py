import json
import shutil
import subprocess

import pytest

from pipeline import understand_visual as uv


pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """3 段纯色拼接：红 2s / 蓝 2s / 绿 2s，应有 2 个切点。"""
    path = tmp_path_factory.mktemp("v") / "colors.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=red:duration=2:size=320x240:rate=10",
        "-f", "lavfi", "-i", "color=blue:duration=2:size=320x240:rate=10",
        "-f", "lavfi", "-i", "color=green:duration=2:size=320x240:rate=10",
        "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_detect_two_cuts(clip):
    res = uv.analyze(clip, threshold=6)
    assert res["cut_count"] >= 2
    starts = [s["start"] for s in res["shots"]]
    assert any(abs(s - 2.0) < 0.6 for s in starts)
    assert any(abs(s - 4.0) < 0.6 for s in starts)
    assert res["shots"][0]["start"] == 0.0
    assert abs(res["shots"][-1]["end"] - res["duration"]) < 0.05


def test_shots_cover_full_duration(clip):
    res = uv.analyze(clip, threshold=6)
    for a, b in zip(res["shots"], res["shots"][1:]):
        assert a["end"] == b["start"]


def test_short_shot_merged_into_previous():
    # 1.0→1.2 只有 0.2 秒，应并入前一个镜头，而不是单独成镜
    shots = uv.build_shots([1.0, 1.2, 3.0], 5.0, min_len=0.5)
    assert [s["start"] for s in shots] == [0.0, 1.2, 3.0]
    assert shots[0]["duration"] == 1.2


def test_no_cut_gives_single_shot():
    shots = uv.build_shots([], 10.0)
    assert len(shots) == 1 and shots[0]["duration"] == 10.0


def test_run_writes_json(clip, tmp_path):
    out = tmp_path / "shots.json"
    uv.run(clip, out, threshold=6)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["shots"] and data["cut_count"] >= 2


@pytest.fixture(scope="module")
def mixclip(tmp_path_factory):
    """灰底 2s + 动态测试图 2s，用于质量指标。"""
    path = tmp_path_factory.mktemp("q") / "mix.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=gray:duration=2:size=160x90:rate=10",
        "-f", "lavfi", "-i", "testsrc2=duration=2:size=160x90:rate=10",
        "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]", "-map", "[v]",
        "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_still_has_no_motion(mixclip):
    samples = uv.sample_frames(mixclip)
    assert len(samples) >= 3
    assert samples[0]["motion"] == 0
    assert samples[0]["blur"] == 0  # 纯色，拉普拉斯方差为 0


def test_moving_content_has_motion_and_detail(mixclip):
    samples = uv.sample_frames(mixclip)
    moving = [s for s in samples if s["t"] >= 2]
    assert moving and max(s["motion"] for s in moving) > 1.0
    assert max(s["blur"] for s in moving) > 100


def test_aggregate_by_segment(mixclip):
    samples = uv.sample_frames(mixclip)
    segs = [{"id": "S001", "start": 0, "end": 2}, {"id": "S002", "start": 2, "end": 4}]
    agg = uv.aggregate_by_segment(samples, segs)
    assert agg["S001"]["motion"] == 0
    assert agg["S002"]["motion"] > 0
    assert agg["S002"]["blur"] > agg["S001"]["blur"]


def test_quality_writes_json(mixclip, tmp_path):
    sp = tmp_path / "segments.json"
    sp.write_text(json.dumps({"segments": [{"id": "S001", "start": 0, "end": 2}]}),
                  encoding="utf-8")
    out = tmp_path / "q.json"
    uv.run_quality(mixclip, sp, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["samples"] >= 3 and "S001" in data["segments"]


def test_quality_flags_relative(mixclip):
    segs = [{"id": "S001", "start": 0, "end": 2}, {"id": "S002", "start": 2, "end": 4}]
    res = uv.quality(mixclip, segs)
    assert "soft" in res["segments"]["S001"]["flags"]      # 纯色：无细节
    assert "still" in res["segments"]["S001"]["flags"]     # 纯色：无运动
    assert "soft" not in res["segments"]["S002"]["flags"]
