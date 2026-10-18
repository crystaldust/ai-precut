import math
import struct
import wave
from pathlib import Path

import pytest

from pipeline import understand_audio as ua


def make_wav(path: Path, chunks: list[tuple[float, int]], rate: int = 16000) -> None:
    """chunks: [(秒数, 振幅0-32767), ...]，按顺序拼成单声道 16bit wav。"""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for seconds, amp in chunks:
            n = int(seconds * rate)
            frames = b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 440 * i / rate)))
                              for i in range(n))
            w.writeframes(frames)


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "a.wav"
    make_wav(path, [(1.0, 3000), (0.6, 200), (1.0, 20000)])
    return path


def test_rms_reflects_loudness(wav):
    segs = [
        {"id": "s1", "start": 0.0, "end": 1.0, "text": "第一句话", "speaker": "1"},
        {"id": "s2", "start": 1.6, "end": 2.6, "text": "第二句更长一些", "speaker": "2"},
    ]
    res = ua.analyze(wav, segs)
    a, b = res["segments"]
    assert b["signals"]["rms_db"] > a["signals"]["rms_db"] + 10
    assert b["signals"]["rel_db"] > 0 > a["signals"]["rel_db"]


def test_pause_between_segments(wav):
    segs = [
        {"id": "s1", "start": 0.0, "end": 1.0, "text": "甲", "speaker": "1"},
        {"id": "s2", "start": 1.6, "end": 2.6, "text": "乙", "speaker": "1"},
    ]
    res = ua.analyze(wav, segs)
    assert res["segments"][0]["signals"]["pause_after"] == pytest.approx(0.6, abs=0.02)
    assert res["segments"][1]["signals"]["pause_after"] == 0.0


def test_speech_rate_counts_chars_per_second(wav):
    segs = [{"id": "s1", "start": 0.0, "end": 2.0, "text": "一二三四五六七八", "speaker": "1"}]
    res = ua.analyze(wav, segs)
    assert res["segments"][0]["signals"]["speech_rate"] == 4.0


def test_overlap_detected_for_different_speakers(wav):
    segs = [
        {"id": "s1", "start": 0.0, "end": 1.0, "text": "甲说", "speaker": "1"},
        {"id": "s2", "start": 0.5, "end": 1.5, "text": "乙抢话", "speaker": "2"},
        {"id": "s3", "start": 1.6, "end": 2.6, "text": "丙正常", "speaker": "3"},
    ]
    res = ua.analyze(wav, segs)
    assert res["segments"][0]["signals"]["overlap"] is True
    assert res["segments"][2]["signals"]["overlap"] is False


def test_interrupt_when_speaker_changes_without_pause(wav):
    segs = [
        {"id": "s1", "start": 0.0, "end": 1.0, "text": "甲说", "speaker": "1"},
        {"id": "s2", "start": 1.05, "end": 1.6, "text": "乙接话", "speaker": "2"},
        {"id": "s3", "start": 2.0, "end": 2.5, "text": "甲再说", "speaker": "1"},
    ]
    res = ua.analyze(wav, segs)
    assert res["segments"][0]["signals"]["interrupt"] is True
    assert res["segments"][1]["signals"]["interrupt"] is False


def test_run_writes_json(wav, tmp_path):
    segs = {"segments": [{"id": "s1", "start": 0.0, "end": 1.0, "text": "甲", "speaker": "1"}]}
    sp = tmp_path / "segments.json"
    sp.write_text(__import__("json").dumps(segs), encoding="utf-8")
    out = tmp_path / "out.json"
    ua.run(wav, sp, out)
    assert out.exists()
    assert '"median_db"' in out.read_text(encoding="utf-8")


def test_rejects_non_16bit(tmp_path):
    path = tmp_path / "b.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(1); w.setframerate(8000)
        w.writeframes(b"\x80" * 100)
    with pytest.raises(ValueError):
        ua.analyze(path, [])
