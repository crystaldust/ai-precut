"""M16 Task 6 · 后端里给用户看的 Mac 文案按平台给：Mac 逐字不变，Windows 按计划的替换规则。"""
import pytest

from gui import settings
from pipeline import export_flow, outputs, to_jianying


def test_jianying_running_message_mac_is_unchanged(mac_platform):
    assert settings.jianying_running_msg() == settings.JIANYING_RUNNING_MSG \
        == "剪映正在运行，请先完全退出（Cmd+Q）再导出到 Mac 剪映"


def test_jianying_running_message_windows(win_platform):
    msg = settings.jianying_running_msg()
    assert msg == "剪映正在运行，请先关闭剪映窗口再导出到 Windows 剪映"
    assert "Mac" not in msg and "Cmd" not in msg


def test_already_in_jianying_per_platform(mac_platform, monkeypatch):
    assert outputs.already_in_jianying("片名_v1") == "这一版已经在 Mac 剪映里：片名_v1" \
        == outputs.ALREADY_IN_JIANYING.format(draft="片名_v1")
    monkeypatch.setattr(outputs.plat, "IS_WIN", True)
    assert outputs.already_in_jianying("片名_v1") == "这一版已经在 Windows 剪映里：片名_v1"


def test_overwrite_refused_per_platform(mac_platform, monkeypatch):
    mac = export_flow.overwrite_refused("v1", "草稿")
    assert mac.endswith("请生成新版本再导出到 Mac 剪映") and "v1" in mac and "「草稿」" in mac
    assert mac == export_flow.OVERWRITE_REFUSED.format(version="v1", draft="草稿")
    monkeypatch.setattr(export_flow.plat, "IS_WIN", True)
    win = export_flow.overwrite_refused("v1", "草稿")
    assert win.endswith("请生成新版本再导出到 Windows 剪映") and "Mac" not in win


def test_check_build_ready_blocks_with_platform_message(win_platform, monkeypatch, tmp_path):
    monkeypatch.setattr(to_jianying, "jianying_running", lambda: True)
    with pytest.raises(settings.PrepareBlocked) as exc:
        settings.check_build_ready(tmp_path, {"target": "mac"})
    assert "Windows 剪映" in str(exc.value) and "Mac" not in str(exc.value)
