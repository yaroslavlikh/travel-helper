from datetime import date
from typing import Any

from pydantic import BaseModel

from app.domain.models import TravelRequest, TravelRequestPatch, TravelRequestRevision
from app.services.extraction import (
    extract_travel_request,
    extract_travel_request_with_model,
    merge_travel_request_revision,
    revise_travel_request_deterministically,
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


def test_extracts_region_food_preference_and_explicit_country_exclusion() -> None:
    request = extract_travel_request("Хочу в Азию поесть острую еду, только не Грузию")

    assert request.preferences == ["Азия", "острая еда"]
    assert request.avoid == ["Грузия"]


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


def test_explicit_no_sea_refinement_overrides_existing_requirement() -> None:
    base = TravelRequest(raw_query="На море", sea_required=True)

    updated = revise_travel_request_deterministically(base, "Я не хочу море, нужна инфраструктура")

    assert updated.sea_required is False


def test_flexible_departure_window_replaces_exact_trip_dates() -> None:
    base = TravelRequest(
        raw_query="Точно с 15 по 23 августа",
        date_from=date(2026, 8, 15),
        date_to=date(2026, 8, 23),
    )
    revision = TravelRequestRevision(
        changes=TravelRequestPatch(
            departure_window_from=date(2026, 8, 15),
            departure_window_to=date(2026, 8, 16),
        )
    )

    updated = merge_travel_request_revision(base, revision)

    assert updated.departure_window_from == date(2026, 8, 15)
    assert updated.departure_window_to == date(2026, 8, 16)
    assert updated.date_from is None
    assert updated.date_to is None


def test_confirmed_flight_dates_replace_approximate_window() -> None:
    base = TravelRequest(
        raw_query="Можно в августе",
        month=8,
        departure_window_from=date(2026, 8, 10),
        departure_window_to=date(2026, 8, 20),
    )
    revision = TravelRequestRevision(
        changes=TravelRequestPatch(
            date_from=date(2026, 8, 15),
            date_to=date(2026, 8, 23),
        )
    )

    updated = merge_travel_request_revision(base, revision)

    assert updated.date_from == date(2026, 8, 15)
    assert updated.date_to == date(2026, 8, 23)
    assert updated.month is None
    assert updated.departure_window_from is None
    assert updated.departure_window_to is None


def test_one_way_refinement_keeps_known_flexible_month() -> None:
    base = TravelRequest(raw_query="В октябре", month=10)
    revision = TravelRequestRevision(changes=TravelRequestPatch(flight_one_way=True))

    updated = merge_travel_request_revision(base, revision)

    assert updated.month == 10
    assert updated.flight_one_way is True
