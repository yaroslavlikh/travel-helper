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
