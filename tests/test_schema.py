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
