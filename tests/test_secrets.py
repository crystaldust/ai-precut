import json
import stat

import pytest

from pipeline import secrets
from platform_marks import IS_POSIX, posix_only


def test_mask_keeps_edges():  # KI-67：规格变更——18 位只留后 4，短 Key 连长度也不暴露
    assert secrets.mask("AKLTabcdefghij9f2a") == "****9f2a"
    assert secrets.mask("short") == "********"
    assert secrets.mask(None) == ""


@pytest.mark.parametrize("n", [12, 16, 23, 24, 48])
def test_mask_tiers(n):
    value = ("abcdefghijklmnop" * 4)[:n - 4] + "wxyz"
    masked = secrets.mask(value)
    if n < secrets.MASK_TAIL_MIN:
        assert masked == "********"
    elif n < secrets.MASK_FULL_MIN:
        assert masked == "****wxyz"
    else:
        assert masked == value[:4] + "****wxyz"
    shown = len(masked.replace("*", ""))
    assert shown <= n // 3  # 最多暴露三分之一


def test_get_strips_keychain_and_file_values(file_env, monkeypatch):
    class FakeKeyring:
        def __init__(self, value):
            self.value = value

        def get_password(self, service, provider):
            return self.value

    monkeypatch.setattr(secrets, "_keyring", lambda: FakeKeyring("sk-abcdefgh12345678\n"))
    assert secrets.get("deepseek") == "sk-abcdefgh12345678"
    monkeypatch.setattr(secrets, "_keyring", lambda: FakeKeyring("   \n"))
    assert secrets.get("deepseek") is None
    monkeypatch.setattr(secrets, "_keyring", lambda: None)
    file_env.mkdir(parents=True, exist_ok=True)
    (file_env / "credentials.json").write_text(json.dumps({"mediakit": " AKLTabcdefgh1234\n"}))
    assert secrets.get("mediakit") == "AKLTabcdefgh1234"
    (file_env / "credentials.json").write_text(json.dumps({"mediakit": "  \t"}))
    assert secrets.get("mediakit") is None


def test_peek_strips(file_env):
    file_env.mkdir(parents=True, exist_ok=True)
    (file_env / "credentials.json").write_text(json.dumps({"deepseek": "sk-abcdefgh12345678\r\n"}))
    assert secrets.peek("deepseek") == "sk-abcdefgh12345678"
    (file_env / "credentials.json").write_text(json.dumps({"deepseek": "   "}))
    assert secrets.peek("deepseek") is None


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
    if IS_POSIX:  # Windows 没有 POSIX 权限位
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
@posix_only("临时凭证文件 0600 权限位")
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


# ---------------------------------------------------------------- KI-28：共享目录不 chmod；删除时屏蔽旧版文件
@posix_only("目录 / 文件权限位")
def test_existing_shared_dir_mode_untouched(file_env):
    file_env.mkdir(parents=True)
    file_env.chmod(0o755)
    secrets.set("mediakit", "AKLTtest123456789")
    assert stat.S_IMODE(file_env.stat().st_mode) == 0o755
    assert stat.S_IMODE((file_env / "credentials.json").stat().st_mode) == 0o600


@posix_only("目录权限位 0700")
def test_new_config_dir_is_0700(file_env):
    secrets.set("mediakit", "AKLTtest123456789")
    assert stat.S_IMODE(file_env.stat().st_mode) == 0o700


@pytest.fixture
def legacy(file_env, tmp_path, monkeypatch):
    f = tmp_path / "legacy" / "api_key"
    f.parent.mkdir()
    f.write_text("AKLTlegacy12345678\n")
    monkeypatch.setattr(secrets, "LEGACY_FILES", {"mediakit": f})
    return f


def test_delete_also_hides_legacy_key(legacy):
    assert secrets.get("mediakit") == "AKLTlegacy12345678"
    secrets.delete("mediakit")
    assert secrets.get("mediakit") is None
    assert secrets.peek("mediakit") is None
    assert secrets.status()["mediakit"]["source"] == ""
    assert legacy.read_text() == "AKLTlegacy12345678\n"  # 别的工具的文件不删


def test_set_after_delete_restores_normal_priority(legacy):
    secrets.delete("mediakit")
    secrets.set("mediakit", "AKLTnew1234567890")
    assert secrets.get("mediakit") == "AKLTnew1234567890"
    secrets.delete("mediakit")
    assert secrets.get("mediakit") is None  # 再删一次仍然屏蔽旧版文件
    data = _ignore_file(legacy)
    assert data == ["mediakit"]


def _ignore_file(legacy) -> list:
    return json.loads((secrets.config_dir() / secrets.LEGACY_IGNORE_FILE).read_text())


def test_corrupt_ignore_file_fails_closed(legacy):  # 审查修复 L18：坏了就当已屏蔽（不读明文旧文件）
    secrets.config_dir().mkdir(parents=True, exist_ok=True)
    (secrets.config_dir() / secrets.LEGACY_IGNORE_FILE).write_text("{oops")
    assert secrets.get("mediakit") is None


def test_status_reports_hidden_legacy_file(legacy):
    secrets.delete("mediakit")
    st = secrets.status()["mediakit"]
    assert st["configured"] is False and st["legacy_file"] is True


def test_legacy_file_note_only_when_ignored(legacy, monkeypatch):
    monkeypatch.setenv("MEDIAKIT_API_KEY", "AKLTfromenv12345678")
    assert secrets.status()["mediakit"]["legacy_file"] is False  # 只是被环境变量盖住，没有屏蔽
