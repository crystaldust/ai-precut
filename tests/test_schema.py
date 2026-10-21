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


# ---------------------------------------------------------------- M2 目标时长
@pytest.mark.parametrize("raw, expected", [(175, 175), ("240", 240), (59.6, 60), (" 90 ", 90),
                                           (10, 10), (3600, 3600)])
def test_check_target_duration_accepts(raw, expected):
    assert schema.check_target_duration(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 0, -5, 9, 3601, True, float("nan"),
                                 float("inf"), "inf", [1]])
def test_check_target_duration_rejects(raw):
    with pytest.raises(ValueError, match="目标时长"):
        schema.check_target_duration(raw)


def test_write_json_compact_when_indent_none(tmp_path):
    # 剪映草稿沿用紧凑格式（to_jianying 复用本函数，GL-13）
    p = tmp_path / "d.json"
    schema.write_json(p, {"a": [1, 2], "中": "文"}, indent=None)
    assert p.read_text(encoding="utf-8") == '{"a": [1, 2], "中": "文"}'
    assert [x.name for x in tmp_path.iterdir()] == ["d.json"]


# ---------------------------------------------------------------- M8：KI-26 / KI-21
def test_default_project_does_not_share_mutable_defaults():
    a = schema.default_project("a", "/x")
    a["calibration"]["tone"] = "t"
    a["brief"]["k"] = 1
    b = schema.default_project("b", "/y")
    assert b["calibration"] == {} and b["brief"] == {}
    assert schema.DEFAULTS["calibration"] == {} and schema.DEFAULTS["brief"] == {}


def test_migrate_fills_defaults_with_fresh_copies():
    cfg, _ = schema.migrate({"name": "n", "material": "m", "schema_version": 2})
    assert cfg["brief"] is not schema.DEFAULTS["brief"]
    assert cfg["calibration"] is not schema.DEFAULTS["calibration"]


def test_read_json_missing_returns_default(tmp_path):
    assert schema.read_json(tmp_path / "none.json", default=None) is None
    assert schema.read_json(tmp_path / "none.json", default={"a": 1}) == {"a": 1}


def test_read_json_missing_without_default_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        schema.read_json(tmp_path / "none.json")


def test_read_json_corrupt_raises_with_file_name(tmp_path):
    p = tmp_path / "shots.json"
    p.write_text("{坏", encoding="utf-8")
    with pytest.raises(schema.CorruptJSON, match="shots.json"):
        schema.read_json(p, default=None)
    assert issubclass(schema.CorruptJSON, ValueError)


def test_read_json_corrupt_message_does_not_leak_content(tmp_path):
    p = tmp_path / "segments.json"
    p.write_text('{"secret": "转写原文', encoding="utf-8")
    with pytest.raises(schema.CorruptJSON) as exc:
        schema.read_json(p)
    assert "转写原文" not in str(exc.value)


def test_read_json_wrong_top_level_type(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(schema.CorruptJSON, match="a.json"):
        schema.read_json(p, expect=dict)
    assert schema.read_json(p, expect=list) == []
    assert schema.read_json(p, expect=None) == []


def test_read_json_bad_utf8(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes(b"\xff\xfe")
    with pytest.raises(schema.CorruptJSON):
        schema.read_json(p, default=None)


def test_read_json_unreadable_is_corrupt(tmp_path):
    d = tmp_path / "dir.json"
    d.mkdir()  # 读目录 → IsADirectoryError（OSError），有文件但读不了
    with pytest.raises(schema.CorruptJSON):
        schema.read_json(d, default=None)


def test_load_corrupt_project_raises_corrupt_json(tmp_path):
    p = tmp_path / "project.json"
    p.write_text("{坏", encoding="utf-8")
    with pytest.raises(schema.CorruptJSON, match="project.json"):
        schema.load(p)


# ---------------------------------------------------------------- KI-51：fsync、陈旧 tmp、跨进程锁
def test_write_json_fsyncs_file(tmp_path, monkeypatch):
    import os
    seen = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (seen.append(fd), real(fd)))
    schema.write_json(tmp_path / "a.json", {"x": 1})
    assert seen  # 至少文件本身 fsync 过
    assert json.loads((tmp_path / "a.json").read_text()) == {"x": 1}


def _tmp_like(tmp_path, age_s):
    import os
    import time
    t = tmp_path / ".project.json.0123456789abcdef0123456789abcdef.tmp"
    t.write_text("{half")
    old = time.time() - age_s
    os.utime(t, (old, old))
    return t


def test_stale_tmp_from_killed_writer_is_cleaned(tmp_path):
    t = _tmp_like(tmp_path, 3600)
    schema.write_json(tmp_path / "project.json", {"x": 1})
    assert not t.exists()


def test_fresh_foreign_tmp_is_kept(tmp_path):
    t = _tmp_like(tmp_path, 5)
    schema.write_json(tmp_path / "project.json", {"x": 1})
    assert t.exists()


def test_update_serializes_across_processes(tmp_path):
    import multiprocessing as mp
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import schema_workers
    path = tmp_path / "project.json"
    schema.write_json(path, {"n": 0})
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=schema_workers.bump_counter, args=(str(path), 50)) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    assert [p.exitcode for p in procs] == [0, 0]
    assert json.loads(path.read_text())["n"] == 100


def test_update_returns_new_value_and_keeps_lock_file_beside(tmp_path):
    path = tmp_path / "project.json"
    schema.write_json(path, {"a": 1})
    new = schema.update(path, lambda c: {**c, "b": 2})
    assert new == {"a": 1, "b": 2} == json.loads(path.read_text())


def test_update_falls_back_when_flock_unsupported(tmp_path, monkeypatch):
    from pipeline import filelock
    def nope(*a):
        raise OSError(45, "Operation not supported")
    monkeypatch.setattr(filelock, "flock", nope)
    path = tmp_path / "project.json"
    schema.write_json(path, {"a": 1})
    assert schema.update(path, lambda c: {**c, "a": 2}) == {"a": 2}


# ---------------------------------------------------------------- KI-69：新建项目原子占位
def test_create_json_exclusive_refuses_existing(tmp_path):
    path = tmp_path / "project.json"
    schema.create_json_exclusive(path, {"who": "me"})
    with pytest.raises(FileExistsError):
        schema.create_json_exclusive(path, {"who": "other"})
    assert json.loads(path.read_text()) == {"who": "me"}
    assert [p.name for p in tmp_path.iterdir()] == ["project.json"]  # 不留临时文件


# ---------------------------------------------------------------- KI-37：中间产物版本号
def test_stamp_adds_artifact_schema_without_mutating():
    obj = {"a": 1}
    out = schema.stamp(obj)
    assert out == {"a": 1, "artifact_schema": schema.ARTIFACT_SCHEMA} and obj == {"a": 1}


def test_lock_file_is_private_and_not_followed(tmp_path):  # 审查修复 L16
    import os
    import stat
    path = tmp_path / "project.json"
    with schema.locked(path):
        pass
    assert stat.S_IMODE(schema.lock_path(path).stat().st_mode) == 0o600
    other = tmp_path / "victim.json"
    other.write_text("keep")
    schema.lock_path(path).unlink()
    os.symlink(other, schema.lock_path(path))
    with pytest.raises(OSError):
        with schema.locked(path):
            pass
    assert other.read_text() == "keep"
