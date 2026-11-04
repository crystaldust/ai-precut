import json
import stat
import threading
import time

import pytest
from keyring.errors import PasswordDeleteError

from pipeline import secrets
from platform_marks import IS_POSIX, posix_only


class FakeKeyring:
    """内存钥匙串：按 (service, username) 存取，记录 get_password 次数，可指定写入失败。"""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.get_calls = 0
        self.fail_set = False

    def get_password(self, svc, k):
        self.get_calls += 1
        return self.store.get((svc, k))

    def set_password(self, svc, k, v):
        if self.fail_set:
            raise RuntimeError("denied")
        self.store[(svc, k)] = v

    def delete_password(self, svc, k):
        if (svc, k) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(svc, k)]


BUNDLE = ("AI粗剪", "api-keys")


@pytest.fixture(autouse=True)
def _fresh_secrets_cache():
    secrets._reset_cache()
    yield
    secrets._reset_cache()


@pytest.fixture
def fake_kr(file_env, monkeypatch):
    kr = FakeKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    return kr


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
    def bundle_kr(value):
        kr = FakeKeyring()
        kr.store[(secrets.SERVICE, secrets.ACCOUNT)] = json.dumps({"deepseek": value})
        return kr

    kr = bundle_kr("sk-abcdefgh12345678\n")
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    assert secrets.get("deepseek") == "sk-abcdefgh12345678"
    secrets._reset_cache()
    kr = bundle_kr("   \n")
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
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


class StickyKeyring(FakeKeyring):
    """delete_password 静默失败（钥匙串被锁 / 拒绝）的钥匙串。"""

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


# ---------------------------------------------------------------- 钥匙串只存一条（打包成 JSON）
def test_constants():
    assert (secrets.SERVICE, secrets.ACCOUNT, secrets.LEGACY_SERVICE) == ("AI粗剪", "api-keys", "ai-cut")


def test_both_providers_share_one_item(fake_kr):
    assert secrets.set("mediakit", " AKLTone123456 ") == "keyring"
    assert secrets.set("deepseek", "sk-two-123456") == "keyring"
    assert list(fake_kr.store) == [BUNDLE]
    assert json.loads(fake_kr.store[BUNDLE]) == {"mediakit": "AKLTone123456", "deepseek": "sk-two-123456"}


def test_status_reads_keychain_once(fake_kr):
    fake_kr.store[BUNDLE] = json.dumps({"mediakit": "AKLTone123456", "deepseek": "sk-two-123456"})
    st = secrets.status()
    assert st["mediakit"]["source"] == "keyring" and st["deepseek"]["configured"] is True
    assert fake_kr.get_calls == 1
    assert secrets.get("deepseek") == "sk-two-123456"
    assert fake_kr.get_calls == 1  # 进程内缓存


def test_set_does_not_mutate_cached_bundle(fake_kr):
    secrets.set("mediakit", "AKLTone123456")
    before = secrets._cache
    secrets.set("deepseek", "sk-two-123456")
    assert before == {"mediakit": "AKLTone123456"}


def test_legacy_items_migrate_into_bundle(fake_kr):
    fake_kr.store[("ai-cut", "mediakit")] = "AKLTold123456"
    fake_kr.store[("ai-cut", "deepseek")] = "sk-old-123456"
    assert secrets.get("mediakit") == "AKLTold123456"
    assert secrets.get("deepseek") == "sk-old-123456"
    assert json.loads(fake_kr.store[BUNDLE]) == {"mediakit": "AKLTold123456", "deepseek": "sk-old-123456"}
    assert ("ai-cut", "mediakit") not in fake_kr.store and ("ai-cut", "deepseek") not in fake_kr.store


def test_migration_write_failure_keeps_legacy_items(fake_kr):
    fake_kr.fail_set = True
    fake_kr.store[("ai-cut", "mediakit")] = "AKLTold123456"
    fake_kr.store[("ai-cut", "deepseek")] = "sk-old-123456"
    assert secrets.get("mediakit") == "AKLTold123456"
    assert secrets.get("deepseek") == "sk-old-123456"
    assert BUNDLE not in fake_kr.store
    assert ("ai-cut", "mediakit") in fake_kr.store and ("ai-cut", "deepseek") in fake_kr.store


def test_failed_keychain_read_is_not_cached(file_env, monkeypatch):
    class Locked(FakeKeyring):
        def get_password(self, svc, k):
            self.get_calls += 1
            raise RuntimeError("locked")

    kr = Locked()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    assert secrets.get("deepseek") is None
    secrets.get("deepseek")
    assert kr.get_calls == 2


def test_delete_keeps_other_provider_then_removes_item(fake_kr):
    secrets.set("mediakit", "AKLTone123456")
    secrets.set("deepseek", "sk-two-123456")
    secrets.delete("mediakit")
    assert json.loads(fake_kr.store[BUNDLE]) == {"deepseek": "sk-two-123456"}
    assert secrets.get("deepseek") == "sk-two-123456" and secrets.get("mediakit") is None
    secrets.delete("deepseek")
    assert BUNDLE not in fake_kr.store
    assert secrets.get("deepseek") is None


def test_delete_also_removes_legacy_keychain_item(fake_kr):
    fake_kr.store[BUNDLE] = json.dumps({"deepseek": "sk-two-123456"})
    fake_kr.store[("ai-cut", "deepseek")] = "sk-stale-12345"
    secrets.delete("deepseek")
    assert ("ai-cut", "deepseek") not in fake_kr.store and BUNDLE not in fake_kr.store
    secrets._reset_cache()
    assert secrets.get("deepseek") is None  # 迁移不会让它复活


@pytest.mark.parametrize("raw", ["{oops SECRETRAW", "[1, 2]", '"SECRETRAW"', '{"deepseek": 5}', ""])
def test_corrupt_bundle_reads_as_empty_and_only_set_repairs_it(fake_kr, raw):
    fake_kr.store[BUNDLE] = raw
    fake_kr.store[("ai-cut", "deepseek")] = "sk-old-123456"  # 坏条目存在时不做迁移
    assert secrets.get("deepseek") is None
    assert "SECRETRAW" not in json.dumps(secrets.status())
    assert fake_kr.store[BUNDLE] == raw
    assert secrets.set("deepseek", "sk-new-123456") == "keyring"
    assert json.loads(fake_kr.store[BUNDLE]) == {"deepseek": "sk-new-123456"}
    secrets._reset_cache()
    assert secrets.get("deepseek") == "sk-new-123456"


def test_set_falls_back_to_file_when_keychain_write_fails(fake_kr, file_env):
    fake_kr.fail_set = True
    assert secrets.set("deepseek", "sk-two-123456") == "file"
    assert secrets.get("deepseek") == "sk-two-123456"


# ---------------------------------------------------------------- 审查修复：跨进程 / 迁移竞态 / 顺序
def test_set_merges_into_fresh_item_not_cache(fake_kr):
    secrets.set("mediakit", "AKLTone123456")  # 缓存已建立
    fake_kr.store[BUNDLE] = json.dumps({"mediakit": "AKLTone123456", "deepseek": "sk-other-proc1"})  # 另一进程写的
    secrets.set("mediakit", "AKLTtwo123456")
    assert json.loads(fake_kr.store[BUNDLE]) == {"mediakit": "AKLTtwo123456", "deepseek": "sk-other-proc1"}


def test_delete_merges_into_fresh_item_not_cache(fake_kr):
    secrets.set("mediakit", "AKLTone123456")
    fake_kr.store[BUNDLE] = json.dumps({"mediakit": "AKLTone123456", "deepseek": "sk-other-proc1"})
    secrets.delete("mediakit")
    assert json.loads(fake_kr.store[BUNDLE]) == {"deepseek": "sk-other-proc1"}


def test_migration_aborts_when_bundle_appears_meanwhile(fake_kr):
    other = json.dumps({"deepseek": "sk-other-proc1"})
    fake_kr.store[("ai-cut", "mediakit")] = "AKLTold123456"
    real_get = fake_kr.get_password
    seen = {"n": 0}

    def racing_get(svc, k):
        if (svc, k) == BUNDLE:
            seen["n"] += 1
            if seen["n"] >= 2:  # 第一次读时还没有，写之前再读就出现了
                fake_kr.store[BUNDLE] = other
        return real_get(svc, k)

    fake_kr.get_password = racing_get
    assert secrets.get("deepseek") == "sk-other-proc1"
    assert fake_kr.store[BUNDLE] == other  # 没覆盖
    assert ("ai-cut", "mediakit") in fake_kr.store  # 没删旧条目


def test_migration_skipped_when_any_legacy_read_fails(fake_kr):
    fake_kr.store[("ai-cut", "mediakit")] = "AKLTold123456"
    real_get = fake_kr.get_password

    def flaky(svc, k):
        if (svc, k) == ("ai-cut", "deepseek"):
            raise RuntimeError("locked")
        return real_get(svc, k)

    fake_kr.get_password = flaky
    assert secrets.get("mediakit") == "AKLTold123456"
    assert BUNDLE not in fake_kr.store and ("ai-cut", "mediakit") in fake_kr.store
    calls = fake_kr.get_calls
    secrets.get("mediakit")
    assert fake_kr.get_calls > calls  # 没缓存，下次重试


def test_unknown_bundle_keys_survive_rewrite_but_are_not_exposed(fake_kr):
    fake_kr.store[BUNDLE] = json.dumps({"mediakit": "AKLTone123456", "futureprov": "zzz-future"})
    assert secrets.get("mediakit") == "AKLTone123456"
    secrets.set("deepseek", "sk-two-123456")
    assert json.loads(fake_kr.store[BUNDLE]) == {
        "mediakit": "AKLTone123456", "futureprov": "zzz-future", "deepseek": "sk-two-123456"}
    secrets.delete("deepseek")
    assert json.loads(fake_kr.store[BUNDLE]) == {"mediakit": "AKLTone123456", "futureprov": "zzz-future"}
    assert "futureprov" not in json.dumps(secrets.status())


def test_delete_cleans_file_and_ignores_legacy_even_when_keychain_refuses(legacy, monkeypatch):
    kr = StickyKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    secrets.set("mediakit", "AKLTkeychain1234")
    secrets.config_dir().mkdir(parents=True, exist_ok=True)
    (secrets.config_dir() / "credentials.json").write_text(json.dumps({"mediakit": "AKLTfilecopy1234"}))
    with pytest.raises(secrets.SecretDeleteError):
        secrets.delete("mediakit")
    assert "mediakit" not in json.loads((secrets.config_dir() / "credentials.json").read_text())
    assert _ignore_file(legacy) == ["mediakit"]


def test_set_file_fallback_scrubs_stale_keychain_value(fake_kr):
    fake_kr.store[BUNDLE] = json.dumps({"deepseek": "sk-stale-12345"})
    fake_kr.fail_set = True
    assert secrets.set("deepseek", "sk-fresh-12345") == "file"
    assert BUNDLE not in fake_kr.store  # 删除仍可用，旧值被清掉
    assert secrets.get("deepseek") == "sk-fresh-12345"


def test_set_file_fallback_still_saves_when_scrub_also_fails(file_env, monkeypatch):
    kr = StickyKeyring()
    kr.fail_set = True
    kr.store[BUNDLE] = json.dumps({"deepseek": "sk-stale-12345"})
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    assert secrets.set("deepseek", "sk-fresh-12345") == "file"
    assert json.loads((file_env / "credentials.json").read_text()) == {"deepseek": "sk-fresh-12345"}


def test_failed_delete_does_not_leave_stale_cache(file_env, monkeypatch):
    kr = StickyKeyring()
    kr.store[BUNDLE] = json.dumps({"deepseek": "sk-sticky-12345"})
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    assert secrets.get("deepseek") == "sk-sticky-12345"  # 建立缓存
    with pytest.raises(secrets.SecretDeleteError):
        secrets.delete("deepseek")
    calls = kr.get_calls
    assert secrets.get("deepseek") == "sk-sticky-12345"
    assert kr.get_calls > calls  # 重新读了钥匙串


def test_concurrent_gets_read_keychain_once(fake_kr):
    fake_kr.store[BUNDLE] = json.dumps({"mediakit": "AKLTone123456", "deepseek": "sk-two-123456"})
    real_get = fake_kr.get_password

    def slow_get(svc, k):
        time.sleep(0.05)
        return real_get(svc, k)

    fake_kr.get_password = slow_get
    results: list = []
    threads = [threading.Thread(target=lambda p=p: results.append(secrets.get(p)))
               for p in ("mediakit", "deepseek")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["AKLTone123456", "sk-two-123456"]
    assert fake_kr.get_calls == 1
