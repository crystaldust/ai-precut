"""M16 Task 6 · 前端平台文案（node vm）：默认 / 无 navigator = Mac 原文逐字不变；Windows UA = Windows 文案、无 zip 按钮。"""
import pytest

from fe_export import in_export, js, mac_export, text_of, ver
from fe_harness import NODE, run_app

pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edg/120.0"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
STAGE = "el('#stage').innerHTML"
COPY_NAMES = ["COPY_EXPORT_MAC", "COPY_IN_JIANYING", "COPY_REVEAL", "COPY_MAC_DRAFT", "COPY_MAC_DRAFT_LEGACY",
              "COPY_JY_RUNNING_BODY", "COPY_NEED_TITLE", "COPY_DIAG_DONE"]
MAC_COPY = ["导出到 Mac 剪映", "已在 Mac 剪映里：{draft}", "在访达中显示", "Mac 剪映：{draft}",
            "Mac 剪映草稿名：{draft}（改版前生成，未记录是否导入过）",
            "导出到 Mac 剪映前请先退出剪映（⌘Q），否则剪映会覆盖草稿库。", "这台 Mac 暂时不能分析",
            "诊断包 {name} 已保存到「{folder}」文件夹并在访达中选中，直接拖进微信发给开发者"]
WIN_COPY = ["导出到 Windows 剪映", "已在 Windows 剪映里：{draft}", "在文件资源管理器中显示", "Windows 剪映：{draft}",
            "Windows 剪映草稿名：{draft}（改版前生成，未记录是否导入过）",
            "导出到 Windows 剪映前请先关闭剪映窗口，否则剪映会覆盖草稿库。", "这台电脑暂时不能分析",
            "诊断包 {name} 已保存到「{folder}」文件夹并在文件资源管理器中选中，直接拖进微信发给开发者"]
NAMES_JS = js(COPY_NAMES)


def copies(ua):
    return run_app(f"{NAMES_JS}.map(n => globalThis[n] !== undefined ? globalThis[n] : eval(n))", ua=ua)


def test_platform_copy_without_navigator_is_mac():
    assert run_app("[IS_WIN, platformCopy('m', 'w')]", files=["platform.js"]) == [False, "m"]


def test_platform_copy_follows_user_agent():
    assert run_app("[IS_WIN, platformCopy('m', 'w')]", files=["platform.js"], ua=WIN_UA) == [True, "w"]
    assert run_app("[IS_WIN, platformCopy('m', 'w')]", files=["platform.js"], ua=MAC_UA) == [False, "m"]
    assert run_app("[IS_WIN, platformCopy('m', 'w')]", files=["platform.js"], ua="") == [False, "m"]


def test_default_copy_is_the_original_mac_text_byte_for_byte():
    assert copies(None) == MAC_COPY
    assert copies(MAC_UA) == MAC_COPY


def test_windows_copy_is_verbatim_from_the_plan():
    assert copies(WIN_UA) == WIN_COPY


def test_mac_export_card_keeps_the_windows_package_button():
    html = in_export(f"return {STAGE};")
    assert 'data-act="exportMac"' in html and "导出到 Mac 剪映" in html
    assert 'data-act="exportWindows"' in html and "生成 Windows 剪映包" in html


def test_windows_export_card_has_only_the_local_export_button():
    html = in_export(f"return {STAGE};", ua=WIN_UA)
    assert 'data-act="exportMac"' in html and "导出到 Windows 剪映" in html
    assert "exportWindows" not in html and "生成 Windows 剪映包" not in html and "INSTALL.bat" not in html


def test_windows_hides_package_done_and_blocked_notes_on_current_and_history_cards():
    versions = [ver("v1", current=True, windows_zip="a.zip", windows_mb=3),
                ver("v2", unusable_hits=2, blocked="含不可用片段"),
                ver("v3", exports=mac_export("v3"), draft="片名_v3")]
    html = in_export(f"return {STAGE};", state={"versions": versions}, ua=WIN_UA)
    text = text_of(html)
    assert "a.zip" not in text and "INSTALL.bat" not in text and "含不可用片段" not in text
    assert "exportVersion" not in html and "revealExport" not in html
    assert "Windows 剪映：片名_v3" in text and "Mac 剪映" not in text


def test_mac_history_cards_still_show_package_state():
    versions = [ver("v1", current=True, windows_zip="a.zip", windows_mb=3)]
    html = in_export(f"return {STAGE};", state={"versions": versions})
    text = text_of(html)
    assert "已生成 a.zip（3 MB）" in text and "在访达中显示" in text and "拷到 Windows 解压，双击 INSTALL.bat" in text


def test_windows_running_jianying_modal_uses_close_window_wording():
    out = in_export("closeJianyingModal(() => null); return el('#modalBody').innerHTML;", ua=WIN_UA)
    assert "导出到 Windows 剪映前请先关闭剪映窗口，否则剪映会覆盖草稿库。" in out and "⌘Q" not in out


def test_navigator_with_undefined_user_agent_is_mac():
    out = run_app("[IS_WIN, platformCopy('m', 'w')]", files=["platform.js"], ua={})
    assert out == [False, "m"]
