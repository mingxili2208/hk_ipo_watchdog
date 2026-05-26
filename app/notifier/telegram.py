"""Telegram 通知发送。"""

import os

import httpx
from loguru import logger

from app.exceptions import NotificationError
from app.notifier.base import BaseNotifier, SendResult


class TelegramNotifier(BaseNotifier):
    """Telegram Bot 通知。"""

    channel = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_base = f"https://api.telegram.org/bot{bot_token}"

    def send(self, title: str, body: str) -> SendResult:
        """发送 Telegram 消息。"""
        text = f"*{title}*\n\n{body}"

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{self.api_base}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("ok"):
                    logger.info(f"Telegram message sent to {self.chat_id}")
                    return SendResult(channel=self.channel, success=True)
                else:
                    error = data.get("description", "unknown error")
                    logger.error(f"Telegram API error: {error}")
                    return SendResult(channel=self.channel, success=False, error_message=error)
        except httpx.HTTPError as e:
            logger.error(f"Telegram send failed: {e}")
            return SendResult(channel=self.channel, success=False, error_message=str(e))
