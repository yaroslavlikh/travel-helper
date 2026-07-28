# ADR-0025: Pricing state is always visible

- Status: accepted
- Date: 2026-07-28

## Context

After removing model-generated trip prices, cards silently lost the entire pricing section. A user
could not distinguish an intentionally unavailable calculation from a frontend regression.

## Decision

Every recommendation carries a typed pricing presentation. A provider-backed immutable snapshot
shows `floor`, `expected`, `safe`, component breakdown and freshness. Without a complete snapshot,
the same area names missing critical components and shows no numeric amount.

Fixture ranges, candidate ranking evidence and LLM output cannot populate this contract. The
destination subchat receives exactly the pricing presentation stored with the recommendation and
cannot recalculate or invent a price.

Live flight and stay credentials remain an external prerequisite for numeric totals.
