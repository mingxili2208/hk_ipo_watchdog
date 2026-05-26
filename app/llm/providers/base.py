"""LLM Provider 基类。"""


class BaseLLMProvider:
    """LLM 提供者基类。"""

    def generate(self, messages: list[dict]) -> dict:
        """根据 messages 生成 JSON 结果。"""
        raise NotImplementedError
