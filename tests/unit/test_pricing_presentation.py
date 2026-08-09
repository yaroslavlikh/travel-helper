from datetime import UTC, date, datetime, timedelta

from app.domain.models import TravelRequest
from app.pricing.models import (
    CostComponent,
    DateScenario,
    FlightPriceSignal,
    MoneyRange,
    ScenarioPrice,
    SourceRef,
    TripPriceEstimate,
)
from app.services.pricing_presentation import cached_flight_card, pricing_card, unavailable_pricing


def test_unavailable_pricing_names_missing_critical_evidence() -> None:
    view = unavailable_pricing(
        TravelRequest(
            raw_query="Из Москвы в Батуми с 10 по 17 августа",
            origin_city="Москва",
            date_from="2026-08-10",
            date_to="2026-08-17",
            adults=1,
        )
    )

    assert view.status == "unavailable"
    assert view.floor_total_rub is None
    assert view.expected_total_rub is None
    assert view.safe_total_rub is None
    assert [item.component for item in view.components] == ["flight", "stay"]
    assert "live provider" in view.components[0].reason


def test_complete_snapshot_becomes_numeric_price_card() -> None:
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    scenario = DateScenario(
        scenario_id="scenario-1",
        outbound_date=date(2026, 8, 10),
        return_date=date(2026, 8, 17),
        nights=7,
    )
    source = SourceRef(
        source_id="live-flight",
        provider="flight-provider",
        source_kind="live",
        observed_at=now,
        valid_until=now + timedelta(minutes=30),
    )
    flight = CostComponent(
        scenario_id=scenario.scenario_id,
        name="flight",
        amount=MoneyRange(floor=40_000, expected=50_000, safe=60_000),
        status="available",
        sources=(source,),
    )
    priced = ScenarioPrice(
        scenario=scenario,
        components=(flight,),
        total=MoneyRange(floor=40_000, expected=50_000, safe=60_000),
    )
    snapshot = TripPriceEstimate(
        pricing_snapshot_id="ps_snapshot_1",
        pricing_version="pricing-core-v1",
        request_hash="request-hash",
        scenario_count_generated=1,
        scenario_count_priced=1,
        total=priced.total,
        components=priced.components,
        selected_scenario_id=scenario.scenario_id,
        scenarios=(priced,),
        confidence="medium",
        calculated_at=now,
        valid_until=source.valid_until,
    )

    view = pricing_card(
        request=TravelRequest(raw_query="Из Москвы в Батуми"),
        snapshot=snapshot,
    )

    assert view.status == "available"
    assert view.expected_total_rub == 50_000
    assert view.headline == "≈ 50 000 ₽"
    assert view.components[0].expected_rub == 50_000


def test_cached_card_discloses_when_api_omits_source_age() -> None:
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    signal = FlightPriceSignal(
        signal_id="cached-signal-1",
        scenario_id="scenario-1",
        origin_iata="MOW",
        destination_iata="IST",
        outbound_date=date(2026, 8, 10),
        return_date=date(2026, 8, 17),
        amount_rub=40_000,
        source=SourceRef(
            source_id="cached-flight",
            provider="aviasales-data",
            source_kind="cached",
            observed_at=now,
        ),
    )

    view = cached_flight_card(signal)

    assert view.status == "partial"
    assert "Время исходного поиска API не передаёт" in view.freshness_label
