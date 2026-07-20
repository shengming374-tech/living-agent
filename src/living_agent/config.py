"""Validated application settings loaded from YAML with environment overrides."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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
    plugin_root: Path = Path("plugins/examples")
    enabled_plugins: list[str] = Field(default_factory=lambda: ["com.livingagent.calculator"])
    plugin_timeout_seconds: float = Field(default=2.0, gt=0.0, le=30.0)
    persona_root: Path = Path("personas/default")
    prompt_root: Path = Path("prompts")
    root_prompt_second_factor_sha256: str | None = None
    psyche_decay_half_life_hours: float = Field(default=12.0, gt=0.0, le=720.0)
    napcat_enabled: bool = False
    napcat_access_token: SecretStr | None = None
    napcat_action_timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    napcat_max_message_chars: int = Field(default=12000, ge=1, le=100000)
    napcat_max_frame_bytes: int = Field(default=1048576, ge=1024, le=52428800)
    napcat_max_in_flight_events: int = Field(default=16, ge=1, le=256)

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

    @field_validator("root_prompt_second_factor_sha256")
    @classmethod
    def validate_second_factor_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
            raise ValueError("root_prompt_second_factor_sha256 must be a SHA-256 hex digest")
        return normalized

    @model_validator(mode="after")
    def validate_napcat_credentials(self) -> Self:
        if self.napcat_enabled:
            token = self.napcat_access_token
            if token is None or not token.get_secret_value().strip():
                raise ValueError("napcat_access_token is required when NapCat is enabled")
        return self


def load_settings() -> Settings:
    """Load settings through the configured Pydantic source chain."""

    return Settings()
