from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "places"
    / "003_global_knowledge_schema.sql"
)


def test_global_knowledge_migration_keeps_existing_places_tables_as_bridges() -> None:
    statement = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE geo_entities" in statement
    assert "CREATE TABLE geo_aliases" in statement
    assert "CREATE TABLE geo_relations" in statement
    assert "ALTER TABLE destinations ADD COLUMN IF NOT EXISTS geo_entity_id" in statement
    assert "ALTER TABLE sources ADD COLUMN IF NOT EXISTS source_registry_id" in statement
    assert "DROP TABLE destinations" not in statement
    assert "DROP TABLE sources" not in statement


def test_global_knowledge_migration_requires_support_and_evidence_contracts() -> None:
    statement = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "destination_domain_support",
        "source_registry",
        "source_documents",
        "evidence_spans",
        "knowledge_facts",
        "fact_evidence",
        "fact_conflicts",
        "knowledge_chunks",
    ):
        assert f"CREATE TABLE {table}" in statement

    assert "CHECK (cardinality(source_document_ids) > 0)" in statement
    assert "CHECK (cardinality(evidence_span_ids) > 0)" in statement
    assert "CHECK (jsonb_typeof(warnings) = 'array')" in statement
