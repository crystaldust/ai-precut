"""pipeline/junk_detect：退出码（KI-19）、收尾闭合 / 重叠去重 / scenes（KI-27）、冻帧+静音强信号（KI-77）。

用固定日志文本打桩 ffmpeg，不依赖真实 ffmpeg。
"""
import json
import sys

import pytest

from pipeline import junk_detect as jd
from pipeline import media_io

LOG = """  Duration: 00:00:20.00, start: 0.000000, bitrate: 1 kb/s
[silencedetect @ 0x1] silence_start: -0.02
[silencedetect @ 0x1] silence_end: 4.0 | silence_duration: 4.02
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 15.0
[silencedetect @ 0x1] silence_start: 14.5
[scdet @ 0x3] lavfi.scd.score: 30.1, lavfi.scd.time: 8.5
[blackdetect @ 0x4] black_start:2.0 black_end:3.5 black_duration:1.5
"""


class FakeProc:
    def __init__(self, code=0, err=""):
        self.returncode, self.stdout, self.stderr = code, "", err


def fake(code=0, err=LOG, seen=None):
    def run(cmd, **kw):
        if seen is not None:
            seen.append(cmd)
        return FakeProc(code, err)
    return run


def _detect(scene=True, **kw):
    return jd.detect("x.mp4", -35.0, 2.0, 0.5, scene, **kw)


def test_unclosed_tail_intervals_closed_at_duration():
    intervals, duration, _ = _detect(runner=fake())
    assert duration == 20.0
    assert (15.0, 20.0, "freeze") in intervals
    assert (14.5, 20.0, "silence") in intervals


def test_negative_silence_start_clamped():
    intervals, _, _ = _detect(runner=fake())
    silences = sorted(i for i in intervals if i[2] == "silence")
    assert silences[0] == (0.0, 4.0, "silence")


def test_scenes_returned_when_requested():
    assert _detect(scene=True, runner=fake())[2] == [8.5]
    assert _detect(scene=False, runner=fake())[2] == []


def test_detect_uses_analysis_command():
    seen = []
    _detect(runner=fake(seen=seen))
    assert seen[0][:3] == ["ffmpeg", "-hide_banner", "-nostats"]
    assert "scdet=threshold=10" in " ".join(seen[0])


def test_detect_raises_on_ffmpeg_failure():
    with pytest.raises(media_io.MediaError, match="Invalid data found"):
        _detect(runner=fake(code=1, err="Invalid data found when processing input"))


def test_union_seconds_counts_overlap_once():
    rows = [{"start": 2, "end": 3.5, "suggest": "删"}, {"start": 3, "end": 4, "suggest": "删"},
            {"start": 10, "end": 12, "suggest": "参考"}]
    assert jd.union_seconds(rows) == 2.0
    assert jd.union_seconds([]) == 0.0
    assert jd.union_seconds(rows, "参考") == 2.0


# ---------------------------------------------------------------- KI-77
def _row(rows, kind):
    return next(r for r in rows if r["type"] == kind)


def test_freeze_and_silence_full_overlap_is_strong_signal():
    rows = jd.judge([(10.0, 20.0, "freeze"), (10.0, 20.0, "silence")], 60.0, -35.0)
    for kind in ("freeze", "silence"):
        r = _row(rows, kind)
        assert r["score"] == 0.97 and r["suggest"] == "删"
        assert "无语音 + 画面静止" in r["reason"]


def test_freeze_mostly_covered_by_silence_is_strong_signal():
    rows = jd.judge([(10.0, 20.0, "freeze"), (9.0, 19.5, "silence")], 60.0, -35.0)
    assert _row(rows, "freeze")["score"] == 0.97


def test_freeze_and_silence_barely_touching_stay_weak():
    rows = jd.judge([(10.0, 20.0, "freeze"), (19.0, 25.0, "silence")], 60.0, -35.0)
    assert _row(rows, "freeze")["score"] == 0.7
    assert _row(rows, "silence")["score"] == 0.55


def test_black_with_freeze_and_silence_still_strong():
    rows = jd.judge([(2.0, 5.0, "black"), (2.0, 5.0, "freeze"), (2.0, 5.0, "silence")], 60.0, -35.0)
    assert _row(rows, "black")["score"] == 0.97


def test_strong_overlap_deleted_seconds_counted_once():
    rows = jd.judge([(10.0, 20.0, "freeze"), (10.0, 20.0, "silence")], 60.0, -35.0)
    assert jd.union_seconds(rows) == 10.0


# ---------------------------------------------------------------- main()
def _run_main(monkeypatch, tmp_path, *extra):
    media = tmp_path / "proxy.mp4"
    media.write_bytes(b"x")
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["junk_detect", str(media), "-o", str(out), *extra])
    jd.main()
    return out


def test_main_exits_with_reason_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(jd, "detect", lambda *a, **k: (_ for _ in ()).throw(
        media_io.MediaError("ffmpeg 失败（退出码 1）：Invalid data found")))
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tmp_path)
    assert "废片检测失败" in str(exc.value.code) and "Invalid data found" in str(exc.value.code)
    assert not (tmp_path / "out/junk_report.json").exists()


def test_main_exits_when_duration_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(jd, "detect", lambda *a, **k: ([], 0.0, []))
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tmp_path)
    assert "废片检测失败" in str(exc.value.code) and "读不到" in str(exc.value.code)
    assert not (tmp_path / "out/junk_report.json").exists()


def test_main_writes_scenes_and_dedups_total(monkeypatch, tmp_path, capsys):
    intervals = [(10.0, 20.0, "freeze"), (10.0, 20.0, "silence")]
    monkeypatch.setattr(jd, "detect", lambda *a, **k: (intervals, 100.0, [8.5]))
    out = _run_main(monkeypatch, tmp_path, "--scene")
    data = json.loads((out / "junk_report.json").read_text(encoding="utf-8"))
    assert data["scenes"] == [8.5]
    printed = capsys.readouterr().out
    assert "建议删除 10.0s" in printed and "占 10.0%" in printed
