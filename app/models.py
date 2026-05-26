"""Pydantic 数据模型定义。"""

from datetime import date, datetime

from pydantic import BaseModel


class IPOItem(BaseModel):
    """标准化 IPO 数据。"""

    stock_code: str
    stock_name: str | None = None
    stock_name_en: str | None = None
    market: str | None = None
    industry: str | None = None
    business_overview: str | None = None

    status: str = "unknown"

    subscription_start_date: date | None = None
    subscription_close_date: date | None = None
    listing_date: date | None = None

    offer_price_min: float | None = None
    offer_price_max: float | None = None
    final_offer_price: float | None = None

    lot_size: int | None = None
    entry_fee_hkd: float | None = None
    market_cap_hkd: float | None = None

    sponsors: list[str] = []
    cornerstone_investors: list[str] = []

    source: str | None = None
    source_url: str | None = None
    raw_sources: dict = {}

    created_at: datetime | None = None
    updated_at: datetime | None = None


class Announcement(BaseModel):
    """公告数据。"""

    id: int | None = None
    stock_code: str | None = None
    stock_name: str | None = None

    title: str
    announcement_type: str = "other"
    source: str
    url: str

    published_at: datetime | None = None
    fetched_at: datetime | None = None

    raw_text: str | None = None
    pdf_url: str | None = None
    parsed: bool = False


class AllotmentResult(BaseModel):
    """配发结果。"""

    stock_code: str

    final_offer_price: float | None = None
    public_subscription_times: float | None = None
    international_subscription_times: float | None = None

    one_lot_success_rate: float | None = None
    clawback_ratio: float | None = None

    total_applicants: int | None = None
    valid_applicants: int | None = None

    basis_of_allocation_url: str | None = None
    announcement_id: int | None = None

    parse_confidence: str = "unknown"
    raw_fields: dict = {}

    created_at: datetime | None = None


class GreyMarketQuote(BaseModel):
    """暗盘报价。"""

    stock_code: str
    source: str

    grey_price: float | None = None
    offer_price: float | None = None
    change_percent: float | None = None
    turnover_hkd: float | None = None

    quoted_at: datetime
    source_url: str | None = None
    raw_fields: dict = {}


class StrategyDecision(BaseModel):
    """策略评估结果。"""

    stock_code: str

    passed: bool
    score: int
    level: int

    matched_rules: list[str] = []
    trigger_reasons: list[str] = []
    risk_flags: list[str] = []
    missing_fields: list[str] = []
    score_breakdown: list[str] = []

    should_notify: bool = False
    notification_type: str | None = None
    notification_key: str | None = None

    evaluated_at: datetime


class LLMSummary(BaseModel):
    """LLM 生成的摘要。"""

    title: str
    summary: str
    key_points: list[str]
    trigger_reasons: list[str]
    risks: list[str]
    suggested_action: str
    confidence: str
    summary_source: str = "llm"


class Notification(BaseModel):
    """推送记录。"""

    notification_key: str
    stock_code: str | None = None

    notification_type: str
    level: int
    channel: str

    title: str
    body: str

    status: str = "pending"
    error_message: str | None = None

    created_at: datetime | None = None
    sent_at: datetime | None = None


class FilterResult(BaseModel):
    """硬过滤结果。"""

    passed: bool = True
    reasons: list[str] = []


class UpsertResult(BaseModel):
    """upsert 操作结果。"""

    created: bool
    changed_fields: list[str] = []
