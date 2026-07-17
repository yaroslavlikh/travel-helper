"""Typed runtime configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings intentionally keep integrations disabled until configured."""

    model_config = SettingsConfigDict(
        # Keep shared development defaults in .env while allowing per-machine secrets and
        # observability settings in the ignored .env.local file. Later files take precedence.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Travel Choice Assistant"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    demo_mode: bool = True
    checkpoint_db_path: str = ".data/travel-helper.sqlite3"
    places_database_url: str | None = None
    places_embedding_version: str = "hash-v1"
    aviasales_marker: str | None = None

    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "GEMINI_API_KEY"),
    )
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_output_tokens: int = Field(default=2_048, ge=128, le=65_536)

    # None means "enable when complete credentials are present"; false remains an explicit opt-out.
    langfuse_enabled: bool | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )
    langfuse_capture_content: bool = False

    @property
    def model_is_configured(self) -> bool:
        """Whether provider selection and credentials are all present."""

        return bool(self.llm_provider and self.llm_model and self.llm_api_key)

    @property
    def langfuse_is_configured(self) -> bool:
        """Whether all Langfuse credentials required by the adapter exist."""

        return bool(
            self.langfuse_enabled is not False
            and self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_base_url
        )

    @model_validator(mode="after")
    def validate_production_mode(self) -> Settings:
        """Production must never silently serve fixture-only recommendations."""

        if self.app_env == "production" and self.demo_mode:
            raise ValueError("DEMO_MODE must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable settings instance."""

    return Settings()
