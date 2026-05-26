"""HKEX 官方新上市信息采集器。"""

from datetime import date
from io import BytesIO
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from app.collectors.base import BaseCollector, RawFetchResult, fetch_url
from app.models import IPOItem
from app.parsers.ipo_calendar_parser import parse_ipo_calendar_html
from app.parsers.normalizer import normalize_date, normalize_hk_code, normalize_money
from app.utils.time_utils import today_hk


OFFICIAL_NEW_LISTING_URL = (
    "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en"
)
_LONG_DATE = (
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"[A-Za-z]+\s+\d{1,2},\s+\d{4}"
)


class HKEXNewListingCollector(BaseCollector):
    """从 HKEX 官方招股公告提取尚在跟踪窗口中的 Main Board IPO。"""

    name = "hkex_new_listing"

    def __init__(self, url: str | None = None, timeout: int = 20):
        self.url = url or OFFICIAL_NEW_LISTING_URL
        self.timeout = timeout

    def fetch(self) -> RawFetchResult:
        return fetch_url(self.url, timeout=self.timeout)

    def parse(self, raw: RawFetchResult) -> list[IPOItem]:
        """解析官方新上市信息表；通用表格 HTML 保留作测试/兼容后备。"""
        official_rows = _official_offering_rows(raw)
        if not official_rows:
            items = parse_ipo_calendar_html(raw.text, source=self.name)
            logger.info(f"HKEX new listing fallback: parsed {len(items)} items")
            return items

        items = []
        for row in official_rows:
            text = self._fetch_document_text(row["announcement_url"])
            item = _parse_offering_announcement(row, text)
            if item and item.status != "listed":
                items.append(item)
        logger.info(f"HKEX official new listing: parsed {len(items)} trackable IPO items")
        return items

    def collect(self) -> list[IPOItem]:
        """采集官方当前招股记录。"""
        try:
            raw = self.fetch()
            return [
                item.model_copy(update={"source_url": str(raw.url)})
                for item in self.parse(raw)
            ]
        except Exception as e:
            logger.error(f"HKEX new listing collect failed: {e}")
            return []

    def _fetch_document_text(self, url: str) -> str:
        raw = fetch_url(url, headers={"Accept": "application/pdf"}, timeout=self.timeout)
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw.content or b""))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def fetch_business_overview(self, prospectus_url: str) -> str | None:
        """从官方招股章程抽取适合在日报展示的短业务摘要。"""
        return _extract_business_overview(self._fetch_document_text(prospectus_url))


def _official_offering_rows(raw: RawFetchResult) -> list[dict[str, str]]:
    soup = BeautifulSoup(raw.text, "lxml")
    for table in soup.find_all("table"):
        headers = [cell.get_text(" ", strip=True).upper() for cell in table.find_all("tr")[0].find_all(["th", "td"])]
        if "NEW LISTING ANNOUNCEMENTS" not in headers:
            continue
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            link = cells[2].find("a", href=True)
            if not link:
                continue
            prospectus_link = cells[3].find("a", href=True) if len(cells) > 3 else None
            try:
                code = normalize_hk_code(cells[0].get_text(" ", strip=True))
            except ValueError:
                continue
            row = {
                "stock_code": code,
                "stock_name": cells[1].get_text(" ", strip=True),
                "announcement_url": urljoin(raw.url, link["href"]),
            }
            if prospectus_link:
                row["prospectus_url"] = urljoin(raw.url, prospectus_link["href"])
            rows.append(row)
        return rows
    return []


def _parse_offering_announcement(row: dict[str, str], text: str) -> IPOItem | None:
    start_date = _extract_date(text, r"Hong Kong Public Offering commences")
    close_date = _extract_date(text, r"Application lists close")
    listing_date = _extract_date(
        text,
        r"Dealings in (?:the )?H Shares on the Stock Exchange\s+expected to commence",
    )
    if not close_date:
        return None

    lot_match = re.search(r"minimum of\s+([\d,]+)\s+Hong Kong Offer Shares", text, re.IGNORECASE)
    lot_size = int(lot_match.group(1).replace(",", "")) if lot_match else None
    entry_fee = None
    if lot_size:
        fee_match = re.search(rf"\b{lot_size:,}\s+([\d,]+\.\d{{2}})\b", text)
        entry_fee = normalize_money(fee_match.group(1)) if fee_match else None

    price_match = re.search(r"Offer Price\s*:\s*(?:HK\$|HKD)\s*([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    price = normalize_money(price_match.group(1)) if price_match else None

    return IPOItem(
        stock_code=row["stock_code"],
        stock_name=row["stock_name"],
        market="Main Board",
        status=_infer_status(start_date, close_date, listing_date),
        subscription_start_date=start_date,
        subscription_close_date=close_date,
        listing_date=listing_date,
        offer_price_min=price,
        offer_price_max=price,
        lot_size=lot_size,
        entry_fee_hkd=entry_fee,
        source="hkex_new_listing",
        raw_sources={
            "hkex_new_listing": {
                "announcement_url": row["announcement_url"],
                "prospectus_url": row.get("prospectus_url"),
            }
        },
    )


def _extract_business_overview(text: str) -> str | None:
    """提取章程 Business Overview 首句，保持日报仅展示摘要。"""
    normalized = re.sub(r"\s+", " ", text).strip()
    match = re.search(r"\bOVERVIEW\s+(We are\b.{20,2000})", normalized, re.IGNORECASE)
    if not match:
        return None
    return summarize_business_overview(match.group(1))


def summarize_business_overview(text: str) -> str | None:
    """将已抽取的官方业务说明收敛为一行首句摘要。"""
    normalized = re.sub(r"\s+", " ", text).strip()
    summary = re.split(r"(?<=\.)\s+(?=[A-Z])", normalized)[0].strip()
    if len(summary) < 40:
        return None
    if len(summary) > 320:
        summary = summary[:317].rsplit(" ", 1)[0] + "..."
    return summary


def _extract_date(text: str, label: str) -> date | None:
    match = re.search(rf"{label}.{{0,150}}?({_LONG_DATE})", text, re.IGNORECASE | re.DOTALL)
    return normalize_date(match.group(1)) if match else None


def _infer_status(start_date: date | None, close_date: date, listing_date: date | None) -> str:
    today = today_hk()
    if listing_date and listing_date <= today:
        return "listed"
    if close_date < today:
        return "subscription_closed"
    if not start_date or start_date <= today:
        return "subscription_open"
    return "planned"
