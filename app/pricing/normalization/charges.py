"""Deterministic mandatory entry and tourist-charge calculation."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.pricing.models import (
    CostComponent,
    DateScenario,
    EntryCharge,
    EntryChargeRegistry,
    FxRateTable,
    MoneyRange,
    PricingRequest,
)
from app.pricing.normalization.money import convert_to_rub


def calculate_mandatory_charges_component(
    *,
    request: PricingRequest,
    scenario: DateScenario,
    destination_country: str,
    registry: EntryChargeRegistry | None,
    as_of: datetime,
    fx_rates: FxRateTable | None = None,
    stay: CostComponent | None = None,
) -> CostComponent:
    """Apply reviewed charge rules; unknown coverage is never interpreted as zero."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if request.citizenship_country is None:
        return _missing(scenario, "Не указано гражданство для проверки правил въезда.")
    destination = destination_country.upper()
    if registry is None or registry.review_status == "unknown":
        return _missing(scenario, "Нет проверенного реестра обязательных сборов.")
    if (
        registry.citizenship_country != request.citizenship_country
        or registry.destination_country != destination
    ):
        return _missing(scenario, "Реестр не соответствует гражданству или стране поездки.")

    stale = registry.review_status in {"stale", "needs_review"} or (
        registry.source.valid_until is not None and registry.source.valid_until <= as_of
    )
    totals = [Decimal(0), Decimal(0), Decimal(0)]
    used_rates = False
    included: list[str] = []
    for charge in registry.charges:
        if not charge.required:
            continue
        contribution, converted = _charge_amounts(
            charge=charge,
            request=request,
            scenario=scenario,
            fx_rates=fx_rates,
            stay=stay,
        )
        if contribution is None:
            return _missing(
                scenario,
                f"Не хватает evidence для обязательного сбора {charge.charge_id}.",
            )
        totals = [current + value for current, value in zip(totals, contribution, strict=True)]
        used_rates = used_rates or converted
        included.append(charge.charge_type)

    sources = [registry.source]
    if used_rates and fx_rates is not None:
        sources.append(fx_rates.source)
    amount = MoneyRange(
        floor=_rubles(totals[0]),
        expected=_rubles(totals[1]),
        safe=_rubles(totals[2]),
    )
    warnings = ("Реестр обязательных сборов устарел или ожидает ручной проверки.",) if stale else ()
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name="mandatory_charges",
        amount=amount,
        status="stale" if stale else "available",
        included=tuple(dict.fromkeys(included)) or ("отсутствие обязательных сборов подтверждено",),
        excluded=("необязательная страховка и recommended add-ons",),
        assumptions=(
            f"Registry {registry.registry_version}; citizenship "
            f"{registry.citizenship_country}; destination {destination}.",
        ),
        warnings=warnings,
        sources=tuple(dict.fromkeys(sources)),
    )


def _charge_amounts(
    *,
    charge: EntryCharge,
    request: PricingRequest,
    scenario: DateScenario,
    fx_rates: FxRateTable | None,
    stay: CostComponent | None,
) -> tuple[tuple[Decimal, Decimal, Decimal] | None, bool]:
    if charge.basis == "percent_stay":
        if stay is None or stay.amount is None:
            return None, False
        ratio = charge.amount / Decimal(100)
        return (
            (
                Decimal(stay.amount.floor) * ratio,
                Decimal(stay.amount.expected) * ratio,
                Decimal(stay.amount.safe) * ratio,
            ),
            False,
        )

    eligible = _eligible_travellers(charge, request)
    if charge.basis == "per_trip":
        multiplier = Decimal(1) if eligible else Decimal(0)
    elif charge.basis == "per_night":
        multiplier = Decimal(eligible * scenario.nights)
    else:
        multiplier = Decimal(eligible)
    if charge.currency == "RUB":
        unit_rub = charge.amount
        converted = False
    else:
        if fx_rates is None:
            return None, False
        try:
            unit_rub = convert_to_rub(charge.amount, charge.currency, fx_rates)
        except KeyError:
            return None, False
        converted = True
    total = unit_rub * multiplier
    return (total, total, total), converted


def _eligible_travellers(charge: EntryCharge, request: PricingRequest) -> int:
    ages = [18] * request.adults
    ages.extend([1] * request.infants)
    ages.extend(request.children_ages)
    return sum(
        1
        for age in ages
        if (charge.age_min is None or age >= charge.age_min)
        and (charge.age_max is None or age <= charge.age_max)
    )


def _missing(scenario: DateScenario, warning: str) -> CostComponent:
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name="mandatory_charges",
        amount=None,
        status="missing",
        warnings=(warning,),
    )


def _rubles(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
