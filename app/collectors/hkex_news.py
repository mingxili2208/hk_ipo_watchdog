"""HKEX News 公告采集器。"""

from datetime import datetime
from io import BytesIO
import re
from urllib.parse import urljoin

from loguru import logger

from app.collectors.base import BaseCollector, RawFetchResult, fetch_url
from app.models import Announcement
from app.parsers.announcement_parser import detect_announcement_type
from app.parsers.normalizer import normalize_hk_code


OFFICIAL_NEW_LISTING_URL = (
    "https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en"
)


class HKEXNewsCollector(BaseCollector):
    """HKEX News 公告采集器。"""

    name = "hkex_news"

    def __init__(self, url: str | None = None, timeout: int = 20, lookback_hours: int = 24):
        self.url = url or OFFICIAL_NEW_LISTING_URL
        self.timeout = timeout
        self.lookback_hours = lookback_hours

    def fetch(self) -> RawFetchResult:
        return fetch_url(self.url, timeout=self.timeout)

    def parse(self, raw: RawFetchResult) -> list[dict]:
        """解析 HKEX News 公告页面。

        注意: HKEX News 页面可能为动态加载，此为参考实现。
        """
        from bs4 import BeautifulSoup

        items = []
        soup = BeautifulSoup(raw.text, "lxml")

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            headers = [cell.get_text(" ", strip=True).upper() for cell in rows[0].find_all(["th", "td"])]
            if "ALLOTMENT RESULTS" not in headers:
                continue
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue
                link = cells[4].find("a", href=True)
                if not link:
                    continue
                try:
                    code = normalize_hk_code(cells[0].get_text(" ", strip=True))
                except ValueError:
                    continue
                items.append({
                    "title": f"Allotment Results - {cells[1].get_text(' ', strip=True)}",
                    "url": urljoin(raw.url, link["href"]),
                    "announcement_type": "allotment_result",
                    "stock_code": code,
                    "stock_name": cells[1].get_text(" ", strip=True),
                    "source": self.name,
                    "fetched_at": datetime.now().isoformat(),
                })
            logger.info(f"HKEX News: parsed {len(items)} official allotment announcements")
            return items

        # 查找公告列表
        for link in soup.find_all("a", href=True):
            href = urljoin(raw.url, link["href"])
            title = link.get_text(strip=True)
            if not title:
                continue

            # 过滤 IPO 相关公告
            ipo_keywords = [
                "global offering",
                "prospectus",
                "allotment",
                "offer price",
                "stabilizing",
                "listing",
                "全球發售",
                "招股",
                "配發",
                "配发",
                "發售價",
                "发售价",
                "上市",
            ]
            title_lower = title.lower()
            if not any(kw in title_lower for kw in ipo_keywords):
                continue

            ann_type = detect_announcement_type(title)
            context = link.parent.get_text(" ", strip=True) if link.parent else title
            items.append({
                "title": title,
                "url": href,
                "announcement_type": ann_type,
                "stock_code": _extract_stock_code(context),
                "source": self.name,
                "fetched_at": datetime.now().isoformat(),
            })

        logger.info(f"HKEX News: parsed {len(items)} announcements")
        return items

    def collect(self) -> list[Announcement]:
        """采集公告列表。"""
        try:
            raw = self.fetch()
            dicts = self.parse(raw)
            announcements = []
            for d in dicts:
                ann = Announcement(
                    title=d["title"],
                    url=d.get("url", ""),
                    announcement_type=d.get("announcement_type", "other"),
                    stock_code=d.get("stock_code"),
                    stock_name=d.get("stock_name"),
                    source=self.name,
                    fetched_at=datetime.now(),
                )
                if ann.announcement_type == "allotment_result":
                    if ann.url.lower().endswith(".pdf"):
                        ann.pdf_url = ann.url
                    ann.raw_text = self._fetch_document_text(ann.url)
                announcements.append(ann)
            return announcements
        except Exception as e:
            logger.error(f"HKEX News collect failed: {e}")
            return []

    def _fetch_document_text(self, url: str) -> str | None:
        """获取公告正文；PDF 解析器不可用时保留链接而不阻断任务。"""
        if not url:
            return None
        try:
            raw = fetch_url(url, timeout=self.timeout)
            content_type = raw.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                return raw.text

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(raw.content or b""))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            logger.warning("pypdf not installed; cannot parse allotment PDF text")
        except Exception as e:
            logger.warning(f"Failed to fetch allotment document {url}: {e}")
        return None


def _extract_stock_code(text: str) -> str | None:
    labelled = re.search(r"(?:stock\s*code|股份代號|股票代號|证券代码|證券代碼)\D*(\d{1,5})", text, re.IGNORECASE)
    candidates = [labelled.group(1)] if labelled else re.findall(r"(?:HK\.)?\d{4,5}(?:\.HK)?", text, re.IGNORECASE)
    for candidate in candidates:
        try:
            return normalize_hk_code(candidate)
        except ValueError:
            continue
    return None
