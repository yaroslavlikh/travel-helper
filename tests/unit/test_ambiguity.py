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
        duration_nights_min=7,
        duration_nights_max=10,
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


def test_month_without_duration_requires_an_approximate_trip_length() -> None:
    request = TravelRequest(raw_query="В августе", month=8)

    questions = clarification_questions(detect_ambiguities(request, today=date(2026, 7, 15)))

    assert questions[0].field == "origin_city"
    assert "duration_nights_min" in [question.field for question in questions]


def test_exact_dates_do_not_require_a_separate_duration() -> None:
    request = TravelRequest(
        raw_query="Из Москвы с 10 по 17 августа",
        origin_city="Москва",
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 17),
        adults=2,
        budget_total_rub=180_000,
        destination_scope="international",
    )

    questions = clarification_questions(detect_ambiguities(request, today=date(2026, 7, 15)))

    assert questions == []


def test_departure_date_and_duration_are_temporally_ready() -> None:
    request = TravelRequest(
        raw_query="После 10 августа на неделю",
        date_from=date(2026, 8, 10),
        duration_nights_min=7,
    )

    fields = [
        question.field
        for question in clarification_questions(
            detect_ambiguities(request, today=date(2026, 7, 15))
        )
    ]

    assert "month" not in fields
    assert "duration_nights_min" not in fields


def test_reversed_exact_dates_require_correction() -> None:
    request = TravelRequest(
        raw_query="С 20 по 10 августа",
        date_from=date(2026, 8, 20),
        date_to=date(2026, 8, 10),
    )

    fields = [
        question.field
        for question in clarification_questions(
            detect_ambiguities(request, today=date(2026, 7, 15))
        )
    ]

    assert "date_to" in fields
