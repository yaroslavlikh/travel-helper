"""Repeatable, bounded OpenStreetMap import for catalog tourist places."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from app.places.catalog import CatalogDestination, catalog_destination
from app.places.semantics import (
    category_from_osm,
    deterministic_embedding,
    normalize_text,
    tags_for_category,
    vector_literal,
)

# Compatibility for the first vertical slice and its external callers.
ISTANBUL_BBOX = catalog_destination("istanbul").bbox
OVERPASS_URLS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
OVERPASS_USER_AGENT = "travel-helper/0.1 (+https://github.com/yaroslavlikh/travel-helper)"
OSM_LICENSE = "ODbL 1.0"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
COMMONS_LICENSE = "See Wikimedia Commons file page"
COMMONS_ATTRIBUTION = "Wikimedia Commons · attribution on file page"


@dataclass(frozen=True, slots=True)
class RawPlace:
    external_id: str
    name: str
    longitude: float
    latitude: float
    category: str
    tags: dict[str, str]
    quality_score: int


@dataclass(frozen=True, slots=True)
class ImportReport:
    run_id: str
    received: int
    accepted: int
    updated: int
    merged: int
    rejected: int
    deactivated: int
    rejection_reasons: dict[str, int]


def _required_id(row: dict[str, Any] | None) -> str:
    """Turn an expected ``RETURNING id`` row into a typed identifier."""

    if row is None or "id" not in row:
        raise RuntimeError("Expected database mutation to return an id")
    return str(row["id"])


def overpass_query(destination: str = "istanbul") -> str:
    """Bound source scope to named tourist POIs, never all commercial objects."""

    west, south, east, north = catalog_destination(destination).bbox
    bbox = f"({south},{west},{north},{east})"
    selectors = (
        '["tourism"~"museum|gallery|attraction|viewpoint|zoo|theme_park"]["name"]',
        '["historic"~"monument|memorial|castle|archaeological_site"]["name"]',
        '["leisure"~"park|garden"]["name"]',
        '["natural"="beach"]["name"]',
        '["amenity"="marketplace"]["name"]',
    )
    statements = "\n".join(f"nwr{selector}{bbox};" for selector in selectors)
    return f"[out:json][timeout:120];\n({statements}\n);\nout center tags;"


def fetch_osm(destination: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Download one public OSM snapshot; callers persist it before normalization."""

    owns_client = client is None
    request_client = client or httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
    )
    last_error: httpx.HTTPError | None = None
    try:
        for url in OVERPASS_URLS:
            try:
                response = request_client.post(
                    url,
                    data={"data": overpass_query(destination)},
                    headers={"Accept": "application/json", "User-Agent": OVERPASS_USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPError as error:
                last_error = error
        else:
            raise RuntimeError(f"All Overpass endpoints failed for {destination}") from last_error
    finally:
        if owns_client:
            request_client.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ValueError(f"Overpass returned an invalid {destination} OSM payload")
    return payload


def fetch_istanbul_osm(client: httpx.Client | None = None) -> dict[str, Any]:
    """Compatibility wrapper for the first catalog destination."""

    return fetch_osm("istanbul", client)


def persist_raw_payload(
    payload: dict[str, Any], raw_directory: Path, *, destination: str = "istanbul"
) -> tuple[Path, str]:
    """Store raw source bytes and return the immutable checksum for the import manifest."""

    raw_directory.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path = raw_directory / f"osm-{destination}-{checksum[:12]}.json"
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return path, checksum


def normalize_osm_payload(
    payload: dict[str, Any], *, limit: int = 300
) -> tuple[list[RawPlace], Counter[str]]:
    """Normalize every valid candidate, then select the strongest tourist POIs deterministically."""

    records: list[RawPlace] = []
    rejected: Counter[str] = Counter()
    seen_external_ids: set[str] = set()
    for element in payload.get("elements", []):
        if not isinstance(element, dict):
            rejected["invalid_element"] += 1
            continue
        tags = element.get("tags")
        if not isinstance(tags, dict):
            rejected["missing_tags"] += 1
            continue
        name = tags.get("name")
        category = category_from_osm(tags)
        coordinates = _coordinates_from_element(element)
        if not isinstance(name, str) or not name.strip():
            rejected["missing_name"] += 1
        elif category is None:
            rejected["unmapped_category"] += 1
        elif coordinates is None:
            rejected["missing_coordinates"] += 1
        else:
            external_id = f"{element.get('type', 'unknown')}/{element.get('id', '')}"
            if external_id in seen_external_ids:
                rejected["duplicate_external_id"] += 1
            else:
                seen_external_ids.add(external_id)
                records.append(
                    RawPlace(
                        external_id=external_id,
                        name=name.strip(),
                        longitude=coordinates[0],
                        latitude=coordinates[1],
                        category=category,
                        tags={str(key): str(value) for key, value in tags.items()},
                        quality_score=_quality_score(name.strip(), category, tags),
                    )
                )
    # The source response order is not a quality signal. Keep external IDs as the final tie-breaker
    # so re-importing an identical full snapshot is deterministic.
    records.sort(
        key=lambda item: (
            -item.quality_score,
            item.category,
            normalize_text(item.name),
            item.external_id,
        )
    )
    return records[:limit], rejected


def _quality_score(name: str, category: str, tags: dict[str, Any]) -> int:
    """Rank only observable OSM completeness signals; this is deliberately not popularity."""

    category_weight = {
        "museum": 40,
        "historic": 40,
        "sight": 35,
        "viewpoint": 32,
        "gallery": 28,
        "market": 26,
        "park": 24,
        "family": 22,
        "beach": 18,
    }.get(category, 0)
    linked_data = sum(bool(tags.get(key)) for key in ("wikidata", "wikipedia", "wikimedia_commons"))
    names = sum(1 for key in tags if key == "name" or key.startswith("name:"))
    useful_tags = sum(
        bool(tags.get(key))
        for key in ("website", "opening_hours", "heritage", "start_date", "image", "operator")
    )
    generic = normalize_text(name) in {"park", "museum", "market", "monument", "viewpoint"}
    return (
        category_weight
        + linked_data * 12
        + min(names, 3) * 3
        + useful_tags * 2
        - (20 if generic else 0)
    )


def _coordinates_from_element(element: dict[str, Any]) -> tuple[float, float] | None:
    lon = element.get("lon")
    lat = element.get("lat")
    center = element.get("center")
    if isinstance(center, dict):
        lon = center.get("lon")
        lat = center.get("lat")
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        return None
    return float(lon), float(lat)


def import_osm_places(
    database_url: str,
    records: list[RawPlace],
    *,
    checksum: str,
    raw_path: Path,
    embedding_version: str,
    rejected: Counter[str],
    destination: CatalogDestination | None = None,
) -> ImportReport:
    """Upsert source records, canonical places and provenance in one database transaction."""

    catalog = destination or catalog_destination("istanbul")
    started_at = datetime.now(UTC)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            osm_source_id = _upsert_source(
                connection,
                slug="openstreetmap",
                name="OpenStreetMap / Overpass",
                license_name=OSM_LICENSE,
                attribution=OSM_ATTRIBUTION,
                base_url="https://www.openstreetmap.org/",
            )
            commons_source_id = _upsert_source(
                connection,
                slug="wikimedia-commons",
                name="Wikimedia Commons",
                license_name=COMMONS_LICENSE,
                attribution=COMMONS_ATTRIBUTION,
                base_url="https://commons.wikimedia.org/",
            )
            destination_id = _upsert_destination(connection, catalog)
            run_id = _required_id(
                connection.execute(
                    """
                INSERT INTO import_runs (
                    source_id, destination_id, scope, source_version, checksum, manifest,
                    started_at, status, received_count
                ) VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, 'running', %s)
                RETURNING id
                """,
                    [
                        osm_source_id,
                        destination_id,
                        json.dumps({"city": catalog.destination_id, "bbox": catalog.bbox}),
                        started_at.date().isoformat(),
                        checksum,
                        json.dumps(
                            {
                                "source": "OpenStreetMap / Overpass",
                                "license": OSM_LICENSE,
                                "scope": f"bounded tourist POIs in {catalog.name}",
                                "raw_path": str(raw_path),
                            }
                        ),
                        started_at,
                        len(records) + sum(rejected.values()),
                    ],
                ).fetchone()
            )
            accepted = 0
            updated = 0
            merged = 0
            for record in records:
                place_id, was_updated, was_merged = _upsert_canonical_place(
                    connection,
                    destination_id=destination_id,
                    source_id=osm_source_id,
                    run_id=run_id,
                    record=record,
                    embedding_version=embedding_version,
                    commons_source_id=commons_source_id,
                )
                del place_id
                accepted += 1
                updated += int(was_updated)
                merged += int(was_merged)
            deactivated = _deactivate_missing_osm_records(
                connection,
                destination_id=destination_id,
                source_id=osm_source_id,
                started_at=started_at,
            )
            completed_at = datetime.now(UTC)
            connection.execute(
                """
                UPDATE import_runs
                SET status = 'completed', completed_at = %s, accepted_count = %s, merged_count = %s,
                    rejected_count = %s, rejection_reasons = %s::jsonb,
                    manifest = manifest || %s::jsonb
                WHERE id = %s
                """,
                [
                    completed_at,
                    accepted,
                    merged,
                    sum(rejected.values()),
                    json.dumps(dict(rejected)),
                    json.dumps(
                        {
                            "completed_at": completed_at.isoformat(),
                            "checksum": checksum,
                            "updated": updated,
                            "deactivated": deactivated,
                        }
                    ),
                    run_id,
                ],
            )
    return ImportReport(
        run_id=str(run_id),
        received=len(records) + sum(rejected.values()),
        accepted=accepted,
        updated=updated,
        merged=merged,
        rejected=sum(rejected.values()),
        deactivated=deactivated,
        rejection_reasons=dict(rejected),
    )


def _upsert_source(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    slug: str,
    name: str,
    license_name: str,
    attribution: str,
    base_url: str,
) -> str:
    return _required_id(
        connection.execute(
            """
            INSERT INTO sources (slug, name, license, attribution, base_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                license = EXCLUDED.license,
                attribution = EXCLUDED.attribution,
                base_url = EXCLUDED.base_url
            RETURNING id
            """,
            [slug, name, license_name, attribution, base_url],
        ).fetchone()
    )


def _upsert_destination(
    connection: psycopg.Connection[dict[str, Any]], catalog: CatalogDestination
) -> str:
    west, south, east, north = catalog.bbox
    return _required_id(
        connection.execute(
            """
            INSERT INTO destinations (slug, name, country_code, center)
            VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
            ON CONFLICT (slug) DO UPDATE SET updated_at = now()
            RETURNING id
            """,
            [
                catalog.destination_id,
                catalog.name,
                catalog.country_code,
                (west + east) / 2,
                (south + north) / 2,
            ],
        ).fetchone()
    )


def _upsert_canonical_place(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    destination_id: str,
    source_id: str,
    run_id: str,
    record: RawPlace,
    embedding_version: str,
    commons_source_id: str,
) -> tuple[str, bool, bool]:
    existing = connection.execute(
        "SELECT place_id FROM place_source_records WHERE source_id = %s AND external_id = %s",
        [source_id, record.external_id],
    ).fetchone()
    updated = existing is not None
    merged = False
    category_id = _upsert_category(connection, record.category)
    normalized_name = normalize_text(record.name)
    if existing:
        place_id = str(existing["place_id"])
        connection.execute(
            """
            UPDATE places SET canonical_name = %s, normalized_name = %s, category_id = %s,
                location = ST_SetSRID(ST_MakePoint(%s, %s), 4326), status = 'active',
                deleted_at = NULL, updated_at = now()
            WHERE id = %s
            """,
            [
                record.name,
                normalized_name,
                category_id,
                record.longitude,
                record.latitude,
                place_id,
            ],
        )
    else:
        nearby = connection.execute(
            """
            SELECT id FROM places
            WHERE destination_id = %s AND normalized_name = %s AND deleted_at IS NULL
              AND ST_DWithin(
                    location::geography,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    120
              )
            LIMIT 1
            """,
            [destination_id, normalized_name, record.longitude, record.latitude],
        ).fetchone()
        if nearby:
            place_id = str(nearby["id"])
            merged = True
        else:
            place_id = _required_id(
                connection.execute(
                    """
                    INSERT INTO places (
                        destination_id, canonical_name, normalized_name, category_id, location
                    )
                    VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    RETURNING id
                    """,
                    [
                        destination_id,
                        record.name,
                        normalized_name,
                        category_id,
                        record.longitude,
                        record.latitude,
                    ],
                ).fetchone()
            )
    connection.execute(
        """
        INSERT INTO place_names (
            place_id, name, normalized_name, language_code, is_primary, source_id
        )
        VALUES (%s, %s, %s, 'und', TRUE, %s)
        ON CONFLICT (place_id, normalized_name, language_code) DO UPDATE SET is_primary = TRUE
        """,
        [place_id, record.name, normalized_name, source_id],
    )
    for key, value in record.tags.items():
        if not key.startswith("name:") or not value.strip():
            continue
        language_code = key.removeprefix("name:")[:16]
        connection.execute(
            """
            INSERT INTO place_names (place_id, name, normalized_name, language_code, source_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (place_id, normalized_name, language_code) DO NOTHING
            """,
            [place_id, value, normalize_text(value), language_code, source_id],
        )
    source_record = _required_id(
        connection.execute(
            """
        INSERT INTO place_source_records (
            place_id, source_id, external_id, source_url, source_category, source_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (source_id, external_id) DO UPDATE SET
            place_id = EXCLUDED.place_id, source_payload = EXCLUDED.source_payload,
            source_category = EXCLUDED.source_category, last_seen_at = now(), deleted_at = NULL
        RETURNING id
        """,
            [
                place_id,
                source_id,
                record.external_id,
                f"https://www.openstreetmap.org/{record.external_id}",
                record.category,
                json.dumps(record.tags),
            ],
        ).fetchone()
    )
    record_checksum = hashlib.sha256(
        json.dumps(record.tags, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    connection.execute(
        """
        INSERT INTO place_source_snapshots (
            place_source_record_id, import_run_id, checksum, payload
        )
        VALUES (%s, %s, %s, %s::jsonb)
        ON CONFLICT (place_source_record_id, checksum) DO NOTHING
        """,
        [source_record, run_id, record_checksum, json.dumps(record.tags)],
    )
    _upsert_tags_and_features(connection, place_id, record.category, source_id)
    connection.execute(
        """
        INSERT INTO place_embeddings (place_id, model_version, embedding)
        VALUES (%s, %s, %s::vector)
        ON CONFLICT (place_id, model_version) DO UPDATE SET
            embedding = EXCLUDED.embedding, created_at = now()
        """,
        [
            place_id,
            embedding_version,
            vector_literal(deterministic_embedding([record.name, record.category])),
        ],
    )
    _upsert_commons_image(connection, place_id, commons_source_id, record.tags)
    return place_id, updated, merged


def _deactivate_missing_osm_records(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    destination_id: str,
    source_id: str,
    started_at: datetime,
) -> int:
    """Retire records absent from this complete source snapshot without deleting audit history."""

    stale_places = connection.execute(
        """
        UPDATE places p SET status = 'inactive', updated_at = now()
        WHERE p.destination_id = %s AND p.status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM place_source_records psr
              WHERE psr.place_id = p.id AND psr.source_id = %s
                AND psr.deleted_at IS NULL AND psr.last_seen_at >= %s
          )
        RETURNING p.id
        """,
        [destination_id, source_id, started_at],
    ).fetchall()
    connection.execute(
        """
        UPDATE place_source_records psr SET deleted_at = now()
        FROM places p
        WHERE psr.place_id = p.id AND p.destination_id = %s AND psr.source_id = %s
          AND psr.deleted_at IS NULL AND psr.last_seen_at < %s
        """,
        [destination_id, source_id, started_at],
    )
    return len(stale_places)


def _upsert_category(connection: psycopg.Connection[dict[str, Any]], slug: str) -> str:
    return _required_id(
        connection.execute(
            """
            INSERT INTO categories (slug, name) VALUES (%s, %s)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            [slug, slug.replace("_", " ").title()],
        ).fetchone()
    )


def _upsert_tags_and_features(
    connection: psycopg.Connection[dict[str, Any]], place_id: str, category: str, source_id: str
) -> None:
    tags = tags_for_category(category)
    for tag in tags:
        tag_id = _required_id(
            connection.execute(
                """
            INSERT INTO tags (slug, name) VALUES (%s, %s)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
                [tag, tag.replace("_", " ").title()],
            ).fetchone()
        )
        connection.execute(
            """
            INSERT INTO place_tags (place_id, tag_id, confidence, source_kind, source_version)
            VALUES (%s, %s, 0.7, 'rule', 'osm-tags-v1')
            ON CONFLICT (place_id, tag_id, source_version) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                calculated_at = now()
            """,
            [place_id, tag_id],
        )
    relevance = 0.9 if category in {"museum", "historic", "sight"} else 0.7
    connection.execute(
        """
        INSERT INTO place_features (
            place_id, popularity, tourist_relevance, uniqueness_score, localness, freshness,
            confidence, tourist_trap_risk, source_quality, version
        ) VALUES (%s, %s, %s, %s, 0.5, 1.0, 0.7, 0.25, 0.8, 'osm-features-v1')
        ON CONFLICT (place_id) DO UPDATE SET
            popularity = EXCLUDED.popularity, tourist_relevance = EXCLUDED.tourist_relevance,
            uniqueness_score = EXCLUDED.uniqueness_score, freshness = EXCLUDED.freshness,
            confidence = EXCLUDED.confidence, source_quality = EXCLUDED.source_quality,
            version = EXCLUDED.version, calculated_at = now()
        """,
        [place_id, relevance, relevance, 0.8 if category in {"historic", "sight"} else 0.6],
    )


def _upsert_commons_image(
    connection: psycopg.Connection[dict[str, Any]],
    place_id: str,
    source_id: str,
    tags: dict[str, str],
) -> None:
    file_name = tags.get("wikimedia_commons")
    if not file_name:
        return
    normalized_file = file_name.removeprefix("File:").replace(" ", "_")
    source_url = f"https://commons.wikimedia.org/wiki/File:{normalized_file}"
    image_url = (
        f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{normalized_file}?width=1280"
    )
    connection.execute(
        """
        INSERT INTO place_images (
            place_id, source_id, source_url, image_url, license, attribution, is_primary
        )
        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (place_id, source_url) DO UPDATE SET image_url = EXCLUDED.image_url,
            license = EXCLUDED.license, attribution = EXCLUDED.attribution, is_primary = TRUE
        """,
        [place_id, source_id, source_url, image_url, COMMONS_LICENSE, COMMONS_ATTRIBUTION],
    )
