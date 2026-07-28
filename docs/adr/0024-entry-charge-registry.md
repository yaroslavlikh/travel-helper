# ADR-0024: Reviewed manual registry for mandatory entry charges

- Status: accepted
- Date: 2026-07-28

## Context

Visa, ETA and tourist charges have no universal reliable free API. Treating missing citizenship or
missing rules as zero creates dangerous underestimates.

## Decision

Mandatory charges come from a versioned registry linked to an official source. Registry coverage is
explicitly `confirmed`, `stale`, `needs_review` or `unknown`. Only a confirmed empty registry means
zero. Unknown coverage or missing citizenship produces a missing component.

Rules support per-person, per-trip, per-night and percent-of-stay bases, age applicability and
currency conversion through the existing CBR table. Optional rules do not enter mandatory totals.
Stale or changed-source entries keep the previous amount visibly marked `stale` until manual review;
an LLM never edits or approves a tariff.

Downloading source pages, calculating content hashes and the review UI are separate operational
slices.
