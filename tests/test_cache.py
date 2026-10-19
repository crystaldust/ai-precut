"""KI-33 / D4：「清理缓存」只删可重建的中间产物。"""
import os

from pipeline import cache, media_io


def _f(pdir, rel, size=10):
    p = pdir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def _project(tmp_path):
    pdir = tmp_path / "p"
    _f(pdir, "project.json", 5)
    _f(pdir, "work/clips/S01.mp4", 100)
    _f(pdir, "work/clips/S01.mp4.done", 3)
    _f(pdir, "work/clips/manifest.json", 7)
    _f(pdir, "work/proxy.mp4", 1000)
    _f(pdir, "work/audio/asr.wav", 500)
    _f(pdir, "work/audio/asr.wav.done", 4)
    _f(pdir, f"work/{media_io.PARTIAL_DIR}/proxy.999999.deadbeef.mp4", 30)
    _f(pdir, "work/.asr.partial-deadbeef.wav", 20)
    _f(pdir, "output/v1/preview.mp4", 900)
    _f(pdir, "output/v1/timeline.json", 9)
    return pdir


def test_items_list_clips_and_partials(tmp_path):
    pdir = _project(tmp_path)
    items = {i["path"]: i["bytes"] for i in cache.items(pdir)}
    assert items["work/clips"] == 110
    assert items[f"work/{media_io.PARTIAL_DIR}"] == 30
    assert items["work/.asr.partial-deadbeef.wav"] == 20
    assert "work/audio/asr.wav" not in items  # 转写 / 声音分析没完成：音轨还要用
    assert all(i["label"] for i in cache.items(pdir))


def test_wav_listed_only_when_transcript_and_audio_done(tmp_path):
    pdir = _project(tmp_path)
    _f(pdir, "work/transcript_raw.json")
    _f(pdir, "work/segments_audio.json")
    items = {i["path"]: i["bytes"] for i in cache.items(pdir)}
    assert items["work/audio/asr.wav"] == 504  # 连同完成标记


def test_clean_keeps_proxy_preview_output_and_json(tmp_path):
    pdir = _project(tmp_path)
    _f(pdir, "work/transcript_raw.json")
    _f(pdir, "work/segments_audio.json")
    freed = cache.clean(pdir)
    assert freed == 110 + 30 + 20 + 504
    assert not (pdir / "work/clips").exists() and not (pdir / "work/audio/asr.wav").exists()
    for keep in ("work/proxy.mp4", "output/v1/preview.mp4", "output/v1/timeline.json",
                 "project.json", "work/transcript_raw.json"):
        assert (pdir / keep).exists()
    assert cache.items(pdir) == []


def test_symlinks_are_not_followed(tmp_path):
    pdir = _project(tmp_path)
    outside = tmp_path / "outside"
    _f(outside, "precious.mp4", 50)
    os.symlink(outside, pdir / "work/clips/link")
    os.symlink(outside / "precious.mp4", pdir / "work/clips/file_link.mp4")
    assert {i["path"]: i["bytes"] for i in cache.items(pdir)}["work/clips"] == 110
    cache.clean(pdir)
    assert (outside / "precious.mp4").exists()


def test_clips_dir_that_is_a_symlink_is_ignored(tmp_path):
    pdir = tmp_path / "p"
    outside = tmp_path / "outside"
    _f(outside, "precious.mp4", 50)
    (pdir / "work").mkdir(parents=True)
    os.symlink(outside, pdir / "work/clips")
    assert cache.items(pdir) == []
    cache.clean(pdir)
    assert (outside / "precious.mp4").exists()


def test_empty_project_has_nothing(tmp_path):
    (tmp_path / "p/work").mkdir(parents=True)
    assert cache.items(tmp_path / "p") == [] and cache.clean(tmp_path / "p") == 0


def test_empty_partial_dir_is_cleaned(tmp_path):  # 审查修复 M4：atomic_output 不再自己 rmdir
    pdir = tmp_path / "p"
    (pdir / f"work/{media_io.PARTIAL_DIR}").mkdir(parents=True)
    assert [i["path"] for i in cache.items(pdir)] == [f"work/{media_io.PARTIAL_DIR}"]
    cache.clean(pdir)
    assert not (pdir / f"work/{media_io.PARTIAL_DIR}").exists()


# ---------------------------------------------------------------- 审查修复 L12 / L15
def test_file_vanishing_during_listing_is_ignored(tmp_path, monkeypatch):
    pdir = _project(tmp_path)
    real = cache._file_size
    gone = pdir / "work/clips/S01.mp4"

    def flaky(p):
        if p == gone:
            raise FileNotFoundError(p)
        return real(p)

    monkeypatch.setattr(cache, "_file_size", flaky)
    items = {i["path"]: i["bytes"] for i in cache.items(pdir)}
    assert items["work/clips"] == 10


def test_symlinked_work_dir_is_not_cleaned(tmp_path):
    outside = tmp_path / "outside_work"
    _f(outside, "clips/S01.mp4", 50)
    pdir = tmp_path / "p"
    pdir.mkdir()
    os.symlink(outside, pdir / "work")
    assert cache.items(pdir) == []
    cache.clean(pdir)
    assert (outside / "clips/S01.mp4").exists()
