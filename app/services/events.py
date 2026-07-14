"""Minimal anonymous product-event storage for local MVP analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class TravelLinkOpenedEvent:
    """A provider CTA click without personal content or arbitrary URLs."""

    session_id: str
    request_id: str
    destination_id: str
    rank: int
    provider: Literal["aviasales", "yandex_travel"]
    link_kind: Literal["flight", "stay"]
    date_mode: Literal["exact", "derived"] | None
    created_at: datetime


@dataclass(slots=True)
class ProductEventStore:
    """In-memory MVP store; production will use the documented events table."""

    travel_link_events: list[TravelLinkOpenedEvent] = field(default_factory=list)

    def record_travel_link_opened(
        self,
        *,
        session_id: str,
        request_id: str,
        destination_id: str,
        rank: int,
        provider: Literal["aviasales", "yandex_travel"],
        link_kind: Literal["flight", "stay"],
        date_mode: Literal["exact", "derived"] | None = None,
    ) -> None:
        self.travel_link_events.append(
            TravelLinkOpenedEvent(
                session_id=session_id,
                request_id=request_id,
                destination_id=destination_id,
                rank=rank,
                provider=provider,
                link_kind=link_kind,
                date_mode=date_mode,
                created_at=datetime.now(UTC),
            )
        )
