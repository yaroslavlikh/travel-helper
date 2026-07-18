# ADR-0011: Graceful uncertainty in the planning dialogue

- Status: accepted
- Date: 2026-07-18

## Context

The original clarification flow treated origin, timing, travellers, budget and destination
scope as equally blocking P0 fields. A short natural-language request therefore often became a
form: the user had to answer several questions before seeing any useful travel options.

That policy is too strict for the product's job: helping a person choose a destination before
they have planned every detail. Timing, party size and budget materially change the ranking, but
their absence should make the result conditional rather than unavailable.

## Decision

Only the origin city is a blocking ambiguity for the current flight-aware shortlist. Every other
missing planning field is represented as a typed, non-blocking uncertainty with an impact level.

The workflow always returns a shortlist after the origin is known. It also returns:

- explicit assumptions and uncertainties, without inventing a missing value;
- a deterministic planning-confidence band derived from the unresolved fields;
- at most one `next_best_question`, selected by the largest expected effect on ranking or hard
  filters.

The next question is advisory, not a LangGraph interrupt. The user may ignore it, answer it in
free text, or refine a different criterion. The UI states that the current shortlist remains
usable and that the question can be answered later.

Unknown values are never sent to external links as confirmed facts. Scoring continues to omit an
unavailable component and renormalize the remaining published weights; the confidence band makes
that reduced coverage visible.

## Consequences

- Most requests reach a shortlist in zero or one clarification turns.
- A response distinguishes a fact, an explicit assumption and an unresolved condition.
- The conversation no longer repeats an optional question merely because it was not answered.
- The confidence band describes planning coverage, not source freshness or a prediction that a
  recommendation will be liked. Source confidence remains a separate evidence property.
- If future search needs another truly mandatory field, its blocking policy must be added here
  and tested instead of silently promoting an optional field to P0.

## Rejected alternatives

- Asking every high-impact field before ranking: produces a questionnaire instead of a dialogue.
- Filling empty fields with hidden defaults: makes estimates look more precise than the request
  supports.
- Letting an LLM decide which uncertainty blocks the flow: makes the control path and evaluation
  non-deterministic.
