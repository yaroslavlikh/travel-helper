"""Cached flight discovery and future live-pricing ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.pricing.models import FlightPriceSignal, PricingRequest, ScenarioBatch


class CachedFlightDiscovery(Protocol):
    async def search(
        self,
        request: PricingRequest,
        batch: ScenarioBatch,
        *,
        now: datetime,
    ) -> tuple[FlightPriceSignal, ...]: ...
