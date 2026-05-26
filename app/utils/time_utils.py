"""时间工具函数。"""

from datetime import datetime, timezone, timedelta


def now_hk() -> datetime:
    """返回当前香港时间。"""
    hk_tz = timezone(timedelta(hours=8))
    return datetime.now(hk_tz)


def today_hk():
    """返回香港时区的今天日期。"""
    return now_hk().date()
