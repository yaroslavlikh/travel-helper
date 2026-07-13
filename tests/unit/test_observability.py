from contextlib import contextmanager
from typing import Any, cast

import pytest

from app.observability.langfuse import LangfuseObservability


class FakeObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class FakeObservationContext:
    def __init__(self, observation: FakeObservation) -> None:
        self.observation = observation

    def __enter__(self) -> FakeObservation:
        return self.observation

    def __exit__(self, *_: Any) -> None:
        return None


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.observations: list[FakeObservation] = []
        self.flush_count = 0

    def start_as_current_observation(self, **kwargs: Any) -> FakeObservationContext:
        observation = FakeObservation()
        self.calls.append(kwargs)
        self.observations.append(observation)
        return FakeObservationContext(observation)

    def flush(self) -> None:
        self.flush_count += 1

    def shutdown(self) -> None:
        return None


def test_trace_propagates_session_and_flushes_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeLangfuseClient()
    propagated: list[dict[str, Any]] = []

    @contextmanager
    def fake_propagate_attributes(**kwargs: Any):  # type: ignore[no-untyped-def]
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(
        "app.observability.langfuse.propagate_attributes",
        fake_propagate_attributes,
    )
    observability = LangfuseObservability(cast(Any, client), flush_on_trace=True)

    with observability.trace(
        "recommendation_pipeline",
        session_id="chat-session-123",
        input={"query": "Хочу на море"},
        metadata={"turnid": "turn-1", "turnkind": "initial"},
        tags=["travel-chat", "initial"],
    ) as trace:
        trace.update(output={"status": "needs_clarification"})

    assert client.calls[0]["as_type"] == "agent"
    assert client.calls[0]["name"] == "recommendation_pipeline"
    assert propagated == [
        {
            "session_id": "chat-session-123",
            "trace_name": "recommendation_pipeline",
            "metadata": {"turnid": "turn-1", "turnkind": "initial"},
            "tags": ["travel-chat", "initial"],
        }
    ]
    assert client.observations[0].updates[0]["output"] == {"status": "needs_clarification"}
    assert client.flush_count == 1


def test_generation_is_a_typed_child_observation() -> None:
    client = FakeLangfuseClient()
    observability = LangfuseObservability(cast(Any, client), flush_on_trace=False)

    with observability.generation(
        "parse_user_query",
        model="gemini-3.1-flash-lite",
        input={"schema": "TravelRequestPatch"},
        metadata={"operation": "parse_user_query"},
    ) as generation:
        generation.update(
            output={"validated": True},
            usage_details={"input": 10, "output": 4, "total": 14},
        )

    assert client.calls[0]["as_type"] == "generation"
    assert client.calls[0]["model"] == "gemini-3.1-flash-lite"
    assert client.observations[0].updates[0]["usage_details"] == {
        "input": 10,
        "output": 4,
        "total": 14,
    }
