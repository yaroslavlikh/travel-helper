"""Public API schemas; internal checkpoints remain private."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Ambiguity, PlanningConfidence, ScoredDestination, TravelRequest
from app.places.models import PlaceSearchResult


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecommendInput(ApiModel):
    query: str = Field(min_length=2, max_length=4_000)
    session_id: str | None = Field(default=None, min_length=8, max_length=128)
    answers: dict[str, Any] | None = None


class FeedbackInput(ApiModel):
    session_id: str = Field(min_length=8, max_length=128)
    request_id: str = Field(min_length=8, max_length=128)
    destination_id: str | None = Field(default=None, max_length=128)
    value: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1_000)


class TravelLinkOpenedInput(ApiModel):
    session_id: str = Field(min_length=8, max_length=128)
    request_id: str = Field(min_length=8, max_length=128)
    destination_id: str = Field(min_length=1, max_length=128)
    rank: int = Field(ge=1, le=100)
    provider: Literal["aviasales", "yandex_travel"]
    link_kind: Literal["flight", "stay"]


class DestinationChatInput(ApiModel):
    session_id: str = Field(min_length=8, max_length=128)
    destination_id: str = Field(min_length=1, max_length=128)
    recommendation_snapshot_id: str | None = Field(default=None, min_length=8, max_length=128)
    query: str = Field(min_length=2, max_length=4_000)


class DestinationChatResponse(ApiModel):
    status: Literal["completed"]
    request_id: str
    session_id: str
    subthread_id: str
    destination_id: str
    destination_name: str
    assistant_message: str
    quick_replies: list[str] = Field(default_factory=list)
    places: list[PlaceSearchResult] = Field(default_factory=list)
    place_retrieval_id: str | None = None
    place_ranking_version: str | None = None
    proposed_trip_change: str | None = None
    message_count: int
    turn_index: int
    warnings: list[str] = Field(default_factory=list)
    pricing_scenario_id: str | None = None
    pricing_changed: bool = False
    previous_total_rub: int | None = None
    current_total_rub: int | None = None
    refresh_status: Literal["not_requested", "updated", "unchanged", "unavailable"] = (
        "not_requested"
    )


class NeedsClarificationResponse(ApiModel):
    status: Literal["needs_clarification"]
    request_id: str
    session_id: str
    parsed_request: TravelRequest
    questions: list[Ambiguity]
    assumptions: list[str]
    planning_confidence: PlanningConfidence
    warnings: list[str] = Field(default_factory=list)
    turn_kind: Literal["initial", "clarification", "refinement"]
    assistant_message: str
    changed_fields: list[str] = Field(default_factory=list)


class PartialRecommendationResponse(ApiModel):
    status: Literal["partial"]
    request_id: str
    session_id: str
    parsed_request: TravelRequest
    assumptions: list[str]
    planning_confidence: PlanningConfidence
    next_best_question: Ambiguity | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str]
    turn_kind: Literal["initial", "clarification", "refinement"]
    assistant_message: str
    changed_fields: list[str] = Field(default_factory=list)


class CompletedRecommendationResponse(ApiModel):
    status: Literal["completed"]
    request_id: str
    session_id: str
    parsed_request: TravelRequest
    assumptions: list[str]
    planning_confidence: PlanningConfidence
    next_best_question: Ambiguity | None = None
    recommendations: list[ScoredDestination]
    warnings: list[str]
    turn_kind: Literal["initial", "clarification", "refinement"]
    assistant_message: str
    changed_fields: list[str] = Field(default_factory=list)


RecommendationResponse = Annotated[
    NeedsClarificationResponse | PartialRecommendationResponse | CompletedRecommendationResponse,
    Field(discriminator="status"),
]
