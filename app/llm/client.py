"""LLM 客户端 — 统一接口。"""

from loguru import logger

from app.models import (
    IPOItem,
    AllotmentResult,
    GreyMarketQuote,
    StrategyDecision,
    LLMSummary,
)
from app.llm.providers.base import BaseLLMProvider
from app.llm.providers.mock_provider import MockLLMProvider
from app.llm.prompts import build_summary_prompt, build_daily_digest_prompt
from app.llm.schemas import validate_summary_json
from app.settings import LLMSettings


def create_llm_provider(settings: LLMSettings) -> BaseLLMProvider:
    """根据配置创建 LLM provider。"""
    if settings.provider == "mock":
        return MockLLMProvider()

    try:
        from app.llm.providers.openai_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(settings)
    except ImportError:
        logger.warning("openai package not installed, using mock provider")
        return MockLLMProvider()


class LLMService:
    """LLM 摘要服务。"""

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider

    def summarize_ipo_alert(
        self,
        ipo: IPOItem,
        decision: StrategyDecision,
        allotment: AllotmentResult | None = None,
        grey_quote: GreyMarketQuote | None = None,
    ) -> LLMSummary:
        """为 IPO 提醒生成摘要。"""
        payload = {
            "ipo": ipo.model_dump(mode="json"),
            "allotment": allotment.model_dump(mode="json") if allotment else None,
            "grey_market": grey_quote.model_dump(mode="json") if grey_quote else None,
            "strategy_decision": decision.model_dump(mode="json"),
        }

        messages = build_summary_prompt(payload)

        for attempt in range(2):
            try:
                raw_json = self.provider.generate(messages)
                if validate_summary_json(raw_json):
                    return LLMSummary(**raw_json, summary_source="llm")
                logger.warning(f"LLM output schema validation failed (attempt {attempt + 1})")
            except Exception as e:
                logger.warning(f"LLM generate failed (attempt {attempt + 1}): {e}")

        logger.warning("LLM failed, using fallback summary")
        return _fallback_summary(ipo, decision)

    def summarize_daily_digest(self, events: list[dict]) -> LLMSummary:
        """生成每日汇总摘要。"""
        messages = build_daily_digest_prompt(events)

        try:
            raw_json = self.provider.generate(messages)
            if validate_summary_json(raw_json):
                return LLMSummary(**raw_json, summary_source="llm")
        except Exception as e:
            logger.warning(f"LLM daily digest failed: {e}")

        return _fallback_daily_digest(events)


def _fallback_summary(ipo: IPOItem, decision: StrategyDecision) -> LLMSummary:
    """LLM 失败时的模板摘要。"""
    name = ipo.stock_name or ipo.stock_code
    level_names = {1: "普通", 2: "观察", 3: "重点", 4: "紧急"}
    level_str = level_names.get(decision.level, "未知")

    return LLMSummary(
        title=f"[规则摘要] {ipo.stock_code} {name}",
        summary=f"{name} 综合评分 {decision.score} 分，提醒等级 {level_str}。",
        key_points=[f"评分: {decision.score}/100", f"等级: {level_str}"],
        trigger_reasons=decision.trigger_reasons or ["无特定触发原因"],
        risks=decision.risk_flags or ["暂无风险标记"],
        suggested_action="请参考官方公告自行判断",
        confidence="low",
        summary_source="fallback",
    )


def _fallback_daily_digest(events: list[dict]) -> LLMSummary:
    """日报 fallback。"""
    return LLMSummary(
        title="[规则摘要] 每日港股打新汇总",
        summary=f"今日共 {len(events)} 条事件。",
        key_points=[f"事件数: {len(events)}"],
        trigger_reasons=[],
        risks=["以上为系统自动生成的规则摘要，LLM 摘要生成失败"],
        suggested_action="请查看详细数据",
        confidence="low",
        summary_source="fallback",
    )
