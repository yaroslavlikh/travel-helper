"""Versioned pricing-core parameters without provider assumptions."""

from decimal import Decimal

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


class CachedFlightConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "aviasales-data-v1"
    max_response_bytes: int = Field(default=2_000_000, ge=1)
    full_pricing_scenario_limit: int = Field(default=12, ge=1, le=60)
    cheapest_scenario_count: int = Field(default=6, ge=1, le=20)
    scenarios_per_month_third: int = Field(default=2, ge=1, le=10)
    max_route_pairs: int = Field(default=8, ge=1, le=64)
    page_limit: int = Field(default=30, ge=1, le=100)


CACHED_FLIGHT_CONFIG = CachedFlightConfig()


class FlightAggregationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "flight-aggregation-v1"
    bait_price_ratio: Decimal = Field(default=Decimal("0.55"), gt=0, lt=1)
    bait_median_count: int = Field(default=10, ge=1, le=50)
    expected_offer_count: int = Field(default=3, ge=1, le=20)
    safe_offer_count: int = Field(default=5, ge=1, le=20)
    safe_percentile: int = Field(default=75, ge=1, le=100)


FLIGHT_AGGREGATION_CONFIG = FlightAggregationConfig()


class StayAggregationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "stay-aggregation-v1"
    outlier_ratio: Decimal = Field(default=Decimal("0.60"), gt=0, lt=1)
    outlier_median_count: int = Field(default=10, ge=1, le=50)
    expected_offer_count: int = Field(default=5, ge=1, le=20)
    safe_offer_count: int = Field(default=10, ge=1, le=30)
    safe_percentile: int = Field(default=75, ge=1, le=100)


STAY_AGGREGATION_CONFIG = StayAggregationConfig()


class DailyCostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "daily-costs-v1"
    infant_food_factor: Decimal = Decimal("0.20")
    child_food_factors: tuple[tuple[int, int, Decimal], ...] = (
        (3, 6, Decimal("0.45")),
        (7, 11, Decimal("0.65")),
        (12, 17, Decimal("0.85")),
    )
    economy_transit_rides_per_day: int = Field(default=2, ge=0)
    standard_transit_rides_per_day: int = Field(default=3, ge=0)
    comfort_transit_rides_per_day: int = Field(default=3, ge=0)


DAILY_COST_CONFIG = DailyCostConfig()
