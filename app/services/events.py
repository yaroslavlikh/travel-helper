"""Privacy-bounded product event persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True, slots=True)
class TravelLinkOpenedEvent:
    session_id: str
    request_id: str
    destination_id: str
    rank: int
    provider: Literal["aviasales", "yandex_travel"]
    link_kind: Literal["flight", "stay"]
    created_at: datetime


class ProductEventRepository(Protocol):
    async def record_travel_link_opened(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str,
        rank: int,
        provider: Literal["aviasales", "yandex_travel"],
        link_kind: Literal["flight", "stay"],
    ) -> None: ...


@dataclass(slots=True)
class ProductEventStore:
    """Isolated in-memory store for development and tests."""

    travel_link_events: list[TravelLinkOpenedEvent] = field(default_factory=list)

    async def record_travel_link_opened(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str,
        rank: int,
        provider: Literal["aviasales", "yandex_travel"],
        link_kind: Literal["flight", "stay"],
    ) -> None:
        self.travel_link_events.append(
            TravelLinkOpenedEvent(
                session_id, request_id, destination_id, rank, provider, link_kind, datetime.now(UTC)
            )
        )


class PostgresProductEventStore:
    """Append-only provider CTA events in the application schema."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[Any]]) -> None:
        self._pool = pool

    async def record_travel_link_opened(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str,
        rank: int,
        provider: Literal["aviasales", "yandex_travel"],
        link_kind: Literal["flight", "stay"],
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO app.product_events
                (id, session_id, request_id, destination_id, rank, provider, link_kind)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (uuid4(), session_id, request_id, destination_id, rank, provider, link_kind),
            )
