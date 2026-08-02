"""No-token pricing adapters that never manufacture an offer."""

from __future__ import annotations

from datetime import datetime

from app.pricing.models import (
    DateScenario,
    FlightOffer,
    FlightPriceSignal,
    PricingRequest,
    ScenarioBatch,
    StayOffer,
)


class UnavailableFlightPriceProvider:
    provider_name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def search(
        self, request: PricingRequest, scenario: DateScenario
    ) -> tuple[FlightOffer, ...]:
        return ()


class UnavailableStayPriceProvider:
    provider_name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def search(
        self, request: PricingRequest, scenario: DateScenario
    ) -> tuple[StayOffer, ...]:
        return ()


class UnavailableCachedFlightDiscovery:
    """Explicit cached-source fallback; it never manufactures a price signal."""

    provider_name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def search(
        self, request: PricingRequest, batch: ScenarioBatch, *, now: datetime
    ) -> tuple[FlightPriceSignal, ...]:
        return ()
