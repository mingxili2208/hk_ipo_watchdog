"""去重逻辑测试。"""

from app.utils.dedup import make_notification_key


def test_make_key():
    key = make_notification_key("03888", "new_ipo", "2026-05-25")
    assert key == "03888:new_ipo:2026-05-25"


def test_make_key_allotment():
    key = make_notification_key("03888", "allotment_result", "announcement_123")
    assert key == "03888:allotment_result:announcement_123"


def test_make_key_grey_market():
    key = make_notification_key("03888", "grey_market_breakout", "aastocks_2026-05-28T16:15")
    assert key == "03888:grey_market_breakout:aastocks_2026-05-28T16:15"
