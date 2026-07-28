from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.pricing.models import (
    ChildTransitFare,
    FoodPriceSet,
    MoneyRange,
    PriceTriple,
    PricingRequest,
    SourceRef,
    TransitFareSet,
)
from app.pricing.normalization.daily_costs import (
    calculate_food_component,
    calculate_local_transport_component,
)
from app.pricing.scenario_generation import generate_date_scenarios

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)
SOURCE = SourceRef(
    source_id="daily-cost-source",
    provider="official-or-manual-registry",
    source_kind="manual",
    observed_at=NOW,
    valid_until=NOW + timedelta(days=30),
)


def _request(**updates: object) -> PricingRequest:
    values: dict[str, object] = {
        "request_id": "daily-cost-request",
        "origin_city_id": "moscow",
        "origin_iata": ("MOW",),
        "destination_id": "istanbul",
        "destination_iata": ("IST",),
        "date_mode": "exact",
        "outbound_date": date(2026, 9, 12),
        "return_date": date(2026, 9, 19),
        "nights_min": 7,
        "nights_max": 7,
        "adults": 1,
        "rooms": 1,
        "spending_profile": "standard",
    }
    values.update(updates)
    return PricingRequest.model_validate(values)


def _food_prices(*, cappuccino: bool = True) -> FoodPriceSet:
    return FoodPriceSet(
        dataset_version="food-v1",
        inexpensive_meal=PriceTriple(low=400, average=500, high=600),
        fast_food_combo=PriceTriple(low=250, average=300, high=350),
        water_small=PriceTriple(low=50, average=60, high=70),
        cappuccino=(PriceTriple(low=150, average=200, high=250) if cappuccino else None),
        grocery_daily_basket=PriceTriple(low=500, average=600, high=700),
        sources=(SOURCE,),
    )


def _scenario(request: PricingRequest):
    return generate_date_scenarios(request).scenarios[0]


def test_standard_food_uses_fixed_basket_and_effective_nights() -> None:
    request = _request()
    component = calculate_food_component(
        request=request,
        scenario=_scenario(request),
        prices=_food_prices(),
    )

    assert component.amount == MoneyRange(
        floor=6_650,
        expected=9_520,
        safe=14_350,
    )
    assert "без алкоголя" in component.included[0]


def test_food_applies_age_factors_without_using_them_for_other_components() -> None:
    request = _request(
        spending_profile="economy",
        adults=2,
        children_ages=(5, 10, 15),
        infants=1,
    )
    component = calculate_food_component(
        request=request,
        scenario=_scenario(request),
        prices=_food_prices(),
    )

    assert component.amount == MoneyRange(
        floor=18_883,
        expected=23_821,
        safe=37_475,
    )


def test_two_year_old_uses_infant_food_factor() -> None:
    request = _request(spending_profile="economy", children_ages=(2,))
    component = calculate_food_component(
        request=request,
        scenario=_scenario(request),
        prices=_food_prices(),
    )

    assert component.amount == MoneyRange(
        floor=5_460,
        expected=6_888,
        safe=10_836,
    )


def test_standard_food_is_missing_without_required_cappuccino_evidence() -> None:
    request = _request()
    component = calculate_food_component(
        request=request,
        scenario=_scenario(request),
        prices=_food_prices(cappuccino=False),
    )

    assert component.amount is None
    assert component.status == "missing"


def test_comfort_food_is_explicitly_unsupported_until_calibrated() -> None:
    request = _request(spending_profile="comfort")
    component = calculate_food_component(
        request=request,
        scenario=_scenario(request),
        prices=_food_prices(),
    )

    assert component.amount is None
    assert "не откалиброван" in component.warnings[0]


def test_transit_chooses_day_and_weekly_pass_for_full_party() -> None:
    request = _request(adults=2, children_ages=(8,), infants=1)
    fares = TransitFareSet(
        dataset_version="transit-v1",
        adult_single_ride_rub=100,
        adult_day_pass_rub=250,
        adult_weekly_pass_rub=1_200,
        child_fares=(
            ChildTransitFare(
                age_min=0,
                age_max=6,
                single_ride_rub=0,
                day_pass_rub=0,
                weekly_pass_rub=0,
            ),
            ChildTransitFare(
                age_min=7,
                age_max=17,
                single_ride_rub=50,
                day_pass_rub=120,
                weekly_pass_rub=500,
            ),
        ),
        sources=(SOURCE,),
    )
    component = calculate_local_transport_component(
        request=request,
        scenario=_scenario(request),
        fares=fares,
    )

    assert component.amount == MoneyRange(floor=2_900, expected=2_900, safe=2_900)
    assert "такси" in component.excluded


def test_transit_is_missing_when_child_tariff_evidence_is_absent() -> None:
    request = _request(children_ages=(8,))
    fares = TransitFareSet(
        dataset_version="transit-v1",
        adult_single_ride_rub=100,
        sources=(SOURCE,),
    )
    component = calculate_local_transport_component(
        request=request,
        scenario=_scenario(request),
        fares=fares,
    )

    assert component.amount is None
    assert component.status == "missing"
    assert "8" in component.warnings[0]


def test_transit_uses_rides_when_passes_are_absent() -> None:
    request = _request(
        outbound_date=date(2026, 9, 12),
        return_date=date(2026, 9, 15),
        nights_min=3,
        nights_max=3,
    )
    fares = TransitFareSet(
        dataset_version="transit-v1",
        adult_single_ride_rub=100,
        sources=(SOURCE,),
    )
    component = calculate_local_transport_component(
        request=request,
        scenario=_scenario(request),
        fares=fares,
    )

    assert component.amount == MoneyRange(floor=900, expected=900, safe=900)
