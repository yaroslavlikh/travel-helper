import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_cannot_enable_demo_mode() -> None:
    with pytest.raises(ValidationError, match="DEMO_MODE must be false"):
        Settings(app_env="production", demo_mode=True, _env_file=None)


def test_production_password_login_requires_a_session_secret() -> None:
    with pytest.raises(ValidationError, match="AUTH_SESSION_SECRET"):
        Settings(app_env="production", demo_mode=False, _env_file=None)


def test_production_rejects_public_fixture_pricing() -> None:
    with pytest.raises(ValidationError, match="Fixture pricing"):
        Settings(
            app_env="production",
            demo_mode=False,
            auth_session_secret="a" * 32,
            pricing_public_display_enabled=True,
            flight_provider_mode="fixture",
            _env_file=None,
        )


def test_production_requires_explicit_non_local_trusted_host() -> None:
    with pytest.raises(ValidationError, match="TRUSTED_HOSTS"):
        Settings(
            app_env="production",
            demo_mode=False,
            auth_session_secret="a" * 32,
            _env_file=None,
        )


def test_production_rejects_non_https_cors_origin() -> None:
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        Settings(
            app_env="production",
            demo_mode=False,
            auth_session_secret="a" * 32,
            trusted_hosts="travel.example",
            cors_allowed_origins="http://app.example",
            _env_file=None,
        )


def test_development_keeps_local_hosts_when_hosted_domains_are_configured() -> None:
    settings = Settings(
        app_env="development",
        trusted_hosts="todayway.ru,www.todayway.ru",
        _env_file=None,
    )

    assert {"localhost", "127.0.0.1"}.issubset(settings.trusted_host_list)


def test_model_configuration_requires_every_value() -> None:
    assert (
        Settings(llm_provider="openai", llm_model="model", _env_file=None).model_is_configured
        is False
    )
    assert (
        Settings(
            llm_provider="openai",
            llm_model="model",
            llm_api_key="not-a-real-key",
            _env_file=None,
        ).model_is_configured
        is True
    )


def test_health_settings_do_not_leak_secret_values() -> None:
    settings = Settings(llm_api_key="not-a-real-key", _env_file=None)
    assert "not-a-real-key" not in str(settings.model_dump())


def test_gemini_api_key_environment_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")

    settings = Settings(
        llm_provider="gemini",
        llm_model="gemini-3.1-flash-lite",
        _env_file=None,
    )

    assert settings.model_is_configured is True
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "not-a-real-key"


def test_complete_langfuse_credentials_enable_tracing_unless_explicitly_disabled() -> None:
    settings = Settings(
        langfuse_public_key="public",
        langfuse_secret_key="secret",
        langfuse_base_url="https://langfuse.example",
        _env_file=None,
    )
    disabled = settings.model_copy(update={"langfuse_enabled": False})

    assert settings.langfuse_is_configured is True
    assert disabled.langfuse_is_configured is False
