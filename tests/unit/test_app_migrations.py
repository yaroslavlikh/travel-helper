from contextlib import contextmanager
from pathlib import Path

from scripts.migrate_app import apply_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATOR = ROOT / "scripts" / "migrate_app.py"
CHECKER = ROOT / "scripts" / "check_app_database.py"
SETUP = ROOT / "scripts" / "setup_langgraph_postgres.py"
MIGRATIONS = ROOT / "migrations" / "app"


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
        if statement == "SELECT version FROM app.schema_migrations":
            return FakeResult([{"version": "001_first.sql"}])
        return FakeResult()


def test_app_migrations_are_additive_and_preserve_places_schema() -> None:
    statements = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS.glob("*.sql"))
    )

    for required in ("CREATE SCHEMA IF NOT EXISTS app", "UUID", "TIMESTAMPTZ", "JSONB"):
        assert required in statements
    for forbidden in ("DROP DATABASE", "DROP SCHEMA", "DROP TABLE", "DELETE FROM"):
        assert forbidden not in statements
    assert "places." not in statements


def test_app_migrator_is_transactional_and_serialized() -> None:
    source = MIGRATOR.read_text(encoding="utf-8")

    assert "with connection.transaction():" in source
    assert "pg_advisory_xact_lock" in source
    assert "app.schema_migrations" in source


def test_app_migrator_records_only_pending_versions_inside_one_transaction(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    connection = FakeConnection()

    applied = apply_migrations(connection, migrations_dir=tmp_path)  # type: ignore[arg-type]

    assert applied == ["002_second.sql"]
    assert connection.transaction_events == ["begin", "commit"]
    assert connection.statements.index("SELECT 2;") < next(
        index for index, statement in enumerate(connection.statements) if "INSERT INTO" in statement
    )


def test_database_check_and_langgraph_setup_use_only_the_application_database_url() -> None:
    checker = CHECKER.read_text(encoding="utf-8")
    setup = SETUP.read_text(encoding="utf-8")

    for required in ("SELECT 1", "app_tables", "foreign_key_integrity", "checkpointer"):
        assert required in checker
    assert "AsyncPostgresSaver" in setup
    assert "PLACES_DATABASE_URL" not in checker + setup
