# Аудит текущего global knowledge / POI / subchat контура

Статус: baseline перед canonical geography и support matrix. Дата: 2026-07-30.

Этот документ фиксирует фактический кодовый контур перед выполнением приложенного
`CODEX_TUDAVAI_GLOBAL_CATALOG_AND_RAG_PLAN.md`.
Он не утверждает, что данные, не присутствующие в репозитории или не прошедшие eval, уже
загружены в локальный PostgreSQL.

## Краткий вывод

В проекте уже есть полезный, но узкий фундамент: отдельный PostgreSQL/PostGIS/pgvector-каталог
мест, bounded OSM importer, provenance для POI и лицензированных описаний, lexical retrieval и
bounded destination subchat. Создавать второй RAG или второй каталог не нужно.

При этом production knowledge platform пока не существует:

- product fixture содержит 13 стран и 26 направлений;
- реальные POI retrieval и evaluation зафиксированы только для Стамбула;
- у остальных 25 направлений есть статический planning brief, но не опубликованный и
  проверенный POI pack;
- `hash-v1` хранится в pgvector для совместимости схемы, но не является semantic retrieval;
- нет canonical geography, aliases, jurisdiction model, domain support, source documents,
  generic facts, conflict model и answerability;
- `POST /destination-chat` передаёт модели fixture-card, planning brief и, если база
  сконфигурирована, до пяти POI. Это не immutable knowledge snapshot и не grounded RAG.

Следующий шаг — расширить **текущий** places PostgreSQL контракт canonical geography и
support/evidence слоем. До миграционных тестов не импортировать Wave 1, не включать его в ranking
и не обещать новый coverage пользователю.

## Фактическое покрытие

| Слой | Что есть | Что доказано | Ограничение |
| --- | --- | --- | --- |
| Candidate fixture | `app/data/destinations.fixture.json`: 13 стран, 26 направлений | Unit/integration путь demo ranking | synthetic price/entry поля, не canonical knowledge |
| Bounded destination catalog | `app/places/catalog.py`: 26 bbox и ISO country code | Каждому fixture-направлению можно задать OSM scope | Это Python configuration, не identity store и не признак наполненного каталога |
| Planning briefs | `app/data/destination-guides.json`: 26 guide entries | Каждый `destination_context()` можно собрать; unit test это проверяет | Один URL на guide, нет source document/evidence span; это не live факт и не POI database |
| Canonical POI | `destinations` → `places` в places PostgreSQL | Istanbul importer, optional PostgreSQL contract и 40-case eval | Нет checked-in raw snapshot, import manifest или per-destination eval для остальных городов |
| POI descriptions | `place_description_documents/chunks` из reviewed manifest | Валидация licence, chunking и bounded prompt tests | `DescriptionManifest.destination` жёстко ограничен `istanbul`; manifest data не включены в repo |
| Semantic/vector search | `place_embeddings`, `place_description_chunks` | Schema compatibility и deterministic vector unit test | Online repository выставляет semantic scores `0.0`; `hash-v1` не участвует в ранжировании |
| Live data | warnings в `DestinationContext` | Unknown показывается вместо выдуманных цен/entry | Нет provider/repository для current entry, weather, hours, transport или events |

В текущем локальном окружении `PLACES_DATABASE_URL` не установлен по умолчанию. В этом режиме
`DisabledPlacesRepository` возвращает `503` на `/places/search`, а destination subchat корректно
отвечает только карточкой и planning brief.

## Текущая модель данных и migration runner

`scripts/migrate_places.py` применяет упорядоченные SQL-файлы из `migrations/places/` и ведёт
`schema_migrations`. В локальном development отдельная `places-db` поднимается через
`docker-compose`; LangGraph/account SQLite не является хранилищем каталога.

```text
static fixture / destination guide                  reviewed description manifest
             │                                                 │
             │                                        `import_place_descriptions.py`
             │                                                 ▼
OSM / Overpass → `import_all_places.py` → destinations → places ← place_source_records
                                                   │        │              │
                                                   │        ├─ names/tags/features/images
                                                   │        ├─ embeddings (hash-v1)
                                                   │        └─ description documents/chunks
                                                   │
                                       `PostgresPlacesRepository.search`
                                                   │
                              `/places/search` and `POST /destination-chat`
```

### Existing tables

| Table/group | Current meaning | Provenance/freshness state |
| --- | --- | --- |
| `destinations` | Flat POI-search scope: slug, display name, optional country code, point center | No parent, entity type, aliases, jurisdiction or canonical identity link |
| `places`, `place_names`, `categories`, `tags`, `place_tags`, `place_features`, `place_images` | Canonical tourist POI and presentation/search metadata | `place_features` are deterministic source-derived signals; not a statement of current opening, price or popularity |
| `sources`, `place_source_records`, `place_source_snapshots`, `import_runs` | POI source identity and immutable OSM payload history | Strong enough for first POI import, but `sources` has no domain/tier/terms/polling/permissions registry |
| `source_usage_policies`, `place_description_documents`, `place_description_chunks` | Explicitly licensed text retention, cited snippets and chunk vectors | Correctly preserves document/snapshot linkage, but is POI-only and Istanbul-only at input boundary |
| `place_embeddings` | Versioned `vector(64)` storage | `hash-v1` only; no multilingual embedding provider or semantic online query |
| `user_events`, `place_stats_daily` | Privacy-bounded POI interaction telemetry | No general retrieval trace, answerability, evidence fusion or support-coverage events |

No current table represents `geo_entities`, country aliases, travel jurisdictions, airport links,
domain support, source documents, generic evidence spans, facts, fact conflicts, generic knowledge
chunks or ingestion review tasks.

## Ingestion and publish paths

### POI import

`app/places/importer.py` performs the following for a requested catalog slug:

1. Builds a bounded Overpass query over named tourist categories for the configured bbox.
2. Persists raw JSON to `data/raw/<destination>/` with SHA-256 checksum.
3. Normalizes, maps a deliberately small OSM taxonomy and deterministically selects 100–300 POIs.
4. Upserts source identity by `source_id + external_id`; a conservative exact normalized-name plus
   120 m match is the only automatic merge.
5. Stores source payload and immutable source snapshot, rule-based tags/features and optional
   Commons image metadata.
6. Deactivates OSM records absent from a complete subsequent source snapshot.

`scripts/import_all_places.py` is generic over all 26 Python catalog records, but it fetches
external data and its reports are not checked in. Its existence is therefore not evidence that any
non-Istanbul destination is published or evaluated. The legacy
`scripts/import_istanbul_places.py` and `fetch_istanbul_osm()` retain Istanbul-only compatibility
paths.

### Description import

`app/places/descriptions.py` only accepts reviewed local JSON. It validates a source usage policy,
records source snapshots, chunks text deterministically, and refuses a description without
permission to store, embed and display an attributed excerpt. This is a reusable legal boundary.
Its schema currently limits the manifest destination to `Literal["istanbul"]`; it cannot fill a
destination pack generically yet.

### Missing ingestion capabilities

There is no source registry review flow, source-document fetcher, raw object-storage abstraction,
generic parser, entity resolver beyond POI matching, fact extractor, conflict detector, publish
gate, support recalculation, or review queue. There are no cron/background tasks: imports are
operator-triggered scripts, which is appropriate before sources and refresh policies are chosen.

## Retrieval and vector storage

`PostgresPlacesRepository.search()` currently implements a transparent lexical/category/geospatial
baseline:

- destination slug and active lifecycle are mandatory;
- aliases use `place_names.normalized_name ILIKE`;
- Russian category hints and a small `AREA_HINTS` map add deterministic boosts;
- category diversity caps two results per category;
- response exposes component scores, source, freshness and optional licensed description.

The repository deliberately emits zero `semantic_place`, `semantic_description` and `semantic`
scores. Although the schema has HNSW pgvector indexes, neither `place_embeddings` nor
`place_description_chunks` is queried online. `inferred_area()` only knows Istanbul areas
(Sultanahmet, Galata/Karaköy, Bosphorus and Beşiktaş), and the default ranking label is
`istanbul-hybrid-v1`; both are product-visible Istanbul-specific assumptions.

The only checked-in retrieval benchmark is
`data/evals/istanbul_places_queries.json` with 40 Russian-language cases. The real PostgreSQL
integration test is optional and only searches Istanbul. There is no benchmark for a second,
contrasting destination, no answer-level benchmark and no citation validator.

## Subchat context and prompts

`POST /destination-chat` first resolves a card from the current LangGraph checkpoint. It does not
rerank. For questions matching a fixed Russian POI-marker list it calls
`search_destination_pois()` with the card's destination slug and a limit of five.

The model prompt receives:

- the current trip request with raw query omitted;
- the mutable serialized candidate/card, including legacy fixture estimates;
- `DestinationContext` planning brief;
- up to five canonical POIs with source and clipped licensed description excerpts;
- last 12 subthread messages and the latest question.

The prompt correctly prohibits inventing live prices, schedules, entry rules, POIs and areas, and
treats serialized data as untrusted. It has no `QuestionPlan`, domain router, `Answerability`,
evidence-pack type, source citation requirement or post-answer citation validation. The fallback
can still compose answers from card highlights when no POI catalog is available.

`DestinationContext` is Istanbul-specific for rich areas. Other 25 destinations are built by
combining a fixture candidate with one JSON guide, a synthetic centre/bbox area and two fixed
unknown warnings. This explains why the card can speak about Rhodes while the subchat cannot list
a deeper evidenced catalogue of Rhodes POIs.

## Istanbul-specific assumptions to remove or generalize

| Location | Assumption | Minimal replacement |
| --- | --- | --- |
| `app/places/context.py:ISTANBUL_CONTEXT` | Rich hard-coded areas, highlights and routes only for Istanbul | Data-backed destination knowledge pack with source/evidence links |
| `app/places/semantics.py:AREA_HINTS` | Area parsing works only for Istanbul | Resolve aliases against generic geo entities, then apply PostGIS relation/radius lookup |
| `PlaceSearchQuery` | `destination="istanbul"`, `ranking_version="istanbul-hybrid-v1"` | Required resolved destination ID and generic `places-lexical-v1` version |
| `DescriptionManifest` | `destination: Literal["istanbul"]` | Resolve any published destination through canonical geo ID and support gate |
| scripts/eval/test names | Only Istanbul query set and optional DB integration | Shared benchmark schema and at least Istanbul + Phuket/Kuala Lumpur before generic rollout |
| compatibility wrappers | `ISTANBUL_BBOX`, `fetch_istanbul_osm`, import target | Keep temporarily behind generic functions; remove after callers migrate |

## Provenance, freshness and safety gaps

Existing POI provenance must be retained, not overwritten. The next model must additionally make
these concepts explicit for country/destination/area knowledge:

- Source authority, terms, storage/derivative/embedding permissions and polling policy are not
  modeled generically.
- A source URL on a destination guide is not a source document, evidence span or verifiable claim.
- There is no shared fact with scope, validity period, confidence, verification state and conflict
  status.
- Mutable data (entry, live weather, current hours, availability, price and disruptions) have no
  provider/evidence path; they must remain `unknown` rather than become chunks.
- Current POI `freshness_at` is import/feature time, not proof of an open venue or current ticket
  price.

## Minimal migration plan

The lowest-risk route is an additive, ordered extension of the **existing** `migrations/places`
database. Do not rename the existing `destinations` or `sources` tables: POI importer and repository
depend on them. No new vector database, ORM, background worker or LLM ingestion path is needed for
this phase.

1. **ADR first.** Record that `geo_entities` is the new canonical identity layer, while the existing
   `destinations` table remains a POI retrieval scope during migration. It must also define the
   explicit bridge, source-registry relationship and the fact subject boundary.
2. **Canonical geography migration.** Add `geo_entities`, `geo_aliases` and `geo_relations` with
   typed entity/relationship checks, unique normalized aliases and PostGIS centroid/boundary indexes.
   Add nullable `destinations.geo_entity_id` with a unique index. Only the present 13/26 identity
   records may be seeded in a later dedicated migration; that bootstrap must not make them eligible
   for ranking or mark them FULL.
3. **Support matrix migration.** Add `destination_domain_support` keyed by destination
   `geo_entity_id` and a controlled domain/tier/freshness/completeness/source-quality contract.
   Use absent rows as `none` rather than treating them as full coverage. Keep display/ranking/subchat
   reads behind an additive adapter until the matrix has data.
4. **Generic provenance migration.** Add `source_registry` and `source_documents`; preserve current
   `sources` and link it later through an explicit one-to-one bridge, not duplicated URL strings.
   Store only permitted raw-storage references and hashes, never unreviewed page text.
5. **Facts and chunks migration.** Add `evidence_spans`, `knowledge_facts`, `fact_evidence`,
   `fact_conflicts` and `knowledge_chunks`. Facts carry scope/validity/confidence; chunks carry
   domain, source/evidence references, FTS and optional future vector. The first schema must keep
   generic destination/country/area facts separate from existing `places`; POI-specific facts can
   be bridged after an explicit subject model is approved.
6. **Migration tests before data.** Apply migrations to an empty PostGIS/pgvector database, rerun
   existing Istanbul importer and description-import tests, prove aliases resolve ambiguous names
   deterministically, and prove no source/knowledge row is publishable without required provenance.
7. **Only then use the schema.** Bootstrap existing identity, set conservative support rows, then
   prove the same generic retrieval path on Istanbul and Phuket or Kuala Lumpur. Wave 1 imports,
   source adapters, hybrid retrieval and subchat grounding come after that proof.

### Compatibility rules

- Existing POI SQL continues to join `places.destination_id → destinations.id` until all callers
  use the explicit `geo_entity_id` bridge.
- Existing `sources`/`place_source_records` remain the source of truth for imported POIs; migration
  must not copy payloads or silently assert a licence policy.
- `destination-guides.json` stays a clearly marked planning fallback until it is ingested through
  source documents/evidence or replaced by reviewed packs.
- `hash-v1` remains non-semantic; hybrid retrieval cannot be enabled just because the new chunk
  table has a vector column.
- Support status never improves ranking position. It can gate unsupported claims and surface a
  warning; factual evidence and user constraints decide suitability.

## Tests and operational checks currently present

| Test/check | Current assertion | Gap before global rollout |
| --- | --- | --- |
| `tests/unit/test_places.py` | deterministic import normalization, bounded scopes, basic category hints | No generic geography/alias/domain-support tests |
| `tests/unit/test_place_descriptions.py` | licence and description-manifest validation | Istanbul-only destination contract |
| `tests/unit/test_destination_pois.py` | POI lookup only for intent, explicit unavailable copy | No distinction between disabled storage and insufficient pack support |
| `tests/unit/test_destination_chat.py` | bounded context, unknown dynamic copy and POI prompt clipping | No answerability/citation/unsupported-question assertions |
| `tests/integration/test_places_api.py` | `503` without configured places DB | No support endpoint or partial metadata |
| `tests/integration/test_places_postgres.py` | optional Istanbul search with provenance | No migration round-trip or second-destination contract |
| `scripts/evaluate_istanbul_places.py` | 40 lexical retrieval cases | No portable benchmark dataset or answer evaluation |

## Explicit non-goals of the next increment

- No bulk import of 60 countries, 220 destinations or arbitrary web pages.
- No scraping Google Maps, Tripadvisor, Яндекс Карты or 2GIS.
- No new standalone vector database or RAG framework.
- No claim that static guide text is current entry, price, schedule, weather or availability evidence.
- No automatic upgrade of a destination's support tier based on the number of imported POIs.

## Decision needed before the first schema commit

The repository has enough information to begin the additive canonical-schema migration, but the
following decision must be recorded in a new ADR before it:

> `geo_entities` becomes the canonical identity source. Existing POI `destinations` and `sources`
> remain backward-compatible operational tables and are linked explicitly; they are not renamed or
> repurposed during the first migration.

This preserves the working Istanbul vertical slice while making the global model possible.

## Bootstrap status

The first implementation batch provides `app/data/countries.seed.json`: 60 sovereign-country
identities from the approved roadmap, with ISO codes and Russian/English/common aliases. The
operator command `make places-bootstrap-catalog` writes them as `draft` canonical entities and no
`destination_domain_support` rows. Therefore the bootstrap improves entity recognition only after
the database migration; it does not make a country a recommendation candidate or claim entry,
pricing, weather or POI coverage.
