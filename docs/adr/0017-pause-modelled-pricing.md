# ADR-0017: Pause modelled pricing until sourced providers exist

- Status: superseded by ADR-0018
- Date: 2026-07-26

## Context

The previous pricing slice extrapolated whole-trip totals from local demo fixture baselines. It was
useful for a prototype but is not live availability or price evidence. Showing those figures on a
recommendation card risks presenting a modelled estimate as a purchasable price.

## Decision

Remove modelled pricing contracts, calculation, card rendering and price-specific subchat context.
The fixture total range remains internal demo evidence for deterministic budget fit and strict-budget
checks; it is not exposed as a user-facing price. A new pricing implementation needs a separate ADR,
sourced provider evidence, freshness and an explicit card contract.

## Consequences

- Recommendation cards keep route, weather, entry and place context but no price block.
- A budget question in a destination subchat directs the traveller to external search rather than
  inventing an estimate.
- The next pricing design starts from provider/evidence requirements rather than compatibility with
  the removed modelled snapshot API.
