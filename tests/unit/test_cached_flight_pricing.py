from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.models import DestinationCandidate, TravelRequest
from app.pricing.models import FlightPriceSignal, PricingRequest, ScenarioBatch, SourceRef
from app.services.cached_flight_pricing import (
    _discovery_scenarios,
    discover_cached_flights,
    pricing_request_for_candidate,
)
from app.services.pricing_presentation import cached_flight_card

NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)


class CachedProvider:
    async def search(
        self, request: PricingRequest, batch: ScenarioBatch, *, now: datetime
    ) -> tuple[FlightPriceSignal, ...]:
        scenario = batch.scenarios[0]
        return (
            FlightPriceSignal(
                signal_id="signal-istanbul",
                scenario_id=scenario.scenario_id,
                origin_iata="MOW",
                destination_iata="IST",
                outbound_date=scenario.outbound_date,
                return_date=scenario.return_date,
                amount_rub=Decimal("25000"),
                airline="TK",
                stops=0,
                return_stops=0,
                duration_minutes=600,
                found_at=NOW - timedelta(hours=2),
                expires_at=NOW + timedelta(hours=12),
                fetched_at=NOW,
                age_hours=2,
                confidence=0.65,
                provider_url="https://www.aviasales.ru/MOW1009IST1709",
                source=SourceRef(
                    source_id="source-istanbul",
                    provider="aviasales-data",
                    source_kind="cached",
                    observed_at=NOW - timedelta(hours=2),
                    valid_until=NOW + timedelta(hours=12),
                ),
            ),
        )


def _request() -> TravelRequest:
    return TravelRequest(
        raw_query="Из Москвы в Стамбул с 10 по 17 сентября",
        origin_city="Москва",
        date_from=date(2026, 9, 10),
        date_to=date(2026, 9, 17),
        adults=1,
        budget_total_rub=100_000,
        budget_strict=True,
    )


def _candidate() -> DestinationCandidate:
    return DestinationCandidate(
        destination_id="istanbul",
        country="Турция",
        city_or_region="Стамбул",
        nearest_airport="IST",
    )


def test_exact_trip_maps_to_one_cached_round_trip_query() -> None:
    pricing_request = pricing_request_for_candidate(_request(), _candidate())

    assert pricing_request is not None
    assert pricing_request.date_mode == "exact"
    assert pricing_request.origin_iata == ("MOW",)
    assert pricing_request.destination_iata == ("IST",)
    assert pricing_request.outbound_date == date(2026, 9, 10)
    assert pricing_request.return_date == date(2026, 9, 17)


@pytest.mark.asyncio
async def test_cached_signal_is_attached_without_a_trip_total_or_budget_pass() -> None:
    results = await discover_cached_flights(
        request=_request(), candidates=[_candidate()], provider=CachedProvider(), now=NOW
    )

    signal = results["istanbul"][0]
    view = cached_flight_card((signal,))
    assert signal.usable_for_total is False
    assert view.status == "partial"
    assert view.expected_total_rub is None
    assert "цена найдена ранее и проверяется при переходе" in view.subtitle
    assert "live-цена" in view.subtitle
    assert view.components[0].expected_rub == 25_000
    assert view.components[1].status == "missing"


def test_month_uses_seven_night_default_and_at_most_five_scenarios() -> None:
    request = _request().model_copy(update={"date_from": None, "date_to": None, "month": 9})
    pricing_request = pricing_request_for_candidate(request, _candidate())

    assert pricing_request is not None
    assert pricing_request.date_mode == "month"
    assert pricing_request.month == "2026-09"
    assert pricing_request.nights_min == pricing_request.nights_max == 7
    assert len(_discovery_scenarios(pricing_request).scenarios) == 5
