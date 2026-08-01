"""Read-only readiness report for application-owned PostgreSQL state."""

from __future__ import annotations

import json
from typing import Any, cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.core.config import Settings

APP_TABLES = (
    "schema_migrations",
    "accounts",
    "account_sessions",
    "account_chats",
    "feedback_events",
    "product_events",
)
CHECKPOINT_TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)


def _foreign_key_orphans(connection: psycopg.Connection[dict[str, Any]]) -> list[dict[str, object]]:
    constraints = connection.execute(
        """SELECT c.conname, child.relname AS child_table, parent.relname AS parent_table,
        array_agg(child_attribute.attname ORDER BY child_key.ordinality) AS child_columns,
        array_agg(parent_attribute.attname ORDER BY child_key.ordinality) AS parent_columns
        FROM pg_constraint c
        JOIN pg_class child ON child.oid = c.conrelid
        JOIN pg_namespace ns ON ns.oid = child.relnamespace
        JOIN pg_class parent ON parent.oid = c.confrelid
        JOIN LATERAL unnest(c.conkey) WITH ORDINALITY child_key(attnum, ordinality) ON TRUE
        JOIN pg_attribute child_attribute ON child_attribute.attrelid = child.oid
            AND child_attribute.attnum = child_key.attnum
        JOIN LATERAL unnest(c.confkey) WITH ORDINALITY parent_key(attnum, ordinality)
            ON parent_key.ordinality = child_key.ordinality
        JOIN pg_attribute parent_attribute ON parent_attribute.attrelid = parent.oid
            AND parent_attribute.attnum = parent_key.attnum
        WHERE c.contype = 'f' AND ns.nspname = 'app'
        GROUP BY c.conname, child.relname, parent.relname
        ORDER BY child.relname, c.conname"""
    ).fetchall()
    broken: list[dict[str, object]] = []
    for constraint in constraints:
        child_columns = cast(list[str], constraint["child_columns"])
        parent_columns = cast(list[str], constraint["parent_columns"])
        child, parent = sql.Identifier("child"), sql.Identifier("parent")
        present = sql.SQL(" AND ").join(
            sql.SQL("{}.{} IS NOT NULL").format(child, sql.Identifier(column))
            for column in child_columns
        )
        matches = sql.SQL(" AND ").join(
            sql.SQL("{}.{} = {}.{}").format(
                parent, sql.Identifier(parent_column), child, sql.Identifier(child_column)
            )
            for child_column, parent_column in zip(child_columns, parent_columns, strict=True)
        )
        result = connection.execute(
            sql.SQL("""SELECT count(*) AS count FROM app.{} AS {} WHERE {} AND NOT EXISTS
            (SELECT 1 FROM app.{} AS {} WHERE {})""").format(
                sql.Identifier(str(constraint["child_table"])),
                child,
                present,
                sql.Identifier(str(constraint["parent_table"])),
                parent,
                matches,
            )
        ).fetchone()
        count = int(result["count"]) if result else 0
        if count:
            broken.append({"constraint": str(constraint["conname"]), "orphan_count": count})
    return broken


def inspect_database(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, object]:
    connection.execute("SELECT 1").fetchone()
    app_tables = {
        str(row["table_name"])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'app'"
        ).fetchall()
    }
    public_tables = {
        str(row["table_name"])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    }
    migrations = (
        [
            str(row["version"])
            for row in connection.execute(
                "SELECT version FROM app.schema_migrations ORDER BY version"
            ).fetchall()
        ]
        if "schema_migrations" in app_tables
        else []
    )
    counts: dict[str, int | None] = {}
    for table in (
        "accounts",
        "account_sessions",
        "account_chats",
        "feedback_events",
        "product_events",
    ):
        row = (
            connection.execute(
                sql.SQL("SELECT count(*) AS count FROM app.{}").format(sql.Identifier(table))
            ).fetchone()
            if table in app_tables
            else None
        )
        counts[table] = int(row["count"]) if row else None
    broken = _foreign_key_orphans(connection)
    return {
        "connection": "ok",
        "applied_migrations": migrations,
        "app_tables": {table: table in app_tables for table in APP_TABLES},
        "counts": counts,
        "foreign_key_integrity": {"status": "ok" if not broken else "failed", "broken": broken},
        "checkpointer": {table: table in public_tables for table in CHECKPOINT_TABLES},
    }


def database_is_ready(report: dict[str, object]) -> bool:
    return (
        all(cast(dict[str, bool], report["app_tables"]).values())
        and all(cast(dict[str, bool], report["checkpointer"]).values())
        and cast(dict[str, str], report["foreign_key_integrity"])["status"] == "ok"
    )


def main() -> None:
    settings = Settings()
    if not settings.database_url_value:
        raise SystemExit("DATABASE_URL is required")
    with psycopg.connect(settings.database_url_value, row_factory=dict_row) as connection:
        report = inspect_database(connection)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not database_is_ready(report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
