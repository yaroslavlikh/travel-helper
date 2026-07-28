"""Exact currency arithmetic at the pricing boundary."""

from decimal import ROUND_HALF_UP, Decimal

from app.pricing.models import FxRateTable

RUBLE_QUANTUM = Decimal("0.01")


def convert_to_rub(amount: Decimal, currency: str, rates: FxRateTable) -> Decimal:
    """Convert a non-negative amount with official nominal-aware rates."""

    if amount < 0:
        raise ValueError("money amount cannot be negative")
    if currency.upper() == "RUB":
        return amount.quantize(RUBLE_QUANTUM, rounding=ROUND_HALF_UP)
    rate = rates.rate_for(currency)
    return (amount * rate.rub_per_unit).quantize(RUBLE_QUANTUM, rounding=ROUND_HALF_UP)
