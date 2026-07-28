"""Deterministic date-scenario generation; no prices participate here."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from hashlib import sha256

from app.pricing.config import PRICING_CORE_CONFIG, PricingCoreConfig
from app.pricing.models import DateScenario, PricingRequest, ScenarioBatch


def generate_date_scenarios(
    request: PricingRequest, config: PricingCoreConfig = PRICING_CORE_CONFIG
) -> ScenarioBatch:
    """Build whole-trip date pairs and deterministically cap large candidate sets."""

    if request.date_mode == "exact":
        assert request.outbound_date is not None and request.return_date is not None
        scenarios = (_scenario(request.outbound_date, request.return_date),)
        return ScenarioBatch(generated_count=1, scenarios=scenarios)

    if request.date_mode == "window":
        assert request.departure_from is not None and request.departure_to is not None
        outbounds = _date_range(request.departure_from, request.departure_to)
    else:
        assert request.month is not None
        year, month = (int(part) for part in request.month.split("-"))
        first = date(year, month, 1)
        outbounds = _date_range(first, date(year, month, monthrange(year, month)[1]))

    all_scenarios = tuple(
        _scenario(outbound, outbound + timedelta(days=nights))
        for outbound in outbounds
        for nights in range(request.nights_min, request.nights_max + 1)
    )
    selected = _even_sample(all_scenarios, config.max_date_scenarios)
    return ScenarioBatch(
        generated_count=len(all_scenarios),
        scenarios=selected,
        sampling_applied=len(selected) < len(all_scenarios),
    )


def _date_range(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))


def _scenario(outbound: date, return_date: date) -> DateScenario:
    scenario_key = f"{outbound.isoformat()}|{return_date.isoformat()}"
    return DateScenario(
        scenario_id=f"ds_{sha256(scenario_key.encode()).hexdigest()[:20]}",
        outbound_date=outbound,
        return_date=return_date,
        nights=(return_date - outbound).days,
    )


def _even_sample(scenarios: tuple[DateScenario, ...], limit: int) -> tuple[DateScenario, ...]:
    if len(scenarios) <= limit:
        return scenarios
    if limit == 1:
        return (scenarios[0],)
    indexes = {round(index * (len(scenarios) - 1) / (limit - 1)) for index in range(limit)}
    return tuple(scenarios[index] for index in sorted(indexes))
