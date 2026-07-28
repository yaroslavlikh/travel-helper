"""Select month scenarios for expensive full pricing using cached flight signals."""

from __future__ import annotations

from calendar import monthrange

from app.pricing.config import CACHED_FLIGHT_CONFIG, CachedFlightConfig
from app.pricing.models import DateScenario, FlightPriceSignal, ScenarioBatch


def select_scenarios_for_full_pricing(
    batch: ScenarioBatch,
    signals: tuple[FlightPriceSignal, ...],
    config: CachedFlightConfig = CACHED_FLIGHT_CONFIG,
) -> tuple[DateScenario, ...]:
    """Choose cheap signals while retaining deterministic early/mid/late month coverage."""

    scenario_by_id = {scenario.scenario_id: scenario for scenario in batch.scenarios}
    cheapest_signal: dict[str, FlightPriceSignal] = {}
    for signal in signals:
        if signal.scenario_id not in scenario_by_id:
            continue
        current = cheapest_signal.get(signal.scenario_id)
        if current is None or signal.amount_rub < current.amount_rub:
            cheapest_signal[signal.scenario_id] = signal
    ordered = sorted(
        cheapest_signal.values(),
        key=lambda signal: (
            signal.amount_rub,
            signal.outbound_date,
            signal.return_date,
            signal.scenario_id,
        ),
    )
    selected_ids = [signal.scenario_id for signal in ordered[: config.cheapest_scenario_count]]
    if ordered:
        year, month = ordered[0].outbound_date.year, ordered[0].outbound_date.month
        days = monthrange(year, month)[1]
        boundaries = ((1, days // 3), (days // 3 + 1, 2 * days // 3), (2 * days // 3 + 1, days))
        for start, end in boundaries:
            third = [
                signal
                for signal in ordered
                if signal.outbound_date.year == year
                and signal.outbound_date.month == month
                and start <= signal.outbound_date.day <= end
            ]
            selected_ids.extend(
                signal.scenario_id for signal in third[: config.scenarios_per_month_third]
            )
    unique_ids = tuple(dict.fromkeys(selected_ids))[: config.full_pricing_scenario_limit]
    return tuple(
        sorted(
            (scenario_by_id[scenario_id] for scenario_id in unique_ids),
            key=lambda scenario: (scenario.outbound_date, scenario.return_date),
        )
    )
