from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

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


class RainConstraintGateway:
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
        del metadata
        assert "rain_avoidance" in prompt
        if operation == "revise_user_query":
            return TravelRequestRevision(changes=TravelRequestPatch(rain_avoidance=True))
        return TravelRequestPatch(origin_city="Москва", rain_avoidance=True)

    async def aclose(self) -> None:
        return None


class AvoidedFeatureGateway:
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
        del operation, schema, metadata
        assert "avoided_features" in prompt
        return TravelRequestPatch(origin_city="Москва", avoided_features=["nightlife"])

    async def aclose(self) -> None:
        return None


class OptionalSeaGateway:
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
        return TravelRequestPatch(origin_city="Москва", sea_required=True, avoided_features=["sea"])

    async def aclose(self) -> None:
        return None


class InferredDatesGateway:
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
        return TravelRequestPatch(
            origin_city="Москва",
            date_from=date(2026, 8, 25),
            date_to=date(2026, 9, 1),
        )

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


def test_extracts_cross_month_trip_range_from_free_text() -> None:
    request = extract_travel_request("Хочу поехать с 20 августа по 3 сентября")

    assert request.date_from == date(2026, 8, 20)
    assert request.date_to == date(2026, 9, 3)
    assert request.month is None


def test_ignores_invalid_legacy_structured_answer_instead_of_breaking_request() -> None:
    request = extract_travel_request(
        "Из Москвы хочу на море",
        {"visa_willingness": "тока шенген если"},
    )

    assert request.origin_city == "Москва"
    assert request.visa_willingness is None


def test_preserves_schengen_only_as_a_visa_and_destination_preference() -> None:
    request = extract_travel_request("Готов только на шенген, вылет из Москвы")

    assert request.visa_willingness == "visa_ok"
    assert "шенгенская зона" in request.preferences


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


def test_extracts_multiple_explicit_destination_countries_to_iso_codes() -> None:
    request = extract_travel_request("Хочу куда-нибудь в Малазию или Сингапур")

    assert request.destination_country_codes == ["MY", "SG"]


@pytest.mark.parametrize(
    "query",
    [
        "Хочу за границу, но не хочу в постсоветские страны",
        "Хочу за границу, но не рассматриваю СНГ",
        "Хочу за границу, исключить бывший СССР",
    ],
)
def test_extracts_post_soviet_country_group_exclusion(query: str) -> None:
    request = extract_travel_request(query)

    assert request.avoid == ["постсоветские страны"]


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


def test_colloquial_not_really_want_sea_is_not_a_requirement() -> None:
    request = extract_travel_request("Хочу отдых в Азии, не оч хочу на море")

    assert request.sea_required is False
    assert "море" in request.avoid


def test_optional_sea_is_not_treated_as_a_requirement() -> None:
    request = extract_travel_request("Хочу городскую жизнь, море не обязательно")

    assert request.sea_required is False
    assert "море" not in request.avoid


@pytest.mark.asyncio
async def test_optional_sea_overrides_model_requirement_and_dislike() -> None:
    request = await extract_travel_request_with_model(
        "Из Москвы в Азию, море не обязательно",
        None,
        OptionalSeaGateway(),  # type: ignore[arg-type]
    )

    assert request.sea_required is False
    assert "sea" not in request.avoided_features


@pytest.mark.asyncio
async def test_month_wording_does_not_accept_model_invented_exact_dates() -> None:
    request = await extract_travel_request_with_model(
        "Из Москвы в Азию в конце августа на неделю",
        None,
        InferredDatesGateway(),  # type: ignore[arg-type]
    )

    assert request.month == 8
    assert request.date_from is None
    assert request.date_to is None


def test_infrastructure_and_activities_become_preference_hints() -> None:
    request = extract_travel_request("Нужна нормальная инфраструктура и куча активностей")

    assert request.preferences == ["инфраструктура", "активности"]


@pytest.mark.parametrize("query", ["не хочу дождей", "без ливней", "нужна сухая погода"])
def test_demo_parser_extracts_rain_avoidance_phrases(query: str) -> None:
    request = extract_travel_request(query)

    assert request.rain_avoidance is True


@pytest.mark.asyncio
async def test_model_normalizes_rain_dislike_into_typed_constraint() -> None:
    request = await extract_travel_request_with_model(
        "Из Москвы, терпеть не могу мокрую погоду",
        None,
        RainConstraintGateway(),  # type: ignore[arg-type]
    )

    assert request.rain_avoidance is True


@pytest.mark.asyncio
async def test_model_refinement_preserves_typed_rain_constraint_in_chat_memory() -> None:
    base = TravelRequest(raw_query="Из Москвы", origin_city="Москва")

    request = await extract_travel_request_with_model(
        "И ещё не хочу дождей",
        None,
        RainConstraintGateway(),  # type: ignore[arg-type]
        base_request=base,
    )

    assert request.origin_city == "Москва"
    assert request.rain_avoidance is True


@pytest.mark.asyncio
async def test_model_normalizes_free_form_dislike_into_controlled_feature() -> None:
    request = await extract_travel_request_with_model(
        "Из Москвы, не переношу шумные тусовочные районы",
        None,
        AvoidedFeatureGateway(),  # type: ignore[arg-type]
    )

    assert request.avoided_features == ["nightlife"]


def test_controlled_avoided_features_reject_unknown_model_output() -> None:
    with pytest.raises(ValidationError):
        TravelRequestPatch(avoided_features=["хамство"])  # type: ignore[list-item]


def test_demo_refinement_can_reverse_rain_avoidance() -> None:
    base = TravelRequest(raw_query="Без дождей", rain_avoidance=True)

    request = revise_travel_request_deterministically(base, "Небольшой дождь не проблема")

    assert request.rain_avoidance is False


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
