# ADR-0016: Country-level entry assessments

- Status: proposed
- Date: 2026-07-26

## Context

The demo catalog stores `visa` and a human-readable entry string on every destination card. Those
values are synthetic, city-level, lack citizenship/date/source context, and currently influence
hard filters, ranking, card rendering and destination-chat replies. This can silently replace an
explicit country request with an unrelated destination whose fixture happens to say `none`.

Entry requirements are country-level policies whose applicability depends at least on traveller
citizenship, destination country and entry date. Passport type, travel purpose, entry mode and
stay length are relevant V1 context. An absent policy is not evidence of visa-free entry.

## Decision

Introduce a separate country-entry bounded context alongside, not inside, the POI catalog:

- Canonical countries use ISO 3166-1 alpha-2 identifiers and explicit aliases; destination
  selection, grouping and entry lookup use IDs/codes rather than localized display names.
- `EntryPolicy` is a versioned, evidenced normative rule. `EntryAssessment` is the immutable
  result of applying a policy to one traveller/trip context.
- The resolver is deterministic, batch-resolves each unique country once per recommendation
  request, and returns `ELIGIBLE`, `REQUIRES_PRETRIP_ACTION`, `INELIGIBLE` or `UNKNOWN` plus
  freshness/confidence and stable warning codes.
- Ranking translates an assessment into `PASS`, `FAIL`, `UNKNOWN` or `NOT_APPLICABLE`; it does
  not query providers or infer rules. `UNKNOWN` never proves a visa-free constraint, but is not
  silently removed from an unrestricted shortlist.
- Recommendation output persists the exact assessment payload used for the card. Destination
  subchat reads that payload and never recomputes or upgrades entry facts without a new retrieval.
- Until a sourced policy provider is available, all entry assessments are `UNKNOWN`/
  `UNAVAILABLE`. Legacy fixture visa values are display-only compatibility data and may not drive
  hard filters, scoring, or user-facing confirmed-entry claims.

The initial scope is ordinary passports, tourism, air entry and short stays. The domain model
allows other values without implementing them prematurely.

## Consequences

- A query such as “only Malaysia, visa-free only” returns an explained empty/conditional result;
  it never substitutes Thailand.
- Existing `visa_willingness` becomes a deprecated compatibility input. A future
  `visa_preference` represents user preference, not a fact about a destination.
- The places PostgreSQL database can reuse `sources` and migration conventions, but entry-policy
  provenance remains in its own tables and is not mixed with POI records.
- Production needs a selected, licensed entry-policy provider before any `verified` claim is
  enabled. No synthetic fixture values are backfilled as policies.

## Rejected alternatives

- Moving `visa` from destination JSON to a country JSON: still lacks citizenship, time, evidence
  and policy history.
- Calling an entry provider in the ranking loop: creates N+1 requests, mixes I/O with deterministic
  ranking and makes snapshots irreproducible.
- Treating `unknown` as either pass or hard failure: both are misleading; it is an explicit
  evidence state.
