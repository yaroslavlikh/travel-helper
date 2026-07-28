from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.pricing.models import (
    MoneyRange,
    PricingRequest,
    SourceRef,
    StayOffer,
    StayProfileRules,
)
from app.pricing.normalization.stays import aggregate_stay_offers
from app.pricing.scenario_generation import generate_date_scenarios

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def _request(**updates: object) -> PricingRequest:
    values: dict[str, object] = {
        "request_id": "request-live-stay",
        "origin_city_id": "moscow",
        "origin_iata": ("MOW",),
        "destination_id": "istanbul",
        "destination_iata": ("IST",),
        "date_mode": "exact",
        "outbound_date": date(2026, 9, 12),
        "return_date": date(2026, 9, 19),
        "nights_min": 7,
        "nights_max": 7,
        "adults": 2,
        "rooms": 1,
        "accommodation_profile": "standard",
    }
    values.update(updates)
    return PricingRequest.model_validate(values)


def _rules(**updates: object) -> StayProfileRules:
    values: dict[str, object] = {
        "rules_version": "istanbul-standard-v1",
        "profile": "standard",
        "minimum_rating": Decimal("7.5"),
        "minimum_review_count": 30,
        "maximum_distance_km": Decimal("5"),
        "require_private_room": True,
        "allow_shared_bathroom": False,
        "require_flexible_cancellation": False,
    }
    values.update(updates)
    return StayProfileRules.model_validate(values)


def _offer(
    offer_id: str,
    amount: int,
    *,
    property_id: str | None = None,
    product_id: str | None = None,
    **updates: object,
) -> StayOffer:
    request = _request()
    scenario = generate_date_scenarios(request).scenarios[0]
    source = SourceRef(
        source_id=f"source-{offer_id}",
        provider="booking-demand",
        source_kind="live",
        observed_at=NOW,
        valid_until=NOW + timedelta(minutes=30),
    )
    values: dict[str, object] = {
        "provider": "booking-demand",
        "offer_id": offer_id,
        "property_id": property_id or f"property-{offer_id}",
        "product_id": product_id or f"product-{offer_id}",
        "scenario_id": scenario.scenario_id,
        "checkin": scenario.outbound_date,
        "checkout": scenario.return_date,
        "adults": 2,
        "children": 0,
        "rooms": 1,
        "total_rub": Decimal(amount),
        "mandatory_excluded_rub": Decimal(0),
        "extra_local_transport_rub": Decimal(0),
        "covers_full_stay": True,
        "covers_full_party": True,
        "mandatory_charges_complete": True,
        "private_room": True,
        "dorm": False,
        "shared_bathroom": False,
        "in_preferred_area": True,
        "rating": Decimal("8.0"),
        "review_count": 100,
        "distance_center_km": Decimal("2.5"),
        "cancellation": "flexible",
        "source": source,
    }
    values.update(updates)
    return StayOffer.model_validate(values)


def _aggregate(
    offers: tuple[StayOffer, ...],
    *,
    request: PricingRequest | None = None,
    rules: StayProfileRules | None = None,
):
    request = request or _request()
    scenario = generate_date_scenarios(request).scenarios[0]
    return aggregate_stay_offers(
        request=request,
        scenario=scenario,
        offers=offers,
        rules=rules or _rules(),
    )


def test_stay_total_adds_mandatory_charges_once_without_room_or_night_multiplier() -> None:
    component = _aggregate(
        (
            _offer(
                "hotel",
                70_000,
                mandatory_excluded_rub=Decimal("5000"),
                extra_local_transport_rub=Decimal("3000"),
            ),
        )
    )

    assert component.amount == MoneyRange(floor=78_000, expected=78_000, safe=78_000)
    assert "не умножается повторно" in component.assumptions[1]


@pytest.mark.parametrize(
    "updates",
    [
        {"checkin": date(2026, 9, 13)},
        {"adults": 1},
        {"rooms": 2},
        {"covers_full_stay": False},
        {"covers_full_party": False},
        {"mandatory_charges_complete": False},
        {"private_room": False},
        {"shared_bathroom": True},
        {"rating": Decimal("7.4")},
        {"review_count": 20},
        {"distance_center_km": Decimal("5.1")},
    ],
)
def test_standard_profile_rejects_wrong_dates_occupancy_or_quality(
    updates: dict[str, object],
) -> None:
    component = _aggregate((_offer("invalid", 50_000, **updates),))

    assert component.amount is None
    assert component.status == "missing"


def test_dorm_requires_explicit_request_even_for_economy() -> None:
    economy_request = _request(accommodation_profile="economy")
    economy_rules = _rules(
        profile="economy",
        rules_version="istanbul-economy-v1",
        minimum_rating=Decimal("7.0"),
        minimum_review_count=0,
        maximum_distance_km=Decimal("10"),
        require_private_room=False,
        allow_shared_bathroom=True,
    )
    dorm = _offer("dorm", 20_000, private_room=False, dorm=True, shared_bathroom=True)

    assert _aggregate((dorm,), request=economy_request, rules=economy_rules).amount is None
    allowed = economy_request.model_copy(update={"allow_dorm": True})
    assert _aggregate((dorm,), request=allowed, rules=economy_rules).amount is not None


def test_comfort_profile_requires_confirmed_preferred_area() -> None:
    comfort_request = _request(accommodation_profile="comfort")
    comfort_rules = _rules(
        profile="comfort",
        rules_version="istanbul-comfort-v1",
        minimum_rating=Decimal("8.0"),
        minimum_review_count=50,
        maximum_distance_km=Decimal("5"),
        require_preferred_area=True,
    )

    outside = _offer("outside", 80_000, in_preferred_area=False)
    unknown = _offer("unknown", 80_000, in_preferred_area=None)
    inside = _offer("inside", 80_000, in_preferred_area=True)

    assert (
        _aggregate((outside, unknown), request=comfort_request, rules=comfort_rules).amount is None
    )
    assert _aggregate((inside,), request=comfort_request, rules=comfort_rules).amount is not None


def test_stay_basket_uses_cheap_acceptable_objects() -> None:
    component = _aggregate(
        tuple(
            _offer(str(index), amount)
            for index, amount in enumerate(range(50_000, 150_000, 10_000))
        )
    )

    assert component.amount == MoneyRange(floor=60_000, expected=80_000, safe=120_000)
    assert "outlier" in component.warnings[0]


def test_stay_lower_outlier_is_removed() -> None:
    component = _aggregate(
        (
            _offer("bait", 10_000),
            _offer("normal-1", 50_000),
            _offer("normal-2", 55_000),
            _offer("normal-3", 60_000),
        )
    )

    assert component.amount == MoneyRange(floor=50_000, expected=55_000, safe=60_000)
    assert "outlier" in component.warnings[0]


def test_duplicate_property_product_keeps_cheapest_total() -> None:
    component = _aggregate(
        (
            _offer("expensive", 70_000, property_id="p1", product_id="room1"),
            _offer("cheap", 60_000, property_id="p1", product_id="room1"),
        )
    )

    assert component.amount == MoneyRange(floor=60_000, expected=60_000, safe=60_000)
