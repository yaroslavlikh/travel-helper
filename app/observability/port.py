"""Vendor-neutral observability boundary used by graph nodes and providers."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any, Literal, Protocol

ObservationLevel = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]


class ObservationHandle(Protocol):
    """Mutable observation result available without exposing a vendor object."""

    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel | None = None,
        status_message: str | None = None,
        usage_details: dict[str, int] | None = None,
    ) -> None: ...


class ObservabilityPort(Protocol):
    """The narrow tracing surface needed by the application."""

    @property
    def backend_name(self) -> str: ...

    def trace(
        self,
        name: str,
        *,
        session_id: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> AbstractContextManager[ObservationHandle]: ...

    def span(self, name: str, **metadata: Any) -> AbstractContextManager[ObservationHandle]: ...

    def generation(
        self,
        name: str,
        *,
        model: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[ObservationHandle]: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


class NoopObservation:
    """Discard observation updates while preserving the same control flow."""

    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: ObservationLevel | None = None,
        status_message: str | None = None,
        usage_details: dict[str, int] | None = None,
    ) -> None:
        del output, metadata, level, status_message, usage_details


class NoopObservability:
    """Safe default when Langfuse is not configured or intentionally deferred."""

    @property
    def backend_name(self) -> str:
        return "noop"

    def trace(
        self,
        name: str,
        *,
        session_id: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> AbstractContextManager[ObservationHandle]:
        del name, session_id, input, metadata, tags
        return nullcontext(NoopObservation())

    def span(self, name: str, **metadata: Any) -> AbstractContextManager[ObservationHandle]:
        del name, metadata
        return nullcontext(NoopObservation())

    def generation(
        self,
        name: str,
        *,
        model: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[ObservationHandle]:
        del name, model, input, metadata
        return nullcontext(NoopObservation())

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None
