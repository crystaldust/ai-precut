"""pipeline/jy_version：剪映版本的唯一来源（KI-17）。"""
import plistlib

import pytest

from pipeline import jy_version as jv


def fake_app(tmp_path, version, name="VideoFusion-macOS.app"):
    app = tmp_path / name
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({jv.VERSION_KEY: version}))
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
