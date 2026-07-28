"""Official FX-rate provider port."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.pricing.models import FxRateTable


class FxRateProvider(Protocol):
    async def get_rates(self, on_date: date | None = None) -> FxRateTable: ...
