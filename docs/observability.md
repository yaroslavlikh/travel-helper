# Observability and future Langfuse integration

Статус: boundary accepted; backend deferred.

## Цель

С первого vertical slice понимать, где pipeline потерял качество или время, но не блокировать запуск отсутствием Langfuse credentials.

## Инструментация по стадиям

Один root trace на `POST /recommend` или resume. Child observations соответствуют стабильным stage names:

- intent_detection;
- request_extraction;
- ambiguity_detection;
- clarification_generation;
- search_query_generation;
- каждый provider call;
- normalization/conflict_resolution;
- hard_filtering;
- scoring;
- recommendation_explanation.

Минимальные metadata: request_id, anonymous session_id, pipeline stage, prompt name/version/source, provider/model, latency, attempt, candidate counts, filtered count, outcome и normalized error type.

## Что не записывать

- API keys, authorization headers и database URLs;
- полный environment;
- raw provider payload без redaction;
- больше пользовательского текста, чем нужно для явно выбранной debugging policy;
- паспортные данные или другие случайно введённые sensitive values.

До public beta необходимо определить retention и sampling. В development можно логировать больше только при явном флаге.

## Port design

Бизнес-узел открывает span/generation через observability port и не импортирует Langfuse. Реализации:

- no-op — всегда доступна;
- structured logging — baseline;
- Langfuse — добавляется позже и не меняет graph nodes;
- test recorder — проверяет names, nesting и metadata без сети.

Langfuse adapter должен связывать prompt versions с generations и использовать один session ID для clarification/resume. Provider errors записываются как observations и одновременно превращаются в product event `provider_failed`.

## Product events

Отдельно от LLM traces хранятся минимальные anonymous events: session_started, query_submitted, clarification_requested, clarification_answered, recommendations_shown, source_opened, feedback_submitted, provider_failed.

Product analytics и Langfuse trace не заменяют друг друга: первое измеряет поведение продукта, второе — выполнение AI pipeline.

## Локальный режим и деградация

Если Langfuse не настроен или недоступен, запрос продолжает работать, а exporter failure попадает только в structured log/metric. Observability не находится на critical path ответа.

Официальные ссылки: [Langfuse integrations](https://langfuse.com/integrations), [observability overview](https://langfuse.com/docs/observability/overview), [prompt-to-trace links](https://langfuse.com/docs/prompt-management/features/link-to-traces).
