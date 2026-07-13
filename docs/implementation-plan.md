# Implementation plan

Статус: завершены Slice 0–2 и Slice 4; Slice 3 остаётся следующим продуктовым этапом, а Slice 5 частично реализован observability-адаптером.

## Slice 0 — project skeleton

Результат: FastAPI app запускается, settings валидируются, resources создаются в lifespan, `GET /health` различает live/ready/demo. Внешних вызовов нет.

Developer experience входит в slice, а не откладывается на потом:

- `uv` lock и воспроизводимый bootstrap;
- self-documenting `Makefile` с targets из `CONTRIBUTING.md`;
- Ruff formatting/lint, выбранный type checker и pytest;
- один немутирующий `make check` как локальный и CI quality gate;
- pre-commit только как удобный быстрый feedback, не как единственное место проверок;
- CI запускает те же make targets, что и разработчик локально.

Статус: completed. Реализованы typed settings, FastAPI lifespan, `/health`, no-op observability, disabled provider-neutral model gateway, compiled LangGraph shell, Dockerfile, `uv.lock`, Makefile, CI и offline tests.

## Slice 1 — clarification loop

Результат: query → typed TravelRequest → deterministic ambiguity rules → LangGraph interrupt → resume с answers. In-memory checkpointer в tests, SQLite local. AI client пока mock или выбранный provider после ADR.

Критические тесты: structured validation, P0/P1/P2, максимум три вопроса, отсутствие повторных вопросов, merge answers, resume same thread, idempotent replay.

Статус: completed. `POST /recommend` использует SQLite checkpoint локально и in-memory checkpoint в тестах, возвращает discriminated `needs_clarification`, `completed` или `partial`. Gemini 3.1 Flash-Lite используется как structured extractor, а детерминированный extractor сохраняется как явно отмеченный demo fallback. Несколько раундов вопросов merge-ятся без потери предыдущих ответов.

## Slice 2 — deterministic recommendations in demo mode

Результат: явно маркированные fixtures → normalization → hard filters → scoring → 3–5 API recommendations. Это тестирует весь graph и UI, но не считается production search.

Критические тесты: filter reasons, weight sum, score determinism, missing-component policy, sort order, evidence retention.

Статус: completed. В `DEMO_MODE=true` API возвращает 3–5 отсортированных fixture-рекомендаций с synthetic sources, явным warning и риском; при выключенном demo mode live pipeline пока возвращает `partial`.

## Slice 3 — live search and climate evidence

До начала выбирается general search provider и фиксируется ADR. Добавляются live candidate generation, real weather/climate source, timeouts, retries, concurrency budget, conflict resolution и partial status. Fixtures остаются только в demo/tests.

Критические тесты: mocked external APIs, one-provider failure, conflicts, official entry-source priority, no-network fallback semantics.

## Slice 4 — user-facing web UI

Результат: одна responsive страница с examples, staged loading, clarification, assumptions, 3–5 cards, expandable evidence и feedback. API и UI явно показывают demo/partial/freshness.

Статус: completed. Статический frontend отдаётся FastAPI по `/`. Chat-first UI поддерживает
несколько локально сохранённых threads, автоматически открытый первый chat, сохранённые вопросы,
refinement существующего TravelRequest и отдельную живую ленту с фотографиями, конкретными местами
и внешними navigation links. Desktop и mobile сценарии проверены в реальном браузере. `POST /feedback` принят для локальной продуктовой проверки, но
сохраняет события только в памяти процесса и не является production-хранилищем.

## Slice 5 — observability and public hardening

Langfuse adapter, prompt registry fallback, trace metadata, redaction, retention, rate limit, SSRF protections, deployment container, managed Postgres, smoke/eval suite.

## Решения перед стартом кода

Обязательны для Slice 0–1:

1. Утвердить LangGraph + модульный монолит baseline.
2. Перед public beta подтвердить Gemini 3.1 Flash-Lite на eval dataset и принять privacy/data-processing режим.
3. Утвердить Python 3.12 + uv.

Можно отложить до Slice 3:

- search/flight/hotel providers;
- hosting vendor;
- Langfuse cloud versus self-hosted.

## Definition of ready для public beta

- Eval dataset принят и имеет ожидаемые результаты, а не только свободные примеры.
- Для каждого важного поля определён источник authority и freshness policy.
- Зафиксированы retention/privacy правила.
- Настроен production checkpointer.
- Demo и live mode невозможно спутать в UI/API.
- Отказ AI, search, weather и observability проверен независимо.
