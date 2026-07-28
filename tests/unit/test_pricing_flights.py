from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.pricing.models import (
    FlightOffer,
    MoneyRange,
    PricingRequest,
    SourceRef,
)
from app.pricing.normalization.flights import aggregate_flight_offers
from app.pricing.scenario_generation import generate_date_scenarios

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def _request(**updates: object) -> PricingRequest:
    values: dict[str, object] = {
        "request_id": "request-live-flight",
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
        "baggage": "required",
    }
    values.update(updates)
    return PricingRequest.model_validate(values)


def _offer(
    offer_id: str,
    amount: int,
    *,
    itinerary_key: str | None = None,
    baggage_status: str = "included",
    baggage_extra_rub: int | None = None,
    revalidated: bool = True,
    **updates: object,
) -> FlightOffer:
    request = _request()
    scenario = generate_date_scenarios(request).scenarios[0]
    source = SourceRef(
        source_id=f"source-{offer_id}",
        provider="amadeus",
        source_kind="live",
        observed_at=NOW,
        valid_until=NOW + timedelta(minutes=10),
    )
    values: dict[str, object] = {
        "provider": "amadeus",
        "offer_id": offer_id,
        "scenario_id": scenario.scenario_id,
        "itinerary_key": itinerary_key or f"itinerary-{offer_id}",
        "origin_iata": "MOW",
        "destination_iata": "IST",
        "total_rub": Decimal(amount),
        "adults": 2,
        "children": 0,
        "infants": 0,
        "outbound_departure": datetime(2026, 9, 12, 8, tzinfo=UTC),
        "outbound_arrival": datetime(2026, 9, 12, 13, tzinfo=UTC),
        "return_departure": datetime(2026, 9, 19, 15, tzinfo=UTC),
        "return_arrival": datetime(2026, 9, 19, 20, tzinfo=UTC),
        "stops_outbound": 0,
        "stops_return": 0,
        "duration_minutes_total": 600,
        "baggage_status": baggage_status,
        "baggage_extra_rub": baggage_extra_rub,
        "taxes_included": True,
        "mandatory_fees_included": True,
        "self_transfer": False,
        "revalidated": revalidated,
        "expires_at": NOW + timedelta(minutes=10),
        "source": source,
    }
    values.update(updates)
    return FlightOffer.model_validate(values)


def _aggregate(
    offers: tuple[FlightOffer, ...],
    request: PricingRequest | None = None,
):
    request = request or _request()
    scenario = generate_date_scenarios(request).scenarios[0]
    return aggregate_flight_offers(
        request=request,
        scenario=scenario,
        offers=offers,
        now=NOW,
    )


def test_live_flight_uses_full_party_baggage_and_cheap_acceptable_basket() -> None:
    component = _aggregate(
        (
            _offer("a", 60_000),
            _offer("b", 70_000),
            _offer("c", 80_000),
            _offer("d", 90_000),
            _offer("e", 100_000),
        )
    )

    assert component.amount == MoneyRange(floor=60_000, expected=70_000, safe=90_000)
    assert component.status == "available"
    assert "вся указанная группа" in component.included


def test_known_baggage_extra_is_added_when_baggage_is_not_excluded() -> None:
    component = _aggregate(
        (
            _offer(
                "with-extra",
                60_000,
                baggage_status="known_extra_price",
                baggage_extra_rub=8_000,
            ),
        )
    )

    assert component.amount == MoneyRange(floor=68_000, expected=68_000, safe=68_000)


@pytest.mark.parametrize(
    "updates",
    [
        {"origin_iata": "LED"},
        {"adults": 1},
        {"taxes_included": False},
        {"mandatory_fees_included": False},
        {"self_transfer": True},
        {"expires_at": NOW},
        {"outbound_departure": datetime(2026, 9, 11, 8, tzinfo=UTC)},
    ],
)
def test_invalid_route_party_or_offer_evidence_never_becomes_component(
    updates: dict[str, object],
) -> None:
    component = _aggregate((_offer("invalid", 60_000, **updates),))

    assert component.amount is None
    assert component.status == "missing"


def test_explicit_stops_and_duration_limits_are_hard_filters() -> None:
    request = _request(max_stops=0, max_flight_minutes=500)
    component = _aggregate(
        (
            _offer(
                "too-long",
                60_000,
                stops_outbound=1,
                duration_minutes_total=600,
            ),
        ),
        request,
    )

    assert component.amount is None


def test_unknown_required_baggage_can_never_define_expected_or_safe() -> None:
    component = _aggregate(
        (
            _offer(
                "unknown-bag",
                50_000,
                baggage_status="not_included_unknown_price",
            ),
        )
    )

    assert component.amount is None
    assert component.status == "missing"
    assert "неподтверждённая стоимость требуемого багажа" in component.excluded


def test_search_only_offer_requires_price_revalidation() -> None:
    component = _aggregate((_offer("search-only", 50_000, revalidated=False),))

    assert component.amount is None
    assert component.status == "missing"


def test_unrequired_baggage_accepts_base_offer_without_guessing_extra() -> None:
    request = _request(baggage="not_required")
    component = _aggregate(
        (
            _offer(
                "no-bag",
                50_000,
                baggage_status="not_included_unknown_price",
            ),
        ),
        request,
    )

    assert component.amount == MoneyRange(floor=50_000, expected=50_000, safe=50_000)


def test_bait_price_requires_revalidation_and_known_baggage() -> None:
    offers = (
        _offer("bait", 20_000, revalidated=False),
        _offer("normal-1", 60_000),
        _offer("normal-2", 62_000),
        _offer("normal-3", 64_000),
    )
    component = _aggregate(offers)

    assert component.amount == MoneyRange(floor=60_000, expected=62_000, safe=64_000)
    assert "подозрительно дешёвых" in component.warnings[0]

    accepted = _aggregate(
        (
            _offer("bait", 20_000, revalidated=True),
            *offers[1:],
        )
    )
    assert accepted.amount is not None
    assert accepted.amount.floor == 20_000


def test_duplicate_itinerary_keeps_cheapest_complete_offer() -> None:
    component = _aggregate(
        (
            _offer("expensive", 70_000, itinerary_key="same-itinerary"),
            _offer("cheap", 60_000, itinerary_key="same-itinerary"),
        )
    )

    assert component.amount == MoneyRange(floor=60_000, expected=60_000, safe=60_000)


def test_two_acceptable_offers_use_higher_for_expected_and_safe() -> None:
    component = _aggregate((_offer("a", 60_000), _offer("b", 75_000)))

    assert component.amount == MoneyRange(floor=60_000, expected=75_000, safe=75_000)
