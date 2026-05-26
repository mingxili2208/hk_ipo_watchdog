"""IPO 日历 HTML 解析。"""

import re
from datetime import date

from bs4 import BeautifulSoup
from loguru import logger

from app.models import IPOItem
from app.parsers.normalizer import normalize_hk_code, normalize_money, normalize_date
from app.utils.time_utils import today_hk


def parse_ipo_calendar_html(html: str, source: str = "unknown") -> list[IPOItem]:
    """从 HTML 中解析 IPO 日历信息。

    注意: 不同数据源的 HTML 结构不同，此函数提供通用解析框架。
    实际使用时由各 collector 的 parse 方法调用。
    """
    items = []
    soup = BeautifulSoup(html, "lxml")

    # 通用表格解析
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]

        for row in rows[1:]:
            cells = row.find_all(["td"])
            if not cells:
                continue

            try:
                item = _parse_row(cells, header, source)
                if item:
                    items.append(item)
            except Exception as e:
                logger.warning(f"Failed to parse table row: {e}")
                continue

    return items


def _parse_row(cells, header: list[str], source: str) -> IPOItem | None:
    """解析单行数据为 IPOItem。"""
    cell_texts = [c.get_text(strip=True) for c in cells]
    row_data = dict(zip(header, cell_texts))

    code = _normalize_code(_lookup(
        row_data,
        ["stock code", "code", "股票代码", "股份代码", "股票代號", "股份代號", "代号", "代號"],
    ))

    if not code:
        return None

    name = _clean_stock_name(_lookup(
        row_data,
        ["stock name", "name", "股票名称", "股票名稱", "股份名称", "股份名稱", "名称", "名稱", "公司名称", "公司名稱"],
    ))
    start_date = normalize_date(_lookup(
        row_data,
        ["subscription start date", "offer start", "subscription start", "招股开始日期", "招股開始日期", "开始认购日期", "開始認購日期"],
    ))
    close_date = normalize_date(_lookup(
        row_data,
        ["subscription close date", "close date", "offer end", "subscription end", "招股截止日", "招股截止日期", "截止认购日期", "截止認購日期", "截止日期"],
    ))
    listing_date = normalize_date(_lookup(
        row_data,
        ["listing date", "listed date", "上市日期", "上市日"],
    ))

    price_min = normalize_money(_lookup(row_data, ["offer price min", "最低招股价", "最低招股價"]))
    price_max = normalize_money(_lookup(row_data, ["offer price max", "最高招股价", "最高招股價"]))
    price_range = _lookup(row_data, ["offer price", "price range", "招股价", "招股價", "发售价", "發售價"])
    if price_range and (price_min is None or price_max is None):
        parsed_min, parsed_max = _parse_price_range(price_range)
        price_min = price_min if price_min is not None else parsed_min
        price_max = price_max if price_max is not None else parsed_max

    return IPOItem(
        stock_code=code,
        stock_name=name,
        market=_lookup(row_data, ["market", "listing board", "市场板块", "市場板塊", "板块", "板塊"]),
        industry=_lookup(row_data, ["industry", "行业", "行業"]),
        status=_infer_status(start_date, close_date, listing_date),
        subscription_start_date=start_date,
        subscription_close_date=close_date,
        listing_date=listing_date,
        offer_price_min=price_min,
        offer_price_max=price_max,
        lot_size=_parse_int(_lookup(row_data, ["lot size", "board lot", "每手股数", "每手股數", "每手"])),
        entry_fee_hkd=normalize_money(_lookup(row_data, ["entry fee", "admission fee", "入场费", "入場費"])),
        source=source,
        raw_sources={source: row_data},
    )


def _lookup(row_data: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        if alias in row_data and row_data[alias]:
            return row_data[alias]
    for key, value in row_data.items():
        if value and any(alias in key for alias in aliases):
            return value
    return None


def _normalize_code(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return normalize_hk_code(value)
    except ValueError:
        return None


def _clean_stock_name(value: str | None) -> str | None:
    """移除合并在公司名字段中的 AAStocks 代码和招股提示。"""
    if not value:
        return value
    return re.sub(r"\s*\d{4,5}\.HK.*$", "", value, flags=re.IGNORECASE).strip()


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"[\d,]+", value)
    return int(match.group(0).replace(",", "")) if match else None


def _parse_price_range(value: str) -> tuple[float | None, float | None]:
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", value)
    parsed = [normalize_money(number) for number in numbers[:2]]
    if not parsed:
        return None, None
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    return parsed[0], parsed[1]


def _infer_status(
    start_date: date | None,
    close_date: date | None,
    listing_date: date | None,
) -> str:
    today = today_hk()
    if listing_date and listing_date <= today:
        return "listed"
    if close_date and close_date < today:
        return "subscription_closed"
    if start_date and start_date <= today and (not close_date or today <= close_date):
        return "subscription_open"
    return "unknown"
