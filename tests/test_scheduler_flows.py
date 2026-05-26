"""调度任务、存储和通知闭环回归测试。"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.llm.client import LLMService
from app.llm.providers.mock_provider import MockLLMProvider
from app.models import Announcement, GreyMarketQuote, IPOItem, StrategyDecision
from app.notifier.base import SendResult
from app.scheduler import SchedulerApp
from app.settings import Settings
from app.storage.db import init_db
from app.storage.models import IPOEventORM, LLMUsageORM, NotificationORM
from app.storage.repository import Repository
from app.strategy.config_loader import StrategyConfig


class FakeNotifier:
    def __init__(self, channel: str):
        self.channel = channel
        self.calls = 0
        self.bodies = []

    def send(self, title: str, body: str) -> SendResult:
        self.calls += 1
        self.bodies.append(body)
        return SendResult(channel=self.channel, success=True)


class RetryOnceNotifier(FakeNotifier):
    def send(self, title: str, body: str) -> SendResult:
        self.calls += 1
        self.bodies.append(body)
        if self.calls == 1:
            return SendResult(channel=self.channel, success=False, error_message="temporary")
        return SendResult(channel=self.channel, success=True)


class UsageProvider(MockLLMProvider):
    def generate(self, messages):
        response = super().generate(messages)
        self._last_usage = {
            "provider": "openai",
            "model": "glm-5.1",
            "prompt_tokens": 40,
            "completion_tokens": 20,
            "cached_tokens": 5,
            "total_tokens": 60,
        }
        return response


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


def test_token_usage_footer_is_only_added_to_email_channel():
    app, repo = _make_app()
    repo.session.add(
        LLMUsageORM(
            purpose="ipo_alert",
            provider="openai",
            model="glm-5.1",
            prompt_tokens=40,
            completion_tokens=20,
            cached_tokens=5,
            total_tokens=60,
            created_at=datetime(2026, 5, 25, 16, 30, tzinfo=timezone.utc),
        )
    )
    repo.session.commit()
    telegram = FakeNotifier("telegram")
    email = FakeNotifier("email")
    app._notifiers = [("telegram", telegram, 1), ("email", email, 1)]

    with patch("app.utils.time_utils.today_hk", return_value=date(2026, 5, 26)):
        app._send_notification("title", "body", 2, "02616:new_ipo:usage", "02616", "new_ipo")

    assert "今日 LLM Token 用量" not in telegram.bodies[0]
    assert "今日 LLM Token 用量" in email.bodies[0]
    assert "总 Token: 60" in email.bodies[0]


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


def test_daily_digest_can_be_resend_without_replacing_original_record():
    app, repo = _make_app()
    notifier = FakeNotifier("email")
    app._notifiers = [("email", notifier, 1)]

    with patch("app.utils.time_utils.today_hk", return_value=date(2026, 5, 26)):
        with patch(
            "app.utils.time_utils.now_hk",
            return_value=datetime(2026, 5, 26, 22, 30, tzinfo=timezone.utc),
        ):
            app.job_send_daily_digest()
            app.job_send_daily_digest(resend=True)

    rows = repo.session.query(NotificationORM).order_by(NotificationORM.id).all()
    assert notifier.calls == 2
    assert rows[0].notification_key == "digest:daily_digest:2026-05-26"
    assert rows[1].notification_key.startswith("digest:daily_digest:2026-05-26:resend:")
    assert rows[1].title.startswith("[补发]")
    assert "更新补发版本" in rows[1].body


def test_daily_digest_events_include_stored_ipo_snapshot():
    app, repo = _make_app()
    ipo = _ipo().model_copy(
        update={
            "subscription_start_date": date(2026, 5, 26),
            "subscription_close_date": date(2026, 5, 29),
            "listing_date": date(2026, 6, 3),
            "offer_price_min": 17.1,
            "offer_price_max": 17.1,
            "entry_fee_hkd": 3454.49,
        }
    )
    repo.upsert_ipo(ipo)
    with patch("app.utils.time_utils.today_hk", return_value=date(2026, 5, 26)):
        repo.add_event(
            stock_code=ipo.stock_code,
            event_type="new_ipo",
            title="发现新 IPO",
        )
        events = repo.get_today_events()

    assert events[0]["ipo"]["subscription_close_date"] == "2026-05-29"
    assert events[0]["ipo"]["offer_price_min"] == 17.1
    assert events[0]["ipo"]["entry_fee_hkd"] == 3454.49


def test_daily_digest_attaches_current_strategy_score_without_alert_send():
    app, repo = _make_app()
    repo.upsert_ipo(_ipo())
    notifier = FakeNotifier("email")
    app._notifiers = [("email", notifier, 1)]
    with patch("app.utils.time_utils.today_hk", return_value=date(2026, 5, 26)):
        repo.add_event(stock_code="02616", event_type="new_ipo", title="发现新 IPO")
        events = app._attach_digest_scores(repo.get_today_events())

    score = events[0]["strategy_score"]
    assert score["score"] > 0
    assert score["push_score_threshold"] == 60
    assert any("基础信息" in item for item in score["score_breakdown"])
    assert notifier.calls == 0


def test_follow_up_on_next_day_counts_down_and_references_discovery_digest():
    app, repo = _make_app()
    ipo = _ipo().model_copy(update={"listing_date": date(2026, 6, 3)})
    repo.upsert_ipo(ipo)
    repo.add_event(stock_code="02616", event_type="new_ipo", title="发现新 IPO")
    event = repo.session.query(IPOEventORM).one()
    event.created_at = datetime(2026, 5, 26, 8, tzinfo=timezone.utc)
    repo.session.commit()
    repo.record_notification(
        notification_key="digest:daily_digest:2026-05-26",
        stock_code=None,
        notification_type="daily_digest",
        level=2,
        channel="email",
        title="日报",
        body="body",
        status="sent",
    )

    with patch("app.utils.time_utils.today_hk", return_value=date(2026, 5, 27)):
        follow_ups = repo.get_ipo_follow_ups_for_digest()

    assert follow_ups[0]["stock_code"] == "02616"
    assert follow_ups[0]["days_to_listing"] == 7
    assert follow_ups[0]["detail_digest_date"] == "2026-05-26"


def test_follow_up_excludes_item_without_listing_date():
    app, repo = _make_app()
    repo.upsert_ipo(_ipo())
    repo.add_event(stock_code="02616", event_type="new_ipo", title="发现新 IPO")
    event = repo.session.query(IPOEventORM).one()
    event.created_at = datetime(2026, 5, 26, 8, tzinfo=timezone.utc)
    repo.session.commit()

    with patch("app.utils.time_utils.today_hk", return_value=date(2026, 5, 27)):
        assert repo.get_ipo_follow_ups_for_digest() == []


def test_llm_service_records_vendor_token_usage():
    init_db("sqlite:///:memory:")
    repo = Repository()
    service = LLMService(UsageProvider(), usage_recorder=repo.record_llm_usage)
    decision = StrategyDecision(
        stock_code="02616",
        passed=True,
        score=70,
        level=2,
        evaluated_at=datetime.now(timezone.utc),
    )

    service.summarize_ipo_alert(_ipo(), decision)

    usage = repo.session.query(LLMUsageORM).one()
    assert usage.purpose == "ipo_alert"
    assert usage.total_tokens == 60
    assert repo.get_llm_usage_summary()[0]["cached_tokens"] == 5


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


def test_calendar_fetches_official_business_overview_only_until_stored():
    app, repo = _make_app()
    official = _ipo().model_copy(
        update={
            "raw_sources": {
                "hkex_new_listing": {"prospectus_url": "https://example.test/prospectus.pdf"}
            }
        }
    )
    app._collect_all_ipo_sources = lambda: [official]

    with patch(
        "app.collectors.hkex_new_listing.HKEXNewListingCollector.fetch_business_overview",
        return_value="We provide consumer 3D printing products and services.",
    ) as fetch:
        app.job_collect_ipo_calendar()
        app.job_collect_ipo_calendar()

    assert repo.get_ipo_by_code("02616").business_overview.startswith("We provide")
    assert fetch.call_count == 1


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

    app.job_collect_grey_market(ignore_window=True)

    assert notifier.calls == 1
    assert repo.has_notification_been_sent("02616:grey_market_breakout:grey_broker_2026-05-25_down_0")


def test_grey_market_same_tier_notifies_once_but_material_move_notifies_again():
    app, repo = _make_app()
    repo.upsert_ipo(_ipo())
    notifier = FakeNotifier("telegram")
    app._notifiers = [("telegram", notifier, 1)]
    quotes = iter(
        [
            GreyMarketQuote(
                stock_code="02616",
                source="aastocks",
                change_percent=-4.0,
                quoted_at=datetime(2026, 5, 25, 16, 15),
            ),
            GreyMarketQuote(
                stock_code="02616",
                source="aastocks",
                change_percent=-4.5,
                quoted_at=datetime(2026, 5, 25, 16, 20),
            ),
            GreyMarketQuote(
                stock_code="02616",
                source="aastocks",
                change_percent=-8.1,
                quoted_at=datetime(2026, 5, 25, 16, 25),
            ),
        ]
    )
    app._collect_grey_market = lambda codes: [next(quotes)]

    for _ in range(3):
        app.job_collect_grey_market(ignore_window=True)

    assert notifier.calls == 2
    assert repo.has_notification_been_sent("02616:grey_market_breakout:grey_aastocks_2026-05-25_down_0")
    assert repo.has_notification_been_sent("02616:grey_market_breakout:grey_aastocks_2026-05-25_down_1")


def test_scheduled_grey_market_collection_skips_outside_market_window():
    settings = Settings(
        schedule={
            "grey_market": {
                "enabled": True,
                "interval_minutes": 5,
                "window_start": "16:15",
                "window_end": "18:30",
                "weekdays_only": True,
            }
        }
    )
    app, _ = _make_app(settings)
    app._collect_grey_market = MagicMock(return_value=[])

    with patch(
        "app.utils.time_utils.now_hk",
        return_value=datetime(2026, 5, 25, 15, 0, tzinfo=timezone.utc),
    ):
        app.job_collect_grey_market()

    app._collect_grey_market.assert_not_called()


def test_grey_market_collection_skips_request_without_active_ipos():
    app, _ = _make_app()
    app._collect_grey_market = MagicMock(return_value=[])

    app.job_collect_grey_market(ignore_window=True)

    app._collect_grey_market.assert_not_called()


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
