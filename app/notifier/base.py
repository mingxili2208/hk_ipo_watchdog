"""通知基类。"""

from dataclasses import dataclass


@dataclass
class SendResult:
    """发送结果。"""

    channel: str
    success: bool
    error_message: str | None = None


class BaseNotifier:
    """通知发送器基类。"""

    channel: str = "base"

    def send(self, title: str, body: str) -> SendResult:
        """发送通知。"""
        raise NotImplementedError
