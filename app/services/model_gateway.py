"""Provider-neutral LLM gateway with a Gemini implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.observability.port import NoopObservability, ObservabilityPort

StructuredResult = TypeVar("StructuredResult", bound=BaseModel)


class ModelGatewayError(RuntimeError):
    """Base error that graph nodes can handle without importing provider SDK types."""


class ModelConfigurationError(ModelGatewayError):
    """The requested provider cannot be created from current settings."""


class ModelUnavailableError(ModelGatewayError):
    """The provider failed temporarily or returned a server error."""


class ModelRateLimitedError(ModelGatewayError):
    """The configured quota or rate limit has been exhausted."""


class ModelTimeoutError(ModelGatewayError):
    """The provider did not finish within the operation budget."""


class ModelInvalidOutputError(ModelGatewayError):
    """The provider response did not satisfy the requested schema."""


class ModelGateway(Protocol):
    """Minimal capability contract consumed by extraction and explanation nodes."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str | None: ...

    async def generate_structured(
        self,
        *,
        operation: str,
        prompt: str,
        schema: type[StructuredResult],
        metadata: dict[str, Any],
    ) -> StructuredResult: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DisabledModelGateway:
    """Explicit failure mode when no supported provider is configured."""

    reason: str

    @property
    def provider_name(self) -> str:
        return "disabled"

    @property
    def model_name(self) -> str | None:
        return None

    async def generate_structured(
        self,
        *,
        operation: str,
        prompt: str,
        schema: type[StructuredResult],
        metadata: dict[str, Any],
    ) -> StructuredResult:
        del operation, prompt, schema, metadata
        raise ModelConfigurationError(self.reason)

    async def aclose(self) -> None:
        return None


class GeminiModelGateway:
    """Async structured generation backed by the official Google Gen AI SDK."""

    def __init__(
        self,
        *,
        client: genai.Client,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        observability: ObservabilityPort | None = None,
        capture_content: bool = False,
    ) -> None:
        self._client = client
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._observability = observability or NoopObservability()
        self._capture_content = capture_content

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_structured(
        self,
        *,
        operation: str,
        prompt: str,
        schema: type[StructuredResult],
        metadata: dict[str, Any],
    ) -> StructuredResult:
        generation_input: dict[str, Any] = {
            "operation": operation,
            "schema": schema.__name__,
            "prompt_length": len(prompt),
        }
        if self._capture_content:
            generation_input["prompt"] = prompt
        generation_metadata = {
            **metadata,
            "operation": operation,
            "schema": schema.__name__,
        }
        with self._observability.generation(
            operation,
            model=self._model,
            input=generation_input,
            metadata=generation_metadata,
        ) as observation:
            try:
                result, response = await self._request_structured(prompt=prompt, schema=schema)
            except ModelGatewayError as error:
                observation.update(
                    level="ERROR",
                    status_message=type(error).__name__,
                    metadata={"outcome": "error", "error_type": type(error).__name__},
                )
                raise
            observation.update(
                output=(
                    result.model_dump(mode="json")
                    if self._capture_content
                    else {"schema": schema.__name__, "validated": True}
                ),
                metadata={"outcome": "success"},
                usage_details=_gemini_usage_details(response),
            )
            return result

    async def _request_structured(
        self,
        *,
        prompt: str,
        schema: type[StructuredResult],
    ) -> tuple[StructuredResult, Any]:
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=self._max_output_tokens,
                        thinking_config=_thinking_config(self._model),
                        response_mime_type="application/json",
                        response_json_schema=_gemini_json_schema(schema),
                    ),
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise ModelTimeoutError("Gemini request timed out") from exc
        except errors.APIError as exc:
            raise _map_gemini_error(exc) from exc
        except ValidationError as exc:
            raise ModelConfigurationError("Gemini rejected the structured schema") from exc

        try:
            if isinstance(response.parsed, schema):
                return response.parsed, response
            if isinstance(response.parsed, BaseModel):
                return schema.model_validate(response.parsed.model_dump()), response
            if response.parsed is not None:
                return schema.model_validate(response.parsed), response
            if response.text:
                return schema.model_validate_json(response.text), response
        except (ValidationError, ValueError) as exc:
            raise ModelInvalidOutputError("Gemini returned invalid structured output") from exc
        raise ModelInvalidOutputError("Gemini returned no structured output")

    async def aclose(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def _map_gemini_error(error: errors.APIError) -> ModelGatewayError:
    if error.code == 429:
        return ModelRateLimitedError("Gemini rate limit or quota was exceeded")
    if error.code in {408, 504}:
        return ModelTimeoutError("Gemini request timed out")
    if error.code >= 500:
        return ModelUnavailableError("Gemini service is temporarily unavailable")
    if error.code in {400, 401, 403, 404}:
        return ModelConfigurationError(
            f"Gemini rejected provider configuration with status {error.code}"
        )
    return ModelUnavailableError(f"Gemini request failed with status {error.code}")


def _gemini_usage_details(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    values = {
        "input": getattr(usage, "prompt_token_count", None),
        "output": getattr(usage, "candidates_token_count", None),
        "total": getattr(usage, "total_token_count", None),
    }
    return {key: value for key, value in values.items() if isinstance(value, int)}


def _gemini_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Translate unsupported strict numeric bounds to Gemini's schema subset."""

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if key == "exclusiveMinimum":
                    normalized["minimum"] = normalize(item)
                elif key == "exclusiveMaximum":
                    normalized["maximum"] = normalize(item)
                else:
                    normalized[key] = normalize(item)
            return normalized
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return cast(dict[str, Any], normalize(schema.model_json_schema()))


def _thinking_config(model: str) -> types.ThinkingConfig:
    """Use the lowest supported reasoning level for deterministic extraction."""

    if model.startswith("gemini-2.5-"):
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def create_model_gateway(
    settings: Settings,
    *,
    observability: ObservabilityPort | None = None,
) -> ModelGateway:
    """Build one process-scoped model gateway during FastAPI lifespan startup."""

    if not settings.model_is_configured:
        return DisabledModelGateway(
            "No LLM provider is configured; application is running in demo-ready mode"
        )
    if settings.llm_provider is None or settings.llm_model is None or settings.llm_api_key is None:
        return DisabledModelGateway("Incomplete LLM configuration")
    if settings.llm_provider.casefold() != "gemini":
        return DisabledModelGateway(f"Unsupported LLM provider: {settings.llm_provider}")

    client = genai.Client(api_key=settings.llm_api_key.get_secret_value())
    return cast(
        ModelGateway,
        GeminiModelGateway(
            client=client,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
            observability=observability,
            capture_content=settings.langfuse_capture_content,
        ),
    )
