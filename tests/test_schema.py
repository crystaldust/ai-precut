import json

import pytest

from pipeline import schema


def test_migrate_v0_adds_version_and_defaults():
    old = {"name": "p1", "material": "/tmp/a.mp4"}
    cfg, changes = schema.migrate(old)
    assert cfg["schema_version"] == 2
    assert cfg["calibration"] == {}
    assert cfg["title"] == "p1"
    assert cfg["preset"] == "纪实3min"
    assert "v0→v1" in changes


def test_migrate_rejects_newer_version():
    with pytest.raises(schema.SchemaTooNew):
        schema.migrate({"name": "p", "material": "m", "schema_version": 99})


def test_v1_project_gains_calibration():
    cfg, changes = schema.migrate({"name": "p", "material": "m", "schema_version": 1})
    assert cfg["schema_version"] == 2
    assert "calibration" in cfg
    assert "v1→v2" in changes


def test_migrate_requires_name_and_material():
    with pytest.raises(ValueError):
        schema.migrate({"schema_version": 1})


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "project.json"
    cfg = schema.default_project("p1", "/tmp/a.mp4", title="片名")
    schema.save(path, cfg)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    loaded = schema.load(path)
    assert loaded["title"] == "片名"
    assert loaded["schema_version"] == schema.CURRENT_SCHEMA
    assert not list(tmp_path.glob("*.tmp"))


def test_default_project_has_all_defaults():
    cfg = schema.default_project("p", "m")
    for key in schema.DEFAULTS:
        assert key in cfg


# ---- GL-18：唯一临时文件的原子写 ----

def test_write_json_concurrent_same_path(tmp_path):
    import threading

    p = tmp_path / "x.json"
    errors: list[BaseException] = []

    def worker(n):
        try:
            for _ in range(25):
                schema.write_json(p, {"i": n})
        except BaseException as exc:  # noqa: BLE001 - 收集给断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert "i" in json.loads(p.read_text(encoding="utf-8"))
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_save_concurrent_same_path(tmp_path):
    import threading

    p = tmp_path / "project.json"
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(25):
                schema.save(p, {"name": "p", "material": "m"})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert schema.load(p)["name"] == "p"


# ---- GL-06：项目名 / 版本号 / 镜头 id 白名单 ----

@pytest.mark.parametrize("name", ["九月 一号", "2026-09-15_探店", "x" * 100])
def test_check_project_name_accepts_chinese_and_space(name):
    assert schema.check_project_name(name) == name


@pytest.mark.parametrize("name", [
    "", "   ", "-h", "--help", ".hidden", "..", "a/b", "a\\b", "a\x00b", "a\nb",
    "x" * 101, None, 123,
])
def test_check_project_name_rejects(name):
    with pytest.raises(ValueError):
        schema.check_project_name(name)


@pytest.mark.parametrize("v", ["v1", "v12"])
def test_check_version_accepts(v):
    assert schema.check_version(v) == v


@pytest.mark.parametrize("v", ["../x", "v1/../..", "1", "v", "--no-draft", "", None, ".."])
def test_check_version_rejects(v):
    with pytest.raises(ValueError):
        schema.check_version(v)


def test_check_shot_ids_accepts():
    schema.check_shot_ids([{"id": "sh01"}, {"id": "sel02"}])
    schema.check_shot_ids([])


def test_check_shot_ids_duplicate_names_the_id():
    with pytest.raises(ValueError, match="sh03"):
        schema.check_shot_ids([{"id": "sh03"}, {"id": "sh03"}])


@pytest.mark.parametrize("shots", [
    [{"id": "../x"}], [{"id": ""}], [{"id": None}], [{"id": "a" * 33}],
    [{}], ["sh01"], [{"id": 3}], {"id": "sh01"}, None,
])
def test_check_shot_ids_rejects(shots):
    with pytest.raises(ValueError):
        schema.check_shot_ids(shots)


# ---- 审查修复：ASCII 版本号、字节上限、首尾空格、片名、镜头数值 ----

@pytest.mark.parametrize("v", ["v٣", "v１", "v1\n"])
def test_check_version_rejects_non_ascii_digits(v):
    with pytest.raises(ValueError):
        schema.check_version(v)


@pytest.mark.parametrize("name", [" a", "a ", "a　", "\ta", "九" * 86, "é" * 100 + "x"])
def test_check_project_name_rejects_whitespace_edges_and_bytes(name):
    with pytest.raises(ValueError, match="项目名"):
        schema.check_project_name(name)


def test_check_project_name_byte_limit_boundary():
    assert schema.check_project_name("九" * 85)  # 255 字节
    assert schema.check_project_name("a b")       # 中间的空格可以


@pytest.mark.parametrize("title", ["九月一号", "-开头也行", "a b"])
def test_check_title_accepts(title):
    assert schema.check_title(title) == title


@pytest.mark.parametrize("title", ["", "a/b", "a\\b", "a\x00b", "a\nb", "x" * 101,
                                   "九" * 86, None, 123, ["x"]])
def test_check_title_rejects(title):
    with pytest.raises(ValueError, match="片名"):
        schema.check_title(title)


def test_clean_shots_normalizes_and_returns_new_list():
    raw = [{"id": "sh01", "in": 0, "out": 1.23456, "sub": "a", "extra": 1},
           {"id": "sh02", "in": "2", "out": 3, "sub": None}]
    out = schema.clean_shots(raw)
    assert out == [{"id": "sh01", "in": 0.0, "out": 1.235, "sub": "a", "note": ""},
                   {"id": "sh02", "in": 2.0, "out": 3.0, "sub": "", "note": ""}]
    assert "note" not in raw[0]  # 不改输入


@pytest.mark.parametrize("shot", [
    {"in": "abc", "out": 1}, {"in": None, "out": 1}, {"in": 0, "out": [1]},
    {"in": float("nan"), "out": 1}, {"in": 0, "out": float("inf")},
    {"in": 1, "out": 1}, {"in": 2, "out": 1}, {"in": -1, "out": 1},
    {"in": True, "out": 2}, {"in": 0, "out": 1, "sub": 3}, {"in": 0, "out": 1, "note": ["x"]},
    {"out": 1},
])
def test_clean_shots_rejects_bad_values(shot):
    with pytest.raises(ValueError):
        schema.clean_shots([{"id": "sh01", **shot}])


def test_clean_shots_rejects_bad_ids():
    with pytest.raises(ValueError, match="重复"):
        schema.clean_shots([{"id": "a", "in": 0, "out": 1}, {"id": "a", "in": 1, "out": 2}])


def test_ensure_supported_rejects_too_new():
    with pytest.raises(schema.SchemaTooNew):
        schema.ensure_supported({"schema_version": schema.CURRENT_SCHEMA + 1})
    schema.ensure_supported({"schema_version": schema.CURRENT_SCHEMA})
    schema.ensure_supported({})
