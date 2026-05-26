"""Email 通知发送。"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from loguru import logger

from app.notifier.base import BaseNotifier, SendResult


class EmailNotifier(BaseNotifier):
    """邮件通知。"""

    channel = "email"

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        receivers: list[str],
        encryption: str = "starttls",
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.receivers = receivers
        self.encryption = encryption

    def send(self, title: str, body: str) -> SendResult:
        """发送邮件。"""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.username
            # Show a single destination normally, while keeping group delivery private.
            msg["To"] = (
                self.receivers[0]
                if len(self.receivers) == 1
                else "undisclosed-recipients:;"
            )
            msg["Subject"] = title
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if self.encryption == "ssl":
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                if self.encryption == "starttls":
                    server.starttls()

            server.login(self.username, self.password)
            server.sendmail(self.username, self.receivers, msg.as_string())
            server.quit()

            logger.info(f"Email sent to {len(self.receivers)} recipients")
            return SendResult(channel=self.channel, success=True)
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return SendResult(channel=self.channel, success=False, error_message=str(e))
