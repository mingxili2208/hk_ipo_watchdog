"""通知格式化测试。"""

from datetime import datetime, date

from app.models import IPOItem, StrategyDecision, LLMSummary
from app.notifier.formatter import append_daily_llm_usage, format_notification, format_daily_digest


def _make_ipo() -> IPOItem:
    return IPOItem(
        stock_code="03888",
        stock_name="测试公司",
        market="Main Board",
        status="subscription_open",
        entry_fee_hkd=2848.44,
        subscription_close_date=date(2026, 5, 26),
        listing_date=date(2026, 5, 29),
        sponsors=["CICC"],
    )


def _make_decision() -> StrategyDecision:
    return StrategyDecision(
        stock_code="03888",
        passed=True,
        score=82,
        level=3,
        matched_rules=["low_entry_fee", "hot_subscription"],
        trigger_reasons=["入场费低于策略阈值", "公开发售热度较高"],
        risk_flags=["缺少暗盘数据"],
        should_notify=True,
        notification_type="new_ipo",
        notification_key="03888:new_ipo:2026-05-25",
        evaluated_at=datetime.now(),
    )


def _make_summary() -> LLMSummary:
    return LLMSummary(
        title="新股打新提醒：03888 测试公司",
        summary="该新股入场费较低，当前符合观察条件。",
        key_points=["入场费 HKD 2,848", "综合评分 82"],
        trigger_reasons=["入场费低于策略阈值"],
        risks=["暗盘数据尚未公布"],
        suggested_action="等待配发结果",
        confidence="medium",
    )


def test_format_notification():
    ipo = _make_ipo()
    decision = _make_decision()
    summary = _make_summary()

    title, body = format_notification(summary, decision, ipo)

    assert "03888" in title
    assert "测试公司" in body
    assert "82" in body
    assert "重点提醒" in body
    assert "入场费" in body
    assert "不构成投资建议" in body


def test_format_notification_fallback():
    summary = LLMSummary(
        title="[规则摘要] 03888 测试",
        summary="fallback",
        key_points=[],
        trigger_reasons=[],
        risks=[],
        suggested_action="none",
        confidence="low",
        summary_source="fallback",
    )
    decision = _make_decision()
    title, body = format_notification(summary, decision)

    assert "规则摘要" in body
    assert "AI 摘要生成失败" in body


def test_format_daily_digest():
    summary = _make_summary()
    events = [
        {"stock_code": "03888", "event_type": "new_ipo", "title": "发现新 IPO"},
    ]

    title, body = format_daily_digest(summary, events)

    assert "1 条" in body
    assert "03888" in body
    assert "不构成投资建议" in body


def test_append_daily_llm_usage():
    body = append_daily_llm_usage(
        "提醒正文",
        {
            "date": "2026-05-26",
            "calls": 2,
            "prompt_tokens": 1234,
            "completion_tokens": 56,
            "cached_tokens": 100,
            "total_tokens": 1290,
        },
    )

    assert "香港时间 2026-05-26" in body
    assert "输入 Token: 1,234" in body
    assert "总 Token: 1,290" in body
