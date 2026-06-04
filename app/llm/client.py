"""LLM 客户端 — 统一接口。"""

from collections.abc import Callable

from loguru import logger

from app.models import (
    IPOItem,
    AllotmentResult,
    GreyMarketQuote,
    StrategyDecision,
    LLMSummary,
    LLMEvaluation,
    ProspectusFinancials,
    SponsorStats,
    MarketHeat,
)
from app.llm.providers.base import BaseLLMProvider
from app.llm.providers.mock_provider import MockLLMProvider
from app.llm.prompts import (
    build_summary_prompt,
    build_daily_digest_prompt,
    build_evaluation_prompt,
    build_financial_extraction_prompt,
    build_enriched_evaluation_prompt,
)
from app.llm.schemas import (
    summary_validation_errors,
    validate_summary_json,
    evaluation_validation_errors,
    validate_evaluation_json,
    financial_validation_errors,
    validate_financial_json,
)
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

    def __init__(
        self,
        provider: BaseLLMProvider,
        usage_recorder: Callable[[str, dict], int] | None = None,
    ):
        self.provider = provider
        self.usage_recorder = usage_recorder

    def _generate(self, messages: list[dict], purpose: str) -> dict:
        """调用 provider，并持久化实际返回的 token 用量。"""
        try:
            return self.provider.generate(messages)
        finally:
            usage = self.provider.consume_usage()
            if usage and self.usage_recorder:
                try:
                    self.usage_recorder(purpose, usage)
                except Exception as e:
                    logger.warning(f"Failed to record LLM token usage: {e}")

    def summarize_ipo_alert(
        self,
        ipo: IPOItem,
        decision: StrategyDecision,
        allotment: AllotmentResult | None = None,
        grey_quote: GreyMarketQuote | None = None,
        purpose: str = "ipo_alert",
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
                raw_json = self._generate(messages, purpose)
                if validate_summary_json(raw_json):
                    return LLMSummary(**raw_json, summary_source="llm")
                errors = "; ".join(summary_validation_errors(raw_json))
                logger.warning(
                    f"LLM output schema validation failed (attempt {attempt + 1}): {errors}"
                )
            except Exception as e:
                logger.warning(f"LLM generate failed (attempt {attempt + 1}): {e}")

        logger.warning("LLM failed, using fallback summary")
        return _fallback_summary(ipo, decision)

    def summarize_daily_digest(self, events: list[dict]) -> LLMSummary:
        """生成每日汇总摘要。"""
        messages = build_daily_digest_prompt(events)

        try:
            raw_json = self._generate(messages, "daily_digest")
            if validate_summary_json(raw_json):
                return LLMSummary(**raw_json, summary_source="llm")
        except Exception as e:
            logger.warning(f"LLM daily digest failed: {e}")

        return _fallback_daily_digest(events)

    def evaluate_ipo(
        self,
        ipo: IPOItem,
        purpose: str = "ipo_evaluation",
    ) -> LLMEvaluation:
        """对 IPO 进行结构化评估（申购推荐阶段使用）。

        输入包含招股书摘要、行业、招股价、入场费、基石投资者等
        在招股开始时就可获取的信息。
        """
        messages = build_evaluation_prompt(ipo.model_dump(mode="json"))

        for attempt in range(2):
            try:
                raw_json = self._generate(messages, purpose)
                if validate_evaluation_json(raw_json):
                    return LLMEvaluation(
                        **_normalize_evaluation_json(raw_json),
                        evaluation_source="llm",
                    )
                errors = "; ".join(evaluation_validation_errors(raw_json))
                logger.warning(
                    f"LLM evaluation schema validation failed "
                    f"(attempt {attempt + 1}): {errors}"
                )
            except Exception as e:
                logger.warning(
                    f"LLM evaluation failed (attempt {attempt + 1}): {e}"
                )

        logger.warning("LLM evaluation failed, using fallback")
        return _fallback_evaluation(ipo)

    def extract_financials(
        self,
        prospectus_text: str,
        purpose: str = "financial_extraction",
    ) -> ProspectusFinancials:
        """从招股书中提取结构化财务数据。"""
        messages = build_financial_extraction_prompt(prospectus_text)

        for attempt in range(2):
            try:
                raw_json = self._generate(messages, purpose)
                if validate_financial_json(raw_json):
                    return ProspectusFinancials(
                        **raw_json, extraction_source="llm"
                    )
                errors = "; ".join(financial_validation_errors(raw_json))
                logger.warning(
                    f"LLM financial extraction validation failed "
                    f"(attempt {attempt + 1}): {errors}"
                )
            except Exception as e:
                logger.warning(
                    f"LLM financial extraction failed "
                    f"(attempt {attempt + 1}): {e}"
                )

        logger.warning("LLM financial extraction failed, using empty fallback")
        return ProspectusFinancials(extraction_source="fallback")

    def evaluate_ipo_enriched(
        self,
        ipo: IPOItem,
        financials: ProspectusFinancials | None = None,
        sponsor_stats: SponsorStats | None = None,
        market_heat: MarketHeat | None = None,
        purpose: str = "ipo_evaluation",
    ) -> LLMEvaluation:
        """带额外上下文的 IPO 评估。

        在基础评估之上追加招股书财务数据、保荐人历史表现、
        近期 IPO 市场热度等信息，提供给 LLM 做更精准的评估。
        """
        fin_dict = financials.model_dump(mode="json") if financials else None
        sp_dict = sponsor_stats.model_dump(mode="json") if sponsor_stats else None
        mh_dict = market_heat.model_dump(mode="json") if market_heat else None

        # 如果没有任何额外上下文，退化为普通评估
        if not fin_dict and not sp_dict and not mh_dict:
            return self.evaluate_ipo(ipo, purpose)

        messages = build_enriched_evaluation_prompt(
            ipo.model_dump(mode="json"),
            financials=fin_dict,
            sponsor_stats=sp_dict,
            market_heat=mh_dict,
        )

        for attempt in range(2):
            try:
                raw_json = self._generate(messages, purpose)
                if validate_evaluation_json(raw_json):
                    return LLMEvaluation(
                        **_normalize_evaluation_json(raw_json),
                        evaluation_source="llm",
                    )
                errors = "; ".join(evaluation_validation_errors(raw_json))
                logger.warning(
                    f"LLM enriched evaluation validation failed "
                    f"(attempt {attempt + 1}): {errors}"
                )
            except Exception as e:
                logger.warning(
                    f"LLM enriched evaluation failed "
                    f"(attempt {attempt + 1}): {e}"
                )

        logger.warning("LLM enriched evaluation failed, using fallback")
        return _fallback_evaluation(ipo)


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


def _normalize_evaluation_json(data: dict) -> dict:
    """宽容补齐可展示字段，避免格式小缺口吞掉整段 AI 判断。"""
    normalized = dict(data)
    for field in (
        "business_quality_reason",
        "financial_health_reason",
        "valuation_fairness_reason",
        "growth_prospect_reason",
    ):
        if not str(normalized.get(field) or "").strip():
            normalized[field] = "当前缺少可验证的事实依据，需补充招股书或人工复核。"
    normalized.setdefault("risk_factors", [])
    normalized.setdefault("comparable_companies", [])
    normalized.setdefault("reasoning", "AI 已返回评分，但部分解释字段缺失，建议人工复核。")
    normalized.setdefault("confidence", "low")
    if any("当前缺少可验证" in str(normalized.get(field, "")) for field in (
        "business_quality_reason",
        "financial_health_reason",
        "valuation_fairness_reason",
        "growth_prospect_reason",
    )):
        normalized["confidence"] = "low"
    return normalized


def _fallback_evaluation(ipo: IPOItem) -> LLMEvaluation:
    """LLM 评估失败时的保守 fallback。"""
    risk_factors = []
    if not ipo.business_overview:
        risk_factors.append("缺少主营业务信息")
    if not ipo.entry_fee_hkd:
        risk_factors.append("缺少入场费数据")
    if not ipo.sponsors:
        risk_factors.append("缺少保荐人信息")

    return LLMEvaluation(
        business_quality=5,
        business_quality_reason="LLM 评估不可用，缺少可验证的商业模式事实依据",
        financial_health=5,
        financial_health_reason="LLM 评估不可用，缺少可验证的财务数据事实依据",
        valuation_fairness=5,
        valuation_fairness_reason="LLM 评估不可用，缺少可验证的估值比较事实依据",
        growth_prospect=5,
        growth_prospect_reason="LLM 评估不可用，缺少可验证的增长前景事实依据",
        risk_level="medium",
        risk_factors=risk_factors or ["LLM 评估不可用，无法识别具体风险"],
        comparable_companies=[],
        recommended_action="watch",
        confidence="low",
        reasoning="LLM 评估服务不可用，采用保守中性评分。建议人工审阅招股书后再做决定。",
        evaluation_source="fallback",
    )
