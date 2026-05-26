"""CLI command behavior tests."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text

from app.main import _cmd_init_db, _cmd_test_e2e, _cmd_test_llm, _cmd_test_notification
from app.models import IPOItem
from app.notifier.base import SendResult
from app.settings import Settings
from app.storage.models import LLMUsageORM, NotificationORM
from app.storage.db import get_engine, get_session, init_db


class FakeLLMProvider:
    def __init__(self, response, usage=None):
        self.response = response
        self.usage = usage
        self.messages = None

    def generate(self, messages):
        self.messages = messages
        return self.response

    def consume_usage(self):
        usage = self.usage
        self.usage = None
        return usage


def _valid_response():
    return {
        "title": "测试摘要",
        "summary": "连通测试成功。",
        "key_points": ["测试"],
        "trigger_reasons": ["连通测试"],
        "risks": ["虚拟数据"],
        "suggested_action": "无需操作",
        "confidence": "low",
    }


def test_init_db_registers_llm_usage_table():
    _cmd_init_db(Settings(database_url="sqlite:///:memory:"))

    assert "llm_usage" in inspect(get_engine()).get_table_names()


def test_init_db_adds_business_overview_column_to_existing_sqlite_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy_engine = create_engine(database_url)
    with legacy_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE ipo_items (id INTEGER PRIMARY KEY, stock_code TEXT UNIQUE NOT NULL)")
        )

    init_db(database_url)

    columns = {column["name"] for column in inspect(get_engine()).get_columns("ipo_items")}
    assert "business_overview" in columns


def test_test_llm_validates_synthetic_response_without_notification():
    provider = FakeLLMProvider(
        _valid_response(),
        {
            "provider": "openai",
            "model": "test-model",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": 0,
        },
    )
    settings = Settings(
        database_url="sqlite:///:memory:",
        llm={"provider": "openai", "model": "test-model"},
    )

    with patch("app.llm.client.create_llm_provider", return_value=provider):
        _cmd_test_llm(settings)

    assert "LLM Connectivity Test" in provider.messages[1]["content"]
    usage = get_session().query(LLMUsageORM).one()
    assert (usage.purpose, usage.total_tokens) == ("test_llm", 15)


def test_test_llm_fails_for_invalid_schema():
    provider = FakeLLMProvider({"title": "missing fields"})

    with patch("app.llm.client.create_llm_provider", return_value=provider):
        with pytest.raises(SystemExit):
            _cmd_test_llm(Settings(database_url="sqlite:///:memory:"))


def test_test_notification_email_includes_daily_llm_usage(monkeypatch):
    settings = Settings(
        database_url="sqlite:///:memory:",
        notification={"email": {"enabled": True}},
        recipients={"email": ["receiver@example.com"]},
    )
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")

    with patch("app.notifier.email.EmailNotifier.send", return_value=SendResult("email", True)) as send:
        _cmd_test_notification(settings)

    body = send.call_args.kwargs["body"]
    assert "今日 LLM Token 用量" in body
    assert "总 Token: 0" in body


def test_test_e2e_sends_tagged_email_from_collected_real_shape_without_notification_record(monkeypatch):
    settings = Settings(
        database_url="sqlite:///:memory:",
        llm={"provider": "mock", "model": "test-model"},
        notification={"email": {"enabled": True}},
        recipients={"email": ["receiver@example.com"]},
    )
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    collected = [
        IPOItem(
            stock_code="03388",
            stock_name="Collected IPO",
            market="Main Board",
            status="subscription_open",
            entry_fee_hkd=2848.44,
            source="hkex_new_listing",
        )
    ]

    with patch("app.scheduler.SchedulerApp._collect_all_ipo_sources", return_value=collected):
        with patch("app.notifier.email.EmailNotifier.send", return_value=SendResult("email", True)) as send:
            _cmd_test_e2e(settings)

    title, body = send.call_args.kwargs["title"], send.call_args.kwargs["body"]
    assert title.startswith("[端到端测试]")
    assert "Collected IPO" in body
    assert "不构成正式提醒" in body
    assert "今日 LLM Token 用量" in body
    assert get_session().query(NotificationORM).count() == 0


def test_test_e2e_fails_without_collected_data(monkeypatch):
    settings = Settings(
        database_url="sqlite:///:memory:",
        notification={"email": {"enabled": True}},
        recipients={"email": ["receiver@example.com"]},
    )
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")

    with patch("app.scheduler.SchedulerApp._collect_all_ipo_sources", return_value=[]):
        with pytest.raises(SystemExit):
            _cmd_test_e2e(settings)
