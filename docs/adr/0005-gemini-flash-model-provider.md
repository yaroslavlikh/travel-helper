# ADR-0005: Gemini 3.1 Flash-Lite as the first LLM provider

- Status: accepted for development MVP
- Date: 2026-07-14

## Context

Диалоговый travel-assistant требует качественного русского structured extraction с низкой
задержкой. Архитектура уже отделяет конкретный SDK от LangGraph и домена через `ModelGateway`.
Для первого AI vertical slice доступен Gemini Developer API key, а выбранная модель должна
поддерживать Pydantic-compatible structured output и async invocation.

## Decision

Использовать официальный Python SDK `google-genai` и стабильную модель
`gemini-3.1-flash-lite` как первый development/MVP provider. Для structured extraction
используется `minimal` thinking, чтобы уменьшить задержку и расход free-квоты.

Provider, model и API key задаются environment variables. Ключ хранится только локально или в
secret manager. Gemini client создаётся один раз в FastAPI lifespan и закрывается при shutdown.
Graph и domain продолжают зависеть только от provider-neutral `ModelGateway`.

Первой AI-операцией становится `parse_user_query`. Она возвращает проверенный Pydantic patch;
детерминированные ambiguity rules, hard filters и scoring сохраняют authority. В demo mode
временная недоступность или невалидный ответ Gemini может привести к явно отмеченному
детерминированному fallback. Production mode не должен молча использовать такой fallback.

## Privacy limitation

Free tier Gemini Developer API может использовать отправленные данные для улучшения продуктов
Google. Поэтому free key разрешён для разработки и контролируемой MVP-отладки без чувствительных
данных, но не считается принятым privacy baseline публичного production. Перед public beta нужно
либо перейти на подходящий paid tier, либо отдельно принять provider/data-processing решение.

## Consequences

- Проект получает реальный async structured LLM path без зависимости домена от Gemini SDK.
- Стабильное имя модели фиксируется configuration default только в локальном setup, а не в
  business logic.
- Нужны typed provider errors, bounded timeout и тесты с mocked SDK boundary.
- Качество extraction проверяется на проектном eval dataset; смена модели не меняет графовый
  контракт.

## Rejected alternatives

- `gemini-flash-latest`: alias может переключиться на новую версию и ухудшить воспроизводимость.
- `gemini-3.5-flash`: выше latency на доступной free quota для короткого chat extraction.
- `gemini-2.5-flash`: больше не доступна новым пользователям Gemini API.
- Preview/experimental Flash: более короткое окно стабильности для первого публичного MVP.
- Прямые SDK-вызовы из LangGraph nodes: нарушают provider boundary и lifecycle клиента.
