from datetime import date

from app.domain.models import TravelRequest
from app.services.ambiguity import (
    clarification_questions,
    detect_ambiguities,
    explicit_assumptions,
    next_best_question,
    planning_confidence,
)


def test_only_origin_blocks_a_shortlist_and_optional_unknowns_remain_visible() -> None:
    ambiguities = detect_ambiguities(TravelRequest(raw_query="Хочу на море"))

    assert [item.field for item in clarification_questions(ambiguities)] == ["origin_city"]
    assert next_best_question(ambiguities) is not None
    assert next_best_question(ambiguities).field == "destination_scope"  # type: ignore[union-attr]


def test_known_origin_returns_a_usable_but_low_confidence_plan() -> None:
    ambiguities = detect_ambiguities(
        TravelRequest(raw_query="Из Москвы хочу на море", origin_city="Москва")
    )

    assert clarification_questions(ambiguities) == []
    assert "Период не указан" in " ".join(explicit_assumptions(ambiguities))
    confidence = planning_confidence(ambiguities)
    assert confidence.level == "low"
    assert {item.field for item in confidence.uncertainties} >= {"month", "budget_total_rub"}


def test_complete_request_has_high_confidence_and_no_advisory_question() -> None:
    request = TravelRequest(
        raw_query="Из Москвы в августе",
        origin_city="Москва",
        month=8,
        adults=1,
        budget_total_rub=100_000,
        destination_scope="international",
        visa_willingness="no_visa",
        max_flight_duration_hours=6,
        baggage_required=True,
        trip_style=["спокойно"],
    )
    ambiguities = detect_ambiguities(request)

    assert clarification_questions(ambiguities) == []
    assert planning_confidence(ambiguities).level == "high"
    assert next_best_question(ambiguities) is None


def test_confirmed_dates_and_departure_window_satisfy_timing_uncertainty() -> None:
    exact_request = TravelRequest(
        raw_query="Точно с 15 по 23 августа",
        origin_city="Москва",
        date_from=date(2026, 8, 15),
        date_to=date(2026, 8, 23),
    )
    flexible_request = TravelRequest(
        raw_query="Могу вылететь 15 или 16 августа",
        origin_city="Москва",
        departure_window_from=date(2026, 8, 15),
        departure_window_to=date(2026, 8, 16),
    )

    assert "month" not in {item.field for item in detect_ambiguities(exact_request)}
    assert "month" not in {item.field for item in detect_ambiguities(flexible_request)}
