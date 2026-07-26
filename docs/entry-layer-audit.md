# Country-entry layer audit

Status: completed audit for ADR-0016. Date: 2026-07-26.

## Current request-to-card pipeline

```text
chat query
→ `extract_travel_request_with_model` / demo parser
→ `TravelRequest.visa_willingness`
→ `rank_demo_candidates`
→ `score_candidate` / `evaluate_hard_checks`
→ LangGraph checkpoint `recommendations`
→ API response and browser local chat state
→ card or destination subchat
```

In demo mode `app/api/routes.py` calls `rank_demo_candidates()` and stores the serialized cards in
the current LangGraph state. `POST /destination-chat` reads the matching stored card through
`_find_current_recommendation()`. This avoids reranking during a subchat, but it is not an
immutable historical recommendation store: a later refinement overwrites `recommendations` in the
same parent checkpoint.

## Legacy entry reads

| Path | Symbol | Current role | Required action |
|---|---|---|---|
| `app/data/destinations.fixture.json` | `visa`, `entry` | synthetic per-destination values | keep only temporary demo compatibility; never backfill as policy |
| `app/services/fixtures.py` | `load_demo_candidates` | maps fixture values into candidate | dual-read adapter, then remove legacy mapping |
| `app/domain/models.py` | `DestinationCandidate.visa_complexity`, `entry_requirements` | card/ranking/subchat fields | deprecate after `EntryAssessment` is available |
| `app/services/filtering.py` | visa hard check | decides `PASS`/`FAIL`/`UNKNOWN` from legacy field | replace with entry constraint evaluator |
| `app/services/scoring.py` | `_entry_fit`, blocking unknown | score and state depend on legacy field | consume assessment features only |
| `app/services/destination_chat.py` | visa fallback reply | repeats fixture visa claim | consume stored assessment and safe copy |
| `app/static/app.js` | entry card metric | displays `entry_requirements` | render assessment copy, source and freshness |
| `tests/unit/test_scoring.py` | legacy visa cases | documents old enum semantics | migrate to assessment table tests |
| `docs/adr/0015-ranking-v1.md` | visa policy | specifies old fixture enum | supersede entry portion through ADR-0016 |

## Current geography

The demo recommendation catalog has 26 destinations in `app/data/destinations.fixture.json`.
Each record has a localized `country` string. `app/services/destination_semantics.py` uses those
strings for controlled region membership, explicit-country avoidance, and ranking diversity.
There is no country ID, country alias resolver, nor explicit selected-country constraint.

The separate POI catalog has a PostgreSQL `destinations` table in
`migrations/places/001_initial_schema.sql`. It contains a UUID, slug, name and optional
`country_code`, but no `parent_id` or `entity_type`. `app/places/catalog.py` is a static Python map
for 26 bounded POI import scopes; it is not a canonical geography repository. The table can be
extended for hierarchy only after an explicit migration and compatibility audit.

## Provenance and snapshots

`SourceEvidence` is already a reusable API/domain contract. The POI catalog also has reusable
`sources`, `place_source_records` and immutable source snapshots. Entry policies may reuse the
generic `sources` table but require separate policy records and source linkage: POI provenance
cannot become entry-policy provenance by implication.

Cards currently carry a deterministic pricing snapshot identifier and are serialized into the
LangGraph checkpoint. There is no database table for recommendation snapshots and no stable
assessment payload. The entry rollout therefore needs a versioned assessment embedded in each
stored card before policy display or subchat claims are enabled.

## Migration risks

- `destinations` is used by POI import/retrieval and must not acquire an ambiguous country/city
  meaning without a staged migration.
- SQLite is the local graph/account store while the POI catalog is PostgreSQL; entry data must have
  an explicit production store decision rather than silently coupling to either.
- Existing local chat checkpoints contain `visa_complexity`; model changes need backward-compatible
  parsing during the rollout.
- Browser state stores raw API cards, so additive API fields are safe; removing legacy fields is a
  later compatibility change.
- Demo mode currently has no live evidence. The first safety release must not change an unavailable
  rule into a claim that a country is eligible.

## Recommended integration points

1. Add country selection to `TravelRequest` as resolved country codes/IDs, never display strings.
2. Resolve one `EntryAssessment` per unique country before deterministic filtering/scoring.
3. Attach the assessment to `DestinationCandidate`; persist it with each recommendation card.
4. Replace legacy visa filtering, entry score and subchat fallback in one ranking integration
   change, protected by a feature flag.
5. Render only user-safe assessment copy in the browser; source, checked time and confidence remain
   structured API fields.

## Files expected to change

`app/domain/models.py`, `app/services/extraction.py`, `app/services/destination_semantics.py`,
`app/services/filtering.py`, `app/services/scoring.py`, `app/services/fixtures.py`,
`app/api/routes.py`, `app/services/destination_chat.py`, `app/static/app.js`, entry migrations,
new `app/entry/` and geography repositories, affected unit/integration tests, ranking/product docs
and ADRs.
