"""Live stay provider port."""

from __future__ import annotations

from typing import Protocol

from app.pricing.models import DateScenario, PricingRequest, StayOffer


class LiveStayProvider(Protocol):
    async def search(
        self,
        request: PricingRequest,
        scenario: DateScenario,
    ) -> tuple[StayOffer, ...]: ...
