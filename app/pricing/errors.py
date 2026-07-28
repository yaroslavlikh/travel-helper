"""Typed pricing failures; callers may degrade without inventing a number."""


class PricingError(ValueError):
    """Base error for deterministic pricing."""


class PricingInvariantError(PricingError):
    """Normalized data violates a calculation invariant."""


class FxProviderError(PricingError):
    """Official FX data is unavailable or invalid."""
