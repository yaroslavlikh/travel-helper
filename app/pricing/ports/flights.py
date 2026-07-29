"""Cached flight discovery and future live-pricing ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.pricing.models import (
    DateScenario,
    FlightOffer,
    FlightPriceSignal,
    PricingRequest,
    ScenarioBatch,
)


class CachedFlightDiscovery(Protocol):
    async def search(
        self,
        request: PricingRequest,
        batch: ScenarioBatch,
        *,
        now: datetime,
    ) -> tuple[FlightPriceSignal, ...]: ...


class FlightPriceProvider(Protocol):
    """Provider-neutral complete-flight search for one coherent scenario."""

    provider_name: str

    async def search(
        self,
        request: PricingRequest,
        scenario: DateScenario,
    ) -> tuple[FlightOffer, ...]: ...


# Compatibility name for adapters introduced before fixture/unavailable modes existed.
LiveFlightProvider = FlightPriceProvider
