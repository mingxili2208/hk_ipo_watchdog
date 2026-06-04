"""Playwright 浏览器管理器。

使用单例模式复用浏览器实例，避免反复启动/关闭造成资源浪费。
每个页面在独立的 BrowserContext 中运行，确保 cookie/session 隔离。
所有操作都有超时保护，防止进程挂起。
"""

from __future__ import annotations

import threading

from loguru import logger

# playwright 未安装时的优雅降级
try:
    from playwright.sync_api import sync_playwright, Browser, Playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]
    Browser = None  # type: ignore[assignment,misc]
    Playwright = None  # type: ignore[assignment,misc]


class BrowserManager:
    """单例 Playwright 浏览器管理器。

    生命周期：
    - 首次调用 get() 时启动 Chromium。
    - 后续调用复用同一实例。
    - 显式调用 close() 或 atexit 时关闭。

    安全保障：
    - 每次 fetch_page() 使用独立 context，结束后关闭 context。
    - 所有操作有超时。
    - 线程安全（锁保护浏览器实例的创建/销毁）。
    """

    _instance: BrowserManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> BrowserManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._pw = None
                    inst._browser = None
                    inst._init_lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    # -- 内部初始化 --

    def _ensure_browser(self) -> Browser:
        """确保浏览器已启动，返回 Browser 实例。"""
        if self._browser and self._browser.is_connected():
            return self._browser

        with self._init_lock:
            # double-check
            if self._browser and self._browser.is_connected():
                return self._browser

            if sync_playwright is None:
                raise RuntimeError(
                    "playwright 未安装，请运行: pip install playwright && "
                    "playwright install chromium --with-deps"
                )

            logger.info("BrowserManager: starting Chromium")
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--single-process",
                ],
            )
            logger.info("BrowserManager: Chromium started")
            return self._browser

    # -- 公开 API --

    def fetch_page(
        self,
        url: str,
        *,
        wait_selector: str | None = None,
        wait_ms: int = 3000,
        timeout_ms: int = 30000,
    ) -> str:
        """获取页面渲染后的 HTML。

        使用独立 BrowserContext，结束后自动关闭，不泄漏资源。

        Args:
            url: 目标 URL。
            wait_selector: 等待此 CSS 选择器出现后再提取 HTML。
            wait_ms: 在 wait_selector 之后额外等待的毫秒数（等待 WebSocket 数据到达）。
            timeout_ms: 整体操作超时（毫秒）。

        Returns:
            渲染后的完整 HTML 字符串。
        """
        browser = self._ensure_browser()
        context = None
        page = None
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-HK",
                timezone_id="Asia/Hong_Kong",
            )
            page = context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            if wait_selector:
                try:
                    page.wait_for_selector(
                        wait_selector, timeout=timeout_ms, state="attached"
                    )
                except Exception:
                    logger.debug(
                        f"BrowserManager: selector '{wait_selector}' "
                        f"not found within {timeout_ms}ms, proceeding"
                    )

            # 额外等待，让 WebSocket 推送的数据渲染到 DOM
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)

            html = page.content()
            logger.debug(
                f"BrowserManager: fetched {url} ({len(html)} bytes)"
            )
            return html
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            if context:
                try:
                    context.close()
                except Exception:
                    pass

    def close(self) -> None:
        """关闭浏览器和 Playwright 实例。"""
        with self._init_lock:
            if self._browser:
                try:
                    self._browser.close()
                except Exception as e:
                    logger.debug(f"BrowserManager: browser close error: {e}")
                self._browser = None
            if self._pw:
                try:
                    self._pw.stop()
                except Exception as e:
                    logger.debug(f"BrowserManager: playwright stop error: {e}")
                self._pw = None
            logger.info("BrowserManager: closed")

    @classmethod
    def close_singleton(cls) -> None:
        """关闭全局单例。在进程退出前调用。"""
        if cls._instance:
            cls._instance.close()
            cls._instance = None

    @classmethod
    def reset(cls) -> None:
        """重置单例（仅用于测试）。"""
        cls.close_singleton()
