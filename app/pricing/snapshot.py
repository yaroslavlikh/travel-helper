"""Immutable pricing snapshot construction from normalized scenario results."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal

from app.pricing.aggregation import aggregate_scenarios
from app.pricing.config import PRICING_CORE_CONFIG, PricingCoreConfig
from app.pricing.models import (
    PricingRequest,
    ScenarioBatch,
    ScenarioPrice,
    TripPriceEstimate,
)


def build_pricing_snapshot(
    *,
    request: PricingRequest,
    batch: ScenarioBatch,
    scenario_prices: tuple[ScenarioPrice, ...],
    calculated_at: datetime,
    config: PricingCoreConfig = PRICING_CORE_CONFIG,
) -> TripPriceEstimate:
    """Build a replayable snapshot; the clock is explicit and no source is queried here."""

    allowed_ids = {scenario.scenario_id for scenario in batch.scenarios}
    if any(item.scenario.scenario_id not in allowed_ids for item in scenario_prices):
        raise ValueError("priced scenario was not generated for this request")
    priced_ids = [item.scenario.scenario_id for item in scenario_prices]
    if len(priced_ids) != len(set(priced_ids)):
        raise ValueError("a date scenario can be priced only once per snapshot")
    ordered = tuple(
        sorted(
            scenario_prices,
            key=lambda item: (item.scenario.outbound_date, item.scenario.return_date),
        )
    )
    total = aggregate_scenarios(ordered, config)
    complete = [item for item in ordered if item.total is not None]
    selected = min(
        complete,
        key=lambda item: (
            item.total.expected,  # type: ignore[union-attr]
            item.scenario.outbound_date,
        ),
        default=None,
    )
    missing = tuple(
        dict.fromkeys(component for item in ordered for component in item.missing_components)
    )
    sources = [
        source for item in ordered for component in item.components for source in component.sources
    ]
    valid_until = min(
        (source.valid_until for source in sources if source.valid_until is not None),
        default=None,
    )
    request_hash = _hash(request.model_dump(mode="json"))
    snapshot_payload = {
        "request_hash": request_hash,
        "pricing_version": config.version,
        "calculated_at": calculated_at.isoformat(),
        "scenarios": [item.model_dump(mode="json") for item in ordered],
    }
    confidence: Literal["high", "medium", "low", "insufficient"] = (
        "insufficient" if total is None else "low" if missing else "medium"
    )
    warnings = tuple(
        dict.fromkeys(
            [
                *(warning for item in ordered for warning in item.warnings),
                *(("Не все компоненты стоимости доступны.",) if missing else ()),
                *(("Нет полного сценария с перелётом и проживанием.",) if total is None else ()),
            ]
        )
    )
    return TripPriceEstimate(
        pricing_snapshot_id=f"ps_{_hash(snapshot_payload)[:24]}",
        pricing_version=config.version,
        request_hash=request_hash,
        scenario_count_generated=batch.generated_count,
        scenario_count_priced=len(ordered),
        total=total,
        components=selected.components if selected else (),
        selected_scenario_id=selected.scenario.scenario_id if selected else None,
        scenarios=ordered,
        confidence=confidence,
        calculated_at=calculated_at,
        valid_until=valid_until,
        assumptions=tuple(
            dict.fromkeys(assumption for item in ordered for assumption in item.assumptions)
        ),
        warnings=warnings,
        missing_components=missing,
    )


def _hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()
