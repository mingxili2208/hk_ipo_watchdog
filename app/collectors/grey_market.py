"""暗盘数据采集器。

支持两种采集模式：
- html: 静态 HTTP GET + BeautifulSoup 解析（适用于服务端渲染的页面）。
- browser: Playwright 无头浏览器渲染 + 解析（适用于 WebSocket/AJAX 动态加载的页面）。
"""

from bs4 import BeautifulSoup
from loguru import logger

from app.collectors.base import BaseCollector, RawFetchResult, fetch_url
from app.exceptions import FetchError
from app.models import GreyMarketQuote
from app.parsers.normalizer import normalize_hk_code, normalize_percent, normalize_money
from app.utils.time_utils import now_hk

# 暗盘页面中"无数据"的标识文本
_NO_DATA_TEXTS = ["供應商是日沒有新股暗盤", "供应商是日没有新股暗盘"]


class GreyMarketCollector(BaseCollector):
    """暗盘报价采集器。"""

    name = "grey_market"

    def __init__(
        self,
        sources: list[dict] | None = None,
        timeout: int = 20,
        collect_mode: str = "html",
    ):
        self.sources = sources or []
        self.timeout = timeout
        self.collect_mode = collect_mode

    def fetch(self) -> RawFetchResult:
        """抓取第一个数据源的原始页面。"""
        if not self.sources:
            raise FetchError("No grey market sources configured")
        url = self.sources[0].get("url", "")
        if not url:
            raise FetchError("Grey market source has no URL")
        return fetch_url(url, timeout=self.timeout)

    def _fetch_with_browser(self, url: str) -> RawFetchResult:
        """使用 Playwright 渲染页面，返回渲染后的 HTML。

        浏览器实例由 BrowserManager 单例管理，此处只创建独立的
        BrowserContext（页面隔离），结束后自动关闭 context，不会泄漏资源。
        """
        from app.utils.browser import BrowserManager

        timeout_ms = self.timeout * 1000
        # 等待 GMList-Container 出现 + 额外 3s 让 WebSocket 数据渲染
        html = BrowserManager().fetch_page(
            url,
            wait_selector="table.GMList-Container",
            wait_ms=3000,
            timeout_ms=timeout_ms,
        )
        return RawFetchResult(
            url=url,
            status_code=200,
            text=html,
        )

    def parse(self, raw: RawFetchResult) -> list[dict]:
        """按表头解析实际暗盘报价表；无暗盘报价时返回空列表。"""
        items = []
        soup = BeautifulSoup(raw.text, "lxml")

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            # 跳过"无数据"提示表
            table_text = table.get_text(strip=True)
            if any(no_data in table_text for no_data in _NO_DATA_TEXTS):
                continue

            header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
            if not _has_header(header, ["暗盤價", "暗盘价"]) or not _has_header(header, ["升跌", "涨跌", "漲跌"]):
                continue

            for row in rows[1:]:
                cells = row.find_all("td")
                if not cells:
                    continue

                try:
                    row_data = dict(zip(header, [cell.get_text(" ", strip=True) for cell in cells]))
                    code_text = _value(row_data, ["公司名稱/代號", "公司名称/代号", "股份", "代號", "代号"])
                    code = normalize_hk_code(code_text)

                    items.append({
                        "stock_code": code,
                        "grey_price": normalize_money(_value(row_data, ["暗盤價", "暗盘价"])),
                        "offer_price": normalize_money(_value(row_data, ["招股價", "招股价", "定價", "定价"])),
                        "change_percent": normalize_percent(_value(row_data, ["暗盤升跌", "暗盘涨跌", "升跌", "漲跌", "涨跌"])),
                        "turnover_hkd": normalize_money(_value(row_data, ["暗盤成交額", "暗盘成交额", "成交額", "成交额"])),
                        "raw_fields": row_data,
                        "source": self.name,
                    })
                except (ValueError, IndexError) as e:
                    logger.debug(f"Grey market: failed to parse row: {e}")
                    continue

        return items

    def collect(self, stock_codes: list[str] | None = None) -> list[GreyMarketQuote]:
        """采集暗盘数据。

        根据 collect_mode 选择采集方式：
        - browser: Playwright 渲染（用于 WebSocket 动态加载的页面）。
        - html: 传统 HTTP GET（用于服务端渲染的页面）。
        """
        quotes = []
        for src in self.sources:
            url = src.get("url", "")
            src_name = src.get("name", "unknown")
            if not url:
                continue

            try:
                if self.collect_mode == "browser":
                    raw = self._fetch_with_browser(url)
                else:
                    raw = fetch_url(url, timeout=self.timeout)

                dicts = self.parse(raw)

                if not dicts:
                    logger.debug(f"Grey market: no quote data from {src_name}")

                for d in dicts:
                    code = d.get("stock_code", "")
                    if stock_codes and code not in stock_codes:
                        continue

                    quote = GreyMarketQuote(
                        stock_code=code,
                        source=src_name,
                        grey_price=d.get("grey_price"),
                        offer_price=d.get("offer_price"),
                        change_percent=d.get("change_percent"),
                        turnover_hkd=d.get("turnover_hkd"),
                        quoted_at=now_hk(),
                        source_url=url,
                        raw_fields=d.get("raw_fields", {}),
                    )
                    quotes.append(quote)
            except Exception as e:
                logger.error(
                    f"Grey market collect from {src_name} "
                    f"(mode={self.collect_mode}) failed: {e}"
                )
                continue

        return quotes


def _has_header(headers: list[str], aliases: list[str]) -> bool:
    return any(any(alias in header for alias in aliases) for header in headers)


def _value(row_data: dict[str, str], aliases: list[str]) -> str | None:
    for header, value in row_data.items():
        if value and any(alias in header for alias in aliases):
            return value
    return None
