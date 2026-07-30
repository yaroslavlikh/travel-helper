"""Populate the non-published 60-country canonical identity catalog."""

from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings
from app.geography.bootstrap import CountrySeed, load_country_seed, normalized_alias


def main() -> None:
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    manifest = load_country_seed()
    with psycopg.connect(settings.places_database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            source_id = _upsert_seed_source(connection)
            for country in manifest.countries:
                entity_id = _upsert_country(connection, country)
                _upsert_aliases(connection, entity_id, country.aliases, source_id)
    print(json.dumps({"countries": len(manifest.countries), "status": "draft"}))


def _upsert_seed_source(connection: psycopg.Connection[dict[str, object]]) -> str:
    row = connection.execute(
        """
        INSERT INTO source_registry (
            domain, publisher, source_type, base_url, quality_tier, terms_url,
            allows_storage, allows_derived_data, allows_embeddings, polling_policy, status
        ) VALUES (
            'geography', 'catalog-roadmap', 'editorial', NULL, 'c', NULL,
            TRUE, TRUE, FALSE, %s::jsonb, 'review'
        )
        ON CONFLICT (publisher, domain, source_type) DO UPDATE
        SET polling_policy = EXCLUDED.polling_policy, updated_at = now()
        RETURNING id
        """,
        [json.dumps({"mode": "manual_seed", "refresh": "before_publish"})],
    ).fetchone()
    if row is None:
        raise RuntimeError("Expected canonical seed source id")
    return str(row["id"])


def _upsert_country(connection: psycopg.Connection[dict[str, object]], country: CountrySeed) -> str:
    row = connection.execute(
        """
        INSERT INTO geo_entities (
            entity_type, canonical_name, canonical_name_ru, canonical_name_en, slug,
            iso2, iso3, status
        ) VALUES ('sovereign_country', %s, %s, %s, %s, %s, %s, 'draft')
        ON CONFLICT (slug) DO UPDATE
        SET canonical_name = EXCLUDED.canonical_name,
            canonical_name_ru = EXCLUDED.canonical_name_ru,
            canonical_name_en = EXCLUDED.canonical_name_en,
            iso2 = EXCLUDED.iso2,
            iso3 = EXCLUDED.iso3,
            updated_at = now()
        RETURNING id
        """,
        [
            country.name_en,
            country.name_ru,
            country.name_en,
            country.slug,
            country.iso2,
            country.iso3,
        ],
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Expected canonical id for {country.slug}")
    return str(row["id"])


def _upsert_aliases(
    connection: psycopg.Connection[dict[str, object]],
    entity_id: str,
    aliases: list[str],
    source_id: str,
) -> None:
    for alias in aliases:
        connection.execute(
            """
            INSERT INTO geo_aliases (
                geo_entity_id, alias, normalized_alias, alias_type, is_preferred, source_registry_id
            ) VALUES (%s, %s, %s, 'common', FALSE, %s)
            ON CONFLICT (geo_entity_id, normalized_alias, language_code) DO UPDATE
            SET alias = EXCLUDED.alias, source_registry_id = EXCLUDED.source_registry_id
            """,
            [entity_id, alias, normalized_alias(alias), source_id],
        )


if __name__ == "__main__":
    main()
