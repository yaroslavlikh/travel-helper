"""PostgreSQL repository for canonical places; no business logic depends on psycopg."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.places.models import (
    PlaceEventInput,
    PlaceImage,
    PlaceSearchQuery,
    PlaceSearchResponse,
    PlaceSearchResult,
)
from app.places.semantics import deterministic_embedding, vector_literal


class PlacesUnavailableError(RuntimeError):
    """Raised when a caller asks for live places without the configured storage."""


class PlacesRepository(Protocol):
    async def search(self, query: PlaceSearchQuery) -> PlaceSearchResponse: ...

    async def record_event(self, event: PlaceEventInput) -> None: ...


@dataclass(frozen=True, slots=True)
class DisabledPlacesRepository:
    """Explicitly disabled adapter; never returns demo fixtures as live places."""

    reason: str = "Places database is not configured"

    async def search(self, query: PlaceSearchQuery) -> PlaceSearchResponse:
        del query
        raise PlacesUnavailableError(self.reason)

    async def record_event(self, event: PlaceEventInput) -> None:
        del event
        raise PlacesUnavailableError(self.reason)


@dataclass(frozen=True, slots=True)
class PostgresPlacesRepository:
    """Small blocking psycopg adapter executed away from FastAPI's event loop."""

    database_url: str
    embedding_version: str

    async def search(self, query: PlaceSearchQuery) -> PlaceSearchResponse:
        return await asyncio.to_thread(self._search_sync, query)

    async def record_event(self, event: PlaceEventInput) -> None:
        await asyncio.to_thread(self._record_event_sync, event)

    def _search_sync(self, query: PlaceSearchQuery) -> PlaceSearchResponse:
        retrieval_id = uuid4()
        embedding = vector_literal(deterministic_embedding([query.query]))
        filters = [
            "d.slug = %s",
            "p.status = 'active'",
            "p.deleted_at IS NULL",
            "pe.model_version = %s",
        ]
        normalized_query = query.query.casefold()
        params: list[object] = [
            embedding,
            normalized_query,
            normalized_query,
            query.destination.casefold(),
            self.embedding_version,
        ]
        if query.include_categories:
            filters.append("c.slug = ANY(%s)")
            params.append(query.include_categories)
        if query.exclude_categories:
            filters.append("COALESCE(c.slug, '') <> ALL(%s)")
            params.append(query.exclude_categories)
        if query.indoor is True:
            filters.append(
                "EXISTS (SELECT 1 FROM place_tags pt JOIN tags t ON t.id = pt.tag_id "
                "WHERE pt.place_id = p.id AND t.slug = 'indoor' AND pt.value)"
            )
        if query.indoor is False:
            filters.append(
                "EXISTS (SELECT 1 FROM place_tags pt JOIN tags t ON t.id = pt.tag_id "
                "WHERE pt.place_id = p.id AND t.slug = 'outdoor' AND pt.value)"
            )
        if query.budget == "free":
            filters.append(
                "EXISTS (SELECT 1 FROM place_tags pt JOIN tags t ON t.id = pt.tag_id "
                "WHERE pt.place_id = p.id AND t.slug = 'budget_friendly' AND pt.value)"
            )
        if query.accessibility_required:
            filters.append(
                "EXISTS (SELECT 1 FROM place_tags pt JOIN tags t ON t.id = pt.tag_id "
                "WHERE pt.place_id = p.id AND t.slug = 'accessible' AND pt.value)"
            )
        if (
            query.latitude is not None
            and query.longitude is not None
            and query.radius_meters is not None
        ):
            filters.append(
                "ST_DWithin(p.location::geography, "
                "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)"
            )
            params.extend([query.longitude, query.latitude, query.radius_meters])

        where_clause = " AND ".join(filters)
        # Retrieve a larger candidate set, then diversify in Python by category.
        params.append(max(query.limit * 4, 20))
        statement = f"""
            WITH ranked AS (
                SELECT
                    p.id,
                    p.canonical_name,
                    d.slug AS destination,
                    ST_Y(p.location) AS latitude,
                    ST_X(p.location) AS longitude,
                    c.slug AS category,
                    COALESCE(pf.freshness, 0) AS freshness_score,
                    COALESCE(pf.tourist_relevance, 0) AS relevance_score,
                    1 - (pe.embedding <=> %s::vector) AS semantic_score,
                    CASE
                        WHEN %s = '' THEN 0.5
                        WHEN p.normalized_name ILIKE '%%' || %s || '%%' THEN 1.0
                        ELSE 0.0
                    END AS lexical_score,
                    COALESCE(pf.tourist_relevance, 0) * 0.55
                      + COALESCE(pf.uniqueness_score, 0) * 0.25
                      + COALESCE(pf.source_quality, 0) * 0.20 AS feature_score,
                    GREATEST(
                        p.updated_at, COALESCE(pf.calculated_at, p.updated_at)
                    ) AS freshness_at,
                    image.image_url,
                    image.source_url AS image_source_url,
                    image.license AS image_license,
                    image.attribution AS image_attribution
                FROM places p
                JOIN destinations d ON d.id = p.destination_id
                LEFT JOIN categories c ON c.id = p.category_id
                JOIN place_embeddings pe ON pe.place_id = p.id
                LEFT JOIN place_features pf ON pf.place_id = p.id
                LEFT JOIN LATERAL (
                    SELECT image_url, source_url, license, attribution
                    FROM place_images
                    WHERE place_id = p.id
                    ORDER BY is_primary DESC, created_at DESC
                    LIMIT 1
                ) image ON TRUE
                WHERE {where_clause}
            )
            SELECT *, (
                semantic_score * 0.40 + lexical_score * 0.25 + feature_score * 0.35
            ) AS rank_score
            FROM ranked
            ORDER BY rank_score DESC, freshness_score DESC, canonical_name
            LIMIT %s
        """
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(statement, params).fetchall()
            tags_by_place = self._tags_for_places(connection, [row["id"] for row in rows])

        results: list[PlaceSearchResult] = []
        seen_categories: defaultdict[str, int] = defaultdict(int)
        for row in rows:
            category = row["category"] or "other"
            if seen_categories[category] >= 2 and len(results) < query.limit:
                continue
            seen_categories[category] += 1
            scores = {
                "semantic": round(float(row["semantic_score"]), 4),
                "lexical": round(float(row["lexical_score"]), 4),
                "features": round(float(row["feature_score"]), 4),
                "final": round(float(row["rank_score"]), 4),
            }
            reasons = [
                "Совпало с тематикой запроса"
                if scores["semantic"] >= 0.45
                else "Подходит по типу места",
                "Прошло заданные фильтры",
            ]
            image = (
                PlaceImage(
                    image_url=row["image_url"],
                    source_url=row["image_source_url"],
                    license=row["image_license"],
                    attribution=row["image_attribution"],
                )
                if row["image_url"]
                else None
            )
            results.append(
                PlaceSearchResult(
                    place_id=row["id"],
                    name=row["canonical_name"],
                    destination=row["destination"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    category=row["category"],
                    tags=tags_by_place.get(row["id"], []),
                    image=image,
                    scores=scores,
                    reasons=reasons,
                    freshness_at=row["freshness_at"],
                    ranking_version=query.ranking_version,
                )
            )
            if len(results) == query.limit:
                break
        return PlaceSearchResponse(
            retrieval_id=retrieval_id,
            ranking_version=query.ranking_version,
            results=results,
        )

    @staticmethod
    def _tags_for_places(
        connection: psycopg.Connection[dict[str, object]], place_ids: list[UUID]
    ) -> dict[UUID, list[str]]:
        if not place_ids:
            return {}
        rows = connection.execute(
            """
            SELECT pt.place_id, t.slug
            FROM place_tags pt JOIN tags t ON t.id = pt.tag_id
            WHERE pt.place_id = ANY(%s) AND pt.value
            ORDER BY t.slug
            """,
            [place_ids],
        ).fetchall()
        tags: defaultdict[UUID, list[str]] = defaultdict(list)
        for row in rows:
            place_id = cast(UUID, row["place_id"])
            tags[place_id].append(cast(str, row["slug"]))
        return dict(tags)

    def _record_event_sync(self, event: PlaceEventInput) -> None:
        # Filters are typed summaries only; never persist the unbounded free-text query here.
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO user_events (
                    event_type, session_id, place_id, retrieval_id, position,
                    ranking_version, experiment_variant, filters
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                [
                    event.event_type,
                    event.session_id,
                    event.place_id,
                    event.retrieval_id,
                    event.position,
                    event.ranking_version,
                    event.experiment_variant,
                    json.dumps(event.filters),
                ],
            )
            connection.commit()


def create_places_repository(database_url: str | None, embedding_version: str) -> PlacesRepository:
    if not database_url:
        return DisabledPlacesRepository()
    return PostgresPlacesRepository(database_url=database_url, embedding_version=embedding_version)
