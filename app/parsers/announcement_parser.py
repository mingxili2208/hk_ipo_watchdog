"""公告类型检测。"""

import re


_ANNOUNCEMENT_KEYWORDS: dict[str, list[str]] = {
    "allotment_result": [
        "allotment results",
        "basis of allocation",
        "配發結果",
        "配发结果",
        "分配基準",
        "分配基准",
    ],
    "prospectus": [
        "prospectus",
        "招股章程",
        "招股书",
    ],
    "offer_price": [
        "offer price",
        "發售價",
        "发售价",
        "offer price and",
        "发售价已",
    ],
    "global_offering": [
        "global offering",
        "全球發售",
        "全球发售",
    ],
    "stabilizing_action": [
        "stabilizing action",
        "stabilisation",
        "穩定價格",
        "稳定价格",
    ],
    "hearing_post": [
        "post hearing",
        "聆訊後",
        "聆讯后",
    ],
    "supplemental": [
        "supplemental",
        "補充",
        "补充",
    ],
}


def detect_announcement_type(title: str, body: str | None = None) -> str:
    """根据标题（和正文）判断公告类型。"""
    text = (title + " " + (body or "")).lower()

    for ann_type, keywords in _ANNOUNCEMENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return ann_type

    return "other"
