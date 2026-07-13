# Travel Choice Assistant

Репозиторий находится на стадии проектирования: исполняемого кода пока нет. Сначала здесь фиксируются продуктовые границы, архитектура и решения, которые должны пережить смену LLM-провайдера и поисковых интеграций.

## С чего начать

1. [Product brief](docs/product.md) — зачем существует продукт и что входит в MVP.
2. [Архитектура](docs/architecture.md) — компоненты, LangGraph pipeline и обработка отказов.
3. [Стек](docs/stack.md) — выбранные технологии и отложенные решения.
4. [AI-контракт](docs/ai-contract.md) — как подключается модель без привязки домена к провайдеру.
5. [План реализации](docs/implementation-plan.md) — последовательность vertical slices и критерии готовности.
6. [ADR](docs/adr/) — журнал архитектурных решений.
7. [Contributing](CONTRIBUTING.md) — Makefile-контракт, quality gates и правила коммитов.

Для AI-инструментов и новых участников краткая память проекта находится в [AGENTS.md](AGENTS.md).

## Текущий статус

- Статус: `docs-first / pre-implementation`.
- Код: намеренно не начат.
- Зафиксировано: FastAPI, Pydantic v2, LangGraph как детерминированная state machine, provider-neutral AI gateway, Langfuse-ready observability.
- Открыто: конкретный LLM и его провайдер, поисковый API, production hosting.
