"""Hard filters that make every rejected option auditable."""

from __future__ import annotations

from app.domain.models import DestinationCandidate, TravelRequest
from app.services.destination_semantics import (
    matches_explicit_avoid,
    matches_requested_regions,
)


def hard_filter_reasons(candidate: DestinationCandidate, request: TravelRequest) -> list[str]:
    """Return machine-readable human-facing reasons for every hard mismatch."""

    reasons: list[str] = []
    if request.destination_scope == "domestic" and "domestic" not in candidate.destination_tags:
        reasons.append("destination_scope_mismatch")
    if (
        request.destination_scope == "international"
        and "international" not in candidate.destination_tags
    ):
        reasons.append("destination_scope_mismatch")
    if request.sea_required and "sea" not in candidate.destination_tags:
        reasons.append("sea_required")
    if not matches_requested_regions(candidate, request):
        reasons.append("preferred_region_mismatch")
    if matches_explicit_avoid(candidate, request):
        reasons.append("explicitly_avoided")
    if (
        request.budget_strict
        and request.budget_total_rub is not None
        and candidate.estimated_total_cost_rub_max is not None
        and candidate.estimated_total_cost_rub_max > request.budget_total_rub
    ):
        reasons.append("strict_budget_exceeded")
    if (
        request.max_flight_duration_hours is not None
        and candidate.flight_duration_hours is not None
        and candidate.flight_duration_hours > request.max_flight_duration_hours
    ):
        reasons.append("max_flight_duration_exceeded")
    if request.visa_willingness == "no_visa" and candidate.visa_complexity not in {
        "none",
        "unknown",
    }:
        reasons.append("visa_requirement_incompatible")
    temperature_limit = request.preferred_max_temperature_c
    if request.heat_tolerance == "low" and temperature_limit is None:
        temperature_limit = 30
    if (
        temperature_limit is not None
        and candidate.expected_temperature_c is not None
        and candidate.expected_temperature_c > temperature_limit
    ):
        reasons.append("temperature_limit_exceeded")
    return reasons
