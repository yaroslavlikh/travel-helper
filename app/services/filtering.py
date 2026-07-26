"""Hard filters that make every rejected option auditable."""

from __future__ import annotations

from typing import Literal

from app.domain.models import DestinationCandidate, TravelRequest
from app.services.destination_semantics import (
    matches_explicit_avoid,
    matches_requested_regions,
    requested_regions,
)

HardCheck = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]


def evaluate_hard_checks(
    candidate: DestinationCandidate, request: TravelRequest
) -> dict[str, HardCheck]:
    """Evaluate requested constraints without ever treating absent evidence as a pass."""

    checks: dict[str, HardCheck] = {}
    if request.destination_scope == "domestic" and "domestic" not in candidate.destination_tags:
        checks["destination_scope"] = "FAIL"
    elif (
        request.destination_scope == "international"
        and "international" not in candidate.destination_tags
    ):
        checks["destination_scope"] = "FAIL"
    elif request.destination_scope is not None:
        checks["destination_scope"] = "PASS"
    if request.sea_required and "sea" not in candidate.destination_tags:
        checks["sea_required"] = "FAIL"
    elif request.sea_required:
        checks["sea_required"] = "PASS"
    if request.destination_country_codes:
        checks["destination_country"] = (
            "PASS" if candidate.country_code in request.destination_country_codes else "FAIL"
        )
    if requested_regions(request) and not matches_requested_regions(candidate, request):
        checks["region"] = "FAIL"
    elif requested_regions(request):
        checks["region"] = "PASS"
    if matches_explicit_avoid(candidate, request):
        checks["explicit_avoid"] = "FAIL"
    if request.budget_strict and request.budget_total_rub is not None:
        minimum = candidate.estimated_total_cost_rub_min
        maximum = candidate.estimated_total_cost_rub_max
        if maximum is not None and maximum > request.budget_total_rub:
            checks["strict_budget"] = "FAIL"
        elif maximum is not None:
            checks["strict_budget"] = "PASS"
        elif minimum is not None and minimum > request.budget_total_rub:
            checks["strict_budget"] = "FAIL"
        else:
            checks["strict_budget"] = "UNKNOWN"
    if request.max_flight_duration_hours is not None:
        if candidate.flight_duration_hours is None:
            checks["max_flight_duration"] = "UNKNOWN"
        elif candidate.flight_duration_hours > request.max_flight_duration_hours:
            checks["max_flight_duration"] = "FAIL"
        else:
            checks["max_flight_duration"] = "PASS"
    if request.preferred_max_temperature_c is not None:
        if candidate.expected_temperature_c is None:
            checks["temperature_limit"] = "UNKNOWN"
        elif candidate.expected_temperature_c > request.preferred_max_temperature_c:
            checks["temperature_limit"] = "FAIL"
        else:
            checks["temperature_limit"] = "PASS"
    if request.visa_willingness is not None:
        if request.visa_willingness == "any":
            checks["visa"] = "NOT_APPLICABLE"
        else:
            assessment = candidate.entry_assessment
            if assessment is None or assessment.confidence != "verified":
                checks["visa"] = "UNKNOWN"
            elif request.visa_willingness == "no_visa":
                checks["visa"] = (
                    "PASS"
                    if assessment.outcome == "eligible" and assessment.requirement == "visa_free"
                    else "FAIL"
                )
            elif request.visa_willingness == "evisa_ok":
                checks["visa"] = (
                    "PASS"
                    if assessment.outcome in {"eligible", "requires_pretrip_action"}
                    and assessment.requirement in {"visa_free", "visa_required"}
                    else "FAIL"
                )
            else:  # visa_ok: any verified, non-restricted outcome remains acceptable.
                checks["visa"] = (
                    "PASS"
                    if assessment.outcome in {"eligible", "requires_pretrip_action"}
                    else "FAIL"
                )
    return checks


def hard_filter_reasons(candidate: DestinationCandidate, request: TravelRequest) -> list[str]:
    """Return stable human-facing machine codes for proven hard failures only."""

    names = {
        "destination_scope": "destination_scope_mismatch",
        "sea_required": "sea_required",
        "destination_country": "destination_country_mismatch",
        "region": "preferred_region_mismatch",
        "explicit_avoid": "explicitly_avoided",
        "strict_budget": "strict_budget_exceeded",
        "max_flight_duration": "max_flight_duration_exceeded",
        "temperature_limit": "temperature_limit_exceeded",
        "visa": "visa_requirement_incompatible",
    }
    return [
        names[name]
        for name, result in evaluate_hard_checks(candidate, request).items()
        if result == "FAIL"
    ]
