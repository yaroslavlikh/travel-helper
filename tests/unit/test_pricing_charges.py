from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.pricing.models import (
    CostComponent,
    EntryCharge,
    EntryChargeRegistry,
    FxRate,
    FxRateTable,
    MoneyRange,
    PricingRequest,
    SourceRef,
)
from app.pricing.normalization.charges import calculate_mandatory_charges_component
from app.pricing.scenario_generation import generate_date_scenarios

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)
SOURCE = SourceRef(
    source_id="entry-registry-source",
    provider="official-entry-registry",
    source_kind="manual",
    observed_at=NOW - timedelta(days=1),
    valid_until=NOW + timedelta(days=30),
    source_url="https://example.test/official-entry-rules",
)


def _request(**updates: object) -> PricingRequest:
    values: dict[str, object] = {
        "request_id": "charge-request",
        "origin_city_id": "moscow",
        "origin_iata": ("MOW",),
        "destination_id": "destination",
        "destination_iata": ("KUL",),
        "date_mode": "exact",
        "outbound_date": date(2026, 9, 12),
        "return_date": date(2026, 9, 19),
        "nights_min": 7,
        "nights_max": 7,
        "adults": 2,
        "children_ages": (10,),
        "infants": 1,
        "rooms": 1,
        "citizenship_country": "RU",
    }
    values.update(updates)
    return PricingRequest.model_validate(values)


def _registry(
    *charges: EntryCharge,
    review_status: str = "confirmed",
    source: SourceRef = SOURCE,
) -> EntryChargeRegistry:
    return EntryChargeRegistry.model_validate(
        {
            "registry_version": "entry-v1",
            "citizenship_country": "RU",
            "destination_country": "MY",
            "review_status": review_status,
            "charges": charges,
            "source": source,
        }
    )


def _calculate(
    registry: EntryChargeRegistry | None,
    *,
    request: PricingRequest | None = None,
    fx_rates: FxRateTable | None = None,
    stay: CostComponent | None = None,
):
    request = request or _request()
    scenario = generate_date_scenarios(request).scenarios[0]
    return calculate_mandatory_charges_component(
        request=request,
        scenario=scenario,
        destination_country="MY",
        registry=registry,
        as_of=NOW,
        fx_rates=fx_rates,
        stay=stay,
    )


def test_confirmed_empty_registry_is_explicit_zero() -> None:
    component = _calculate(_registry())

    assert component.amount == MoneyRange(floor=0, expected=0, safe=0)
    assert "подтверждено" in component.included[0]


def test_missing_citizenship_or_unknown_registry_never_becomes_zero() -> None:
    without_citizenship = _request(citizenship_country=None)

    assert _calculate(_registry(), request=without_citizenship).amount is None
    assert _calculate(None).amount is None
    assert _calculate(_registry(review_status="unknown")).amount is None


def test_per_person_and_per_night_charges_apply_age_rules() -> None:
    visa = EntryCharge(
        charge_id="adult-visa",
        charge_type="visa",
        age_min=18,
        amount=1_000,
        currency="RUB",
        basis="per_person",
        required=True,
    )
    tax = EntryCharge(
        charge_id="adult-tourist-tax",
        charge_type="tourist_tax",
        age_min=18,
        amount=100,
        currency="RUB",
        basis="per_night",
        required=True,
    )
    optional = EntryCharge(
        charge_id="optional-entry-addon",
        charge_type="entry_fee",
        amount=50_000,
        currency="RUB",
        basis="per_trip",
        required=False,
    )

    component = _calculate(_registry(visa, tax, optional))

    assert component.amount == MoneyRange(floor=3_400, expected=3_400, safe=3_400)


def test_foreign_charge_uses_nominal_aware_fx_and_source() -> None:
    usd_fee = EntryCharge(
        charge_id="eta",
        charge_type="eta",
        amount=10,
        currency="USD",
        basis="per_person",
        required=True,
    )
    fx_source = SOURCE.model_copy(
        update={"source_id": "fx-source", "provider": "cbr", "source_kind": "cached"}
    )
    rates = FxRateTable(
        table_version="cbr-v1",
        effective_date=NOW.date(),
        fetched_at=NOW,
        rates=(FxRate(char_code="USD", nominal=10, value_rub=900),),
        source=fx_source,
    )

    component = _calculate(_registry(usd_fee), fx_rates=rates)

    assert component.amount == MoneyRange(floor=3_600, expected=3_600, safe=3_600)
    assert fx_source in component.sources


def test_foreign_charge_without_fx_is_missing() -> None:
    usd_fee = EntryCharge(
        charge_id="eta",
        charge_type="eta",
        amount=10,
        currency="USD",
        basis="per_person",
        required=True,
    )

    assert _calculate(_registry(usd_fee)).amount is None


def test_percent_stay_charge_uses_each_stay_range_value() -> None:
    request = _request()
    scenario = generate_date_scenarios(request).scenarios[0]
    stay = CostComponent(
        scenario_id=scenario.scenario_id,
        name="stay",
        amount=MoneyRange(floor=50_000, expected=60_000, safe=80_000),
        status="available",
        sources=(SOURCE,),
    )
    tax = EntryCharge(
        charge_id="city-tax",
        charge_type="tourist_tax",
        amount=10,
        currency="RUB",
        basis="percent_stay",
        required=True,
    )

    component = _calculate(_registry(tax), request=request, stay=stay)

    assert component.amount == MoneyRange(floor=5_000, expected=6_000, safe=8_000)


def test_stale_or_needs_review_registry_keeps_old_amount_with_warning() -> None:
    fee = EntryCharge(
        charge_id="entry",
        charge_type="entry_fee",
        amount=500,
        currency="RUB",
        basis="per_trip",
        required=True,
    )

    component = _calculate(_registry(fee, review_status="needs_review"))

    assert component.amount == MoneyRange(floor=500, expected=500, safe=500)
    assert component.status == "stale"
    assert "ручной проверки" in component.warnings[0]
