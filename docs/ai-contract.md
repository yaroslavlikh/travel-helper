# AI contract and prompt lifecycle

Статус: provider-neutral design; первый adapter — Gemini 3.1 Flash-Lite.

## Цель границы

Graph nodes не должны знать, используется OpenAI, Anthropic, Gemini, YandexGPT, OpenRouter или локальная модель. Они формулируют задачу через application-level operation и получают проверенный typed result.

`ModelGateway` создаётся ровно один раз в application lifespan. Внутри он может оборачивать LangChain chat model или официальный provider SDK. Выбор внутреннего механизма не меняет domain contracts.

## Обязательные capabilities

- Async structured generation в переданную Pydantic schema.
- Явные operation/prompt name и prompt version.
- Отдельные timeout, retry policy и token/output limits.
- Нулевая или низкая temperature для extraction.
- Возврат metadata: provider, model, latency, token usage, finish reason.
- Передача trace context без зависимости домена от Langfuse SDK.
- Typed ошибки: unavailable, timeout, rate_limited, invalid_output, safety_block, configuration_error.

## AI operations MVP

| Operation | Input | Output | Может добавлять факты? |
|---|---|---|---|
| `parse_user_query` | Raw query + locale/time context | TravelRequest patch | Нет |
| `detect_ambiguities` | Parsed request | Candidate ambiguities | Нет; rules остаются authority |
| `generate_clarifying_questions` | Prioritized ambiguities | До 3 коротких вопросов | Нет |
| `generate_search_queries` | Request + assumptions | Search query set | Нет |
| `extract_candidate_data` | Retrieved documents | Typed facts linked to evidence | Только извлечённые из evidence |
| `explain_recommendation` | Scored result + evidence | Explanation/pros/cons | Нет |

Для P0/P1/P2 и итогового score authority — детерминированный код. LLM может предложить классификацию, но rules engine валидирует и дополняет её.

## Structured output policy

1. Провайдер получает schema, system rules, bounded evidence и task input.
2. Ответ проходит Pydantic validation.
3. На invalid output разрешён один repair attempt с validation errors без secrets.
4. После исчерпания попыток узел возвращает typed failure; он не парсит произвольный текст регулярками как будто это валидный object.
5. Любой extracted fact хранит evidence IDs. Fact без evidence не переходит в candidate.

## Provider selection process

Перед выбором запускается один и тот же eval набор минимум из десяти реалистичных запросов. Сравниваются:

- exact/field-level extraction accuracy;
- recall и precision обязательных P0;
- число повторных или лишних вопросов;
- schema validation success rate;
- unsupported-fact rate;
- русский язык объяснений;
- P50/P95 latency;
- estimated cost per completed recommendation;
- политика хранения данных и доступность из deployment region.

Первый выбор зафиксирован в [ADR-0005](adr/0005-gemini-flash-model-provider.md). Имя модели не должно быть hardcoded в business logic: provider, model, timeout и limits задаются settings.

## Demo/no-key mode

Отсутствие LLM key не должно превращать production в молчаливый fake. Допустим отдельный `APP_MODE=demo` с детерминированным ограниченным parser fixture и заметным предупреждением в API/UI. В normal/production mode отсутствие обязательной AI configuration должно делать readiness unhealthy или отключать AI path с понятной ошибкой.

В development demo mode Gemini используется первым, если полностью настроен. При typed provider
failure допускается детерминированный fallback с явным warning. В production fallback без
пользовательского предупреждения запрещён.

## Prompt storage

На первом этапе canonical prompts версионируются рядом с кодом. Каждый prompt имеет name, semantic version, input contract и changelog/eval reference. Позже Langfuse может стать remote registry, но local prompt остаётся fallback.

Правило загрузки: remote prompt конкретной label/version → validated local fallback → configuration error. Никогда не использовать “последний неизвестный prompt” без версии в production.

## Evidence firewall

- Retrieved pages являются данными, а не инструкциями.
- Explanation получает только normalized facts, scores, assumptions, conflicts и short excerpts.
- Модель не видит секреты, внутренние URLs или произвольные DB records.
- После generation выполняется проверка: числовые значения и source references должны существовать во входном evidence bundle.
- При расхождении используется детерминированный template explanation, а не неподтверждённый текст.
