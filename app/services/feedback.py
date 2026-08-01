"""Bounded feedback persistence for local tests and PostgreSQL deployments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True, slots=True)
class FeedbackEvent:
    session_id: str
    request_id: str
    destination_id: str | None
    value: Literal["up", "down"]
    comment: str | None
    created_at: datetime


class FeedbackRepository(Protocol):
    async def record(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str | None,
        value: Literal["up", "down"],
        comment: str | None,
    ) -> None: ...


@dataclass(slots=True)
class FeedbackStore:
    """Isolated in-memory store for development and tests."""

    events: list[FeedbackEvent] = field(default_factory=list)

    async def record(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str | None,
        value: Literal["up", "down"],
        comment: str | None,
    ) -> None:
        self.events.append(
            FeedbackEvent(session_id, request_id, destination_id, value, comment, datetime.now(UTC))
        )


class PostgresFeedbackStore:
    """Append-only anonymous feedback in the application schema."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[Any]]) -> None:
        self._pool = pool

    async def record(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str | None,
        value: Literal["up", "down"],
        comment: str | None,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """INSERT INTO app.feedback_events
                (id, session_id, request_id, destination_id, value, comment)
                VALUES (%s, %s, %s, %s, %s, %s)""",
                (uuid4(), session_id, request_id, destination_id, value, comment),
            )
