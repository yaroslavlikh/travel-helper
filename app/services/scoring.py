"""Deterministic, evidence-aware destination ranking; no LLM participates here."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from app.domain.models import DestinationCandidate, ScoredDestination, TravelRequest
from app.services.destination_semantics import normalized_avoided_tags, normalized_preference_tags
from app.services.filtering import evaluate_hard_checks, hard_filter_reasons

SCORING_PATH = Path(__file__).resolve().parents[1] / "data" / "scoring.json"
STRICT_BUDGET_FALLBACK = "Показаны ближайшие варианты выше строгого бюджета."
DIMENSIONS = {
    "budget": 30.0,
    "experience": 50.0,
    "logistics": 40.0,
    "weather": 45.0,
    "entry": 30.0,
    "practical": 50.0,
}
STATE_ORDER = {"ELIGIBLE": 0, "CONDITIONAL": 1, "FALLBACK": 2, "EXCLUDED": 3}
CandidateState = Literal["ELIGIBLE", "CONDITIONAL", "EXCLUDED", "FALLBACK"]


@lru_cache
def load_scoring_config() -> dict[str, Any]:
    """Load the versioned, deterministic ranking parameters."""

    return cast(dict[str, Any], json.loads(SCORING_PATH.read_text(encoding="utf-8")))


def load_scoring_weights() -> dict[str, float]:
    return {name: float(weight) for name, weight in load_scoring_config()["weights"].items()}


def validate_scoring_weights(weights: dict[str, float]) -> None:
    config = load_scoring_config()
    if set(weights) != set(DIMENSIONS) or round(sum(weights.values()), 6) != 100:
        raise ValueError("ranking-v1 weights must cover six dimensions and sum to 100")
    if set(config["priors"]) != set(DIMENSIONS):
        raise ValueError("ranking-v1 priors must cover six dimensions")


def _clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, value))


def _budget_fit(candidate: DestinationCandidate, request: TravelRequest) -> float | None:
    if request.budget_total_rub is None or candidate.estimated_total_cost_rub_min is None:
        return None
    floor = candidate.estimated_total_cost_rub_min
    safe = candidate.estimated_total_cost_rub_max or floor
    expected = (floor + safe) / 2
    budget = request.budget_total_rub
    if safe <= budget:
        return 90 + 10 * min((budget - safe) / max(budget * 0.2, 1), 1)
    if expected <= budget:
        return 70 + 20 * (budget - expected) / max(safe - expected, 1)
    if floor <= budget:
        return 40 + 30 * (budget - floor) / max(expected - floor, 1)
    return 40 * max(0, 1 - (floor - budget) / max(budget * 0.5, 1))


def _experience_fit(candidate: DestinationCandidate, request: TravelRequest) -> float:
    preferences = normalized_preference_tags(request)
    avoided = normalized_avoided_tags(request)
    if not preferences and not avoided:
        return 50.0
    tags = {tag.casefold() for tag in candidate.destination_tags}
    matched = sum(tag in tags for tag in preferences)
    avoided_non_matches = sum(tag not in tags for tag in avoided)
    return 100 * (matched + avoided_non_matches) / (len(preferences) + len(avoided))


def _logistics_fit(candidate: DestinationCandidate) -> float | None:
    if candidate.flight_duration_hours is None:
        return None
    duration = candidate.flight_duration_hours
    if duration <= 4:
        duration_score = 100.0
    elif duration <= 7:
        duration_score = 100 - (duration - 4) * 35 / 3
    elif duration <= 12:
        duration_score = 65 - (duration - 7) * 30 / 5
    elif duration <= 18:
        duration_score = 35 - (duration - 12) * 20 / 6
    else:
        duration_score = 10.0
    stops = candidate.transfers_count or 0
    return _clamp(duration_score * 0.6 + max(0, 100 - stops * 45) * 0.4)


def _weather_fit(candidate: DestinationCandidate, request: TravelRequest) -> float | None:
    if candidate.expected_temperature_c is None:
        return None
    limit = request.preferred_max_temperature_c
    if limit is None and request.heat_tolerance == "low":
        limit = 30
    temperature = (
        85.0
        if limit is None
        else _clamp(100 - max(0, candidate.expected_temperature_c - limit) * 12)
    )
    rain = {"low": 100.0, "medium": 65.0, "high": 30.0}.get(
        candidate.precipitation_risk or "", 50.0
    )
    return temperature * 0.75 + rain * 0.25


def _entry_fit(candidate: DestinationCandidate) -> float | None:
    return {"none": 100.0, "evisa": 75.0, "visa": 50.0}.get(candidate.visa_complexity or "")


def _practical_fit(candidate: DestinationCandidate, request: TravelRequest) -> float:
    wants_city = "city" in normalized_preference_tags(request)
    if not wants_city:
        return 50.0
    return 85.0 if "city" in candidate.destination_tags else 35.0


def _confidence(candidate: DestinationCandidate, observed: float | None) -> float:
    if observed is None:
        return 0.0
    return candidate.data_confidence if candidate.data_confidence is not None else 0.6


def score_candidate(candidate: DestinationCandidate, request: TravelRequest) -> ScoredDestination:
    """Score one candidate with fixed weights, per-axis shrinkage and explicit state."""

    weights = load_scoring_weights()
    validate_scoring_weights(weights)
    config = load_scoring_config()
    priors = {name: float(value) for name, value in config["priors"].items()}
    observed = {
        "budget": _budget_fit(candidate, request),
        "experience": _experience_fit(candidate, request),
        "logistics": _logistics_fit(candidate),
        "weather": _weather_fit(candidate, request),
        "entry": _entry_fit(candidate),
        "practical": _practical_fit(candidate, request),
    }
    confidences = {name: _confidence(candidate, value) for name, value in observed.items()}
    effective = {
        name: confidences[name] * (value if value is not None else priors[name])
        + (1 - confidences[name]) * priors[name]
        for name, value in observed.items()
    }
    contributions = {name: round(effective[name] * weights[name] / 100, 2) for name in weights}
    uncertainty_settings = config["uncertainty"]
    uncertainty = min(
        float(uncertainty_settings["cap"]),
        float(uncertainty_settings["multiplier"])
        * sum(weights[name] / 100 * (1 - confidences[name]) for name in weights),
    )
    checks = evaluate_hard_checks(candidate, request)
    reasons = hard_filter_reasons(candidate, request)
    unknown = [name for name, result in checks.items() if result == "UNKNOWN"]
    blocking_unknown = {"strict_budget", "visa"} & set(unknown)
    state: CandidateState = (
        "EXCLUDED" if reasons or blocking_unknown else "CONDITIONAL" if unknown else "ELIGIBLE"
    )
    pre_cap = sum(contributions.values()) - uncertainty
    caps: list[str] = []
    cap_settings = config["caps"]
    if request.budget_total_rub is not None and (observed["budget"] or 0) < 25:
        pre_cap, caps = min(pre_cap, float(cap_settings["budget_below_25"])), ["budget_below_25"]
    if (observed["entry"] or 0) < 25:
        pre_cap, caps = (
            min(pre_cap, float(cap_settings["entry_below_25"])),
            [*caps, "entry_below_25"],
        )
    if request.max_flight_duration_hours is not None and (observed["logistics"] or 0) < 20:
        pre_cap, caps = (
            min(pre_cap, float(cap_settings["logistics_below_20"])),
            [*caps, "logistics_below_20"],
        )
    total = round(_clamp(pre_cap))
    candidate_tags = {tag.casefold() for tag in candidate.destination_tags}
    matched = [
        label
        for label in [*request.preferences, *request.trip_style, *request.priorities]
        if label.casefold() in candidate_tags
    ]
    return ScoredDestination(
        candidate=candidate,
        passed_hard_filters=state == "ELIGIBLE",
        rejected_reasons=reasons,
        total_score=total,
        final_score=total,
        state=state,
        ranking_version="ranking-v1",
        score_breakdown=contributions,
        hard_checks=checks,
        uncertainty_penalty=round(uncertainty, 2),
        caps_applied=caps,
        pros=(
            ["Соответствует подтверждённым условиям.", *matched][:3]
            if state == "ELIGIBLE"
            else matched[:3]
        ),
        cons=[
            *[_failure_message(reason) for reason in reasons],
            *[_unknown_message(name) for name in unknown],
        ][:3],
        risks=["Оценки demo fixture не являются актуальными фактами."],
        assumptions=[
            "Цена — modelled estimate; для строгого бюджета используется safe total.",
            *[_unknown_message(name) for name in unknown],
        ],
        explanation=_explanation(state, unknown),
    )


def _sort_key(item: ScoredDestination) -> tuple[int, int, float, str]:
    return (
        STATE_ORDER[item.state],
        -item.final_score,
        -(item.candidate.data_confidence or 0),
        item.candidate.destination_id,
    )


def _unknown_message(name: str) -> str:
    return {
        "strict_budget": "Не удалось подтвердить безопасную верхнюю границу стоимости.",
        "visa": "Не удалось подтвердить применимый визовый режим.",
        "max_flight_duration": "Не удалось подтвердить длительность перелёта.",
        "temperature_limit": "Не удалось подтвердить температуру для заданного лимита.",
    }.get(name, "Не удалось подтвердить одно из заданных условий.")


def _failure_message(reason: str) -> str:
    return {
        "destination_scope_mismatch": "Не соответствует выбранной географии поездки.",
        "sea_required": "Не подтверждено обязательное море.",
        "preferred_region_mismatch": "Не относится к выбранному региону.",
        "explicitly_avoided": "Направление явно исключено из запроса.",
        "strict_budget_exceeded": "Безопасная верхняя оценка цены выше строгого бюджета.",
        "max_flight_duration_exceeded": "Перелёт дольше заданного лимита.",
        "temperature_limit_exceeded": "Температура выше заданного лимита.",
        "visa_requirement_incompatible": "Визовый режим не соответствует условию.",
    }[reason]


def _explanation(state: CandidateState, unknown: list[str]) -> str:
    if state == "ELIGIBLE":
        return "Все заданные hard-условия подтверждены; рейтинг рассчитан детерминированно без LLM."
    if state == "CONDITIONAL":
        return f"Нужно проверить: {'; '.join(_unknown_message(name) for name in unknown)}"
    if state == "FALLBACK":
        return "Вариант показан только как ближайший выше строгого бюджета."
    return "Вариант не проходит одно или несколько заданных условий."


def _similarity(left: ScoredDestination, right: ScoredDestination) -> float:
    country = 1.0 if left.candidate.country == right.candidate.country else 0.0
    tags_left, tags_right = (
        set(left.candidate.destination_tags),
        set(right.candidate.destination_tags),
    )
    archetype = len(tags_left & tags_right) / max(len(tags_left | tags_right), 1)
    cost = 1.0 if abs(left.final_score - right.final_score) < 10 else 0.0
    climate = (
        1.0
        if abs(
            (left.candidate.expected_temperature_c or 0)
            - (right.candidate.expected_temperature_c or 0)
        )
        <= 3
        else 0.0
    )
    return 0.35 * country + 0.30 * archetype + 0.20 * cost + 0.15 * climate


def _diversify(items: list[ScoredDestination], limit: int) -> list[ScoredDestination]:
    if not items:
        return []
    settings = load_scoring_config()["diversity"]
    comparable = [
        item
        for item in items
        if item.final_score >= items[0].final_score - float(settings["score_gap"])
    ]
    selected = [comparable.pop(0)]
    while comparable and len(selected) < limit:
        choices = [
            item
            for item in comparable
            if sum(other.candidate.country == item.candidate.country for other in selected)
            < int(settings["country_cap"])
            or not any(
                sum(other.candidate.country == other_item.candidate.country for other in selected)
                < int(settings["country_cap"])
                for other_item in comparable
            )
        ]
        best = min(
            choices,
            key=lambda item: (
                -(
                    item.final_score
                    - float(settings["similarity_penalty"])
                    * max(_similarity(item, chosen) for chosen in selected)
                ),
                _sort_key(item),
            ),
        )
        selected.append(best)
        comparable.remove(best)
    return [
        item.model_copy(update={"rank_after_diversity": index + 1})
        for index, item in enumerate(selected)
    ]


def rank_demo_candidates(request: TravelRequest, limit: int = 5) -> list[ScoredDestination]:
    """Rank fixture candidates, exposing marked fallback only when normal results are absent."""

    from app.services.fixtures import load_demo_candidates

    scored = [score_candidate(candidate, request) for candidate in load_demo_candidates()]
    eligible = [item for item in scored if item.state in {"ELIGIBLE", "CONDITIONAL"}]
    pool = eligible
    if not pool:
        pool = [
            item.model_copy(
                update={
                    "state": "FALLBACK",
                    "passed_hard_filters": False,
                    "cons": [*item.cons, STRICT_BUDGET_FALLBACK],
                    "risks": [*item.risks, STRICT_BUDGET_FALLBACK],
                    "assumptions": [*item.assumptions, STRICT_BUDGET_FALLBACK],
                    "explanation": _explanation("FALLBACK", []),
                }
            )
            for item in scored
            if item.hard_checks.get("strict_budget") == "FAIL"
            and all(
                result in {"PASS", "NOT_APPLICABLE"}
                for name, result in item.hard_checks.items()
                if name != "strict_budget"
            )
        ]
    ordered = [
        item.model_copy(update={"rank_before_diversity": index + 1})
        for index, item in enumerate(sorted(pool, key=_sort_key))
    ]
    return _diversify(ordered, limit)
