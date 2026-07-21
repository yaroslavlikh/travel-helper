# ADR-0013: Istanbul POI quality selection and lexical retrieval baseline

- Status: accepted for Stage 1
- Date: 2026-07-21

## Context

The first Istanbul importer retained the first 300 Overpass rows and labelled a deterministic token
hash as a semantic embedding. Its evaluation repeated the same category hints used by ranking, so
it did not independently measure useful Russian-language retrieval. Records missing from a later
full source snapshot also stayed active.

## Decision

The importer normalizes every received candidate before deterministic quality selection. It keeps
100–300 named, tourist-relevant records ordered by explicit category, OSM completeness and linked
Wikidata/Wikipedia/Commons signals; it does not fabricate popularity. Exact normalized-name plus a
120 m location match remains the only automatic cross-record merge.

`hash-v1` remains a storage compatibility vector but is not used as semantic relevance. Online
retrieval is explicitly lexical/category/geospatial, with transparent stable area hints for the
published Istanbul destination context. A later multilingual embedding adapter must demonstrate
improvement on the independent eval set before being enabled.

Every complete import marks source records absent from that snapshot stale and deactivates a
canonical place when it has no current source record. The destination subchat receives a bounded
Istanbul context and at most five retrieved POIs, each with source and optional licensed-description
provenance.

## Consequences

- A response-order change from Overpass cannot decide catalog membership.
- Current retrieval is an honest baseline, not a claimed semantic search.
- The independent 40-case eval measures names, categories, area intent and negative relevance.
- Dynamic destination facts remain unknown until a separately sourced snapshot is introduced.
