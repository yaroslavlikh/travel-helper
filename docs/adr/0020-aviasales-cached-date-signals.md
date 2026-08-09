# ADR-0020: Aviasales Data API only as cached date discovery

- Status: accepted
- Date: 2026-07-28

## Context

The Aviasales Data API exposes prices cached from user searches. Its documented request does not
carry the exact trip party, and cached observations do not confirm current availability.

## Decision

Use `prices_for_dates` only to produce `FlightPriceSignal` records, shortlist exact date
scenarios and show a clearly marked cached flight observation in a destination card. Every signal
is labelled `cached_unknown_party`, `usable_for_total=false`, carries fetch time, confidence and
provider route link, and is matched to a generated date scenario. If the endpoint omits original
search timestamps, `age_hours` and expiry remain `unknown`; the source observation is the API
fetch time and confidence is reduced. An absent `actual` field is not treated as `false`.

The API token is sent in `X-Access-Token`, never logged or stored in snapshots. Explicitly expired,
malformed, zero, negative or date-mismatched observations are discarded. For month discovery,
request at most five evenly distributed representative scenarios. If the traveller has supplied a
month but not a trip length, use a visibly disclosed seven-night planning default. The card presents
the minimum and maximum of returned cached observations, never a generated estimate.

## Consequences

- Cached prices cannot become a confirmed flight component, full-trip total or a strict-budget pass.
- A card may show one cached flight observation only with the Russian disclosure «цена найдена ранее
  и проверяется при переходе» and with the missing accommodation component visible.
- An empty API response means that the cache has no suitable observation, not that the flight provider
  is disconnected. The card must show this distinction and must not fabricate a price.
- No public pricing endpoint is enabled by this slice.
- Live flight pricing with exact passenger composition remains required before cards show totals.
