from datetime import date

from app.domain.models import TravelRequest
from app.services.ambiguity import clarification_questions, detect_ambiguities, explicit_assumptions


def test_p0_questions_are_limited_and_prioritized() -> None:
    ambiguities = detect_ambiguities(TravelRequest(raw_query="Хочу на море"))
    questions = clarification_questions(ambiguities)

    assert len(questions) == 3
    assert all(item.priority == "P0" for item in questions)
    assert [item.field for item in questions] == ["origin_city", "month", "adults"]


def test_known_fields_are_not_asked_again_and_defaults_are_disclosed() -> None:
    request = TravelRequest(
        raw_query="Из Москвы в августе",
        origin_city="Москва",
        month=8,
        adults=1,
        budget_total_rub=100_000,
        destination_scope="international",
    )
    ambiguities = detect_ambiguities(request)

    assert clarification_questions(ambiguities) == []
    assert (
        "Готовность оформлять визу не указана: рассматриваем любые варианты."
        in explicit_assumptions(ambiguities)
    )


def test_confirmed_flight_dates_satisfy_period_question() -> None:
    request = TravelRequest(
        raw_query="Точно с 15 по 23 августа",
        origin_city="Москва",
        date_from=date(2026, 8, 15),
        date_to=date(2026, 8, 23),
        adults=1,
        budget_total_rub=100_000,
        destination_scope="international",
    )

    fields = [item.field for item in clarification_questions(detect_ambiguities(request))]

    assert "month" not in fields


def test_departure_window_satisfies_period_question() -> None:
    request = TravelRequest(
        raw_query="Могу вылететь 15 или 16 августа",
        origin_city="Москва",
        departure_window_from=date(2026, 8, 15),
        departure_window_to=date(2026, 8, 16),
        adults=1,
        budget_total_rub=100_000,
        destination_scope="international",
    )

    fields = [item.field for item in clarification_questions(detect_ambiguities(request))]

    assert "month" not in fields
