"""去重工具函数。"""


def make_notification_key(
    stock_code: str, notification_type: str, event_key: str
) -> str:
    """构造通知去重 key。

    格式: {stock_code}:{notification_type}:{event_key}
    """
    return f"{stock_code}:{notification_type}:{event_key}"
