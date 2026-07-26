# Country-entry layer implementation plan

Status: approved sequence proposed by ADR-0016. Date: 2026-07-26.

This plan implements the production contract from
`tudavai_country_entry_production_plan.md` without presenting fixture values as entry facts.
Each numbered item is a separately reviewable Conventional Commit or PR.

## 1. Safety patch

Goal: stop fixture `visa` from deciding or claiming real entry conditions.

- Introduce an unavailable `EntryAssessment` compatibility adapter.
- Disable legacy visa hard filtering and entry-score contribution behind an explicit flag.
- Keep cards in an unrestricted shortlist as conditional, with the copy “Условия въезда пока не
  проверены”; never silently replace a selected country.
- Stop destination-chat fallback from describing legacy `none`/`evisa`/`visa` as facts.
- Add `ENTRY_DATA_UNAVAILABLE` observability and regression tests.

Acceptance: a `visa-free only` request cannot call a fixture direction confirmed visa-free; unknown
entry data remains visible and explained. No network provider or database migration in this change.

## 2. Canonical geography

Goal: make country identity an explicit, resolvable domain concept.

- Write a migration extending the existing geography store only after validating the POI repository
  queries; add 13 country entities and map all 26 destinations to exactly one country ancestor.
- Add ISO alpha-2 code, country aliases and a `CountryRepository` port.
- Extend candidates with `country_id` and `country_code`; preserve the localized `country` only as a
  temporary display fallback.
- Extract explicit country requests such as “в Малайзию или Таиланд” into a resolved allowed-country
  set. Apply that set as a deterministic hard filter; explicit exclusions win.

Acceptance: no join, filter, cache key or diversity cap uses the display country name.

## 3. Entry domain contracts

Goal: separate normative policy from trip-specific outcome.

- Add enums and Pydantic contracts for `EntryPolicy`, `EntryAssessment`, application channels,
  outcome, confidence and stable warning codes.
- Add `TravelerEntryContext` to `TravelRequest`: citizenship, exact/approximate dates, ordinary
  passport, tourism and air entry. Do not collect passport numbers or scans.
- Define `VisaPreference` independently from policy requirement.

Acceptance: all contracts serialize stably; unavailable assessment needs no policy and cannot be
eligible.

## 4. Persistence and resolver

Goal: support evidenced, historical country policies without provider coupling.

- Add migrations for policies, channels and separate entry-policy source records; reuse generic
  `sources` only by foreign key.
- Implement repository and deterministic resolver selection, validity boundaries, collision rules,
  stay limit checks, freshness and request-scoped batch cache.
- Add a validation command for country mappings, policy validity, evidence and conflicting verified
  records.

Acceptance: Phuket/Samui/Krabi receive one Thai assessment in a request; missing date/citizenship,
stale data and conflicts return safe `UNKNOWN` rather than a guessed rule.

## 5. Ranking and immutable recommendation assessment

Goal: make policy outcome auditable and reproducible in the shortlist.

- Add `EntryConstraintEvaluator`; map `VisaPreference` and `EntryAssessment` to the existing
  four-state hard-check contract.
- Keep entry friction separate from evidence uncertainty in ranking configuration.
- Persist the assessment payload/ID inside the recommendation snapshot before returning the card.
- Ensure a later policy update cannot rewrite the snapshot used by a card or subchat.

Acceptance: `visa_free_only` passes only verified visa-free entry; unconfirmed country data is
conditional/explained, not silently excluded. No provider call happens in the ranking loop.

## 6. API, card and subchat

Goal: show one truthful assessment consistently everywhere.

- Return additive `entry_assessment` fields in the recommendation API.
- Render verified, action-required, stale, conflicting and unavailable states with distinct Russian
  copy, checked time and source link where present.
- Pass the exact stored assessment to destination subchat and prohibit unsupported upgrades by the
  model.

Acceptance: the card and subchat use the same assessment snapshot, including the unavailable case.

## 7. Provider and cleanup

Goal: add verified data only after selecting a licensed source.

- Define a provider-neutral adapter, raw payload persistence/hash, normalization and activation
  lifecycle. Provider failure retains the last verified version and reports degradation.
- Run shadow mode, then enable card display, soft ranking and finally hard filters as data coverage
  proves safe.
- Remove legacy fixture visa fields only after telemetry confirms no production reads and local
  checkpoint compatibility has expired.

Acceptance: no synthetic policy enters the verified table; rollback turns the layer off to safe
unavailable assessments, never back to fixture claims.

## Validation gates for every implementation stage

- Table-driven unit tests for policy/assessment semantics and country filtering.
- Mocked integration tests for repository, snapshot and subchat consistency.
- Migration tests against a fresh and upgraded PostgreSQL schema once persistence is introduced.
- `make check`, `node --check app/static/app.js` when UI changes, and `git diff --check` before
  every commit.
