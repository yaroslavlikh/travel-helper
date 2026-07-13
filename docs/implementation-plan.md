# Implementation plan

Статус: proposed. Начинать только после согласования открытых решений, необходимых для соответствующего slice.

## Slice 0 — project skeleton

Результат: FastAPI app запускается, settings валидируются, resources создаются в lifespan, `GET /health` различает live/ready/demo. Есть lint/type/test commands и CI. Внешних вызовов нет.

## Slice 1 — clarification loop

Результат: query → typed TravelRequest → deterministic ambiguity rules → LangGraph interrupt → resume с answers. In-memory checkpointer в tests, SQLite local. AI client пока mock или выбранный provider после ADR.

Критические тесты: structured validation, P0/P1/P2, максимум три вопроса, отсутствие повторных вопросов, merge answers, resume same thread, idempotent replay.

## Slice 2 — deterministic recommendations in demo mode

Результат: явно маркированные fixtures → normalization → hard filters → scoring → 3–5 API recommendations. Это тестирует весь graph и UI, но не считается production search.

Критические тесты: filter reasons, weight sum, score determinism, missing-component policy, sort order, evidence retention.

## Slice 3 — live search and climate evidence

До начала выбирается general search provider и фиксируется ADR. Добавляются live candidate generation, real weather/climate source, timeouts, retries, concurrency budget, conflict resolution и partial status. Fixtures остаются только в demo/tests.

Критические тесты: mocked external APIs, one-provider failure, conflicts, official entry-source priority, no-network fallback semantics.

## Slice 4 — user-facing web UI

Результат: одна responsive страница с examples, staged loading, clarification, assumptions, 3–5 cards, expandable evidence и feedback. API и UI явно показывают demo/partial/freshness.

## Slice 5 — observability and public hardening

Langfuse adapter, prompt registry fallback, trace metadata, redaction, retention, rate limit, SSRF protections, deployment container, managed Postgres, smoke/eval suite.

## Решения перед стартом кода

Обязательны для Slice 0–1:

1. Утвердить LangGraph + модульный монолит baseline.
2. Выбрать первый LLM provider/model либо явно решить, что Slice 1 начинается на mock до короткого provider bake-off.
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
