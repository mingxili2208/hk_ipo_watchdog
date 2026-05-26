"""配发结果解析。"""

import re
from datetime import datetime

from loguru import logger

from app.models import AllotmentResult


def parse_allotment_result_text(text: str, stock_code: str = "") -> AllotmentResult:
    """从配发结果文本中提取字段。"""
    result = AllotmentResult(stock_code=stock_code)

    # 最终发售价
    price_patterns = [
        r"(?:Offer Price|offer price|發售價|发售价)[^\d]*?(?:HK\$|HKD)?\s*([\d,]+\.?\d*)",
        r"(?:每股|per share)[^\d]*?(?:HK\$|HKD)?\s*([\d,]+\.?\d*)\s*(?:港元|HKD|港幣)?",
    ]
    for pat in price_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result.final_offer_price = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # 公开发售超购倍数
    sub_patterns = [
        r"(?:over-subscribed|超額認購|超额认购)[^\d]*?([\d,]+\.?\d*)\s*(?:times|倍)",
        r"(?:approximately|約|约)\s*([\d,]+\.?\d*)\s*(?:times|倍)",
    ]
    for pat in sub_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result.public_subscription_times = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # 一手中签率
    lot_patterns = [
        r"(?:one board lot|一手|申請一手|申请一手)[^\d]*?([\d,]+\.?\d*)\s*%",
        r"(?:中籤率|中签率)[^\d]*?([\d,]+\.?\d*)\s*%",
    ]
    for pat in lot_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result.one_lot_success_rate = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # 回拨比例
    clawback_pat = r"(?:clawback|回拨|回撥)[^\d]*?([\d,]+\.?\d*)\s*%"
    m = re.search(clawback_pat, text, re.IGNORECASE)
    if m:
        try:
            result.clawback_ratio = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # 国际配售认购倍数
    intl_pat = r"(?:international (?:placing|offering)|國際配售|国际配售)[^\d]*?([\d,]+\.?\d*)\s*(?:times|倍)"
    m = re.search(intl_pat, text, re.IGNORECASE)
    if m:
        try:
            result.international_subscription_times = float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # 总申请人数
    total_pat = r"(?:total (?:number of )?applications|總申請|总申请)[^\d]*?([\d,]+)"
    m = re.search(total_pat, text, re.IGNORECASE)
    if m:
        try:
            result.total_applicants = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # 判断解析置信度
    filled = sum(
        1
        for f in [
            result.final_offer_price,
            result.public_subscription_times,
            result.one_lot_success_rate,
        ]
        if f is not None
    )
    if filled >= 2:
        result.parse_confidence = "high"
    elif filled >= 1:
        result.parse_confidence = "medium"
    else:
        result.parse_confidence = "low"

    return result
