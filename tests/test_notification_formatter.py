"""通知格式化测试。"""

from datetime import datetime, date

from app.models import IPOItem, StrategyDecision, LLMSummary
from app.notifier.formatter import append_daily_llm_usage, format_notification, format_daily_digest


def _make_ipo() -> IPOItem:
    return IPOItem(
        stock_code="03888",
        stock_name="测试公司",
        market="Main Board",
        business_overview="We provide consumer 3D printing products and services.",
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
    assert "主营业务 (官方章程摘要)" in body
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
        {
            "stock_code": "03888",
            "event_type": "new_ipo",
            "title": "发现新 IPO",
            "ipo": _make_ipo().model_dump(mode="json", exclude_none=True),
            "strategy_score": {
                "score": 21,
                "level": 1,
                "push_score_threshold": 60,
                "score_breakdown": [
                    "基础信息: +21 (入场费不高于 HKD 5,000；行业未列入排除清单)",
                    "认购热度: +0 (缺少配发结果数据)",
                ],
                "risk_flags": ["缺少配发结果数据", "缺少暗盘数据"],
            },
        },
    ]

    follow_ups = [
        {
            "stock_code": "02553",
            "ipo": {
                "stock_name": "测试跟踪",
                "listing_date": "2026-06-03",
                "business_overview": "We supply low-carbon products and solutions.",
            },
            "days_to_listing": 7,
            "discovered_on": "2026-05-26",
            "detail_digest_date": "2026-05-26",
        }
    ]

    title, body = format_daily_digest(summary, events, follow_ups)

    assert "1 条" in body
    assert "03888" in body
    assert "招股: - 至 2026-05-26" in body
    assert "上市: 2026-05-29" in body
    assert "入场费: HKD 2,848.44" in body
    assert "主营业务 (官方章程摘要)" in body
    assert "consumer 3D printing" in body
    assert "评分: 21/100" in body
    assert "未达到普通推送线 60" in body
    assert "评分依据:" in body
    assert "缺少暗盘数据" in body
    assert "持续跟踪 (1 只)" in body
    assert "距离上市还有 7 天" in body
    assert "low-carbon products" in body
    assert "详细招股信息见 2026-05-26 日报" in body
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
