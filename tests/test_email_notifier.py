"""Email 多收件人推送测试。"""

from unittest.mock import patch

from app.notifier.email import EmailNotifier


def test_email_notifier_sends_one_message_to_configured_recipients():
    recipients = ["first@example.com", "second@example.com"]
    notifier = EmailNotifier(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="sender@example.com",
        password="app-password",
        receivers=recipients,
    )

    with patch("app.notifier.email.smtplib.SMTP") as smtp:
        result = notifier.send("subject", "body")

    assert result.success
    smtp.return_value.starttls.assert_called_once()
    smtp.return_value.login.assert_called_once_with("sender@example.com", "app-password")
    args = smtp.return_value.sendmail.call_args.args
    assert args[0] == "sender@example.com"
    assert args[1] == recipients
    assert "To: sender@example.com" in args[2]
    assert "first@example.com" not in args[2]
    assert "second@example.com" not in args[2]


def test_email_notifier_supports_implicit_ssl():
    notifier = EmailNotifier(
        smtp_host="smtp.example.com",
        smtp_port=465,
        username="sender@example.com",
        password="app-password",
        receivers=["receiver@example.com"],
        encryption="ssl",
    )

    with patch("app.notifier.email.smtplib.SMTP") as smtp, patch(
        "app.notifier.email.smtplib.SMTP_SSL"
    ) as smtp_ssl:
        result = notifier.send("subject", "body")

    assert result.success
    smtp.assert_not_called()
    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=30)
    smtp_ssl.return_value.login.assert_called_once_with("sender@example.com", "app-password")


def test_email_notifier_supports_unencrypted_smtp_without_starttls():
    notifier = EmailNotifier(
        smtp_host="smtp.example.com",
        smtp_port=25,
        username="sender@example.com",
        password="app-password",
        receivers=["receiver@example.com"],
        encryption="none",
    )

    with patch("app.notifier.email.smtplib.SMTP") as smtp:
        result = notifier.send("subject", "body")

    assert result.success
    smtp.return_value.starttls.assert_not_called()
