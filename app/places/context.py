"""Small, sourced destination context separate from mutable travel facts."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.places.catalog import DESTINATIONS
from app.services.fixtures import load_demo_candidates


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
    west, south, east, north = catalog.bbox
    return DestinationContext(
        destination_id=destination_id,
        city=catalog.name,
        country=candidate.country,
        source_url=(
            candidate.image.source_url if candidate.image else "https://www.openstreetmap.org/"
        ),
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
        suitable_for=candidate.destination_tags,
        less_suitable_for=[],
        transport_notes=["Конкретные маршруты лучше собирать по районам, а не по всей зоне сразу."],
        poi_categories=["museum", "historic", "sight", "viewpoint", "park", "market", "family"],
        curated_highlights=[
            f"{highlight.name}: {highlight.description}" for highlight in candidate.highlights
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
