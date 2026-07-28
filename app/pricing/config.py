"""Versioned pricing-core parameters without provider assumptions."""

from pydantic import BaseModel, ConfigDict, Field


class PricingCoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "pricing-core-v1"
    max_date_scenarios: int = Field(default=60, ge=1, le=500)
    expected_scenario_basket: int = Field(default=3, ge=1, le=20)
    safe_scenario_basket: int = Field(default=5, ge=1, le=20)
    safe_percentile: int = Field(default=75, ge=1, le=100)


PRICING_CORE_CONFIG = PricingCoreConfig()


class FxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "cbr-fx-v1"
    cache_ttl_seconds: int = Field(default=86_400, ge=1)
    stale_fallback_seconds: int = Field(default=259_200, ge=1)
    max_response_bytes: int = Field(default=1_000_000, ge=1)


FX_CONFIG = FxConfig()
