"""Live stay provider port."""

from __future__ import annotations

from typing import Protocol

from app.pricing.models import DateScenario, PricingRequest, StayOffer


class StayPriceProvider(Protocol):
    """Provider-neutral complete-stay search for one coherent scenario."""

    provider_name: str

    async def search(
        self,
        request: PricingRequest,
        scenario: DateScenario,
    ) -> tuple[StayOffer, ...]: ...


# Compatibility name for adapters introduced before fixture/unavailable modes existed.
LiveStayProvider = StayPriceProvider
