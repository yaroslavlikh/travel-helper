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
    PlaceDescription,
    PlaceEventInput,
    PlaceImage,
    PlaceSearchQuery,
    PlaceSearchResponse,
    PlaceSearchResult,
    PlaceSource,
)
from app.places.semantics import inferred_area, inferred_categories, normalize_text


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
        filters = [
            "d.slug = %s",
            "p.status = 'active'",
            "p.deleted_at IS NULL",
        ]
        normalized_query = normalize_text(query.query)
        category_hints = inferred_categories(query.query)
        params: list[object] = [
            normalized_query,
            normalized_query,
            category_hints,
            query.destination.casefold(),
        ]
        area = inferred_area(query.query)
        if area:
            filters.append(
                "ST_DWithin(p.location::geography, "
                "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)"
            )
            params.extend([area[1], area[0], area[2]])
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
                    0.0 AS place_semantic_score,
                    0.0 AS description_semantic_score,
                    0.0 AS semantic_score,
                    CASE
                        WHEN %s = '' THEN 0.5
                        WHEN EXISTS (
                            SELECT 1 FROM place_names pn
                            WHERE pn.place_id = p.id
                              AND pn.normalized_name ILIKE '%%' || %s || '%%'
                        ) THEN 1.0
                        ELSE 0.0
                    END AS lexical_score,
                    CASE WHEN c.slug = ANY(%s) THEN 1.0 ELSE 0.0 END AS category_score,
                    COALESCE(pf.tourist_relevance, 0) * 0.55
                      + COALESCE(pf.uniqueness_score, 0) * 0.25
                      + COALESCE(pf.source_quality, 0) * 0.20 AS feature_score,
                    GREATEST(
                        p.updated_at, COALESCE(pf.calculated_at, p.updated_at)
                    ) AS freshness_at,
                    image.image_url,
                    image.source_url AS image_source_url,
                    image.license AS image_license,
                    image.attribution AS image_attribution,
                    source.name AS source_name,
                    source.source_url AS source_url,
                    source.attribution AS source_attribution,
                    source.license AS source_license,
                    description.text_content AS description_text,
                    description.language_code AS description_language_code,
                    description.content_kind AS description_content_kind,
                    description.observed_at AS description_observed_at,
                    description.valid_until AS description_valid_until,
                    description.source_name AS description_source_name,
                    description.source_url AS description_source_url,
                    description.source_attribution AS description_source_attribution,
                    description.source_license AS description_source_license
                FROM places p
                JOIN destinations d ON d.id = p.destination_id
                LEFT JOIN categories c ON c.id = p.category_id
                LEFT JOIN place_features pf ON pf.place_id = p.id
                LEFT JOIN LATERAL (
                    SELECT image_url, source_url, license, attribution
                    FROM place_images
                    WHERE place_id = p.id
                    ORDER BY is_primary DESC, created_at DESC
                    LIMIT 1
                ) image ON TRUE
                JOIN LATERAL (
                    SELECT s.name, psr.source_url, s.attribution, s.license
                    FROM place_source_records psr
                    JOIN sources s ON s.id = psr.source_id
                    WHERE psr.place_id = p.id AND psr.deleted_at IS NULL
                    ORDER BY (s.slug = 'openstreetmap') DESC, psr.last_seen_at DESC
                    LIMIT 1
                ) source ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        document.text_content,
                        document.language_code,
                        document.content_kind,
                        document.observed_at,
                        document.valid_until,
                        description_source.name AS source_name,
                        description_record.source_url,
                        description_source.attribution AS source_attribution,
                        description_source.license AS source_license
                    FROM place_description_documents document
                    JOIN place_source_records description_record
                        ON description_record.id = document.place_source_record_id
                    JOIN sources description_source
                        ON description_source.id = description_record.source_id
                    JOIN source_usage_policies description_policy
                        ON description_policy.source_id = description_source.id
                    WHERE document.place_id = p.id
                      AND description_record.deleted_at IS NULL
                      AND (document.valid_until IS NULL OR document.valid_until > now())
                      AND description_policy.may_display_excerpt
                    ORDER BY
                        (document.language_code = 'ru') DESC,
                        CASE document.content_kind
                            WHEN 'overview' THEN 0
                            WHEN 'practical' THEN 1
                            ELSE 2
                        END,
                        document.observed_at DESC
                    LIMIT 1
                ) description ON TRUE
                WHERE {where_clause}
            )
            SELECT *, (lexical_score * 0.40 + category_score * 0.40 + feature_score * 0.20)
                AS rank_score
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
                "semantic_place": 0.0,
                "semantic_description": 0.0,
                "semantic": 0.0,
                "lexical": round(float(row["lexical_score"]), 4),
                "features": round(float(row["feature_score"]), 4),
                "category": round(float(row["category_score"]), 4),
                "final": round(float(row["rank_score"]), 4),
            }
            reasons = [
                "Совпало по названию" if scores["lexical"] else "Подходит по типу места",
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
                    source=PlaceSource(
                        name=row["source_name"],
                        url=row["source_url"],
                        attribution=row["source_attribution"],
                        license=row["source_license"],
                    ),
                    description=(
                        PlaceDescription(
                            text=row["description_text"],
                            language_code=row["description_language_code"],
                            content_kind=row["description_content_kind"],
                            observed_at=row["description_observed_at"],
                            valid_until=row["description_valid_until"],
                            source=PlaceSource(
                                name=row["description_source_name"],
                                url=row["description_source_url"],
                                attribution=row["description_source_attribution"],
                                license=row["description_source_license"],
                            ),
                        )
                        if row["description_text"]
                        else None
                    ),
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
