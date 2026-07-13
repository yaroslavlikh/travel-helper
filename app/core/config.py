"""Typed runtime configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings intentionally keep integrations disabled until configured."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Travel Choice Assistant"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    demo_mode: bool = True

    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None

    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )

    @property
    def model_is_configured(self) -> bool:
        """Whether provider selection and credentials are all present."""

        return bool(self.llm_provider and self.llm_model and self.llm_api_key)

    @property
    def langfuse_is_configured(self) -> bool:
        """Whether all Langfuse credentials required by the adapter exist."""

        return bool(
            self.langfuse_enabled
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
