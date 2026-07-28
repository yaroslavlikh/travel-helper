# ADR-0021: Provider-neutral live flight normalization

- Status: accepted
- Date: 2026-07-28

## Context

Live providers return multiple offers with different baggage, tax, passenger and itinerary
semantics. A cheap response cannot become a trip component until it is validated against one exact
date scenario and the full party.

## Decision

Normalize adapters into immutable `FlightOffer` records. The deterministic aggregation layer checks
route, dates, passenger composition, expiry, taxes, mandatory fees, stops, duration, self-transfer
and baggage before producing a `flight` component.
Only offers confirmed by the provider's pricing/revalidation step may contribute to expected or
safe. Search-only offers can remain diagnostics but cannot produce a complete component.

Offers are deduplicated by provider-neutral itinerary key. A price below 55% of the first-ten median
is excluded from floor unless revalidated with known baggage. Expected is based on the first three
cheap acceptable offers; safe uses the configured upper quartile of the first five. If required or
unknown baggage has no confirmed included/known-extra offer, the component is missing.

The exact Amadeus REST adapter and Flight Offers Price revalidation remain a separate credentialed
slice. This decision defines the contract they must satisfy.
