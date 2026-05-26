"""Server 酱通知发送。"""

import httpx
from loguru import logger

from app.notifier.base import BaseNotifier, SendResult


class ServerChanNotifier(BaseNotifier):
    """Server 酱推送。"""

    channel = "server_chan"

    def __init__(self, send_key: str, api_url: str = "https://sctapi.ftqq.com"):
        self.send_key = send_key
        self.api_url = api_url.rstrip("/")

    def send(self, title: str, body: str) -> SendResult:
        """发送 Server 酱通知。"""
        try:
            url = f"{self.api_url}/{self.send_key}.send"
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, data={"title": title, "desp": body})
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == 0:
                    logger.info("Server Chan notification sent")
                    return SendResult(channel=self.channel, success=True)
                else:
                    error = data.get("message", "unknown error")
                    return SendResult(channel=self.channel, success=False, error_message=error)
        except httpx.HTTPError as e:
            logger.error(f"Server Chan send failed: {e}")
            return SendResult(channel=self.channel, success=False, error_message=str(e))
