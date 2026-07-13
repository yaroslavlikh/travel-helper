import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_cannot_enable_demo_mode() -> None:
    with pytest.raises(ValidationError, match="DEMO_MODE must be false"):
        Settings(app_env="production", demo_mode=True, _env_file=None)


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
