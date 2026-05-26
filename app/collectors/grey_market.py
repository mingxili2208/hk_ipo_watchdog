"""暗盘数据采集器。"""

from datetime import datetime

from bs4 import BeautifulSoup
from loguru import logger

from app.collectors.base import BaseCollector, RawFetchResult, fetch_url
from app.exceptions import FetchError
from app.models import GreyMarketQuote
from app.parsers.normalizer import normalize_hk_code, normalize_percent, normalize_money


class GreyMarketCollector(BaseCollector):
    """暗盘报价采集器。"""

    name = "grey_market"

    def __init__(self, sources: list[dict] | None = None, timeout: int = 20):
        self.sources = sources or []
        self.timeout = timeout

    def fetch(self) -> RawFetchResult:
        """暗盘可能有多个来源，这里返回第一个。"""
        if not self.sources:
            raise FetchError("No grey market sources configured")
        url = self.sources[0].get("url", "")
        return fetch_url(url, timeout=self.timeout)

    def parse(self, raw: RawFetchResult) -> list[dict]:
        """按表头解析实际暗盘报价表；无暗盘报价时返回空列表。"""
        items = []
        soup = BeautifulSoup(raw.text, "lxml")

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
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
        """采集暗盘数据。"""
        quotes = []
        for src in self.sources:
            url = src.get("url", "")
            src_name = src.get("name", "unknown")
            if not url:
                continue

            try:
                raw = fetch_url(url, timeout=self.timeout)
                dicts = self.parse(raw)

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
                        quoted_at=datetime.now(),
                        source_url=url,
                        raw_fields=d.get("raw_fields", {}),
                    )
                    quotes.append(quote)
            except Exception as e:
                logger.error(f"Grey market collect from {src_name} failed: {e}")
                continue

        return quotes


def _has_header(headers: list[str], aliases: list[str]) -> bool:
    return any(any(alias in header for alias in aliases) for header in headers)


def _value(row_data: dict[str, str], aliases: list[str]) -> str | None:
    for header, value in row_data.items():
        if value and any(alias in header for alias in aliases):
            return value
    return None
