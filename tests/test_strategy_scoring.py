"""策略评分单元测试。"""

from datetime import date, datetime, timedelta

from app.models import IPOItem, AllotmentResult, GreyMarketQuote
from app.strategy.config_loader import StrategyConfig
from app.strategy.scoring import calculate_score, decide_alert_level, collect_matched_rules, collect_trigger_reasons, collect_risk_flags
from app.strategy.filters import apply_hard_filters
from app.strategy.rule_engine import evaluate_ipo
from app.utils.time_utils import today_hk


def _make_ipo(**kwargs) -> IPOItem:
    defaults = {
        "stock_code": "02616",
        "stock_name": "测试股票",
        "market": "Main Board",
        "industry": "technology",
        "status": "subscription_open",
        "entry_fee_hkd": 3000.0,
        "lot_size": 1000,
        "sponsors": ["CICC"],
    }
    defaults.update(kwargs)
    return IPOItem(**defaults)


def _make_allotment(**kwargs) -> AllotmentResult:
    defaults = {
        "stock_code": "02616",
        "public_subscription_times": 25.0,
        "one_lot_success_rate": 15.0,
        "final_offer_price": 3.0,
    }
    defaults.update(kwargs)
    return AllotmentResult(**defaults)


def _make_grey(**kwargs) -> GreyMarketQuote:
    defaults = {
        "stock_code": "02616",
        "source": "test",
        "grey_price": 3.5,
        "offer_price": 3.0,
        "change_percent": 16.7,
        "quoted_at": datetime.now(),
    }
    defaults.update(kwargs)
    return GreyMarketQuote(**defaults)


class TestCalculateScore:
    def test_high_score(self):
        ipo = _make_ipo()
        allotment = _make_allotment(public_subscription_times=50)
        grey = _make_grey(change_percent=15)
        config = StrategyConfig()
        score = calculate_score(ipo, config, allotment, grey)
        assert score >= 60

    def test_low_score(self):
        ipo = _make_ipo(industry="property", market="GEM", entry_fee_hkd=25000)
        config = StrategyConfig()
        score = calculate_score(ipo, config)
        assert score < 50

    def test_no_allotment(self):
        ipo = _make_ipo()
        config = StrategyConfig()
        score = calculate_score(ipo, config)
        assert score >= 0

    def test_score_bounded(self):
        ipo = _make_ipo()
        config = StrategyConfig()
        score = calculate_score(ipo, config)
        assert 0 <= score <= 100


class TestDecideAlertLevel:
    def test_urgent(self):
        config = StrategyConfig()
        assert decide_alert_level(90, config) == 4

    def test_important(self):
        config = StrategyConfig()
        assert decide_alert_level(80, config) == 3

    def test_watch(self):
        config = StrategyConfig()
        assert decide_alert_level(65, config) == 2

    def test_normal(self):
        config = StrategyConfig()
        assert decide_alert_level(40, config) == 1


class TestHardFilters:
    def test_pass(self):
        ipo = _make_ipo()
        config = StrategyConfig()
        result = apply_hard_filters(ipo, config)
        assert result.passed

    def test_fail_entry_fee(self):
        ipo = _make_ipo(entry_fee_hkd=50000)
        config = StrategyConfig()
        result = apply_hard_filters(ipo, config)
        assert not result.passed

    def test_fail_industry(self):
        ipo = _make_ipo(industry="property")
        config = StrategyConfig()
        result = apply_hard_filters(ipo, config)
        assert not result.passed

    def test_fail_market(self):
        ipo = _make_ipo(market="GEM")
        config = StrategyConfig()
        result = apply_hard_filters(ipo, config)
        assert not result.passed


class TestEvaluateIPO:
    def test_full_evaluation(self):
        ipo = _make_ipo()
        allotment = _make_allotment()
        grey = _make_grey()
        config = StrategyConfig()

        decision = evaluate_ipo(ipo, config, allotment, grey)
        assert decision.stock_code == "02616"
        assert 0 <= decision.score <= 100
        assert 1 <= decision.level <= 4
        assert decision.evaluated_at is not None

    def test_should_notify_high_score(self):
        ipo = _make_ipo()
        allotment = _make_allotment(public_subscription_times=100)
        config = StrategyConfig()
        decision = evaluate_ipo(ipo, config, allotment)
        assert decision.passed

    def test_subscription_deadline_precedes_new_ipo(self):
        ipo = _make_ipo(subscription_close_date=today_hk() + timedelta(days=1))
        config = StrategyConfig(alerts={"watch_score_above": 0, "only_push_score_above": 0})

        decision = evaluate_ipo(ipo, config)

        assert decision.notification_type == "subscription_deadline"
        assert str(ipo.subscription_close_date) in decision.notification_key

    def test_new_ipo_notification_key_is_stable_across_scans(self):
        ipo = _make_ipo(subscription_start_date=date(2026, 5, 20))
        config = StrategyConfig(alerts={"watch_score_above": 0, "only_push_score_above": 0})

        decision = evaluate_ipo(ipo, config)

        assert decision.notification_key == "02616:new_ipo:2026-05-20"
