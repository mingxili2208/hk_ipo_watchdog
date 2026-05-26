"""策略引擎 — 整合过滤、评分和等级判断。"""

from datetime import datetime

from app.models import (
    IPOItem,
    AllotmentResult,
    GreyMarketQuote,
    StrategyDecision,
)
from app.strategy.config_loader import StrategyConfig
from app.strategy.filters import apply_hard_filters
from app.strategy.scoring import (
    calculate_score,
    decide_alert_level,
    collect_matched_rules,
    collect_trigger_reasons,
    collect_risk_flags,
    collect_score_breakdown,
)


def grey_market_alert_event_key(
    grey: GreyMarketQuote,
    config: StrategyConfig,
) -> str | None:
    """构造按交易日、方向与显著幅度阶梯去重的暗盘事件 key。"""
    change = grey.change_percent
    if change is None or config.grey_market.re_alert_step_percent <= 0:
        return None

    if change >= config.grey_market.min_grey_gain_percent:
        distance = change - config.grey_market.min_grey_gain_percent
        direction = "up"
    elif change <= config.grey_market.alert_if_below_percent:
        distance = config.grey_market.alert_if_below_percent - change
        direction = "down"
    else:
        return None

    tier = int(distance // config.grey_market.re_alert_step_percent)
    return f"grey_{grey.source}_{grey.quoted_at.date()}_{direction}_{tier}"


def evaluate_ipo(
    ipo: IPOItem,
    config: StrategyConfig,
    allotment: AllotmentResult | None = None,
    grey: GreyMarketQuote | None = None,
) -> StrategyDecision:
    """对单只 IPO 进行完整策略评估。"""
    # 1. 硬过滤
    filter_result = apply_hard_filters(ipo, config)

    # 2. 计算分数
    score = calculate_score(ipo, config, allotment, grey)

    # 3. 收集匹配规则和触发原因
    matched_rules = collect_matched_rules(ipo, config, allotment, grey)
    trigger_reasons = collect_trigger_reasons(ipo, config, allotment, grey)
    risk_flags = collect_risk_flags(ipo, allotment, grey)
    score_breakdown = collect_score_breakdown(ipo, config, allotment, grey)

    # 4. 决定等级
    level = decide_alert_level(score, config)

    # 5. 缺失字段
    missing = []
    if not ipo.entry_fee_hkd:
        missing.append("entry_fee_hkd")
    if not ipo.listing_date:
        missing.append("listing_date")
    if not ipo.lot_size:
        missing.append("lot_size")

    # 6. 是否需要推送
    notification_type = _decide_notification_type(ipo, allotment, grey, config)
    downside_grey_alert = (
        notification_type == "grey_market_breakout"
        and grey is not None
        and grey.change_percent is not None
        and grey.change_percent <= config.grey_market.alert_if_below_percent
    )
    if downside_grey_alert:
        level = max(level, 3)

    should_notify = (
        filter_result.passed
        and (
            (score >= config.alerts.only_push_score_above and level >= 2)
            or downside_grey_alert
        )
    )

    # 8. 推送 key
    notification_key = None
    if should_notify and notification_type:
        event_key = ipo.status or "status_update"
        if notification_type == "allotment_result" and allotment:
            event_key = (
                f"announcement_{allotment.announcement_id}"
                if allotment.announcement_id
                else f"allotment_{allotment.stock_code}"
            )
        elif notification_type == "grey_market_breakout" and grey:
            event_key = grey_market_alert_event_key(grey, config) or "grey_threshold"
        elif notification_type == "subscription_deadline":
            event_key = str(ipo.subscription_close_date)
        elif notification_type == "new_ipo":
            event_key = str(ipo.subscription_start_date or "discovered")

        from app.utils.dedup import make_notification_key

        notification_key = make_notification_key(ipo.stock_code, notification_type, event_key)

    return StrategyDecision(
        stock_code=ipo.stock_code,
        passed=filter_result.passed,
        score=score,
        level=level,
        matched_rules=matched_rules,
        trigger_reasons=trigger_reasons,
        risk_flags=risk_flags,
        missing_fields=missing,
        score_breakdown=score_breakdown,
        should_notify=should_notify,
        notification_type=notification_type,
        notification_key=notification_key,
        evaluated_at=datetime.now(),
    )


def _decide_notification_type(
    ipo: IPOItem,
    allotment: AllotmentResult | None,
    grey: GreyMarketQuote | None,
    config: StrategyConfig,
) -> str | None:
    """根据当前状态决定通知类型。"""
    if grey and grey.change_percent is not None:
        if (
            grey.change_percent >= config.grey_market.min_grey_gain_percent
            or grey.change_percent <= config.grey_market.alert_if_below_percent
        ):
            return "grey_market_breakout"

    if allotment:
        return "allotment_result"

    if ipo.subscription_close_date:
        from app.utils.time_utils import today_hk

        days_left = (ipo.subscription_close_date - today_hk()).days
        if 0 <= days_left <= 1:
            return "subscription_deadline"

    if ipo.status in ("subscription_open", "hearing_passed"):
        return "new_ipo"

    return "status_update"
