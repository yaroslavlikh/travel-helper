from contextlib import contextmanager
from pathlib import Path

from scripts.migrate_places import apply_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATOR = ROOT / "scripts" / "migrate_places.py"
CHECKER = ROOT / "scripts" / "check_places_database.py"
MIGRATIONS = ROOT / "migrations" / "places"


class FakeResult:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.transaction_events: list[str] = []

    @contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        self.transaction_events.append("begin")
        yield
        self.transaction_events.append("commit")

    def execute(self, statement: str, _params: object = None) -> FakeResult:
        self.statements.append(statement)
        if statement == "SELECT version FROM schema_migrations":
            return FakeResult([{"version": "001_first.sql"}])
        return FakeResult()


def test_places_migrations_require_extensions_without_destructive_sql() -> None:
    statements = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS.glob("*.sql"))
    )

    for extension in ("postgis", "vector", "pgcrypto"):
        assert f"CREATE EXTENSION IF NOT EXISTS {extension}" in statements
    for forbidden in ("DROP DATABASE", "DROP SCHEMA", "DROP TABLE"):
        assert forbidden not in statements


def test_places_migrator_is_transactional_and_serialized() -> None:
    source = MIGRATOR.read_text(encoding="utf-8")

    assert "autocommit=True" not in source
    assert "with connection.transaction():" in source
    assert "pg_advisory_xact_lock" in source
    assert "INSERT INTO schema_migrations" in source


def test_places_migrator_records_only_pending_versions_inside_one_transaction(
    tmp_path: Path,
) -> None:
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    connection = FakeConnection()

    applied = apply_migrations(connection, migrations_dir=tmp_path)  # type: ignore[arg-type]

    assert applied == ["002_second.sql"]
    assert connection.transaction_events == ["begin", "commit"]
    assert connection.statements.index("SELECT 2;") < next(
        index
        for index, statement in enumerate(connection.statements)
        if "INSERT INTO schema_migrations" in statement
    )


def test_places_database_check_covers_schema_extensions_and_foreign_keys() -> None:
    source = CHECKER.read_text(encoding="utf-8")

    for required in (
        "postgis",
        "vector",
        "pgcrypto",
        "schema_migrations",
        "destinations",
        "places",
        "geo_entities",
        "foreign_key_integrity",
    ):
        assert required in source
