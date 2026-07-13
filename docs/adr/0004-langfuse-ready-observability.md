# ADR-0004: Langfuse-ready observability port

- Status: proposed
- Date: 2026-07-13

## Context

Langfuse желателен для prompt management, traces и eval analysis, но не обязан быть настроен на первом этапе. Его недоступность не должна ломать рекомендации.

## Decision

Заложить observability port со stable stage names, no-op/logging реализациями и test recorder. Langfuse добавить отдельным adapter позже. Все операции несут request/session IDs, prompt name/version, provider/model, latency, counts, outcome и typed error metadata.

## Consequences

Instrumentation появляется сразу, а vendor integration можно отложить. Порт требует дисциплины, чтобы не превратиться в самодельную telemetry platform. Exporter всегда работает вне critical path и не получает secrets.

## Rejected alternatives

- Добавить tracing после MVP: придётся заново определять stage boundaries и prompt identity.
- Импортировать Langfuse SDK во всех узлах: тесная связанность и сложная деградация.
- Делать Langfuse обязательным runtime dependency: ухудшает local/demo reliability.
