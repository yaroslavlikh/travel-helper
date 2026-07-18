# Technology stack

Статус: accepted baseline. Конкретные версии фиксируются `uv.lock`.

## Рекомендованный baseline

| Область | Выбор | Почему |
|---|---|---|
| Runtime | Python 3.12 | Зрелая совместимость библиотек и предсказуемый production runtime |
| Package/tooling | `uv` + `pyproject.toml` | Быстрая воспроизводимая установка, lock и единая точка команд |
| HTTP API | FastAPI | Async I/O, Pydantic-контракты, OpenAPI, простой lifespan |
| Validation/config | Pydantic v2 + pydantic-settings | Один типизированный контракт на границах и env configuration |
| Workflow | LangGraph `StateGraph` | Явное состояние, conditional edges, checkpoint/resume и interrupt |
| HTTP client | httpx | Async client, timeouts, transport mocking |
| Persistence | SQLite local/dev; PostgreSQL production | Простота локально, durable concurrent checkpointer и account storage публично |
| Optional identity | OpenID Connect authorization code + PKCE | Внешняя identity verification без хранения паролей в продукте |
| Frontend | HTML/CSS/vanilla JS | Достаточно для одной страницы без отдельной frontend platform |
| Tests | pytest, pytest-asyncio | Unit и network-independent in-process integration tests |
| Quality | Ruff + mypy | Форматирование/lint и строгая проверка типов без тяжёлого toolchain |
| Observability | structured logs + observability port; Langfuse adapter | Бизнес-код трассируется, но не зависит от наличия Langfuse |
| Packaging | Docker | Одинаковый runtime локально и на хостинге |

## Почему LangGraph подходит

Pipeline имеет настоящее состояние, ветвление, частичные отказы и human-in-the-loop pause/resume. Это сильнее обычной линейной service-функции, но не требует автономного агента. LangGraph предоставляет checkpoints, thread-level persistence и interrupts; `thread_id` становится техническим указателем на anonymous session. Официальная документация рекомендует durable checkpointer для production и отдельно предупреждает, что interrupt перезапускает узел с начала — поэтому side effects проектируются идемпотентно.

LangGraph не должен владеть доменной логикой. Extraction, ambiguity rules, filtering и scoring остаются обычными функциями/сервисами, которые вызываются узлами и тестируются вне графа.

Ссылки: [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

## LLM: Gemini 3.1 Flash-Lite через provider-neutral gateway

Для development MVP выбран официальный `google-genai` SDK и стабильная модель
`gemini-3.1-flash-lite`. Решение и privacy-ограничения free tier зафиксированы в
[ADR-0005](adr/0005-gemini-flash-model-provider.md).

Минимальный capability contract остаётся provider-neutral:

- structured output с проверкой Pydantic schema;
- async invocation;
- timeout/retry/cancellation;
- usage and latency metadata;
- prompt identity/version;
- возможность передать tracing context.

На старте приложения фабрика создаёт один model client/gateway и кладёт его в application resources. Graph nodes получают gateway через runtime context или dependency container. В graph state клиент не сохраняется.

Качество модели проверяется не общими benchmark scores, а eval dataset проекта: качество
extraction, precision P0, unsupported-fact rate, latency и стоимость. Имя модели, provider и
credentials задаются settings, поэтому следующая модель не требует менять domain contracts или
LangGraph topology.

LangChain `init_chat_model` может быть внутренним механизмом фабрики: он даёт единый интерфейс для разных провайдеров и structured output. Домен всё равно зависит от собственного узкого `ModelGateway`, чтобы provider-specific особенности не просочились по всему коду. См. [provider-agnostic model interface](https://docs.langchain.com/oss/python/concepts/providers-and-models).

## Persistence

- Unit tests: in-memory checkpointer.
- Local development: Async SQLite checkpointer.
- Public deployment: Async PostgreSQL checkpointer.
- Anonymous `session_id` маппится на LangGraph `thread_id`, но наружу не выдаются checkpoint IDs.
- Authenticated chat snapshots имеют server-side owner index; внешний OIDC token не хранится.
- Product events/feedback могут жить в той же PostgreSQL инсталляции, но в собственных таблицах.
- LangGraph не хранит long-term semantic memory. Bounded POI documents, chunks и их embeddings
  живут только в отдельном canonical places PostgreSQL с provenance, лицензией и freshness.

SQLite не рекомендуется для публичного многопроцессного deployment: ограничения конкурентной записи и локального диска усложнят эксплуатацию сильнее, чем маленький managed PostgreSQL.

## Langfuse-connected, но не Langfuse-dependent

Интерфейс observability имеет no-op backend и Langfuse adapter, который подключается environment configuration и отправляет root trace/spans/generations на тех же stage boundaries. При отсутствии credentials бизнес-пайплайн продолжает работать без изменения graph topology. См. [Langfuse integrations](https://langfuse.com/integrations) и [observability concepts](https://langfuse.com/docs/observability/overview).

## Что намеренно не добавляем

- Celery/Redis/queue до появления измеренной потребности в background jobs.
- ORM и миграционный framework до появления собственных бизнес-таблиц сложнее events/feedback.
- React/Next.js для единственной интерактивной страницы.
- Отдельную vector database и неограниченный web-RAG: bounded POI chunks использует уже имеющийся
  pgvector в canonical places PostgreSQL.
- Service container framework; достаточно FastAPI lifespan + typed resource container.
- Multi-agent framework. Один граф, узкие узлы и детерминированные ветки.

## Открытые решения

| Решение | Когда принять | Критерии |
|---|---|---|
| LLM provider/model для public beta | Перед public beta | Eval quality, structured output, latency, price, data policy |
| General search API | Перед search vertical slice | Геопокрытие, freshness, source URLs, ToS, цена, rate limits |
| Flight/hotel providers | После проверки general search | Доступность API и качество диапазонов |
| Hosting | Перед public beta | Managed Postgres, TLS, region, logs, predictable cost |
| Retention period | До сбора public events | Privacy, debugging need, стоимость |
