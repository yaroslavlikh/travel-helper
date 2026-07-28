from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.pricing import (
    CostComponent,
    MoneyRange,
    PricingRequest,
    SourceRef,
    aggregate_scenarios,
    build_pricing_snapshot,
    calculate_scenario,
    generate_date_scenarios,
)
from app.pricing.errors import PricingInvariantError


def _request(**updates: object) -> PricingRequest:
    values: dict[str, object] = {
        "request_id": "request-1",
        "origin_city_id": "moscow",
        "origin_iata": ("MOW",),
        "destination_id": "istanbul",
        "destination_iata": ("IST", "SAW"),
        "date_mode": "exact",
        "outbound_date": date(2026, 9, 12),
        "return_date": date(2026, 9, 19),
        "nights_min": 7,
        "nights_max": 7,
        "adults": 2,
        "rooms": 1,
    }
    values.update(updates)
    return PricingRequest.model_validate(values)


def _source(*, valid_until: datetime | None = None) -> SourceRef:
    observed = datetime(2026, 7, 28, 12, tzinfo=UTC)
    return SourceRef(
        source_id="source-1",
        provider="contract-test",
        source_kind="live",
        observed_at=observed,
        valid_until=valid_until or observed + timedelta(minutes=15),
    )


def _component(
    scenario_id: str,
    name: str,
    floor: int,
    expected: int,
    safe: int,
) -> CostComponent:
    return CostComponent(
        scenario_id=scenario_id,
        name=name,  # type: ignore[arg-type]
        amount=MoneyRange(floor=floor, expected=expected, safe=safe),
        status="available",
        sources=(_source(),),
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"return_date": date(2026, 9, 12)},
        {"return_date": None},
        {"nights_min": 8, "nights_max": 7},
        {"infants": 3},
        {"children_ages": (8,) * 8},
        {"origin_iata": ("MOSCOW",)},
        {"month": "2026-09"},
    ],
)
def test_pricing_request_rejects_ambiguous_or_invalid_input(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _request(**updates)


def test_exact_dates_create_one_whole_scenario() -> None:
    batch = generate_date_scenarios(_request())

    assert batch.generated_count == 1
    assert not batch.sampling_applied
    assert len(batch.scenarios) == 1
    assert batch.scenarios[0].nights == 7


def test_window_generation_is_bounded_and_deterministic() -> None:
    request = _request(
        date_mode="window",
        outbound_date=None,
        return_date=None,
        departure_from=date(2026, 8, 1),
        departure_to=date(2026, 8, 31),
        nights_min=5,
        nights_max=10,
    )

    first = generate_date_scenarios(request)
    second = generate_date_scenarios(request)

    assert first == second
    assert first.generated_count == 186
    assert first.sampling_applied
    assert len(first.scenarios) == 60
    assert first.scenarios[0].outbound_date == date(2026, 8, 1)
    assert first.scenarios[-1].outbound_date == date(2026, 8, 31)


def test_month_generation_uses_real_calendar_boundaries() -> None:
    request = _request(
        date_mode="month",
        outbound_date=None,
        return_date=None,
        month="2028-02",
        nights_min=7,
        nights_max=7,
    )

    batch = generate_date_scenarios(request)

    assert batch.generated_count == 29
    assert batch.scenarios[0].outbound_date == date(2028, 2, 1)
    assert batch.scenarios[-1].outbound_date == date(2028, 2, 29)


def test_scenario_never_mixes_components_from_different_dates() -> None:
    scenario = generate_date_scenarios(_request()).scenarios[0]
    foreign = scenario.model_copy(update={"scenario_id": "ds_foreign_scenario"})

    with pytest.raises(PricingInvariantError, match="different date scenarios"):
        calculate_scenario(
            scenario,
            (
                _component(scenario.scenario_id, "flight", 50_000, 55_000, 60_000),
                _component(foreign.scenario_id, "stay", 40_000, 45_000, 50_000),
            ),
        )


def test_missing_flight_or_stay_never_becomes_zero() -> None:
    scenario = generate_date_scenarios(_request()).scenarios[0]

    priced = calculate_scenario(
        scenario,
        (_component(scenario.scenario_id, "stay", 40_000, 45_000, 50_000),),
    )

    assert priced.total is None
    assert "flight" in priced.missing_components


def test_scenario_total_uses_recommended_only_for_safe() -> None:
    scenario = generate_date_scenarios(_request()).scenarios[0]
    priced = calculate_scenario(
        scenario,
        (
            _component(scenario.scenario_id, "flight", 50_000, 55_000, 60_000),
            _component(scenario.scenario_id, "stay", 40_000, 45_000, 50_000),
            _component(scenario.scenario_id, "food", 10_000, 12_000, 14_000),
            _component(scenario.scenario_id, "recommended", 2_000, 3_000, 5_000),
        ),
    )

    assert priced.total == MoneyRange(floor=100_000, expected=112_000, safe=127_000)


def test_aggregation_uses_complete_scenarios_and_preserves_ordering() -> None:
    request = _request(
        date_mode="window",
        outbound_date=None,
        return_date=None,
        departure_from=date(2026, 9, 12),
        departure_to=date(2026, 9, 14),
        nights_min=7,
        nights_max=7,
    )
    scenarios = generate_date_scenarios(request).scenarios
    totals = (
        (90_000, 100_000, 110_000),
        (100_000, 120_000, 150_000),
        (80_000, 110_000, 130_000),
    )
    priced = tuple(
        calculate_scenario(
            scenario,
            (
                _component(scenario.scenario_id, "flight", *total),
                _component(scenario.scenario_id, "stay", 0, 0, 0),
            ),
        )
        for scenario, total in zip(scenarios, totals, strict=True)
    )

    result = aggregate_scenarios(priced)

    assert result == MoneyRange(floor=80_000, expected=110_000, safe=140_000)


def test_snapshot_is_replayable_and_keeps_source_freshness() -> None:
    request = _request()
    batch = generate_date_scenarios(request)
    scenario = batch.scenarios[0]
    priced = calculate_scenario(
        scenario,
        (
            _component(scenario.scenario_id, "flight", 50_000, 55_000, 60_000),
            _component(scenario.scenario_id, "stay", 40_000, 45_000, 50_000),
        ),
    )
    calculated_at = datetime(2026, 7, 28, 12, tzinfo=UTC)

    first = build_pricing_snapshot(
        request=request,
        batch=batch,
        scenario_prices=(priced,),
        calculated_at=calculated_at,
    )
    second = build_pricing_snapshot(
        request=request,
        batch=batch,
        scenario_prices=(priced,),
        calculated_at=calculated_at,
    )

    assert first == second
    assert first.pricing_snapshot_id == second.pricing_snapshot_id
    assert first.total == MoneyRange(floor=90_000, expected=100_000, safe=110_000)
    assert first.valid_until == datetime(2026, 7, 28, 12, 15, tzinfo=UTC)


def test_incomplete_snapshot_has_no_total_and_explicit_warning() -> None:
    request = _request()
    batch = generate_date_scenarios(request)
    scenario = batch.scenarios[0]
    priced = calculate_scenario(
        scenario,
        (_component(scenario.scenario_id, "stay", 40_000, 45_000, 50_000),),
    )

    snapshot = build_pricing_snapshot(
        request=request,
        batch=batch,
        scenario_prices=(priced,),
        calculated_at=datetime(2026, 7, 28, 12, tzinfo=UTC),
    )

    assert snapshot.total is None
    assert snapshot.confidence == "insufficient"
    assert "flight" in snapshot.missing_components
    assert "Нет полного сценария с перелётом и проживанием." in snapshot.warnings
