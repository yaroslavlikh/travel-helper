# ADR-0015: Deterministic shortlist ranking v1

- Status: accepted
- Date: 2026-07-22

## Context

The demo scorer currently renormalizes away missing dimensions and treats the lower end of a cost
range as enough proof for a strict budget. Both behaviours can promote a poorly evidenced option.

## Decision

Ranking version `ranking-v1` is deterministic. LLMs may extract request fields or phrase an already
bounded explanation, but never assign a score or alter ordering. Every candidate has one state:
`ELIGIBLE`, `CONDITIONAL`, `EXCLUDED`, or `FALLBACK`.

V1 uses the existing normalized candidate contract. Its six dimensions are budget, experience,
logistics, weather, entry and practical fit. Missing evidence keeps its predeclared weight, is
shrunk to a conservative dimension prior, and adds a separate uncertainty penalty. A strict budget
passes only when the upper (`safe`) total is within budget. Country/scope/exclusion contradictions
remain non-negotiable hard failures.

Candidates are sorted deterministically, then a bounded diversity pass can only reorder comparable
eligible/conditional candidates. Affiliate links never enter either calculation. The returned object
records version, states, dimension breakdown, caps and rank before/after diversity.

## Consequences

- Existing fixture estimates are explicitly modelled evidence, not a live fare guarantee.
- No new provider client or ML/ranking dependency is introduced.
- Child/room/route-date and live entry snapshots require their typed provider contracts before they
  can be represented as hard checks; they are not silently inferred from the current demo schema.
