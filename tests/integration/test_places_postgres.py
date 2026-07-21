"""Optional real-PostgreSQL coverage for the reproducible local Istanbul catalog."""

from __future__ import annotations

import os

import pytest

from app.places.models import PlaceSearchQuery
from app.places.repository import PostgresPlacesRepository

DATABASE_URL = os.environ.get("PLACES_DATABASE_URL")


@pytest.mark.skipif(
    not DATABASE_URL, reason="PLACES_DATABASE_URL is required for PostgreSQL contract"
)
async def test_postgres_retrieval_returns_provenanced_active_istanbul_pois() -> None:
    repository = PostgresPlacesRepository(
        database_url=str(DATABASE_URL), embedding_version="hash-v1"
    )

    response = await repository.search(
        PlaceSearchQuery(destination="istanbul", query="Айя-София", limit=5)
    )

    assert response.results
    assert all(result.source.url.startswith("https://") for result in response.results)
    assert all(result.destination == "istanbul" for result in response.results)
    assert any("Aya" in result.name for result in response.results)
