"""OpenAI-compatible LLM Provider。"""

import json
import os

from loguru import logger

from app.exceptions import LLMError
from app.llm.providers.base import BaseLLMProvider
from app.settings import LLMSettings


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI 兼容的 LLM 提供者。"""

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        api_key = os.environ.get(settings.api_key_env, "")
        if not api_key:
            raise LLMError(f"API key not found in env: {settings.api_key_env}")

        try:
            from openai import OpenAI

            kwargs = {
                "api_key": api_key,
                "timeout": settings.timeout_seconds,
            }
            if settings.base_url:
                kwargs["base_url"] = settings.base_url

            self.client = OpenAI(**kwargs)
            self.model = settings.model
            self.thinking = settings.thinking
            self.temperature = settings.temperature
            self.max_tokens = settings.max_tokens
            self._last_usage = None
        except Exception as e:
            raise LLMError(f"Failed to initialize OpenAI client: {e}")

    def generate(self, messages: list[dict]) -> dict:
        """调用 OpenAI API 生成 JSON。"""
        try:
            self._last_usage = None
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
            }
            if self.thinking:
                kwargs["extra_body"] = {"thinking": {"type": self.thinking}}

            response = self.client.chat.completions.create(
                **kwargs
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                details = getattr(usage, "prompt_tokens_details", None)
                self._last_usage = {
                    "provider": self.settings.provider,
                    "model": self.model,
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    "cached_tokens": getattr(details, "cached_tokens", 0) or 0,
                }

            content = response.choices[0].message.content
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM output is not valid JSON: {e}")
        except Exception as e:
            raise LLMError(f"LLM API call failed: {e}")
