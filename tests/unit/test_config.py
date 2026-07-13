import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_cannot_enable_demo_mode() -> None:
    with pytest.raises(ValidationError, match="DEMO_MODE must be false"):
        Settings(app_env="production", demo_mode=True)


def test_model_configuration_requires_every_value() -> None:
    assert Settings(llm_provider="openai", llm_model="model").model_is_configured is False
    assert (
        Settings(
            llm_provider="openai", llm_model="model", llm_api_key="not-a-real-key"
        ).model_is_configured
        is True
    )


def test_health_settings_do_not_leak_secret_values() -> None:
    settings = Settings(llm_api_key="not-a-real-key")
    assert "not-a-real-key" not in str(settings.model_dump())
