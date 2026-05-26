"""策略配置加载。"""

from pathlib import Path

import yaml
from pydantic import BaseModel
from loguru import logger

from app.exceptions import ConfigError


class BasicConfig(BaseModel):
    max_entry_fee_hkd: float = 20000
    min_market_cap_hkd: float = 0
    allowed_markets: list[str] = ["Main Board"]
    exclude_industries: list[str] = ["property", "traditional retail", "loss-making biotech"]


class SubscriptionConfig(BaseModel):
    min_public_subscription_times: float = 10
    prefer_reallocation_triggered: bool = True
    min_one_lot_success_rate: float = 5


class ValuationConfig(BaseModel):
    max_pe: float = 40
    prefer_profitable: bool = True


class SponsorConfig(BaseModel):
    whitelist: list[str] = ["CICC", "Morgan Stanley", "Goldman Sachs", "Haitong International"]
    blacklist: list[str] = []


class GreyMarketConfig(BaseModel):
    min_grey_gain_percent: float = 5
    alert_if_below_percent: float = -3
    re_alert_step_percent: float = 5


class ScoringConfig(BaseModel):
    basic_weight: int = 30
    subscription_weight: int = 20
    allotment_weight: int = 15
    grey_market_weight: int = 20
    sponsor_weight: int = 10
    risk_penalty_max: int = 30


class AlertsConfig(BaseModel):
    watch_score_above: int = 60
    important_score_above: int = 75
    urgent_score_above: int = 85
    only_push_score_above: int = 60


class StrategyConfig(BaseModel):
    basic: BasicConfig = BasicConfig()
    subscription: SubscriptionConfig = SubscriptionConfig()
    valuation: ValuationConfig = ValuationConfig()
    sponsor: SponsorConfig = SponsorConfig()
    grey_market: GreyMarketConfig = GreyMarketConfig()
    scoring: ScoringConfig = ScoringConfig()
    alerts: AlertsConfig = AlertsConfig()


def load_strategy_config(path: str = "config/strategy.yaml") -> StrategyConfig:
    """加载策略配置。"""
    p = Path(path)
    if not p.exists():
        logger.warning(f"Strategy config not found: {path}, using defaults")
        return StrategyConfig()

    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return StrategyConfig(**data)
    except Exception as e:
        raise ConfigError(f"Failed to load strategy config: {e}")
