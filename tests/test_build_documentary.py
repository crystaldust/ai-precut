"""pipeline/build_documentary：字幕卡（GL-10）与切片原子落盘（GL-15）。"""
from pipeline import build_documentary as bd


def test_card_entries_drops_card_starting_after_total(capsys):
    cards = [{"at": 0.0, "dur": 4.5, "text": "片头"}, {"at": 170.0, "dur": 5.5, "text": "片尾"}]
    out = bd.card_entries(cards, total=150.0, size=6.8)
    assert [c["text"] for c in out] == ["片头"]
    assert all(c["end"] > c["start"] for c in out)
    assert "[warn]" in capsys.readouterr().out  # D1：跳过要告诉剪辑师


def test_card_entries_clips_end_to_total():
    out = bd.card_entries([{"at": 2.0, "dur": 10.0, "text": "x"}], total=5.0, size=6.8)
    assert out[0]["end"] == 5.0 and out[0]["style"]["align"] == bd.CARD_ALIGN == 5
    assert out[0]["style"]["size"] == 6.8


# ---------------------------------------------------------------- GL-15
def test_cut_shot_goes_through_atomic_output(tmp_path, monkeypatch):
    from pathlib import Path

    from pipeline import media_io
    seen = []

    def run(args, **kw):
        seen.append(args)
        Path(args[-1]).write_bytes(b"ok")
    monkeypatch.setattr(media_io, "run_ffmpeg", run)
    dst = tmp_path / "S01.mp4"
    bd.cut_shot(tmp_path / "src.mov", dst, 0.0, 1.0)
    assert media_io.is_complete(dst) and "+faststart" in seen[0]
    assert seen[0][-1] != str(dst)  # 写临时文件再改名


def test_card_entries_warns_when_card_is_shortened(capsys):
    # 审查修复 8：片尾卡被成片结尾截短也要告诉剪辑师
    bd.card_entries([{"at": 2.0, "dur": 10.0, "text": "片尾"}], total=5.0)
    out = capsys.readouterr().out
    assert "[warn]" in out and "截短" in out


def test_card_entries_quiet_when_card_fits(capsys):
    bd.card_entries([{"at": 0.0, "dur": 4.5, "text": "片头"}], total=150.0)
    assert capsys.readouterr().out == ""


# ================================================================ M6 · KI-11 缓存绑定入出点
def test_preview_fingerprint_changes_when_in_out_shift(tmp_path):
    from pathlib import Path
    tl = {"video": [{"id": "S01", "in": 0.0, "out": 5.0}], "text": []}
    a = [{"id": "S01", "in": 10.0, "out": 15.0}]
    b = [{"id": "S01", "in": 12.0, "out": 17.0}]
    src = Path("/src.mov")
    assert bd.preview_fingerprint(tl, a, src) != bd.preview_fingerprint(tl, b, src)
    assert bd.preview_fingerprint(tl, a, src) == bd.preview_fingerprint(tl, [dict(a[0])], src)
    assert bd.clip_key(a[0], src) != bd.clip_key(b[0], src)


def _spec(tmp_path, inn, out):
    import json
    src = tmp_path / "src.mov"
    src.write_bytes(b"x")
    sp = tmp_path / "shots.json"
    sp.write_text(json.dumps({"project": "片", "source": str(src),
                              "shots": [{"id": "S01", "in": inn, "out": out, "sub": "你好"}]}),
                  encoding="utf-8")
    return sp


def test_main_recuts_when_in_out_changed(tmp_path, monkeypatch):
    import sys

    from pipeline import media_io
    cuts = []
    monkeypatch.setattr(bd, "cut_shot", lambda src, dst, start, dur: cuts.append(start))
    monkeypatch.setattr(media_io, "complete_or_adopt", lambda p: True)
    out = tmp_path / "out"

    def run(inn, outp):
        monkeypatch.setattr(sys, "argv", ["bd", str(_spec(tmp_path, inn, outp)), "-o", str(out)])
        bd.main()
    run(0.0, 5.0)
    assert cuts == [0.0]
    run(2.0, 7.0)
    assert cuts == [0.0, 2.0]
    run(2.0, 7.0)
    assert cuts == [0.0, 2.0]
