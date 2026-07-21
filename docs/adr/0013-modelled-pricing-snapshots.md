# ADR-0013: Modelled trip-cost snapshots before live pricing providers

- Status: accepted for the first pricing vertical slice
- Date: 2026-07-21

## Context

The demo catalog exposed an ambiguous `min/max` total and used its lower bound for strict-budget
filtering. Cards and destination subchats therefore could not say whether a number covered the
whole party, which costs were included, or whether it was current provider availability.

Live flight and hotel APIs are not available for this MVP slice. A CTA is navigation, not price
evidence, so pretending a route link is a live quote would be misleading.

## Decision

The first slice adds a deterministic `TripCostEstimate` for every demo-card. It is explicitly
`modelled`, uses the local catalog baselines, and calculates `floor`, `expected`, and `safe` totals
for the whole selected group. The card headline is expected-to-safe; floor is secondary.

Strict budget passes only when safe total is within budget. When only strict-budget failures remain,
the shortlist may show them as fallback candidates without changing `passed_hard_filters`.

Every returned card carries a deterministic pricing snapshot ID and recommendation snapshot ID.
The current card collection is stored in the parent checkpoint, and destination chat resolves that
stored snapshot rather than re-running ranking. It receives the component breakdown and source
kind. No live refresh, persistent observations table, provider client, or scraping is added here.

## Consequences

- Users see a transparent planning estimate rather than a false price claim.
- A refinement creates a new card snapshot; an open subchat remains scoped to the card it received.
- Future cached/live providers replace component inputs behind the same output contract.
- The modelled fixture is low-confidence and remains clearly labelled until benchmarked sources
  exist.

## Rejected alternatives

- Treating Aviasales deeplinks as a price source: a link does not confirm price or availability.
- Choosing random dates for month-only queries: creates unsupported precision.
- Adding provider ports and database tables without a provider: speculative infrastructure.
