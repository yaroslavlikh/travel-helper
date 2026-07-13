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

## Текущий статус

- Завершён Slice 0: FastAPI app, typed settings, startup lifecycle, provider-neutral `ModelGateway`, LangGraph workflow shell, `/health`, Dockerfile, Makefile и CI.
- Завершён Slice 1: typed `TravelRequest`, детерминированный demo-extractor, P0/P1/P2 rules и checkpointed `/recommend` clarification/resume.
- Завершён Slice 2: 11 явно помеченных demo fixtures, auditable hard filters, JSON-конфигурация весов и детерминированный scoring с sources/risks.
- Завершён Slice 4: responsive веб-интерфейс в бело-синей палитре, примеры запросов, уточняющие вопросы, карточки рекомендаций и anonymous feedback.
- Langfuse подключается через optional environment configuration; без credentials используется no-op exporter.
- Режим без API-ключей — явный `demo`; `/health` возвращает `degraded`, а не имитирует live-провайдеры.
- Feedback хранится только в памяти процесса и предназначен для локальной отладки; перед публичным запуском нужен persistent storage.
- Следующий Slice: live search/weather adapters и partial failure handling.
- Открыто: конкретный LLM и его провайдер, поисковый API, production hosting.

## Текущая структура

```text
app/             FastAPI app, settings, workflow и application ports
tests/           unit и in-process integration tests
scripts/         offline project checks
docs/            продуктовые контракты и архитектурные решения
```
