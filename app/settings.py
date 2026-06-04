"""配置加载模块。"""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel

from app.exceptions import ConfigError


class LLMSettings(BaseModel):
    provider: str = "mock"
    model: str = "gpt-4.1-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    thinking: Literal["enabled", "disabled"] | None = None
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout_seconds: int = 30
    retry_times: int = 1


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    min_level: int = 2


class EmailSettings(BaseModel):
    enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    encryption: Literal["starttls", "ssl", "none"] = "starttls"
    username_env: str = "SMTP_USERNAME"
    password_env: str = "SMTP_PASSWORD"
    min_level: int = 3


class BarkSettings(BaseModel):
    enabled: bool = False
    device_key_env: str = "BARK_DEVICE_KEY"
    min_level: int = 3


class ServerChanSettings(BaseModel):
    enabled: bool = False
    send_key_env: str = "SERVER_CHAN_SEND_KEY"
    min_level: int = 3


class DigestVersionUpdateSettings(BaseModel):
    enabled: bool = False
    version: str | None = None
    date: str | None = None
    title: str = "版本更新说明"
    highlights: list[str] = []
    details: list[str] = []


class QuietHoursSettings(BaseModel):
    enabled: bool = False
    start: str = "23:30"
    end: str = "08:00"


class NotificationSettings(BaseModel):
    quiet_hours: QuietHoursSettings = QuietHoursSettings()
    telegram: TelegramSettings = TelegramSettings()
    email: EmailSettings = EmailSettings()
    bark: BarkSettings = BarkSettings()
    server_chan: ServerChanSettings = ServerChanSettings()
    digest_version_update: DigestVersionUpdateSettings = DigestVersionUpdateSettings()


class RecipientsSettings(BaseModel):
    email: list[str] = []


class ScheduleItemSettings(BaseModel):
    enabled: bool = True
    interval_minutes: int = 10
    time: str | None = None
    timezone: str = "Asia/Hong_Kong"
    window_start: str | None = None
    window_end: str | None = None
    weekdays_only: bool = False


class ScheduleSettings(BaseModel):
    ipo_calendar: ScheduleItemSettings = ScheduleItemSettings(interval_minutes=10)
    hkex_announcements: ScheduleItemSettings = ScheduleItemSettings(interval_minutes=5)
    allotment_results: ScheduleItemSettings = ScheduleItemSettings(enabled=False, interval_minutes=5)
    grey_market: ScheduleItemSettings = ScheduleItemSettings(
        enabled=False,
        interval_minutes=5,
        window_start="16:15",
        window_end="18:30",
        weekdays_only=True,
    )
    llm_evaluation: ScheduleItemSettings = ScheduleItemSettings(
        enabled=True,
        time="20:30",
        timezone="Asia/Hong_Kong",
    )
    daily_digest: ScheduleItemSettings = ScheduleItemSettings(time="21:30")


class SourceConfig(BaseModel):
    enabled: bool = True
    type: str = "html"
    url: str | None = None
    interval_minutes: int = 10
    save_raw: bool = True
    timeout_seconds: int = 20
    lookback_hours: int = 24
    sources: list[dict[str, Any]] = []
    host: str | None = None
    port: int | None = None
    collect_mode: str = "html"


class SourcesSettings(BaseModel):
    hkex_new_listing: SourceConfig = SourceConfig(
        url="https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en"
    )
    hkex_news: SourceConfig = SourceConfig(
        url="https://www2.hkexnews.hk/New-Listings/New-Listing-Information/Main-Board?sc_lang=en"
    )
    aastocks_ipo: SourceConfig = SourceConfig()
    futu_ipo: SourceConfig = SourceConfig(enabled=False, type="api")
    grey_market: SourceConfig = SourceConfig(enabled=False, collect_mode="browser")


class Settings(BaseModel):
    """全局配置。"""

    config_dir: str = "config"
    database_url: str = "sqlite:///data/hk_ipo_watchdog.db"
    log_level: str = "INFO"

    sources: SourcesSettings = SourcesSettings()
    llm: LLMSettings = LLMSettings()
    notification: NotificationSettings = NotificationSettings()
    recipients: RecipientsSettings = RecipientsSettings()
    schedule: ScheduleSettings = ScheduleSettings()


def load_env(env_path: str = ".env") -> dict[str, str | None]:
    """加载 .env 文件。"""
    keys = [
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ZHIPU_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "BARK_DEVICE_KEY",
        "SERVER_CHAN_SEND_KEY",
    ]

    if Path(env_path).exists():
        load_dotenv(env_path)
        logger.info(f"Loaded .env from {env_path}")
    elif any(os.environ.get(key) for key in keys):
        logger.info("No .env file mounted; using injected environment variables")
    else:
        logger.warning(f".env file not found at {env_path}")

    return {k: os.environ.get(k) for k in keys}


def load_yaml_config(path: str) -> dict:
    """加载 YAML 配置文件。"""
    p = Path(path)
    if not p.exists():
        logger.debug(f"Config file not found: {path}, using defaults")
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if data else {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML parse error in {path}: {e}")


def resolve_llm_config(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve a selected LLM profile while preserving flat-config compatibility."""
    profiles = data.get("profiles")
    if profiles is None:
        return data

    active_profile = data.get("active_profile")
    if not isinstance(profiles, dict) or not isinstance(active_profile, str):
        raise ConfigError("LLM profiles require an active_profile and a profiles mapping")

    selected = profiles.get(active_profile)
    if not isinstance(selected, dict):
        raise ConfigError(f"LLM active_profile not found: {active_profile}")

    shared = {
        key: value
        for key, value in data.items()
        if key not in {"active_profile", "profiles"}
    }
    shared.update(selected)
    logger.info(f"Using LLM profile: {active_profile}")
    return shared


def load_settings(
    config_dir: str = "config",
    env_path: str = ".env",
    database_url: str | None = None,
    log_level: str | None = None,
) -> Settings:
    """加载所有配置。"""
    load_env(env_path)

    kwargs: dict[str, Any] = {"config_dir": config_dir}

    if database_url:
        kwargs["database_url"] = database_url
    if log_level:
        kwargs["log_level"] = log_level

    sources_data = load_yaml_config(f"{config_dir}/sources.yaml")
    if sources_data and "sources" in sources_data:
        kwargs["sources"] = sources_data["sources"]

    llm_data = load_yaml_config(f"{config_dir}/llm.yaml")
    if llm_data and "llm" in llm_data:
        kwargs["llm"] = resolve_llm_config(llm_data["llm"])

    notif_data = load_yaml_config(f"{config_dir}/notification.yaml")
    if notif_data and "notification" in notif_data:
        kwargs["notification"] = notif_data["notification"]

    recipients_data = load_yaml_config(f"{config_dir}/recipients.yaml")
    if recipients_data and "recipients" in recipients_data:
        kwargs["recipients"] = recipients_data["recipients"]

    sched_data = load_yaml_config(f"{config_dir}/schedule.yaml")
    if sched_data and "schedule" in sched_data:
        kwargs["schedule"] = sched_data["schedule"]

    return Settings(**kwargs)
