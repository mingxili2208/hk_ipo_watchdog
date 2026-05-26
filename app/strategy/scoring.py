"""策略评分模块。"""

from app.models import IPOItem, AllotmentResult, GreyMarketQuote
from app.strategy.config_loader import StrategyConfig


def calculate_score(
    ipo: IPOItem,
    config: StrategyConfig,
    allotment: AllotmentResult | None = None,
    grey: GreyMarketQuote | None = None,
) -> int:
    """计算综合得分（0-100）。"""
    score = 0

    score += _score_basic(ipo, config)
    score += _score_subscription(allotment, config)
    score += _score_allotment_structure(allotment, config)
    score += _score_grey_market(grey, config)
    score += _score_sponsor(ipo, config)
    score -= _score_risks(ipo, allotment, config)

    return max(0, min(100, score))


def decide_alert_level(score: int, config: StrategyConfig) -> int:
    """根据分数决定提醒等级。"""
    if score >= config.alerts.urgent_score_above:
        return 4
    if score >= config.alerts.important_score_above:
        return 3
    if score >= config.alerts.watch_score_above:
        return 2
    return 1


def _score_basic(ipo: IPOItem, config: StrategyConfig) -> int:
    """基本面评分（权重占比）。"""
    s = 0
    weight = config.scoring.basic_weight

    if ipo.entry_fee_hkd:
        if ipo.entry_fee_hkd <= 5000:
            s += weight * 0.4
        elif ipo.entry_fee_hkd <= 10000:
            s += weight * 0.25
        elif ipo.entry_fee_hkd <= 20000:
            s += weight * 0.1

    if ipo.market_cap_hkd and ipo.market_cap_hkd >= 1_000_000_000:
        s += weight * 0.3

    if ipo.industry and ipo.industry.lower() not in [i.lower() for i in config.basic.exclude_industries]:
        s += weight * 0.3

    return min(int(s), weight)


def _score_subscription(allotment: AllotmentResult | None, config: StrategyConfig) -> int:
    """认购热度评分。"""
    if not allotment or not allotment.public_subscription_times:
        return 0

    weight = config.scoring.subscription_weight
    times = allotment.public_subscription_times

    if times >= 100:
        return weight
    elif times >= 50:
        return int(weight * 0.8)
    elif times >= 20:
        return int(weight * 0.6)
    elif times >= 10:
        return int(weight * 0.4)
    elif times >= 5:
        return int(weight * 0.2)
    return int(weight * 0.1)


def _score_allotment_structure(allotment: AllotmentResult | None, config: StrategyConfig) -> int:
    """中签结构评分。"""
    if not allotment:
        return 0

    weight = config.scoring.allotment_weight
    s = 0

    if allotment.one_lot_success_rate:
        if allotment.one_lot_success_rate >= 20:
            s += weight * 0.5
        elif allotment.one_lot_success_rate >= 10:
            s += weight * 0.35
        elif allotment.one_lot_success_rate >= 5:
            s += weight * 0.2
        else:
            s += weight * 0.05

    if allotment.clawback_ratio and allotment.clawback_ratio > 0:
        s += weight * 0.3

    if allotment.public_subscription_times and allotment.public_subscription_times > 15:
        s += weight * 0.2

    return min(int(s), weight)


def _score_grey_market(grey: GreyMarketQuote | None, config: StrategyConfig) -> int:
    """暗盘表现评分。"""
    if not grey or grey.change_percent is None:
        return 0

    weight = config.scoring.grey_market_weight
    change = grey.change_percent

    if change >= 20:
        return weight
    elif change >= 10:
        return int(weight * 0.8)
    elif change >= 5:
        return int(weight * 0.6)
    elif change >= 0:
        return int(weight * 0.3)
    elif change >= -3:
        return int(weight * 0.1)
    else:
        return 0


def _score_sponsor(ipo: IPOItem, config: StrategyConfig) -> int:
    """保荐人评分。"""
    if not ipo.sponsors:
        return 0

    weight = config.scoring.sponsor_weight
    for s in ipo.sponsors:
        if s in config.sponsor.whitelist:
            return weight

    return int(weight * 0.3)


def _score_risks(
    ipo: IPOItem,
    allotment: AllotmentResult | None,
    config: StrategyConfig,
) -> int:
    """风险扣分。"""
    penalty = 0
    max_penalty = config.scoring.risk_penalty_max

    if ipo.industry and ipo.industry.lower() in [i.lower() for i in config.basic.exclude_industries]:
        penalty += 15

    if allotment and allotment.public_subscription_times and allotment.public_subscription_times < 2:
        penalty += 10

    if ipo.market and ipo.market == "GEM":
        penalty += 10

    return min(penalty, max_penalty)


def collect_matched_rules(
    ipo: IPOItem,
    config: StrategyConfig,
    allotment: AllotmentResult | None = None,
    grey: GreyMarketQuote | None = None,
) -> list[str]:
    """收集命中的规则。"""
    rules = []

    if ipo.entry_fee_hkd and ipo.entry_fee_hkd <= 5000:
        rules.append("low_entry_fee")

    if allotment and allotment.public_subscription_times and allotment.public_subscription_times >= 20:
        rules.append("hot_subscription")

    if allotment and allotment.one_lot_success_rate and allotment.one_lot_success_rate >= 10:
        rules.append("high_one_lot_rate")

    if grey and grey.change_percent and grey.change_percent >= 5:
        rules.append("strong_grey_market")

    if ipo.sponsors:
        for s in ipo.sponsors:
            if s in config.sponsor.whitelist:
                rules.append("top_sponsor")
                break

    return rules


def collect_trigger_reasons(
    ipo: IPOItem,
    config: StrategyConfig,
    allotment: AllotmentResult | None = None,
    grey: GreyMarketQuote | None = None,
) -> list[str]:
    """生成触发原因（中文）。"""
    reasons = []

    if ipo.entry_fee_hkd and ipo.entry_fee_hkd <= 5000:
        reasons.append("入场费低于 5,000 HKD")

    if ipo.entry_fee_hkd and ipo.entry_fee_hkd <= 3000:
        reasons.append("入场费极低，适合小资金参与")

    if allotment and allotment.public_subscription_times:
        if allotment.public_subscription_times >= 100:
            reasons.append("公开发售超购超过 100 倍")
        elif allotment.public_subscription_times >= 20:
            reasons.append("公开发售超购超过 20 倍")

    if allotment and allotment.one_lot_success_rate and allotment.one_lot_success_rate >= 10:
        reasons.append("一手中签率较高")

    if grey and grey.change_percent and grey.change_percent >= 5:
        reasons.append(f"暗盘涨幅 {grey.change_percent:.1f}%")

    if ipo.sponsors:
        for s in ipo.sponsors:
            if s in config.sponsor.whitelist:
                reasons.append(f"保荐人为头部券商 ({s})")
                break

    return reasons


def collect_risk_flags(
    ipo: IPOItem,
    allotment: AllotmentResult | None = None,
    grey: GreyMarketQuote | None = None,
) -> list[str]:
    """收集风险标记。"""
    flags = []

    if grey and grey.change_percent and grey.change_percent < -3:
        flags.append(f"暗盘下跌 {grey.change_percent:.1f}%")

    if ipo.market == "GEM":
        flags.append("GEM 板块股票")

    if not ipo.entry_fee_hkd:
        flags.append("缺少入场费数据")

    if not allotment:
        flags.append("缺少配发结果数据")

    if not grey:
        flags.append("缺少暗盘数据")

    return flags
