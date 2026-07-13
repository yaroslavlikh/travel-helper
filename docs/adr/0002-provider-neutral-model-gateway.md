# ADR-0002: Provider-neutral model gateway

- Status: accepted
- Date: 2026-07-13

## Context

LLM provider/model будет выбран позже. Pipeline требует structured output, но не должен зависеть от provider-specific request/response types.

## Decision

Определить узкий application `ModelGateway`, создать единственный client instance в FastAPI lifespan и передавать его узлам через runtime context. Provider adapter и integration package выбираются после project eval. Gateway стандартизует structured output, timeout/retry, usage metadata и typed errors.

Первый provider adapter выбран в [ADR-0005](0005-gemini-flash-model-provider.md); это не меняет provider-neutral границу этого решения.

## Consequences

Модель можно менять без переписывания graph nodes. Provider-specific возможности доступны только через осознанное расширение contract. Появляется небольшой wrapper, который нужно держать действительно узким и не дублировать весь LangChain API.

## Rejected alternatives

- Импортировать конкретный provider SDK в каждом узле: высокая связанность и разрозненные retry/telemetry rules.
- Делать универсальный внутренний SDK на десятки методов: преждевременная абстракция.
- Создавать клиента на каждый вызов: лишние connections и сложнее lifecycle/testing.
