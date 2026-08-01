from contextlib import asynccontextmanager

import pytest

from app.services.events import PostgresProductEventStore
from app.services.feedback import PostgresFeedbackStore


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.calls.append((query, params))


class FakePool:
    def __init__(self) -> None:
        self.connection_value = FakeConnection()

    @asynccontextmanager
    async def connection(self):  # type: ignore[no-untyped-def]
        yield self.connection_value


@pytest.mark.asyncio
async def test_postgres_feedback_and_product_events_are_inserted() -> None:
    pool = FakePool()
    feedback = PostgresFeedbackStore(pool)  # type: ignore[arg-type]
    events = PostgresProductEventStore(pool)  # type: ignore[arg-type]

    await feedback.record(
        session_id="session",
        request_id="request",
        destination_id="istanbul",
        value="up",
        comment=None,
    )
    await events.record_travel_link_opened(
        session_id="session",
        request_id="request",
        destination_id="istanbul",
        rank=1,
        provider="aviasales",
        link_kind="flight",
    )

    assert "INSERT INTO app.feedback_events" in pool.connection_value.calls[0][0]
    assert "INSERT INTO app.product_events" in pool.connection_value.calls[1][0]
