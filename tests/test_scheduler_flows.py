"""调度任务、存储和通知闭环回归测试。"""

from datetime import datetime, timezone
from unittest.mock import patch

from app.llm.client import LLMService
from app.llm.providers.mock_provider import MockLLMProvider
from app.models import Announcement, GreyMarketQuote, IPOItem
from app.notifier.base import SendResult
from app.scheduler import SchedulerApp
from app.settings import Settings
from app.storage.db import init_db
from app.storage.models import IPOEventORM, NotificationORM
from app.storage.repository import Repository
from app.strategy.config_loader import StrategyConfig


class FakeNotifier:
    def __init__(self, channel: str):
        self.channel = channel
        self.calls = 0

    def send(self, title: str, body: str) -> SendResult:
        self.calls += 1
        return SendResult(channel=self.channel, success=True)


class RetryOnceNotifier(FakeNotifier):
    def send(self, title: str, body: str) -> SendResult:
        self.calls += 1
        if self.calls == 1:
            return SendResult(channel=self.channel, success=False, error_message="temporary")
        return SendResult(channel=self.channel, success=True)


def _make_app(settings: Settings | None = None) -> tuple[SchedulerApp, Repository]:
    init_db("sqlite:///:memory:")
    repo = Repository()
    app = SchedulerApp(
        settings or Settings(),
        StrategyConfig(),
        LLMService(MockLLMProvider()),
        repo,
    )
    return app, repo


def _ipo() -> IPOItem:
    return IPOItem(
        stock_code="02616",
        stock_name="Example",
        market="Main Board",
        industry="technology",
        status="subscription_open",
        entry_fee_hkd=3000.0,
        lot_size=1000,
        sponsors=["CICC"],
        source="hkex_new_listing",
        raw_sources={"hkex_new_listing": {"code": "02616"}},
    )


def test_no_real_calendar_data_does_not_inject_mock_items():
    settings = Settings(
        sources={
            "hkex_new_listing": {"enabled": False},
            "aastocks_ipo": {"enabled": False},
            "hkex_news": {"enabled": False},
            "grey_market": {"enabled": False},
        }
    )
    app, _ = _make_app(settings)

    assert app._collect_all_ipo_sources() == []


def test_email_notifier_uses_configured_recipient_list(monkeypatch):
    settings = Settings(
        notification={"email": {"enabled": True, "encryption": "ssl"}},
        recipients={"email": ["first@example.com", "second@example.com"]},
    )
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    app, _ = _make_app(settings)

    channel, notifier, min_level = app._get_notifiers()[0]

    assert channel == "email"
    assert notifier.receivers == ["first@example.com", "second@example.com"]
    assert notifier.encryption == "ssl"
    assert min_level == 3


def test_multi_channel_send_records_one_logical_notification():
    app, repo = _make_app()
    first = FakeNotifier("telegram")
    second = FakeNotifier("email")
    app._notifiers = [("telegram", first, 1), ("email", second, 1)]

    app._send_notification("title", "body", 2, "02616:new_ipo:event", "02616", "new_ipo")

    records = repo.session.query(NotificationORM).all()
    assert first.calls == second.calls == 1
    assert len(records) == 1
    assert records[0].channel == "telegram,email"
    assert repo.has_notification_been_sent("02616:new_ipo:event")


def test_multi_channel_retry_only_retries_failed_channel():
    app, repo = _make_app()
    telegram = FakeNotifier("telegram")
    email = RetryOnceNotifier("email")
    app._notifiers = [("telegram", telegram, 1), ("email", email, 1)]

    app._send_notification("title", "body", 2, "02616:new_ipo:retry", "02616", "new_ipo")
    first = repo.session.query(NotificationORM).one()
    assert first.status == "partial"
    assert first.channel == "telegram"

    app._send_notification("title", "body", 2, "02616:new_ipo:retry", "02616", "new_ipo")
    second = repo.session.query(NotificationORM).one()
    assert telegram.calls == 1
    assert email.calls == 2
    assert second.status == "sent"
    assert second.channel == "telegram,email"


def test_quiet_hours_defers_notification_send():
    settings = Settings(
        notification={"quiet_hours": {"enabled": True, "start": "23:00", "end": "08:00"}}
    )
    app, repo = _make_app(settings)
    notifier = FakeNotifier("telegram")
    app._notifiers = [("telegram", notifier, 1)]

    with patch("app.utils.time_utils.now_hk", return_value=datetime(2026, 5, 25, 23, 30, tzinfo=timezone.utc)):
        app._send_notification("title", "body", 2, "02616:new_ipo:quiet", "02616", "new_ipo")

    assert notifier.calls == 0
    assert not repo.has_notification_been_sent("02616:new_ipo:quiet")


def test_daily_digest_is_sent_only_once_per_day():
    app, _ = _make_app()
    notifier = FakeNotifier("telegram")
    app._notifiers = [("telegram", notifier, 1)]

    app.job_send_daily_digest()
    app.job_send_daily_digest()

    assert notifier.calls == 1


def test_allotment_collection_recalculates_and_notifies():
    app, repo = _make_app()
    repo.upsert_ipo(_ipo())
    notifier = FakeNotifier("telegram")
    app._notifiers = [("telegram", notifier, 1)]
    app._collect_announcements = lambda: [
        Announcement(
            stock_code="02616",
            title="Allotment Results",
            announcement_type="allotment_result",
            source="hkex_news",
            url="https://example.test/allotment.pdf",
            raw_text="Offer Price HK$3.00 over-subscribed by 100 times one board lot 20%",
        )
    ]

    app.job_collect_announcements()

    assert notifier.calls == 1
    assert repo.has_notification_been_sent("02616:allotment_result:announcement_1")
    assert repo.get_ipo_by_code("02616").status == "allotment_result_published"


def test_allotment_for_untracked_historical_ipo_is_ignored():
    app, repo = _make_app()
    app._collect_announcements = lambda: [
        Announcement(
            stock_code="06872",
            title="Allotment Results",
            announcement_type="allotment_result",
            source="hkex_news",
            url="https://example.test/historical.pdf",
            raw_text="Offer Price HK$75.70",
        )
    ]

    app.job_collect_announcements()

    assert repo.get_latest_allotment("06872") is None
    assert repo.session.query(IPOEventORM).count() == 0


def test_same_scan_source_enrichment_only_records_new_ipo_event():
    app, repo = _make_app()
    official = _ipo()
    website = _ipo().model_copy(
        update={
            "industry": "technology",
            "source": "aastocks_ipo",
            "raw_sources": {"aastocks_ipo": {"fee": "3000"}},
        }
    )
    app._collect_all_ipo_sources = lambda: [official, website]

    app.job_collect_ipo_calendar()

    events = repo.session.query(IPOEventORM).all()
    assert [(event.stock_code, event.event_type) for event in events] == [("02616", "new_ipo")]


def test_closed_ipo_is_seeded_for_allotment_without_new_ipo_event():
    app, repo = _make_app()
    app._collect_all_ipo_sources = lambda: [
        _ipo().model_copy(update={"status": "subscription_closed"})
    ]

    app.job_collect_ipo_calendar()

    assert repo.get_ipo_by_code("02616").status == "subscription_closed"
    assert repo.session.query(IPOEventORM).count() == 0


def test_downside_grey_quote_generates_risk_notification():
    app, repo = _make_app()
    repo.upsert_ipo(_ipo())
    notifier = FakeNotifier("telegram")
    app._notifiers = [("telegram", notifier, 1)]
    quote = GreyMarketQuote(
        stock_code="02616",
        source="broker",
        change_percent=-4.0,
        quoted_at=datetime(2026, 5, 25, 16, 15),
    )
    app._collect_grey_market = lambda codes: [quote]

    app.job_collect_grey_market()

    assert notifier.calls == 1
    assert repo.has_notification_been_sent("02616:grey_market_breakout:grey_broker_202605251615")


def test_official_source_fields_are_not_overwritten_but_missing_fields_are_filled():
    _, repo = _make_app()
    official = _ipo().model_copy(update={"stock_name": "Official Name", "entry_fee_hkd": None})
    website = _ipo().model_copy(
        update={
            "stock_name": "Website Name",
            "entry_fee_hkd": 3030.30,
            "source": "aastocks_ipo",
            "raw_sources": {"aastocks_ipo": {"fee": "3030.30"}},
        }
    )

    repo.upsert_ipo(official)
    repo.upsert_ipo(website)
    stored = repo.get_ipo_by_code("02616")

    assert stored.stock_name == "Official Name"
    assert stored.entry_fee_hkd == 3030.30
    assert set(stored.raw_sources) == {"hkex_new_listing", "aastocks_ipo"}


def test_lower_priority_source_can_advance_lifecycle_status():
    _, repo = _make_app()
    repo.upsert_ipo(_ipo())
    closed = _ipo().model_copy(update={"status": "subscription_closed", "source": "aastocks_ipo"})

    repo.upsert_ipo(closed)

    assert repo.get_ipo_by_code("02616").status == "subscription_closed"
