from app.domain.models import TravelRequest
from app.pricing.estimator import estimate_trip_cost, price_card_view
from app.services.fixtures import load_demo_candidates


def _candidate():
    return next(item for item in load_demo_candidates() if item.destination_id == "istanbul")


def test_modelled_trip_price_is_ordered_and_covers_the_whole_party() -> None:
    request = TravelRequest(
        raw_query="Из Москвы в Стамбул на двоих на неделю",
        origin_city="Москва",
        adults=2,
        date_from="2026-08-10",
        date_to="2026-08-17",
        budget_total_rub=500_000,
    )

    estimate = estimate_trip_cost(_candidate(), request)

    assert estimate.floor_total_rub <= estimate.expected_total_rub <= estimate.safe_total_rub
    assert estimate.party_size == 2
    assert estimate.date_mode == "exact"
    assert estimate.budget_fit == "confidently_within"
    assert price_card_view(estimate).headline.startswith("≈ ")


def test_more_adults_never_reduce_modelled_total() -> None:
    one = estimate_trip_cost(_candidate(), TravelRequest(raw_query="one", adults=1))
    two = estimate_trip_cost(_candidate(), TravelRequest(raw_query="two", adults=2))

    assert two.floor_total_rub >= one.floor_total_rub
    assert two.expected_total_rub >= one.expected_total_rub
    assert two.safe_total_rub >= one.safe_total_rub


def test_strict_budget_uses_safe_total_not_floor() -> None:
    baseline = estimate_trip_cost(_candidate(), TravelRequest(raw_query="base", adults=1))
    request = TravelRequest(
        raw_query="strict",
        adults=1,
        budget_total_rub=baseline.expected_total_rub,
        budget_strict=True,
    )

    estimate = estimate_trip_cost(_candidate(), request)

    assert estimate.floor_total_rub <= request.budget_total_rub < estimate.safe_total_rub
    assert estimate.budget_fit == "likely_within"
