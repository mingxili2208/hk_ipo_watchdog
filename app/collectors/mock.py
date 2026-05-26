"""Mock Collector 用于开发和测试。"""

from datetime import date, datetime

from app.collectors.base import BaseCollector, RawFetchResult
from app.models import IPOItem


MOCK_IPO_DATA = [
    {
        "stock_code": "02616",
        "stock_name": "嘉创物流",
        "market": "Main Board",
        "industry": "logistics",
        "status": "subscription_open",
        "subscription_start_date": "2026-05-20",
        "subscription_close_date": "2026-05-26",
        "listing_date": "2026-05-29",
        "offer_price_min": 2.50,
        "offer_price_max": 3.00,
        "lot_size": 1000,
        "entry_fee_hkd": 3030.30,
        "sponsors": ["CICC"],
    },
    {
        "stock_code": "02617",
        "stock_name": "新特能源",
        "market": "Main Board",
        "industry": "new energy",
        "status": "subscription_open",
        "subscription_start_date": "2026-05-18",
        "subscription_close_date": "2026-05-23",
        "listing_date": "2026-05-30",
        "offer_price_min": 15.00,
        "offer_price_max": 18.00,
        "lot_size": 200,
        "entry_fee_hkd": 3636.36,
        "sponsors": ["Morgan Stanley", "Goldman Sachs"],
    },
    {
        "stock_code": "02618",
        "stock_name": "测试公司A",
        "market": "GEM",
        "industry": "property",
        "status": "hearing_passed",
        "subscription_start_date": None,
        "subscription_close_date": None,
        "listing_date": None,
        "offer_price_min": 1.00,
        "offer_price_max": 1.50,
        "lot_size": 2000,
        "entry_fee_hkd": 3030.30,
        "sponsors": ["Unknown Sponsor"],
    },
    {
        "stock_code": "02619",
        "stock_name": "热点科技",
        "market": "Main Board",
        "industry": "technology",
        "status": "subscription_open",
        "subscription_start_date": "2026-05-22",
        "subscription_close_date": "2026-05-27",
        "listing_date": "2026-06-01",
        "offer_price_min": 50.00,
        "offer_price_max": 60.00,
        "lot_size": 100,
        "entry_fee_hkd": 6060.61,
        "sponsors": ["CICC", "Haitong International"],
    },
]


class MockIPOCollector(BaseCollector):
    """Mock IPO 日历采集器。"""

    name = "mock_ipo"

    def __init__(self, data: list[dict] | None = None):
        self.data = data or MOCK_IPO_DATA

    def fetch(self) -> RawFetchResult:
        return RawFetchResult(
            url="mock://ipo-calendar",
            status_code=200,
            text="mock",
            fetched_at=datetime.now(),
        )

    def parse(self, raw: RawFetchResult) -> list[dict]:
        return self.data

    def collect(self) -> list[IPOItem]:
        """直接返回 IPOItem 列表。"""
        items = []
        for d in self.data:
            item = IPOItem(
                stock_code=d["stock_code"],
                stock_name=d.get("stock_name"),
                market=d.get("market"),
                industry=d.get("industry"),
                status=d.get("status", "unknown"),
                subscription_start_date=_parse_date(d.get("subscription_start_date")),
                subscription_close_date=_parse_date(d.get("subscription_close_date")),
                listing_date=_parse_date(d.get("listing_date")),
                offer_price_min=d.get("offer_price_min"),
                offer_price_max=d.get("offer_price_max"),
                lot_size=d.get("lot_size"),
                entry_fee_hkd=d.get("entry_fee_hkd"),
                sponsors=d.get("sponsors", []),
                source="mock",
            )
            items.append(item)
        return items


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    from datetime import datetime as dt

    return dt.strptime(val, "%Y-%m-%d").date()
