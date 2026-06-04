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


class LLMEvaluation(BaseModel):
    """LLM 结构化评估结果（用于申购推荐阶段）。"""

    business_quality: int  # 1-10: 商业模式、竞争壁垒
    business_quality_reason: str = ""  # 具体事实陈述
    financial_health: int  # 1-10: 盈利能力、增速、负债
    financial_health_reason: str = ""  # 具体事实陈述
    valuation_fairness: int  # 1-10: 相对同行业定价合理性
    valuation_fairness_reason: str = ""  # 具体事实陈述
    growth_prospect: int  # 1-10: 行业前景、增长空间
    growth_prospect_reason: str = ""  # 具体事实陈述
    risk_level: str  # low / medium / high / very_high
    risk_factors: list[str]  # 具体风险点
    comparable_companies: list[str]  # 可比公司名称
    recommended_action: str  # subscribe / skip / watch
    confidence: str  # low / medium / high
    reasoning: str  # 推理过程
    evaluation_source: str = "llm"


class ProspectusFinancials(BaseModel):
    """从招股书中提取的财务数据。"""

    revenue_hkd_million: float | None = None  # 最近一年收入（百万港元）
    net_profit_hkd_million: float | None = None  # 最近一年净利润
    revenue_growth_yoy: float | None = None  # 收入同比增速 (%)
    net_profit_growth_yoy: float | None = None  # 净利润同比增速 (%)
    gross_margin: float | None = None  # 毛利率 (%)
    net_margin: float | None = None  # 净利率 (%)
    total_debt_to_equity: float | None = None  # 资产负债率
    fiscal_year: str | None = None  # 财年标识，如 "FY2025"
    extraction_source: str = "llm"


class SponsorStats(BaseModel):
    """保荐人历史表现统计。"""

    sponsor_name: str
    total_ipo_count: int  # 总保荐 IPO 数
    avg_score: float  # 平均策略评分
    avg_llm_score: float  # 平均 LLM 评估分
    high_score_ratio: float  # 评分 ≥60 的比例


class MarketHeat(BaseModel):
    """近期 IPO 市场热度指标。"""

    recent_ipo_count_30d: int  # 近 30 天 IPO 数量
    avg_score_30d: float  # 近 30 天 IPO 平均评分
    high_score_count_30d: int  # 近 30 天评分 ≥60 的数量
    active_ipo_count: int  # 当前活跃 IPO 数量


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
