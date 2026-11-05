"""app/cursor_mac：macOS 下让 WebKit 处理按键后不再隐藏鼠标指针。"""
import builtins
import sys

import pytest

from app import cursor_mac


@pytest.fixture(autouse=True)
def fresh_flag(monkeypatch):
    monkeypatch.setattr(cursor_mac, "_installed", False)


def test_non_darwin_returns_false_without_importing_appkit(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    real_import, attempted = builtins.__import__, []

    def spy(name, *a, **k):
        attempted.append(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", spy)
    assert cursor_mac.keep_cursor_visible() is False
    assert "AppKit" not in attempted and "objc" not in attempted
    assert cursor_mac._installed is False


def test_missing_pyobjc_returns_false_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", None)  # import AppKit → ImportError
    assert cursor_mac.keep_cursor_visible() is False
    assert cursor_mac._installed is False


@pytest.mark.skipif(sys.platform != "darwin", reason="需要 macOS 的 AppKit")
def test_installs_python_replacement_and_is_idempotent():
    import AppKit
    assert cursor_mac.keep_cursor_visible() is True
    assert cursor_mac._installed is True
    sel = AppKit.NSCursor.pyobjc_classMethods.setHiddenUntilMouseMoves_
    assert type(sel).__name__ == "python_selector"  # 实现已换成 Python 的 no-op（原生的是 native_selector）
    assert AppKit.NSCursor.setHiddenUntilMouseMoves_(True) is None
    assert cursor_mac.keep_cursor_visible() is True  # 第二次：不重复定义 category，不报错


def test_unexpected_pyobjc_failure_is_logged_and_does_not_abort_startup(monkeypatch):
    import types
    monkeypatch.setattr(sys, "platform", "darwin")
    boom = types.SimpleNamespace(Category=lambda cls: (_ for _ in ()).throw(RuntimeError("category boom")))
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(NSCursor=object))
    monkeypatch.setitem(sys.modules, "objc", boom)
    assert cursor_mac.keep_cursor_visible() is False  # 只是体验优化：装不上也照常启动
    assert cursor_mac._installed is False
