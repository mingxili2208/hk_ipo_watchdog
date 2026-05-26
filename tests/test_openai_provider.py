"""OpenAI-compatible provider request tests."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.llm.providers.openai_provider import OpenAICompatibleProvider
from app.settings import LLMSettings


def _response():
    content = json.dumps(
        {
            "title": "Test",
            "summary": "Summary",
            "key_points": [],
            "trigger_reasons": [],
            "risks": [],
            "suggested_action": "Observe",
            "confidence": "low",
        }
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=21,
            completion_tokens=13,
            total_tokens=34,
            prompt_tokens_details=SimpleNamespace(cached_tokens=5),
        ),
    )


def test_zhipu_thinking_option_is_forwarded_as_vendor_body(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")
    client = MagicMock()
    client.chat.completions.create.return_value = _response()

    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=lambda **_: client)}):
        provider = OpenAICompatibleProvider(
            LLMSettings(
                provider="openai",
                model="glm-5.1",
                api_key_env="ZHIPU_API_KEY",
                thinking="disabled",
            )
        )
        provider.generate([{"role": "user", "content": "JSON"}])

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_standard_openai_profile_does_not_send_vendor_thinking_body(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = MagicMock()
    client.chat.completions.create.return_value = _response()

    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=lambda **_: client)}):
        provider = OpenAICompatibleProvider(LLMSettings(provider="openai"))
        provider.generate([{"role": "user", "content": "JSON"}])

    assert "extra_body" not in client.chat.completions.create.call_args.kwargs


def test_provider_exposes_api_token_usage_once(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test-key")
    client = MagicMock()
    client.chat.completions.create.return_value = _response()

    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=lambda **_: client)}):
        provider = OpenAICompatibleProvider(
            LLMSettings(provider="openai", model="glm-5.1", api_key_env="ZHIPU_API_KEY")
        )
        provider.generate([{"role": "user", "content": "JSON"}])

    assert provider.consume_usage() == {
        "provider": "openai",
        "model": "glm-5.1",
        "prompt_tokens": 21,
        "completion_tokens": 13,
        "total_tokens": 34,
        "cached_tokens": 5,
    }
    assert provider.consume_usage() is None
