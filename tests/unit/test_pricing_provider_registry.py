from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.pricing.models import DateScenario, FlightOffer, PricingRequest, SourceRef, StayOffer
from app.pricing.providers.fixture import FixtureFlightPriceProvider, FixtureStayPriceProvider
from app.pricing.registry import create_pricing_provider_registry

NOW = datetime(2026, 7, 29, tzinfo=UTC)
SCENARIO = DateScenario(
    scenario_id="scenario-1",
    outbound_date=date(2026, 8, 15),
    return_date=date(2026, 8, 20),
    nights=5,
)
REQUEST = PricingRequest(
    request_id="request-1",
    origin_city_id="moscow",
    origin_iata=("MOW",),
    destination_id="istanbul",
    destination_iata=("IST",),
    date_mode="exact",
    outbound_date=SCENARIO.outbound_date,
    return_date=SCENARIO.return_date,
    nights_min=5,
    nights_max=5,
    adults=1,
    rooms=1,
)
SOURCE = SourceRef(
    source_id="fixture-offer",
    provider="test-fixture",
    source_kind="fixture",
    observed_at=NOW,
    valid_until=NOW + timedelta(days=1),
)


@pytest.mark.asyncio
async def test_fixture_providers_return_only_an_exact_full_scenario_match() -> None:
    flight = FlightOffer(
        provider="test-fixture",
        offer_id="flight-1",
        scenario_id=SCENARIO.scenario_id,
        itinerary_key="fixture-itinerary",
        origin_iata="MOW",
        destination_iata="IST",
        total_rub=Decimal("30000"),
        adults=1,
        outbound_departure=NOW + timedelta(days=17),
        outbound_arrival=NOW + timedelta(days=17, hours=4),
        return_departure=NOW + timedelta(days=22),
        return_arrival=NOW + timedelta(days=22, hours=4),
        stops_outbound=0,
        stops_return=0,
        duration_minutes_total=480,
        baggage_status="included",
        taxes_included=True,
        mandatory_fees_included=True,
        self_transfer=False,
        source=SOURCE,
    )
    stay = StayOffer(
        provider="test-fixture",
        offer_id="stay-1",
        property_id="property-1",
        product_id="rate-1",
        scenario_id=SCENARIO.scenario_id,
        checkin=SCENARIO.outbound_date,
        checkout=SCENARIO.return_date,
        adults=1,
        rooms=1,
        total_rub=Decimal("25000"),
        covers_full_stay=True,
        covers_full_party=True,
        mandatory_charges_complete=True,
        private_room=True,
        dorm=False,
        shared_bathroom=False,
        distance_center_km=Decimal("1"),
        cancellation="flexible",
        source=SOURCE,
    )

    flights = await FixtureFlightPriceProvider(
        (flight, flight.model_copy(update={"adults": 2}))
    ).search(REQUEST, SCENARIO)
    stays = await FixtureStayPriceProvider((stay, stay.model_copy(update={"rooms": 2}))).search(
        REQUEST, SCENARIO
    )

    assert flights == (flight,)
    assert stays == (stay,)


@pytest.mark.asyncio
async def test_live_mode_without_credentials_returns_typed_unavailable_providers() -> None:
    registry = create_pricing_provider_registry(
        Settings(
            app_env="test",
            demo_mode=True,
            flight_provider_mode="live",
            stay_provider_mode="live",
            _env_file=None,
        )
    )

    assert [item.status for item in registry.public_statuses()] == [
        "missing_credentials",
        "missing_credentials",
    ]
    assert await registry.flight.search(REQUEST, SCENARIO) == ()
    assert await registry.stay.search(REQUEST, SCENARIO) == ()
