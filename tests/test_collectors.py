"""Collector 到标准模型的回归测试。"""

from datetime import timedelta

from app.collectors.aastocks_ipo import AAStocksIPOCollector
from app.collectors.base import RawFetchResult
from app.collectors.grey_market import GreyMarketCollector
from app.collectors.hkex_new_listing import HKEXNewListingCollector
from app.collectors.hkex_news import HKEXNewsCollector
from app.utils.time_utils import today_hk


def _english_date(value):
    return value.strftime("%A, %B %d, %Y")


def test_ipo_calendar_collector_preserves_strategy_fields():
    today = today_hk()
    close_date = today + timedelta(days=1)
    html = f"""
    <table>
      <tr>
        <th>Stock Code</th><th>Stock Name</th><th>Market</th>
        <th>Subscription Start Date</th><th>Subscription Close Date</th>
        <th>Listing Date</th><th>Offer Price</th><th>Lot Size</th><th>Entry Fee</th>
      </tr>
      <tr>
        <td>3888</td><td>Demo</td><td>Main Board</td>
        <td>{today}</td><td>{close_date}</td><td>{today + timedelta(days=4)}</td>
        <td>HK$2.50 - HK$3.00</td><td>1,000</td><td>HK$3,030.30</td>
      </tr>
    </table>
    """
    collector = HKEXNewListingCollector(url="https://example.test/calendar")
    collector.fetch = lambda: RawFetchResult(
        url="https://example.test/calendar",
        status_code=200,
        text=html,
    )

    item = collector.collect()[0]

    assert item.stock_code == "03888"
    assert item.status == "subscription_open"
    assert item.subscription_close_date == close_date
    assert item.offer_price_max == 3.0
    assert item.lot_size == 1000
    assert item.entry_fee_hkd == 3030.30
    assert "hkex_new_listing" in item.raw_sources


def test_hkex_official_listing_page_keeps_closed_unlisted_ipo_for_tracking():
    today = today_hk()
    start_date = today - timedelta(days=1)
    close_date = today + timedelta(days=1)
    listing_date = today + timedelta(days=4)
    html = """
    <table>
      <tr><th>Stock Code</th><th>Stock Name</th><th>NEW LISTING ANNOUNCEMENTS</th><th>PROSPECTUSES</th><th>ALLOTMENT RESULTS</th></tr>
      <tr><td>3388</td><td>Creality</td><td><a href="/open.pdf">Download</a></td><td></td><td></td></tr>
      <tr><td>0901</td><td>Closed</td><td><a href="/closed.pdf">Download</a></td><td></td><td></td></tr>
    </table>
    """
    open_text = f"""
    Offer Price : HK$18.80 per Offer Share
    made for a minimum of 150 Hong Kong Offer Shares
    150 2,848.44
    Hong Kong Public Offering commences 9:00 a.m. on {_english_date(start_date)}
    Application lists close 12:00 noon on {_english_date(close_date)}
    Dealings in the H Shares on the Stock Exchange expected to commence at 9:00 a.m. on {_english_date(listing_date)}
    """
    closed_text = open_text.replace(_english_date(close_date), _english_date(today - timedelta(days=1)))
    collector = HKEXNewListingCollector(url="https://example.test/new-listing")
    collector._fetch_document_text = (
        lambda url: open_text if url.endswith("/open.pdf") else closed_text
    )

    items = collector.parse(RawFetchResult(url=collector.url, status_code=200, text=html))

    assert len(items) == 2
    item = items[0]
    assert item.stock_code == "03388"
    assert item.market == "Main Board"
    assert item.subscription_close_date == close_date
    assert item.offer_price_max == 18.8
    assert item.lot_size == 150
    assert item.entry_fee_hkd == 2848.44
    assert items[1].status == "subscription_closed"


def test_hkex_news_collects_allotment_code_and_document_text():
    collector = HKEXNewsCollector(url="https://example.test/news")
    collector.fetch = lambda: RawFetchResult(
        url="https://example.test/news",
        status_code=200,
        text='<div>Stock Code: 03888 <a href="/allocation.html">Allotment Results</a></div>',
    )
    collector._fetch_document_text = lambda url: "Offer Price HK$3.00; over-subscribed by 30 times"

    announcement = collector.collect()[0]

    assert announcement.stock_code == "03888"
    assert announcement.announcement_type == "allotment_result"
    assert announcement.url == "https://example.test/allocation.html"
    assert "Offer Price" in announcement.raw_text


def test_hkex_news_reads_allotment_column_from_official_listing_page():
    html = """
    <table>
      <tr><th>Stock Code</th><th>Stock Name</th><th>NEW LISTING ANNOUNCEMENTS</th><th>PROSPECTUSES</th><th>ALLOTMENT RESULTS</th></tr>
      <tr><td>6872</td><td>TenNor</td><td></td><td></td><td><a href="/allocation.pdf">Download</a></td></tr>
    </table>
    """
    collector = HKEXNewsCollector(url="https://example.test/new-listing")
    collector._fetch_document_text = lambda url: "Offer Price HK$20.00; over-subscribed by 30 times"

    announcements = collector.parse(RawFetchResult(url=collector.url, status_code=200, text=html))

    assert announcements == [{
        "title": "Allotment Results - TenNor",
        "url": "https://example.test/allocation.pdf",
        "announcement_type": "allotment_result",
        "stock_code": "06872",
        "stock_name": "TenNor",
        "source": "hkex_news",
        "fetched_at": announcements[0]["fetched_at"],
    }]


def test_aastocks_only_reads_active_subscription_table():
    today = today_hk()
    close_date = today + timedelta(days=1)
    listing_date = today + timedelta(days=4)
    html = f"""
    <table>
      <tr>
        <th>公司名稱/代號</th><th>行業</th><th>招股價 4</th><th>每手股數</th>
        <th>入場費</th><th>招股截止日</th><th>上市日期</th>
      </tr>
      <tr>
        <td>創想三維 03388.HK 明天截止招股</td><td>電腦存儲</td><td>18.8</td>
        <td>150</td><td>2,848.44</td><td>{close_date}</td><td>{listing_date}</td>
      </tr>
    </table>
    <table>
      <tr><th>公司名稱/代號</th><th>上市日期</th></tr>
      <tr><td>歷史公司 06872.HK</td><td>{today - timedelta(days=1)}</td></tr>
    </table>
    """
    collector = AAStocksIPOCollector(url="https://example.test/ipo")

    items = collector.parse(RawFetchResult(url=collector.url, status_code=200, text=html))

    assert len(items) == 1
    item = items[0]
    assert item.stock_code == "03388"
    assert item.stock_name == "創想三維"
    assert item.status == "subscription_open"
    assert item.subscription_close_date == close_date
    assert item.entry_fee_hkd == 2848.44
    assert item.market is None


def test_board_lot_is_not_interpreted_as_market():
    collector = HKEXNewListingCollector(url="https://example.test/calendar")
    html = """
    <table>
      <tr><th>Stock Code</th><th>Stock Name</th><th>Board Lot</th></tr>
      <tr><td>00901</td><td>SDMC</td><td>100</td></tr>
    </table>
    """

    item = collector.parse(RawFetchResult(url=collector.url, status_code=200, text=html))[0]

    assert item.market is None
    assert item.lot_size == 100


def test_grey_market_only_parses_quote_table_by_headers():
    html = """
    <table>
      <tr><th>公司名稱/代號</th><th>定價</th><th>暗盤日期</th></tr>
      <tr><td>不應解析 02723.HK</td><td>20.8</td><td>2026/05/26</td></tr>
    </table>
    <table>
      <tr>
        <th>公司名稱/代號</th><th>招股價</th><th>暗盤價</th>
        <th>暗盤升跌</th><th>暗盤成交額</th>
      </tr>
      <tr><td>華曦達 00901.HK</td><td>0.25</td><td>0.332</td><td>+32.8%</td><td>1,200,000</td></tr>
    </table>
    """
    collector = GreyMarketCollector()

    items = collector.parse(RawFetchResult(url="https://example.test/grey", status_code=200, text=html))

    assert len(items) == 1
    assert items[0]["stock_code"] == "00901"
    assert items[0]["grey_price"] == 0.332
    assert items[0]["offer_price"] == 0.25
    assert items[0]["change_percent"] == 32.8
    assert items[0]["turnover_hkd"] == 1200000.0
