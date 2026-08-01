"""Apply ordered, transactional PostgreSQL migrations for canonical places storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "places"
MIGRATION_LOCK_KEY = "tudavai:places-migrations"


def migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> tuple[Path, ...]:
    """Return the immutable ordered migration list."""

    return tuple(sorted(migrations_dir.glob("*.sql")))


def apply_migrations(
    connection: psycopg.Connection[dict[str, Any]], *, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply every pending migration atomically while holding a database-wide advisory lock."""

    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [MIGRATION_LOCK_KEY])
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            str(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        pending = [
            migration
            for migration in migration_files(migrations_dir)
            if migration.name not in applied
        ]
        for migration in pending:
            connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", [migration.name]
            )
    return [migration.name for migration in pending]


def main() -> None:
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    with psycopg.connect(settings.places_database_url, row_factory=dict_row) as connection:
        for version in apply_migrations(connection):
            print(f"applied {version}")


if __name__ == "__main__":
    main()
