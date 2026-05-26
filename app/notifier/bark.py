"""Bark 通知发送。"""

import httpx
from loguru import logger

from app.notifier.base import BaseNotifier, SendResult


class BarkNotifier(BaseNotifier):
    """Bark 推送。"""

    channel = "bark"

    def __init__(self, device_key: str, server_url: str = "https://api.day.app"):
        self.device_key = device_key
        self.server_url = server_url.rstrip("/")

    def send(self, title: str, body: str) -> SendResult:
        """发送 Bark 通知。"""
        try:
            url = f"{self.server_url}/{self.device_key}"
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    url,
                    json={"title": title, "body": body, "group": "hk-ipo-watchdog"},
                )
                resp.raise_for_status()
                logger.info("Bark notification sent")
                return SendResult(channel=self.channel, success=True)
        except httpx.HTTPError as e:
            logger.error(f"Bark send failed: {e}")
            return SendResult(channel=self.channel, success=False, error_message=str(e))
