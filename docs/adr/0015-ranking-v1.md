# ADR-0015: Deterministic shortlist ranking v1

- Status: accepted
- Date: 2026-07-22

## Context

The demo scorer must not turn missing travel evidence into a silent match. In particular, a lower
price estimate is not proof that a strict budget is met, and an unknown visa regime is not proof
of visa-free entry.

## Decision

`ranking-v1` is deterministic. LLMs may extract request fields or phrase an already bounded
response, but never assign a score or alter ordering. It has six fixed dimensions: budget,
experience, logistics, weather, entry and practical fit. Weights, priors, uncertainty multiplier
and cap thresholds are versioned in `app/data/scoring.json`.

Every requested hard constraint is evaluated as `PASS`, `FAIL`, `UNKNOWN` or `NOT_APPLICABLE`.
No user constraint means no check. Missing evidence for a requested constraint is `UNKNOWN`.
Known contradictions are `FAIL`. Unknown temperature or flight duration produces a `CONDITIONAL`
card; unknown strict budget and visa evidence do not establish mandatory requirements and exclude
the card. Visa policy is explicit: `no_visa` accepts only `none`, `evisa_ok` accepts `none/evisa`,
`visa_ok` accepts any known mode, and `any` is not applicable.

Strict-budget fallback is the sole relaxation. It is allowed only when strict budget has failed and
every other applicable check is `PASS` or `NOT_APPLICABLE`; existing warnings remain intact and a
human budget warning is appended. Region matching is a controlled alias-to-country-set mapping,
not arbitrary country substring matching.

Candidates sort by deterministic state/score/confidence/id. Diversity operates only in a bounded
score window and records rank before/after; it uses a documented similarity penalty and country
cap. Affiliate links never affect filtering, score, or diversity.

## Consequences

- The ranking result makes evidence gaps visible instead of claiming confirmed fit.
- `preliminary_score` and the always-zero `risk_penalty` are removed: `final_score` is the sole
  ranking score; risks are qualitative evidence warnings.
- Existing fixture estimates remain modelled evidence rather than live fare, weather or entry data.
- New providers or unsupported geography require a typed contract and an ADR update before they
  become ranking evidence.
