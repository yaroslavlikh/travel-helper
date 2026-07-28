# ADR-0020: Aviasales Data API only as cached date discovery

- Status: accepted
- Date: 2026-07-28

## Context

The Aviasales Data API exposes prices cached from user searches. Its documented request does not
carry the exact trip party, and cached observations do not confirm current availability.

## Decision

Use `prices_for_dates` only to produce `FlightPriceSignal` records and shortlist exact date
scenarios for later live pricing. Every signal is labelled `cached_unknown_party`,
`usable_for_total=false`, has an explicit `expires_at`, and is matched to a generated date scenario.

The API token is sent in `X-Access-Token`, never logged or stored in snapshots. Expired, malformed,
zero, negative or date-mismatched observations are discarded. For month discovery, select up to
twelve scenarios using six cheapest signals plus deterministic early/middle/late coverage.

## Consequences

- Cached prices cannot become a flight component or full-trip total.
- No public pricing endpoint is enabled by this slice.
- Live flight pricing with exact passenger composition remains required before cards show totals.
