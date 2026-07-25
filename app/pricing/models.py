"""Public, serializable pricing contracts. Values are always for the whole trip party."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PricingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyRange(PricingModel):
    currency: Literal["RUB"] = "RUB"
    low: int = Field(ge=0)
    expected: int = Field(ge=0)
    high: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> MoneyRange:
        if not self.low <= self.expected <= self.high:
            raise ValueError("money range must satisfy low <= expected <= high")
        return self


class CostSourceSummary(PricingModel):
    provider: str
    source_kind: Literal["live", "cached", "modelled", "manual", "derived"]
    observed_at: datetime
    valid_until: datetime | None = None
    url: str | None = None
    confidence: float = Field(ge=0, le=1)


class CostComponentEstimate(PricingModel):
    component: Literal["flight", "stay", "daily", "required", "recommended", "contingency"]
    amount: MoneyRange
    status: Literal["available", "partial", "missing", "stale"] = "available"
    included_items: list[str] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sources: list[CostSourceSummary] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


BudgetFitStatus = Literal[
    "confidently_within", "likely_within", "possible_with_savings", "over_budget", "unknown"
]


class TripCostEstimate(PricingModel):
    pricing_snapshot_id: str
    pricing_version: str
    request_hash: str
    scenario_summary: str
    party_size: int = Field(ge=1)
    nights_min: int = Field(ge=1)
    nights_max: int = Field(ge=1)
    date_mode: Literal["exact", "flex_window", "month", "unknown"]
    floor_total_rub: int = Field(ge=0)
    expected_total_rub: int = Field(ge=0)
    safe_total_rub: int = Field(ge=0)
    budget_fit: BudgetFitStatus
    budget_gap_expected_rub: int | None = None
    budget_gap_safe_rub: int | None = None
    components: list[CostComponentEstimate]
    included_items: list[str]
    excluded_items: list[str]
    assumptions: list[str]
    warnings: list[str]
    confidence: float = Field(ge=0, le=1)
    confidence_label: Literal["high", "medium", "low", "insufficient"]
    calculated_at: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def totals_are_ordered(self) -> TripCostEstimate:
        if not self.floor_total_rub <= self.expected_total_rub <= self.safe_total_rub:
            raise ValueError("trip total must satisfy floor <= expected <= safe")
        return self


class PriceBreakdownRow(PricingModel):
    label: str
    value: str


class PriceCardView(PricingModel):
    headline: str
    subtitle: str
    floor_label: str | None = None
    budget_status_label: str
    freshness_label: str
    confidence_label: str
    breakdown_rows: list[PriceBreakdownRow]
    included_items: list[str]
    excluded_items: list[str]
    warnings: list[str]
