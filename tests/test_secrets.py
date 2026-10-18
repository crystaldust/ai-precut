import json
import stat

import pytest

from pipeline import secrets


def test_mask_keeps_edges():
    assert secrets.mask("AKLTabcdefghij9f2a") == "AKLT****9f2a"
    assert secrets.mask("short") == "*****"
    assert secrets.mask(None) == ""


@pytest.fixture
def file_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CUT_SECRETS", "file")
    monkeypatch.setenv("AI_CUT_CONFIG_DIR", str(tmp_path / "cfg"))
    for var in secrets.ENV_KEYS.values():
        monkeypatch.delenv(var, raising=False)
    # 隔离历史遗留文件，避免读到本机真实 key
    monkeypatch.setattr(secrets, "LEGACY_FILES", {}, raising=False)
    return tmp_path / "cfg"


def test_file_backend_roundtrip(file_env):
    assert secrets.get("mediakit") is None
    backend = secrets.set("mediakit", "AKLTtest123456789")
    assert backend == "file"
    assert secrets.get("mediakit") == "AKLTtest123456789"
    cred = file_env / "credentials.json"
    assert cred.exists()
    assert oct(stat.S_IMODE(cred.stat().st_mode)) == oct(0o600)
    secrets.delete("mediakit")
    assert secrets.get("mediakit") is None


def test_env_overrides_store(file_env, monkeypatch):
    secrets.set("mediakit", "from-file")
    monkeypatch.setenv("MEDIAKIT_API_KEY", "from-env")
    assert secrets.get("mediakit") == "from-env"
    assert secrets.status()["mediakit"]["source"] == "env"


def test_legacy_mediakit_file_is_read(file_env, monkeypatch, tmp_path):
    legacy = tmp_path / "legacy" / "api_key"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("AKLTlegacykey123", encoding="utf-8")
    monkeypatch.setitem(secrets.LEGACY_FILES, "mediakit", legacy)
    assert secrets.get("mediakit") == "AKLTlegacykey123"
    assert secrets.status()["mediakit"]["source"] == "legacy"


def test_status_masks(file_env):
    secrets.set("deepseek", "sk-abcdefghijk")
    st = secrets.status()
    assert st["deepseek"]["configured"] is True
    assert "abcdefghijk" not in json.dumps(st)
    assert st["mediakit"]["configured"] is False
