"""KI-33：磁盘空间预检（D5：按码率估算 + 1 GB 余量）。"""
from types import SimpleNamespace

from pipeline import diskspace

GB = 1024 ** 3


def fake_usage(free):
    return lambda path: SimpleNamespace(total=100 * GB, used=0, free=free)


def test_need_grows_with_media_length():
    assert diskspace.need_for_prepare(0) == diskspace.MARGIN_BYTES
    assert diskspace.need_for_prepare(3600) > diskspace.need_for_prepare(60) > diskspace.MARGIN_BYTES
    assert diskspace.need_for_build(180, 180) > diskspace.need_for_build(180, 0) > diskspace.MARGIN_BYTES


def test_enough_space_is_none(tmp_path):
    assert diskspace.shortfall(tmp_path, 2 * GB, usage=fake_usage(3 * GB)) is None


def test_exactly_enough_is_none(tmp_path):
    assert diskspace.shortfall(tmp_path, 2 * GB, usage=fake_usage(2 * GB)) is None


def test_not_enough_explains_need_and_free(tmp_path):
    msg = diskspace.shortfall(tmp_path, 5 * GB, usage=fake_usage(1 * GB))
    assert msg and "5.0 GB" in msg and "1.0 GB" in msg


def test_missing_path_checks_nearest_existing_parent(tmp_path):
    seen = []

    def usage(path):
        seen.append(path)
        return SimpleNamespace(total=1, used=0, free=10 * GB)

    assert diskspace.shortfall(tmp_path / "a/b/c", GB, usage=usage) is None
    assert seen == [tmp_path]


def test_unreadable_usage_does_not_block(tmp_path):
    def boom(path):
        raise OSError("nope")
    assert diskspace.shortfall(tmp_path, GB, usage=boom) is None


# ---------------------------------------------------------------- 审查修复 M5：只算还要写的
def test_nothing_to_write_needs_nothing(tmp_path):
    assert diskspace.need_for_prepare(3600, wav=False, proxy=False) == 0
    assert diskspace.need_for_build(0, 0) == 0
    assert diskspace.shortfall(tmp_path, 0, usage=lambda p: pytest_fail()) is None


def pytest_fail():
    raise AssertionError("不需要写盘时不应查磁盘")


def test_only_missing_parts_counted():
    full = diskspace.need_for_prepare(3600)
    wav_only = diskspace.need_for_prepare(3600, proxy=False)
    assert diskspace.MARGIN_BYTES < wav_only < full
    assert diskspace.need_for_build(100, 0) < diskspace.need_for_build(100, 100)
