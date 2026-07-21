"""Stable domain contracts and JSON-serializable LangGraph state."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

DestinationScope = Literal["domestic", "international", "any"]
HeatTolerance = Literal["low", "medium", "high"]
VisaWillingness = Literal["no_visa", "evisa_ok", "visa_ok", "any"]
AmbiguityPriority = Literal["P0", "P1", "P2"]
ClarificationTopic = Literal[
    "departure",
    "timing",
    "geography",
    "party",
    "budget",
    "travel_friction",
    "trip_style",
]
UncertaintyImpact = Literal["high", "medium", "low"]
PlanningConfidenceLevel = Literal["high", "medium", "low"]


class DomainModel(BaseModel):
    """Forbid accidental fields at API and provider boundaries."""

    model_config = ConfigDict(extra="forbid")


class TravelRequestPatch(DomainModel):
    """Structured fields an LLM may extract; unknown values must remain ``None``."""

    origin_city: str | None = None
    origin_country: str | None = None
    citizenship: str | None = None
    destination_scope: DestinationScope | None = None
    # Exact trip boundaries: outbound and return dates when both are confirmed.
    date_from: date | None = None
    date_to: date | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    # A range of possible outbound days, distinct from a return date.
    departure_window_from: date | None = None
    departure_window_to: date | None = None
    # Kept for compatibility with already persisted local chat snapshots.
    flight_departure_date: date | None = None
    flight_return_date: date | None = None
    flight_one_way: bool | None = None
    duration_nights_min: int | None = Field(default=None, ge=1)
    duration_nights_max: int | None = Field(default=None, ge=1)
    date_flexibility_days: int | None = Field(default=None, ge=0)
    adults: int | None = Field(default=None, ge=1)
    children: int | None = Field(default=None, ge=0)
    infants: int | None = Field(default=None, ge=0)
    budget_total_rub: int | None = Field(default=None, ge=1)
    budget_strict: bool | None = None
    trip_style: list[str] = Field(default_factory=list)
    sea_required: bool | None = None
    heat_tolerance: HeatTolerance | None = None
    preferred_max_temperature_c: float | None = None
    visa_willingness: VisaWillingness | None = None
    max_flight_duration_hours: float | None = Field(default=None, gt=0)
    baggage_required: bool | None = None
    preferences: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)


class TravelRequest(TravelRequestPatch):
    """Validated planning request with the immutable original user query."""

    raw_query: str = Field(min_length=1)
    sea_required: bool = False


class TravelRequestRevision(DomainModel):
    """Explicit changes for one follow-up turn; null values never erase known state."""

    changes: TravelRequestPatch = Field(default_factory=TravelRequestPatch)
    clear_fields: list[str] = Field(default_factory=list)


class Ambiguity(DomainModel):
    """A missing constraint, grouped for natural-language dialogue and policy."""

    field: str
    topic: ClarificationTopic
    priority: AmbiguityPriority
    reason: str
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    default_value: Any | None = None
    can_use_default: bool = False


class PlanningUncertainty(DomainModel):
    """An unresolved condition that changes the confidence of a usable shortlist."""

    field: str
    impact: UncertaintyImpact
    effect: str


class PlanningConfidence(DomainModel):
    """Coverage of the travel plan, distinct from evidence freshness or source confidence."""

    score: int = Field(ge=0, le=100)
    level: PlanningConfidenceLevel
    summary: str
    uncertainties: list[PlanningUncertainty] = Field(default_factory=list)


class SourceEvidence(DomainModel):
    """Traceable source payload for any fact presented to a user."""

    source_type: str
    title: str
    url: str
    provider: str
    retrieved_at: datetime
    excerpt: str
    confidence: float = Field(ge=0, le=1)


class DestinationImage(DomainModel):
    """Credited real-place image; generated imagery is not used as destination evidence."""

    url: str
    source_url: str
    alt: str
    credit: str


class DestinationPlace(DomainModel):
    """Concrete neighborhood or sight that helps a user understand the destination."""

    name: str
    category: Literal["area", "beach", "sight", "nature"]
    description: str
    url: str


class ExternalTravelLink(DomainModel):
    """Navigation link, never evidence of current availability or price."""

    title: str
    provider: str
    category: Literal["flight", "stay", "activity", "package_tour"]
    url: str


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
    image: DestinationImage | None = None
    highlights: list[DestinationPlace] = Field(default_factory=list)
    stay_areas: list[str] = Field(default_factory=list)
    external_links: list[ExternalTravelLink] = Field(default_factory=list)
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
    state: Literal["ELIGIBLE", "CONDITIONAL", "EXCLUDED", "FALLBACK"] = "ELIGIBLE"
    final_score: int = Field(default=0, ge=0, le=100)
    preliminary_score: int | None = Field(default=None, ge=0, le=100)
    ranking_version: str = "ranking-v1"
    uncertainty_penalty: float = Field(default=0, ge=0, le=15)
    risk_penalty: float = Field(default=0, ge=0, le=25)
    caps_applied: list[str] = Field(default_factory=list)
    hard_checks: dict[str, Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]] = Field(
        default_factory=dict
    )
    rank_before_diversity: int | None = Field(default=None, ge=1)
    rank_after_diversity: int | None = Field(default=None, ge=1)


class DestinationThreadMessage(DomainModel):
    """One bounded message in a destination-specific subthread."""

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=4_000)


class DestinationChatModelReply(DomainModel):
    """Structured model output that cannot mutate the main trip by itself."""

    answer: str = Field(min_length=1, max_length=2_000)
    quick_replies: list[str] = Field(default_factory=list, max_length=3)
    proposed_trip_change: str | None = Field(default=None, max_length=500)


class PlannerState(TypedDict, total=False):
    """JSON-serializable checkpoint state; runtime clients never enter this object."""

    request_id: str
    session_id: str
    raw_query: str
    answers: dict[str, Any]
    previous_request: dict[str, Any]
    parsed_request: dict[str, Any]
    query_history: list[str]
    question_history: list[dict[str, Any]]
    destination_threads: dict[str, dict[str, Any]]
    turn_count: int
    ambiguities: list[dict[str, Any]]
    questions: list[dict[str, Any]]
    assumptions: list[str]
    planning_confidence: dict[str, Any]
    next_best_question: dict[str, Any] | None
    status: Literal["received", "needs_clarification", "ready_for_search"]
    warnings: list[str]
