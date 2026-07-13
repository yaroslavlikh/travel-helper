from typing import Any, cast

import pytest
from google.genai import errors, types
from pydantic import BaseModel, Field

from app.services.model_gateway import (
    GeminiModelGateway,
    ModelConfigurationError,
    ModelRateLimitedError,
)


class ExampleResult(BaseModel):
    value: str
    duration: float = Field(gt=0)


class FakeResponse:
    def __init__(self, parsed: Any) -> None:
        self.parsed = parsed
        self.text = None


class FakeModels:
    def __init__(
        self, response: FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class FakeAsyncClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.aio = FakeAsyncClient(models)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def gateway_for(models: FakeModels) -> GeminiModelGateway:
    return GeminiModelGateway(
        client=cast(Any, FakeClient(models)),
        model="gemini-3.1-flash-lite",
        timeout_seconds=1,
        max_output_tokens=512,
    )


@pytest.mark.asyncio
async def test_gemini_gateway_returns_validated_structured_output() -> None:
    models = FakeModels(FakeResponse({"value": "ok", "duration": 1.5}))
    gateway = gateway_for(models)

    result = await gateway.generate_structured(
        operation="test",
        prompt="prompt",
        schema=ExampleResult,
        metadata={},
    )

    assert result == ExampleResult(value="ok", duration=1.5)
    assert models.calls[0]["model"] == "gemini-3.1-flash-lite"
    config = models.calls[0]["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.temperature is None
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    duration_schema = config.response_json_schema["properties"]["duration"]
    assert duration_schema["minimum"] == 0
    assert "exclusiveMinimum" not in duration_schema


@pytest.mark.asyncio
async def test_gemini_gateway_maps_quota_errors() -> None:
    gateway = gateway_for(FakeModels(error=errors.ClientError(429, {})))

    with pytest.raises(ModelRateLimitedError):
        await gateway.generate_structured(
            operation="test",
            prompt="prompt",
            schema=ExampleResult,
            metadata={},
        )


@pytest.mark.asyncio
async def test_gemini_gateway_maps_invalid_model_configuration() -> None:
    gateway = gateway_for(FakeModels(error=errors.ClientError(404, {})))

    with pytest.raises(ModelConfigurationError):
        await gateway.generate_structured(
            operation="test",
            prompt="prompt",
            schema=ExampleResult,
            metadata={},
        )
