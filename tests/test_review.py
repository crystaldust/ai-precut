import json

from pipeline import review


def test_set_level_and_load(tmp_path):
    review.set_level(tmp_path, "S001", 3)
    data = review.load(tmp_path)
    assert data["S001"]["level"] == 3
    assert "at" in data["S001"]


def test_invalid_level_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        review.set_level(tmp_path, "S001", 9)


def test_set_must_and_clear(tmp_path):
    review.set_must(tmp_path, "S002", True)
    assert review.load(tmp_path)["S002"]["must_keep"] is True
    review.clear(tmp_path, "S002")
    assert "S002" not in review.load(tmp_path)


def test_apply_merges_overrides():
    segs = [{"id": "S001", "level": 2, "level_reason": "待定"},
            {"id": "S002", "level": 3, "level_reason": "含关键信息"}]
    merged = review.apply(segs, {"S001": {"level": 1, "must_keep": True}})
    assert merged[0]["level"] == 1
    assert merged[0]["base_level"] == 2
    assert merged[0]["override"] is True
    assert merged[0]["must_keep"] is True
    assert merged[1]["override"] is False
    assert merged[1]["level_reason"] == "含关键信息"


def test_apply_without_overrides_keeps_original():
    segs = [{"id": "S001", "level": 2, "level_reason": "x"}]
    merged = review.apply(segs, {})
    assert merged[0]["level"] == 2 and merged[0]["must_keep"] is False


# ---- GL-18：损坏不当空、读改写串行 ----

def test_load_missing_returns_empty(tmp_path):
    assert review.load(tmp_path) == {}


def test_load_corrupt_raises(tmp_path):
    import pytest
    (tmp_path / "overrides.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt, match="overrides.json"):
        review.load(tmp_path)


def test_load_non_dict_raises(tmp_path):
    import pytest
    (tmp_path / "overrides.json").write_text("[1,2]", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.load(tmp_path)


def test_set_level_on_corrupt_keeps_file(tmp_path):
    import pytest
    f = tmp_path / "overrides.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.set_level(tmp_path, "S001", 3)
    assert f.read_text(encoding="utf-8") == "{bad"


def test_set_must_on_corrupt_keeps_file(tmp_path):
    import pytest
    f = tmp_path / "overrides.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.set_must(tmp_path, "S001", True)
    assert f.read_text(encoding="utf-8") == "{bad"


def test_clear_one_on_corrupt_keeps_file(tmp_path):
    import pytest
    f = tmp_path / "overrides.json"
    f.write_text("{bad", encoding="utf-8")
    with pytest.raises(review.OverridesCorrupt):
        review.clear(tmp_path, "S001")
    assert f.read_text(encoding="utf-8") == "{bad"


def test_concurrent_set_level_no_lost_update(tmp_path):
    import threading
    errors = []

    def worker(i):
        try:
            review.set_level(tmp_path, f"S{i:03d}", 3)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(review.load(tmp_path)) == 50


def test_overrides_corrupt_is_value_error():
    assert issubclass(review.OverridesCorrupt, ValueError)
