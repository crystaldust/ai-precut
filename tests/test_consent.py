"""M4 · GL-02：首次使用的数据外发告知确认记录。"""
import json

from pipeline import consent, secrets


def test_initially_not_accepted():
    assert consent.accepted() is False


def test_accept_then_accepted():
    consent.accept()
    assert consent.accepted() is True


def test_record_lives_in_config_dir_not_project(tmp_path):
    consent.accept()
    path = secrets.config_dir() / consent.FILENAME
    assert path.is_file() and str(path).startswith(str(tmp_path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == consent.CONSENT_VERSION and data["at"]


def test_older_version_needs_reconfirm():
    consent.accept()
    path = secrets.config_dir() / consent.FILENAME
    path.write_text(json.dumps({"version": consent.CONSENT_VERSION - 1}), encoding="utf-8")
    assert consent.accepted() is False


def test_corrupt_record_is_not_accepted():
    path = secrets.config_dir() / consent.FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops", encoding="utf-8")
    assert consent.accepted() is False
    path.write_text("[1]", encoding="utf-8")
    assert consent.accepted() is False
