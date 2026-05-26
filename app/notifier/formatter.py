"""通知内容格式化。"""

from app.models import IPOItem, StrategyDecision, LLMSummary


_LEVEL_NAMES = {1: "普通记录", 2: "观察提醒", 3: "重点提醒", 4: "紧急提醒"}


def format_notification(
    summary: LLMSummary,
    decision: StrategyDecision,
    ipo: IPOItem | None = None,
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

    if ipo and ipo.entry_fee_hkd:
        lines.append(f"入场费: HKD {ipo.entry_fee_hkd:,.2f}")

    if ipo and ipo.subscription_close_date:
        lines.append(f"截止认购: {ipo.subscription_close_date}")

    if ipo and ipo.listing_date:
        lines.append(f"上市日期: {ipo.listing_date}")

    lines.append(f"综合评分: {decision.score} / 100")
    lines.append(f"提醒等级: {_LEVEL_NAMES.get(decision.level, '未知')}")

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
) -> tuple[str, str]:
    """格式化每日汇总。"""
    title = summary.title

    lines = [summary.summary, ""]

    if events:
        lines.append(f"今日事件 ({len(events)} 条):")
        for ev in events[:20]:
            code = ev.get("stock_code", "")
            etype = ev.get("event_type", "")
            ev_title = ev.get("title", "")
            lines.append(f"  - [{etype}] {code} {ev_title}")

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
