"""BrowserManager 生命周期测试。"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.utils.browser import BrowserManager


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前重置单例。"""
    BrowserManager.reset()
    yield
    BrowserManager.reset()


def test_browser_manager_is_singleton():
    a = BrowserManager()
    b = BrowserManager()
    assert a is b


def test_browser_manager_close_singleton_clears_instance():
    mgr = BrowserManager()
    mgr.close_singleton()
    assert BrowserManager._instance is None
    # 再次获取应是新实例
    new_mgr = BrowserManager()
    assert new_mgr is not mgr


def test_browser_manager_reset_clears_instance():
    mgr = BrowserManager()
    BrowserManager.reset()
    assert BrowserManager._instance is None


def test_fetch_page_creates_and_closes_context(monkeypatch):
    """fetch_page 应创建独立 context 并在 finally 中关闭。"""
    mock_page = MagicMock()
    mock_page.content.return_value = "<html>rendered</html>"

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_browser.new_context.return_value = mock_context

    mock_pw = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser

    mock_pw_instance = MagicMock()
    mock_pw_instance.start.return_value = mock_pw

    with patch("app.utils.browser.sync_playwright", return_value=mock_pw_instance):
        mgr = BrowserManager()
        result = mgr.fetch_page(
            "https://example.test",
            wait_selector="table.data",
            wait_ms=100,
            timeout_ms=5000,
        )

    assert result == "<html>rendered</html>"
    # context 应被创建并关闭
    mock_browser.new_context.assert_called_once()
    mock_page.close.assert_called_once()
    mock_context.close.assert_called_once()


def test_fetch_page_closes_context_on_error(monkeypatch):
    """即使 page 操作抛异常，context 也应被关闭。"""
    mock_page = MagicMock()
    mock_page.goto.side_effect = Exception("navigation failed")

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.is_connected.return_value = True
    mock_browser.new_context.return_value = mock_context

    mock_pw = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser

    mock_pw_instance = MagicMock()
    mock_pw_instance.start.return_value = mock_pw

    with patch("app.utils.browser.sync_playwright", return_value=mock_pw_instance):
        mgr = BrowserManager()
        with pytest.raises(Exception, match="navigation failed"):
            mgr.fetch_page("https://example.test", timeout_ms=5000)

    # context 和 page 都应被关闭（finally 块）
    mock_page.close.assert_called_once()
    mock_context.close.assert_called_once()


def test_close_handles_missing_browser_gracefully():
    """close() 在浏览器未启动时不应抛异常。"""
    mgr = BrowserManager()
    # 直接关闭不应报错
    mgr.close()
    assert mgr._browser is None
    assert mgr._pw is None


def test_fetch_page_raises_if_playwright_not_installed(monkeypatch):
    """playwright 未安装时应抛出 RuntimeError。"""
    monkeypatch.setattr("app.utils.browser.sync_playwright", None)
    # 需要重置单例以重新初始化
    BrowserManager.reset()

    mgr = BrowserManager()
    with pytest.raises(RuntimeError, match="playwright 未安装"):
        mgr.fetch_page("https://example.test")
