"""Validated application settings loaded from YAML with environment overrides."""

from __future__ import annotations

import os
import re
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from living_agent.plugins.sandbox import PluginSandbox, PluginSandboxUnavailableError


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
    management_api_token: SecretStr | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    ingress_max_request_bytes: int = Field(
        default=32 * 1024 * 1024,
        ge=1024,
        le=128 * 1024 * 1024,
    )
    event_conversation_storage_limit_bytes: int = Field(
        default=100 * 1024 * 1024,
        ge=1024,
        le=4 * 1024 * 1024 * 1024,
    )
    event_total_storage_limit_bytes: int = Field(
        default=1024 * 1024 * 1024,
        ge=1024,
        le=16 * 1024 * 1024 * 1024,
    )
    model_provider: Literal["mock", "openai_compatible"] = "mock"
    model_name: str = "mock-chat-v1"
    model_vision_name: str = "gpt-5.5"
    model_image_mode: Literal["auto", "caption", "direct"] = "auto"
    model_image_description_cache_entries: int = Field(default=256, ge=0, le=10000)
    model_image_description_max_chars: int = Field(default=1200, ge=100, le=4000)
    model_image_allowed_hosts: list[str] = Field(default_factory=list, max_length=100)
    model_api_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_timeout_seconds: float = Field(default=60.0, gt=0.0, le=300.0)
    model_max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    model_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    model_max_context_chars: int = Field(default=100000, ge=1000, le=1000000)
    model_max_response_bytes: int = Field(default=1048576, ge=1024, le=16777216)
    model_allow_insecure_http: bool = False
    model_allow_insecure_image_urls: bool = False
    embedding_provider: Literal["mock", "openai_compatible"] = "mock"
    embedding_model: str = "mock-hash-v1"
    embedding_api_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_dimensions: int | None = Field(default=None, ge=1, le=65536)
    embedding_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    embedding_max_batch_size: int = Field(default=32, ge=1, le=256)
    embedding_max_input_chars: int = Field(default=12000, ge=1, le=100000)
    embedding_max_total_chars: int = Field(default=48000, ge=1, le=1000000)
    embedding_max_response_bytes: int = Field(default=4194304, ge=1024, le=67108864)
    embedding_allow_insecure_http: bool = False
    memory_auto_candidates_enabled: bool = True
    memory_auto_approval_enabled: bool = True
    memory_self_candidates_enabled: bool = False
    memory_self_candidate_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    memory_embeddings_enabled: bool = False
    memory_embeddings_allow_remote: bool = False
    memory_embedding_backfill_limit: int = Field(default=2000, ge=1, le=100000)
    memory_embedding_min_similarity: float = Field(default=0.25, ge=-1.0, le=1.0)
    memory_recall_candidate_limit: int = Field(default=300, ge=1, le=5000)
    memory_recall_mode: Literal["legacy", "shadow", "dual"] = "dual"
    memory_recall_min_score: float = Field(default=0.4, ge=0.0, le=1.0)
    memory_narrative_recall_limit: int = Field(default=2, ge=1, le=8)
    audit_page_size: int = Field(default=100, ge=1, le=1000)
    test_disable_delays: bool = False
    plugin_root: Path = Path("plugins/examples")
    enabled_plugins: list[str] = Field(default_factory=lambda: ["com.livingagent.calculator"])
    plugin_timeout_seconds: float = Field(default=2.0, gt=0.0, le=30.0)
    plugin_sandbox_mode: Literal["auto", "required", "disabled"] = "auto"
    persona_root: Path = Path("personas/default")
    prompt_root: Path = Path("prompts")
    root_prompt_second_factor_sha256: str | None = None
    work_workspace_root: Path = Path(".")
    work_max_file_bytes: int = Field(default=1_048_576, ge=1024, le=16_777_216)
    work_web_search_endpoint: str = "https://html.duckduckgo.com/html/"
    work_web_allowed_hosts: list[str] = Field(default_factory=list, max_length=100)
    work_web_allow_insecure_http: bool = False
    work_web_timeout_seconds: float = Field(default=15.0, gt=0.0, le=120.0)
    work_web_max_response_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=16_777_216,
    )
    work_shell_enabled: bool = True
    work_shell_allowed_executables: list[str] = Field(
        default_factory=lambda: ["git", "mypy", "pwd", "pytest", "rg", "ruff", "uv"],
        min_length=1,
        max_length=50,
    )
    work_shell_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    work_shell_max_output_bytes: int = Field(default=262_144, ge=1024, le=4_194_304)
    psyche_decay_half_life_hours: float = Field(default=12.0, gt=0.0, le=720.0)
    social_engage_units_min: int = Field(default=2, ge=1, le=3)
    social_engage_units_max: int = Field(default=3, ge=1, le=3)
    social_followup_delay_min_ms: int = Field(default=300, ge=0, le=10000)
    social_followup_delay_max_ms: int = Field(default=650, ge=0, le=10000)
    social_group_auto_participation: bool = False
    social_group_participation_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    social_group_min_user_turns: int = Field(default=5, ge=1, le=100)
    social_group_cooldown_seconds: float = Field(default=60.0, ge=0.0, le=86400.0)
    social_avoid_full_stops: bool = False
    social_scheduler_enabled: bool = True
    social_focus_idle_exit_cycles: int = Field(default=3, ge=1, le=100)
    social_mid_term_min_events: int = Field(default=6, ge=3, le=64)
    social_mid_term_ttl_hours: float = Field(default=72.0, gt=0.0, le=2160.0)
    social_attention_cue_ttl_minutes: float = Field(default=30.0, gt=0.0, le=10080.0)
    napcat_enabled: bool = False
    napcat_access_token: SecretStr | None = None
    napcat_action_timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    napcat_max_message_chars: int = Field(default=12000, ge=1, le=100000)
    napcat_max_frame_bytes: int = Field(default=1048576, ge=1024, le=52428800)
    napcat_max_in_flight_events: int = Field(default=16, ge=1, le=256)
    openclaw_bridge_enabled: bool = False
    openclaw_bridge_access_token: SecretStr | None = None
    openclaw_bridge_allowed_channels: list[str] = Field(default_factory=lambda: ["openclaw-weixin"])
    openclaw_bridge_allowed_account_ids: list[str] = Field(default_factory=list)
    openclaw_bridge_max_message_chars: int = Field(default=12000, ge=1, le=100000)
    openclaw_bridge_idempotency_entries: int = Field(default=2048, ge=1, le=100000)
    life_timezone: str = "Asia/Shanghai"
    life_nightly_enabled: bool = False
    life_nightly_hour: int = Field(default=3, ge=0, le=23)
    life_scheduler_poll_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)

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

    @field_validator("management_api_token")
    @classmethod
    def validate_management_api_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        normalized = value.get_secret_value().strip()
        if len(normalized) < 32:
            raise ValueError("management_api_token must contain at least 32 characters")
        return SecretStr(normalized)

    @field_validator("model_name", "model_vision_name", "embedding_model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 255:
            raise ValueError("model names must contain 1 to 255 characters")
        return normalized

    @field_validator("model_image_allowed_hosts", "work_web_allowed_hosts")
    @classmethod
    def validate_image_allowed_hosts(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for host in value:
            candidate = host.strip().rstrip(".").casefold()
            if (
                not candidate
                or len(candidate) > 253
                or "://" in candidate
                or "/" in candidate
                or candidate == "*"
            ):
                raise ValueError("model_image_allowed_hosts must contain exact hostnames")
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized

    @field_validator("work_web_search_endpoint")
    @classmethod
    def validate_work_search_endpoint(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("work_web_search_endpoint must be an HTTP(S) URL without credentials")
        return normalized

    @field_validator("work_shell_allowed_executables")
    @classmethod
    def validate_shell_executables(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for executable in value:
            candidate = executable.strip()
            if (
                not candidate
                or len(candidate) > 100
                or "/" in candidate
                or "\\" in candidate
                or re.fullmatch(r"[A-Za-z0-9_.+-]+", candidate) is None
            ):
                raise ValueError(
                    "work_shell_allowed_executables must contain exact command names"
                )
            if candidate not in normalized:
                normalized.append(candidate)
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

    @field_validator("life_timezone")
    @classmethod
    def validate_life_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("life_timezone must be a valid IANA timezone") from exc
        return normalized

    @model_validator(mode="after")
    def validate_adapter_credentials(self) -> Self:
        management_token = self.management_api_token
        if self.environment == "production" and management_token is None:
            raise ValueError("management_api_token is required in production")
        if self.environment == "production" and self.plugin_sandbox_mode == "disabled":
            raise ValueError("plugin_sandbox_mode cannot be disabled in production")
        try:
            sandbox_enforced = PluginSandbox(mode=self.plugin_sandbox_mode).status.enforced
        except PluginSandboxUnavailableError as exc:
            raise ValueError(
                "a supported plugin sandbox backend is required in production"
            ) from exc
        if self.environment == "production" and not sandbox_enforced:
            raise ValueError("a supported plugin sandbox backend is required in production")
        if self.social_engage_units_min > self.social_engage_units_max:
            raise ValueError("social_engage_units_min cannot exceed social_engage_units_max")
        if self.social_followup_delay_min_ms > self.social_followup_delay_max_ms:
            raise ValueError(
                "social_followup_delay_min_ms cannot exceed social_followup_delay_max_ms"
            )
        if self.memory_auto_approval_enabled and not self.memory_auto_candidates_enabled:
            raise ValueError("memory_auto_approval_enabled requires memory_auto_candidates_enabled")
        if self.model_provider == "openai_compatible":
            if self.model_api_base_url is None:
                raise ValueError("model_api_base_url is required for openai_compatible provider")
            model_loopback = self._validate_external_api_url(
                self.model_api_base_url,
                setting_name="model_api_base_url",
                allow_insecure_http=self.model_allow_insecure_http,
            )
            key = self.model_api_key
            if not model_loopback and (key is None or not key.get_secret_value().strip()):
                raise ValueError("model_api_key is required for a remote model API")
        if self.embedding_provider == "openai_compatible":
            if self.embedding_api_base_url is None:
                raise ValueError(
                    "embedding_api_base_url is required for openai_compatible provider"
                )
            self._validate_external_api_url(
                self.embedding_api_base_url,
                setting_name="embedding_api_base_url",
                allow_insecure_http=self.embedding_allow_insecure_http,
            )
        self._validate_external_api_url(
            self.work_web_search_endpoint,
            setting_name="work_web_search_endpoint",
            allow_insecure_http=self.work_web_allow_insecure_http,
        )
        if self.napcat_enabled:
            token = self.napcat_access_token
            if token is None or not token.get_secret_value().strip():
                raise ValueError("napcat_access_token is required when NapCat is enabled")
        if self.openclaw_bridge_enabled:
            token = self.openclaw_bridge_access_token
            if token is None or not token.get_secret_value().strip():
                raise ValueError(
                    "openclaw_bridge_access_token is required when OpenClaw bridge is enabled"
                )
            if not self.openclaw_bridge_allowed_channels:
                raise ValueError("OpenClaw bridge requires at least one allowed channel")
        return self

    @staticmethod
    def _validate_external_api_url(
        value: str,
        *,
        setting_name: str,
        allow_insecure_http: bool,
    ) -> bool:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{setting_name} must be an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f"{setting_name} cannot contain credentials, query, or fragment")
        hostname = parsed.hostname.lower()
        try:
            loopback = ip_address(hostname).is_loopback
        except ValueError:
            loopback = hostname == "localhost"
        if parsed.scheme != "https" and not loopback and not allow_insecure_http:
            raise ValueError(
                f"remote {setting_name} requires HTTPS unless insecure HTTP is explicit"
            )
        return loopback


def load_settings() -> Settings:
    """Load settings through the configured Pydantic source chain."""

    return Settings()
