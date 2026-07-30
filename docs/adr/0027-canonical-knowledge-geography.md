# ADR-0027: Canonical geography and knowledge schema

- Status: accepted
- Date: 2026-07-30

## Context

The current places database is a bounded POI catalog. Its `destinations` table identifies a search
scope by slug and optional country code; it has no hierarchy, aliases, jurisdictions or airport
relations. The `sources` table preserves POI provenance but cannot express source terms, domain,
polling policy or generic source documents. Istanbul is the only verified POI/retrieval vertical
slice.

The global knowledge plan needs canonical country/destination identity, explicit support coverage,
and source-backed facts and qualitative chunks. Renaming or repurposing the current operational
tables would break the working importer and repository before the new data model is proved.

## Decision

Add the canonical layer as ordered, additive migrations in the existing places PostgreSQL database.
PostgreSQL, PostGIS and pgvector remain the only data infrastructure.

1. `geo_entities`, `geo_aliases` and `geo_relations` are the canonical identity model. They can
   represent sovereign countries, travel jurisdictions, territories, regions, cities, islands,
   resorts, coasts and airport zones.
2. Existing `destinations` remains the POI retrieval-scope table. A nullable, unique
   `geo_entity_id` explicitly bridges a published scope to canonical identity. It is not populated
   by the schema migration and the old `slug` queries continue to work.
3. `destination_domain_support` stores only per-domain support evidence and conservative coverage.
   No row means `none`; support never changes suitability score or rank by itself.
4. `source_registry` holds the reviewed source policy. Existing `sources` retains current POI
   provenance and gets a nullable explicit `source_registry_id` bridge. No historical payload or
   licence claim is copied by migration.
5. `source_documents`, `evidence_spans`, `knowledge_facts`, `fact_evidence`, `fact_conflicts` and
   `knowledge_chunks` are generic knowledge contracts. Exact facts and qualitative chunks are
   deliberately separate. The initial fact subject is a canonical geo entity; POI facts remain in
   their provenanced places model until a dedicated subject bridge is approved.
6. The migration creates no countries, destinations, POIs, source documents, facts or chunks. Data
   bootstrap happens only after an empty-database migration contract and the existing Istanbul
   importer remain green.

## Consequences

- There is one catalog database and no parallel RAG store.
- Existing Istanbul retrieval keeps working while generic identity and support coverage become
  available incrementally.
- A source URL alone cannot make a fact publishable: facts require evidence spans linked to source
  documents; chunks retain their supporting source/evidence identifiers.
- Live entry, pricing, current weather, opening hours and disruptions remain provider data with
  explicit freshness rules. They are not made permanent chunks by this schema.
- Runtime domain repositories, entity resolution, ingestion, hybrid retrieval and subchat
  answerability are separate future increments. The schema alone does not claim any destination is
  FULL or search-ready.

## Rejected alternatives

- Extending the fixture JSON as a global RAG corpus: it cannot preserve source, freshness or
  conflict semantics.
- Renaming `destinations` into a universal geography table: breaks the active POI importer/retrieval
  contract and conflates search scope with country/jurisdiction identity.
- Adding a second vector database or a RAG framework before there is a semantic model and a
  benchmark: pgvector plus PostgreSQL FTS are sufficient for the planned first generic slice.
