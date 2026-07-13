"""Deterministic, evidence-aware ranking of candidates after hard filters."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import DestinationCandidate, ScoredDestination, TravelRequest
from app.services.filtering import hard_filter_reasons

SCORING_PATH = Path(__file__).resolve().parents[1] / "data" / "scoring.json"


def load_scoring_weights() -> dict[str, float]:
    """Read weights from data rather than hiding product choices in Python."""

    payload = json.loads(SCORING_PATH.read_text(encoding="utf-8"))
    return {name: float(weight) for name, weight in payload["weights"].items()}


def validate_scoring_weights(weights: dict[str, float]) -> None:
    if round(sum(weights.values()), 6) != 100:
        raise ValueError("Scoring weights must sum to 100")


def _budget_fit(candidate: DestinationCandidate, request: TravelRequest) -> float | None:
    if request.budget_total_rub is None or candidate.estimated_total_cost_rub_min is None:
        return None
    budget = request.budget_total_rub
    minimum = candidate.estimated_total_cost_rub_min
    maximum = candidate.estimated_total_cost_rub_max or minimum
    if maximum <= budget:
        return 100.0
    if minimum > budget:
        return max(0.0, 100.0 - ((minimum - budget) / budget * 100))
    return 75.0


def _weather_fit(candidate: DestinationCandidate, request: TravelRequest) -> float | None:
    if candidate.expected_temperature_c is None:
        return None
    if request.heat_tolerance != "low" and request.preferred_max_temperature_c is None:
        return 70.0
    limit = request.preferred_max_temperature_c or 30
    return max(0.0, 100.0 - max(0.0, candidate.expected_temperature_c - limit) * 18)


def _entry_simplicity(candidate: DestinationCandidate) -> float | None:
    return {"none": 100.0, "evisa": 80.0, "visa": 45.0, "unknown": 25.0}.get(
        candidate.visa_complexity or "unknown"
    )


def _transport_convenience(candidate: DestinationCandidate) -> float | None:
    if candidate.flight_duration_hours is None:
        return None
    transfer_penalty = (candidate.transfers_count or 0) * 18
    duration_penalty = max(0.0, candidate.flight_duration_hours - 2) * 6
    return max(0.0, 100.0 - transfer_penalty - duration_penalty)


def _preference_fit(candidate: DestinationCandidate, request: TravelRequest) -> float | None:
    preferences = set(request.preferences + request.trip_style)
    if not preferences:
        return 60.0
    normalized = {tag.casefold() for tag in candidate.destination_tags}
    matches = sum(preference.casefold() in normalized for preference in preferences)
    return 100.0 * matches / len(preferences)


def _evidence_quality(candidate: DestinationCandidate) -> float | None:
    if not candidate.sources:
        return None
    return (candidate.data_confidence or 0.0) * 100


def score_candidate(candidate: DestinationCandidate, request: TravelRequest) -> ScoredDestination:
    """Compute a stable 0–100 score and renormalize only known components."""

    weights = load_scoring_weights()
    validate_scoring_weights(weights)
    component_scores = {
        "budget_fit": _budget_fit(candidate, request),
        "weather_fit": _weather_fit(candidate, request),
        "entry_simplicity": _entry_simplicity(candidate),
        "transport_convenience": _transport_convenience(candidate),
        "preference_fit": _preference_fit(candidate, request),
        "evidence_quality": _evidence_quality(candidate),
    }
    known = {name: score for name, score in component_scores.items() if score is not None}
    active_weight = sum(weights[name] for name in known)
    contributions = {
        name: round(score * weights[name] / active_weight, 2) for name, score in known.items()
    }
    rejected_reasons = hard_filter_reasons(candidate, request)
    matched = [
        pref for pref in request.preferences if pref.casefold() in candidate.destination_tags
    ]
    risks = ["Данные основаны на demo fixture и не являются актуальными фактами."]
    if candidate.precipitation_risk in {"high", "medium"}:
        risks.append(f"Риск осадков: {candidate.precipitation_risk}.")
    return ScoredDestination(
        candidate=candidate,
        passed_hard_filters=not rejected_reasons,
        rejected_reasons=rejected_reasons,
        total_score=round(sum(contributions.values()), 2),
        score_breakdown=contributions,
        pros=["Соответствует критическим фильтрам.", *matched][:4],
        cons=[] if not rejected_reasons else rejected_reasons[:3],
        risks=risks,
        assumptions=["Расчёт использует локальные demo estimates."],
        explanation=(
            "Оценка рассчитана детерминированно по опубликованным весам; "
            "требуется live-проверка источников."
        ),
    )


def rank_demo_candidates(request: TravelRequest, limit: int = 5) -> list[ScoredDestination]:
    """Rank local fixtures only for explicit demo mode."""

    from app.services.fixtures import load_demo_candidates

    scored = [score_candidate(candidate, request) for candidate in load_demo_candidates()]
    eligible = [item for item in scored if item.passed_hard_filters]
    return sorted(eligible, key=lambda item: item.total_score, reverse=True)[:limit]
