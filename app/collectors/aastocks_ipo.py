"""AAStocks IPO 采集器。"""

from loguru import logger
from bs4 import BeautifulSoup

from app.collectors.base import BaseCollector, RawFetchResult, fetch_url
from app.models import IPOItem
from app.parsers.ipo_calendar_parser import parse_ipo_calendar_html


class AAStocksIPOCollector(BaseCollector):
    """AAStocks IPO 日历采集器。"""

    name = "aastocks_ipo"

    def __init__(self, url: str | None = None, timeout: int = 20):
        self.url = url or "https://www.aastocks.com/tc/stocks/market/ipo/mainpage.aspx"
        self.timeout = timeout

    def fetch(self) -> RawFetchResult:
        return fetch_url(self.url, timeout=self.timeout)

    def parse(self, raw: RawFetchResult) -> list[IPOItem]:
        """只解析 AAStocks 页面中的正在招股表，避免导入历史上市记录。"""
        soup = BeautifulSoup(raw.text, "lxml")
        items: list[IPOItem] = []
        for table in soup.find_all("table"):
            header = table.find("tr")
            header_text = header.get_text(" ", strip=True) if header else ""
            if "招股截止日" not in header_text or "入場費" not in header_text:
                continue
            for item in parse_ipo_calendar_html(str(table), source=self.name):
                items.append(item.model_copy(update={"status": "subscription_open"}))

        logger.info(f"AAStocks: parsed {len(items)} IPO items")
        return items

    def collect(self) -> list[IPOItem]:
        """采集并返回 IPOItem 列表。"""
        try:
            raw = self.fetch()
            items = self.parse(raw)
            return [
                item.model_copy(update={"source_url": str(raw.url)})
                for item in items
            ]
        except Exception as e:
            logger.error(f"AAStocks IPO collect failed: {e}")
            return []
