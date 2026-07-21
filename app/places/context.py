"""Small, sourced destination context separate from mutable travel facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.places.catalog import DESTINATIONS
from app.services.fixtures import load_demo_candidates

GUIDES_PATH = Path(__file__).resolve().parents[1] / "data" / "destination-guides.json"


@lru_cache(maxsize=1)
def _guides() -> dict[str, dict[str, Any]]:
    payload = json.loads(GUIDES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Destination guides must be a JSON object")
    return payload


class DestinationFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["entry", "climate", "transport", "risk", "price"]
    value: str | None = None
    source_url: str | None = None
    provider: str | None = None
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    excerpt: str | None = None
    confidence: float = Field(ge=0, le=1, default=0)
    warning: str | None = None


class DestinationArea(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_meters: int


class DestinationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: str
    city: str
    country: str
    source_url: str
    observed_at: datetime
    tourist_areas: list[DestinationArea]
    stay_areas: list[str]
    trip_styles: list[str]
    suitable_for: list[str]
    less_suitable_for: list[str]
    transport_notes: list[str]
    poi_categories: list[str]
    summary: str | None = None
    day_plans: list[str] = Field(default_factory=list)
    curated_highlights: list[str] = Field(default_factory=list)
    dynamic_facts: list[DestinationFact]


ISTANBUL_CONTEXT = DestinationContext(
    destination_id="istanbul",
    city="Стамбул",
    country="Турция",
    source_url="https://www.openstreetmap.org/relation/223474",
    observed_at=datetime(2026, 7, 21, tzinfo=UTC),
    tourist_areas=[
        DestinationArea(
            name="Султанахмет", latitude=41.0054, longitude=28.9768, radius_meters=1_500
        ),
        DestinationArea(
            name="Галата и Каракёй", latitude=41.0261, longitude=28.9786, radius_meters=1_800
        ),
        DestinationArea(
            name="Бешикташ и Босфор", latitude=41.0422, longitude=29.0066, radius_meters=2_500
        ),
    ],
    stay_areas=["Султанахмет", "Каракёй", "Бейоглу", "Кадыкёй"],
    trip_styles=["история", "музеи", "городские прогулки", "гастрономия", "семейная поездка"],
    suitable_for=["первая поездка в Турцию", "насыщенный городской уикенд", "музеи и история"],
    less_suitable_for=["тихий пляжный отдых", "поездка без городского ритма"],
    transport_notes=[
        "Ключевые районы лежат по обе стороны Босфора.",
        "Маршрут лучше собирать по районам, а не по всему городу за один день.",
    ],
    poi_categories=["museum", "historic", "sight", "viewpoint", "park", "market", "family"],
    summary=(
        "Город двух континентов с плотной историей, водой и районами, "
        "которые лучше не пытаться охватить одним маршрутом."
    ),
    curated_highlights=[
        "Айя-София и Султанахмет: историческое ядро.",
        "Галатская башня и Каракёй: виды и городской ритм.",
        "Дворец Топкапы: большой отдельный музейный маршрут.",
        "Кадыкёй: азиатская сторона с рынками и кафе.",
    ],
    day_plans=[
        "История: Айя-София → Голубая мечеть → Топкапы.",
        "Город: Каракёй → Галата → Бейоглу вечером.",
    ],
    dynamic_facts=[
        DestinationFact(
            kind="entry",
            warning=(
                "Актуальные правила въезда не загружены: "
                "проверьте официальный источник перед поездкой."
            ),
        ),
        DestinationFact(
            kind="price",
            warning="Актуальные цены и расписания не входят в контекст каталога мест.",
        ),
    ],
)


@lru_cache(maxsize=32)
def destination_context(destination_id: str) -> DestinationContext | None:
    """Give each current card a bounded planning brief; dynamic facts stay explicitly unknown."""

    destination_id = destination_id.casefold()
    if destination_id == "istanbul":
        return ISTANBUL_CONTEXT
    catalog = DESTINATIONS.get(destination_id)
    if catalog is None:
        return None
    candidate = next(
        (item for item in load_demo_candidates() if item.destination_id == destination_id), None
    )
    if candidate is None:
        return None
    guide = _guides().get(destination_id)
    if guide is None:
        return None
    west, south, east, north = catalog.bbox
    return DestinationContext(
        destination_id=destination_id,
        city=catalog.name,
        country=candidate.country,
        source_url=str(guide["source_url"]),
        observed_at=datetime(2026, 7, 21, tzinfo=UTC),
        tourist_areas=[
            DestinationArea(
                name=f"Основная зона {catalog.name}",
                latitude=(south + north) / 2,
                longitude=(west + east) / 2,
                radius_meters=5_000,
            )
        ],
        stay_areas=candidate.stay_areas,
        trip_styles=candidate.destination_tags,
        suitable_for=list(guide["suitable_for"]),
        less_suitable_for=list(guide["less_suitable_for"]),
        transport_notes=list(guide["transport_notes"]),
        poi_categories=["museum", "historic", "sight", "viewpoint", "park", "market", "family"],
        summary=str(guide["summary"]),
        curated_highlights=list(guide["curated_highlights"]),
        day_plans=list(guide["day_plans"]),
        dynamic_facts=[
            DestinationFact(
                kind="entry",
                warning=(
                    "Актуальные правила въезда не загружены: "
                    "проверьте официальный источник перед поездкой."
                ),
            ),
            DestinationFact(
                kind="price",
                warning="Актуальные цены и расписания не входят в контекст каталога мест.",
            ),
        ],
    )
