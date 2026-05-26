"""Configuration loading tests."""

from pathlib import Path

import pytest

from app.exceptions import ConfigError
from app.settings import load_settings


def _write_llm_config(config_dir: Path, contents: str) -> None:
    config_dir.mkdir()
    (config_dir / "llm.yaml").write_text(contents, encoding="utf-8")


def test_load_settings_resolves_selected_llm_profile(tmp_path):
    config_dir = tmp_path / "config"
    _write_llm_config(
        config_dir,
        """
llm:
  active_profile: glm
  temperature: 0.4
  profiles:
    mock:
      provider: mock
    glm:
      provider: openai
      model: glm-5.1
      api_key_env: ZHIPU_API_KEY
      base_url: "https://open.bigmodel.cn/api/paas/v4/"
      thinking: disabled
""",
    )

    settings = load_settings(config_dir=str(config_dir), env_path=str(tmp_path / ".env"))

    assert settings.llm.provider == "openai"
    assert settings.llm.model == "glm-5.1"
    assert settings.llm.api_key_env == "ZHIPU_API_KEY"
    assert settings.llm.thinking == "disabled"
    assert settings.llm.temperature == 0.4


def test_load_settings_keeps_legacy_flat_llm_config(tmp_path):
    config_dir = tmp_path / "config"
    _write_llm_config(
        config_dir,
        """
llm:
  provider: mock
  temperature: 0.3
""",
    )

    settings = load_settings(config_dir=str(config_dir), env_path=str(tmp_path / ".env"))

    assert settings.llm.provider == "mock"
    assert settings.llm.temperature == 0.3


def test_load_settings_rejects_unknown_llm_profile(tmp_path):
    config_dir = tmp_path / "config"
    _write_llm_config(
        config_dir,
        """
llm:
  active_profile: missing
  profiles:
    mock:
      provider: mock
""",
    )

    with pytest.raises(ConfigError, match="active_profile not found: missing"):
        load_settings(config_dir=str(config_dir), env_path=str(tmp_path / ".env"))
