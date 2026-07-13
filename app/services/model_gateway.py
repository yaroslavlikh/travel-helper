"""Provider-neutral LLM gateway contract; concrete providers are deliberately deferred."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.core.config import Settings

StructuredResult = TypeVar("StructuredResult", bound=BaseModel)


class ModelGateway(Protocol):
    """Minimal capability contract consumed by future extraction and explanation nodes."""

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


@dataclass(frozen=True, slots=True)
class DisabledModelGateway:
    """Explicit failure mode until a provider adapter is selected and installed."""

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
        raise RuntimeError(self.reason)


def create_model_gateway(settings: Settings) -> ModelGateway:
    """Build one process-scoped model gateway during FastAPI lifespan startup."""

    if settings.model_is_configured:
        return DisabledModelGateway(
            "LLM configuration is present, but its provider adapter has not been selected yet"
        )
    return DisabledModelGateway(
        "No LLM provider is configured; application is running in demo-ready mode"
    )
