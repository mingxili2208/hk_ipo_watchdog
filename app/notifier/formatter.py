"""通知内容格式化。"""

from app.models import IPOItem, StrategyDecision, LLMSummary, LLMEvaluation


_LEVEL_NAMES = {1: "普通记录", 2: "观察提醒", 3: "重点提醒", 4: "紧急提醒"}

_RISK_LEVEL_NAMES = {
    "low": "低风险",
    "medium": "中等风险",
    "high": "高风险",
    "very_high": "极高风险",
}

_ACTION_NAMES = {
    "subscribe": "建议申购",
    "skip": "建议放弃",
    "watch": "建议观望",
}

_STATUS_NAMES = {
    "unknown": "未知",
    "planned": "计划中",
    "hearing_passed": "聆讯通过",
    "subscription_open": "招股中",
    "subscription_closed": "已截止认购",
    "allotment_result_published": "配发结果已公布",
    "grey_market_trading": "暗盘交易中",
    "listed": "已上市",
    "archived": "已归档",
}


def format_notification(
    summary: LLMSummary,
    decision: StrategyDecision,
    ipo: IPOItem | None = None,
    llm_eval: LLMEvaluation | None = None,
) -> tuple[str, str]:
    """格式化推送内容，返回 (title, body)。"""
    title = summary.title

    lines = []

    if ipo:
        lines.append(f"股票: {ipo.stock_code} {ipo.stock_name or ''}")
        if ipo.market:
            lines.append(f"板块: {ipo.market}")

    status_map = {
        "unknown": "未知",
        "planned": "计划中",
        "hearing_passed": "聆讯通过",
        "subscription_open": "招股中",
        "subscription_closed": "已截止认购",
        "allotment_result_published": "配发结果已公布",
        "grey_market_trading": "暗盘交易中",
        "listed": "已上市",
        "archived": "已归档",
    }

    if ipo and ipo.status:
        lines.append(f"状态: {status_map.get(ipo.status, ipo.status)}")

    if ipo and ipo.business_overview:
        lines.append(f"主营业务 (官方章程摘要): {ipo.business_overview}")

    if ipo and ipo.entry_fee_hkd:
        lines.append(f"入场费: HKD {ipo.entry_fee_hkd:,.2f}")

    if ipo and ipo.subscription_close_date:
        lines.append(f"截止认购: {ipo.subscription_close_date}")

    if ipo and ipo.listing_date:
        lines.append(f"上市日期: {ipo.listing_date}")

    lines.append(f"综合评分: {decision.score} / 100")
    lines.append(f"提醒等级: {_LEVEL_NAMES.get(decision.level, '未知')}")

    # ── LLM 评估依据 ──
    if llm_eval:
        lines.append("")
        lines.append("AI 评估依据:")
        dims = [
            ("商业模式", llm_eval.business_quality, llm_eval.business_quality_reason),
            ("财务健康", llm_eval.financial_health, llm_eval.financial_health_reason),
            ("定价合理", llm_eval.valuation_fairness, llm_eval.valuation_fairness_reason),
            ("增长前景", llm_eval.growth_prospect, llm_eval.growth_prospect_reason),
        ]
        for name, score, reason in dims:
            lines.append(f"  {name}: {score}/10 — {_reason_text(reason)}")
        lines.append(
            f"  风险等级: {_RISK_LEVEL_NAMES.get(llm_eval.risk_level, llm_eval.risk_level)}"
        )
        if llm_eval.recommended_action:
            action_name = _ACTION_NAMES.get(
                llm_eval.recommended_action, llm_eval.recommended_action
            )
            lines.append(f"  AI 建议: {action_name}")
        if llm_eval.reasoning:
            lines.append(f"  综合判断: {llm_eval.reasoning}")
        if llm_eval.comparable_companies:
            lines.append(f"  可比公司: {'、'.join(llm_eval.comparable_companies)}")
        if llm_eval.risk_factors:
            lines.append(f"  风险因素: {'；'.join(llm_eval.risk_factors)}")
        lines.append(f"  (评估来源: {llm_eval.evaluation_source}，置信度: {llm_eval.confidence})")

    lines.append("")
    lines.append(summary.summary)

    if summary.key_points:
        lines.append("")
        lines.append("关键信息:")
        for p in summary.key_points:
            lines.append(f"  - {p}")

    if decision.trigger_reasons:
        lines.append("")
        lines.append("触发原因:")
        for r in decision.trigger_reasons:
            lines.append(f"  - {r}")

    if summary.risks or decision.risk_flags:
        lines.append("")
        lines.append("风险提示:")
        for r in (summary.risks or decision.risk_flags):
            lines.append(f"  - {r}")

    if summary.suggested_action:
        lines.append("")
        lines.append(f"建议: {summary.suggested_action}")

    lines.append("")
    lines.append("说明: 本提醒仅用于信息整理，不构成投资建议。")

    if summary.summary_source == "fallback":
        lines.append("注意: AI 摘要生成失败，以上为规则摘要。")

    body = "\n".join(lines)
    return title, body


def format_daily_digest(
    summary: LLMSummary,
    events: list[dict],
    follow_ups: list[dict] | None = None,
    active_evaluations: list[dict] | None = None,
    pending_evaluations: list[dict] | None = None,
    version_update: dict | None = None,
) -> tuple[str, str]:
    """格式化每日汇总。"""
    title = summary.title

    lines = [summary.summary, ""]

    if version_update and version_update.get("enabled"):
        lines.extend(_format_version_update(version_update))
        lines.append("")

    if events:
        lines.append(f"今日事件 ({len(events)} 条):")
        for ev in events[:20]:
            code = ev.get("stock_code", "")
            etype = ev.get("event_type", "")
            ev_title = ev.get("title", "")
            lines.append(f"  - [{etype}] {code} {ev_title}")
            ipo = ev.get("ipo") or {}
            if ipo:
                status_map = {
                    "subscription_open": "招股中",
                    "subscription_closed": "已截止认购",
                    "allotment_result_published": "配发结果已公布",
                    "listed": "已上市",
                }
                schedule = []
                if ipo.get("subscription_start_date") or ipo.get("subscription_close_date"):
                    schedule.append(
                        f"招股: {ipo.get('subscription_start_date', '-')} 至 "
                        f"{ipo.get('subscription_close_date', '-')}"
                    )
                if ipo.get("listing_date"):
                    schedule.append(f"上市: {ipo['listing_date']}")
                if schedule:
                    lines.append(f"      {' | '.join(schedule)}")

                terms = []
                price_min = ipo.get("offer_price_min")
                price_max = ipo.get("offer_price_max")
                if price_min is not None and price_max is not None:
                    price = (
                        f"HKD {price_min:,.2f}"
                        if price_min == price_max
                        else f"HKD {price_min:,.2f}-{price_max:,.2f}"
                    )
                    terms.append(f"发售价: {price}")
                if ipo.get("lot_size") is not None:
                    terms.append(f"每手: {ipo['lot_size']:,} 股")
                if ipo.get("entry_fee_hkd") is not None:
                    terms.append(f"入场费: HKD {ipo['entry_fee_hkd']:,.2f}")
                if terms:
                    lines.append(f"      {' | '.join(terms)}")

                metadata = []
                if ipo.get("industry"):
                    metadata.append(f"行业: {ipo['industry']}")
                status = status_map.get(ipo.get("status"), ipo.get("status"))
                if status:
                    metadata.append(f"状态: {status}")
                if metadata:
                    lines.append(f"      {' | '.join(metadata)}")
                if ipo.get("business_overview"):
                    lines.append(f"      主营业务 (官方章程摘要): {ipo['business_overview']}")

            score = ev.get("strategy_score") or {}
            if score:
                score_value = score.get("score")
                level_value = score.get("level")
                level_name = _LEVEL_NAMES.get(level_value, "未知")
                score_line = f"AI 评委分: {score_value}/100 | 等级: {level_name}"
                lines.append(f"      {score_line}")
                if score.get("score_breakdown"):
                    lines.append("      AI 评分依据:")
                    for reason in score["score_breakdown"]:
                        lines.append(f"        - {reason}")

            # ── LLM 评估依据 ──
            llm_eval = ev.get("llm_evaluation") or {}
            if llm_eval and llm_eval.get("evaluation_source") != "fallback":
                lines.append("      AI 评估依据:")
                dims = [
                    ("商业模式", llm_eval.get("business_quality"), llm_eval.get("business_quality_reason")),
                    ("财务健康", llm_eval.get("financial_health"), llm_eval.get("financial_health_reason")),
                    ("定价合理", llm_eval.get("valuation_fairness"), llm_eval.get("valuation_fairness_reason")),
                    ("增长前景", llm_eval.get("growth_prospect"), llm_eval.get("growth_prospect_reason")),
                ]
                for name, sc, reason in dims:
                    if sc is not None:
                        lines.append(f"        {name}: {sc}/10 — {_reason_text(reason)}")
                if llm_eval.get("risk_level"):
                    lines.append(f"        风险等级: {_RISK_LEVEL_NAMES.get(llm_eval['risk_level'], llm_eval['risk_level'])}")
                if llm_eval.get("recommended_action"):
                    action = _ACTION_NAMES.get(llm_eval["recommended_action"], llm_eval["recommended_action"])
                    lines.append(f"        AI 建议: {action}")
                if llm_eval.get("reasoning"):
                    lines.append(f"        综合判断: {llm_eval['reasoning']}")
                if llm_eval.get("comparable_companies"):
                    lines.append(f"        可比公司: {'、'.join(llm_eval['comparable_companies'])}")
                if llm_eval.get("risk_factors"):
                    lines.append(f"        风险因素: {'；'.join(llm_eval['risk_factors'])}")

    if follow_ups:
        lines.append("")
        lines.append(f"持续跟踪 ({len(follow_ups)} 只):")
        for item in follow_ups:
            ipo = item.get("ipo") or {}
            code = item.get("stock_code", "")
            name = ipo.get("stock_name", "")
            days = item.get("days_to_listing")
            listing_date = ipo.get("listing_date", "-")
            if days == 0:
                countdown = "今日上市"
            else:
                countdown = f"距离上市还有 {days} 天"
            lines.append(f"  - {code} {name}: {countdown} (上市日: {listing_date})")
            if item.get("ai_score") is not None:
                lines.append(f"      AI 评委分: {item['ai_score']}/100")
            overview = item.get("company_overview") or ipo.get("business_overview")
            if overview:
                lines.append(f"      公司概述: {overview}")
            llm_eval = item.get("llm_evaluation") or {}
            if llm_eval.get("recommended_action"):
                action = _ACTION_NAMES.get(llm_eval["recommended_action"], llm_eval["recommended_action"])
                lines.append(f"      AI 建议: {action}")
            if item.get("detail_digest_date"):
                lines.append(f"      详细招股信息见 {item['detail_digest_date']} 日报")
            else:
                lines.append(f"      首次发现于 {item.get('discovered_on', '-')}，未确认存在已送达的详情日报")

    if active_evaluations:
        lines.append("")
        lines.append(f"AI 关注 Top {len(active_evaluations)}:")
        for item in active_evaluations:
            ipo = item.get("ipo") or {}
            code = item.get("stock_code", "")
            name = ipo.get("stock_name", "")
            rank = item.get("rank", "-")
            score = item.get("ai_score")
            status = _STATUS_NAMES.get(ipo.get("status"), ipo.get("status", "-"))
            listing_date = ipo.get("listing_date", "-")
            score_text = f"{score}/100" if score is not None else "暂无"
            lines.append(f"  {rank}. {code} {name} | AI 评委分: {score_text}")
            lines.append(f"      状态: {status} | 上市日: {listing_date}")
            if ipo.get("industry"):
                lines.append(f"      行业: {ipo['industry']}")
            overview = item.get("company_overview")
            if overview:
                lines.append(f"      公司概述: {overview}")
            if ipo.get("subscription_close_date"):
                lines.append(f"      截止认购: {ipo['subscription_close_date']}")
            if ipo.get("entry_fee_hkd") is not None:
                lines.append(f"      入场费: HKD {ipo['entry_fee_hkd']:,.2f}")

            llm_eval = item.get("llm_evaluation") or {}
            if llm_eval:
                if llm_eval.get("recommended_action"):
                    action = _ACTION_NAMES.get(llm_eval["recommended_action"], llm_eval["recommended_action"])
                    lines.append(f"      AI 建议: {action}")
                lines.append("      入榜理由:")
                dims = [
                    ("商业模式", llm_eval.get("business_quality"), llm_eval.get("business_quality_reason")),
                    ("财务健康", llm_eval.get("financial_health"), llm_eval.get("financial_health_reason")),
                    ("定价合理", llm_eval.get("valuation_fairness"), llm_eval.get("valuation_fairness_reason")),
                    ("增长前景", llm_eval.get("growth_prospect"), llm_eval.get("growth_prospect_reason")),
                ]
                for name, sc, reason in dims:
                    if sc is not None:
                        lines.append(f"        {name}: {sc}/10 — {_reason_text(reason)}")
                if llm_eval.get("risk_level"):
                    lines.append(f"        风险等级: {_RISK_LEVEL_NAMES.get(llm_eval['risk_level'], llm_eval['risk_level'])}")
                if llm_eval.get("reasoning"):
                    lines.append(f"        综合判断: {llm_eval['reasoning']}")
                if llm_eval.get("risk_factors"):
                    lines.append(f"        风险因素: {'；'.join(llm_eval['risk_factors'])}")

    if pending_evaluations:
        lines.append("")
        lines.append(f"AI 评审待补充 / 未入榜 ({len(pending_evaluations)} 只):")
        for item in pending_evaluations:
            ipo = item.get("ipo") or {}
            code = item.get("stock_code", "")
            name = ipo.get("stock_name", "")
            status = _STATUS_NAMES.get(ipo.get("status"), ipo.get("status", "-"))
            listing_date = ipo.get("listing_date", "-")
            lines.append(f"  - {code} {name}: 状态 {status} | 上市日: {listing_date}")
            overview = item.get("company_overview")
            if overview:
                lines.append(f"      已知概述: {overview}")
            known = []
            if ipo.get("industry"):
                known.append(f"行业: {ipo['industry']}")
            if ipo.get("subscription_close_date"):
                known.append(f"截止认购: {ipo['subscription_close_date']}")
            if ipo.get("entry_fee_hkd") is not None:
                known.append(f"入场费: HKD {ipo['entry_fee_hkd']:,.2f}")
            if known:
                lines.append(f"      已知信息: {' | '.join(known)}")
            unknown = item.get("unknown_fields") or []
            if unknown:
                lines.append(f"      Unknown: {'、'.join(unknown)}")
            exclusions = item.get("top_exclusion_reasons") or []
            if exclusions:
                lines.append(f"      未入榜原因: {'；'.join(exclusions)}")
            note = item.get("ai_review_note")
            if note:
                lines.append(f"      AI 状态: {note}")

    if summary.key_points:
        lines.append("")
        lines.append("要点:")
        for p in summary.key_points:
            lines.append(f"  - {p}")

    if summary.risks:
        lines.append("")
        lines.append("风险:")
        for r in summary.risks:
            lines.append(f"  - {r}")

    lines.append("")
    lines.append("说明: 本汇总仅用于信息整理，不构成投资建议。")

    body = "\n".join(lines)
    return title, body


def append_daily_llm_usage(body: str, usage: dict) -> str:
    """为邮件正文追加当日 LLM token 汇总。"""
    lines = [
        body,
        "",
        f"今日 LLM Token 用量 (香港时间 {usage['date']}):",
        f"  调用次数: {usage['calls']:,}",
        f"  输入 Token: {usage['prompt_tokens']:,}",
        f"  输出 Token: {usage['completion_tokens']:,}",
        f"  缓存命中 Token: {usage['cached_tokens']:,}",
        f"  总 Token: {usage['total_tokens']:,}",
    ]
    return "\n".join(lines)


def _format_version_update(update: dict) -> list[str]:
    title = update.get("title") or "版本更新说明"
    version = update.get("version")
    date = update.get("date")
    header_parts = [title]
    if version:
        header_parts.append(str(version))
    if date:
        header_parts.append(str(date))

    lines = [" | ".join(header_parts)]
    highlights = update.get("highlights") or []
    if highlights:
        lines.append("本次更新:")
        for item in highlights:
            lines.append(f"  - {item}")
    details = update.get("details") or []
    if details:
        lines.append("实现说明:")
        for item in details:
            lines.append(f"  - {item}")
    return lines


def _reason_text(reason: str | None) -> str:
    if reason and str(reason).strip():
        return str(reason).strip()
    return "当前缺少可验证的事实依据，需补充招股书或人工复核。"
