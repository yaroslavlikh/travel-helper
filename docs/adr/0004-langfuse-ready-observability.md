# ADR-0004: Langfuse-ready observability port

- Status: accepted and implemented for local/debug
- Date: 2026-07-13

## Context

Langfuse желателен для prompt management, traces и eval analysis, но не обязан быть настроен на первом этапе. Его недоступность не должна ломать рекомендации.

## Decision

Использовать observability port со stable stage names, no-op реализацией и test recorder. Langfuse SDK v4 подключается отдельным adapter. Каждый HTTP turn создаёт root observation `recommendation_pipeline`; `session_id` чата передаётся через `propagate_attributes`, поэтому initial request, clarification и refinement становятся отдельными traces одной Langfuse session. Gemini-вызовы записываются typed `generation`, остальные этапы — spans.

В development root trace flush-ится после каждого turn, чтобы вопросы и ошибки сразу появлялись в UI Langfuse. Production сохраняет buffered export. Полный query/prompt записывается только при `LANGFUSE_CAPTURE_CONTENT=true`; credentials и provider payloads не трассируются.

## Consequences

Порт сохраняет vendor isolation и не получает secrets. Development flush немного увеличивает latency, но делает отладку детерминированной; production export остаётся вне critical path. До public beta нужны retention, sampling и redaction policy.

## Rejected alternatives

- Добавить tracing после MVP: придётся заново определять stage boundaries и prompt identity.
- Импортировать Langfuse SDK во всех узлах: тесная связанность и сложная деградация.
- Делать Langfuse обязательным runtime dependency: ухудшает local/demo reliability.
