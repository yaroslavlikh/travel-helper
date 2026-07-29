# Аудит текущей recommendation-системы

Статус: baseline для production master-plan. Дата: 2026-07-29.

## Вывод

В репозитории есть два не соединённых до конца контура.

1. Основной пользовательский путь — `POST /recommend` → demo catalog →
   `ranking-v1` → карточки в LangGraph checkpoint. Он работает, но использует локальные
   fixture-диапазоны как ranking evidence.
2. `app/pricing` — отдельный deterministic pricing core с typed scenarios, live/cached
   observations, source refs и immutable `TripPriceEstimate`. Он покрыт unit-тестами, но
   не вызывается из основного recommendation pipeline.

Следующее изменение не должно создавать ещё один pricing или ranking engine. Минимальный путь:
адаптировать текущий `TravelRequest` к `PricingRequest`, вызывать существующий core через
provider registry и передавать получившийся snapshot в текущую карточку, ranking и subchat.

## Текущий поток

```text
POST /recommend
  → app/api/routes.py:_invoke_planner_turn
  → app/services/workflow.py: LangGraph extract + ambiguity loop
  → app/api/routes.py:_build_recommendation_response
  → app/services/fixtures.py:load_demo_candidates
  → app/services/scoring.py:rank_demo_candidates
  → app/services/aviasales.py:add_aviasales_links
  → app/services/pricing_presentation.py:unavailable_pricing
  → serialized `recommendations` in LangGraph checkpoint
  → API response / app/static/app.js
  → POST /destination-chat reads the stored card, without reranking
```

В `APP_ENV=production` с `DEMO_MODE=false` workflow заканчивается `partial`: search-based
candidate generation пока не реализована. Это корректно не маскирует demo как production,
но означает, что staging сначала должен поддерживать явно маркированный demo path.

## Карта контрактов и legacy-полей

| Symbol / field | Path | Current role and consumers | Source of truth | Problem | Action |
| --- | --- | --- | --- | --- | --- |
| `TravelRequest`, `TravelRequestPatch`, `TravelRequestRevision` | `app/domain/models.py`; создаются в `app/services/extraction.py` | LangGraph state, ambiguity, ranking, API | Да для chat intent | Не содержит canonical `request_id`, date mode, airport group, child ages и typed entry context из master-plan | Adapt in place; сохранить backward-compatible fields на период миграции |
| `PlannerState.parsed_request` | `app/domain/models.py`, `app/services/workflow.py` | SQLite/in-memory LangGraph checkpoint, `/recommend` | Да для текущего chat turn | Нет schema version и immutable recommendation snapshot; future refinement перезаписывает `recommendations` | Keep; добавить versioned snapshot reference/payload |
| `DestinationCandidate` | `app/domain/models.py`; создаётся в `app/services/fixtures.py` | ranking, card, subchat, Aviasales links | Нет: demo aggregation | Смешивает identity, fixture facts, legacy price fields, entry display и card content | Adapt; добавить canonical country/scenario/assessment/pricing refs, затем deprecate legacy fields |
| `TripScenarioCandidate` | отсутствует; ближайший аналог `app/pricing/models.py:DateScenario` | pricing-only | Нет | Нет связи scenario с destination/group/request в recommendation layer | Introduce as canonical adapter around existing `PricingRequest` + `DateScenario`, не дублировать scenario generator |
| `PricingRequest` / `DateScenario` | `app/pricing/models.py`, `app/pricing/scenario_generation.py` | deterministic pricing core and tests | Да внутри pricing boundary | Не строится из `TravelRequest` в runtime | Reuse; создать narrow request/scenario mapper |
| `MoneyRange`, `CostComponent`, `TripPriceEstimate` | `app/pricing/models.py`, `app/pricing/snapshot.py` | pricing aggregation, presentation tests | Да внутри pricing boundary | Snapshot in-memory only; no provider registry/runtime invocation | Reuse as canonical price contract; persist it with recommendation snapshot |
| `PricingCardView` | `app/domain/models.py`, `app/services/pricing_presentation.py` | API and frontend card, subchat context | Presentation projection | Runtime always receives `snapshot=None`, so only unavailable state is shown | Keep; populate only from `TripPriceEstimate` |
| `estimated_*_cost_rub_*`, `total_min`, `total_max` | `app/domain/models.py`, `app/services/fixtures.py`, `app/data/destinations.fixture.json` | `filtering.py`, `scoring.py`, destination-chat model context | No: synthetic fixture | Current strict budget and budget score read legacy totals directly; fixture loader derives component shares from synthetic total | Deprecate as demo-only ranking adapter; canonical ranking must read `TripPriceEstimate` |
| `EntryPolicy` | отсутствует | — | — | No country/date/citizenship policy store | Introduce in dedicated `app/entry` bounded context after canonical geography decision |
| `EntryAssessment` | `app/domain/models.py` | filtering, score, card metric, subchat | Compatibility adapter only | Missing assessment ID, policy version, source refs and traveller context; fixture always `unknown/unavailable` | Adapt to canonical assessment, keep safe unknown compatibility |
| `visa`, `entry`, `visa_complexity`, `entry_requirements` | fixture JSON; `DestinationCandidate` | legacy display compatibility only; filtering reads `entry_assessment`, not fixture `visa` | No | Legacy fixture fields remain in source JSON; no verified country policy exists | Do not backfill. Remove only after snapshot/entry migration and checkpoint window |
| `ScoredDestination` | `app/domain/models.py`, `app/services/scoring.py` | ranking result, cards, checkpoint, subchat | Current card payload | Contains both `total_score` and `final_score` with same semantics, generated `recommendation_snapshot_id`, and legacy candidate | Adapt to reference canonical scenario/price/entry; audit/deprecate duplicate score field in ranking task |
| `ranking_version` | `ScoredDestination`; `app/data/scoring.json` | ranking response, place events separately | Yes for current ranking config | Recommendation-level version is not persisted independently from mutable checkpoint | Carry into immutable recommendation snapshot |
| `SourceEvidence` / pricing `SourceRef` | `app/domain/models.py`; `app/pricing/models.py` | card candidate source vs pricing components | Split, incompatible contracts | No shared provenance/freshness registry; `SourceEvidence` lacks `valid_until`/trust tier, pricing source lacks excerpt | Define canonical shared source adapter; migrate consumers incrementally |
| `DestinationKnowledgeSnapshot` | absent; closest `app/places/context.py:DestinationContext` | destination subchat / POI retrieval | POI repository for published places | Knowledge context is query-time and not attached to a recommendation snapshot | Keep bounded POI context; add immutable source references to recommendation later |
| `RecommendationSnapshot` | absent; `ScoredDestination.recommendation_snapshot_id` and checkpoint list are placeholders | cards and `POST /destination-chat` | No | ID is deterministic per destination (`rec-{destination_id}`), not unique per run; refinement overwrites cards in parent checkpoint | Introduce persistent versioned snapshot and use it as sole card/subchat context |
| `fallback` | `app/services/scoring.py:rank_demo_candidates` | strict-budget fallback, frontend state | Yes for ranking-v1 | Correctly limited to strict budget, but still based on legacy price fields | Preserve behavior while switching input to canonical price estimate |
| destination subchat | `app/api/routes.py:destination_chat`, `app/services/destination_chat.py` | reads current serialized recommendation and saves bounded history in `PlannerState.destination_threads` | Current checkpoint | Does not rerank, but has no durable immutable snapshot and context sends legacy totals to LLM | Keep lookup behavior; switch context to persisted snapshot fields only |

## Concrete answers required by master-plan

1. `TravelRequest` is created by `extract_travel_request`, `extract_travel_request_with_model`,
   and refinement merge helpers in `app/services/extraction.py`; workflow stores it as
   `PlannerState.parsed_request`.
2. Gemini parses free text in `app/services/extraction.py:extract_travel_request_with_model`;
   `app/services/model_gateway.py` owns the single lifespan client. The regex parser is a
   demo-only fallback.
3. Demo candidates are generated by `app/services/fixtures.py:load_demo_candidates` from
   `app/data/destinations.fixture.json`. Production candidate generation does not exist yet.
4. Pricing scenarios are generated by `app/pricing/scenario_generation.py:generate_scenarios`.
   There is no runtime `TripScenarioCandidate` for recommendations yet.
5. User-visible price is currently unavailable by design: `routes.py` passes `None` to
   `pricing_card`. The legacy totals from the fixture are still used only by ranking.
6. Budget hard check is `app/services/filtering.py:evaluate_hard_checks`; budget soft score is
   `app/services/scoring.py:_budget_fit`. Both currently use legacy candidate totals.
7. Ranking runs in `app/services/scoring.py:rank_demo_candidates` / `score_candidate` with
   config in `app/data/scoring.json`.
8. Card response is `CompletedRecommendationResponse.recommendations` in
   `app/api/schemas.py`, composed by `_build_recommendation_response` in `app/api/routes.py`;
   rendering is in `app/static/app.js`.
9. Frontend formats `PricingCardView` only. It does not calculate price, but older card fields
   still render legacy flight/weather/entry descriptors.
10. Destination subchat is `POST /destination-chat` and `answer_destination_question`.
11. Subchat history is in `PlannerState.destination_threads`, inside the LangGraph checkpoint.
12. No immutable/persistent recommendation snapshot exists. The current checkpoint card list is
   only a mutable current-feed snapshot.
13. Main duplicate/legacy values: all `estimated_*_cost_*` fields, fixture `total_min/max`,
   fixture `visa/entry`, duplicate score fields, and separate provenance contracts.
14. End-to-end-ish coverage: `tests/integration/test_health.py` exercises clarify → recommend →
   refine → destination chat; `tests/integration/test_accounts_api.py` covers ownership and chat
   import; pricing has unit/contract-style tests only. There is no fixture request → pricing →
   ranking → persisted snapshot → subchat integration test.
15. Existing flags/configuration: `DEMO_MODE`, `APP_ENV`, LLM/Langfuse config, places DB config,
   and `AVIASALES_MARKER`. There are no pricing provider mode flags.
16. Deployment entrypoint: `Dockerfile` runs `uvicorn app.main:app` on port 8000. `docker-compose.yml`
   starts only the places PostGIS/pgvector database. CI runs `make check`; no staging host,
   web-service database, migration command, or health/readiness split exists.

## Existing assets to reuse

- `app/pricing`: validated requests, deterministic scenario generation, source-aware component
  normalizers, aggregation and snapshot hash. It has no LLM imports; `tests/unit/test_pricing_boundary.py`
  guards this boundary.
- `app/pricing/ports/flights.py` and `app/pricing/ports/stays.py`: starting provider ports.
  `CachedFlightDiscovery` / `app/pricing/providers/aviasales_data.py` is explicitly cached,
  `usable_for_total=false` and cannot become a live price by configuration alone.
- `app/pricing/providers/cbr_fx.py`: source-aware official FX adapter with bounded stale fallback.
- `PricingCardView` and `pricing_presentation.py`: complete safe presentation boundary.
- `EntryAssessment` safety work and ADR-0016: unknown entry data already does not pass a no-visa
  hard constraint.
- POI PostgreSQL schema and repository: useful conventions for published data, sources,
  snapshots and event ingestion; entry policies must remain a separate domain.
- LangGraph checkpoint and current `_find_current_recommendation`: card/subchat consistency is
  already enforced within a single current feed.

## Gaps and migration order

| Priority | Gap | Minimal migration |
| --- | --- | --- |
| P0 | No canonical bridge from chat request to pricing request | Add mapper and scenario owner fields; use existing pricing core |
| P0 | No runtime provider registry/unavailable typed result/readiness | Add registry using existing ports, unavailable providers and explicit settings; do not add a second engine |
| P0 | Ranking reads fixture totals | Add a price-to-ranking adapter; retain legacy fields only behind explicit demo compatibility path |
| P0 | Recommendation snapshots are mutable checkpoints | Persist versioned snapshot payloads before cards/subchat consume canonical price or entry data |
| P0 | Country entry has no canonical policy/geography store | Follow existing ADR-0016 and `docs/entry-layer-implementation-plan.md`; begin with safe unknown data |
| P1 | Provenance models are split | Introduce a narrow shared source contract before dynamic facts are persisted across domains |
| P1 | Readiness/deployment contract incomplete | Add `/health/live`, `/health/ready`, provider status, then staging service + web DB; do not request live provider credentials before that |
| P1 | Istanbul subchat is not benchmarked as a full snapshot vertical slice | Add evaluation set after snapshot context is stable |

## Safety constraints discovered

- Do not pass fixture `total_min/max` to a live price presentation or convert them into component
  percentages. `load_demo_candidates` currently performs exactly that only inside the demo ranking
  candidate; the canonical pricing path must not reuse it.
- Do not treat `FlightPriceSignal` from Aviasales Data API as live or full-party evidence.
- Do not expose a public numeric total until flight and stay are complete for the same scenario.
- Do not make entry rules a per-city or per-ranking-loop network call.
- Do not store provider payloads, credentials, passport data or raw user text in product events.
- Do not use the existing POI `destinations` table as a country hierarchy until a migration proves
  its current repository queries remain valid.

## Audit checks run

- `git status`, branches, decorated graph and legacy symbol search completed on 2026-07-29.
- Detailed pricing, ranking, country-entry and places architecture specifications were loaded from
  the supplied files before this audit.
- No worktree changes existed before creating this document.
