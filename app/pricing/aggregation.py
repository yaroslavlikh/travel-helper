"""Scenario-local arithmetic and cross-scenario aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.pricing.config import PRICING_CORE_CONFIG, PricingCoreConfig
from app.pricing.errors import PricingInvariantError
from app.pricing.models import (
    ComponentName,
    CostComponent,
    DateScenario,
    MoneyRange,
    ScenarioPrice,
)

CRITICAL_COMPONENTS: frozenset[ComponentName] = frozenset({"flight", "stay"})
COMPONENT_NAMES: tuple[ComponentName, ...] = (
    "flight",
    "stay",
    "airport_transfer",
    "food",
    "local_transport",
    "activities",
    "mandatory_charges",
    "recommended",
)


def calculate_scenario(
    scenario: DateScenario,
    components: tuple[CostComponent, ...],
) -> ScenarioPrice:
    """Sum only components belonging to one scenario; missing critical data blocks total."""

    scenario_id = scenario.scenario_id
    names = {component.name for component in components}
    if len(names) != len(components):
        raise PricingInvariantError("scenario contains duplicate components")
    if any(component.scenario_id != scenario_id for component in components):
        raise PricingInvariantError("cannot mix components from different date scenarios")

    missing = tuple(
        name
        for name in COMPONENT_NAMES
        if name not in names
        or next(component for component in components if component.name == name).amount is None
    )
    total = None
    if not CRITICAL_COMPONENTS.intersection(missing):
        regular = [
            component.amount
            for component in components
            if component.amount is not None and component.name != "recommended"
        ]
        recommended = next(
            (
                component.amount
                for component in components
                if component.name == "recommended" and component.amount is not None
            ),
            None,
        )
        total = MoneyRange(
            floor=sum(amount.floor for amount in regular),
            expected=sum(amount.expected for amount in regular),
            safe=sum(amount.safe for amount in regular)
            + (recommended.expected if recommended else 0),
        )
    return ScenarioPrice(
        scenario=scenario,
        components=components,
        total=total,
        missing_components=missing,
        assumptions=_unique(
            assumption for component in components for assumption in component.assumptions
        ),
        warnings=_unique(warning for component in components for warning in component.warnings),
    )


def aggregate_scenarios(
    scenarios: tuple[ScenarioPrice, ...],
    config: PricingCoreConfig = PRICING_CORE_CONFIG,
) -> MoneyRange | None:
    """Aggregate complete whole-trip scenarios without mixing their components."""

    complete = sorted(
        (scenario for scenario in scenarios if scenario.total is not None),
        key=lambda scenario: (
            scenario.total.expected,  # type: ignore[union-attr]
            scenario.scenario.outbound_date,
            scenario.scenario.return_date,
        ),
    )
    if not complete:
        return None
    if len(complete) == 1:
        return complete[0].total

    expected_basket = complete[: config.expected_scenario_basket]
    safe_basket = complete[: config.safe_scenario_basket]
    floor = min(item.total.floor for item in complete if item.total is not None)
    expected = _round_decimal(
        Decimal(str(median(item.total.expected for item in expected_basket if item.total)))
    )
    safe = _percentile(
        [item.total.safe for item in safe_basket if item.total],
        config.safe_percentile,
    )
    if not floor <= expected <= safe:
        raise PricingInvariantError("aggregated total violates floor <= expected <= safe")
    return MoneyRange(floor=floor, expected=expected, safe=safe)


def _percentile(values: list[int], percentile: int) -> int:
    ordered = sorted(values)
    if not ordered:
        raise PricingInvariantError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(percentile) / Decimal(100) * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    value = Decimal(ordered[lower_index]) + fraction * (
        Decimal(ordered[upper_index]) - Decimal(ordered[lower_index])
    )
    return _round_decimal(value)


def _round_decimal(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
