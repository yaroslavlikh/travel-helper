# ADR-0010: Provenance-preserving POI descriptions for bounded retrieval

- Status: accepted for the Istanbul places vertical slice
- Date: 2026-07-18

## Context

The initial Istanbul catalog contains an entity, coordinates, category, rule-based tags and source
provenance. That is sufficient to identify a place, but not sufficient to answer a narrow
destination-subchat question with useful, source-backed context. Sending the full catalog, raw OSM
payloads or the entire conversation to a model would increase token cost, weaken auditability and
make prompt-injection handling harder.

Travel articles can be useful context, but publication on a public platform is not permission to
copy, persist, embed or redistribute the text. In particular, arbitrary crawling of blogs or Dzen
is outside this decision. A description is accepted only when the importer receives an explicit
license or a recorded direct permission that permits storage and embeddings.

## Decision

Add a bounded POI-description document model in the existing PostgreSQL/PostGIS/pgvector catalog.
It is not a general-purpose web corpus.

1. A source has an explicit usage policy: whether its text may be stored, embedded and shown as an
   attributed excerpt. The importer rejects a description when these permissions are absent.
2. Each document is bound to one existing canonical place through a source record and keeps a
   source URL, license, attribution, language, content type, observed time, optional expiry and an
   immutable source snapshot checksum.
3. The active document is split deterministically into small chunks. Each chunk gets a versioned
   local embedding. A change to content replaces the active chunks; the original source snapshot
   remains auditable.
4. The online place search returns at most one active, non-expired description per place. The
   subchat sends a clipped excerpt only for the already retrieved top places. It treats that text as
   untrusted evidence and never as proof of live opening hours, prices or availability.
5. The first import path accepts a reviewed local JSON manifest. It performs no web crawling and no
   implicit network calls. This makes the licence decision, matching and freshness review explicit.

## Consequences

- PostgreSQL remains the source of truth for canonical POIs, documents, chunks, vectors and
  provenance; no new vector database is introduced.
- The RAG prompt stays bounded: selected-card context, short subthread history and short excerpts
  from the top retrieved POIs only.
- A source can later be added through a dedicated adapter only after its terms, fetch policy,
  attribution format and retention have been reviewed. Direct partner permission for a Dzen author
  is acceptable when it explicitly covers persistence, embeddings and display.
- Descriptions may be unavailable without making a POI unavailable. The response continues with
  the canonical entity data and does not fabricate a summary.
- Current operational facts require a source with an appropriate freshness policy. Static
  historical context and mutable facts are intentionally not conflated.

## Rejected alternatives

- Storing all articles or raw crawled pages directly in LangGraph state: unbounded context,
  poor retention control and no provenance boundary.
- Using public visibility as an implied right to embed articles: legally and operationally unsafe.
- Letting an LLM write a description from only a POI name: violates evidence-first behaviour.
- Adding a separate vector database for one city: pgvector already covers this bounded scale.
