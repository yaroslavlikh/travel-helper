# ADR-0026: Pricing provider registry and no-token readiness

- Status: accepted
- Date: 2026-07-29

## Context

`app/pricing` already normalizes complete flight and stay observations, but the application has no
runtime registry for provider selection and no machine-readable status for the missing credentials
case. The card correctly displays no total; operations and a future staging deployment still cannot
distinguish a deliberately disabled provider from absent credentials or an unimplemented live adapter.

## Decision

- Extend the existing flight/stay ports into provider-neutral protocols. Keep `LiveFlightProvider`
  and `LiveStayProvider` as compatibility aliases during the migration.
- Add only four minimal adapters: fixture and unavailable for flight and stay. Fixture data is
  accepted only when it is a full typed offer for the exact scenario; unavailable returns no offers
  and carries its reason through the registry status, never as a zero price.
- Add a small `PricingProviderRegistry` to application resources. Before a selected live adapter
  exists it creates unavailable/empty adapters and reports `missing_credentials`, `disabled` or
  `not_implemented`; it does not call external APIs at startup.
- Expose `/health/live`, `/health/ready` and a non-production `/internal/provider-status` endpoint.
  Readiness is `degraded` while required flight or stay pricing is unavailable. The endpoints expose
  mode and safe reason only, never credentials, provider URLs or payloads.
- Add settings for provider mode and feature flags. Public production pricing remains disabled by
  default; fixture mode is not valid for public production.

## Consequences

- A deployment can be verified by a provider before it has live credentials.
- A future Amadeus/Booking adapter is added behind the existing registry without changing price
  aggregation or card semantics.
- This decision does not wire pricing into recommendation ranking. That remains a later vertical
  slice once a canonical recommendation snapshot is persisted.
