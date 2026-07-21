# ADR-0014: Multi-city POI catalog rollout

- Status: accepted
- Date: 2026-07-21

## Context

The product catalog has 26 destinations, while the provenance-backed POI pipeline is currently
hard-coded to Istanbul. Copying its code or copying its POIs to other destinations would make
subchat quality inconsistent and break source boundaries.

## Decision

All supported destinations are declared in one versioned catalog configuration with a bounded OSM
scope, country code, city label and stable context. The importer accepts a destination ID, records
that ID and scope in every import run, and keeps the existing source identity/lifecycle rules.

Each city is populated and evaluated independently. A city becomes subchat-searchable only after
its import passes the catalog bounds and its destination-specific eval is recorded. Dynamic facts
remain unknown until dedicated sourced snapshots exist.

## Consequences

- 26 destinations can reuse one importer and database schema without a global unbounded crawler.
- A partially populated city cannot masquerade as a complete catalog.
- The rollout remains a sequence of verifiable city imports, not a one-off fixture generation.
