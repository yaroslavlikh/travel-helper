"""Stable domain contracts and JSON-serializable LangGraph state."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

DestinationScope = Literal["domestic", "international", "any"]
HeatTolerance = Literal["low", "medium", "high"]
VisaWillingness = Literal["no_visa", "evisa_ok", "visa_ok", "any"]
AmbiguityPriority = Literal["P0", "P1", "P2"]


class DomainModel(BaseModel):
    """Forbid accidental fields at API and provider boundaries."""

    model_config = ConfigDict(extra="forbid")


class TravelRequest(DomainModel):
    """Only explicitly known user constraints are populated; unknowns stay ``None``."""

    origin_city: str | None = None
    origin_country: str | None = None
    citizenship: str | None = None
    destination_scope: DestinationScope | None = None
    date_from: date | None = None
    date_to: date | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    duration_nights_min: int | None = Field(default=None, ge=1)
    duration_nights_max: int | None = Field(default=None, ge=1)
    date_flexibility_days: int | None = Field(default=None, ge=0)
    adults: int | None = Field(default=None, ge=1)
    children: int | None = Field(default=None, ge=0)
    budget_total_rub: int | None = Field(default=None, ge=1)
    budget_strict: bool | None = None
    trip_style: list[str] = Field(default_factory=list)
    sea_required: bool = False
    heat_tolerance: HeatTolerance | None = None
    preferred_max_temperature_c: float | None = None
    visa_willingness: VisaWillingness | None = None
    max_flight_duration_hours: float | None = Field(default=None, gt=0)
    baggage_required: bool | None = None
    preferences: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    raw_query: str = Field(min_length=1)


class Ambiguity(DomainModel):
    """A missing or uncertain constraint with an explicit product policy."""

    field: str
    priority: AmbiguityPriority
    reason: str
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    default_value: Any | None = None
    can_use_default: bool = False


class SourceEvidence(DomainModel):
    """Traceable source payload for any fact presented to a user."""

    source_type: str
    title: str
    url: str
    provider: str
    retrieved_at: datetime
    excerpt: str
    confidence: float = Field(ge=0, le=1)


class DestinationCandidate(DomainModel):
    """Normalized travel option; estimate fields are ranges, never fabricated point prices."""

    destination_id: str
    country: str
    city_or_region: str
    nearest_airport: str | None = None
    estimated_flight_cost_rub_min: int | None = Field(default=None, ge=0)
    estimated_flight_cost_rub_max: int | None = Field(default=None, ge=0)
    estimated_hotel_cost_rub_min: int | None = Field(default=None, ge=0)
    estimated_hotel_cost_rub_max: int | None = Field(default=None, ge=0)
    estimated_other_cost_rub: int | None = Field(default=None, ge=0)
    estimated_total_cost_rub_min: int | None = Field(default=None, ge=0)
    estimated_total_cost_rub_max: int | None = Field(default=None, ge=0)
    expected_temperature_c: float | None = None
    expected_sea_temperature_c: float | None = None
    precipitation_risk: str | None = None
    flight_duration_hours: float | None = Field(default=None, gt=0)
    transfers_count: int | None = Field(default=None, ge=0)
    entry_requirements: str | None = None
    visa_complexity: str | None = None
    destination_tags: list[str] = Field(default_factory=list)
    matched_preferences: list[str] = Field(default_factory=list)
    violated_preferences: list[str] = Field(default_factory=list)
    sources: list[SourceEvidence] = Field(default_factory=list)
    data_confidence: float | None = Field(default=None, ge=0, le=1)
    retrieved_at: datetime | None = None


class ScoredDestination(DomainModel):
    """Deterministic score output with transparent reasons and assumptions."""

    candidate: DestinationCandidate
    passed_hard_filters: bool
    rejected_reasons: list[str] = Field(default_factory=list)
    total_score: float = Field(ge=0, le=100)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    explanation: str


class PlannerState(TypedDict, total=False):
    """JSON-serializable checkpoint state; runtime clients never enter this object."""

    request_id: str
    session_id: str
    raw_query: str
    answers: dict[str, Any]
    parsed_request: dict[str, Any]
    ambiguities: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    assumptions: list[str]
    status: Literal["received", "needs_clarification", "ready_for_search"]
    warnings: list[str]
