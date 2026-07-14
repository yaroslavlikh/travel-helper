from datetime import date
from typing import Any

from pydantic import BaseModel

from app.domain.models import TravelRequest, TravelRequestPatch, TravelRequestRevision
from app.services.extraction import (
    extract_travel_request,
    extract_travel_request_with_model,
    merge_travel_request_revision,
)


class FakeModelGateway:
    provider_name = "fake"
    model_name = "fake-model"

    async def generate_structured(
        self,
        *,
        operation: str,
        prompt: str,
        schema: type[BaseModel],
        metadata: dict[str, Any],
    ) -> BaseModel:
        del operation, prompt, schema, metadata
        return TravelRequestPatch(origin_city="Москва", month=8, adults=2)

    async def aclose(self) -> None:
        return None


def test_extracts_user_supplied_travel_constraints() -> None:
    request = extract_travel_request(
        "Живу в Москве, хочу улететь на море в августе на 7–10 дней, "
        "бюджет 150 тысяч рублей на одного, не люблю сильную жару"
    )

    assert request.origin_city == "Москва"
    assert request.month == 8
    assert request.duration_nights_min == 7
    assert request.duration_nights_max == 10
    assert request.budget_total_rub == 150_000
    assert request.adults == 1
    assert request.sea_required is True
    assert request.heat_tolerance == "low"
    assert request.destination_scope is None


def test_answers_merge_without_rewriting_known_request_fields() -> None:
    request = extract_travel_request(
        "Из Москвы в августе на море, бюджет 150 тысяч на одного",
        {"destination_scope": "international", "visa_willingness": "no_visa"},
    )

    assert request.origin_city == "Москва"
    assert request.destination_scope == "international"
    assert request.visa_willingness == "no_visa"


def test_extracts_russian_number_words_for_travelers_and_flight_limit() -> None:
    request = extract_travel_request(
        "Из Санкт-Петербурга на море в сентябре на неделю, нас двое, "
        "за границу, максимум четыре часа перелета, бюджет 180 тысяч"
    )

    assert request.adults == 2
    assert request.duration_nights_min == 7
    assert request.max_flight_duration_hours == 4


async def test_model_extraction_preserves_query_and_applies_validated_answers() -> None:
    request = await extract_travel_request_with_model(
        "Из Москвы в августе",
        {"budget_total_rub": 200_000},
        FakeModelGateway(),  # type: ignore[arg-type]
    )

    assert request.raw_query == "Из Москвы в августе"
    assert request.origin_city == "Москва"
    assert request.adults == 2
    assert request.budget_total_rub == 200_000


def test_revision_changes_only_explicit_fields_and_can_clear_constraints() -> None:
    base = TravelRequest(
        raw_query="Из Москвы на море",
        origin_city="Москва",
        adults=2,
        budget_total_rub=200_000,
        sea_required=True,
        preferences=["тихий пляж"],
    )
    revision = TravelRequestRevision(
        changes=TravelRequestPatch(budget_total_rub=160_000),
        clear_fields=["sea_required", "preferences"],
    )

    updated = merge_travel_request_revision(base, revision)

    assert updated.origin_city == "Москва"
    assert updated.adults == 2
    assert updated.budget_total_rub == 160_000
    assert updated.sea_required is False
    assert updated.preferences == []


def test_planning_window_replaces_confirmed_flight_dates() -> None:
    base = TravelRequest(
        raw_query="Точно с 15 по 23 августа",
        flight_departure_date=date(2026, 8, 15),
        flight_return_date=date(2026, 8, 23),
    )
    revision = TravelRequestRevision(changes=TravelRequestPatch(month=9))

    updated = merge_travel_request_revision(base, revision)

    assert updated.month == 9
    assert updated.flight_departure_date is None
    assert updated.flight_return_date is None


def test_confirmed_flight_dates_replace_approximate_window() -> None:
    base = TravelRequest(
        raw_query="Можно в августе",
        month=8,
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 20),
    )
    revision = TravelRequestRevision(
        changes=TravelRequestPatch(
            flight_departure_date=date(2026, 8, 15),
            flight_return_date=date(2026, 8, 23),
        )
    )

    updated = merge_travel_request_revision(base, revision)

    assert updated.flight_departure_date == date(2026, 8, 15)
    assert updated.flight_return_date == date(2026, 8, 23)
    assert updated.month is None
    assert updated.date_from is None
    assert updated.date_to is None
