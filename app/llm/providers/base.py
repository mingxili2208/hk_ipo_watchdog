"""LLM Provider 基类。"""


class BaseLLMProvider:
    """LLM 提供者基类。"""

    def generate(self, messages: list[dict]) -> dict:
        """根据 messages 生成 JSON 结果。"""
        raise NotImplementedError

    def consume_usage(self) -> dict | None:
        """返回并清除最近一次实际 API 调用的 token 用量。"""
        usage = getattr(self, "_last_usage", None)
        self._last_usage = None
        return usage
