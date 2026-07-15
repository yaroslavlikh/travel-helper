"""Typed public contracts for canonical place retrieval."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PlaceSearchQuery(BaseModel):
    """Constraints accepted by the bounded one-city places search."""

    model_config = ConfigDict(extra="forbid")

    destination: str = Field(default="istanbul", min_length=2, max_length=80)
    query: str = Field(default="", max_length=500)
    include_categories: list[str] = Field(default_factory=list, max_length=10)
    exclude_categories: list[str] = Field(default_factory=list, max_length=10)
    budget: Literal["free", "budget", "any"] = "any"
    indoor: bool | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_meters: int | None = Field(default=None, ge=50, le=50_000)
    visit_minutes: int | None = Field(default=None, ge=10, le=1_440)
    accessibility_required: bool = False
    limit: int = Field(default=10, ge=1, le=30)
    ranking_version: str = Field(default="istanbul-hybrid-v1", max_length=80)


class PlaceImage(BaseModel):
    image_url: str
    source_url: str
    license: str
    attribution: str


class PlaceSearchResult(BaseModel):
    place_id: UUID
    name: str
    destination: str
    latitude: float
    longitude: float
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    image: PlaceImage | None = None
    scores: dict[str, float]
    reasons: list[str]
    freshness_at: datetime | None = None
    ranking_version: str


class PlaceSearchResponse(BaseModel):
    retrieval_id: UUID
    ranking_version: str
    results: list[PlaceSearchResult]
    warnings: list[str] = Field(default_factory=list)


class PlaceEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "place_impression",
        "place_opened",
        "place_saved",
        "place_hidden",
        "place_selected",
        "external_link_clicked",
        "plan_regenerated",
        "place_feedback_submitted",
    ]
    session_id: str = Field(min_length=8, max_length=128)
    place_id: UUID | None = None
    retrieval_id: UUID | None = None
    position: int | None = Field(default=None, ge=1, le=100)
    ranking_version: str | None = Field(default=None, max_length=80)
    experiment_variant: str | None = Field(default=None, max_length=80)
    filters: dict[str, str | int | float | bool | list[str] | None] = Field(default_factory=dict)
