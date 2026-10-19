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


# ---------------------------------------------------------------- M4 审查修复 2（LOW-10，KI-28 的创建权限部分）
def test_cred_temp_file_created_0600_with_unique_name(file_env, monkeypatch):
    import os
    import stat as st
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((os.path.basename(src), st.S_IMODE(os.stat(src).st_mode)))
        return real_replace(src, dst)

    monkeypatch.setattr(secrets.os, "replace", spy)
    secrets.set("deepseek", "sk-one-123456")
    secrets.set("mediakit", "AKLT-two-123456")
    assert [m for _, m in seen] == [0o600, 0o600]  # 一创建就是 0600，没有可读窗口
    names = [n for n, _ in seen]
    assert len(set(names)) == 2 and "credentials.tmp" not in names


def test_cred_write_failure_leaves_no_temp(file_env, monkeypatch):
    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(secrets.os, "replace", boom)
    with pytest.raises(OSError):
        secrets.set("deepseek", "sk-one-123456")
    assert [p.name for p in file_env.iterdir() if p.name.endswith(".tmp")] == []


class StickyKeyring:
    """delete_password 静默失败（钥匙串被锁 / 拒绝）的钥匙串。"""

    def __init__(self):
        self.store = {}

    def set_password(self, svc, k, v):
        self.store[k] = v

    def get_password(self, svc, k):
        return self.store.get(k)

    def delete_password(self, svc, k):
        raise RuntimeError("locked")


def test_delete_raises_when_keychain_still_has_key(file_env, monkeypatch):
    kr = StickyKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    secrets.set("deepseek", "sk-sticky-12345")
    with pytest.raises(secrets.SecretDeleteError):
        secrets.delete("deepseek")


def test_delete_ok_when_gone(file_env):
    secrets.set("deepseek", "sk-gone-123456")
    secrets.delete("deepseek")
    assert secrets.get("deepseek") is None
