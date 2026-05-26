"""SQLAlchemy ORM 模型。"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    Float,
    Text,
    String,
    DateTime,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IPOItemORM(Base):
    __tablename__ = "ipo_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(Text)
    stock_name_en: Mapped[str | None] = mapped_column(Text)
    market: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text, default="unknown")

    subscription_start_date = Column(Text)
    subscription_close_date = Column(Text)
    listing_date = Column(Text)

    offer_price_min = Column(Float)
    offer_price_max = Column(Float)
    final_offer_price = Column(Float)

    lot_size = Column(Integer)
    entry_fee_hkd = Column(Float)
    market_cap_hkd = Column(Float)

    sponsors_json = Column(Text, default="[]")
    cornerstone_investors_json = Column(Text, default="[]")
    raw_sources_json = Column(Text, default="{}")

    source = Column(Text)
    source_url = Column(Text)

    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class AnnouncementORM(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code = Column(Text)
    stock_name = Column(Text)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    announcement_type = Column(Text, default="other")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    published_at = Column(DateTime)
    fetched_at = Column(DateTime)

    raw_text = Column(Text)
    pdf_url = Column(Text)
    parsed = Column(Integer, default=0)

    created_at = Column(DateTime, default=_now)


class AllotmentResultORM(Base):
    __tablename__ = "allotment_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)

    final_offer_price = Column(Float)
    public_subscription_times = Column(Float)
    international_subscription_times = Column(Float)

    one_lot_success_rate = Column(Float)
    clawback_ratio = Column(Float)

    total_applicants = Column(Integer)
    valid_applicants = Column(Integer)

    basis_of_allocation_url = Column(Text)
    announcement_id = Column(Integer)

    parse_confidence = Column(Text, default="unknown")
    raw_fields_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=_now)


class GreyMarketQuoteORM(Base):
    __tablename__ = "grey_market_quotes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    grey_price = Column(Float)
    offer_price = Column(Float)
    change_percent = Column(Float)
    turnover_hkd = Column(Float)

    quoted_at = Column(DateTime)
    source_url = Column(Text)
    raw_fields_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=_now)


class IPOEventORM(Base):
    __tablename__ = "ipo_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code = Column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_key = Column(Text, unique=True)
    title = Column(Text)
    detail_json = Column(Text)
    created_at = Column(DateTime, default=_now)


class StrategyScoreORM(Base):
    __tablename__ = "strategy_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(Text, nullable=False)
    score = Column(Integer)
    level = Column(Integer)
    passed = Column(Integer)
    matched_rules_json = Column(Text, default="[]")
    trigger_reasons_json = Column(Text, default="[]")
    risk_flags_json = Column(Text, default="[]")
    missing_fields_json = Column(Text, default="[]")
    evaluated_at = Column(DateTime)


class LLMSummaryORM(Base):
    __tablename__ = "llm_summaries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stock_code = Column(Text)
    event_key = Column(Text)
    title = Column(Text)
    summary = Column(Text)
    key_points_json = Column(Text, default="[]")
    trigger_reasons_json = Column(Text, default="[]")
    risks_json = Column(Text, default="[]")
    suggested_action = Column(Text)
    confidence = Column(Text)
    summary_source = Column(Text, default="llm")
    created_at = Column(DateTime, default=_now)


class NotificationORM(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    notification_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    stock_code = Column(Text)
    notification_type = Column(Text)
    level = Column(Integer)
    channel = Column(Text)
    title = Column(Text)
    body = Column(Text)
    status = Column(Text, default="pending")
    error_message = Column(Text)
    created_at = Column(DateTime, default=_now)
    sent_at = Column(DateTime)
