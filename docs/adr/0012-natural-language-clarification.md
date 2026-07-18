# ADR-0012: Natural-language clarification instead of field forms

- Status: accepted
- Date: 2026-07-18

## Context

Travel constraints are not naturally expressed as one value per form control. A traveller may
write "20 августа — 3 сентября", describe a flexible departure window, answer several questions
in one sentence, or refine a previously stated condition in their own wording. Field cards force
that conversation into a lossy UI taxonomy and can submit raw display strings as API values.

## Decision

The UI renders clarification only as assistant chat messages. It never renders a select, radio
button, numeric field or confirmation card for trip constraints. The planner keeps a typed internal
taxonomy to choose its next question:

- `departure`: origin city and country;
- `timing`: month, exact trip interval, flexible departure window and duration;
- `geography`: domestic/international scope;
- `party`: adults and children;
- `budget`: total budget and strictness;
- `travel_friction`: visa, flight duration, transfers and baggage;
- `trip_style`: preferences and pace.

The planner asks only one highest-impact question in natural language. A reply is always treated as
a request patch rather than an answer to a single field: extraction may update every explicitly
stated constraint. The deterministic fallback also recognizes exact cross-month intervals.

Structured `answers` remains an API compatibility path, but each field is independently validated
before merge. Invalid legacy values are ignored rather than causing a 500 response.

## Consequences

- A traveller can answer with dates, a range, a correction and extra preferences in one message.
- The visible conversation does not expose storage-field names or force a month-only choice.
- The API still returns typed questions for observability and non-web clients, but the web UI does
  not render them as controls.
- Response parsing failures are surfaced as a generic temporary-service message, never as a JSON
  parser error to the traveller.
