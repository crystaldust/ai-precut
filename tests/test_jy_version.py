"""pipeline/jy_version：剪映版本的唯一来源（KI-17）。"""
import plistlib
from pathlib import Path

import pytest

from pipeline import jy_version as jv


def fake_app(tmp_path, version, name="VideoFusion-macOS.app", bundle_id=None):
    app = tmp_path / name
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(
        {jv.VERSION_KEY: version, jv.BUNDLE_ID_KEY: bundle_id or jv.BUNDLE_ID}))
    return app


def test_installed_version_reads_info_plist(tmp_path):
    assert jv.installed_version([fake_app(tmp_path, "11.6.0")]) == "11.6.0"


def test_installed_version_takes_first_readable_candidate(tmp_path):
    first = tmp_path / "nope.app"
    assert jv.installed_version([first, fake_app(tmp_path, "11.2.0")]) == "11.2.0"


def test_installed_version_none_when_missing_or_corrupt(tmp_path):
    bad = tmp_path / "X.app/Contents"
    bad.mkdir(parents=True)
    (bad / "Info.plist").write_text("garbage")
    assert jv.installed_version([tmp_path / "nope.app", tmp_path / "X.app"]) is None


def test_installed_version_none_when_key_not_a_string(tmp_path):
    app = tmp_path / "Y.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({jv.VERSION_KEY: 11}))
    assert jv.installed_version([app]) is None


@pytest.mark.parametrize("v,warns", [("11.6.0", False), ("11.0.0", False), ("12.0.1", True),
                                     ("10.8.0", True), (None, False), ("abc", False),
                                     ("", False)])
def test_compat_warning_only_on_major_change(v, warns):
    assert (jv.compat_warning(v) is not None) == warns


def test_compat_warning_names_found_and_verified_series():
    msg = jv.compat_warning("12.0.0")
    assert "12.0.0" in msg and "11.x" in msg


def test_template_is_the_verified_version_and_exists():
    assert jv.TEMPLATE.name == f"base_template_{jv.VERIFIED_SERIES}.json" and jv.TEMPLATE.exists()
    assert jv.VERIFIED_VERSION.startswith(jv.VERIFIED_SERIES)


# ---------------------------------------------------------------- KI-98：find_app（固定位置 + Spotlight）
import subprocess  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _runner(stdout="", returncode=0, raises=None, calls=None):
    def run(argv, **kw):
        if calls is not None:
            calls.append((argv, kw))
        if raises is not None:
            raise raises
        return SimpleNamespace(stdout=stdout, returncode=returncode)
    return run


def test_find_app_constants():
    assert jv.BUNDLE_ID == "com.lemon.lvpro" and jv.MDFIND_TIMEOUT_S == 3


def test_find_app_returns_existing_candidate_without_spotlight(tmp_path):
    app = fake_app(tmp_path, "11.0.0")
    calls = []
    assert jv.find_app([tmp_path / "nope.app", app], _runner(calls=calls), roots=[tmp_path]) == app
    assert calls == []


def test_find_app_falls_back_to_mdfind_by_bundle_id_with_timeout(tmp_path):
    app = fake_app(tmp_path, "11.0.0", name="剪映专业版.app")
    calls = []
    found = jv.find_app([tmp_path / "nope.app"], _runner(f"{app}\n", calls=calls), roots=[tmp_path])
    assert found == app
    argv, kw = calls[0]
    assert argv[0] == "mdfind" and jv.BUNDLE_ID in argv[1]
    assert kw["timeout"] == jv.MDFIND_TIMEOUT_S


def test_find_app_skips_trash_missing_and_non_app_results(tmp_path):
    trash = fake_app(tmp_path / ".Trash", "11.0.0")
    good = fake_app(tmp_path, "11.0.0", name="剪映.app")
    plain = tmp_path / "x.txt"
    plain.write_text("x")
    out = "\n".join([str(trash), str(tmp_path / "gone.app"), str(plain), "", str(good)])
    assert jv.find_app([], _runner(out), roots=[tmp_path]) == good


@pytest.mark.parametrize("runner", [
    _runner(raises=subprocess.TimeoutExpired("mdfind", 3)),
    _runner(raises=FileNotFoundError("mdfind")),
    _runner(raises=PermissionError("x")),
    _runner("/Applications/X.app\n", returncode=1),
    _runner(""),
])
def test_find_app_none_when_spotlight_unavailable_or_empty(runner):
    assert jv.find_app([], runner) is None


# ---- 安全：只信任系统应用目录里、bundle id 对得上的 .app
def test_default_roots_are_application_folders_only():
    names = {str(r) for r in jv.APP_ROOTS}
    assert {"/Applications", "/System/Applications", str(Path.home() / "Applications")} == names


def test_find_app_rejects_app_outside_trusted_roots(tmp_path):
    outside = fake_app(tmp_path / "Downloads", "11.0.0")
    trusted = tmp_path / "Applications"
    trusted.mkdir()
    assert jv.find_app([outside], _runner(f"{outside}\n"), roots=[trusted]) is None


def test_find_app_rejects_symlink_escaping_trusted_roots(tmp_path):
    real = fake_app(tmp_path / "elsewhere", "11.0.0")
    trusted = tmp_path / "Applications"
    trusted.mkdir()
    (trusted / "link.app").symlink_to(real, target_is_directory=True)
    assert jv.find_app([trusted / "link.app"], _runner(""), roots=[trusted]) is None


def test_find_app_rejects_wrong_or_unreadable_bundle_id(tmp_path):
    wrong = fake_app(tmp_path, "11.0.0", name="Other.app", bundle_id="com.evil.app")
    broken = tmp_path / "Broken.app/Contents"
    broken.mkdir(parents=True)
    (broken / "Info.plist").write_text("garbage")
    noplist = tmp_path / "NoPlist.app"
    noplist.mkdir()
    out = "\n".join(str(p) for p in (wrong, tmp_path / "Broken.app", noplist))
    assert jv.find_app([wrong, tmp_path / "Broken.app", noplist], _runner(out), roots=[tmp_path]) is None


def test_find_app_prefers_earlier_root_among_candidates_and_spotlight(tmp_path):
    first, second = tmp_path / "A", tmp_path / "B"
    a = fake_app(first, "11.0.0")
    b = fake_app(second, "11.0.0")
    assert jv.find_app([b, a], _runner(""), roots=[first, second]) == a
    assert jv.find_app([], _runner(f"{b}\n{a}\n"), roots=[first, second]) == a


# ---- installed_version
def test_installed_version_default_goes_through_cached_find_app(tmp_path, monkeypatch):
    app = fake_app(tmp_path, "11.4.0", name="任意名字.app")
    calls = []
    monkeypatch.setattr(jv, "find_app", lambda *a, **k: calls.append(1) or app)
    jv.reset_cache()
    assert jv.installed_version() == "11.4.0" and jv.installed_version() == "11.4.0"
    assert len(calls) == 1                      # 第二次走缓存，不再跑 mdfind
    jv.reset_cache()
    monkeypatch.setattr(jv, "find_app", lambda *a, **k: None)
    assert jv.installed_version() is None


def test_cached_find_refresh_and_expiry(monkeypatch):
    calls, t = [], [100.0]
    monkeypatch.setattr(jv, "find_app", lambda *a, **k: calls.append(1))
    jv.reset_cache()
    jv.cached_find(now=lambda: t[0])
    jv.cached_find(now=lambda: t[0])
    assert len(calls) == 1
    jv.cached_find(refresh=True, now=lambda: t[0])
    assert len(calls) == 2
    t[0] += jv.CACHE_S + 1
    jv.cached_find(now=lambda: t[0])
    assert len(calls) == 3
