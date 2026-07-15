# Travel Choice Assistant

Evidence-first сервис для выбора направления путешествия по свободному запросу. Он не продаёт и не бронирует поездки: задача продукта — сократить выбор до прозрачного shortlist с допущениями, рисками и источниками.

## С чего начать

1. [Product brief](docs/product.md) — зачем существует продукт и что входит в MVP.
2. [Архитектура](docs/architecture.md) — компоненты, LangGraph pipeline и обработка отказов.
3. [Стек](docs/stack.md) — выбранные технологии и отложенные решения.
4. [AI-контракт](docs/ai-contract.md) — как подключается модель без привязки домена к провайдеру.
5. [План реализации](docs/implementation-plan.md) — последовательность vertical slices и критерии готовности.
6. [ADR](docs/adr/) — журнал архитектурных решений.
7. [Contributing](CONTRIBUTING.md) — Makefile-контракт, quality gates и правила коммитов.

Для AI-инструментов и новых участников краткая память проекта находится в [AGENTS.md](AGENTS.md).

## Быстрый старт

Нужны Python 3.12+ и `uv`. Если `uv` установлен как Python module, команды Makefile тоже его найдут.

```bash
cp .env.example .env
make bootstrap
make dev
```

После запуска интерфейс доступен по адресу `http://127.0.0.1:8000/`, а readiness — по адресу `http://127.0.0.1:8000/health`.

Все локальные quality gates запускаются одной командой:

```bash
make check
```

## Каталог мест: Стамбул

Первый live-срез — 100–300 туристических мест Стамбула. Это отдельная от SQLite-checkpoint
PostgreSQL/PostGIS/pgvector база: она хранит канонические места, source snapshots, лицензии,
детерминированные локальные embeddings и анонимные события ранжирования. Demo-карточки направлений
от этого каталога не зависят и не маскируются под live-результаты.

Для локального полного прогона нужен запущенный Docker Desktop:

```bash
make places-up
make places-migrate
make places-import-istanbul
make places-eval-istanbul
```

Импорт запрашивает ограниченный named-POI срез OpenStreetMap через Overpass, сохраняет неизменяемый
raw JSON в `data/raw/istanbul/` (игнорируется Git), нормализует его и публикует не более 300 записей.
Результат API доступен через `POST /places/search`; при не настроенной базе он возвращает честный
`503`, а не fixture. Набор из 30 регрессионных запросов лежит в
[`data/evals/istanbul_places_queries.json`](data/evals/istanbul_places_queries.json).

## Текущий статус

- Завершён Slice 0: FastAPI app, typed settings, startup lifecycle, provider-neutral `ModelGateway`, LangGraph workflow shell, `/health`, Dockerfile, Makefile и CI.
- Завершён Slice 1: typed `TravelRequest`, детерминированный demo-extractor, P0/P1/P2 rules и checkpointed `/recommend` clarification/resume.
- Завершён Slice 2: 26 явно помеченных demo fixtures по основным туристическим странам, auditable hard filters, JSON-конфигурация весов и детерминированный scoring с sources/risks.
- Завершён Slice 4: chat-first responsive UI, несколько локально сохранённых чатов, многораундовые уточнения и живая лента конкретных направлений.
- Вопросы и ответы остаются в transcript; критерии thread сохраняются в SQLite LangGraph checkpointer, а браузерное представление — в `localStorage`.
- Demo-карточки содержат реальные credited-фотографии, районы, достопримечательности и внешние переходы к поиску проживания, активностей и туров. Эти ссылки не подтверждают цену или наличие.
- Aviasales-ссылки формируются на backend и передают только маршрут через route page; даты пользователь выбирает у провайдера, а affiliate marker при наличии читается из `AVIASALES_MARKER`.
- Для AI extraction выбран Gemini 3.1 Flash-Lite через provider-neutral gateway; без ключа или при сбое development demo использует явно отмеченный deterministic fallback.
- Langfuse группирует все turns одного чата в session: каждый запрос/ответ — отдельный trace, Gemini — generation, graph stages и вопросы — дочерние spans. Без валидных credentials используется no-op exporter.
- Добавлен bounded Istanbul places pipeline: Postgres/PostGIS/pgvector schema, OSM provenance,
  snapshots, conservative entity resolution, embeddings `hash-v1`, hybrid retrieval и event storage.
  Для фактического наполнения требуется локально запущенный Docker daemon и доступ к Overpass.
- Режим без API-ключей — явный `demo`; `/health` возвращает `degraded`, а не имитирует live-провайдеры.
- Feedback хранится только в памяти процесса и предназначен для локальной отладки; перед публичным запуском нужен persistent storage.
- Следующий Slice: live search/weather/travel adapters и partial failure handling.
- Открыто: LLM для public beta, поисковые и travel API, production hosting.

## Текущая структура

```text
app/             FastAPI app, settings, workflow и application ports
tests/           unit и in-process integration tests
scripts/         offline project checks
docs/            продуктовые контракты и архитектурные решения
```
