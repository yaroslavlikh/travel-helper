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

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Travel Choice Assistant"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    demo_mode: bool = True
    checkpoint_db_path: str = ".data/travel-helper.sqlite3"
    account_db_path: str = ".data/travel-accounts.sqlite3"
    places_database_url: str | None = None
    places_embedding_version: str = "hash-v1"
    aviasales_marker: str | None = None

    flight_provider_mode: Literal["disabled", "fixture", "cached", "live"] = "disabled"
    stay_provider_mode: Literal["disabled", "fixture", "cached", "live"] = "disabled"
    pricing_live_enabled: bool = False
    pricing_cached_enabled: bool = False
    pricing_fixture_enabled: bool = False
    pricing_public_display_enabled: bool = False
    pricing_debug_breakdown_enabled: bool = False
    amadeus_client_id: SecretStr | None = None
    amadeus_client_secret: SecretStr | None = None
    booking_api_key: SecretStr | None = None
    booking_affiliate_id: SecretStr | None = None

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

    oidc_issuer: str | None = None
    oidc_authorization_url: str | None = None
    oidc_token_url: str | None = None
    oidc_userinfo_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str = "http://127.0.0.1:8000/auth/callback"
    auth_session_secret: SecretStr | None = None
    auth_cookie_secure_override: bool | None = None
    password_auth_enabled: bool = True

    @property
    def model_is_configured(self) -> bool:
        """Whether provider selection and credentials are all present."""

        return bool(self.llm_provider and self.llm_model and self.llm_api_key)

    @property
    def amadeus_is_configured(self) -> bool:
        return bool(self.amadeus_client_id and self.amadeus_client_secret)

    @property
    def booking_is_configured(self) -> bool:
        return bool(self.booking_api_key and self.booking_affiliate_id)

    @property
    def langfuse_is_configured(self) -> bool:
        """Whether all Langfuse credentials required by the adapter exist."""

        return bool(
            self.langfuse_enabled is not False
            and self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_base_url
        )

    @property
    def auth_is_configured(self) -> bool:
        return bool(
            self.oidc_issuer
            and self.oidc_authorization_url
            and self.oidc_token_url
            and self.oidc_userinfo_url
            and self.oidc_client_id
            and self.oidc_client_secret
            and self.auth_session_secret
        )

    @property
    def password_auth_is_configured(self) -> bool:
        return self.password_auth_enabled and (
            self.app_env != "production" or bool(self.auth_session_secret)
        )

    @property
    def account_auth_is_configured(self) -> bool:
        return self.auth_is_configured or self.password_auth_is_configured

    @property
    def auth_cookie_secure(self) -> bool:
        if self.auth_cookie_secure_override is not None:
            return self.auth_cookie_secure_override
        return self.app_env == "production"

    @property
    def oidc_client_secret_value(self) -> str:
        return self.oidc_client_secret.get_secret_value() if self.oidc_client_secret else ""

    @property
    def auth_session_secret_value(self) -> str:
        return self.auth_session_secret.get_secret_value() if self.auth_session_secret else ""

    @model_validator(mode="after")
    def validate_production_mode(self) -> Settings:
        """Production must never silently serve fixture-only recommendations."""

        if self.app_env == "production" and self.demo_mode:
            raise ValueError("DEMO_MODE must be false in production")
        if (
            self.app_env == "production"
            and self.pricing_public_display_enabled
            and (self.flight_provider_mode == "fixture" or self.stay_provider_mode == "fixture")
        ):
            raise ValueError("Fixture pricing cannot be displayed publicly in production")
        if self.app_env == "production" and (self.auth_is_configured or self.password_auth_enabled):
            if not self.auth_cookie_secure:
                raise ValueError("Secure account cookies are required in production")
            if len(self.auth_session_secret_value) < 32:
                raise ValueError("AUTH_SESSION_SECRET must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable settings instance."""

    return Settings()
