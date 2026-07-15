# ADR-0009: Istanbul places data pipeline

- Status: accepted for the first live-data vertical slice
- Date: 2026-07-15

## Context

Current destination cards are built from local demo fixtures. They do not support a real query over
places, provenance per external value, repeatable imports or geographic filtering. Replacing the
chat checkpointer or the complete MVP would add risk without helping validate a single-city places
search.

## Decision

Add a separate PostgreSQL database for canonical travel places. It enables `postgis`, `vector` and
`pgcrypto`; SQLite remains the local LangGraph checkpointer. Schema changes are ordered SQL
migrations executed by a small repository-owned runner. The runtime creates the places repository
only when `PLACES_DATABASE_URL` is configured; otherwise the existing demo journey stays available.

The first city is Istanbul. Its importer fetches a bounded, public OpenStreetMap/Overpass scope,
persists the raw payload and a manifest, then normalizes and upserts 100–300 tourist-relevant
objects. Overture, Wikidata, Wikivoyage and Commons are represented as provenance-compatible
sources and can enrich the same canonical records without changing the public API.

The initial embedding is deterministic and local (`hash-v1`), stored in pgvector to validate the
hybrid retrieval contract without a paid model or a separate vector database. It is a retrieval
signal only, never a source of facts. A later embedding provider replaces that implementation by
version, not by schema rewrite.

## Consequences

- Each imported source record retains `source_id + external_id`, a raw snapshot checksum and a link
  to one canonical UUID place.
- Re-import is idempotent: source identity is checked first; then name plus a small PostGIS radius
  supports conservative merging.
- Place output carries category, tags, scores, freshness, image attribution and ranking version.
- The importer creates no global catalog and only stores the selected city scope.
- The API fails explicitly as unavailable when the places database is not configured; it does not
  silently return demo places as live search results.

## Rejected alternatives

- Extending the JSON destination fixture into a fake global POI database: no provenance, imports or
  geographic query semantics.
- Running a separate vector database: pgvector is sufficient for one city and avoids extra ops.
- Letting the LLM invent places: violates evidence-first ranking and cannot be audited.
