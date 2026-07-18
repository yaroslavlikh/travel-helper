from datetime import UTC, datetime
from uuid import uuid4

from app.places.models import (
    PlaceSearchResponse,
    PlaceSearchResult,
    PlaceSource,
)
from app.places.repository import DisabledPlacesRepository
from app.services.destination_pois import is_poi_question, search_destination_pois


class PlacesRepositoryStub:
    def __init__(self) -> None:
        self.query = None

    async def search(self, query):  # type: ignore[no-untyped-def]
        self.query = query
        return PlaceSearchResponse(
            retrieval_id=uuid4(),
            ranking_version="istanbul-hybrid-v1",
            results=[
                PlaceSearchResult(
                    place_id=uuid4(),
                    name="Айя-София",
                    destination="istanbul",
                    latitude=41.0086,
                    longitude=28.9802,
                    category="museum",
                    tags=["culture", "indoor"],
                    source=PlaceSource(
                        name="OpenStreetMap / Overpass",
                        url="https://www.openstreetmap.org/",
                        attribution="© OpenStreetMap contributors",
                    ),
                    scores={"final": 0.8},
                    reasons=["Совпало с тематикой запроса"],
                    freshness_at=datetime.now(UTC),
                    ranking_version="istanbul-hybrid-v1",
                )
            ],
        )


async def test_retrieves_canonical_pois_only_for_supported_place_intent() -> None:
    repository = PlacesRepositoryStub()

    result = await search_destination_pois(
        destination_id="istanbul",
        query="Что посмотреть рядом с Айя-Софией?",
        repository=repository,  # type: ignore[arg-type]
    )

    assert repository.query is not None
    assert repository.query.destination == "istanbul"
    assert result.places[0].name == "Айя-София"
    assert result.places[0].source.name == "OpenStreetMap / Overpass"


async def test_skips_catalog_for_non_place_questions_and_unsupported_destinations() -> None:
    repository = PlacesRepositoryStub()

    visa_result = await search_destination_pois(
        destination_id="istanbul",
        query="Нужна ли виза?",
        repository=repository,  # type: ignore[arg-type]
    )
    city_result = await search_destination_pois(
        destination_id="rome",
        query="Что посмотреть?",
        repository=repository,  # type: ignore[arg-type]
    )

    assert not visa_result.places
    assert not city_result.places
    assert repository.query is None
    assert is_poi_question("Где посмотреть закат на Босфоре?")


async def test_reports_when_the_canonical_catalog_is_unavailable() -> None:
    result = await search_destination_pois(
        destination_id="istanbul",
        query="Что посмотреть рядом с Айя-Софией?",
        repository=DisabledPlacesRepository(),
    )

    assert result.places == []
    assert result.user_warnings == [
        "Каталог конкретных мест сейчас недоступен; ответ ограничен данными карточки."
    ]
