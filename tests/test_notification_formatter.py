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


def test_format_notification_with_llm_evaluation():
    from app.models import LLMEvaluation

    summary = _make_summary()
    decision = _make_decision()
    ipo = _make_ipo()
    llm_eval = LLMEvaluation(
        business_quality=8,
        financial_health=7,
        valuation_fairness=6,
        growth_prospect=9,
        risk_level="medium",
        risk_factors=["估值偏高"],
        comparable_companies=["公司A (01234.HK)"],
        recommended_action="subscribe",
        confidence="high",
        reasoning="AI赛道增长确定性强，已实现盈利",
    )

    title, body = format_notification(summary, decision, ipo, llm_eval=llm_eval)

    assert "AI 评估依据" in body
    assert "商业模式: 8/10" in body
    assert "增长前景: 9/10" in body
    assert "综合判断: AI赛道增长确定性强" in body
    assert "建议申购" in body
    assert "公司A (01234.HK)" in body
    assert "估值偏高" in body


def test_format_notification_without_llm_evaluation():
    summary = _make_summary()
    decision = _make_decision()
    ipo = _make_ipo()

    title, body = format_notification(summary, decision, ipo)

    assert "AI 评估依据" not in body
    assert "综合评分" in body


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
                "score_source": "ai_judge",
                "score_breakdown": [
                    "AI 评委分: 21/100",
                    "日报主评分采用 AI 评审体系",
                ],
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
    assert "AI 评委分: 21/100" in body
    assert "AI 评分依据:" in body
    assert "持续跟踪 (1 只)" in body
    assert "距离上市还有 7 天" in body
    assert "low-carbon products" in body
    assert "详细招股信息见 2026-05-26 日报" in body
    assert "不构成投资建议" in body


def test_format_daily_digest_active_evaluations_section():
    summary = _make_summary()
    active_evaluations = [
        {
            "stock_code": "03888",
            "rank": 1,
            "ai_score": 77,
            "company_overview": "公司提供工业软件和自动化解决方案。",
            "ipo": _make_ipo().model_dump(mode="json", exclude_none=True),
            "llm_evaluation": {
                "business_quality": 8,
                "business_quality_reason": "公司客户续约率 90%",
                "financial_health": 7,
                "financial_health_reason": "最近一年收入同比增长 20%",
                "valuation_fairness": 6,
                "valuation_fairness_reason": "招股估值接近同行中位数",
                "growth_prospect": 9,
                "growth_prospect_reason": "目标市场规模持续扩大",
                "risk_level": "medium",
                "recommended_action": "watch",
                "reasoning": "测试综合判断",
                "risk_factors": ["客户集中"],
            },
        }
    ]

    title, body = format_daily_digest(summary, [], [], active_evaluations)

    assert "AI 关注 Top 1" in body
    assert "1. 03888" in body
    assert "AI 评委分: 77/100" in body
    assert "公司概述: 公司提供工业软件和自动化解决方案。" in body
    assert "公司客户续约率 90%" in body
    assert "AI 建议: 建议观望" in body
    assert "测试综合判断" in body


def test_format_daily_digest_ai_reasons_fallback_when_missing():
    summary = _make_summary()
    active_evaluations = [
        {
            "stock_code": "03888",
            "rank": 1,
            "ai_score": 77,
            "company_overview": "公司提供工业软件和自动化解决方案。",
            "ipo": _make_ipo().model_dump(mode="json", exclude_none=True),
            "llm_evaluation": {
                "business_quality": 8,
                "business_quality_reason": "",
                "financial_health": 7,
                "financial_health_reason": "",
                "valuation_fairness": 6,
                "valuation_fairness_reason": "",
                "growth_prospect": 9,
                "growth_prospect_reason": "",
                "risk_level": "medium",
                "recommended_action": "watch",
            },
        }
    ]

    title, body = format_daily_digest(summary, [], [], active_evaluations)

    assert "商业模式: 8/10 — 当前缺少可验证的事实依据" in body
    assert "财务健康: 7/10 — 当前缺少可验证的事实依据" in body


def test_format_daily_digest_pending_ai_review_section():
    summary = _make_summary()
    pending = [
        {
            "stock_code": "01081",
            "company_overview": "暂无官方章程主营摘要；需等待招股书解析或人工补充。",
            "ipo": {
                "stock_code": "01081",
                "stock_name": "大金重工",
                "status": "subscription_open",
                "subscription_close_date": "2026-06-05",
                "entry_fee_hkd": 3030.3,
            },
            "unknown_fields": ["公司主营业务", "行业", "上市日"],
            "ai_review_note": "LLM 评审失败，当前仅有 fallback 结果；不作为 AI 评委分。",
            "top_exclusion_reasons": ["关键字段 unknown: 公司主营业务、上市日"],
        }
    ]

    title, body = format_daily_digest(summary, [], [], [], pending)

    assert "AI 评审待补充 / 未入榜 (1 只)" in body
    assert "01081 大金重工" in body
    assert "Unknown: 公司主营业务、行业、上市日" in body
    assert "未入榜原因: 关键字段 unknown" in body
    assert "LLM 评审失败" in body


def test_format_daily_digest_version_update_plugin():
    summary = _make_summary()

    title, body = format_daily_digest(
        summary,
        [],
        [],
        [],
        [],
        {
            "enabled": True,
            "version": "score-ai-review-v1.0",
            "date": "2026-06-04",
            "title": "评分版本更新说明",
            "highlights": ["AI 评委分由四个 1-10 分维度换算为 0-100 分。"],
            "details": ["商业模式×3.0 + 财务健康×2.5 + 定价合理×2.5 + 增长前景×2.0。"],
        },
    )

    assert "评分版本更新说明 | score-ai-review-v1.0 | 2026-06-04" in body
    assert "AI 评委分由四个 1-10 分维度换算为 0-100 分。" in body
    assert "商业模式×3.0 + 财务健康×2.5" in body


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
