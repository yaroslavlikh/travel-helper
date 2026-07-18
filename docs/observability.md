# Observability and Langfuse integration

Статус: Langfuse adapter реализован для local/debug; no-op fallback остаётся default без credentials.

## Цель

С первого vertical slice понимать, где pipeline потерял качество или время, но не блокировать запуск отсутствием Langfuse credentials.

## Инструментация по стадиям

Один root trace на каждый `POST /recommend`, resume или `POST /destination-chat`. Все traces одной
поездки объединены общим Langfuse session, но сохраняют отдельные latency/error boundaries. В UI
они получают имена `Turn NN · initial request`, `Turn NN · clarification`,
`Turn NN · refinement` или `Turn NN · destination question · <place>`. Child observations
соответствуют стабильным stage names:

- `workflow.initialize_request`;
- request_extraction;
- ambiguity_detection;
- clarification_requested;
- Gemini generation (`parse_user_query`, `revise_user_query` или clarification extraction);
- search_query_generation;
- каждый provider call;
- normalization/conflict_resolution;
- hard_filtering;
- scoring;
- recommendation_explanation.
- destination_question_answering.

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
- Langfuse — SDK v4 adapter, не протекающий в domain code;
- test recorder — проверяет names, nesting и metadata без сети.

Langfuse adapter связывает каждый Gemini call с generation и использует один first-class session ID для initial request, clarification и refinement. Provider errors записываются как observations и одновременно превращаются в product event `provider_failed`.

## Product events

Отдельно от LLM traces хранятся минимальные anonymous events: session_started, query_submitted, clarification_requested, clarification_answered, recommendations_shown, source_opened, feedback_submitted, provider_failed.

Product analytics и Langfuse trace не заменяют друг друга: первое измеряет поведение продукта,
включая `travel_link_opened`, второе — выполнение AI pipeline.

## Текущая интеграция

При наличии `LANGFUSE_ENABLED=true`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` и `LANGFUSE_BASE_URL` приложение создаёт один Langfuse client на FastAPI lifespan. На startup выполняется `auth_check`; неверные credentials безопасно переводят adapter в no-op. При shutdown вызывается `shutdown()`.

Root observation называется `recommendation_pipeline` и охватывает полный turn до API response, включая scoring. `propagate_attributes(session_id=...)` группирует traces одного chat в Langfuse session. Root output всегда содержит outcome, question/recommendation counts, changed fields и planning-confidence band; `ambiguity_detection` дополнительно пишет field одного advisory `next_best_question`, но не raw текст пользователя. `clarification_requested` содержит только blocking question fields. Gemini generation хранит model, operation, validated schema и token usage, когда provider возвращает usage metadata.

`LANGFUSE_CAPTURE_CONTENT=false` по умолчанию скрывает raw query, answers, prompt и structured output. Для локальной отладки флаг можно явно включить; API keys и authorization headers не записываются в любом режиме. В development выполняется `flush()` после каждого root trace, поэтому ветка `needs_clarification` видна сразу.

## Локальный режим и деградация

Если Langfuse не настроен или credentials не проходят `auth_check`, запрос продолжает работать с no-op adapter. В production экспорт буферизован; синхронный development flush предназначен именно для отладки.

Официальные ссылки: [Langfuse sessions](https://langfuse.com/docs/observability/features/sessions), [data model](https://langfuse.com/docs/observability/data-model), [Python SDK v4 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4), [prompt-to-trace links](https://langfuse.com/docs/prompt-management/features/link-to-traces).
