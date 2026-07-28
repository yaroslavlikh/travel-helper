# ADR-0018: Deterministic pricing core without AI

- Status: accepted
- Date: 2026-07-28

## Context

The removed prototype pricing layer extrapolated totals from destination fixtures. Production
pricing instead needs exact trip scenarios, typed source observations and reproducible arithmetic.
Flight, stay and local-cost providers are not selected or configured yet.

## Decision

Create `app/pricing` as an AI-free bounded context. It accepts only a validated, structured
`PricingRequest`; generates deterministic date scenarios; aggregates complete scenario component
ranges; and creates immutable, versioned snapshots.

The package may use Pydantic, the Python standard library, `Decimal` arithmetic and typed provider
ports. It must not import LLM, agent, embedding or model SDKs. An AST test enforces this boundary.

No provider is implied by this core. Missing flight or stay evidence produces no total. External
providers, persistence and public API endpoints require later ADRs and mocked contract tests.

## Invariants

- Components from different date scenarios are never combined.
- Missing evidence is never converted to zero.
- Every money range satisfies `floor <= expected <= safe`.
- Exact dates produce one scenario; flexible windows are sampled deterministically.
- Snapshot IDs and request hashes depend only on canonical input, config and normalized results.
- The calculation clock is explicit input, so tests and replay remain reproducible.

## Consequences

- The first slice is not wired into destination cards and returns no fabricated user price.
- Pricing can evolve provider by provider without importing LangGraph or the LLM gateway.
- The next implementation slice is official FX normalization with `Decimal` and source freshness.
