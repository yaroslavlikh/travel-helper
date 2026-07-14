from datetime import date
from typing import Any

from pydantic import BaseModel

from app.domain.models import Ambiguity, TravelRequest, TravelRequestPatch, TravelRequestRevision
from app.services.extraction import (
    extract_answers_for_questions,
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


class TimingModelGateway(FakeModelGateway):
    async def generate_structured(
        self,
        *,
        operation: str,
        prompt: str,
        schema: type[BaseModel],
        metadata: dict[str, Any],
    ) -> BaseModel:
        del operation, prompt, schema, metadata
        return TravelRequestPatch(
            month=8,
            duration_nights_min=7,
            duration_nights_max=10,
        )


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


async def test_timing_clarification_keeps_month_and_full_duration_range() -> None:
    question = Ambiguity(
        field="month",
        priority="P0",
        reason="Нужен период",
        question="Когда хотите поехать?",
    )

    answers = await extract_answers_for_questions(
        "В августе на 7–10 ночей",
        [question],
        TimingModelGateway(),  # type: ignore[arg-type]
        demo_mode=False,
    )

    assert answers == {
        "month": 8,
        "duration_nights_min": 7,
        "duration_nights_max": 10,
    }


def test_revision_switches_from_exact_dates_to_a_month_without_stale_dates() -> None:
    base = TravelRequest(
        raw_query="С 10 по 17 августа",
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 17),
    )
    revision = TravelRequestRevision(
        changes=TravelRequestPatch(
            month=9,
            duration_nights_min=7,
            duration_nights_max=7,
        )
    )

    updated = merge_travel_request_revision(base, revision)

    assert updated.month == 9
    assert updated.date_from is None
    assert updated.date_to is None
