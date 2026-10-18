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
