"""Explicitly marked local-only candidates for demo mode and tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.models import DestinationCandidate, SourceEvidence

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "destinations.fixture.json"


def load_demo_candidates() -> list[DestinationCandidate]:
    """Load synthetic fixture data; callers must expose demo mode to users."""

    payload: dict[str, Any] = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    retrieved_at = datetime.now(UTC)
    candidates: list[DestinationCandidate] = []
    for item in payload["destinations"]:
        total_min = item["total_min"]
        total_max = item["total_max"]
        source = SourceEvidence(
            source_type="fixture",
            title="Demo fixture estimate",
            url=f"https://example.invalid/travel-demo/{item['id']}",
            provider="local-demo-fixture",
            retrieved_at=retrieved_at,
            excerpt=payload["notice"],
            confidence=0.35,
        )
        candidates.append(
            DestinationCandidate(
                destination_id=item["id"],
                country=item["country"],
                city_or_region=item["region"],
                nearest_airport=item["airport"],
                estimated_flight_cost_rub_min=round(total_min * 0.35),
                estimated_flight_cost_rub_max=round(total_max * 0.35),
                estimated_hotel_cost_rub_min=round(total_min * 0.50),
                estimated_hotel_cost_rub_max=round(total_max * 0.50),
                estimated_other_cost_rub=round(total_min * 0.15),
                estimated_total_cost_rub_min=total_min,
                estimated_total_cost_rub_max=total_max,
                expected_temperature_c=item["temp"],
                expected_sea_temperature_c=item["sea_temp"],
                precipitation_risk=item["rain"],
                flight_duration_hours=item["flight"],
                transfers_count=item["transfers"],
                entry_requirements=item["entry"],
                visa_complexity=item["visa"],
                destination_tags=item["tags"],
                sources=[source],
                data_confidence=source.confidence,
                retrieved_at=retrieved_at,
            )
        )
    return candidates
