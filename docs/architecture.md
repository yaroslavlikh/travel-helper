# Architecture

Статус: proposed for MVP.

## Архитектурный стиль

Модульный монолит с одним FastAPI process и одним LangGraph workflow. Внутри — domain/application/provider boundaries. Это сохраняет заменяемость внешних интеграций без operational complexity микросервисов.

```mermaid
flowchart LR
    UI["Chat + live feed UI"] --> API["FastAPI API"]
    UI --> LOCAL["Local chat presentation cache"]
    UI --> AUTH["Optional OIDC login"]
    API --> GRAPH["LangGraph workflow"]
    API --> ACCOUNTS["Account chat repository"]
    GRAPH --> DOMAIN["Deterministic domain services"]
    GRAPH --> AI["ModelGateway"]
    GRAPH --> PROVIDERS["Search and travel provider ports"]
    API -. structured request .-> PRICING["Deterministic pricing core"]
    PRICING --> PRICEPORTS["Typed pricing provider ports"]
    GRAPH --> CP["LangGraph checkpointer"]
    API --> EVENTS["Anonymous events and feedback"]
    API --> PLACES["Places repository + destination context"]
    GRAPH -. spans .-> OBS["Observability port"]
    AI --> LLM["Gemini 3.1 Flash-Lite"]
    PROVIDERS --> WEB["External APIs and web sources"]
    CP --> DB["SQLite local / PostgreSQL prod"]
    ACCOUNTS --> ADB["SQLite local / PostgreSQL prod"]
    PLACES --> PG["PostgreSQL + PostGIS + pgvector"]
    OBS -. later .-> LF["Langfuse"]
```

Pricing — отдельный bounded context без зависимостей от LangGraph и LLM SDK. Он принимает уже
структурированный запрос, считает цельные date scenarios и immutable snapshot. До выбора
провайдеров этот модуль не подключён к карточкам и не создаёт модельные цены.

## Startup lifecycle

FastAPI lifespan создаёт и закрывает long-lived resources в определённом порядке:

1. validated settings;
2. shared async HTTP client with explicit timeouts;
3. checkpointer/database resources;
4. search/travel provider adapters;
5. one `ModelGateway` instance or explicit disabled/demo adapter;
6. observability adapter, initially no-op if unconfigured;
7. compiled graph using these ports.

API handler не собирает зависимости вручную и не создаёт клиентов на каждый запрос. Graph state не содержит сами resources — только сериализуемое состояние запроса.

## Graph state

State — versioned, JSON-serializable contract. Предполагаемые группы полей:

- identity: request_id, session_id/thread_id, state_schema_version;
- input: raw_query, clarification_answers;
- conversation: bounded query history, question history, destination subthreads и previous
  normalized request;
- intent: parsed TravelRequest, ambiguities, assumptions;
- search: generated queries, raw provider results, provider warnings;
- candidates: normalized candidates, evidence, conflicts;
- decision: rejected candidates/reasons, scoring weights, scored candidates;
- output: immutable recommendation snapshots for the current feed;
- output: response status, recommendations, warnings;
- operational: stage attempts and error codes, но не secrets и не live clients.

Большие полные документы не должны бесконтрольно копироваться в каждый checkpoint. В state хранятся нормализованные excerpts и IDs; raw payload при необходимости уходит в отдельное bounded storage.

## Workflow

```mermaid
flowchart TD
    START(["START"]) --> INTENT["detect_intent"]
    INTENT --> PARSE["extract_request"]
    PARSE --> AMBIG["detect_ambiguities"]
    AMBIG --> ROUTE{"Есть P0?"}
    ROUTE -->|Да| ASK["interrupt_for_clarification"]
    ASK --> MERGE["merge_answers"]
    MERGE --> AMBIG
    ROUTE -->|Нет| DEFAULTS["apply_explicit_defaults"]
    DEFAULTS --> QUERIES["generate_search_queries"]
    QUERIES --> SEARCH["collect_provider_evidence"]
    SEARCH --> NORMALIZE["normalize_and_resolve_conflicts"]
    NORMALIZE --> FILTER["apply_hard_filters"]
    FILTER --> SCORE["deterministic_scoring"]
    SCORE --> SELECT["select_top_candidates"]
    SELECT --> EXPLAIN["evidence_bounded_explanation"]
    EXPLAIN --> END(["END"])
```

Это не ReAct loop и не multi-agent graph. Conditional edges известны заранее. LLM используется только там, где нужен язык или structured extraction; filters, weights, calculations и final ordering выполняет Python.

## Clarification и resume

- P0 приводит к LangGraph `interrupt` с JSON-serializable массивом максимум из трёх вопросов.
- Клиент получает `needs_clarification` и сохраняет opaque session ID.
- Следующий API call возобновляет тот же `thread_id` с answers.
- Узел с interrupt не выполняет non-idempotent side effects до паузы: при resume LangGraph начинает узел заново.
- Ответы валидируются, merge не затирает исходно подтверждённые значения неявно, ambiguity detection запускается повторно.

## Graceful uncertainty

`origin_city` — единственный P0 для текущего flight-aware shortlist. Остальные отсутствующие поля
остаются в state как typed ambiguities с impact level и не вызывают `interrupt`. Узел ambiguity
detection вычисляет `planning_confidence` и выбирает один `next_best_question`; оба значения
детерминированы, сериализуемы и попадают в trace без raw user text. Клиент показывает вопрос только
текстом в чате. Ответ рассматривается как patch всей поездки: он может заполнить несколько typed
полей, включая точный межмесячный интервал, а не только поле заданного вопроса.

Scoring не заполняет неизвестные поля дефолтными числами. Как и прежде, unavailable component
исключается из опубликованной формулы с нормализацией оставшихся весов; planning confidence делает
границы такого результата видимыми отдельно от source confidence.

## Follow-up refinement

- Новый message в завершённом thread запускает новый graph turn с `previous_request`.
- Structured extraction возвращает только explicit patch и список явно снятых ограничений.
- Merge выполняется детерминированно; `null` в patch не удаляет подтверждённое значение.
- После merge повторно выполняются ambiguity detection и ranking.
- Graph checkpoint сохраняет bounded query/question history; UI transcript сохраняется локально и
  не передаётся модели целиком.

## Provider boundaries

Application ports: general search, flights, hotels, weather/climate, entry rules, reviews. Каждый адаптер возвращает не “готовую рекомендацию”, а typed result + evidence + freshness + confidence или typed failure.

Общие правила:

- total timeout budget ограничен на запрос и на provider;
- retry только для transient errors, с bounded exponential backoff и jitter;
- fan-out выполняется конкурентно там, где вызовы независимы;
- circuit breaker/queue не добавляются до измеренной необходимости;
- официальные источники имеют приоритет для entry rules;
- конфликт не замалчивается: обе evidence сохраняются, confidence снижается, появляется risk;
- provider failure превращается в warning/event и `partial`, если оставшихся данных достаточно.

Candidate generation в production начинается с поиска по ограничениям. Fixture dataset разрешён только в явно маркированном demo/test mode и никогда не маскируется под live data.

## Scoring boundary

Scoring получает только normalized candidate + TravelRequest + weight configuration. Базовые веса: budget 30, weather 20, entry 15, transport 15, preferences 15, evidence quality 5. Компоненты сначала оцениваются 0–100, затем агрегируются.

Если компонент неизвестен, значение не выдумывается. Точное правило перераспределения веса должно быть одним, документированным и покрытым тестами до реализации. Рекомендуемый вариант MVP: renormalize веса только по доступным компонентам и одновременно показывать completeness/confidence, чтобы высокий score на малом количестве данных не выглядел полноценным.

## API boundary

- `GET /health`: readiness и состояние настроенных adapters без secrets.
- `POST /recommend`: новый turn, clarification resume или refinement существующего thread;
  discriminated response `needs_clarification | completed | partial`.
- `POST /destination-chat`: bounded вопрос по карточке без автоматического изменения основной
  поездки; для POI-вопросов о Стамбуле добавляет до пяти результатов из канонического каталога с
  provenance и retrieval ID. Эти записи не подтверждают текущие часы работы, цены или доступность.
  Endpoint возвращает optional предложение отправить refinement в основной chat.
  Он читает сохранённый recommendation snapshot, а не запускает ranking заново.
- `POST /events/travel-link`: best-effort anonymous событие перехода к flight/hotel provider.
- `POST /places/search`: lexical/category/geospatial baseline только по опубликованному каноническому
  каталогу мест; hash-v1 не считается semantic retrieval;
  активное лицензированное описание возвращается только с provenance, freshness и source URL.
  При отсутствии базы endpoint честно возвращает `503` и не подменяет ответ demo fixture.
- `POST /events/place`: privacy-bounded impression/open/save/hide/select для последующей оценки
  ранжирования; raw текст запроса в это событие не записывается.
- `POST /feedback`: anonymous up/down и optional comment.
- `POST /auth/password/register`, `POST /auth/password/login`, `GET /auth/login`,
  `GET /auth/callback`, `POST /auth/logout`: optional email/password or OIDC login and opaque
  application session lifecycle.
- `/account/*`: current identity, owned chat list/create/import/update/delete and complete account-data
  deletion. Authenticated mutations require a session-bound CSRF token.
- Dev-only parse endpoint допускается только под config flag.

API schema не должен раскрывать внутренние LangGraph checkpoint payloads. Идемпотентность повторного resume обеспечивается request/operation ID.

## Security and privacy

- Anonymous random session IDs remain the default; optional accounts never block the guest flow.
- Account access uses an opaque HTTP-only application session and explicit chat ownership checks;
  `session_id` alone is not authorization.
- Existing anonymous chats are imported into new owned IDs only after explicit consent. Old anonymous
  checkpoints are not claimed by identifier.
- Raw query может содержать персональные данные, поэтому retention ограничивается и документируется до public beta.
- Secrets только в environment/secret manager, никогда в state, logs, prompts metadata или API responses.
- SSRF-safe URL fetching: allow only http/https, block private/link-local ranges, enforce size/time limits.
- Source excerpts считаются untrusted content; prompt-injection из найденных страниц не меняет системные правила или tools.
- Текст POI хранится и векторизуется только при явно записанном разрешении source; в prompt попадает
  clipped excerpt top-POI, а не raw document или весь каталог.
- Feedback comments ограничиваются по длине и очищаются для отображения.

## Deployment target

Один containerized web service + managed PostgreSQL. Static frontend отдаётся тем же приложением.
Local/dev thread state хранится в SQLite; канонический каталог мест всегда использует отдельный
PostgreSQL/PostGIS/pgvector store. Это
достаточно для первой сотни пользователей. Отдельный worker появляется только если измеренный
search latency потребует asynchronous jobs, которые переживают HTTP request.
