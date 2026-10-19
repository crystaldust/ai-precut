"""pipeline/format_transcript：时间码（KI-24）。"""
import json
import sys

import pytest

from pipeline import format_transcript as ft


@pytest.mark.parametrize("sec,expected", [(59.999, "01:00.00"), (0, "00:00.00"), (61.234, "01:01.23"),
                                          (-1, "00:00.00"), (119.995, "02:00.00"), (5.5, "00:05.50")])
def test_tc_rounds_before_carry(sec, expected):
    assert ft.tc(sec) == expected


def _raw(tmp_path, subs, duration=30.0):
    p = tmp_path / "transcript_raw.json"
    p.write_text(json.dumps({"result": {"duration": duration, "subtitles": subs}},
                            ensure_ascii=False), encoding="utf-8")
    return p


GOOD = {"start_time": 1.0, "end_time": 3.0, "text": "大家好，今天讲合同"}
BAD = [{"end_time": 2.0, "text": "缺起点"},
       {"start_time": 1.0, "end_time": "abc", "text": "终点不是数"},
       {"start_time": 5.0, "end_time": 4.0, "text": "终点早于起点"}]


def test_subs_missing_time_are_dropped_and_counted(tmp_path):
    subs, duration, dropped = ft.load_subs(_raw(tmp_path, [GOOD, *BAD]))
    assert [s["text"] for s in subs] == ["大家好，今天讲合同"]
    assert dropped == 3 and duration == 30.0


def test_bool_time_is_not_a_number(tmp_path):
    subs, _, dropped = ft.load_subs(_raw(tmp_path, [{"start_time": True, "end_time": 2, "text": "x"}]))
    assert subs == [] and dropped == 1


def test_contained_sentence_does_not_move_end_backwards():
    subs = [{"start": 0.0, "end": 10.0, "text": "A", "speaker": "A"},
            {"start": 2.0, "end": 3.0, "text": "A", "speaker": "A"}]
    seg = ft.build_segments(subs)[0]
    assert seg["end"] == 10.0 and seg["duration"] == 10.0


def _main(monkeypatch, raw, out):
    monkeypatch.setattr(sys, "argv", ["format_transcript", str(raw), "-o", str(out)])
    ft.main()


def test_main_warns_dropped(tmp_path, monkeypatch, capsys):
    _main(monkeypatch, _raw(tmp_path, [GOOD, *BAD]), tmp_path / "out")
    assert "3 句缺少有效时间码" in capsys.readouterr().out
    assert (tmp_path / "out/segments.json").exists()


def test_main_exits_when_all_dropped(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, _raw(tmp_path, BAD), tmp_path / "out")
    assert "没有可用的时间码" in str(exc.value.code)
    assert not (tmp_path / "out/segments.json").exists()


def test_main_no_subtitles_message_kept(tmp_path, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, _raw(tmp_path, []), tmp_path / "out")
    assert "没有解析到字幕" in str(exc.value.code)
