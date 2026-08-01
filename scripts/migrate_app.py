"""Apply additive PostgreSQL migrations for application-owned state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "app"
MIGRATION_LOCK_KEY = "tudavai:app-migrations"


def migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> tuple[Path, ...]:
    return tuple(sorted(migrations_dir.glob("*.sql")))


def apply_migrations(
    connection: psycopg.Connection[dict[str, Any]], *, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply pending app migrations once, atomically, without touching places tables."""

    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [MIGRATION_LOCK_KEY])
        connection.execute("CREATE SCHEMA IF NOT EXISTS app")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS app.schema_migrations (
            version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
        )
        applied = {
            str(row["version"])
            for row in connection.execute("SELECT version FROM app.schema_migrations").fetchall()
        }
        pending = [item for item in migration_files(migrations_dir) if item.name not in applied]
        for migration in pending:
            connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO app.schema_migrations (version) VALUES (%s)", [migration.name]
            )
    return [item.name for item in pending]


def main() -> None:
    settings = Settings()
    if not settings.database_url_value:
        raise SystemExit("DATABASE_URL is required")
    with psycopg.connect(settings.database_url_value, row_factory=dict_row) as connection:
        for version in apply_migrations(connection):
            print(f"applied {version}")


if __name__ == "__main__":
    main()
