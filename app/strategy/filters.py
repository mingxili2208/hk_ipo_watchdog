"""策略硬过滤。"""

from app.models import IPOItem, FilterResult
from app.strategy.config_loader import StrategyConfig


def apply_hard_filters(ipo: IPOItem, config: StrategyConfig) -> FilterResult:
    """执行硬性过滤。"""
    result = FilterResult(passed=True, reasons=[])

    # 入场费
    if ipo.entry_fee_hkd and ipo.entry_fee_hkd > config.basic.max_entry_fee_hkd:
        result.passed = False
        result.reasons.append(f"入场费 {ipo.entry_fee_hkd:.0f} 超过上限 {config.basic.max_entry_fee_hkd:.0f}")

    # 市场板块
    if config.basic.allowed_markets and ipo.market:
        if ipo.market not in config.basic.allowed_markets:
            result.passed = False
            result.reasons.append(f"市场板块 {ipo.market} 不在允许列表中")

    # 行业排除
    if ipo.industry and ipo.industry.lower() in [i.lower() for i in config.basic.exclude_industries]:
        result.passed = False
        result.reasons.append(f"行业 {ipo.industry} 在排除列表中")

    # 保荐人黑名单
    if ipo.sponsors and config.sponsor.blacklist:
        for s in ipo.sponsors:
            if s in config.sponsor.blacklist:
                result.passed = False
                result.reasons.append(f"保荐人 {s} 在黑名单中")

    return result
