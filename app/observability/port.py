"""Vendor-neutral observability boundary used by graph nodes and providers."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any, Protocol


class ObservabilityPort(Protocol):
    """The narrow tracing surface needed by the application."""

    @property
    def backend_name(self) -> str: ...

    def span(self, name: str, **metadata: Any) -> AbstractContextManager[None]: ...


class NoopObservability:
    """Safe default when Langfuse is not configured or intentionally deferred."""

    @property
    def backend_name(self) -> str:
        return "noop"

    def span(self, name: str, **metadata: Any) -> AbstractContextManager[None]:
        del name, metadata
        return nullcontext()
