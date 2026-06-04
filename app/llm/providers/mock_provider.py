"""Mock LLM Provider 用于开发和测试。"""

from app.llm.providers.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM 提供者。"""

    def generate(self, messages: list[dict]) -> dict:
        """根据 prompt 类型返回 mock JSON。"""
        system_text = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
                break

        # 评估请求
        if "IPO 分析师" in system_text or "business_quality" in system_text:
            return {
                "business_quality": 7,
                "business_quality_reason": "Mock公司在国内SaaS市场排名前三，客户续约率约90%，核心产品有3项专利保护",
                "financial_health": 6,
                "financial_health_reason": "2025年收入50亿港元，同比增长25%，净利润8亿，毛利率45%",
                "valuation_fairness": 5,
                "valuation_fairness_reason": "招股价对应PE 15倍，同行业已上市公司中位数PE 18倍",
                "growth_prospect": 8,
                "growth_prospect_reason": "目标市场规模800亿元，年复合增速20%，十四五规划明确支持",
                "risk_level": "medium",
                "risk_factors": ["数据来源为 mock，仅供参考"],
                "comparable_companies": ["Mock Corp (00000.HK)"],
                "recommended_action": "subscribe",
                "confidence": "medium",
                "reasoning": "Mock 评估结果，仅供测试。实际评估需要真实 LLM 服务。",
            }

        # 财务数据提取请求
        if "财务数据提取" in system_text:
            return {
                "revenue_hkd_million": 5000.0,
                "net_profit_hkd_million": 800.0,
                "revenue_growth_yoy": 25.0,
                "net_profit_growth_yoy": 30.0,
                "gross_margin": 45.0,
                "net_margin": 16.0,
                "total_debt_to_equity": 0.5,
                "fiscal_year": "FY2025",
            }

        # 摘要请求（默认）
        return {
            "title": "新股打新提醒：Mock Stock",
            "summary": "该新股符合基本筛选条件，综合评分较高。",
            "key_points": [
                "入场费在可接受范围",
                "综合评分较高",
            ],
            "trigger_reasons": [
                "符合低入场费策略",
                "综合评分达到观察线",
            ],
            "risks": [
                "数据来源为 mock，仅供参考",
            ],
            "suggested_action": "等待更多数据后自行判断",
            "confidence": "medium",
        }
