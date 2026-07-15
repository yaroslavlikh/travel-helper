"""Apply ordered PostgreSQL migrations for canonical places storage."""

from __future__ import annotations

from pathlib import Path

import psycopg

from app.core.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "places"


def main() -> None:
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    with psycopg.connect(settings.places_database_url, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name in applied:
                continue
            connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", [migration.name]
            )
            print(f"applied {migration.name}")


if __name__ == "__main__":
    main()
