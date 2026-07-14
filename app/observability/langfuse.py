"""Langfuse adapter isolated behind the application's observability port."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse, propagate_attributes

from app.core.config import Settings
from app.observability.port import ObservabilityPort, ObservationHandle, ObservationLevel

logger = logging.getLogger(__name__)


class LangfuseObservation:
    """Small wrapper around the SDK v4 observation update surface."""

    def __init__(self, observation: Any) -> None:
        self._observation = observation

    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel | None = None,
        status_message: str | None = None,
        usage_details: dict[str, int] | None = None,
    ) -> None:
        try:
            self._observation.update(
                output=output,
                metadata=metadata,
                level=level,
                status_message=status_message,
                usage_details=usage_details,
            )
        except Exception:
            logger.exception("Langfuse observation update failed")


class LangfuseObservability:
    """Emit best-effort spans without exposing credentials to domain code."""

    def __init__(self, client: Langfuse, *, flush_on_trace: bool) -> None:
        self._client = client
        self._flush_on_trace = flush_on_trace

    @property
    def backend_name(self) -> str:
        return "langfuse"

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        session_id: str,
        trace_name: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[ObservationHandle]:
        try:
            with self._client.start_as_current_observation(
                as_type="agent",
                name=name,
                input=input,
                metadata=metadata,
            ) as observation:
                with propagate_attributes(
                    session_id=session_id,
                    trace_name=trace_name or name,
                    metadata={key: str(value) for key, value in (metadata or {}).items()},
                    tags=tags,
                ):
                    yield LangfuseObservation(observation)
        finally:
            if self._flush_on_trace:
                self.flush()

    @contextmanager
    def span(self, name: str, **metadata: Any) -> Iterator[ObservationHandle]:
        with self._client.start_as_current_observation(
            as_type="span", name=name, metadata=metadata
        ) as observation:
            yield LangfuseObservation(observation)

    @contextmanager
    def generation(
        self,
        name: str,
        *,
        model: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[ObservationHandle]:
        with self._client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input,
            metadata=metadata,
        ) as observation:
            yield LangfuseObservation(observation)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            logger.exception("Langfuse flush failed")

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception:
            logger.exception("Langfuse shutdown failed")


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
    client = Langfuse(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
        timeout=5,
    )
    try:
        authenticated = client.auth_check()
    except Exception:
        logger.exception("Langfuse authentication check failed; tracing disabled")
        client.shutdown()
        from app.observability.port import NoopObservability

        return NoopObservability()
    if not authenticated:
        logger.error("Langfuse credentials were rejected; tracing disabled")
        client.shutdown()
        from app.observability.port import NoopObservability

        return NoopObservability()
    logger.info("Langfuse authentication succeeded")
    return LangfuseObservability(client, flush_on_trace=settings.app_env == "development")
