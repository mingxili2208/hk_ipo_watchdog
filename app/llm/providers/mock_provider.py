"""Mock LLM Provider 用于开发和测试。"""

from app.llm.providers.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM 提供者。"""

    def generate(self, messages: list[dict]) -> dict:
        """返回 mock 摘要 JSON。"""
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
