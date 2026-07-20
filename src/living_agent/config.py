"""Validated application settings loaded from YAML with environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class Settings(BaseSettings):
    """Runtime settings. Environment variables override YAML values."""

    model_config = SettingsConfigDict(
        env_prefix="LIVING_AGENT_",
        env_file=".env",
        extra="forbid",
        case_sensitive=False,
    )

    app_name: str = "LivingAgent"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite+aiosqlite:///./living_agent.db"
    owner_id: str = "owner-local"
    admin_ids: list[str] = Field(default_factory=list)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    model_provider: Literal["mock"] = "mock"
    audit_page_size: int = Field(default=100, ge=1, le=1000)
    test_disable_delays: bool = False

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        config_path = Path(os.getenv("LIVING_AGENT_CONFIG", "config/default.yaml"))
        yaml_settings = YamlConfigSettingsSource(settings_cls, yaml_file=config_path)
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            yaml_settings,
            file_secret_settings,
        )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        supported = ("sqlite+aiosqlite://", "postgresql+asyncpg://")
        if not value.startswith(supported):
            raise ValueError("database_url must use sqlite+aiosqlite or postgresql+asyncpg")
        return value

    @field_validator("owner_id")
    @classmethod
    def validate_owner_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("owner_id cannot be empty")
        return normalized


def load_settings() -> Settings:
    """Load settings through the configured Pydantic source chain."""

    return Settings()
