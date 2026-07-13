"""Minimal anonymous feedback storage for the single-process demo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class FeedbackEvent:
    session_id: str
    request_id: str
    destination_id: str | None
    value: Literal["up", "down"]
    comment: str | None
    created_at: datetime


@dataclass(slots=True)
class FeedbackStore:
    """In-memory implementation; replace with SQLite/PostgreSQL before public deployment."""

    events: list[FeedbackEvent] = field(default_factory=list)

    def record(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str | None,
        value: Literal["up", "down"],
        comment: str | None,
    ) -> None:
        self.events.append(
            FeedbackEvent(
                session_id=session_id,
                request_id=request_id,
                destination_id=destination_id,
                value=value,
                comment=comment,
                created_at=datetime.now(UTC),
            )
        )
