"""Langfuse adapter isolated behind the application's observability port."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse

from app.core.config import Settings
from app.observability.port import ObservabilityPort


class LangfuseObservability:
    """Emit best-effort spans without exposing credentials to domain code."""

    def __init__(self, client: Langfuse) -> None:
        self._client = client

    @property
    def backend_name(self) -> str:
        return "langfuse"

    @contextmanager
    def span(self, name: str, **metadata: Any) -> Iterator[None]:
        with self._client.start_as_current_observation(
            as_type="span", name=name, metadata=metadata
        ):
            yield

    def shutdown(self) -> None:
        self._client.shutdown()


def create_observability(settings: Settings) -> ObservabilityPort:
    """Create the configured exporter, otherwise retain the existing no-op behavior."""

    if (
        not settings.langfuse_is_configured
        or settings.langfuse_public_key is None
        or settings.langfuse_secret_key is None
        or settings.langfuse_base_url is None
    ):
        from app.observability.port import NoopObservability

        return NoopObservability()
    return LangfuseObservability(
        Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            environment=settings.app_env,
        )
    )
