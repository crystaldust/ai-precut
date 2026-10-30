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


def test_version_2_record_from_before_vision_needs_reconfirm():
    """告知加了画面理解这条数据流（第 2 阶段）：确认过 v1 的用户要重新确认一次。"""
    assert consent.CONSENT_VERSION == 2
    path = secrets.config_dir() / consent.FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
    assert consent.accepted() is False


def test_cli_and_gui_notice_list_the_same_three_flows():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "gui/static/settings.js").read_text(encoding="utf-8")
    flows = [line.strip().lstrip("·").strip() for line in consent.NOTICE_LINES if line.strip().startswith("·")]
    assert len(flows) == 3 and "画面理解" in flows[2] and "不是原始视频" in flows[2]
    assert all(f"'{flow}'" in js for flow in flows)
    assert consent.NOTICE_LINES[0].startswith("原始视频不会离开这台电脑") and consent.NOTICE_LINES[0] in js
    assert "画面理解" in consent.CLI_REQUIRED_MSG
