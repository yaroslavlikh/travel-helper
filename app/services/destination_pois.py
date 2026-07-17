"""Bounded canonical POI retrieval for destination-specific subchats."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.places.models import PlaceSearchQuery, PlaceSearchResult
from app.places.repository import PlacesRepository, PlacesUnavailableError

# The catalog is deliberately one-city for now. Expanding this map requires a populated,
# provenance-preserving catalog for the new destination rather than falling back to fixtures.
CATALOG_DESTINATIONS = {"istanbul": "istanbul"}

POI_QUERY_MARKERS = (
    "айя",
    "босфор",
    "галат",
    "дворц",
    "достопримеч",
    "закат",
    "куда сход",
    "маршрут",
    "мест",
    "мечет",
    "музе",
    "набережн",
    "ночн",
    "парк",
    "посмотр",
    "прогул",
    "район",
    "рынок",
    "рядом",
    "смотров",
    "султанахм",
    "топкап",
    "экскурси",
)


@dataclass(frozen=True, slots=True)
class DestinationPoiSearch:
    """One optional retrieval attached to a subchat response, never stored in graph state."""

    retrieval_id: UUID | None = None
    ranking_version: str | None = None
    results: list[PlaceSearchResult] | None = None
    warnings: list[str] | None = None

    @property
    def places(self) -> list[PlaceSearchResult]:
        return self.results or []

    @property
    def user_warnings(self) -> list[str]:
        return self.warnings or []


def is_poi_question(query: str) -> bool:
    """Avoid irrelevant catalog lookups for questions about visas, flights, or budget."""

    normalized = query.casefold()
    return any(marker in normalized for marker in POI_QUERY_MARKERS)


async def search_destination_pois(
    *,
    destination_id: str,
    query: str,
    repository: PlacesRepository,
) -> DestinationPoiSearch:
    """Retrieve evidence-backed POIs only for a supported destination and relevant intent."""

    catalog_destination = CATALOG_DESTINATIONS.get(destination_id.casefold())
    if catalog_destination is None or not is_poi_question(query):
        return DestinationPoiSearch()
    try:
        response = await repository.search(
            PlaceSearchQuery(destination=catalog_destination, query=query, limit=5)
        )
    except PlacesUnavailableError:
        return DestinationPoiSearch(
            warnings=[
                "Каталог конкретных мест сейчас недоступен; ответ ограничен данными карточки."
            ]
        )
    return DestinationPoiSearch(
        retrieval_id=response.retrieval_id,
        ranking_version=response.ranking_version,
        results=response.results,
        warnings=response.warnings,
    )
