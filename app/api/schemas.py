"""Public API schemas; internal checkpoints remain private."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Ambiguity, TravelRequest


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecommendInput(ApiModel):
    query: str = Field(min_length=2, max_length=4_000)
    session_id: str | None = Field(default=None, min_length=8, max_length=128)
    answers: dict[str, Any] | None = None


class NeedsClarificationResponse(ApiModel):
    status: Literal["needs_clarification"]
    request_id: str
    session_id: str
    parsed_request: TravelRequest
    questions: list[Ambiguity]
    assumptions: list[str]


class PartialRecommendationResponse(ApiModel):
    status: Literal["partial"]
    request_id: str
    session_id: str
    parsed_request: TravelRequest
    assumptions: list[str]
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str]


RecommendationResponse = Annotated[
    NeedsClarificationResponse | PartialRecommendationResponse,
    Field(discriminator="status"),
]
