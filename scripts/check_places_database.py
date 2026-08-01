"""Report whether the configured places PostgreSQL database is ready for catalog use."""

from __future__ import annotations

import json
from typing import Any, cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.core.config import Settings

REQUIRED_EXTENSIONS = ("postgis", "vector", "pgcrypto")
KEY_TABLES = (
    "schema_migrations",
    "destinations",
    "places",
    "geo_entities",
    "geo_aliases",
    "source_registry",
)


def _foreign_key_orphans(connection: psycopg.Connection[dict[str, Any]]) -> list[dict[str, object]]:
    constraints = connection.execute(
        """
        SELECT
            constraint_row.conname,
            child_namespace.nspname AS child_schema,
            child_table.relname AS child_table,
            parent_namespace.nspname AS parent_schema,
            parent_table.relname AS parent_table,
            array_agg(child_attribute.attname ORDER BY child_key.ordinality) AS child_columns,
            array_agg(parent_attribute.attname ORDER BY child_key.ordinality) AS parent_columns
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS child_table ON child_table.oid = constraint_row.conrelid
        JOIN pg_namespace AS child_namespace ON child_namespace.oid = child_table.relnamespace
        JOIN pg_class AS parent_table ON parent_table.oid = constraint_row.confrelid
        JOIN pg_namespace AS parent_namespace ON parent_namespace.oid = parent_table.relnamespace
        JOIN LATERAL unnest(constraint_row.conkey) WITH ORDINALITY AS child_key(attnum, ordinality)
            ON TRUE
        JOIN pg_attribute AS child_attribute
            ON child_attribute.attrelid = child_table.oid
            AND child_attribute.attnum = child_key.attnum
        JOIN LATERAL unnest(constraint_row.confkey)
            WITH ORDINALITY AS parent_key(attnum, ordinality)
            ON parent_key.ordinality = child_key.ordinality
        JOIN pg_attribute AS parent_attribute
            ON parent_attribute.attrelid = parent_table.oid
            AND parent_attribute.attnum = parent_key.attnum
        WHERE constraint_row.contype = 'f' AND child_namespace.nspname = 'public'
        GROUP BY
            constraint_row.conname, child_namespace.nspname, child_table.relname,
            parent_namespace.nspname, parent_table.relname
        ORDER BY child_table.relname, constraint_row.conname
        """
    ).fetchall()
    broken: list[dict[str, object]] = []
    for constraint in constraints:
        child_columns = [str(value) for value in cast(list[object], constraint["child_columns"])]
        parent_columns = [str(value) for value in cast(list[object], constraint["parent_columns"])]
        child = sql.Identifier("child")
        parent = sql.Identifier("parent")
        all_columns_present = sql.SQL(" AND ").join(
            sql.SQL("{}.{} IS NOT NULL").format(child, sql.Identifier(column))
            for column in child_columns
        )
        matching_columns = sql.SQL(" AND ").join(
            sql.SQL("{}.{} = {}.{}").format(
                parent, sql.Identifier(parent_column), child, sql.Identifier(child_column)
            )
            for child_column, parent_column in zip(child_columns, parent_columns, strict=True)
        )
        statement = sql.SQL(
            """
            SELECT count(*) AS orphan_count
            FROM {}.{} AS {}
            WHERE {} AND NOT EXISTS (
                SELECT 1 FROM {}.{} AS {} WHERE {}
            )
            """
        ).format(
            sql.Identifier(str(constraint["child_schema"])),
            sql.Identifier(str(constraint["child_table"])),
            child,
            all_columns_present,
            sql.Identifier(str(constraint["parent_schema"])),
            sql.Identifier(str(constraint["parent_table"])),
            parent,
            matching_columns,
        )
        result = connection.execute(statement).fetchone()
        orphan_count = int(result["orphan_count"]) if result else 0
        if orphan_count:
            broken.append(
                {
                    "constraint": str(constraint["conname"]),
                    "table": str(constraint["child_table"]),
                    "orphan_count": orphan_count,
                }
            )
    return broken


def inspect_database(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, object]:
    """Read database readiness without changing schema or catalog data."""

    connection.execute("SELECT 1").fetchone()
    extensions = {
        str(row["extname"])
        for row in connection.execute(
            "SELECT extname FROM pg_extension WHERE extname = ANY(%s)", [list(REQUIRED_EXTENSIONS)]
        ).fetchall()
    }
    tables = {
        str(row["table_name"])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    }
    migrations = (
        [
            str(row["version"])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        if "schema_migrations" in tables
        else []
    )
    counts: dict[str, int | None] = {
        "countries": None,
        "destinations": None,
        "places": None,
    }
    if "geo_entities" in tables:
        row = connection.execute(
            "SELECT count(*) AS count FROM geo_entities WHERE entity_type = 'sovereign_country'"
        ).fetchone()
        counts["countries"] = int(row["count"]) if row else 0
    for table in ("destinations", "places"):
        if table in tables:
            row = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
            ).fetchone()
            counts[table] = int(row["count"]) if row else 0
    unvalidated = [
        str(row["conname"])
        for row in connection.execute(
            "SELECT conname FROM pg_constraint WHERE contype = 'f' AND NOT convalidated"
        ).fetchall()
    ]
    disabled_triggers = [
        str(row["tgname"])
        for row in connection.execute(
            "SELECT tgname FROM pg_trigger WHERE tgconstraint <> 0 AND tgenabled = 'D'"
        ).fetchall()
    ]
    broken = _foreign_key_orphans(connection)
    foreign_key_integrity = {
        "status": "ok" if not (broken or unvalidated or disabled_triggers) else "failed",
        "broken": broken,
        "unvalidated": unvalidated,
        "disabled_triggers": disabled_triggers,
    }
    return {
        "connection": "ok",
        "extensions": {extension: extension in extensions for extension in REQUIRED_EXTENSIONS},
        "applied_migrations": migrations,
        "key_tables": {table: table in tables for table in KEY_TABLES},
        "counts": counts,
        "foreign_key_integrity": foreign_key_integrity,
    }


def database_is_ready(report: dict[str, object]) -> bool:
    extensions = cast(dict[str, bool], report["extensions"])
    tables = cast(dict[str, bool], report["key_tables"])
    integrity = cast(dict[str, object], report["foreign_key_integrity"])
    return all(extensions.values()) and all(tables.values()) and integrity["status"] == "ok"


def main() -> None:
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    with psycopg.connect(settings.places_database_url, row_factory=dict_row) as connection:
        report = inspect_database(connection)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not database_is_ready(report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
